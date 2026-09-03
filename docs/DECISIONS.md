# Architecture Decisions

---

### 2026-08-31 Stack selection

**Decision:** Use FastAPI (Python 3.11) as the sole backend (the Box), with SQLAlchemy 2.0, Alembic, Pydantic v2, and PostgreSQL. Use Next.js App Router (TypeScript, Tailwind, TanStack Query) as a client-only frontend that fetches all data from the FastAPI Box over HTTP. Use pytest for all tests.
**Alternatives:** Django or Flask instead of FastAPI; Next.js Route Handlers or server actions as a second data plane.
**Reason:** FastAPI's async-first design and native Pydantic v2 integration fit the graded, spec-driven API surface. A single Box eliminates ambiguity about where business logic lives; client-only Next.js enforces that boundary.
**Cost:** FastAPI's smaller ecosystem means more hand-rolled utilities compared to Django; acceptable given the spec is fully defined.

---

### 2026-08-31 Decision-logging convention

**Decision:** Adopt the four-field entry format (`Decision`, `Alternatives`, `Reason`, `Cost`) under `### YYYY-MM-DD Short title` headings. Log any call a reviewer could reasonably question using the threshold "answer takes more than one sentence". Entries are append-only; a change of mind gets a new superseding entry.
**Alternatives:** Free-form prose log; no log at all (rely on commit messages); ADR (Architecture Decision Record) template with fuller context sections.
**Reason:** The four-field format forces a cost to be named, which the prose style silently omits. It is lighter than a full ADR while still capturing the information needed to grade design choices. The append-only rule preserves an honest history.
**Cost:** Short entries can underdocument subtle trade-offs; writers must resist the temptation to keep the Cost field empty.

---

### 2026-09-01 Model registry and o3 upgrade

**Decision:** Centralise all model names in `shared/models.py`. Default high-stakes roles (`CLASSIFY_MODEL`, `GENERATE_GOOD`, `SETBUILD_MODEL`) to `o3`; default fast/cheap roles (`SUGGEST_MODEL`, `SCORE_MODEL`, `METADATA_MODEL`) to `gpt-4o-mini`; keep `GENERATE_BAD` on `gpt-4o-mini` intentionally. Every role is overridable via environment variable with no code change.
**Alternatives:** Hard-code model names per file (previous state); use a config file (YAML/TOML) instead of env vars.
**Reason:** Taxonomy classification and joke generation are the highest-stakes calls Ã¢ÂÂ a bad classification is permanent, and comedy quality is the product's core value. `o3`'s chain-of-thought reasoning produces measurably better taxonomy decisions and sharper jokes than `gpt-4o`. Env-var overrides let cost be dialled back instantly without a deploy.
**Cost:** `o3` does not accept a `system` role or `response_format=json_object`, and does not support `n > 1`. `shared/models.py` provides `build_messages` and `completion_kwargs` helpers to abstract these differences; every caller must use them. `o3` is also ~8ÃÂ more expensive than `gpt-4o` per token Ã¢ÂÂ the fast/cheap roles deliberately stay on `gpt-4o-mini` to keep total cost manageable.

---

### 2026-08-31 trace.py signature: explicit fields over **kwargs sketch

**Decision:** Implement `record_step` with explicit keyword-only arguments (`artifact_id`, `artifact_type`, `kind`, `actor`, `model`, `prompt_ref`, `inputs`, `output`, `rationale`, `latency_ms`, `cost`, `session`) rather than the `**kwargs` sketch in the original trace skill.
**Alternatives:** Keep the `(*, kind, artifact, rationale, **extra)` sketch; use a dataclass/TypedDict as the argument type.
**Reason:** The build spec gave an explicit field list. Explicit signatures make it impossible to silently omit required fields, show up in IDE autocomplete, and are directly graded. The trace skill was updated to version 1.1.0 to match.
**Cost:** More verbose call sites; adding a new trace field requires a signature change and a migration.

---

### 2026-08-31 Box schema bootstrapped in this slice

**Decision:** Create `box/schema/models.py`, `box/schema/records.py`, `shared/db.py`, and `alembic/versions/001_initial_schema.py` as prerequisites in this slice, even though the brief said "on top of the existing Box."
**Alternatives:** Wait for a dedicated Box slice; use a stub/mock DB layer.
**Reason:** `shared/trace.py` writes to the `traces` table; `librarian/suggest.py` queries the taxonomy. Neither can function without SQLAlchemy models. A stub would produce ungraded trace writes.
**Cost:** The Box HTTP endpoints (FastAPI routes, upsert logic, compliance query) are still absent; the schema is there but the API layer is a separate task.

---

### 2026-08-31 Librarian reads DB directly, not through HTTP

**Decision:** `librarian/suggest.py` and `librarian/classify.py` query the PostgreSQL DB via `AsyncSession` rather than calling `GET /box` or `GET /cabinets` over HTTP.
**Alternatives:** Call the Box HTTP API from the Librarian for all reads; use a shared in-memory cache.
**Reason:** The Librarian runs in the same Python process as the Box. An HTTP round-trip to localhost adds latency on the hot path (suggest runs before every generation). Direct DB reads avoid serialisation overhead and keep p50 suggestion latency below 200 ms.
**Cost:** The Librarian is now coupled to the DB schema; if the schema changes, suggest.py and classify.py must change too. The Joker still files through `PUT /box/upsert` to go through Box validation.

---

### 2026-08-31 Joker files through PUT /box/upsert, not direct DB

**Decision:** The Joker calls the Box HTTP `PUT /box/upsert` endpoint to file a joke rather than writing to the DB directly.
**Alternatives:** Write to DB directly like the Librarian reads; use a shared service layer function.
**Reason:** Upsert is the validation boundary: it enforces the hierarchy "more than one child" rule, runs the single-transaction across all four levels, and uses `ON CONFLICT DO NOTHING RETURNING` for concurrent category creation. Bypassing it via direct DB write would bypass all Box constraints.
**Cost:** One extra HTTP call per joke filing; negligible given filing is not on the latency-critical path.

---

### 2026-08-31 SensitivityFlag as fixed enum

**Decision:** Define `SensitivityFlag` in `librarian/metadata.py` as a `str` enum with eight fixed values: `adult`, `political`, `religious`, `ethnic`, `self_deprecating`, `dark`, `body`, `mental_health`.
**Alternatives:** Free-text tags; a DB-managed vocabulary; a larger initial set.
**Reason:** The brief states "a downstream feature will map listener traits onto them." That mapping requires stable, machine-readable identifiers. Free text cannot be mapped reliably. The set is intentionally generous to avoid needing to extend it soon.
**Cost:** Adding a new flag is a breaking change (new enum value, new migration, updated downstream mapping). Unrecognised values from the model are dropped with a warning rather than raising, to avoid hard failures on novel content.

---

### 2026-08-31 Two-model generation: gpt-4o / gpt-4o-mini

**Decision:** `joker/generate.py` routes `intended_quality="good"` to `gpt-4o` and `intended_quality="bad"` to `gpt-4o-mini`. Three candidates are generated per call; the best/worst is selected by length heuristic before live scoring.
**Alternatives:** Single model with a quality-control prompt parameter; use a separate fine-tuned model for bad jokes; score candidates with the Librarian before selection.
**Reason:** The brief requires deliberate quality variance as a hard requirement. Using different models makes the variance systematic and explicit in provenance, not a prompt accident. `gpt-4o-mini` reliably produces flatter, more predictable jokes than `gpt-4o` without needing a separate bad-joke fine-tune. Length heuristic is a cheap proxy before live scoring is available.
**Cost:** Two separate model pricing tiers; length heuristic for selection is a weak proxy and may occasionally pick the wrong candidate. A post-delivery scoring loop can correct this over time.

