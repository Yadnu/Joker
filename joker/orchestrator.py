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

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.models import Trace

from box.schema.records import (
    Attribution,
    JokeRecord,
    Provenance,
    PromptTurn,
    SetId,
    UserContext,
)
from joker import box_client
from joker.generate import generate, next_engine, next_shape, strip_repeated_closings
from joker.latency import LatencyTracker, Stage
from joker.setbuilder import JokeSet, Slot, adapt_set, build_set
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
_REALTIME_TEMPLATE = (_PROMPTS_DIR / "realtime_perform_v3.txt").read_text(encoding="utf-8")


@dataclass
class SlotGeneration:
    """Bookkeeping the orchestrator keeps for one generated slot."""

    joke_id: str
    topic: str
    style: str
    intended_quality: str
    provenance: Provenance
    tone_level: int = 1
    filed_id: str | None = None
    shape: str | None = None
    engine: str | None = None


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
    filing_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_shape: str | None = None
    last_engine: str | None = None
    used_stalls: set[str] = field(default_factory=set)
    used_transitions: set[str] = field(default_factory=set)
    # Every line already generated this session, fed back into the prompt as
    # the avoid-list so a second request for the same form is not the same bit.
    told_lines: list[str] = field(default_factory=list)
    # Archive rows already handed to the host, so a lookup does not keep
    # returning the single highest-scored joke in the genre.
    served_joke_ids: set[str] = field(default_factory=set)


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
    shape = next_shape(last_shape=state.last_shape, slot_idx=slot_idx)
    engine = next_engine(last_engine=state.last_engine)
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
        shape=shape,
        last_shape=state.last_shape,
        engine=engine,
        last_engine=state.last_engine,
        avoid=state.told_lines,
    )
    joke_text = strip_repeated_closings(joke_text, state.used_transitions)
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
        shape=shape,
        engine=engine,
    )
    state.last_shape = shape
    state.last_engine = engine
    state.told_lines.append(joke_text)
    return joke_text


# Forms a listener can ask for by name. The value is what the prompt is told
# to write; the key is what the host heard.
REQUESTABLE_FORMS: dict[str, str] = {
    "knock-knock": "knock-knock joke",
    "riddle": "riddle",
    "pun": "pun",
    "one-liner": "one-liner",
    "dad-joke": "dad joke",
    "limerick": "limerick",
    "story": "story bit",
    "bit": "stand-up bit",
}


async def fresh_bit(
    *,
    state: SessionState,
    session: AsyncSession,
    topic: str,
    form: str = "bit",
    tracker: LatencyTracker | None = None,
) -> dict:
    """Write a NEW bit on request and file it. Never a recital.

    The archive lookups are ordered by score, so a request for a named form
    ("give me a knock-knock") used to return the same top-scored seeded joke
    every time. This path generates instead, feeding every line already used
    this session back in as the avoid-list, so a second request for the same
    form cannot come back the same.
    """
    form_label = REQUESTABLE_FORMS.get(form.strip().lower(), form.strip() or "stand-up bit")
    slot_idx = len(state.joke_set.slots)
    joke_id = f"joke_{uuid.uuid4().hex[:12]}"
    shape = next_shape(last_shape=state.last_shape, slot_idx=slot_idx)
    engine = next_engine(last_engine=state.last_engine)
    tone_level = state.angles[0].tone_level if state.angles else 1

    t0 = time.monotonic()
    joke_text, provenance = await generate(
        joke_id=joke_id,
        topic=topic or form_label,
        tone_level=tone_level,
        style=shape,
        intended_quality="good",
        user_context=_describe_context(state.listener_context),
        set_position=slot_idx + 1,
        session=session,
        shape=shape,
        last_shape=state.last_shape,
        engine=engine,
        last_engine=state.last_engine,
        form=form_label,
        avoid=state.told_lines,
        candidate_count=1,
    )
    if tracker is not None:
        tracker.record(Stage.GENERATION, int((time.monotonic() - t0) * 1000))

    joke_text = strip_repeated_closings(joke_text, state.used_transitions)

    # Give the previously-final slot a transition so the set stays valid, then
    # append the requested bit as the new final slot.
    if state.joke_set.slots:
        prev = state.joke_set.slots[-1]
        if not prev.transition_to_next.strip():
            prev.transition_to_next = (
                f"Listener asked for a {form_label}; the requested bit follows."
            )
    state.joke_set.slots.append(
        Slot(name="bit", joke_id=joke_id, joke_text=joke_text, transition_to_next="")
    )
    state.generations[slot_idx] = SlotGeneration(
        joke_id=joke_id,
        topic=topic or form_label,
        style=shape,
        intended_quality="good",
        provenance=provenance,
        tone_level=tone_level,
        shape=shape,
        engine=engine,
    )
    state.last_shape = shape
    state.last_engine = engine
    state.told_lines.append(joke_text)

    filed = await file_told_slot(state=state, slot_idx=slot_idx, session=session)
    return {
        "joke_text": joke_text,
        "joke_id": (filed or {}).get("joke_id") or joke_id,
        "form": form_label,
        "engine": engine,
        "slot_idx": slot_idx,
    }


