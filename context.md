# Jokebox session handoff

Transfer document for the next agent or chat. Written 2026-09-01 after a short session whose only user request was **run the Box**, plus this handoff.

Repo: `C:\development\Joker`  
Remote: `github.com/cyrano-hiring/jokebox-yadneya-joshi`  
Branch: `master` at `8796de8` (`docs: rewrite README for Milestone 1 submission`), up to date with `origin/master`.  
OS: Windows 10, PowerShell. Python venv: `C:\development\Joker\env` (Python 3.14.3).

---

## What happened in this session

1. User: "run the box".
2. Agent tried `.\env\Scripts\python.exe -m uvicorn box.main:app --reload`.
3. That failed with `WinError 10013` (socket access forbidden). Port **8000 is already taken**.
4. Existing process (PID **61652**):

   ```
   C:\development\Joker\env\Scripts\python.exe
     C:\development\Joker\env\Scripts\uvicorn.exe box.main:app --port 8000
   ```

5. `GET http://127.0.0.1:8000/docs` returned **200**. The Box is already running. Do not start a second copy on 8000.
6. User asked to write everything about this into `context.md` (this file).

Nothing else was implemented, committed, or pushed in this session.

**Stale start command:** an older terminal used `uvicorn box.api.main:app`. That module path does not exist. Correct entrypoint is `box.main:app` (`box/main.py`).

**PowerShell note:** `curl` is aliased to `Invoke-WebRequest`. Use `curl.exe` or `Invoke-WebRequest` with `-UseBasicParsing`.

---

## What this product is

Jokebox is an AI stand-up comedian that tells jokes over live voice, records how each one lands, files them into a strict taxonomy, and can explain every decision.

Three packages, one FastAPI process:

| Package | Role |
|---------|------|
| **Box** (`box/`) | Archive. Stores what it is handed. Does not infer, default, or repair paths. |
| **Librarian** (`librarian/`) | Classification intelligence: suggest, classify, score, metadata. |
| **Joker** (`joker/`) | Generation, set building, live voice, filing via HTTP upsert. |

Frontend is Next.js App Router, client-only. No Next server components for data, no server actions, no Next API routes. There is exactly one backend: FastAPI.

---

## Non-negotiable constraints (from AGENTS.md)

- Hierarchy is **Box > Cabinet > Drawer > File > Joke**. Every level must contain **MORE THAN ONE** child. Never create a singleton to make a test pass.
- Every joke record requires **provenance**: generated or curated, which model, which prompt, selection rationale. No exceptions.
- No `"General"` category and no catch-all. Every joke goes into a real, specific genre.
- Field names in `box/schema/records.py` are **fixed**. Do not rename, pluralize, or paraphrase them. They are graded.
- The Box stores what it is handed. All classification intelligence lives in the Librarian.
- Any model call not recorded via `shared/trace.py` **does not exist** for grading.

Working agreement:

- After any non-obvious design decision, append a dated entry to `docs/DECISIONS.md` (Decision / Alternatives / Reason / Cost).
- Commit after each working slice with a message that states what and why. Never `"wip"` or `"fixes"`.
- Never commit API keys, `.env`, or raw audio.
- **Do not commit unless the user asks.** This session did not ask to commit.

---

## How to run the Box

```bash
cd C:\development\Joker
.\env\Scripts\activate
uvicorn box.main:app --reload
```

- API: http://127.0.0.1:8000
- Interactive spec: http://127.0.0.1:8000/docs
- Voice WebSocket: `ws://127.0.0.1:8000/ws/session/{session_id}` (mounted from `joker/realtime.py`)

`box/main.py` loads `.env` from the repo root (`load_dotenv(..., override=True)`) then includes:

- `box.router.router` — HTTP archive API
- `joker.realtime.router` — live voice WebSocket

Required env (do not put secrets in this file):

- `DATABASE_URL` — `postgresql+asyncpg://...` (Neon URLs are normalized at startup)
- `TEST_DATABASE_URL` — used by pytest
- `OPENAI_API_KEY` — Joker and Librarian; Box HTTP alone makes no model calls

