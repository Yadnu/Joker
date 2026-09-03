"""Shared trace layer.

Every model call, decision, and artifact must pass through record_step.
A call that is not recorded here does not exist for grading purposes.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

_LOG = logging.getLogger("shared.trace")

from box.schema.models import Trace

VALID_TRIGGER_TYPES: frozenset[str] = frozenset(
    {
        "cold_open",
        "user_request",
        "set_continuation",
        "reroll",
        "barge_in_recovery",
        "query_slot",
    }
)


@dataclass(frozen=True)
class TurnSnap:
    """Cause and grouping for the current joke chain / listener exchange."""

    turn_id: str
    turn_index: int
    trigger_type: str
    trigger_text: str | None


_current_turn: ContextVar[TurnSnap | None] = ContextVar("trace_turn", default=None)


def opening_trigger_type(session_id: str) -> str:
    """Query Slot sessions are `viewer-…`; the live show is not."""
    return "query_slot" if session_id.startswith("viewer-") else "cold_open"


def current_turn() -> TurnSnap | None:
    return _current_turn.get()


def bind_turn(
    *,
    turn_id: str,
    turn_index: int,
    trigger_type: str,
    trigger_text: str | None,
) -> TurnSnap:
    """Set the turn copied onto every subsequent record_step in this task.

    Does not change the record_step signature. Callers bind at the start of a
    turn; asyncio.create_task copies the context into the child.
    """
    if trigger_type not in VALID_TRIGGER_TYPES:
        raise ValueError(
            f"Invalid trigger_type {trigger_type!r}. "
            f"Must be one of: {sorted(VALID_TRIGGER_TYPES)}"
        )
    if trigger_type in ("cold_open", "set_continuation"):
        trigger_text = None
    snap = TurnSnap(
        turn_id=turn_id,
        turn_index=turn_index,
        trigger_type=trigger_type,
        trigger_text=trigger_text,
    )
    _current_turn.set(snap)
    return snap


def clear_turn() -> None:
    _current_turn.set(None)


def current_turn_fields() -> dict:
    """Keys for librarian_step WebSocket events and Trace rows."""
    snap = current_turn()
    if snap is None:
        return {
            "trigger_type": None,
            "trigger_text": None,
            "turn_id": None,
            "turn_index": None,
        }
    return {
        "trigger_type": snap.trigger_type,
        "trigger_text": snap.trigger_text,
        "turn_id": snap.turn_id,
        "turn_index": snap.turn_index,
    }


def stamp_generation(gen: object) -> None:
    """Copy the current turn onto a SlotGeneration (or any object with the fields)."""
    snap = current_turn()
    if snap is None:
        return
    gen.turn_id = snap.turn_id  # type: ignore[attr-defined]
    gen.turn_index = snap.turn_index  # type: ignore[attr-defined]
    gen.trigger_type = snap.trigger_type  # type: ignore[attr-defined]
    gen.trigger_text = snap.trigger_text  # type: ignore[attr-defined]


def bind_from_generation(gen: object) -> None:
    """Restore the turn that produced this slot so delivery/filing stay attached."""
    turn_id = getattr(gen, "turn_id", None)
    if not turn_id:
        return
    trigger_type = getattr(gen, "trigger_type", None)
    if trigger_type not in VALID_TRIGGER_TYPES:
        return
    bind_turn(
        turn_id=turn_id,
        turn_index=int(getattr(gen, "turn_index", 0) or 0),
        trigger_type=trigger_type,
        trigger_text=getattr(gen, "trigger_text", None),
    )


async def restore_turn_from_artifact(session: AsyncSession, artifact_id: str) -> bool:
    """Rebind the turn that started this artifact's chain, if one was recorded."""
    from sqlalchemy import select

    row = (
        await session.execute(
            select(Trace)
            .where(Trace.artifact_id == artifact_id)
            .where(Trace.turn_id.is_not(None))
            .order_by(Trace.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None or not row.turn_id or not row.trigger_type:
        return False
    if row.trigger_type not in VALID_TRIGGER_TYPES:
        return False
    bind_turn(
        turn_id=row.turn_id,
        turn_index=int(row.turn_index or 0),
        trigger_type=row.trigger_type,
        trigger_text=row.trigger_text,
    )
    return True

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
        # Librarian craft note: one mechanism, stored on metadata.critique.
        "critique",
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

    snap = current_turn()
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
        trigger_type=snap.trigger_type if snap else None,
        trigger_text=snap.trigger_text if snap else None,
        turn_id=snap.turn_id if snap else None,
        turn_index=snap.turn_index if snap else None,
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