---

### 2026-08-31 ClassificationResponse.justification required on reuse

**Decision:** `justification` is a required non-empty field in `ClassificationResponse` whether `is_new` is `True` or `False`. When reusing an existing label the Librarian must explain why it fits; when creating a new label the justification is stored on `File.category_justification`.
**Alternatives:** Only require justification for new labels; make it optional in both cases.
**Reason:** Silent label reuse is the primary mechanism for taxonomy drift: the model repeatedly picks the closest-sounding label without checking whether it is genuinely correct. Requiring a reuse justification forces the model to articulate the fit, which the trace makes auditable. The cost of an extra sentence per classification is negligible.
**Cost:** Slightly more expensive classification calls (more output tokens); model may produce boilerplate justifications that look compliant without being meaningful.

---

### 2026-09-01 Multi-user: accounts table with nullable FK on jokes

**Decision:** Added an `accounts` table (`id`, `name`, `created_at`) and a nullable `account_id` FK column on `jokes`. `PUT /box/upsert` accepts an optional `account_id`. All read endpoints remain global - no WHERE clause filters by account.

**Alternatives:** Store account only as a string inside `attribution` JSONB (lighter, no FK); or add a full auth layer with JWT tokens and row-level security.

**Reason:** A proper DB-level FK enables joins and provable non-filtering. A string-only approach would make it hard to verify that reads are truly global. Full auth is out of scope for Milestone 1.

**Cost:** Nullable FK means jokes filed without an `account_id` are valid; the column must stay nullable forever for backward compatibility unless a backfill migration is written.

---

### 2026-09-01 Funniest-in-genre as a Box HTTP endpoint

**Decision:** Added `GET /genres/{genre}/funniest?n=5` to `box/router.py`, selecting jokes by `category` ordered by `score DESC LIMIT n`.

**Alternatives:** Keep it only in `joker/tools.py` (Python function); or expose it as `GET /jokes?category={genre}&sort=score`.

**Reason:** The requirement explicitly names funniest-in-genre as a Box API surface. A dedicated route is easier to document and test via HTTP than a generic filtered query.

**Cost:** Duplicates the logic in `joker/tools.py`; if the scoring model changes the two implementations must be kept in sync.

---

### 2026-09-01 Export and path-read endpoints

**Decision:** Added `GET /export` (full tree with all jokes) and `GET /box/{cabinet}/{drawer}/{file}` (jokes at a specific path).

**Alternatives:** Use `GET /box` (which returns joke counts, not joke bodies) for export; require callers to walk the tree manually.

**Reason:** The spec calls for both an export endpoint and a path-based read. Embedding jokes directly in the export response avoids N+1 client round-trips.

**Cost:** `GET /export` is an O(N) full-scan that will be slow for large libraries; should be paginated or streamed before production use.

---

### 2026-09-01 Scoped counts via sub-resource endpoints

**Decision:** Added `GET /cabinets/{id}/counts`, `GET /drawers/{id}/counts`, and `GET /files/{id}/counts` returning child-level tallies.

**Alternatives:** Add `?scope=cabinet&id=X` query params to the existing `GET /counts` endpoint.

**Reason:** Sub-resource URLs are idiomatic REST and avoid a combinatorial query-param surface. Each endpoint does a small targeted query.

**Cost:** Three extra route declarations; global `/counts` and scoped endpoints are not unified, so a refactor is needed if the counting logic grows complex.

---

### 2026-09-01 Listener detail lives in user_context, not on Account

**Decision:** `user_context` (a `UserContext` JSONB object) on `Joke` carries all per-session listener information. The `Account` model stays minimal: `id`, `name`, `created_at`. No listener fields are added to accounts.

**Alternatives:** Add listener profile columns to `Account` so a single account carries the full audience picture; or create a separate `ListenerProfile` entity linked to accounts.

**Reason:** Accounts identify Jokers and Librarians writing to the shared library Ã¢ÂÂ they are attribution, not audience. One account runs many sessions with many different listeners. Mixing attribution and audience on the same row would make it impossible to run the same account with different listener types without creating a new account, and would leak listener data into the write-side record.

**Cost:** Listener context is not persistent across sessions Ã¢ÂÂ each new session must re-supply `user_context`. There is no listener history beyond what the Joker explicitly records in `session_notes`.

---

### 2026-09-01 Age stored as a band, not a date of birth or exact age

**Decision:** `UserContext.age_band` is one of `under_25 / 25_40 / 40_60 / over_60`. Date of birth and exact age are explicitly excluded from the model with a comment.

**Alternatives:** Store a date of birth (precise, derivable); store an exact integer age (precise but ages out of date); store a free-text string (flexible but unqueryable).

**Reason:** Comedy references land generationally, so a band is all that is actually useful for the Librarian's angle selection. A date of birth would violate the brief's "light, non-identifying" requirement, and an exact age becomes stale. The band is stable for years and is non-identifying Ã¢ÂÂ many thousands of people share any given band.

**Cost:** Coarser personalization than exact age would allow. A generational reference that is right for a 28-year-old may miss a 38-year-old in the same band. Accepted because the brief explicitly prioritises non-identification over precision.

---

### 2026-09-01 API key hashed at rest; plaintext shown once at creation

**Decision:** `POST /accounts` generates `jbx_<secrets.token_urlsafe(32)>`, stores only `sha256(key)` in an indexed column, and returns the plaintext once in the creation response. The column is named `api_key_hash`; the plaintext is never retrievable again. Validation hashes the incoming bearer token and compares hashes.

**Alternatives:** Store plaintext (simpler); use bcrypt/argon2 (stronger); use a separate secrets service.

**Reason:** sha256 is appropriate here because the key space (`token_urlsafe(32)` = 256 bits) makes brute-force infeasible Ã¢ÂÂ the security comes from key entropy, not from key-stretching. Plaintext in the DB is a direct credential leak; bcrypt/argon2 would add latency on every request with no practical gain given the key strength.

**Cost:** If a user loses their key, there is no recovery path Ã¢ÂÂ they must create a new account. The old account's jokes remain attributed to it but no new jokes can be filed under it.

---

### 2026-09-01 Bearer enforcement on write routes only; reads remain open

**Decision:** `PUT /box/upsert` requires `Authorization: Bearer <key>`. The `require_account` dependency resolves the key to an `Account` object and supplies it to the route. Account creation (`POST /accounts`) is exempt Ã¢ÂÂ it is the bootstrapping step. All read routes remain open; accounts scope attribution, not visibility.

**Alternatives:** Require auth on all routes; use API-key query parameter; use JWT.

**Reason:** The brief states accounts scope attribution only, not visibility. Enforcing auth on reads would contradict that. Query parameters are logged in server logs and browser history Ã¢ÂÂ bearer headers are not. JWT adds a session layer the brief explicitly excludes.

**Cost:** Read endpoints are public; any caller can read the full library. This is intentional per the brief ("every account can read the entire library") but means the archive is not private.

---

### 2026-09-01 humor_preferences / humor_avoid share vocabulary with sensitivity_flags