Migrations: `alembic upgrade head`  
Seed: `python scripts/seed.py` (22 jokes; leaves one deliberate singleton so `/compliance` reports a violation)  
Tests: `python -m pytest -q`  
README still says expected **40 passed**; that number is for committed Milestone 1. Uncommitted tests in this working tree are additional.

`PUT /box/upsert` needs a bearer token. Create one:

```bash
curl.exe -s -X POST http://127.0.0.1:8000/accounts `
  -H "Content-Type: application/json" `
  -d "{\"name\": \"my-joker\"}"
```

Response includes `"api_key": "jbx_..."` once. Stored as sha256 hash; plaintext is not recoverable.

---

## Architecture that the next agent must not break

**Box vs Librarian.** Box does not classify. Caller supplies `cabinet` / `drawer` / `file`. Upsert is one transaction across all four levels. Concurrent category creation uses `ON CONFLICT DO NOTHING RETURNING`.

**Compliance** is a live query (`GET /compliance`), never a stored flag. Checks: every cabinet has >1 drawer, every drawer >1 file, every file >1 joke.

**Auth.** Bearer on write only (`PUT /box/upsert`). Reads are open. Accounts scope attribution, not visibility. `attribution.account` comes from the token, not the body.

**Librarian reads DB directly** (same process, `AsyncSession`). **Joker files through HTTP** `PUT /box/upsert` via `joker/box_client.py`. Do not invert that.

**Joker/Librarian seam.** Typed contract is `librarian/interface.py` (`SuggestionRequest`/`Response`, `ClassificationRequest`/`Response`, `INTERFACE_VERSION`). Joker must not import Librarian internals; Librarian must not import `joker.*`.

**Live pipeline** (`joker/orchestrator.py` is the glue `realtime.py` calls):

1. `start_session()` → `librarian.suggest.suggest()` → `joker.setbuilder.build_set()` → trace `placement`
2. `generate_slot()` → `joker.generate.generate()` (at least one `"bad"` slot per set)
3. On `speech_stopped`: `process_reaction()` → score → classify → extract_metadata → `box_client.upsert_joke` (trace `filing`). Score < 4 → `adapt_set()`.
4. Full-duplex barge-in: `input_audio_buffer.speech_started` always `response.cancel`.

**Prompts** live in `prompts/*.txt` at repo root, loaded at import. `prompt_ref` on traces must be a real relative path (e.g. `prompts/generate_good_v1.txt`).

**Models** are centralized in `shared/models.py`. High-stakes roles default to `o3`; fast roles to `gpt-4o-mini`. `o3` has no `system` role, no `json_object` response_format, no `n > 1`. Use `build_messages` and `completion_kwargs`.

**Traces.** `shared/trace.py` `record_step` is keyword-only; `rationale` required and non-empty. Valid kinds: suggestion, generation, placement, delivery, reaction_capture, scoring, classification, filing, category_creation, set_construction, set_adaptation. Set rationale is **only** in traces (`GET /traces/{artifact_id}`), never a new JokeRecord field.

**Latency.** `joker/latency.py` appends rows to `docs/TOPOGRAPHY.md`. Most rows are still placeholders (`n=0`). One `generation` row with n=5 is from unit samples, not live TTS.

---

## Joke record (graded field names)

Canonical definition: `box/schema/records.py`. Exact names:

`prompt_responses`, `joke_text`, `user_reaction`, `score`, `category`, `metadata`, `user_context`, `attribution`, `provenance`, `set_id`

- `provenance`: `{source, model, prompt, selection_rationale}` — `source` is `generated` or `curated`. `intended_quality` is written into `selection_rationale`, not as a new field.
- `user_context`: optional bands only. Never name, DOB, exact age, email, employer, city.
- `HumorStyle` (shared by `sensitivity_flags`, `humor_preferences`, `humor_avoid`): `wordplay`, `observational`, `absurdist`, `deadpan`, `dark`, `physical`, `self_deprecating`, `topical`.

---

