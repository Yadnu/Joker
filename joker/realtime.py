"""Joker — full-duplex voice over FastAPI WebSocket.

Architecture
------------
One FastAPI WebSocket endpoint bridges the browser to the voice provider
selected by the VOICE_PROVIDER environment variable (default: elevenlabs):

    Client ── audio / JSON ──> voice_session.send_audio()  ──> Provider
    Client <── audio + events ─ VoiceCallbacks ─────────── <── Provider

Both directions run concurrently; the input relay loop calls send_audio()
while the provider fires VoiceCallbacks.  Strict turn-taking is not used.

Barge-in handling
-----------------
When the provider signals barge-in (on_barge_in callback):
  1. The VoiceSession has already cancelled in-flight TTS.
  2. The orchestrator writes a delivery trace recording what was cut.
  3. A typed barge_in event is sent to the browser.
  4. session.speak(BARGE_IN_ACK) asks the provider for an in-character ack.

Batch-pipeline wiring
---------------------
`joker/orchestrator.py` is the glue between this module and the Librarian.
Before the voice session opens, start_session() → build_set() → generate()
run for every slot.  The generated lines are given to the voice session as
the system prompt.  When the user reacts, process_reaction() runs off the
audio-relay hot path via asyncio.create_task.

Provider isolation
------------------
All provider-specific code lives in joker/voice/.  This module imports only
from joker.voice.  Nothing here references websockets, elevenlabs, or openai
SDKs directly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.records import UserContext
from joker import orchestrator
from joker.latency import LatencyTracker, Stage
from joker.timing import mark as tmark
from joker.timing import now as tnow
from joker.tools import dispatch_tool
from joker.stalls import pick_stall
from joker.voice import VoiceCallbacks, make_voice_session
from shared.db import session_maker
from shared.trace import (
    bind_from_generation,
    bind_turn,
    current_turn,
    current_turn_fields,
    record_step,
)

_LOG = logging.getLogger(__name__)

router = APIRouter()

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
BARGE_IN_ACK = (_PROMPTS_DIR / "realtime_ack_v1.txt").read_text(encoding="utf-8").strip()

# Provider name for trace records (set from VOICE_PROVIDER at import time)
_VOICE_PROVIDER = os.environ.get("VOICE_PROVIDER", "elevenlabs")
_TRACE_MODEL = (
    "elevenlabs-convai" if _VOICE_PROVIDER == "elevenlabs" else "gpt-realtime-2.1"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _emit(ws: WebSocket, event: dict) -> None:
    """Send a typed custom event to the client WebSocket.

    Silently swallows send errors so the relay hot-path is never blocked.
    librarian_step events carry the same turn/trigger fields as the Trace row.
    """
    if event.get("type") == "librarian_step":
        event = {**current_turn_fields(), **event}
    try:
        await ws.send_json(event)
    except Exception:
        pass


async def _isolated_record_step(**kwargs: Any) -> None:
    """Write a trace on its own DB session so it cannot flush the audio loop."""
    try:
        factory = session_maker()
        async with factory() as session:
            await record_step(session=session, **kwargs)
            await session.commit()
    except Exception:
        _LOG.exception("isolated trace failed")


async def _keep_flushed_traces(session: Any) -> None:
    """Commit whatever record_step already flushed, even if a later step failed.

    Score/classify/generate traces must survive a Box upsert timeout. record_step
    only flushes; without this commit the session rollback drops the audit trail.
    """
    try:
        await session.commit()
    except Exception:
        _LOG.exception("trace commit failed")
        try:
            await session.rollback()
        except Exception:
            pass


async def _speak_stall(
    *,
    vs: Any,
    state: Any,
    category: str,
    session_id: str,
    wait: str,
    topic: str | None = None,
) -> None:
    """Speak unused filler. Trace as stall. Never file to the Box."""
    if vs is None or state is None:
        return
    line = pick_stall(category, state, topic=topic)
    if not line:
        return
    t0 = time.monotonic()
    try:
        await vs.speak(line)
    except Exception:
        _LOG.exception("stall speak failed category=%s", category)
        return
    ms = max(0, int((time.monotonic() - t0) * 1000))
    await _isolated_record_step(
        artifact_id=session_id,
        artifact_type="session",
        kind="stall",
        actor="joker.realtime",
        model=None,
        prompt_ref="prompts/stalls.yaml",
        inputs={
            "category": category,
            "wait": wait,
            "topic": topic,
            "filed": False,
        },
        output={"line": line, "filed": False},
        rationale=(
            f"Filler covering {wait}. Performance only — not a joke, "
            "not scored, not assigned a genre, not filed to the Box."
        ),
        latency_ms=ms,
        cost=None,
    )


async def _file_told_task(
    *,
    session_state: orchestrator.SessionState,
    slot_idx: int,
    client_ws: WebSocket,
) -> None:
    """Classify and upsert a delivered (or cut) joke so the archive is not empty."""
    gen = session_state.generations.get(slot_idx)
    if gen is not None:
        bind_from_generation(gen)
    try:
        factory = session_maker()
        async with factory() as db_session:
            try:
                result = await orchestrator.file_told_slot(
                    state=session_state,
                    slot_idx=slot_idx,
                    session=db_session,
                )
                await db_session.commit()
            except Exception:
                await _keep_flushed_traces(db_session)
                raise
        if result and not result.get("already_filed"):
            path_parts = result.get("path") or []
            filed_path = " › ".join(path_parts) if path_parts else result.get("category", "")
            await _emit(client_ws, {
                "type": "librarian_step",
                "kind": "filed",
                "actor": "joker.box_client",
                "model": None,
                "latency_ms": 0,
                "rationale": f"Filed as told at {filed_path}.",
                "payload": {
                    "path": filed_path,
                    "joke_id": result.get("joke_id"),
                    "told": True,
                },
                "joke_id": result.get("joke_id"),
            })
    except Exception:
        _LOG.exception("file_told_slot failed; session-end flush may retry")


async def _flush_unfiled_slots(state: orchestrator.SessionState) -> None:
    try:
        factory = session_maker()
        async with factory() as db_session:
            try:
                await orchestrator.file_unfiled_slots(state=state, session=db_session)
                await db_session.commit()
            except Exception:
                await _keep_flushed_traces(db_session)
                raise
    except Exception:
        _LOG.exception("session-end file_unfiled_slots failed")


def _spawn(tasks: set[asyncio.Task], coro: Any) -> asyncio.Task:
    task = asyncio.create_task(coro)
    tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            _LOG.exception("background task failed: %s", exc)

    task.add_done_callback(_done)
    return task


def _score_anchor(score: int) -> str:
    if score <= 3:
        return "bombed"
    if score <= 5:
        return "tepid"
    if score <= 7:
        return "landed"
    if score <= 9:
        return "strong"
    return "killed"


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws/session/{session_id}")
async def voice_session(websocket: WebSocket, session_id: str) -> None:
    """Full-duplex voice bridge between the browser and the active voice provider.

    Voice first. Librarian suggest/generate run in the background after
    the host is already talking. The opening line is picked from
    prompts/persona.md with no model call and no Box query.
    """
    await websocket.accept()
    t0 = tnow()
    tmark(t0, "server_ws_accepted")

    tracker = LatencyTracker()
    listener_context = _listener_context_from_query(websocket.query_params)
    state_box: list[Any] = [None]
    background_tasks: set[asyncio.Task] = set()

    if True:
        current_slot_idx = 0
        interrupted_current = False
        reaction_transcript_parts: list[str] = []
        delivery_start_time: float | None = None
        first_audio_logged = False
        topic_acked_this_window = False

        # voice_session_ref is set after the session is created but before
        # callbacks fire — it is safe because start() runs before any events.
        voice_session_ref: list[Any] = [None]  # mutable cell for the closure

        # ------------------------------------------------------------------
        # Callbacks
        # ------------------------------------------------------------------

        async def on_audio_chunk(data: bytes) -> None:
            nonlocal first_audio_logged
            if not first_audio_logged:
                first_audio_logged = True
                tmark(t0, "first_audio_byte", f"bytes={len(data)}")
            try:
                await websocket.send_bytes(data)
            except Exception:
                pass

        async def on_delivery_start() -> None:
            nonlocal delivery_start_time
            delivery_start_time = time.monotonic()
            tracker.record(Stage.TTS_FIRST_BYTE, 0)

        async def on_delivery_done(latency_ms: int, text: str) -> None:
            nonlocal current_slot_idx, delivery_start_time
            elapsed = (
                int((time.monotonic() - delivery_start_time) * 1000)
                if delivery_start_time is not None
                else latency_ms
            )
            session_state = state_box[0]
            delivered_slot = None
            gen = None
            if session_state is not None and current_slot_idx < len(session_state.joke_set.slots):
                delivered_slot = session_state.joke_set.slots[current_slot_idx]
                gen = session_state.generations.get(current_slot_idx)
            if gen is not None:
                bind_from_generation(gen)
            _spawn(background_tasks, _isolated_record_step(
                artifact_id=(gen.joke_id if gen else session_id),
                artifact_type="joke" if gen else "session",
                kind="delivery",
                actor="joker.realtime",
                model=_TRACE_MODEL,
                prompt_ref="prompts/realtime_perform_v3.txt",
                inputs={
                    "session_id": session_id,
                    "slot_idx": current_slot_idx,
                    "joke_text": delivered_slot.joke_text if delivered_slot else "",
                    "provider": _VOICE_PROVIDER,
                },
                output={"interrupted": False, "text": text[:200]},
                rationale=(
                    f"Completed delivery of slot {current_slot_idx} "
                    f"via {_VOICE_PROVIDER} ({elapsed} ms)."
                ),
                latency_ms=elapsed,
                cost=None,
            ))
            await _emit(websocket, {
                "type": "librarian_step",
                "kind": "delivery",
                "actor": "joker.realtime",
                "model": _TRACE_MODEL,
                "latency_ms": elapsed,
                "rationale": (
                    f"Completed delivery of slot {current_slot_idx} "
                    f"via {_VOICE_PROVIDER} ({elapsed} ms)."
                ),
                "payload": {
                    "slot_idx": current_slot_idx,
                    "joke_text": delivered_slot.joke_text if delivered_slot else "",
                    "interrupted": False,
                },
                "joke_id": gen.joke_id if gen else None,
            })
            await _emit(websocket, {
                "type": "set_position",
                "current": current_slot_idx + 1,
                "total": (
                    len(session_state.joke_set.slots)
                    if session_state is not None else 0
                ),
            })
            delivery_start_time = None
            if (
                session_state is not None
                and current_slot_idx in session_state.generations
            ):
                _spawn(
                    background_tasks,
                    _file_told_task(
                        session_state=session_state,
                        slot_idx=current_slot_idx,
                        client_ws=websocket,
                    ),
                )

        async def on_agent_transcript_delta(delta: str) -> None:
            if delta:
                await _emit(websocket, {
                    "type": "transcript_delta",
                    "speaker": "host",
                    "delta": delta,
                })

        async def on_agent_transcript_done(text: str) -> None:
            await _emit(websocket, {
                "type": "joke_turn",
                "speaker": "host",
                "content": text,
            })

        async def on_user_transcript(transcript: str) -> None:
            nonlocal reaction_transcript_parts, topic_acked_this_window
            if transcript:
                reaction_transcript_parts.append(transcript)
                await _emit(websocket, {
                    "type": "transcript_delta",
                    "speaker": "user",
                    "delta": transcript,
                })
                # Topic-aware filler while the next bit loads. Never filed.
                if (
                    not topic_acked_this_window
                    and len(transcript.split()) >= 1
                    and state_box[0] is not None
                    and voice_session_ref[0] is not None
                ):
                    topic_acked_this_window = True
                    _spawn(
                        background_tasks,
                        _speak_stall(
                            vs=voice_session_ref[0],
                            state=state_box[0],
                            category="topic_acknowledgment",
                            session_id=session_id,
                            wait="listener_named_topic",
                            topic=transcript,
                        ),
                    )

        async def on_barge_in(cut_text: str, at_ms: int) -> None:
            nonlocal interrupted_current
            interrupted_current = True
            session_state = state_box[0]
            cut_slot = (
                session_state.joke_set.slots[current_slot_idx]
                if session_state is not None
                and current_slot_idx < len(session_state.joke_set.slots)
                else None
            )

            async def _cancel() -> None:
                pass  # already cancelled by VoiceSession

            async def _send_ack() -> None:
                await _emit(websocket, {"type": "barge_in_ack", "text": BARGE_IN_ACK})

            async def _speak_ack() -> None:
                vs = voice_session_ref[0]
                if vs is not None:
                    await vs.speak(BARGE_IN_ACK)

            if session_state is not None:
                orchestrator.advance_turn(session_state, "barge_in_recovery", None)

            await handle_speech_started(
                session_id=session_id,
                session=None,
                synthesis_elapsed_ms=at_ms,
                cancel_synthesis=_cancel,
                send_ack=_send_ack,
                speak_ack=_speak_ack,
                slot_idx=current_slot_idx,
                joke_text=(cut_slot.joke_text if cut_slot else ""),
            )
            await _emit(websocket, {
                "type": "barge_in",
                "cut_text": cut_slot.joke_text if cut_slot else cut_text,
                "at_ms": at_ms,
            })
            if (
                session_state is not None
                and current_slot_idx in session_state.generations
            ):
                _spawn(
                    background_tasks,
                    _file_told_task(
                        session_state=session_state,
                        slot_idx=current_slot_idx,
                        client_ws=websocket,
                    ),
                )

        async def on_user_speech_stop() -> None:
            nonlocal interrupted_current, reaction_transcript_parts, current_slot_idx, topic_acked_this_window
            skip_file = interrupted_current
            interrupted_current = False

            session_state = state_box[0]
            if (
                not skip_file
                and session_state is not None
                and current_slot_idx in session_state.generations
            ):
                gen_for_turn = session_state.generations[current_slot_idx]
                if gen_for_turn.trigger_type:
                    orchestrator.advance_turn(
                        session_state,
                        gen_for_turn.trigger_type,
                        gen_for_turn.trigger_text,
                    )
                else:
                    bind_from_generation(gen_for_turn)

            _spawn(background_tasks, _isolated_record_step(
                artifact_id=session_id,
                artifact_type="session",
                kind="reaction_capture",
                actor="joker.realtime",
                model=_TRACE_MODEL,
                prompt_ref=None,
                inputs={
                    "session_id": session_id,
                    "slot_idx": current_slot_idx,
                    "interrupted": skip_file,
                    "provider": _VOICE_PROVIDER,
                },
                output={"event": "speech_stopped"},
                rationale=(
                    "User finished speaking; reaction window closed."
                    + (" Barged slot still filed as told." if skip_file else "")
                ),
                latency_ms=0,
                cost=None,
            ))
            tracker.record(Stage.REACTION, 0)
            await _emit(websocket, {"type": "session_state", "state": "idle"})

            if (
                not skip_file
                and session_state is not None
                and current_slot_idx < len(session_state.joke_set.slots)
                and current_slot_idx in session_state.generations
            ):
                user_reaction = " ".join(reaction_transcript_parts).strip() or (
                    "(no speech transcript captured for this reaction window)"
                )
                gen_data = session_state.generations.get(current_slot_idx)
                await _emit(websocket, {
                    "type": "librarian_step",
                    "kind": "reaction",
                    "actor": "joker.realtime",
                    "model": None,
                    "latency_ms": 0,
                    "rationale": "User finished speaking; reaction window closed.",
                    "payload": {
                        "slot_idx": current_slot_idx,
                        "transcript": user_reaction,
                    },
                    "joke_id": gen_data.joke_id if gen_data else None,
                })
                _spawn(
                    background_tasks,
                    _process_reaction_task(
                        session_state=session_state,
                        slot_idx=current_slot_idx,
                        user_reaction=user_reaction,
                        voice_session_ref=voice_session_ref,
                        client_ws=websocket,
                        tracker=tracker,
                    ),
                )
                current_slot_idx += 1
            elif skip_file:
                current_slot_idx += 1

            reaction_transcript_parts = []
            topic_acked_this_window = False

        async def on_tool_call(name: str, args: dict) -> Any:
            try:
                factory = session_maker()
                async with factory() as session:
                    try:
                        result = await dispatch_tool(
                            name, args, session, state=state_box[0]
                        )
                        await session.commit()
                    except Exception:
                        await _keep_flushed_traces(session)
                        raise
                    return result
            except Exception:
                _LOG.exception("tool call %s failed", name)
                return {"error": "tool_failed"}

        async def on_state_change(state: str) -> None:
            await _emit(websocket, {"type": "session_state", "state": state})

        async def on_provider_error(message: str) -> None:
            await _emit(websocket, {"type": "error", "message": message})

        # ------------------------------------------------------------------
        # Voice session lifecycle
        # ------------------------------------------------------------------

        callbacks = VoiceCallbacks(
            on_audio_chunk=on_audio_chunk,
            on_delivery_start=on_delivery_start,
            on_delivery_done=on_delivery_done,
            on_agent_transcript_delta=on_agent_transcript_delta,
            on_agent_transcript_done=on_agent_transcript_done,
            on_user_transcript=on_user_transcript,
            on_barge_in=on_barge_in,
            on_user_speech_stop=on_user_speech_stop,
            on_tool_call=on_tool_call,
            on_state_change=on_state_change,
            on_provider_error=on_provider_error,
        )

        vs = make_voice_session(callbacks)
        voice_session_ref[0] = vs

        try:
            cold_open = orchestrator.pick_cold_open()
            tmark(t0, "cold_open_picked")
            await vs.start(
                system_prompt=orchestrator.opening_instructions(),
                first_message=cold_open,
            )
            tmark(t0, "voice_start_returned")

            async def _warmup() -> None:
                try:
                    factory = session_maker()
                    async with factory() as db:
                        try:
                            tmark(t0, "warmup_suggest_start")
                            state = await orchestrator.start_session(
                                session_id=session_id,
                                listener_context=listener_context,
                                taxonomy_snapshot_version=date.today().isoformat(),
                                session=db,
                                joker_name=os.environ.get("JOKER_NAME", "joker-v1"),
                                account_name=os.environ.get("BOX_ACCOUNT_NAME", "joker-live"),
                                box_api_key=os.environ.get("BOX_API_KEY"),
                                tracker=tracker,
                            )
                            await db.commit()
                            state_box[0] = state
                            tmark(
                                t0,
                                "suggest_and_set_done",
                                f"slots={len(state.joke_set.slots)}",
                            )
                            await _emit(websocket, {"type": "session_state", "state": "connected"})
                            await _emit(websocket, {
                                "type": "librarian_step",
                                "kind": "suggestion",
                                "actor": "librarian.suggest",
                                "model": None,
                                "latency_ms": 0,
                                "rationale": (
                                    state.angles[0].rationale if state.angles
                                    else "No angles returned."
                                ),
                                "payload": {
                                    "angles": [
                                        {
                                            "genre": a.genre,
                                            "topic": a.topic,
                                            "rationale": a.rationale,
                                            "tone_level": a.tone_level,
                                        }
                                        for a in state.angles
                                    ],
                                    "slot_count": len(state.joke_set.slots),
                                },
                                "joke_id": None,
                            })
                            for slot_idx in range(len(state.joke_set.slots)):
                                v = voice_session_ref[0]
                                stall = (
                                    _speak_stall(
                                        vs=v,
                                        state=state,
                                        category="thinking",
                                        session_id=session_id,
                                        wait=f"generate_slot_{slot_idx}",
                                    )
                                    if v is not None
                                    else asyncio.sleep(0)
                                )
                                await asyncio.gather(
                                    orchestrator.generate_slot(
                                        state=state,
                                        slot_idx=slot_idx,
                                        session=db,
                                        tracker=tracker,
                                    ),
                                    stall,
                                )
                                await db.commit()
                                gen = state.generations.get(slot_idx)
                                slot = state.joke_set.slots[slot_idx]
                                if gen is not None:
                                    await _emit(websocket, {
                                        "type": "librarian_step",
                                        "kind": "generation",
                                        "actor": "joker.generate",
                                        "model": gen.provenance.model,
                                        "latency_ms": 0,
                                        "rationale": gen.provenance.selection_rationale,
                                        "payload": {
                                            "slot_idx": slot_idx,
                                            "slot_name": slot.name,
                                            "topic": gen.topic,
                                            "tone_level": gen.tone_level,
                                            "intended_quality": gen.intended_quality,
                                            "prompt_ref": gen.provenance.prompt,
                                            "slot_count": len(state.joke_set.slots),
                                        },
                                        "joke_id": gen.joke_id,
                                    })
                            tmark(t0, "all_slots_generated")
                            v = voice_session_ref[0]
                            if v is not None:
                                await v.update_instructions(
                                    orchestrator.render_set_instructions(state)
                                )
                            tmark(t0, "set_instructions_pushed")
                        except Exception:
                            await _keep_flushed_traces(db)
                            raise
                except Exception:
                    _LOG.exception("warmup failed; host keeps talking")

            _spawn(background_tasks, _warmup())
            await asyncio.gather(
                _relay_browser_to_voice(websocket, vs),
                vs.wait(),
            )
        except WebSocketDisconnect:
            tmark(t0, "browser_ws_disconnect")
        finally:
            print(
                f"[timing] session_end +{int((time.monotonic() - t0) * 1000)}ms",
                flush=True,
            )
            await vs.close()
            leftover = state_box[0]
            if leftover is not None:
                _spawn(background_tasks, _flush_unfiled_slots(leftover))
            if background_tasks:
                await asyncio.gather(*background_tasks, return_exceptions=True)
            tracker.flush_to_topography(Path("docs/TOPOGRAPHY.md"))


def _listener_context_from_query(query_params) -> UserContext:  # noqa: ANN001
    def _str(name: str) -> str | None:
        value = query_params.get(name)
        return value or None

    def _list(name: str) -> list[str]:
        value = query_params.get(name)
        return [v.strip() for v in value.split(",") if v.strip()] if value else []

    first_time_raw = _str("first_time")
    return UserContext(
        age_band=_str("age_band"),
        region=_str("region"),
        occupation_field=_str("occupation_field"),
        humor_preferences=_list("humor_preferences"),
        humor_avoid=_list("humor_avoid"),
        energy=_str("energy"),
        first_time=(first_time_raw.lower() == "true") if first_time_raw else None,
        session_notes=_str("session_notes"),
    )


async def handle_speech_started(
    *,
    session_id: str,
    session: AsyncSession | None,
    synthesis_elapsed_ms: int,
    cancel_synthesis,
    send_ack,
    speak_ack,
    slot_idx: int | None = None,
    joke_text: str = "",
) -> str:
    """Cancel in-flight synthesis, acknowledge in character, and trace the barge-in."""
    await cancel_synthesis()
    await send_ack()
    if speak_ack is not None:
        await speak_ack()
    await _isolated_record_step(
        artifact_id=session_id,
        artifact_type="session",
        kind="delivery",
        actor="joker.realtime",
        model=_TRACE_MODEL,
        prompt_ref="prompts/realtime_ack_v1.txt",
        inputs={
            "session_id": session_id,
            "synthesis_elapsed_ms": synthesis_elapsed_ms,
            "slot_idx": slot_idx,
            "joke_text": joke_text,
            "cut_off": True,
            "provider": _VOICE_PROVIDER,
        },
        output={"interrupted": True, "barge_in_ack": BARGE_IN_ACK},
        rationale=(
            "User spoke during synthesis (barge-in). "
            f"In-flight synthesis cancelled after {synthesis_elapsed_ms} ms "
            f"on slot {slot_idx}: {joke_text[:80]!r}. "
            "In-character acknowledgment requested; listening continues concurrently."
        ),
        latency_ms=synthesis_elapsed_ms,
        cost=None,
    )
    return BARGE_IN_ACK


async def _relay_browser_to_voice(client_ws: WebSocket, vs) -> None:
    """Forward browser audio (and optional JSON control) to the voice session."""
    try:
        while True:
            message = await client_ws.receive()
            if message.get("type") == "websocket.disconnect":
                print(
                    f"[ws] browser disconnect code={message.get('code')} "
                    f"reason={message.get('reason')}",
                    flush=True,
                )
                break
            if message.get("bytes") is not None:
                await vs.send_audio(message["bytes"])
            elif message.get("text") is not None:
                # Forward JSON control messages; voice sessions that support them
                # can interpret them; others silently ignore.
                try:
                    ctrl = json.loads(message["text"])
                    if ctrl.get("type") == "cancel":
                        await vs.update_instructions("")
                except Exception:
                    pass
    except (WebSocketDisconnect, Exception):
        pass


async def _process_reaction_task(
    *,
    session_state: orchestrator.SessionState,
    slot_idx: int,
    user_reaction: str,
    voice_session_ref: list,
    client_ws: WebSocket,
    tracker: LatencyTracker,
) -> None:
    """Score/classify/file off the audio path, on a dedicated DB session."""
    reaction_snap = current_turn()
    t0 = time.monotonic()
    try:
        factory = session_maker()
        async with factory() as db_session:
            try:
                result = await orchestrator.process_reaction(
                    state=session_state,
                    slot_idx=slot_idx,
                    user_reaction=user_reaction,
                    session=db_session,
                    tracker=tracker,
                )
                await db_session.commit()
            except Exception:
                await _keep_flushed_traces(db_session)
                raise
    except Exception:
        _LOG.exception("process_reaction failed; host keeps performing")
        return
    if reaction_snap is not None:
        bind_turn(
            turn_id=reaction_snap.turn_id,
            turn_index=reaction_snap.turn_index,
            trigger_type=reaction_snap.trigger_type,
            trigger_text=reaction_snap.trigger_text,
        )
    total_ms = max(1, int((time.monotonic() - t0) * 1000))
    per_step_ms = total_ms // 3

    score_val: int = result.get("score", 0)
    category: str = result.get("category", "")
    path_parts: list = result.get("path", [category] if category else [])
    joke_id: str | None = result.get("joke_id")
    gen_for_slot = session_state.generations.get(slot_idx)
    tone_level_val = gen_for_slot.tone_level if gen_for_slot is not None else None

    await _emit(client_ws, {
        "type": "librarian_step",
        "kind": "score",
        "actor": "librarian.score",
        "model": None,
        "latency_ms": per_step_ms,
        "rationale": (
            f"Score {score_val}/10 — {_score_anchor(score_val)}. "
            f"{'Bombed: set adaptation triggered.' if result.get('bombed') else ''}"
        ).strip(),
        "payload": {
            "score": score_val,
            "rubric_anchor": _score_anchor(score_val),
            "bombed": result.get("bombed", False),
            "tone_level": tone_level_val,
        },
        "joke_id": joke_id,
    })

    filed_path = " › ".join(path_parts) if path_parts else category
    await _emit(client_ws, {
        "type": "librarian_step",
        "kind": "classify",
        "actor": "librarian.classify",
        "model": None,
        "latency_ms": per_step_ms,
        "rationale": f"Classified as {category!r}.",
        "payload": {"category": category, "path": path_parts},
        "joke_id": joke_id,
    })

    await _emit(client_ws, {
        "type": "librarian_step",
        "kind": "filed",
        "actor": "joker.box_client",
        "model": None,
        "latency_ms": per_step_ms,
        "rationale": f"Filed at {filed_path}.",
        "payload": {"path": filed_path, "joke_id": joke_id},
        "joke_id": joke_id,
    })

    # Steer the voice session with updated instructions
    vs = voice_session_ref[0]
    if vs is not None:
        instructions = result.get("session_instructions")
        if instructions:
            await vs.update_instructions(instructions)

        if result.get("bombed"):
            await _speak_stall(
                vs=vs,
                state=session_state,
                category="post_bomb",
                session_id=session_state.session_id,
                wait="reaction_bomb",
            )
        elif score_val >= 6:
            await _speak_stall(
                vs=vs,
                state=session_state,
                category="post_laugh",
                session_id=session_state.session_id,
                wait="reaction_landed",
            )