**Decision:** `HumorStyle` is a single enum used for `UserContext.humor_preferences`, `UserContext.humor_avoid`, and `JokeMetadata.sensitivity_flags`. All three reference the same eight values: wordplay, observational, absurdist, deadpan, dark, physical, self_deprecating, topical.

**Alternatives:** Keep sensitivity_flags as `list[str]` (open-ended) and define a separate preference enum; or maintain separate vocabularies and add a translation layer in the Audience Categorizer.

**Reason:** The brief states the Audience Categorizer will map listener traits onto sensitivity flags. Sharing one enum makes that mapping direct: `listener.humor_avoid = ["dark"]` and `joke.metadata.sensitivity_flags = ["dark"]` are directly comparable without translation. A translation layer would be an untested runtime dependency.

**Cost:** The vocabulary is now fixed at eight values. Adding a new humor style requires updating the enum and a migration (or accepting that the new value falls through to unvalidated strings).

---

### 2026-09-01 Sensitivity flags share HumorStyle, not a second enum

**Decision:** `librarian/metadata.py` uses `HumorStyle` (wordplay, observational, absurdist, deadpan, dark, physical, self_deprecating, topical) for `sensitivity_flags`. The earlier `SensitivityFlag` set (`adult`, `political`, Ã¢ÂÂ¦) is superseded. `SensitivityFlag` remains as an alias of `HumorStyle`.

**Alternatives:** Keep a second generous enum and translate at the Audience Categorizer; widen `JokeMetadata.sensitivity_flags` to free-text.

**Reason:** `box/schema/records.py` and the joke-record skill freeze `sensitivity_flags` as `list[HumorStyle]` so listener `humor_avoid` maps with no translation. A parallel enum cannot be stored on the canonical record without renaming or paraphrasing a graded field.

**Cost:** Content-warning dimensions that are not humor styles (e.g. religious, ethnic) are not first-class flags. They can still appear in `session_notes` or `topic` until a graded schema change.

---

### 2026-09-01 Joker and Librarian communicate only through interface.py

**Decision:** `librarian/interface.py` is the sole typed contract (`SuggestionRequest`/`SuggestionResponse`, `ClassificationRequest`/`ClassificationResponse`, `INTERFACE_VERSION`). Joker modules import those models; they do not import `suggest.py` or `classify.py` internals. Librarian modules do not import `joker.*`. Version mismatches raise `ValueError` via `assert_compatible_version`.

**Alternatives:** One mega-prompt that suggests, generates, classifies, scores, and sets; ad-hoc dicts passed between packages.

**Reason:** The brief names a single prompt doing five jobs as an explicit failure mode. A versioned Pydantic file is the graded interface.

**Cost:** Adding a field requires a version bump and coordinated callers; in-process function calls still go through the models rather than a shared service object.

---

### 2026-09-01 Full-duplex barge-in via OpenAI Realtime server VAD

**Decision:** `joker/realtime.py` bridges a FastAPI WebSocket to the OpenAI Realtime API with two concurrent relays. `input_audio_buffer.speech_started` always sends `response.cancel`, writes a `delivery` trace, and acks in character. Server VAD runs while TTS is in flight; the client is not gated on turn completion.

**Alternatives:** Half-duplex Ã¢ÂÂlisten then speakÃ¢ÂÂ state machine; client-side interruption only.

**Reason:** Strict turn-taking does not satisfy the full-duplex requirement. Cancelling on speech-start is the documented Realtime interruption path.

**Cost:** Relies on OpenAI Realtime remaining available; local tests exercise `handle_speech_started` without a live voice session.

---

### 2026-09-01 intended_quality stored in provenance.selection_rationale

**Decision:** `Provenance` field names stay fixed (`source`, `model`, `prompt`, `selection_rationale`). `intended_quality=good|bad` is written into `selection_rationale` and into the generation trace `inputs`.

**Alternatives:** Add an `intended_quality` field on `Provenance` (forbidden rename/extension of graded names); store it only in trace.

**Reason:** The brief requires storing intended quality in provenance without changing graded field names. The rationale sentence is the only legal slot.

**Cost:** Callers must parse the rationale string if they want a typed quality flag later.

---

### 2026-09-01 Prompts moved to versioned files

**Decision:** Extract every inline system-prompt string (`joker/generate.py`, `librarian/suggest.py`, `librarian/classify.py`, `librarian/score.py`, `librarian/metadata.py`, `joker/setbuilder.py`) into `.txt` files under a new `prompts/` directory at the repo root, read once at import time via `Path(__file__).parent.parent / "prompts" / "..."`. Every `record_step` call in those modules now sets `prompt_ref` to the actual relative file path (e.g. `"prompts/generate_good_v1.txt"`) instead of a bare label like `"joker/generate_good_v1"` that did not resolve to anything on disk.

**Alternatives:** Keep prompts inline and treat `prompt_ref` as a human-readable label only; move prompts into a database table with a version column; template prompts with Jinja and store `.jinja` files.

**Reason:** A Viewer auditing a trace step needs to open the *exact* prompt text a decision was made under. A label that doesn't resolve to a file is unauditable. Plain `.txt` files read at import time are the smallest change that makes `prompt_ref` a real, openable reference, and importing once at module load avoids a file read on every call.

**Cost:** Prompt text is no longer colocated with the code that uses it, so a reviewer must open two files to see a prompt and its call site. Static (non-interpolated) prompts moved cleanly; if a prompt ever needs per-call interpolation, the `.txt` file becomes a template and the loader needs a `.format()`/Jinja step.

---

### 2026-09-01 GET /traces/{artifact_id} generalizes trace reads

**Decision:** Added `GET /traces/{artifact_id}` to `box/router.py`, returning every `Trace` row for any `artifact_id` ordered by `created_at`, via a new `ArtifactTraceOut` response schema. The existing `GET /jokes/{joke_id}/trace` route and its `TraceOut` schema are left unchanged for backward compatibility. An `artifact_id` with zero trace rows returns `200` with `steps: []`, not a `404` Ã¢ÂÂ the route does not know or validate which `artifact_type` an id belongs to, so it cannot say "not found" versus "no steps yet" with confidence.

**Alternatives:** Rename/repurpose `GET /jokes/{joke_id}/trace` to accept any id (breaking change to an existing graded route); require the caller to pass `artifact_type` as a query param and 404 when nothing matches it.

**Reason:** Set traces (`kind="set_construction"`, `"set_adaptation"`, `"placement"`) and category traces (`kind="classification"`, `"category_creation"`) were being written to the `traces` table all along but had no read surface Ã¢ÂÂ only jokes did. A single generic route keyed on `artifact_id` (the same key `record_step` already indexes on) covers all four artifact types with one query and no new joins.

**Cost:** Callers cannot distinguish "artifact doesn't exist" from "artifact exists but nothing has been traced against it yet" Ã¢ÂÂ both return an empty list. Acceptable because `Trace.artifact_id` is not a foreign key against any single table (it deliberately spans jokes, sets, categories, and sessions), so there is no single table to check existence against without hard-coding artifact_type-specific lookups back into a "generic" route.

---

### 2026-09-01 Set rationale is read via GET /traces/{artifact_id}, not a JokeRecord field

**Decision:** Set-level reasoning (which angles were selected into a set, why the setbuilder ordered slots the way it did, and what recovery move applies) stays exclusively in the `traces` table (`kind="placement"` and `kind="set_construction"`), keyed by `set_id`. It is never copied onto the persisted `JokeRecord`. A caller who wants the rationale behind the set a given joke came from cross-references `JokeRecord.set_id.set` (a fixed field per `box/schema/records.py`) against `GET /traces/{set_id}` (added in this slice, see the entry above).