def dedupe_archive_rows(
    rows: list[dict],
    state: SessionState,
    limit: int | None = None,
) -> list[dict]:
    """Drop rows already served this session, shuffle, and mark what is handed over.

    `funniest_in_genre` and `search_jokes` both order by score descending, so
    without this the host is handed the same highest-scored joke on every
    lookup. Only the rows actually returned are marked as served.
    """
    import random

    fresh = [r for r in rows if str(r.get("id")) not in state.served_joke_ids]
    if not fresh:
        return []
    random.shuffle(fresh)
    served = fresh[:limit] if limit else fresh
    for row in served:
        state.served_joke_ids.add(str(row.get("id")))
    return served


TOLD_REACTION = "(told on stage; reaction not captured yet)"


async def _relink_and_mark_filed(
    *,
    session: AsyncSession,
    gen: SlotGeneration,
    slot,
    filed_id: str | None,
) -> None:
    if filed_id and gen.joke_id and filed_id != gen.joke_id:
        await session.execute(
            update(Trace)
            .where(Trace.artifact_id == gen.joke_id)
            .values(artifact_id=filed_id)
        )
        gen.joke_id = filed_id
        slot.joke_id = filed_id
    if filed_id:
        gen.filed_id = filed_id


async def _classify_and_upsert_slot(
    *,
    state: SessionState,
    slot_idx: int,
    user_reaction: str,
    result_score: int,
    session: AsyncSession,
    tracker: LatencyTracker | None,
) -> dict:
    slot = state.joke_set.slots[slot_idx]
    gen = state.generations[slot_idx]
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

    filed_id = upsert_result.get("joke_id")
    await _relink_and_mark_filed(
        session=session, gen=gen, slot=slot, filed_id=filed_id
    )
    if classification.category not in state.listener_history:
        state.listener_history.append(classification.category)
    return {
        "score": result_score,
        "category": classification.category,
        "path": list(classification.path),
        "joke_id": filed_id,
        "metadata": metadata,
        "classification": classification,
    }


async def file_told_slot(
    *,
    state: SessionState,
    slot_idx: int,
    session: AsyncSession,
    tracker: LatencyTracker | None = None,
) -> dict | None:
    """File a joke the host actually told, before (or without) a reaction.

    Score is 0 until process_reaction updates the landing. Skips if this slot
    is already in the Box so delivery and session-end flushes are idempotent.
    """
    if slot_idx not in state.generations:
        return None
    async with state.filing_lock:
        gen = state.generations[slot_idx]
        if gen.filed_id:
            return {"joke_id": gen.filed_id, "already_filed": True}
        return await _classify_and_upsert_slot(
            state=state,
            slot_idx=slot_idx,
            user_reaction=TOLD_REACTION,
            result_score=0,
            session=session,
            tracker=tracker,
        )


async def file_unfiled_slots(
    *,
    state: SessionState,
    session: AsyncSession,
) -> None:
    """Persist every generated slot that never made it through upsert."""
    for slot_idx in list(state.generations):
        await file_told_slot(state=state, slot_idx=slot_idx, session=session)


