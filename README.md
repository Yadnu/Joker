# Jokebox

## 1. What this is

Jokebox is an AI stand-up comedian. It performs over live voice, records how each joke lands, files the result into a strict four-level taxonomy, and keeps a decision trace for every model call and routing choice so a reviewer can see why a bit was suggested, written, scored, classified, and stored.

The product is four components with a hard boundary between judgment and storage.

| Component | Owns |
|-----------|------|
| The Joker | The voice loop, joke generation, set construction, barge-in, and filing through the Box HTTP API |
| The Librarian | Pre-generation suggestions, genre assignment, reaction scoring, and the taxonomy. All judgment about what a joke *is* lives here |
| The Box | The archive API: hierarchy, upsert, validation, queries, accounts, traces, export. It holds **no** classification intelligence |
| The Viewer | The transparency layer. It renders the archive tree, every joke field, and the decision trace. It does not compute genres or scores |

The Box receives a path (`cabinet` / `drawer` / `file`) and trusts it. It does not infer a category, repair a path, or invent a "General" bucket. If the Librarian hands it a bad path, the Box stores that path. That split is deliberate: the archive can be audited, replaced, or pointed at another Box without moving the comedy brain.

## 2. Quick start

Verified on this machine: Python **3.14.3**, Node **v24.19.0**, npm **11.17.0**, Box on `http://127.0.0.1:8000`, Viewer on `http://localhost:3000`.

First install is not two minutes (venv, pip, npm). After those exist, start Box then Viewer and open the URLs below.

### Prerequisites

- Python 3.11 or later (this repo was run with 3.14.3)
- Node.js 18 or later (Viewer was run with v24.19.0)
- PostgreSQL, local or cloud (asyncpg DSN; Neon pooler works for the app)
- `OPENAI_API_KEY` for generation, suggestion, score, classify, metadata
- `ELEVENLABS_API_KEY` for the default voice provider
- `DATABASE_URL` and `TEST_DATABASE_URL` (pytest uses a separate database)

### Install

```bash
git clone https://github.com/cyrano-hiring/jokebox-yadneya-joshi.git
cd jokebox-yadneya-joshi
python -m venv env
```

Windows:

```bash
.\env\Scripts\activate
pip install -r requirements.txt
```

macOS / Linux:

```bash
source env/bin/activate
pip install -r requirements.txt
```

`pip install -r requirements.txt` was run in this repo: requirements already satisfied (FastAPI 0.141.1, SQLAlchemy 2.0.52, Alembic 1.19.1, Pydantic 2.13.5, uvicorn 0.52.4, openai 3.6.0).

Viewer:

```bash
cd viewer
npm install
```

`npm install` in `viewer/` completed: 112 packages, already up to date.

### Configure

```bash
cp .env.example .env
```

On Windows, `copy .env.example .env`. Edit `.env`. The file is gitignored. See `.env.example` for Neon `ssl=require` notes and optional model overrides.

Minimum for the Box plus Joker/Librarian:

```
DATABASE_URL=postgresql+asyncpg://USER:PASS@HOST/DB?ssl=require
TEST_DATABASE_URL=postgresql+asyncpg://USER:PASS@HOST/TESTDB?ssl=require
OPENAI_API_KEY=sk-your-openai-key
ELEVENLABS_API_KEY=sk_your-elevenlabs-key
BOX_API_KEY=jbx_YOUR_KEY_SHOWN_ONCE
```

`BOX_API_KEY` is the Joker write key (section 3). Viewer:

```bash
cd viewer
cp .env.local.example .env.local
```

Default: `NEXT_PUBLIC_BOX_URL=http://localhost:8000`.

### Migrate

The repo folder `alembic/` shadows the installed Alembic package if you run `python -m alembic` from the repo root. The command below was executed here and reached head (schema already applied):

```bash
python -c "from pathlib import Path; import sys; root=Path('.').resolve(); sys.path=[p for p in sys.path if Path(p).resolve()!=root]; from alembic.config import main; sys.argv=['alembic','upgrade','head']; main()"
```

Idempotent.

