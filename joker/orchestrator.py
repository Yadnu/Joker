"""Joker — orchestration layer wiring the live pipeline together.

This module is the glue `joker/realtime.py` calls into.  Before this module
existed, `realtime.py` never called `suggest()`, `generate()`, `build_set()`,
`score()`, `classify()`, `extract_metadata()`, or `PUT /box/upsert` — nothing
said live was ever traced as a generation, scored, classified, or filed.
See docs/DECISIONS.md 2026-09-01 "realtime.py wired to the batch pipeline
via orchestrator.py".

Joker/Librarian separation
---------------------------
This module imports from `librarian.interface` (the versioned request/
response contract), and from the top-level entry-point functions each
Librarian module exposes — `librarian.suggest.suggest`,
`librarian.classify.classify`, `librarian.score.score`,
`librarian.metadata.extract_metadata`.  It never imports a Librarian
module's private helpers (the leading-underscore functions such as
`_build_prompt` or `_fetch_taxonomy`).  On the Joker side it imports
`joker.generate.generate`, `joker.setbuilder.build_set` /
`joker.setbuilder.adapt_set`, and `joker.box_client.upsert_joke`.  Nothing
here reaches into `librarian.*` internals or exposes `joker.*` internals to
the Librarian — the seam stays exactly where docs/DECISIONS.md 2026-09-01
"Joker and Librarian communicate only through interface.py" put it; this
module is simply the first caller that actually exercises that seam end to
end.

Lifecycle
---------
1. `start_session()`   — before the live WebSocket opens.  Calls
                          `librarian.suggest.suggest()`, then
                          `joker.setbuilder.build_set()` with the returned
                          angles, then traces `kind="placement"` recording
                          which angles were selected into the set and why.
2. `generate_slot()`   — fills in the joke_text for one slot by calling
                          `joker.generate.generate()`.  `intended_quality`
                          is "good" for opener/callback/closer slots and
                          "bad" for the first "bit" slot encountered —
                          AGENTS.md requires deliberate quality variance,
                          and joker/generate.py already traces
                          `kind="generation"` internally for every call.
3. `process_reaction()` — after a reaction is captured (speech_stopped).
                          Calls `librarian.score.score()`, then
                          `librarian.classify.classify()`, then
                          `librarian.metadata.extract_metadata()`, then
                          `joker.box_client.upsert_joke()`, in that order.
                          Each of the first three already traces internally;
                          `box_client.upsert_joke` traces `kind="filing"`.
                          If the score bombs (< BOMB_THRESHOLD), also calls
                          `joker.setbuilder.adapt_set()` (which traces
                          `kind="set_adaptation"` internally) and applies
                          the resulting `RecoveryMove` to session state.

`joker/realtime.py` calls `process_reaction()` via `asyncio.create_task` so
the Librarian round-trip never blocks the audio relay.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.records import (
    Attribution,
    JokeRecord,
    Provenance,
    PromptTurn,
    SetId,
    UserContext,
)
from joker import box_client
from joker.generate import generate
from joker.latency import LatencyTracker, Stage
from joker.setbuilder import JokeSet, adapt_set, build_set
from librarian.interface import (
    Angle,
    ClassificationRequest,
    SuggestionRequest,
    classify,
    extract_metadata,
    score,
    suggest,
)
from shared.trace import record_step

# A bit that scores below this is treated as "bombed" and triggers
# joker.setbuilder.adapt_set() — see FIX 1 item 5 / AGENTS.md.
BOMB_THRESHOLD = 4

_DEFAULT_STYLE = "one-liner"
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_REALTIME_TEMPLATE = (_PROMPTS_DIR / "realtime_perform_v1.txt").read_text(encoding="utf-8")


@dataclass
class SlotGeneration:
    """Bookkeeping the orchestrator keeps for one generated slot."""

    joke_id: str
    topic: str
    style: str
    intended_quality: str
    provenance: Provenance
    tone_level: int = 1


@dataclass
class SessionState:
    """In-memory state threaded through one live session by the orchestrator.

    Not persisted — every decision that matters for grading is written to
    the `traces` table via the functions this module calls; this dataclass
    only holds what the orchestrator needs to sequence the next call.
    """

    session_id: str
    listener_context: UserContext
    taxonomy_snapshot_version: str
    joker_name: str
    account_name: str
    box_api_key: str | None
    angles: list[Angle]
    joke_set: JokeSet
    generations: dict[int, SlotGeneration] = field(default_factory=dict)
    bad_slot_assigned: bool = False
    listener_history: list[str] = field(default_factory=list)
    # Per-tone score history for preference learning.
    # Maps tone_level (1/2/3) -> list of scores recorded this session.
    tone_scores: dict[int, list[int]] = field(default_factory=lambda: {1: [], 2: [], 3: []})
    # How many rerolls have been requested this session (for refusal-line rotation).
    reroll_count: int = 0


async def start_session(
    *,
    session_id: str,
    listener_context: UserContext,
    taxonomy_snapshot_version: str,
    session: AsyncSession,
    listener_history: list[str] | None = None,
    joker_name: str = "joker-v1",
    account_name: str = "joker-live",
    box_api_key: str | None = None,
    tracker: LatencyTracker | None = None,
) -> SessionState:
    """Suggest angles, build a set from them, and trace the placement decision.

    Returns the SessionState the caller must thread into generate_slot()
    and process_reaction() for the rest of the session.
    """
    history = list(listener_history or [])

    t0 = time.monotonic()
    suggestion = await suggest(
        SuggestionRequest(
            user_context=listener_context,
            listener_history=history,
            taxonomy_snapshot_version=taxonomy_snapshot_version,
            preferred_tone_level=None,  # no session data yet
        ),
        session,
    )
    if tracker is not None:
        tracker.record(Stage.SUGGESTION, int((time.monotonic() - t0) * 1000))

    joke_set = await build_set(
        angles=suggestion.angles,
        listener_context=_describe_context(listener_context),
        session=session,
    )

    await record_step(
        artifact_id=joke_set.set_id,
        artifact_type="set",
        kind="placement",
        actor="joker.orchestrator",
        model=None,
        prompt_ref=None,
        inputs={
            "session_id": session_id,
            "angle_count": len(suggestion.angles),
            "angles": [a.model_dump() for a in suggestion.angles],
        },
        output={
            "set_id": joke_set.set_id,
            "slot_count": len(joke_set.slots),
            "selected_angles": [
                {"genre": a.genre, "topic": a.topic, "rationale": a.rationale}
                for a in suggestion.angles
            ],
        },
        rationale=(
            f"Set {joke_set.set_id} was assembled from all "
            f"{len(suggestion.angles)} ranked angle(s) librarian.suggest "
            "returned for this listener; joker.setbuilder chose which angle "
            "backs each of the set's slots. Recorded separately from the "
            "set_construction trace so the placement decision itself "
            "(which angles the set will try, and why suggest ranked them "
            "that way) is auditable via GET /traces/{set_id} independent of "
            "the set's internal slot structure."
        ),
        latency_ms=0,
        cost=None,
        session=session,
    )

    return SessionState(
        session_id=session_id,
        listener_context=listener_context,
        taxonomy_snapshot_version=taxonomy_snapshot_version,
        joker_name=joker_name,
        account_name=account_name,
        box_api_key=box_api_key,
        angles=suggestion.angles,
        joke_set=joke_set,
        listener_history=history,
    )


async def generate_slot(
    *,
    state: SessionState,
    slot_idx: int,
    session: AsyncSession,
    style: str = _DEFAULT_STYLE,
    tracker: LatencyTracker | None = None,
) -> str:
    """Generate the final joke_text for one slot of state.joke_set.

    Every non-"bit" slot (opener, callback, closer) is intended_quality=
    "good".  The FIRST "bit" slot encountered across the session is
    deliberately intended_quality="bad" (AGENTS.md hard requirement: at
    least one bad-quality generation per set); subsequent bit slots are
    "good".  The premise/topic setbuilder wrote into the slot is passed to
    generate() as the topic; generate()'s output replaces slot.joke_text.
    """
    slot = state.joke_set.slots[slot_idx]
    quality = _quality_for_slot(state, slot.name)

    joke_id = f"joke_{uuid.uuid4().hex[:12]}"
    topic = slot.joke_text or f"{slot.name} material"
    # Use the tone_level from the angle that backs this slot, defaulting to 1
    # for slots that were not backed by a Librarian-suggested angle.
    tone_level = _tone_for_slot(state, slot_idx)
    t0 = time.monotonic()
    joke_text, provenance = await generate(
        joke_id=joke_id,
        topic=topic,
        tone_level=tone_level,
        style=style,
        intended_quality=quality,
        user_context=_describe_context(state.listener_context),
        set_position=slot_idx + 1,
        session=session,
    )
    if tracker is not None:
        tracker.record(Stage.GENERATION, int((time.monotonic() - t0) * 1000))

    slot.joke_text = joke_text
    slot.joke_id = joke_id
    state.generations[slot_idx] = SlotGeneration(
        joke_id=joke_id,
        topic=topic,
        style=style,
        intended_quality=quality,
        provenance=provenance,
        tone_level=tone_level,
    )
    return joke_text


async def process_reaction(
    *,
    state: SessionState,
    slot_idx: int,
    user_reaction: str,
    session: AsyncSession,
    tracker: LatencyTracker | None = None,
) -> dict:
    """Score, classify, extract metadata, and file the joke just delivered.

    Runs score() -> classify() -> extract_metadata() -> upsert_joke(), in
    that fixed order, matching the worked example in .cursor/skills/trace.
    If the score bombs (< BOMB_THRESHOLD), also calls adapt_set() and
    replaces state.joke_set with the adapted set.

    Returns a small summary dict for the caller (realtime.py) to log/act on.
    """
    slot = state.joke_set.slots[slot_idx]
    gen = state.generations[slot_idx]
    user_context_str = _describe_context(state.listener_context)

    t_score = time.monotonic()
    result_score = await score(
        joke_id=gen.joke_id,
        joke_text=slot.joke_text,
        user_reaction=user_reaction,
        user_context=user_context_str,
        session=session,
    )
    if tracker is not None:
        tracker.record(Stage.SCORING, int((time.monotonic() - t_score) * 1000))

    t_cls = time.monotonic()
    classification = await classify(
        ClassificationRequest(
            joke_text=slot.joke_text,
            user_reaction=user_reaction,
            taxonomy_snapshot_version=state.taxonomy_snapshot_version,
            suggested_path=_suggested_path_for_slot(state, slot),
        ),
        session,
    )
    if tracker is not None:
        tracker.record(Stage.CLASSIFICATION, int((time.monotonic() - t_cls) * 1000))

    metadata = await extract_metadata(
        joke_id=gen.joke_id,
        joke_text=slot.joke_text,
        tone_level=gen.tone_level,
        session=session,
    )

    record = JokeRecord(
        prompt_responses=[
            PromptTurn(role="system", content=gen.provenance.prompt),
            PromptTurn(role="assistant", content=slot.joke_text),
        ],
        joke_text=slot.joke_text,
        user_reaction=user_reaction,
        score=result_score,
        category=classification.category,
        metadata=metadata,
        user_context=state.listener_context,
        attribution=Attribution(joker=state.joker_name, account=state.account_name),
        provenance=gen.provenance,
        set_id=SetId(set=state.joke_set.set_id, position=slot_idx + 1),
    )

    t_file = time.monotonic()
    upsert_result = await box_client.upsert_joke(
        cabinet=classification.path[0],
        drawer=classification.path[1],
        file=classification.path[2],
        record=record,
        session=session,
        api_key=state.box_api_key,
    )
    if tracker is not None:
        tracker.record(Stage.FILING, int((time.monotonic() - t_file) * 1000))

    if classification.category not in state.listener_history:
        state.listener_history.append(classification.category)

    # Record scored tone level so suggest() can steer future angles.
    state.tone_scores[gen.tone_level].append(result_score)

    recovery_applied: str | None = None
    if result_score < BOMB_THRESHOLD:
        state.joke_set = await adapt_set(
            joke_set=state.joke_set,
            bombed_slot_idx=slot_idx,
            session=session,
        )
        recovery_applied = state.joke_set.recovery.action

    steered = await _steer_remaining(
        state=state,
        just_played=slot_idx,
        session=session,
        tracker=tracker,
    )

    return {
        "score": result_score,
        "category": classification.category,
        "joke_id": upsert_result.get("joke_id"),
        "bombed": result_score < BOMB_THRESHOLD,
        "recovery_applied": recovery_applied,
        "recovery_line": state.joke_set.recovery.line if recovery_applied else None,
        "session_instructions": render_set_instructions(state),
        "steered": steered,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def render_set_instructions(state: SessionState) -> str:
    """Fill prompts/realtime_perform_v1.txt with the current set script."""
    lines = []
    for i, slot in enumerate(state.joke_set.slots):
        transition = slot.transition_to_next or "close the set"
        lines.append(f"{i + 1}. [{slot.name}] {slot.joke_text}  (then: {transition})")
    return _REALTIME_TEMPLATE.format(set_script="\n".join(lines)).strip()


async def _steer_remaining(
    *,
    state: SessionState,
    just_played: int,
    session: AsyncSession,
    tracker: LatencyTracker | None,
) -> bool:
    """Re-query the Librarian for what to try next on unplayed slots."""
    remaining_idx = [
        i for i in range(len(state.joke_set.slots)) if i > just_played
    ]
    if not remaining_idx:
        return False

    t0 = time.monotonic()
    suggestion = await suggest(
        SuggestionRequest(
            user_context=state.listener_context,
            listener_history=state.listener_history,
            taxonomy_snapshot_version=state.taxonomy_snapshot_version,
            preferred_tone_level=_preferred_tone(state),
        ),
        session,
    )
    if tracker is not None:
        tracker.record(Stage.SUGGESTION, int((time.monotonic() - t0) * 1000))

    state.angles = suggestion.angles
    next_idx = remaining_idx[0]
    next_slot = state.joke_set.slots[next_idx]
    chosen = suggestion.angles[0]
    next_slot.joke_text = chosen.topic
    await generate_slot(
        state=state, slot_idx=next_idx, session=session, tracker=tracker
    )

    await record_step(
        artifact_id=state.joke_set.set_id,
        artifact_type="set",
        kind="set_adaptation",
        actor="joker.orchestrator",
        model=None,
        prompt_ref="prompts/suggest_user_v1.txt",
        inputs={
            "just_played": just_played,
            "listener_history": list(state.listener_history),
            "next_angle": chosen.model_dump(),
        },
        output={
            "next_slot_idx": next_idx,
            "next_topic": chosen.topic,
            "next_genre": chosen.genre,
        },
        rationale=(
            f"After slot {just_played}, re-ran suggest() against the archive "
            f"and listener_history={state.listener_history!r}. Steering the "
            f"next slot toward {chosen.genre!r} / {chosen.topic!r}: "
            f"{chosen.rationale}"
        ),
        latency_ms=int((time.monotonic() - t0) * 1000),
        cost=None,
        session=session,
    )
    return True


def _quality_for_slot(state: SessionState, slot_name: str) -> str:
    if slot_name != "bit":
        return "good"
    if not state.bad_slot_assigned:
        state.bad_slot_assigned = True
        return "bad"
    return "good"


def _tone_for_slot(state: SessionState, slot_idx: int) -> int:
    """Return the tone level for this slot.

    If the angle backing this slot has a tone_level, use it.
    Otherwise fall back to the session's preferred tone (or 1 for new sessions).
    """
    slot = state.joke_set.slots[slot_idx]
    for angle in state.angles:
        if angle.topic == (slot.joke_text or "") or angle.genre in (slot.joke_text or ""):
            return max(1, min(3, angle.tone_level))
    # No matching angle — use preferred tone for consistency.
    return _preferred_tone(state) or 1


def _preferred_tone(state: SessionState) -> int | None:
    """Return the tone level with the highest average score, or None if no data."""
    best_tone: int | None = None
    best_avg = -1.0
    for tone, scores in state.tone_scores.items():
        if not scores:
            continue
        avg = sum(scores) / len(scores)
        if avg > best_avg:
            best_avg = avg
            best_tone = tone
    return best_tone


def _suggested_path_for_slot(state: SessionState, slot) -> list[str]:  # noqa: ANN001
    for angle in state.angles:
        if angle.topic == slot.joke_text or angle.genre in (slot.joke_text or ""):
            return [angle.genre]
    return [state.angles[0].genre] if state.angles else []


def _describe_context(ctx: UserContext) -> str:
    """One-line human-readable summary for prompts that take a context string."""
    parts: list[str] = []
    if ctx.age_band is not None:
        parts.append(f"age {ctx.age_band.value}")
    if ctx.region is not None:
        parts.append(f"region {ctx.region}")
    if ctx.occupation_field is not None:
        parts.append(f"occupation {ctx.occupation_field.value}")
    if ctx.energy is not None:
        parts.append(f"energy {ctx.energy.value}")
    if ctx.humor_preferences:
        parts.append("prefers " + ", ".join(s.value for s in ctx.humor_preferences))
    if ctx.humor_avoid:
        parts.append("avoid " + ", ".join(s.value for s in ctx.humor_avoid))
    if ctx.first_time is not None:
        parts.append("first-time listener" if ctx.first_time else "returning listener")
    if ctx.session_notes:
        parts.append(ctx.session_notes)
    return "; ".join(parts) or "no listener context provided"
