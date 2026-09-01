# Jokebox

An AI stand-up comedian that tells jokes over live voice, records how each one
lands, files them into a strict taxonomy, and can explain every decision it made.

---

## Quick start

### Prerequisites

- Python 3.11+
- A PostgreSQL database (Neon or local)
- An OpenAI API key

### 1 — Clone and install

```bash
git clone <repo-url>
cd Joker
python -m venv env
# Windows
.\env\Scripts\activate
# macOS / Linux
source env/bin/activate

pip install -r requirements.txt
```

### 2 — Configure environment

```bash
cp .env.example .env
# Edit .env and fill in DATABASE_URL, TEST_DATABASE_URL, OPENAI_API_KEY
```

The `DATABASE_URL` must be an asyncpg-compatible connection string:

```
DATABASE_URL=postgresql+asyncpg://user:pass@host/db?ssl=require
```

If you paste a Neon URL in the standard `postgresql://` format, the app
normalises it automatically at startup.

### 3 — Run migrations

```bash
alembic upgrade head
```

### 4 — Start the server

```bash
uvicorn box.main:app --reload
```

The API is available at **http://127.0.0.1:8000**.
Interactive docs: **http://127.0.0.1:8000/docs**

### 5 — Create your first account

`PUT /box/upsert` requires a bearer token.  Create an account to get one:

```bash
curl -X POST http://127.0.0.1:8000/accounts \
  -H "Content-Type: application/json" \
  -d '{"name": "my-joker"}'
```

```json
{
  "id": "...",
  "name": "my-joker",
  "api_key": "jbx_aBcDeFgH...",
  "created_at": "..."
}
```

**Copy `api_key` immediately — it is shown exactly once and never retrievable again.**
`GET /accounts` and `GET /accounts/{id}` will not include the key.
If you lose it, create a new account with a different name.

### 6 — File a joke

```bash
curl -X PUT http://127.0.0.1:8000/box/upsert \
  -H "Authorization: Bearer jbx_aBcDeFgH..." \
  -H "Content-Type: application/json" \
  -d '{ ... }'
```

### 7 — Run tests

```bash
python -m pytest -v
```

Tests use `TEST_DATABASE_URL` from `.env`.  Each test runs inside a transaction
that is rolled back, so the test database stays clean between runs.

---

## Authentication

Write routes require `Authorization: Bearer <key>`.  Read routes are open.

| Route | Auth required |
|-------|---------------|
| `POST /accounts` | No — this is the bootstrap step |
| `PUT /box/upsert` | Yes — `Bearer <key>` |
| All `GET` routes | No |

**Key lifecycle:**
- Generated as `jbx_<secrets.token_urlsafe(32)>` on account creation
- Only the `sha256` hash is stored; the plaintext is never persisted
- Returned once in the `POST /accounts` response — copy it immediately
- Validation: incoming bearer token is hashed and matched against the indexed `api_key_hash` column
- Lost key → create a new account; the old account's jokes remain attributed to it

**Attribution:** the `attribution.account` field on every stored joke is set from
the resolved bearer account, not from the request body, so it cannot be spoofed.

---

## API reference

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness check |

### Accounts

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/accounts` | None | Create a new account; returns plaintext key once |
| GET | `/accounts` | None | List all accounts (no keys returned) |
| GET | `/accounts/{id}` | None | Get account by id (no key returned) |

**Visibility is always global** — every account can read the entire library.
Accounts scope attribution only, never visibility.

### Library (write)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| PUT | `/box/upsert` | Bearer | File a joke; creates missing cabinet/drawer/file in one transaction |

### Library (read)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/box` | Full tree (cabinet → drawer → file → joke count) |
| GET | `/box/{cabinet}/{drawer}/{file}` | All jokes at a specific path |
| GET | `/export` | Full tree with every joke embedded |
| GET | `/cabinets` | List all cabinets |
| GET | `/cabinets/{id}` | Cabinet with its drawers |
| GET | `/cabinets/{id}/counts` | Drawer / file / joke counts under a cabinet |
| GET | `/drawers` | List all drawers (flat, across all cabinets; includes `cabinet_id`) |
| GET | `/drawers/{id}` | Drawer with its files |
| GET | `/drawers/{id}/counts` | File / joke counts under a drawer |
| GET | `/files/{id}` | File with its jokes |
| GET | `/files/{id}/counts` | Joke count in a file |
| GET | `/jokes/{id}` | Single joke by id |
| GET | `/jokes/{id}/trace` | Trace log for a joke |

### Discovery