### Seed (optional, empty database only)

```bash
python scripts/seed.py
```

On this database the command exited 1 with: `Account 'seed-account' already exists.` That is expected after the first seed. On a fresh database it files a sample tree and leaves `DarkHumor > Absurdist > Existential` with one joke so `GET /compliance` shows a real violation.

### Start the Box

```bash
uvicorn box.main:app --reload --port 8000
```

- API: http://127.0.0.1:8000
- Health (run just now): `GET /health` → `{"status":"ok"}`
- Interactive OpenAPI: http://127.0.0.1:8000/docs (`GET /docs` returned 200)

### Start the Viewer

From `viewer/` (not the repo root; there is no root `package.json`):

```bash
cd viewer
npm run dev
```

- Live show: http://localhost:3000 (`GET /` returned 200)
- Archive: http://localhost:3000/viewer (`GET /viewer` returned 200)

## 3. Accounts and API keys

Accounts name **who filed** a joke. They do **not** hide the library. Every account reads every joke.

### Create an account

```bash
curl -s -X POST http://127.0.0.1:8000/accounts \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"my-joker\"}"
```

Status **201**. Shape (`AccountCreateOut`):

```json
{
  "id": "<account-uuid>",
  "name": "my-joker",
  "api_key": "jbx_YOUR_KEY_SHOWN_ONCE",
  "created_at": "2026-09-02T00:00:00.000000"
}
```

The plaintext `api_key` is returned **once**. The Box stores only `sha256(api_key)`. Duplicate names return **409**. `GET /accounts` and `GET /accounts/{id}` never include the key.

### Header on writes

```
Authorization: Bearer jbx_YOUR_KEY_SHOWN_ONCE
```

Not an `X-API-Key` header. Writes (`PUT /box/upsert`, `PUT /jokes/{id}`) use `Depends(require_account)`. Reads are open. Why: accounts scope **identity and attribution**, not visibility. A reviewer with no key can still `GET /box` and `GET /jokes/{id}`.

`PUT /box/upsert` with no `Authorization` header returns **401** with a body naming the missing header. That was hit against this live Box.

### How the Joker authenticates

The Joker does not send `attribution.account` as truth. It sends `Authorization: Bearer` from `BOX_API_KEY` (`shared/box_client.py`, `joker/realtime.py`). On insert the Box sets `joke.account_id` to the resolved account and overwrites `attribution["account"]` with that account's **name**. A spoofed `attribution.account` in the body does not stick. Covered by `box/tests/test_auth.py`.

### What a reviewer should run

```bash
curl -s -X POST http://127.0.0.1:8000/accounts \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"reviewer\"}"
```

Copy `api_key`, then file one joke (section 7) with:

```bash
curl -s -X PUT http://127.0.0.1:8000/box/upsert \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer jbx_YOUR_KEY_SHOWN_ONCE" \
  -d @joke.json
```

Do not commit the key. Do not paste a real key into this README.

## 4. System design

### Hierarchy and compliance

Box > Cabinet > Drawer > File > Joke. Every level must contain **more than one** child. A cabinet with one drawer is a violation. A file with one joke is a violation.

`GET /compliance` recomputes that rule on every request from live counts. A stored `compliant` flag would go stale the moment the next joke was filed. There is no compliance column.

### Upsert

`PUT /box/upsert` creates cabinet, drawer, and file if missing, then inserts the joke. Inserts use PostgreSQL `ON CONFLICT DO NOTHING` on `(label)` for cabinets and `(parent_id, label)` for drawers and files, then `SELECT` the row. **One** `session.commit()` at the end (`box/router.py`). A failure before commit leaves no orphaned levels.

The code does **not** use `RETURNING` on those inserts. It is conflict-then-select, not lock-based.

### Concurrency

Two Librarians inventing the same path at once: unique constraints plus `ON CONFLICT DO NOTHING`, no `SERIALIZABLE`, no `FOR UPDATE`. The proof is `box/tests/test_concurrency.py` (`test_concurrent_upsert_same_path`): two real threads, one path, one cabinet/drawer/file, two jokes, neither request errors.