## HTTP surface (`box/router.py`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/health` | open |
| POST | `/accounts` | open (bootstrapping) |
| GET | `/accounts`, `/accounts/{id}` | open |
| PUT | `/box/upsert` | Bearer |
| GET | `/box` | open |
| GET | `/box/{cabinet}/{drawer}/{file}` | open |
| GET | `/export` | open |
| GET | `/cabinets`, `/cabinets/{id}`, `/cabinets/{id}/counts` | open |
| GET | `/drawers`, `/drawers/{id}`, `/drawers/{id}/counts` | open |
| GET | `/files/{id}`, `/files/{id}/counts` | open |
| GET | `/jokes/{id}` | open |
| GET | `/jokes/{id}/trace` | open |
| GET | `/traces/{artifact_id}` | open (uncommitted in working tree; empty steps → 200 not 404) |
| GET | `/genres/{genre}/funniest` | open |
| GET | `/counts` | open |
| GET | `/compliance` | open |
| WS | `/ws/session/{session_id}` | live voice |

4xx/5xx bodies must identify **level** (`box` \| `cabinet` \| `drawer` \| `file` \| `joke`) and **reason**.

---

## Skills to read before touching code

| Skill | When |
|-------|------|
| `.cursor/skills/box-api/SKILL.md` | Any Box endpoint, schema, upsert, compliance |
| `.cursor/skills/joke-record/SKILL.md` | Constructing/reading/serializing a joke record |
| `.cursor/skills/trace/SKILL.md` | Any model call, decision, or artifact |
| `.agents/skills/tdd/SKILL.md` | Test-first / integration tests |
| `.agents/skills/fastapi/SKILL.md` | FastAPI routes, Pydantic, streaming |

Also: `AGENTS.md`, `docs/DECISIONS.md`, `docs/TOPOGRAPHY.md`, `README.md`.

---

## Uncommitted work (not from this chat — already in the tree)

HEAD is Milestone 1 README. The working tree has a large uncommitted slice (Joker/Librarian wiring, traces, prompts, extra tests). **Do not discard it.**

Modified:

- `box/main.py` — dotenv load + voice router
- `box/router.py` — `GET /traces/{artifact_id}` (~39 lines)
- `box/schema/responses.py` — `ArtifactTraceOut`
- `box/tests/conftest.py` — `OPENAI_API_KEY` default
- `docs/DECISIONS.md` — ~98 lines (prompts, traces, orchestrator, etc.)
- `docs/TOPOGRAPHY.md` — latency table
- `joker/generate.py`, `joker/realtime.py` (large), `joker/setbuilder.py`
- `librarian/classify.py`, `interface.py`, `metadata.py`, `score.py`, `suggest.py`
- `requirements.txt`, `shared/db.py`

Untracked:

- `joker/box_client.py`, `joker/orchestrator.py`
- `prompts/` (`suggest_v1`, `classify_v1`, `generate_good_v1`, `generate_bad_v1`, `metadata_v1`, `score_v1`, `setbuilder_v1`)
- `conftest.py` (repo-root: sets dummy `OPENAI_API_KEY` so imports do not construct a real client)
- `box/tests/archive_seed.py`
- `box/tests/test_joker_*.py`, `test_librarian_*.py`, `test_router_traces.py`, `test_trace.py`

Duplicate test locations exist (`joker/tests/`, `librarian/tests/` committed; extra copies under `box/tests/` untracked). Prefer the seams already used by pytest collection; do not blindly delete either set without checking.

---

## Local environment quirks

- Venv Python is 3.14.3; AGENTS.md says 3.11. README says tested on 3.14.3.
- DB is Neon (asyncpg). `shared/db.py` disables prepared-statement cache for PgBouncer.
- Port 8000 was occupied at 22:06 local time by uvicorn PID 61652. Confirm with `netstat -ano | findstr ":8000"` before starting another server.
- User's terminal 1 previously ran the old `box.api.main:app` path, shut it down, then ran pytest. That is not the live 8000 process.

---

## What to do next (if the user has not specified)

This session did not leave an implementation task. Likely continuations from the uncommitted slice:

- Confirm pytest still passes with the new tests (README's "40 passed" is stale).
- Replace placeholder latency rows after a real `/ws/session/{id}` run.
- Commit the uncommitted slice **only if the user asks**, with a message that states why (orchestrator wiring + versioned prompts + generic trace read).

If asked to run the Box again: check port 8000 first; if PID 61652 (or another `box.main:app`) is healthy, leave it.
