"""Shared trace layer.

Every model call, decision, and artifact must pass through record_step.
A call that is not recorded here does not exist for grading purposes.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

_LOG = logging.getLogger("shared.trace")

from box.schema.models import Trace

VALID_KINDS: frozenset[str] = frozenset(
    {
        "suggestion",
        "generation",
        "placement",
        "delivery",
        "reaction_capture",
        "scoring",
        "classification",
        "filing",
        "category_creation",
        "set_construction",
        "set_adaptation",
        # Reroll lifecycle: user requests a darker version of a joke.
        # "reroll" records the replacement generation at tone_level+1.
        # "reroll_refused" records the ceiling hit when tone_level is already 3.
        "reroll",
        "reroll_refused",
        # Performance filler covering latency. Never a joke. Never filed.
        "stall",
    }
)


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
) -> None:
    """Write one trace row.

    All arguments are keyword-only.  `rationale` has no default and must be
    a non-empty string explaining why this step was taken.

    Args:
        artifact_id:   Identifier of the primary artifact being recorded
                       (joke_id, set_id, category label, etc.).
        artifact_type: Kind of artifact ("joke", "set", "category", "score", …).
        kind:          One of the kinds listed in VALID_KINDS.
        actor:         Component that produced this step ("librarian.classify",
                       "joker.generate", etc.).
        model:         Model name if a model was called; None otherwise.
        prompt_ref:    Stable reference to the prompt template used, if any.
        inputs:        Serialisable dict of all inputs to this step.
        output:        Serialisable dict of all outputs from this step.
        rationale:     Required.  One or more sentences explaining the decision.
        latency_ms:    Wall-clock time for this step in milliseconds.
        cost:          Estimated USD cost of any model call; None if no call.
        session:       Active AsyncSession for the current request.
    """
    if not kind or kind not in VALID_KINDS:
        raise ValueError(
            f"Invalid trace kind {kind!r}. Must be one of: {sorted(VALID_KINDS)}"
        )
    if not rationale or not rationale.strip():
        raise ValueError("rationale is required and must be a non-empty string.")

    row = Trace(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        kind=kind,
        actor=actor,
        model=model,
        prompt_ref=prompt_ref,
        inputs=inputs,
        output=output,
        rationale=rationale,
        latency_ms=latency_ms,
        cost=cost,
    )
    session.add(row)
    try:
        await session.flush()
    except Exception:
        _LOG.exception(
            "record_step failed artifact_id=%s artifact_type=%s kind=%s actor=%s",
            artifact_id,
            artifact_type,
            kind,
            actor,
        )
        raise
