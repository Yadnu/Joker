---
name: box-api
description: Use when implementing or modifying any Box API endpoint, the hierarchy schema, upsert logic, or compliance validation.
version: "1.0.0"
---

# Box API

The Box is the sole backend. It is implemented in FastAPI. The Next.js frontend
never adds API routes, server actions, or Next API routes. All data flows through
the Box over HTTP.

## Endpoint list

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness check |
| `GET` | `/box` | Full hierarchy: Box > Cabinet > Drawer > File > Joke |
| `PUT` | `/box/upsert` | File a joke; caller supplies the full path; Box does not infer, default, or repair paths |
| `GET` | `/cabinets` | List all cabinets |
| `GET` | `/cabinets/{cabinet_id}` | Single cabinet with its drawers |
| `GET` | `/drawers/{drawer_id}` | Single drawer with its files |
| `GET` | `/files/{file_id}` | Single file with its jokes |
| `GET` | `/jokes/{joke_id}` | Single joke record |
| `GET` | `/jokes/{joke_id}/trace` | All recorded decisions for that joke (grading / explainability) |
| `GET` | `/compliance` | Live hierarchy compliance query; never a stored flag |

## Upsert rules

- The upsert of cabinet, drawer, file, and joke rows runs in a **single
  transaction** across all four levels. If any level fails the whole operation
  rolls back.
- Concurrent creation of a category row (cabinet, drawer, or file) uses
  `ON CONFLICT DO NOTHING RETURNING`. The upsert selects the existing row when
  RETURNING yields nothing.
- The Box stores what it is handed. Classification intelligence belongs to the
  Librarian, not the Box.

## Compliance

`GET /compliance` executes a live query over the hierarchy tree. Compliance is
never stored as a flag on any row. The query checks:

- Every cabinet has more than one drawer.
- Every drawer has more than one file.
- Every file has more than one joke.

## Error bodies

All 4xx and 5xx responses include a JSON body identifying **the failing level**
and **the reason**:

```json
{
  "level": "file",
  "reason": "File 'Wordplay' has only one joke; hierarchy requires more than one."
}
```

Valid level values: `box` | `cabinet` | `drawer` | `file` | `joke`.

Hierarchy violations ("more than one child" failures) must cite the level and
the specific count found.
