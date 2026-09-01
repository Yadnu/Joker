# Jokebox

An AI stand-up comedian that tells jokes over live voice, records how each one
lands, files them into a strict taxonomy, and can explain every decision it made.

## Non-negotiable constraints

- The hierarchy is Box > Cabinet > Drawer > File > Joke. Every level must contain
  MORE THAN ONE child. A cabinet with one drawer is non-compliant. A file with
  one joke is non-compliant. Validators enforce this. Never create a singleton to
  make a test pass.
- Every joke record requires provenance: generated or curated, which model, which
  prompt, and the selection rationale. No exceptions.
- There is no "General" category and no catch-all. Every joke is classified into
  a real, specific genre.
- Field names in box/schema/records.py are fixed. Do not rename, pluralize, or
  paraphrase them. They are graded against a written spec.
- The Box stores what it is handed. It does not infer, default, or repair paths.
  All classification intelligence lives in the Librarian.
- Any model call that is not recorded via shared/trace.py does not exist for
  grading purposes.

## Working agreement

- After any non-obvious design decision, append a dated entry to
  docs/DECISIONS.md stating the decision, the alternatives, and the reason.
- Commit after each working slice. Message states what changed and why.
  Never commit "wip" or "fixes".
- Never commit API keys, .env files, or raw audio.

## Stack

Backend: Python 3.11, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, PostgreSQL.
Frontend: Next.js App Router, TypeScript, Tailwind, TanStack Query.
The Next.js app is client-only. It does not use server components for data,
server actions, or Next API routes. All data comes from the FastAPI Box over
HTTP. There is exactly one backend and it is FastAPI.
Tests: pytest.