### Joke record (ten fields)

Field names are fixed in `box/schema/records.py`.

| Field | Purpose |
|-------|---------|
| `prompt_responses` | Ordered turns (`role` + `content`). The joke is the exchange that produced it, not a single string |
| `joke_text` | The line that was told |
| `user_reaction` | What the listener did, stored **apart** from the joke because it is a response to the joke, not part of it |
| `score` | Integer 0-10 from the Librarian rubric |
| `category` | Genre label assigned by the Librarian (must not be "General") |
| `metadata` | Topic, style, length, sensitivity flags, theme flags, tone level; optional `shape` and `critique` on newer rows |
| `user_context` | Light, non-identifying listener snapshot (age band, region, occupation field, preferences, energy) |
| `attribution` | `joker` plus `account` (account filled from the bearer, not the body) |
| `provenance` | `generated` or `curated`, model, prompt, selection rationale |
| `set_id` | `{ "set": "...", "position": n }` |

### Joker and Librarian contract

The typed contract is `librarian/interface.py` (version `1.0`). Facades: `suggest`, `classify`, `score`, `extract_metadata`.

- Librarian → Joker: ranked `Angle`s (genre, topic, rationale, freshness, tone) **before** generation; after a bit, a `ClassificationResponse` (category, `is_new`, justification, three-label path) and an integer score.
- Joker → Librarian: `SuggestionRequest` (listener context, history, taxonomy snapshot, preferred tone); `ClassificationRequest` (joke text, reaction, suggested path, snapshot).

The Librarian does not import `joker.*`. Box I/O from the Joker goes through `shared/box_client.py` (`BOX_BASE_URL`). Suggestion and taxonomy reads may use that client in-process. **Exception (not the intended seam):** `joker/generate.py` currently imports `librarian.critique` for few-shot shape names and room-feedback formatting. Classify still writes new File rows with SQL (`_create_category`) instead of HTTP.

### Voice loop

Default provider: **ElevenLabs Conversational AI** (`VOICE_PROVIDER=elevenlabs`). Fallback: OpenAI Realtime (`VOICE_PROVIDER=openai`). Browser PCM16 (24 kHz) rides `GET` upgrade `WS /ws/session/{session_id}`. The Box process bridges to the provider. Mic capture and speaker playback run concurrently (`asyncio.gather` of browser→voice and `vs.wait()`). The ElevenLabs session feeds input while output chunks arrive; that is the duplex path.

Barge-in: provider VAD fires; output is cancelled; the partial joke text is stored on the delivery trace; the host speaks an in-character ack from `prompts/realtime_ack_v1.txt`; the client gets `barge_in` and `barge_in_ack` events. The interrupted bit is still **filed as told**. The trace kind is `delivery` with `interrupted: true`, not a separate `barge_in` kind.

The WebSocket route is **not** listed in `/openapi.json`. HTTP routes are.

### Set construction

`joker/setbuilder.py` asks the model for ordered slots (opener, bits, callback, closer). Every non-final slot must include `transition_to_next` or validation fails. A set you could shuffle without losing those sentences is treated as a list, which is a construction failure.

When a bit scores **below 4** (`BOMB_THRESHOLD` in `joker/orchestrator.py`), `adapt_set` runs (skip to callback, self-deprecate, pivot, or end) and writes `kind=set_adaptation`.

Worked example from a real trace, `GET /traces/set_cfd2bb0b3634` (200, 5800 bytes). `kind=set_construction`, rationale: built a 5-slot set, recovery `self_deprecate`.

| Slot | Why the next slot follows |
|------|---------------------------|
| Opener | Talking vegetables prime absurd scenarios; next bit uses modern absurdity (influencers) |
| Bit 1 | Humanized broccoli leads to objects with human traits (superheroes in mundane items) |
| Bit 2 | People and objects overlap; callback combines the two |
| Callback | Characters return so the room feels a payoff before the closer |
| Closer | Last slot (transition may be empty) |

Recovery line on that set stays inside the vegetable theme and admits the miss.

### Trace layer

