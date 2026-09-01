# Architecture Decisions

---

## 2026-08-31 — Stack selection

**Decision:** Use FastAPI (Python 3.11) as the sole backend (the Box), with
SQLAlchemy 2.0, Alembic, Pydantic v2, and PostgreSQL. Use Next.js App Router
(TypeScript, Tailwind, TanStack Query) as a client-only frontend that fetches
all data from the FastAPI Box over HTTP. Use pytest for all tests.

**Alternatives considered:**

- Django or Flask instead of FastAPI: both are viable Python backends, but
  FastAPI's async-first design, native Pydantic v2 integration, and automatic
  OpenAPI generation are better suited to a graded, spec-driven API surface.
- Adding Next.js Route Handlers or server actions as a second data plane: this
  would introduce a second backend, split the data contract, and contradict the
  spec requirement that there is exactly one backend and it is FastAPI.

**Reason:** A single FastAPI Box is the graded boundary. Keeping all data logic
there ensures types, migrations, and tests map directly to the spec. The
client-only Next.js constraint eliminates any ambiguity about where business
logic lives.
