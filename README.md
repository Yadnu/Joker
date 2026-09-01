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

### 5 — Run tests

```bash
python -m pytest -v
```

Tests use `TEST_DATABASE_URL` from `.env`.  Each test runs inside a transaction
that is rolled back, so the test database stays clean between runs.

---

## API reference

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness check |

### Accounts

| Method | Path | Description |
|--------|------|-------------|
| POST | `/accounts` | Create a new account |
| GET | `/accounts` | List all accounts |
| GET | `/accounts/{id}` | Get account by id |

Accounts identify who filed a joke (`account_id` on the upsert body).
**Visibility is always global** — every account can read the entire library.

### Library (write)

| Method | Path | Description |
|--------|------|-------------|
| PUT | `/box/upsert` | File a joke; creates missing cabinet/drawer/file in one transaction |

### Library (read)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/box` | Full tree (cabinet → drawer → file → joke count) |
| GET | `/box/{cabinet}/{drawer}/{file}` | All jokes at a specific path |
| GET | `/export` | Full tree with every joke embedded |
| GET | `/cabinets` | List all cabinets |
| GET | `/cabinets/{id}` | Cabinet with its drawers |
| GET | `/cabinets/{id}/counts` | Drawer / file / joke counts under a cabinet |
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
- ON CONFLICT DO NOTHING on unique constraints ensures concurrent writes to the
  same path produce exactly one set of category levels.
