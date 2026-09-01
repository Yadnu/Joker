---
name: trace
description: Use when adding or modifying any component that calls a model, makes a decision, or produces an artifact.
version: "1.1.0"
---

# Trace

Every model call, decision, and artifact must be recorded via `shared/trace.py`.
A call that is not recorded via this module does not exist for grading purposes.

## Signature

```python
async def record_step(
    *,
    artifact_id: str,
    artifact_type: str,
    kind: str,
    actor: str,
    model: str | None,
    prompt_ref: str | None,
    inputs: dict,
    output: dict,
    rationale: str,
    latency_ms: int,
    cost: float | None,
    session: AsyncSession,
) -> None: ...
```

All arguments are keyword-only. `rationale` is required and has **no default**.
Omitting it is a `TypeError`. An empty string raises `ValueError`.

The `session` argument is the active `AsyncSession` for the current request.
`record_step` calls `session.flush()` but does not commit; the caller owns
the transaction boundary.

## Field descriptions

| Argument | Notes |
|----------|-------|
| `artifact_id` | Identifier of the primary artifact (joke_id, set_id, category label, …) |
| `artifact_type` | Kind of artifact: `"joke"`, `"set"`, `"category"`, `"score"`, … |
| `kind` | One of the eleven valid step kinds (see below) |
| `actor` | Component path: `"librarian.classify"`, `"joker.generate"`, … |
| `model` | Model name if a model was called; `None` otherwise |
| `prompt_ref` | Stable reference to the prompt template, if any |
| `inputs` | Serialisable dict of all inputs to this step |
| `output` | Serialisable dict of all outputs from this step |
| `rationale` | **Required.** One or more sentences explaining the decision |
| `latency_ms` | Wall-clock time for this step in milliseconds |
| `cost` | Estimated USD cost of any model call; `None` if no model was called |

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

Any string not in this list raises `ValueError`.

## Worked example — single joke, generation through filing

```python
from shared.trace import record_step
import time

t0 = time.monotonic()
# ... call model ...
ms = int((time.monotonic() - t0) * 1000)

await record_step(
    artifact_id="joke_a1b2c3",
    artifact_type="joke",
    kind="generation",
    actor="joker.generate",
    model="gpt-4o",
    prompt_ref="prompts/generate_good_v1",
    inputs={"topic": "airport security", "style": "one-liner", "intended_quality": "good"},
    output={"joke_text": "I told the TSA agent I packed my own bags. He said, 'That's great—now unpack them.'"},
    rationale="Highest-scoring of three candidates; punchline timing suited one-liner delivery.",
    latency_ms=ms,
    cost=0.0012,
    session=session,
)

await record_step(
    artifact_id="joke_a1b2c3",
    artifact_type="joke",
    kind="classification",
    actor="librarian.classify",
    model="gpt-4o-mini",
    prompt_ref="prompts/classify_v1",
    inputs={"joke_text": "...", "taxonomy_snapshot_version": "2026-08-31"},
    output={"category": "Observational", "is_new": False, "path": ["Travel", "Airports", "Security"]},
    rationale="Joke draws humour from a recognisable everyday inconvenience with no target group; existing label 'Observational' is the closest match.",
    latency_ms=210,
    cost=0.0001,
    session=session,
)

await record_step(
    artifact_id="joke_a1b2c3",
    artifact_type="joke",
    kind="filing",
    actor="joker.file",
    model=None,
    prompt_ref=None,
    inputs={"file_id": "file_security_01", "path": ["Travel", "Airports", "Security"]},
    output={"joke_id": "joke_a1b2c3", "success": True},
    rationale="Path supplied by Librarian; Box upsert succeeded in single transaction.",
    latency_ms=45,
    cost=None,
    session=session,
)
```