`shared/trace.py` `record_step` is keyword-only. `rationale` has **no default**. A model call that skips this module does not exist for grading.

New rows also copy a **turn** from a process-local context (`bind_turn`): `trigger_type` (`cold_open`, `user_request`, `set_continuation`, `reroll`, `barge_in_recovery`, `query_slot`), `trigger_text` (verbatim listener line, or null for cold open / set continuation), `turn_id`, `turn_index`. Historical rows stay **null**. Nothing is backfilled.

Traces persist on the Box. `GET /jokes/{joke_id}/trace` is joke-scoped. `GET /traces/{artifact_id}` is any artifact (joke, set, category, session). The Viewer Trace panel renders kind, actor, model, latency, and rationale, **grouped by turn** when those fields are present.

## 5. The Viewer

Client-only Next.js App Router. No `app/api` routes. No server actions for data. Fetches `NEXT_PUBLIC_BOX_URL`.

| Route | What you get |
|-------|----------------|
| http://localhost:3000 | Live show: mic, host, transcript, critic column. WebSocket to the Box |
| http://localhost:3000/viewer | Archive: tree, joke detail, trace, exports, Query Slot |
| http://localhost:3000/viewer?joke=`<id>` | Same archive, that joke selected |

- **Tree:** one `GET /box`. Counts on cabinets, drawers, files, jokes. Compliance marks on violating nodes; summary bar names how many and where (`GET /compliance`). The browse tree hides seed-script / RaceCab rows; the compliance bar does **not** hide them.
- **Joke detail:** one screen, no tabs: path, genre, `joke_text`, `prompt_responses`, score, `user_reaction`, set id and position, metadata (including tone, and `shape` / `critique` when stored), user_context, attribution, provenance. A “What prompted this” block repeats the turn trigger above the dialogue.
- **Trace:** steps for the selected joke (`GET /jokes/{id}/trace`), including rationale, grouped under turn headers (`cold_open`, `user_request`, …). Unrecorded historical steps render as an unrecorded group, not an error.
- There is **no** `GET /tree`. The tree is `GET /box`. OpenAPI lists HTTP routes; it does **not** list `WS /ws/session/{session_id}`.
- **Exports:** current joke JSON, current joke CSV, whole library JSON, whole library CSV (`GET /export` for the library). Nested fields in CSV are JSON strings.
- **Query Slot:** on `/viewer`, a mic control that opens a voice session. You speak; audio and transcript come back; a filed joke id on `librarian_step` selects that joke (and its trace) without leaving the page. A session that never files a Box UUID will not open a trace. Treat a live Query Slot pass as part of the demo, not as something this README can guarantee from a curl.

## 6. Models and why

Defaults are in `shared/models.py`. Any name can be overridden by an environment variable of the same name. This machine may pin `GENERATE_GOOD=gpt-4o` in `.env`; the **code** default for good generation and classify is `o3`.

| Component | Default model | Why |
|-----------|---------------|-----|
| Librarian.classify | `o3` | Taxonomy is permanent; higher reasoning cost is accepted |
| Joker.generate (good) | `o3` | Comedy quality is the product |
| Joker.generate (bad) | `gpt-4o-mini` | Deliberate weaker path; must not silently upgrade |
| Joker.setbuilder | `o3` | Slot order and transitions need planning |
| Librarian.suggest | `gpt-4o-mini` | Rank angles; cheap and frequent |
| Librarian.score | `gpt-4o-mini` | Rubric JSON; fast |
| Librarian.metadata | `gpt-4o-mini` | Tags only |
| Voice (default) | ElevenLabs Conversational AI, voice **Charlie** (`IKne3meq5aSn9XLyUdCD`) | Full-duplex agent, VAD, tools; host register is casual US male |
| Voice (fallback) | OpenAI Realtime `gpt-realtime-2.1` | `VOICE_PROVIDER=openai` |

Full topography, including rows we **did** and **did not** measure: `docs/TOPOGRAPHY.md`.