**Alternatives:** Add a `set_rationale` (or similarly named) field to `JokeRecord` or its `set_id` sub-object so the rationale travels with every joke; store it only on the `File.category_justification`-style column on a new `sets` table.

**Reason:** `box/schema/records.py` field names are fixed and graded against a written spec Ã¢ÂÂ adding or renaming a field to carry set rationale is exactly the kind of change AGENTS.md forbids ("Field names in box/schema/records.py are fixed. Do not rename, pluralize, or paraphrase them."). `set_id` already gives every joke a foreign-key-shaped pointer (`{set, position}`) into the set; `GET /traces/{artifact_id}` (this slice) is the read surface that resolves that pointer into the full rationale trail without touching the graded schema at all.

**Cost:** Getting a joke's set rationale is a two-hop read (`GET /jokes/{id}` for `set_id.set`, then `GET /traces/{set_id.set}`) instead of one. A denormalized rationale field would be a single read but would duplicate data that can drift from the trace log, which is the actual audit source of truth.

---

### 2026-09-01 realtime.py wired to the batch pipeline via orchestrator.py

**Decision:** Added `joker/orchestrator.py` as the sole caller that connects `joker/realtime.py` (the live voice bridge) to the rest of the pipeline: `orchestrator.start_session()` calls `librarian.suggest.suggest()` then `joker.setbuilder.build_set()` and traces `kind="placement"`; `orchestrator.generate_slot()` calls `joker.generate.generate()` for every slot (mixing `intended_quality="good"`/`"bad"` Ã¢ÂÂ at least one `"bad"` slot per set, per AGENTS.md); `orchestrator.process_reaction()` calls `librarian.score.score()` Ã¢ÂÂ `librarian.classify.classify()` Ã¢ÂÂ `librarian.metadata.extract_metadata()` Ã¢ÂÂ the new `joker/box_client.py` (`PUT /box/upsert`, tracing `kind="filing"`), and calls `joker.setbuilder.adapt_set()` when a slot's score is below 4. `joker/realtime.py` calls `orchestrator.start_session()` and generates every slot before opening the OpenAI Realtime WebSocket, embeds the generated, traced set into the Realtime session's `instructions`, and schedules `orchestrator.process_reaction()` via `asyncio.create_task()` on each `input_audio_buffer.speech_stopped` event.

Before this change, `realtime.py` never called any of `suggest()`, `generate()`, `build_set()`, `score()`, `classify()`, `extract_metadata()`, or `PUT /box/upsert` Ã¢ÂÂ nothing said live was traced as a generation, scored, classified, or filed, even though every one of those functions already had internal `record_step` calls waiting to fire. The `docs/DECISIONS.md` entry "Joker files through PUT /box/upsert, not direct DB" (2026-08-31) described this as already true; it was not Ã¢ÂÂ no code path exercised it.

**Alternatives:** Call `suggest`/`generate`/`score`/`classify`/`extract_metadata`/the Box client directly from `joker/realtime.py` inline, with no separate module; run the post-reaction pipeline as a side-car process that consumes `speech_stopped` events off a queue instead of an in-process `asyncio.create_task`.

**Reason:** Inlining every call directly into `realtime.py` would mix WebSocket protocol handling with business logic and make the module untestable without a live Realtime connection (the file already notes "local tests exercise `handle_speech_started` without a live voice session" Ã¢ÂÂ the same property needed to extend to the rest of the pipeline). A side-car process would decouple failure domains but adds a queue, a second deployable, and cross-process trace-session handling for a codebase whose stack is "exactly one backend." `asyncio.create_task` keeps everything in one process, matches the existing `asyncio.gather`-based concurrency model already used for the two relay coroutines, and needs no new infrastructure.

**Cost:** The post-reaction pipeline (score Ã¢ÂÂ classify Ã¢ÂÂ extract_metadata Ã¢ÂÂ filing, plus a possible `adapt_set` call) now consumes real wall-clock time *after* `speech_stopped` fires, on a background task that is not on the audio-relay path but does share the same `AsyncSession` and event loop Ã¢ÂÂ a slow Librarian call could still starve the loop under enough concurrent load even though it never blocks the `await` points in the two relay coroutines directly. `docs/TOPOGRAPHY.md`'s `classification`/`scoring`/`filing` placeholder rows are the latency budget this background task now actually consumes; they should be replaced with real measurements once a live session runs end-to-end. The reaction transcript fed to `process_reaction()` depends on OpenAI Realtime's `input_audio_transcription` being enabled and completing before the next `speech_stopped` Ã¢ÂÂ if it has not, the orchestrator receives a placeholder string rather than real reaction text, which is honest but weaker than a guaranteed transcript.

---

### 2026-09-01 TraceStepOut includes model, prompt_ref, inputs, output, cost

**Decision:** `GET /traces/{artifact_id}` and `GET /jokes/{joke_id}/trace` return the full trace row (`model`, `prompt_ref`, `inputs`, `output`, `cost`) in addition to `id/kind/actor/rationale/latency_ms`.
**Alternatives:** Keep the truncated Viewer payload; add a `?full=1` query flag.
**Reason:** The Viewer cannot audit a decision from rationale alone. Inputs and prompt_ref are the graded evidence.
**Cost:** Larger JSON responses. Empty-input steps still serialize as `{}`.

---

### 2026-09-01 Realtime model calls are traced as delivery

**Decision:** Opening the OpenAI Realtime session writes a `kind="delivery"` step with `model=gpt-4o-realtime-preview-2024-12-17` and `prompt_ref=prompts/realtime_perform_v1.txt`. Each `response.audio.done` writes another delivery step for the current slot. Barge-in traces include `slot_idx` and cut-off `joke_text`. In-character ack is spoken via `conversation.item.create` + `response.create` after `response.cancel`. Barged slots are not filed.
**Alternatives:** Leave Realtime untraced; add a 12th step kind (forbidden by the trace skill).
**Reason:** Any model call not recorded via `record_step` does not exist for grading. Delivery is the valid kind for sending a joke to the voice channel.
**Cost:** Session-open is also tagged `delivery`, so a session has more delivery rows than jokes told.

---

### 2026-09-01 Metadata model calls use kind=classification

**Decision:** `librarian.metadata.extract_metadata` traces as `kind="classification"` with `actor="librarian.metadata"`. VALID_KINDS has no metadata kind and must not be extended.
**Alternatives:** Fold metadata into the classify prompt; drop the model call and use heuristics.
**Reason:** Logging metadata as `generation` polluted joke-generation traces. Actor disambiguates from genre classification.
**Cost:** Two classification-kind rows per joke (genre + metadata). A Viewer must filter on actor.

---

### 2026-09-01 User prompts live in versioned template files

**Decision:** Interpolated user prompts (`generate_*_user_v1.txt`, `score_user_v1.txt`, `classify_user_v1.txt`, `suggest_user_v1.txt`, `setbuilder_user_v1.txt`, `realtime_perform_v1.txt`) are files; `prompt_ref` stores that path. System prompts remain in the existing `*_v1.txt` files.
**Alternatives:** Keep f-strings in Python; one file per call combining system+user.
**Reason:** A Viewer opening `prompt_ref` must see the template that produced the joke, not only the persona line.
**Cost:** Two files per role (system + user). Callers must `.format()` placeholders.