async def process_reaction(
    *,
    state: SessionState,
    slot_idx: int,
    user_reaction: str,
    session: AsyncSession,
    tracker: LatencyTracker | None = None,
) -> dict:
    """Score, classify, extract metadata, and file the joke just delivered.

    Runs score() -> classify() -> extract_metadata() -> upsert_joke() (or
    update an already-filed row if delivery already persisted the joke).
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

    async with state.filing_lock:
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

        t_file = time.monotonic()
        if gen.filed_id:
            await box_client.update_joke_landing(
                joke_id=gen.filed_id,
                user_reaction=user_reaction,
                score=result_score,
                category=classification.category,
                metadata=metadata,
                session=session,
                api_key=state.box_api_key,
            )
            upsert_result = {"joke_id": gen.filed_id}
        else:
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

        filed_id = upsert_result.get("joke_id")
        await _relink_and_mark_filed(
            session=session, gen=gen, slot=slot, filed_id=filed_id
        )

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
        "path": list(classification.path),
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
    """Fill prompts/realtime_perform_v3.txt with the current set script."""
    lines = [
        f"{i + 1}. [{slot.name}] {slot.joke_text}"
        for i, slot in enumerate(state.joke_set.slots)
    ]
    return _REALTIME_TEMPLATE.format(set_script="\n".join(lines)).strip()


def opening_instructions() -> str:
    """Short persona prompt for the first 2 seconds. No set script, no Box."""
    return (
        "You are Eddie Voss, host of The Late Word. You perform for a room. "
        "You do not serve a user. Open immediately in character. "
        "A set script will arrive as a contextual update; until then keep "
        "talking. No chatbot greeting. No 'how can I help you.' "
        "Never say 'your move' or 'talk to me.'"
    )


def pick_cold_open() -> str:
    """Rotate a spoken cold open from prompts/persona_v3.md. No model, no Box."""
    import random

    text = (_PROMPTS_DIR / "persona_v3.md").read_text(encoding="utf-8")
    start = text.find("## COLD OPENS")
    if start < 0:
        return "Look, the lights are up, which means we have to start."
    nxt = text.find("\n## ", start + 5)
    block = text[start:nxt if nxt >= 0 else None]
    items: list[str] = []
    buf: list[str] = []
    for line in block.splitlines()[1:]:
        if line.startswith("- "):
            if buf:
                items.append(" ".join(buf).strip())
            buf = [line[2:].strip()]
        elif line.strip() and buf:
            buf.append(line.strip())
    if buf:
        items.append(" ".join(buf).strip())
    return random.choice(items) if items else "Look, the lights are up, which means we have to start."


_COLD_OPEN_SYSTEM = (
    "You write lines for a live stage performance. "
    "Generate 2-3 sentences for Eddie Voss to speak the instant the show begins. "
    "No stage directions, no quotation marks, no 'Hello' or 'Good evening' or 'Welcome'. "
    "Start mid-thought as if he's already been in the room. "
    "Do not hand the floor back. Do not say your move, talk to me, hit me, over to you. "
    "Keep talking. Match his sarcastic, spoken voice."
)


async def generate_cold_open(
    state: SessionState,
    session: AsyncSession,
) -> str:
    """Generate a fresh, per-session cold open for Eddie Voss.

    Uses gpt-4o-mini for speed (< 500 ms typical).  Temperature 1.0 produces
    variance across sessions so the opening never sounds scripted.
    Traced so the model call is on the record.
    """
    persona_text = (_PROMPTS_DIR / "persona_v3.md").read_text(encoding="utf-8").strip()
    angles_summary = "; ".join(
        f"{a.genre}/{a.topic}" for a in state.angles[:3]
    ) or "general material"

    user_msg = (
        f"CHARACTER:\n{persona_text}\n\n"
        f"Tonight's set covers: {angles_summary}\n\n"
        "Write the cold open now."
    )

    client = AsyncOpenAI()
    t0 = time.monotonic()
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _COLD_OPEN_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=1.0,
        max_tokens=120,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    text = (response.choices[0].message.content or "").strip()

    await record_step(
        artifact_id=state.joke_set.set_id,
        artifact_type="set",
        kind="generation",
        actor="joker.orchestrator",
        model="gpt-4o-mini",
        prompt_ref="prompts/persona_v3.md",
        inputs={"angles": angles_summary},
        output={"cold_open": text},
        rationale=(
            "Generated a per-session cold open from the host persona and tonight's "
            "set angles so the host speaks unprompted on connect and the opening "
            "varies between sessions."
        ),
        latency_ms=latency_ms,
        cost=None,
        session=session,
    )
    return text


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