Measured on live sessions (model/HTTP stages, not TTS): generation often ~1.2-2.5s p50; suggestion ~5-7s; classification ~7-10s; scoring ~1.2-1.8s; filing ~1.2-2.5s. **`tts_first_byte` is recorded as 0** in that file because the tracker currently writes zero on delivery start. A live show log on this machine recorded `[timing] first_audio_byte +8081ms` from WebSocket accept, which is **not** click-to-first-byte. Do not treat the zeros as latency.

Comedy prompts: few-shot shapes in `prompts/shapes_v1.md` (also appended on `persona.md` / `persona_v4.md`). Score rubric **1.1** is stored on scoring traces as `inputs.rubric_version`. Classify writes a `critique` mechanism sentence onto `metadata.critique`. Session `critique_buffer` is fed back into generate and suggest.

## 7. API reference

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Process up |
| POST | `/accounts` | Create account; returns `api_key` once |
| GET | `/accounts` | List accounts (no keys) |
| GET | `/accounts/{account_id}` | One account (no key) |
| PUT | `/box/upsert` | File a joke; create missing path; bearer required |
| GET | `/box` | Full tree |
| GET | `/box/{cabinet}/{drawer}/{file}` | Jokes at a path |
| GET | `/cabinets` | All cabinets |
| GET | `/cabinets/{cabinet_id}` | Cabinet plus drawers |
| GET | `/cabinets/{cabinet_id}/counts` | Counts under a cabinet |
| GET | `/drawers` | All drawers |
| GET | `/drawers/{drawer_id}` | Drawer plus files |
| GET | `/drawers/{drawer_id}/counts` | Counts under a drawer |
| GET | `/files/{file_id}` | File plus jokes |
| GET | `/files/{file_id}/counts` | Joke count in a file |
| GET | `/jokes/top` | High scores |
| GET | `/jokes/{joke_id}` | One joke |
| PUT | `/jokes/{joke_id}` | Patch a stored joke; bearer required |
| GET | `/jokes/{joke_id}/trace` | Trace steps for that joke |
| GET | `/traces/{artifact_id}` | Trace steps for any artifact |
| GET | `/genres/coverage` | Per-genre counts |
| GET | `/genres/{genre}/funniest` | Top-n in a genre |
| GET | `/export` | Full library JSON |
| GET | `/compliance` | Live hierarchy violations |
| GET | `/counts` | Cabinets, drawers, files, jokes |
| POST | `/joker/reroll` | Darker replacement (or ceiling refusal) |
| WS | `/ws/session/{session_id}` | Full-duplex voice (not in OpenAPI) |

Live reads this session (Box on `127.0.0.1:8000`, 2026-09-03):

| Request | Result |
|---------|--------|
| `GET /health` | 200 `{"status":"ok"}` |
| `GET /counts` | 200 `{"cabinets":3,"drawers":6,"files":19,"jokes":86}` |
| `GET /compliance` | 200, `compliant: false`, **4** file-level violations (listed in section 9) |
| `GET /docs` | 200, 1006 bytes |
| `GET /openapi.json` | 200, 33487 bytes; paths include `/box`, `/traces/{artifact_id}`, `/joker/reroll`; **no** `/tree` |
| `GET /accounts` | 200, 23 accounts, **no** `api_key` fields |
| `GET /export` | 200, **230150** bytes |
| `GET /jokes/e14feb8f-ed39-4ee9-af81-b34934f1f12d` | 200, 3628 bytes |
| `GET /jokes/…/trace` (same id) | 200, 20335 bytes |
| `GET /traces/set_897ff40d3d17` | 200, 6672 bytes |

### Worked example

**1. Create an account** (command in section 3). Expected 201 shape above. `box/tests/test_accounts.py` asserts `api_key` starts with `jbx_`.

**2. File a joke** with all ten fields. Validated with `JokeRecord.model_validate` against current `records.py`. Replace the bearer token.