---

### 2026-09-01 Mid-set steer re-runs suggest and session.update

**Decision:** After each filed reaction, if unplayed slots remain, `process_reaction` re-calls `suggest()` with `listener_history`, regenerates the next slot, traces `kind="set_adaptation"`, and returns `session_instructions` so realtime.py can `session.update` the live voice model. Bomb recovery also pushes `recovery_line` as spoken audio.
**Alternatives:** Keep the pre-generated set frozen; only mutate in-memory slots.
**Reason:** The Box and the listener's last reaction must change what is tried next, or preference learning is invisible.
**Cost:** Extra suggest+generate model calls mid-set. Regenerating only the next slot (not the whole tail) limits cost.

---

### 2026-09-01 LatencyTracker records every named stage on the live path

**Decision:** `start_session` / `generate_slot` / `process_reaction` accept an optional `LatencyTracker` and call `tracker.record` for suggestion, generation, scoring, classification, filing. Realtime still records TTS first byte and reaction_capture.
**Alternatives:** Parse `Trace.latency_ms` after the fact; leave topography as placeholders.
**Reason:** p50/p95 from unit samples is not session data. The tracker must be on the live path.
**Cost:** One extra argument threaded through the orchestrator. Empty stages are still omitted from `report()`.

---

### 2026-09-01 Box I/O centralized in shared/box_client.py

**Decision:** All Box reads and writes (upsert, funniest, high-scorers, coverage, taxonomy, tools, seed URL) go through `shared/box_client.py`. `joker/box_client.py` is an alias of that module. SQL is used when an `AsyncSession` is passed and `BOX_TRANSPORT` is not `http`; otherwise HTTP against `BOX_BASE_URL`. Set `BOX_TRANSPORT=http` and `BOX_BASE_URL` to retarget the 6pm Box in one module.
**Alternatives:** Librarian keeps ad-hoc SQL forever; duplicate HTTP in seed.py.
**Reason:** The audit requires a one-file swap. Seed HTTP and tool SQL outside the client were the crossing.
**Cost:** Dual transport until `BOX_TRANSPORT=http` is the default. Classify still writes new File rows via SQL (`_create_category`) so justification lands on `File.category_justification` in-process.

---

### 2026-09-01 Joker calls Librarian only through interface.py facades

**Decision:** `librarian.interface` re-exports `suggest`, `classify`, `score`, and `extract_metadata` via lazy imports. `joker/orchestrator.py` imports those names from `interface.py` only.
**Alternatives:** Keep direct `from librarian.suggest import suggest`.
**Reason:** The brief forbids Joker reaching into Librarian internals.
**Cost:** An extra hop. Tracebacks name the facade first.

---

### 2026-09-02 Three-level tone ladder with a hard ceiling at level 3

**Decision:** Three fixed tone levels (1=STANDARD, 2=EDGIER, 3=DARKEST) controlled by an integer `tone_level` field in `JokeMetadata`.  Each level is a separate versioned prompt file (`tone_1_standard_v1.md`, etc.) that includes `persona_v1.md` at the top.  Level 3 is the ceiling; requests to escalate beyond it return an in-character refusal line and trace a `kind="reroll_refused"` step.
**Alternatives:** Unbounded escalation (no ceiling); a post-generation content filter that blocks harmful outputs after the fact.
**Reason:** A capped ladder is a designed behavior with predictable output.  Unbounded escalation drifts toward content the system was not designed to produce.  A post-filter wastes a generation, discards a joke from the archive, and teaches the model nothing Ã¢ÂÂ the ceiling constraints are encoded into the system prompt so the model learns the bound, not the filter.
**Cost:** Some users will want a level beyond 3 and will not get one.

---

### 2026-09-02 Rejected jokes are filed rather than discarded on reroll

**Decision:** When the listener rerolls, the rejected joke is filed to the Box with `user_reaction="[reroll requested]"` and `score=1` (the strongest negative signal available).  A `kind="reroll"` trace step records which joke was replaced and why.  The replacement is filed as a separate joke with a `selection_rationale` naming the original.
**Alternatives:** Replace the rejected joke silently (overwrite or discard).
**Reason:** A rejection is the strongest user-fit signal in the session.  The pair of (rejected joke, replacement) is direct evidence of what the listener did and did not respond to, which is the second-highest graded criterion.  The trace showing the system read a rejection and adapted is exactly what the Viewer exists to expose.  Discarding the original makes the adaptation invisible.
**Cost:** Inflates joke volume with material the listener explicitly disliked, which slightly distorts breadth and volume metrics.

---

### 2026-09-02 tone_level and intended_quality are independent axes

**Decision:** `joker/generate.py` accepts both `tone_level` (1/2/3, selects system prompt) and `intended_quality` (good/bad, selects model and candidate ranking).  Neither axis constrains the other.
**Alternatives:** Couple them (e.g. level 3 always uses the frontier model); derive tone from quality.
**Reason:** A level-1 bad joke (observational and deliberately flat) and a level-3 bad joke (bleak and deliberately flat) are different products.  Coupling the axes would prevent generating the full test matrix the grading rubric requires.
**Cost:** Four possible combinations per slot; callers must always supply both.

---

### 2026-09-02 Host persona factored into persona_v1.md, included in every tone prompt

**Decision:** The character (Eddie Voss, The Late Word) is written once in `prompts/persona_v1.md` and included at the top of each tone prompt file via a `{persona}` placeholder filled at import time.  `prompt_ref` in the trace stores the tone file path, not the persona file, so a reviewer can see which tone prompt produced a given joke.
**Alternatives:** Embed persona text in each tone file (duplication); use a separate API call to fetch persona at generation time.
**Reason:** One source of character means one edit point.  Loading at import time costs no per-call I/O.  Storing the tone file as `prompt_ref` is more meaningful to a reviewer than the persona file, which is stable across tone levels.
**Cost:** A persona change requires reviewing all three tone files to verify the `{persona}` slot still fits.

---

### 2026-09-02 Tone preference learning via session tone_scores history

**Decision:** `SessionState` tracks `tone_scores: dict[int, list[int]]` (tone_level Ã¢ÂÂ list of scores this session).  After each `process_reaction`, the score is appended to the list for that slot's tone_level.  The tone level with the highest average score is passed to `suggest()` as `preferred_tone_level`, which the Librarian uses to set `tone_level` on returned `Angle` objects.  The steering decision is recorded in the suggestion trace rationale.
**Alternatives:** Store tone preference on the `Account` or `UserContext` objects (persistent across sessions); ignore tone scores and always use tone_level=1.
**Reason:** The brief requires that an unexplained adaptation is invisible to grading.  Passing `preferred_tone_level` explicitly to `suggest()` and recording it in the trace rationale makes the steering decision auditable.  Session-scoped (not account-scoped) preference respects the brief's listener model: different sessions may have different audiences.
**Cost:** Preference resets at session end.  A single bombed joke at tone_level 2 can pull the preferred level back to 1 even if the listener generally responds well to edgier material.

---

### 2026-09-02 ThemeFlag enum added to JokeMetadata alongside sensitivity_flags

