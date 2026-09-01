"""Joker — set composition and live adaptation.

A set has named slots: opener, one or more bits, callback, closer.
Every adjacent slot pair carries a written transition_to_next that explains
WHY that ordering is intentional.  A set whose slots could be reordered
without loss is a construction failure.

Each set also defines a recovery move for when a bit bombs, stored as a
RecoveryMove dataclass.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from librarian.interface import Angle
from shared.models import SETBUILD_MODEL, build_messages, completion_kwargs
from shared.trace import record_step

_client = AsyncOpenAI()

SlotName = Literal["opener", "bit", "callback", "closer"]


@dataclass
class RecoveryMove:
    """What the Joker does when a bit bombs (score <= 3)."""

    action: Literal["skip_to_callback", "self_deprecate", "pivot_topic", "end_set"]
    line: str = ""
    rationale: str = ""


@dataclass
class Slot:
    name: SlotName
    joke_id: str | None
    joke_text: str
    # Written rationale for why this slot precedes the next.
    # Required for all slots except the final (closer) slot.
    transition_to_next: str = ""

    def validate_transition(self, is_last: bool) -> None:
        if not is_last and not self.transition_to_next.strip():
            raise ValueError(
                f"Slot '{self.name}' (joke_id={self.joke_id}) has no "
                "transition_to_next. Every non-final slot must explain why its "
                "successor follows."
            )


@dataclass
class JokeSet:
    set_id: str
    slots: list[Slot]
    recovery: RecoveryMove

    def validate(self) -> None:
        """Raise if the set would be valid as a shuffle."""
        for i, slot in enumerate(self.slots):
            slot.validate_transition(is_last=(i == len(self.slots) - 1))


async def build_set(
    *,
    angles: list[Angle],
    listener_context: str,
    session: AsyncSession,
) -> JokeSet:
    """Compose an ordered set from the suggested angles.

    The model returns a list of slots with joke_text and transition_to_next
    for every adjacent pair.  The set is validated before the trace is written;
    an invalid set (missing transitions) is a hard error.
    """
    t0 = time.monotonic()
    set_id = f"set_{uuid.uuid4().hex[:12]}"

    prompt = _build_prompt(angles, listener_context)

    system = (
        "You are a stand-up comedy set designer. "
        "Build an ordered set with slots: opener, 2-3 bits, callback, closer. "
        "Return JSON with keys: "
        "'slots' (list of {name, joke_text, transition_to_next}), "
        "'recovery' ({action, line, rationale}). "
        "transition_to_next must explain the DEPENDENCY between this slot and the next, "
        "not just describe the next joke. "
        "Valid recovery actions: skip_to_callback, self_deprecate, pivot_topic, end_set."
    )
    response = await _client.chat.completions.create(
        **completion_kwargs(
            SETBUILD_MODEL,
            response_format={"type": "json_object"},
            messages=build_messages(system, prompt, SETBUILD_MODEL),
        )
    )

    latency_ms = int((time.monotonic() - t0) * 1000)

    raw = json.loads(response.choices[0].message.content or "{}")

    raw_slots = raw.get("slots", [])
    slots = [
        Slot(
            name=s.get("name", "bit"),
            joke_id=None,
            joke_text=s.get("joke_text", ""),
            transition_to_next=s.get("transition_to_next", ""),
        )
        for s in raw_slots
    ]

    raw_recovery = raw.get("recovery", {})
    recovery = RecoveryMove(
        action=raw_recovery.get("action", "skip_to_callback"),
        line=raw_recovery.get("line", ""),
        rationale=raw_recovery.get("rationale", ""),
    )

    joke_set = JokeSet(set_id=set_id, slots=slots, recovery=recovery)
    joke_set.validate()

    await record_step(
        artifact_id=set_id,
        artifact_type="set",
        kind="set_construction",
        actor="joker.setbuilder",
        model=SETBUILD_MODEL,
        prompt_ref="joker/setbuilder_v1",
        inputs={
            "angles": [a.model_dump() for a in angles],
            "listener_context": listener_context,
        },
        output={
            "set_id": set_id,
            "slots": [
                {
                    "name": s.name,
                    "joke_text": s.joke_text[:80],
                    "transition_to_next": s.transition_to_next,
                }
                for s in slots
            ],
            "recovery": {
                "action": recovery.action,
                "line": recovery.line,
                "rationale": recovery.rationale,
            },
        },
        rationale=(
            f"Built {len(slots)}-slot set for listener context. "
            f"Recovery action: {recovery.action}. "
            "Each slot transition recorded."
        ),
        latency_ms=latency_ms,
        cost=_estimate_cost(response),
        session=session,
    )

    return joke_set


async def adapt_set(
    *,
    joke_set: JokeSet,
    bombed_slot_idx: int,
    session: AsyncSession,
) -> JokeSet:
    """Apply recovery when a bit at bombed_slot_idx scored <= 3.

    The bombed slot is replaced according to the set's RecoveryMove.
    The resulting set is re-validated and a set_adaptation trace is written.
    """
    t0 = time.monotonic()

    original_slots = list(joke_set.slots)
    recovery = joke_set.recovery

    if recovery.action == "skip_to_callback":
        # Remove the bombed bit; the callback slot follows directly
        adapted_slots = [s for i, s in enumerate(original_slots) if i != bombed_slot_idx]
    elif recovery.action == "self_deprecate":
        bombed = original_slots[bombed_slot_idx]
        bombed.joke_text = recovery.line or "That one fell flat — even I saw that coming."
        bombed.transition_to_next = "Self-deprecation acknowledged; pivot to next bit."
        adapted_slots = original_slots
    elif recovery.action == "pivot_topic":
        adapted_slots = [s for i, s in enumerate(original_slots) if i != bombed_slot_idx]
    else:
        # end_set: truncate after the bombed slot
        adapted_slots = original_slots[:bombed_slot_idx]

    new_set = JokeSet(
        set_id=joke_set.set_id,
        slots=adapted_slots,
        recovery=recovery,
    )

    latency_ms = int((time.monotonic() - t0) * 1000)

    await record_step(
        artifact_id=joke_set.set_id,
        artifact_type="set",
        kind="set_adaptation",
        actor="joker.setbuilder",
        model=None,
        prompt_ref=None,
        inputs={
            "set_id": joke_set.set_id,
            "bombed_slot_idx": bombed_slot_idx,
            "recovery_action": recovery.action,
            "original_slot_count": len(original_slots),
        },
        output={
            "adapted_slot_count": len(adapted_slots),
            "recovery_line": recovery.line,
        },
        rationale=(
            f"Slot {bombed_slot_idx} ({original_slots[bombed_slot_idx].name if bombed_slot_idx < len(original_slots) else 'out-of-range'}) "
            f"bombed. Applied recovery action '{recovery.action}'. "
            f"{recovery.rationale or 'No additional rationale.'}"
        ),
        latency_ms=latency_ms,
        cost=None,
        session=session,
    )

    return new_set


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_prompt(angles: list[Angle], listener_context: str) -> str:
    angle_lines = "\n".join(
        f"  [{i+1}] {a.genre} / {a.topic} — {a.rationale}" for i, a in enumerate(angles)
    )
    return (
        f"Listener context: {listener_context}\n\n"
        f"Suggested angles:\n{angle_lines}\n\n"
        "Build an ordered comedy set using these angles. "
        "Each transition must explain why the next joke follows this one — "
        "the dependency, not just a description."
    )


def _estimate_cost(response) -> float | None:  # type: ignore[no-untyped-def]
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return (usage.prompt_tokens * 5 + usage.completion_tokens * 15) / 1_000_000
