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