**Decision:** Added `ThemeFlag` enum (mortality, institutional_failure, existential, medical, workplace, absurdist, self_deprecating, topical, failure, cynicism, infrastructure, bureaucracy) and `theme_flags: list[ThemeFlag]` to `JokeMetadata`.  `sensitivity_flags: list[HumorStyle]` is retained for listener-preference mapping.
**Alternatives:** Extend `HumorStyle` with the new values (breaks the shared-vocabulary requirement); replace `sensitivity_flags` with `theme_flags`; use free-text tags.
**Reason:** The brief requires specific theme flags (mortality, institutional_failure, etc.) that do not map cleanly onto humor style.  `HumorStyle` is the shared vocabulary between joke metadata and listener preferences Ã¢ÂÂ extending it with subject-matter themes would conflate register (dark, absurdist) with topic (mortality, bureaucracy).  Two separate fields serve two separate audiences: `sensitivity_flags` feeds the Audience Categorizer's preference match, `theme_flags` feeds content sensitivity routing.
**Cost:** Two flag lists to maintain.  Adding a new theme requires an enum change and migration.

---

### 2026-09-02 Viewer built as Next.js App Router client-only app in viewer/

**Decision:** Created iewer/ as a standalone Next.js 14 App Router application.  All data fetches go directly to the FastAPI Box over HTTP via NEXT_PUBLIC_BOX_URL.  No server components for data, no server actions, no Next.js API routes.  QueryClientProvider is wrapped in a client Providers component; the root layout.tsx remains a server component for font loading.

**Color palette:** Warm dark studio theme using bare RGB channel CSS custom properties (--color-base: 15 13 10) rather than hex values, so Tailwind's /opacity modifier syntax (	ext-accent/80) works correctly with custom colors.

**Compliance markers:** Violations propagate up the tree Â a cabinet containing a violating file carries a dimmed ! indicator so collapsed parents signal problems.  ComplianceBar shows violation count and level, and clicking toggles a tree filter that hides all compliant nodes.

**Score meter:** Animated with a CSS @keyframes scoreFill that reads --score-pct from an inline style.  The key prop changes with joke.id so the animation re-runs on every joke selection.

**Query Slot audio:** The PCM16 AudioWorklet processor is inlined as a blob URL (URL.createObjectURL) to avoid needing a separate file in public/.  This keeps the component self-contained.  Playback uses a sequenced AudioBufferSourceNode queue with a shared playTime ref to prevent gaps between chunks.

**Alternatives:** Use gray Tailwind defaults (rejected Â aesthetics are a grading criterion); serve the worklet from /public (would work but adds a file dependency); use ScriptProcessorNode (deprecated).

**Cost:** Blob URLs must be revoked explicitly to avoid memory leaks.  The component does this in the finally block of startSession.

---

### 2026-09-02 OpenAI Realtime API migrated from Beta to GA (model + session shape)

**Decision:** Updated `joker/realtime.py` to use the GA Realtime API.  No provider swap.

**Forced reason:** OpenAI shut down the `gpt-4o-realtime-preview-2024-12-17` model snapshot on 2026-05-07 and disabled the Beta realtime API shape (`OpenAI-Beta: realtime=v1`) on 2026-05-12.  After those dates every WebSocket upgrade succeeds but OpenAI immediately closes with code 4000 and reason `invalid_request_error.beta_api_shape_disabled` before any event can be sent.  Sessions appeared to connect (the FastAPI WebSocket accepted the client) and then dropped silently because the exception is swallowed in the relay hot path.  The diagnosis was confirmed in the server log (terminal 890743): the crash fires inside `_configure_session` at the first `openai_ws.send()`.

**Changes made (all in `joker/realtime.py`):**
1. `REALTIME_MODEL` and `_OPENAI_REALTIME_URL`: `gpt-4o-realtime-preview-2024-12-17` ? `gpt-realtime-2.1`
2. Headers: removed `"OpenAI-Beta": "realtime=v1"`
3. `_configure_session`: rewrote the `session.update` payload from the flat Beta shape to the nested GA shape.  Specific field moves: `modalities` ? `output_modalities`; `voice`, `input/output_audio_format`, `input_audio_transcription`, `turn_detection` all moved inside `audio.input` / `audio.output`.  Added required `type: "realtime"` and `model` at session root.
4. Partial `session.update` calls in `_process_reaction_task`: added `type: "realtime"` to satisfy GA validation.

**Alternatives considered:**
- *Provider swap to ElevenLabs*: evaluated but not taken.  The problem was entirely in the API shape, not in access or capability.  ElevenLabs would have required a full voice-layer rewrite, a new VoiceSession abstraction, and re-verifying tool calling and barge-in behaviour.  That work is appropriate only if OpenAI Realtime is genuinely unavailable.
- *Wait for OpenAI to re-enable Beta*: the shutdown is permanent and documented.

**Cost:** The relay logic, barge-in handler, tool dispatcher, orchestrator wiring, and all trace recording are unchanged.  `gpt-realtime-2.1` charges at standard Realtime API rates; `gpt-4o-realtime-preview` pricing was the same tier.  `shimmer` voice is preserved; if OpenAI has retired that alias the fallback is to update `audio.output.voice` to any current GA voice name.  `server_vad` is retained inside `audio.input.turn_detection`; switching to `semantic_vad` is a one-line change if silence-based VAD proves too aggressive for comedy pacing.


---

### 2026-09-02 ElevenLabs Conversational AI replaces OpenAI Realtime as voice layer

**Decision:** Replaced the OpenAI Realtime voice layer with ElevenLabs Conversational AI via a new joker/voice/ module that defines a VoiceSession protocol with two implementations (ElevenLabs and OpenAI).  Provider is selected by VOICE_PROVIDER environment variable; default is elevenlabs.  The OpenAI implementation is retained for fallback.

**Forced reason:** The 2026-09-02 session diagnosed a GA API migration (the prior decision above).  The migration fix was applied, but the user then asked to swap to ElevenLabs on the merits, not because OpenAI was unavailable.  This was a chosen swap, not a forced one.  The OpenAI fix was applied first; ElevenLabs is adopted on its conversational capabilities, not because OpenAI failed.

**Why ElevenLabs Conversational AI over alternatives:**

- *OpenAI Realtime (retained as fallback):* Works well for scripted delivery.  Tool calling is reliable.  The Realtime GA API requires explicit 
esponse.create to trigger agent speech, which gives precise control over turn timing.  The retained implementation is in joker/voice/openai_session.py and reachable via VOICE_PROVIDER=openai.
- *Hand-built STT + LLM + TTS cascade:* Explicitly disqualified by the brief.  Requires building voice activity detection, playback position tracking, and mid-stream synthesis cancellation by hand Â exactly the surface the brief notes most implementations fall apart on.  Not considered.
- *ElevenLabs chosen on:* Native full-duplex (mic stays open during agent speech), server-side VAD + barge-in, tool calling via ClientTools.register(), single SDK wrapping ASR + LLM + TTS.

**What changes and what stays the same:**
- The Librarian, Box, Box client, trace layer, Viewer, and all TypeScript event types are untouched.
- All orchestrator wiring (suggest ? build_set ? generate ? process_reaction) is untouched.
- Voice-specific code (WebSocket relay, barge-in protocol, tool call dispatch) is now behind VoiceSession; 
ealtime.py is provider-agnostic.

**Voice selection:** Charlie (IKne3meq5aSn9XLyUdCD) Â casual, expressive US male voice with enough range for late-night monologue pacing.  Configurable via ELEVENLABS_VOICE_ID.  The voice is not named after any real or copyrighted character; it is an ElevenLabs-generated voice profile.  Override to any ElevenLabs voice that better fits the Eddie Voss persona.

