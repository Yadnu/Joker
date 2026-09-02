# Jokebox -- The Box

## 1. What this is

The Box is the archive service for Jokebox. It stores jokes in a four-level
hierarchy (Cabinet > Drawer > File > Joke), enforces structural rules, and
answers queries. It is not a classifier. It receives a path and trusts it. All
judgment about what a joke is, which genre it belongs to, and how funny it
scored lives in the Librarian. That boundary is deliberate: the Box can be
audited, replaced, or scaled independently of the classification logic.

---

## 2. Quick start

### Prerequisites

- Python 3.11 or later (tested on 3.14.3)
- PostgreSQL -- local or cloud (tested on Neon; any asyncpg-compatible instance)
- OpenAI API key (the Joker and Librarian need it; the Box alone makes no model calls)

### Install

```bash
git clone https://github.com/cyrano-hiring/jokebox-yadneya-joshi.git
cd jokebox-yadneya-joshi
python -m venv env

# Windows
.\env\Scripts\activate
# macOS / Linux
source env/bin/activate

pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
```

Edit `.env`. The minimum required fields:

```
DATABASE_URL=postgresql+asyncpg://user:pass@host/db?ssl=require
TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host/testdb?ssl=require
OPENAI_API_KEY=sk-...
```

If you paste a standard `postgresql://` Neon URL the app normalises it to
asyncpg format at startup. See `.env.example` for Neon-specific notes and
optional model overrides.

### Migrate

```bash
alembic upgrade head
```

Idempotent. Safe to run on a database that already has the schema.

### Start

```bash
uvicorn box.main:app --reload
```

API: http://127.0.0.1:8000
Interactive spec: http://127.0.0.1:8000/docs

### Create an account

`PUT /box/upsert` requires a bearer token. Create one account to get a key:

```bash
curl -s -X POST http://127.0.0.1:8000/accounts \
  -H "Content-Type: application/json" \
  -d '{"name": "my-joker"}'
```

The response includes `"api_key": "jbx_..."`. Copy it immediately. It is shown
once and never stored in plaintext.

### Seed sample data

```bash
python scripts/seed.py
```

Files 22 jokes across 3 cabinets, 6 drawers, 11 files. Leaves one file
(`DarkHumor > Absurdist > Existential`) with a single joke so that
`GET /compliance` reports a real violation on a fresh install.

### Run tests

```bash
python -m pytest -q
```

Expected: **40 passed**

---

## 3. System design

### The hierarchy

The Box organises jokes in a four-level tree:

```
Box
  Cabinet  (e.g. "Observational")
    Drawer   (e.g. "Everyday Life")
      File     (e.g. "Work")
        Joke
```

Every level must contain more than one child. A cabinet with one drawer is
non-compliant. A file with one joke is non-compliant. Compliance is computed at
request time by `GET /compliance`, not stored as a flag. A stored flag goes
stale the moment the next write happens without updating it; a Box that cannot
tell you where it is violating the rule at the moment you ask is not finished.

### Upsert

One write can create an entire missing path. `PUT /box/upsert` accepts
`cabinet`, `drawer`, `file`, and a complete joke record. It resolves or creates
each level, then inserts the joke -- all inside a single database transaction.
If the joke insert fails after the cabinet, drawer, and file have been created,
the transaction rolls back and no orphaned levels are left behind.

### Concurrency

When two Librarians invent the same category at the same instant, a unique
constraint on `(cabinet_id, label)` at each level combined with
`INSERT ... ON CONFLICT DO NOTHING` means exactly one row is created and
neither request errors. There are no locks, no mutexes, no serialised write
queue. `test_concurrency.py` proves this: two real OS threads hit the same
cabinet/drawer/file path simultaneously against the real database, and the
result is one cabinet, one drawer, one file, and two distinct jokes.

### Multi-user model

Accounts identify who filed a joke. They scope attribution, not visibility. The
entire library is readable by anyone without credentials -- `GET /jokes/{id}`,
`GET /export`, and every other read route are open. The API key on
`PUT /box/upsert` determines which account name lands in `attribution.account`;
it cannot be supplied or overridden in the request body. This is attribution,
not access control: the goal is a trustworthy paper trail, not a private
library.

### The joke record

All ten fields are required on every write.