```bash
curl -s -X PUT http://127.0.0.1:8000/box/upsert \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer jbx_YOUR_KEY_SHOWN_ONCE" \
  -d "{
  \"cabinet\": \"Wordplay\",
  \"drawer\": \"Puns\",
  \"file\": \"Animals\",
  \"joke\": {
    \"prompt_responses\": [
      {\"role\": \"system\", \"content\": \"You are a stand-up comedian.\"},
      {\"role\": \"user\", \"content\": \"Tell me a short pun about animals and GPS.\"},
      {\"role\": \"assistant\", \"content\": \"I told my GPS I was lost. It said that makes two of us, then rerouted me through a roundabout it also did not understand.\"}
    ],
    \"joke_text\": \"I told my GPS I was lost. It said that makes two of us, then rerouted me through a roundabout it also did not understand.\",
    \"user_reaction\": \"A real laugh, then they repeated the roundabout line.\",
    \"score\": 7,
    \"category\": \"Animals\",
    \"metadata\": {
      \"topic\": \"GPS and animals\",
      \"style\": \"one-liner\",
      \"length\": \"short\",
      \"sensitivity_flags\": [],
      \"theme_flags\": [\"failure\"],
      \"tone_level\": 1
    },
    \"user_context\": {
      \"age_band\": \"25_40\",
      \"region\": \"US West\",
      \"occupation_field\": \"tech\",
      \"humor_preferences\": [\"wordplay\", \"observational\"],
      \"humor_avoid\": [],
      \"energy\": \"dry\",
      \"first_time\": true,
      \"session_notes\": \"README worked example\"
    },
    \"attribution\": {
      \"joker\": \"joker-v1\",
      \"account\": \"spoofed-should-not-stick\"
    },
    \"provenance\": {
      \"source\": \"generated\",
      \"model\": \"gpt-4o\",
      \"prompt\": \"Tell me a short pun about animals and GPS.\",
      \"selection_rationale\": \"Worked example for the README.\"
    },
    \"set_id\": {\"set\": \"readme-example-set\", \"position\": 1}
  }
}"
```

Expected **201**:

```json
{
  "joke_id": "<joke-uuid>",
  "cabinet_id": "<cabinet-uuid>",
  "drawer_id": "<drawer-uuid>",
  "file_id": "<file-uuid>"
}
```

**3. Read it back**

```bash
curl -s http://127.0.0.1:8000/jokes/<joke-uuid>
```

Expected **200**. Top-level keys match a live `GET /jokes/{id}` on this Box: `id`, `file_id`, `account_id`, plus the ten record fields. `attribution.account` is the **account name from the bearer**, not `spoofed-should-not-stick`. Round-trip of those fields is what `box/tests/test_write.py` asserts.

Live GET example (real generated row, not the curl above): `GET /jokes/e14feb8f-ed39-4ee9-af81-b34934f1f12d` returned 200, 3628 bytes. Keys: `id`, `file_id`, `account_id`, plus the ten record fields. `attribution.account` = `YAJ` (bearer account name). `joke_text` is a generated line; `provenance.source` = `generated`; `metadata.shape` = `misdirect`; `metadata.critique` is populated; `user_context` age/region/energy are **null** (empty listener snapshot). `category` on this row is the path string `Observational > Social > Restaurants`, not only the file label.

## 8. Tests

```bash
python -m pytest -q
```

Run on this machine (2026-09-03): **109 passed, 1 failed** in 73.54s.

The failure is `box/tests/test_joker_realtime.py::test_barge_in_cancels_and_traces`, which still asserts the retired OpenAI Realtime snapshot `gpt-4o-realtime-preview-2024-12-17`. Default voice traces `elevenlabs-convai`. Cancel, ack, and `interrupted: true` are still asserted.

| File | What it proves |
|------|----------------|
| `test_write.py` | Write then read; all ten fields round-trip |
| `test_upsert_creates_levels.py` | One write creates missing cabinet/drawer/file; second write reuses ids |
| `test_read.py` | Read by id and by path; 404 names the missing level; export |
| `test_count.py` | Counts match a known tree |
| `test_funniest_in_genre.py` | `GET /genres/{genre}/funniest` |
| `test_structural_validation.py` | Compliance at cabinet, drawer, and file |
| `test_concurrency.py` | Two threads, same path, no duplicate levels |
| `test_auth.py` | Bearer on writes; attribution from account; reads open |
| `test_accounts.py` | Create, 409, no key on GET, global visibility |
| `test_trace.py` / `test_trace_turns.py` / `test_router_traces.py` | `record_step`, turn/trigger copy, HTTP trace reads |
| `test_librarian_*.py` | suggest / classify / score / interface |
| `test_joker_*.py` | generate, setbuilder, tools, stalls, fresh bit, orchestrator, latency, box client |
| `test_joker_realtime.py` | Barge-in cancel + trace (currently fails on model string) |