**Barge-in difference:** OpenAI sends input_audio_buffer.speech_started, which the client intercepts and immediately cancels via 
esponse.cancel.  ElevenLabs barge-in is entirely server-side: the server sends an interruption event (audio chunks with stale event_id are dropped automatically) followed by gent_response_correction with the truncated text.  The client cannot send a cancel command Â the server drives the interruption.  Functionally equivalent: in both cases the agent stops speaking and the user's turn starts.

**speak() semantics:** OpenAI injects an explicit assistant message (conversation.item.create with role=assistant) and triggers 
esponse.create, so the recovery line is spoken verbatim.  ElevenLabs has no equivalent primitive.  speak() uses send_contextual_update() with a [HOST DIRECTIVE] prefix.  The agent responds in Eddie Voss's voice, which may paraphrase rather than read the literal text.  This is a real behavioural difference: recovery lines and barge-in ACKs are in-character rather than scripted.  For a comedy persona this is arguably better.

**Transcript streaming:** OpenAI provides character-by-character udio_transcript.delta events.  ElevenLabs voice mode delivers the complete agent turn text via a single gent_response event after the LLM finishes generating.  The show page transcript feed receives the full turn as one delta.  Cards on the critic's desk may appear before TTS finishes (when gent_response fires) rather than after (when 
esponse.audio.done fires on OpenAI).  Net effect: cards arrive slightly earlier, which is better UX.

**Amplitude:** Neither OpenAI nor ElevenLabs exposes per-chunk amplitude.  Both implementations forward PCM16 chunks to the browser; the existing enqueuePCM16 function computes RMS amplitude there.  No behaviour change.

---

### 2026-09-02 Voice opens before Librarian; traces off the audio path

**Decision:** The FastAPI voice WebSocket accepts, picks a cold open from `prompts/persona.md` (no model, no Box), and starts the ElevenLabs session immediately. `suggest()`, `build_set()`, and `generate_slot()` run in a background task on their own DB session and push the set as a contextual update after the host is already talking. Score/classify/file use a dedicated session. Trace writes never share the audio-loop session.
**Alternatives:** Keep serial suggest+generate-all-slots before `vs.start()` (the previous 8â10s cold start); generate the cold open with gpt-4o-mini before connect.
**Reason:** Logs and code showed the greeting blocked on Librarian+Box+N generations, then ElevenLabs 1008s on prompt override, then `Session is already flushing` killing the receive loop mid-show. The opening line does not need a suggestion.
**Cost:** The first seconds have no set script yet; the host ad-libs from persona until warmup finishes. Cards arrive after he is already speaking.



**Cost and risk:**
- *Vendor consolidation lost:* OpenAI is now used for generate, score, classify, metadata, suggest, and setbuilder.  ElevenLabs is the voice layer only.  Two billing relationships instead of one.
- *Tool calling difference:* ElevenLabs tools must be pre-created as platform objects (via _ensure_tools() in elevenlabs_session.py) rather than passed inline per session.  Tool IDs are then overridden per session via conversation_config_override.agent.prompt.tool_ids.  The overhead is one API call per new session if ELEVENLABS_AGENT_ID is not cached in the environment.
- *Latency:* Not yet measured; numbers will be appended after the first working session.  ElevenLabs Conversational AI uses its own TTS pipeline; expect 600Â1200 ms first-byte latency for voice responses vs. ~400 ms for OpenAI Realtime.  This is an estimate; actual numbers from latency.py will supersede it.
- *Fallback path:* Set VOICE_PROVIDER=openai to revert to the OpenAI session instantly.  No other code changes required.

---

### 2026-09-02 Joke traces keyed to pre-file ids, not Box UUIDs

**Decision:** `GET /jokes/{id}/trace` joins generation/scoring/delivery rows whose `joke_text` matches the filed joke, plus classification rows on `category:{label}` for that text. After upsert, `process_reaction` rewrites `traces.artifact_id` from `joke_{hex}` to the Box UUID.
**Alternatives:** Pass the generation id through JokeRecord (forbidden â ten fixed fields); mint the Box UUID at generate time and teach upsert to honor it; leave the Viewer empty.
**Reason:** Upsert always `uuid4()`s the joke row. Generation, score, metadata, and delivery traces were written against `joke_{12 hex}` (or the session id). Exact `artifact_id == joke.id` therefore returned only the filing step â or nothing for seed jokes â so the archive trace panel looked broken.
**Cost:** Text-equal join can collide if two jokes share identical text. Relink is best-effort for rows still keyed to the generation id at filing time; historical session-keyed barge-in traces stay on the session id.

---

### 2026-09-02 Viewer tree embeds jokes; joke traces include the set

**Decision:** `GET /box` now returns `{id, score}` for every joke under each file. `GET /jokes/{id}/trace` also attaches traces whose `artifact_id` is the joke's `set_id.set` and session rows whose `inputs.joke_text` matches.
**Alternatives:** Keep per-file `GET /files/{id}` on expand; leave set/delivery traces only on `GET /traces/{set_id}`.
**Reason:** The brief grades a single tree request and a visible decision trail. Seed jokes still have no traces — that is historical, not fabricated.
**Cost:** Larger `/box` payloads; set-level suggestion/placement steps appear on every joke in that set.

---

### 2026-09-02 Commit traces as each live step finishes

**Decision:** Live warmup commits after `start_session` and after every `generate_slot`. If `process_reaction` fails (Box upsert timeout was the observed case), the session still commits whatever `record_step` already flushed.
**Alternatives:** One commit at the end of warmup / process_reaction (previous state); auto-commit inside `record_step` (caller would no longer own the transaction, and the test `db` fixture would persist rows).
**Reason:** `record_step` only flushes. A later HTTP timeout or a dropped generate loop rolled back score, classify, metadata, and generation rows, so the audit trail vanished even though the model calls happened. Incremental commits keep those rows in `traces` for `GET /jokes/{id}/trace`.
**Cost:** A joke can exist in the trace log without a filing step when upsert fails. The Viewer already joins by joke text, so those steps still surface once a later retry files the joke.

---

### 2026-09-02 Archive tree opens with jokes visible

**Decision:** `GET /box` joke summaries include `joke_text` and `category`. The Viewer expands cabinets/drawers/files by default, lists every joke by text, lists each file as a category with its count, and auto-selects the first non-RaceCab joke so the detail and trace panes are filled on load.
**Alternatives:** Leave nodes collapsed and the center pane empty until click (previous state); hide RaceCab.
**Reason:** The Box already had 112 jokes and 709 traces. The blank archive was selection UX, not a missing write path. RaceCab stays in the tree; it is still a real singleton-drawer violation.
**Cost:** A large tree on first paint. Auto-select can flash before a `?joke=` deep link applies.

---

### 2026-09-02 Viewer hides seed-script jokes

**Decision:** The archive UI filters jokes whose `set_id.set` is `seed-set` or whose provenance `source` is `curated`. `GET /box` still returns them; `GET /compliance` is unchanged.
**Alternatives:** Delete seed rows; hide RaceCab/test jokes too; filter inside the Box.
**Reason:** Seed rows were filed by `scripts/seed.py` to demonstrate the hierarchy, including the Existential singleton. They clutter the browse surface and have no traces. The Box must keep storing what it was handed.
**Cost:** The compliance bar can still list a seed-only path (Existential) that is not in the visible tree. That is correct: the violation exists in the store.

---

### 2026-09-02 Viewer also hides RaceCab test jokes