| Method | Path | Description |
|--------|------|-------------|
| GET | `/genres/{genre}/funniest` | Top-n highest-scoring jokes in a genre (`?n=5`) |
| GET | `/counts` | Global counts: cabinets, drawers, files, jokes |
| GET | `/compliance` | Live hierarchy compliance check (> 1 child at every level) |

---

## Joke record fields

All ten fields are required on `PUT /box/upsert`.

| Field | Type | Notes |
|-------|------|-------|
| `prompt_responses` | `[{role, content}]` | Turn-by-turn exchange; supports multi-turn knock-knock structure |
| `joke_text` | `str` | Full joke as delivered |
| `user_reaction` | `str` | What the listener said after the punchline; stored separately from the joke |
| `score` | `int` 0–10 | Landing score |
| `category` | `str` | Genre label; must match the file label; never `"General"` |
| `metadata` | `{topic, style, length, sensitivity_flags}` | `sensitivity_flags` uses `HumorStyle` vocabulary |
| `user_context` | `UserContext` object | Per-session listener snapshot (see below) |
| `attribution` | `{joker, account}` | `joker` from caller; `account` overridden from bearer token |
| `provenance` | `{source, model, prompt, selection_rationale}` | `source` is `"generated"` or `"curated"` |
| `set_id` | `{set, position}` | Set name and position within it |

### UserContext

All fields optional — a session with only `energy` populated is valid.

| Field | Type | Values |
|-------|------|--------|
| `age_band` | enum | `under_25` · `25_40` · `40_60` · `over_60` |
| `region` | str | Coarse locale, e.g. `"US West"`, `"UK"`. **Not a city.** |
| `occupation_field` | enum | `tech` · `healthcare` · `education` · `trades` · `finance` · `student` · `retired` · `other` |
| `humor_preferences` | list[HumorStyle] | Styles the listener enjoys |
| `humor_avoid` | list[HumorStyle] | **Hard constraint** — never a soft preference |
| `energy` | enum | `warm` · `dry` · `rowdy` · `reserved` |
| `first_time` | bool | Whether this listener has heard this Joker before |
| `session_notes` | str | One short free-text line |

**HumorStyle vocabulary** (shared by `sensitivity_flags`, `humor_preferences`, `humor_avoid`):
`wordplay` · `observational` · `absurdist` · `deadpan` · `dark` · `physical` · `self_deprecating` · `topical`

**Never stored:** name, date of birth, exact age, email, employer, city, or any other identifying value.

---

## Database migrations

| Migration | Description |
|-----------|-------------|
| `001` | Initial schema — cabinets, drawers, files, jokes, traces |
| `002` | Add accounts table; `account_id` FK on jokes |
| `003` | Convert `jokes.user_context` from TEXT to JSONB |
| `004` | Add `api_key` column to accounts |
| `005` | Replace plaintext `api_key` with `api_key_hash` (sha256, indexed) |

---

## Architecture

```
box/          FastAPI app — stores what it is handed, no inference
librarian/    Classification intelligence — suggest, classify, score, metadata
joker/        Voice comedian — realtime, generate, setbuilder, tools, latency
shared/       db.py, trace.py, models.py — shared across all components
alembic/      Database migrations
docs/         DECISIONS.md, TOPOGRAPHY.md
```

**The Box never infers or repairs a path.**  All taxonomy intelligence lives
in the Librarian.  Every model call is recorded via `shared/trace.py`.

---

## Hierarchy rules

- Box > Cabinet > Drawer > File > Joke — four levels.
- Every level must have **more than one** child.  The `/compliance` endpoint
  detects violations at request time; nothing is stored as a flag.
- `ON CONFLICT DO NOTHING` on unique constraints ensures concurrent writes to the
  same path produce exactly one set of category levels.

---

## Tests

Eight test files, each asserting one named concern:

| File | What it covers |
|------|----------------|
| `test_write.py` | Round-trip of all ten joke record fields |
| `test_upsert_creates_levels.py` | Upsert creates missing levels; no duplicate levels on repeat writes |
| `test_read.py` | Read by id, by path, export, scoped counts |
| `test_count.py` | Global and per-cabinet counts |
| `test_funniest_in_genre.py` | Highest scorer, tie, empty genre |
| `test_structural_validation.py` | Compliance violations at all four levels |
| `test_concurrency.py` | Two real OS threads, same path, one category produced |
| `test_accounts.py` | Account creation, duplicate, list/get, attribution via bearer |
| `test_auth.py` | 401 no key, 401 bad key, 201 valid key, spoof prevention |