## 9. Current state

**Works**

- Four-level Box, upsert in one transaction, live compliance, open reads, bearer writes
- Tree, joke detail, trace panel, four export buttons, live show at `/`
- Separate suggest / generate / score / classify (and metadata) model calls
- Set construction with stored transitions; bomb path calls `adapt_set`
- Traces with required rationales, persisted, readable over HTTP; new steps carry turn/trigger fields
- ElevenLabs duplex session plus tools (`funniest_in_genre`, `write_fresh_bit`)
- Tags `milestone-1` and `milestone-2` exist locally and on `origin`

**Partial**

- Query Slot is implemented on `/viewer`; it is not proven in this document by a live spoken round-trip
- `tts_first_byte` in `docs/TOPOGRAPHY.md` is 0; first audio from WS accept was logged at +8081ms on one session, not click-to-audio
- Barge-in is traced as `delivery`, not `kind=barge_in`; no `reroll` / `reroll_refused` rows in the live trace table at last audit
- Many generated jokes have empty `user_context` and score **0** until a reaction is scored
- `Joke.category` sometimes stores a path string rather than the file label
- Filed `set_id` values include bags `seed-set` and `restored-from-traces`; per-slot transitions live on `set_construction` traces
- Intended-bad generation exists in code; recent generation traces on this Box used `gpt-4o` (often `GENERATE_GOOD` in `.env`), not `o3`
- `docs/TOPOGRAPHY.md` is a latency table, not the full model/cost/set essay
- OpenAPI omits the WebSocket; there is no `/tree` path
- `joker/generate.py` imports `librarian.critique` (seam exception above)
- Pytest: **109 passed, 1 failed** (barge-in model string)

**Cut / not claimed**

- No committed raw audio (by design)
- Seed inflation is not used to hide a thin live archive

**Archive as of `GET /counts` and `GET /compliance` this session**

- 3 cabinets, 6 drawers, **19** files, **86** jokes
- **4 compliance violations**, all file-level. The number is **correct**. Do not weaken the checker.

| Path | Jokes |
|------|------:|
| `Observational > Everyday Life > Money & Finance` | 0 |
| `Observational > Everyday Life > Shopping & Retail` | 0 |
| `Observational > Everyday Life > Health & Medicine` | 0 |
| `DarkHumor > Absurdist > Existential` | 1 |

Split from a live SQL pass (not `GET /counts`): **62** `provenance.source=generated`, **24** `curated` / `set=seed-set`. Remaining generated rows include live `set_*` ids and some `restored-from-traces`. Git tags: `milestone-1`, `milestone-2`.

## 10. Project structure

```
box/                 FastAPI Box: router, schema, auth, tests
  main.py            App, CORS, include routers
  router.py          HTTP API
  schema/records.py  Ten joke fields (fixed names)
  schema/models.py   SQLAlchemy tables and unique constraints
joker/               Voice, generate, setbuilder, orchestrator, tools
  realtime.py        WebSocket voice session
  voice/             ElevenLabs + OpenAI VoiceSession
  generate.py        Two-path generation
  setbuilder.py      Ordered sets + recovery
  orchestrator.py    Suggest → set → generate → score → classify → file
librarian/           Suggestion, classify, score, metadata, interface.py
shared/              trace.py, box_client.py, models.py, db.py
prompts/             Versioned prompt files (prompt_ref points here)
viewer/              Next.js App Router client
docs/                DECISIONS.md, TOPOGRAPHY.md
scripts/seed.py      Sample archive for an empty database
alembic/             Migrations (folder name shadows the Alembic library)
```