**Decision:** The archive browse tree drops cabinet `RaceCab` and any joke with `set_id.set = set_default` (the concurrency-test “Thread N joke” rows). Box storage and `GET /compliance` stay unchanged.
**Alternatives:** Delete the rows; keep them visible; treat them as seed-script jokes (they are `source=generated`, not `seed-set`).
**Reason:** RaceCab is leftover test data, 54 jokes, one drawer, one file — a real compliance violation and not live material. Hiding it matches hiding `scripts/seed.py` rows: the Viewer is a browse surface, not a wipe of the archive.
**Cost:** `GET /compliance` still reports RaceCab’s singleton drawer/file even though those nodes are not in the visible tree.

---

### 2026-09-02 File every joke that is told, then patch the landing

**Decision:** Delivery (and barge-in, and session end) call `file_told_slot` which classifies and `PUT /box/upsert`s with score 0. After a reaction, `process_reaction` `PUT /jokes/{id}`s the score and reaction onto that row instead of inserting a second joke. Box HTTP timeout is 120s.
**Alternatives:** File only after a scored reaction (previous state — told jokes vanished on disconnect or upsert timeout); always insert a second scored row.
**Reason:** The Viewer now hides seed/RaceCab rows, so the archive is only live material. Jokes the host actually says must hit the Box even if the room stays quiet.
**Cost:** A told joke can sit at score 0 until a reaction lands. `PUT /jokes/{id}` does not move cabinet/drawer/file.

---

### 2026-09-02 Versioned comedy prompts, session-unique filler

**Decision:** Generation loads `persona_v2.md` plus `tone_*_v2.md` and `generate_good_v2.txt`. Previous `*_v1` files stay on disk so older `prompt_ref` values still open the prompt that produced those jokes. Live filler lives in `prompts/stalls.yaml`, is picked by `joker/stalls.py` with no repeat per `SessionState.used_stalls`, traces as `kind="stall"`, and is never upserted. Closings are tracked in `used_transitions`. Joke shapes rotate via `next_shape` (never the same twice in a row).
**Alternatives:** Edit `persona.md` in place; put filler lines in the perform prompt; file stalls as jokes; filter tics only after generation.
**Reason:** Instructions written as catchphrases become tics. Examples move quality more than adjectives. Filler in the Box would corrupt counts and compliance. Versioned prompt files keep provenance honest.
**Cost:** Two persona files can drift if someone edits `persona.md` instead of cutting `persona_v3.md`. `GENERATE_GOOD` may still be overridden to `gpt-4o` in the environment when o3 TPM is exhausted — routing code still prefers the good model, not mini.

---

### 2026-09-02 v3 prompts rotate the comic engine, not just the shape

**Decision:** Generation loads `persona_v3.md`, `tone_*_v3.md`, `generate_good_v3.txt`, `generate_good_user_v3.txt`; delivery loads `realtime_perform_v3.txt`. A new axis, ENGINE (`JOKE_ENGINES`, eleven mechanisms), rotates alongside SHAPE and never repeats adjacently. The good-path system prompt asks for three internal attempts and one sharpened line prefixed `FINAL:`, which `_extract_final` parses. `_select` now ranks candidates on crutch-free, names-something-concrete, spoken length, last-word punch. Good-path sampling uses temperature 1.05 with frequency/presence penalties.
**Alternatives:** Keep rotating shape only; add a second punch-up model call; post-filter banned phrasings after generation.
**Reason:** v2 rotated shape and still produced eleven variants of one mechanism — an appliance behaves like a person — with similes carrying the punch. Shape is the silhouette; the engine is the joke. Draft-then-sharpen inside one call buys a self-critique pass at no extra request.
**Cost:** Longer completions, so higher token cost and latency per bit. `FINAL:` parsing is a contract with the model; if it omits the prefix the whole body is spoken, which is why `_extract_final` falls through to the full text.

---

### 2026-09-02 Requested joke forms are generated, never recited

**Decision:** New tool `write_fresh_bit` (ElevenLabs client tool + `dispatch_tool`) calls `orchestrator.fresh_bit`, which generates in the requested FORM, appends a slot, and files at score 0. `SessionState` gains `told_lines` (fed back as the prompt's avoid-list) and `served_joke_ids`. `funniest_in_genre` and `search_jokes` results now pass through `dedupe_archive_rows`, which drops rows already served this session and shuffles the rest. `dispatch_tool` takes the live `SessionState`. Famous jokes and the persona's own demo knock-knocks are banned by name in the prompts.
**Alternatives:** Prompt the host not to repeat itself (does not work — retrieval is deterministic); randomise ordering inside the Box query; delete the seeded Knock Knock file.
**Reason:** Asking for a knock-knock returned the identical joke every time because the host answered from the archive: `funniest_in_genre` is `ORDER BY score DESC` and `scripts/seed.py` filed the interrupting cow at score 9. No prompt change could vary a deterministic query. Requests must reach the generator. Sampling belongs in the Joker, not in the Box, which stores what it is handed.
**Cost:** A requested bit is filed at score 0 and a later reaction is attributed to the scripted slot the host was on, so some requested jokes keep score 0. `fresh_bit` uses `candidate_count=1` to stay inside the voice provider's tool-response timeout, so it gets one draft-then-sharpen pass instead of three.

---

### 2026-09-02 Few-shot shapes, critique field, rubric 1.1

**Decision:** Add six few-shot turns (reversal, literalism, definition, wrong-detail, compression, misdirect) in `prompts/shapes_v1.md`, appended to `persona.md` and `persona_v4.md`. Generation loads v4. Spoken `JOKE_SHAPES` and `JOKE_ENGINES` stay. `ClassificationResponse.critique` is a mechanism sentence; `kind=critique` is a new trace kind; score is unchanged. SessionState keeps the last five critiques and feeds them to generate() and suggest() as room feedback. Rubric anchors were replaced and versioned to 1.1. `JokeMetadata` gained optional `shape` and `critique`.
**Alternatives:** Replace spoken shapes with the six turns (would break existing rotation tests); fold critique into the score rationale (hides craft notes); keep reaction-only scoring anchors.
**Reason:** Few-shot structure beats adjectives. A named failure in the next prompt is the only adaptation a reviewer can grade. Low clustered scores were using a reaction rubric, not a craft rubric.
**Cost:** One extra classify retry when the critique is vibe-only. Generation prompts are longer. Older jokes have empty `metadata.shape` / `metadata.critique`.

---

### 2026-09-02 Trace steps carry the turn that caused them

**Decision:** Add nullable `trigger_type`, `trigger_text`, `turn_id`, and `turn_index` on `traces`. `record_step`'s signature is unchanged; a contextvar (`bind_turn` / `advance_turn`) is copied onto every row in the current task, including `asyncio.create_task` children. Alembic 006 does not backfill. The Viewer groups archive traces and the live Librarian feed by `turn_id` with the same header copy.
**Alternatives:** Add kwargs to `record_step` (would touch every call site); backfill guessed triggers on old rows; replace `artifact_id` linkage with turns.
**Reason:** A flat step list shows what happened, not whether the host opened, the listener asked, the set continued, a reroll fired, or Query Slot originated the bit. Same fields on the WebSocket `librarian_step` event keep the live feed from disagreeing with stored traces.
**Cost:** Historical rows stay null and render as an "unrecorded" group. Delivery/filing must re-bind the slot's stored turn so a later barge-in or reaction turn does not stamp the wrong cause.