| Field | Purpose |
|---|---|
| `prompt_responses` | Ordered turn sequence (role/content pairs). A joke is the exchange that delivers it. A five-turn knock-knock structure fits natively. |
| `joke_text` | Full joke as delivered. Stored separately for search and display. |
| `user_reaction` | What the listener said after the punchline. Stored separately because it is the response to the joke, not part of it. |
| `score` | Integer 0-10. Assigned by the Librarian against a versioned rubric. |
| `category` | Genre label. Must match the file label. Never "General". |
| `metadata` | topic, style, length, and sensitivity_flags. |
| `user_context` | Per-session listener snapshot: age band, region, occupation, humor preferences, energy level. All fields optional. Non-identifying by design. |
| `attribution` | joker (which Joker instance) and account (resolved from the bearer token, not the body). |
| `provenance` | source (generated or curated), model, prompt, selection_rationale. |
| `set_id` | Which set and position within it. |

---

## 4. Technical choices

| Choice | Alternatives considered | Reason |
|---|---|---|
| PostgreSQL | SQLite, MySQL | JSONB columns for metadata and provenance; unique constraints plus ON CONFLICT for concurrent category creation; asyncpg driver for async I/O |
| FastAPI | Django, Flask | Async-first; native Pydantic v2 integration; auto-generated OpenAPI spec that is graded |
| SQLAlchemy 2.0 + Alembic | Raw asyncpg queries, Tortoise ORM | Type-safe ORM with async support; version-controlled reversible migrations |
| Pydantic v2 | dataclasses, attrs, marshmallow | Co-designed with FastAPI; strict field validation; `model_dump(mode="json")` for clean JSONB serialisation |

Full decision log with alternatives and costs: [docs/DECISIONS.md](docs/DECISIONS.md)

---

## 5. API reference

Full interactive spec with request/response schemas: http://127.0.0.1:8000/docs

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | /health | - | Liveness check |
| POST | /accounts | - | Create account; returns api_key once |
| GET | /accounts | - | List all accounts (no keys returned) |
| GET | /accounts/{id} | - | Get account by id |
| PUT | /box/upsert | Bearer | File a joke; creates missing levels in one transaction |
| GET | /box | - | Full tree with joke counts |
| GET | /box/{cabinet}/{drawer}/{file} | - | All jokes at a specific path |
| GET | /export | - | Full tree with every joke embedded |
| GET | /cabinets | - | List all cabinets |
| GET | /cabinets/{id} | - | Cabinet with its drawers |
| GET | /cabinets/{id}/counts | - | Drawer/file/joke counts under a cabinet |
| GET | /drawers | - | All drawers, flat list |
| GET | /drawers/{id} | - | Drawer with its files |
| GET | /drawers/{id}/counts | - | File/joke counts under a drawer |
| GET | /files/{id} | - | File with its jokes |
| GET | /files/{id}/counts | - | Joke count in a file |
| GET | /jokes/{id} | - | Single joke by id |
| GET | /jokes/{id}/trace | - | Trace log for a joke |
| GET | /genres/{genre}/funniest | - | Top-n highest-scoring jokes in a genre (?n=5) |
| GET | /counts | - | Global counts |
| GET | /compliance | - | Live hierarchy compliance check |

### Worked example

**Step 1 -- create an account**

```bash
curl -s -X POST http://127.0.0.1:8000/accounts \
  -H "Content-Type: application/json" \
  -d '{"name": "my-joker"}'
```

```json
{
  "id": "2c64f15c-d301-42b5-a23a-a510beacdde8",
  "name": "my-joker",
  "api_key": "jbx_...",
  "created_at": "2026-09-01T19:41:07.367441"
}
```

The `api_key` is shown exactly once. Store it now.

**Step 2 -- file a joke (replace `YOUR_API_KEY`)**

