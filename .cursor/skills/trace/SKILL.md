---
name: trace
description: Use when adding or modifying any component that calls a model, makes a decision, or produces an artifact.
version: "1.0.0"
---

# Trace

Every model call, decision, and artifact must be recorded via `shared/trace.py`.
A model call that is not recorded via this module does not exist for grading
purposes.

## Signature

```python
def record_step(*, kind: str, artifact: object, rationale: str, **extra) -> None:
    ...
```

All arguments are keyword-only. `rationale` is required and has **no default**.
Omitting it is a type error.

## Valid step kinds

Only the following values are accepted for `kind`:

| Kind | When to use |
|------|-------------|
| `suggestion` | The Librarian proposes a classification path before committing |
| `generation` | A model generates a joke or other text |
| `placement` | A joke is assigned to a position in a set |
| `delivery` | A joke is sent to the voice channel |
| `reaction_capture` | The user's post-punchline reaction is recorded |
| `scoring` | A score (0–10) is assigned to a joke |
| `classification` | The Librarian assigns a genre/category |
| `filing` | The joke is written to the Box (upsert called) |
| `category_creation` | A new cabinet, drawer, or file row is created |
| `set_construction` | A new set is assembled |
| `set_adaptation` | An existing set is modified in response to live feedback |

Any string not in this list is invalid.

## Worked example — single joke, generation through filing

```python
from shared.trace import record_step

# 1. Model generates the joke
record_step(
    kind="generation",
    artifact={
        "joke_text": "I told the TSA agent I packed my own bags. He said, 'That's great—now unpack them.'"
    },
    rationale="Prompt requested a short observational joke about airport security; this candidate had the tightest punchline of three.",
    model="gpt-4o",
    prompt="Tell me a short joke about airport security.",
    candidates_evaluated=3,
)

# 2. Librarian classifies the joke
record_step(
    kind="classification",
    artifact={"category": "Observational"},
    rationale="Joke draws humour from a recognisable everyday inconvenience with no target group; fits Observational over Satire or Topical.",
)

# 3. Librarian suggests a filing path
record_step(
    kind="suggestion",
    artifact={"path": ["Travel", "Airports", "Security"]},
    rationale="Existing cabinet 'Travel' > drawer 'Airports' > file 'Security' is the closest compliant match; no new category needed.",
)

# 4. Joke is filed into the Box
record_step(
    kind="filing",
    artifact={"joke_id": "joke_a1b2c3", "file_id": "file_security_01"},
    rationale="Path supplied by Librarian; Box upsert succeeded in single transaction.",
)

# 5. Joke delivered over voice
record_step(
    kind="delivery",
    artifact={"joke_id": "joke_a1b2c3", "channel": "voice"},
    rationale="Next joke in set_travel_2026_08_31 at position 3; prior joke scored 7, continuing set.",
)

# 6. User reaction captured
record_step(
    kind="reaction_capture",
    artifact={"user_reaction": "Ha! That's exactly what happened to me last Tuesday."},
    rationale="Captured verbatim immediately after punchline silence window (1.2 s).",
)

# 7. Score assigned
record_step(
    kind="scoring",
    artifact={"score": 8},
    rationale="Positive verbal reaction plus laughter detected; mapped to 8/10 per scoring rubric.",
)
```
