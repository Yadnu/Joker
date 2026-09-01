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