```bash
curl -s -X PUT http://127.0.0.1:8000/box/upsert \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
  "cabinet": "Observational",
  "drawer": "Everyday Life",
  "file": "Work",
  "joke": {
    "prompt_responses": [
      {"role": "system",    "content": "You are a stand-up comedian."},
      {"role": "user",      "content": "Tell me a work joke."},
      {"role": "assistant", "content": "Why do programmers prefer dark mode? Because light attracts bugs."}
    ],
    "joke_text":     "Why do programmers prefer dark mode? Because light attracts bugs.",
    "user_reaction": "Ha! That is actually true.",
    "score":         8,
    "category":      "Observational",
    "metadata": {
      "topic": "work",
      "style": "one-liner",
      "length": "short",
      "sensitivity_flags": []
    },
    "user_context": {
      "age_band":           "25_40",
      "occupation_field":   "tech",
      "humor_preferences":  ["observational", "deadpan"],
      "energy":             "dry",
      "first_time":         true
    },
    "attribution": {
      "joker":   "joker-v1",
      "account": "my-joker"
    },
    "provenance": {
      "source":              "generated",
      "model":               "gpt-4o",
      "prompt":              "Tell me a work joke.",
      "selection_rationale": "Best of three candidates by score."
    },
    "set_id": {"set": "evening-set-1", "position": 1}
  }
}'
```

```json
{
  "joke_id":    "7fe9d058-0d25-4887-bf90-e1fc20729754",
  "cabinet_id": "337df5e9-264f-4669-8a09-ecfede22c4bb",
  "drawer_id":  "...",
  "file_id":    "..."
}
```

**Step 3 -- read it back**

```bash
curl -s http://127.0.0.1:8000/jokes/7fe9d058-0d25-4887-bf90-e1fc20729754
```

Returns the full joke record with all ten fields. No auth required.

**Check compliance after seeding**

```bash
curl -s http://127.0.0.1:8000/compliance
```

Reports the `DarkHumor > Absurdist > Existential` file as a violation (1 joke).

---

## 6. Tests

```bash
python -m pytest -q   # 40 passed
```

| File | What it proves | Milestone 1 requirement |
|---|---|---|
| test_write.py | All ten fields survive a round-trip with correct types and values | Joke record |
| test_upsert_creates_levels.py | One write creates the full path; repeat writes do not duplicate levels | Upsert |
| test_read.py | Read by id, by path, export, and scoped counts all return correct data | API |
| test_count.py | Global counts and per-cabinet counts match seeded data | API |
| test_funniest_in_genre.py | Highest scorer returned; tie returns both; empty genre returns empty list | API |
| test_structural_validation.py | Compliance violations detected at all four levels; computed at request time | Validators |
| test_concurrency.py | Two OS threads, same path, one category row created, neither errors | Concurrency |
| test_accounts.py | Attribution stored from bearer token; key absent from list/get responses | Multi-user |
| test_auth.py | 401 on missing key, 401 on invalid key, 201 on valid key; body account cannot be spoofed | Authentication |

---

## 7. Project structure

```
box/
  main.py             FastAPI application entry point; loads .env
  router.py           All routes: upsert, read, compliance, funniest, export, accounts
  schema/
    models.py         SQLAlchemy ORM: Account, Cabinet, Drawer, File, Joke, Trace
    records.py        Pydantic models for the joke record and all sub-types
    responses.py      Pydantic response models for every endpoint

librarian/            Classification intelligence -- not part of the Box
  interface.py        The typed contract between Librarian and Joker
  suggest.py          Angle suggestion using listener context and archive coverage
  classify.py         Taxonomy placement: reuse an existing label or justify a new one
  score.py            Integer 0-10 score against a versioned rubric
  metadata.py         topic, style, length, sensitivity flags

joker/                Voice comedian -- not part of the Box
  realtime.py         Full-duplex voice over WebSocket (OpenAI Realtime API)
  generate.py         Two-model generation: frontier for good jokes, cheap for bad
  setbuilder.py       Ordered set with named slots and transition rationale
  tools.py            Box functions exposed to the voice model as callable tools
  latency.py          Stage timestamps; p50/p95 in docs/TOPOGRAPHY.md

shared/
  db.py               Async SQLAlchemy engine and session factory
  trace.py            record_step() -- every model call is recorded here
  models.py           Centralised model name registry with env-var overrides

alembic/
  versions/           Five migrations: 001 initial schema through 005 hashed api key

scripts/
  seed.py             Sample data loader; includes one deliberate compliance violation

docs/
  DECISIONS.md        Architecture decisions with alternatives and costs
  TOPOGRAPHY.md       Latency measurements: p50/p95 per pipeline stage
```
