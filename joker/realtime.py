"""Joker — full-duplex voice over FastAPI WebSocket.

Architecture
------------
One FastAPI WebSocket endpoint bridges the client to the OpenAI Realtime API:

    Client ── audio / JSON ──> _relay_to_openai() ──> OpenAI Realtime
    Client <─ audio + events ─ _relay_to_client() <── OpenAI Realtime

Both relay coroutines run concurrently via asyncio.gather so listening and
speaking happen at the same time. Strict turn-taking is not used.

Barge-in handling
-----------------
When OpenAI sends `input_audio_buffer.speech_started`, the Joker:
  1. Sends `{"type": "response.cancel"}` immediately (stops in-flight TTS).
  2. Writes a delivery trace with a barge-in rationale.
  3. Sends an in-character acknowledgment so the interruption is handled
     as performance, not a dropped connection.

Batch-pipeline wiring
---------------------
`joker/orchestrator.py` is the glue between this module and the Librarian
(see docs/DECISIONS.md 2026-09-01 "realtime.py wired to the batch pipeline
via orchestrator.py").  Before the WebSocket to OpenAI opens,
`orchestrator.start_session()` calls `librarian.suggest.suggest()` and
`joker.setbuilder.build_set()`, then every slot in the resulting set is
generated via `orchestrator.generate_slot()` (deliberately mixing
intended_quality="good"/"bad" per AGENTS.md).  The generated lines are fed
into the Realtime session's `instructions` so the live voice model has real,
traced material to perform instead of improvising untraced jokes.

When OpenAI reports `input_audio_buffer.speech_stopped`, the reaction
transcript accumulated since the last delivered slot is handed to
`orchestrator.process_reaction()` via `asyncio.create_task` — scoring,
classification, metadata extraction, and Box filing all happen off the
audio-relay hot path so listening/speaking are never blocked on the
Librarian round-trip.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.records import UserContext
from joker import orchestrator
from joker.latency import LatencyTracker, Stage
from joker.tools import TOOL_SCHEMAS, dispatch_tool
from shared.db import session_maker
from shared.trace import record_step

router = APIRouter()

_OPENAI_REALTIME_URL = (
    "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17"
)
REALTIME_MODEL = "gpt-4o-realtime-preview-2024-12-17"
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
BARGE_IN_ACK = (_PROMPTS_DIR / "realtime_ack_v1.txt").read_text(encoding="utf-8").strip()


@router.websocket("/ws/session/{session_id}")
async def voice_session(websocket: WebSocket, session_id: str) -> None:
    """Full-duplex voice bridge between the client and OpenAI Realtime API.

    Before the OpenAI WebSocket opens, this wires the batch pipeline in via
    joker.orchestrator: suggest() -> build_set() -> generate() for every
    slot.  See module docstring "Batch-pipeline wiring" for the full flow.
    """
    await websocket.accept()

    tracker = LatencyTracker()
    factory = session_maker()

    async with factory() as db_session:
        listener_context = _listener_context_from_query(websocket.query_params)
        session_state = await orchestrator.start_session(
            session_id=session_id,
            listener_context=listener_context,
            taxonomy_snapshot_version=date.today().isoformat(),
            session=db_session,
            joker_name=os.environ.get("JOKER_NAME", "joker-v1"),
            account_name=os.environ.get("BOX_ACCOUNT_NAME", "joker-live"),
            box_api_key=os.environ.get("BOX_API_KEY"),
            tracker=tracker,
        )
        for slot_idx in range(len(session_state.joke_set.slots)):
            await orchestrator.generate_slot(
                state=session_state, slot_idx=slot_idx, session=db_session, tracker=tracker
            )
        await db_session.commit()

        api_key = os.environ["OPENAI_API_KEY"]
        headers = {
            "Authorization": f"Bearer {api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        try:
            async with websockets.connect(
                _OPENAI_REALTIME_URL,
                additional_headers=headers,
            ) as openai_ws:
                await _configure_session(openai_ws, session_state)
                await record_step(
                    artifact_id=session_id,
                    artifact_type="session",
                    kind="delivery",
                    actor="joker.realtime",
                    model=REALTIME_MODEL,
                    prompt_ref="prompts/realtime_perform_v1.txt",
                    inputs={
                        "session_id": session_id,
                        "set_id": session_state.joke_set.set_id,
                        "slot_count": len(session_state.joke_set.slots),
                    },
                    output={"realtime_model": REALTIME_MODEL, "configured": True},
                    rationale=(
                        f"Opened OpenAI Realtime session on {REALTIME_MODEL} with "
                        "the traced set as instructions; subsequent audio deltas "
                        "are deliveries of that script."
                    ),
                    latency_ms=0,
                    cost=None,
                    session=db_session,
                )

                await asyncio.gather(
                    _relay_to_openai(websocket, openai_ws),
                    _relay_to_client(
                        websocket,
                        openai_ws,
                        session_id,
                        db_session,
                        tracker,
                        session_state,
                    ),
                )
        except WebSocketDisconnect:
            pass
        finally:
            tracker.flush_to_topography(Path("docs/TOPOGRAPHY.md"))


def _listener_context_from_query(query_params) -> UserContext:  # noqa: ANN001
    """Build a UserContext from optional `/ws/session/{id}?...` query params.

    Every field is optional (per box/schema/records.py UserContext); a
    session that supplies none of them is valid and the Librarian's
    suggest() prompt falls back to general-audience defaults.
    """

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
    session: AsyncSession,
    synthesis_elapsed_ms: int,
    cancel_synthesis: Callable[[], Awaitable[None]],
    send_ack: Callable[[], Awaitable[None]],
    speak_ack: Callable[[], Awaitable[None]] | None = None,
    slot_idx: int | None = None,
    joke_text: str = "",
) -> str:
    """Cancel in-flight synthesis, acknowledge in character, and trace the barge-in."""
    await cancel_synthesis()
    await send_ack()
    if speak_ack is not None:
        await speak_ack()
    await record_step(
        artifact_id=session_id,
        artifact_type="session",
        kind="delivery",
        actor="joker.realtime",
        model=REALTIME_MODEL,
        prompt_ref="prompts/realtime_ack_v1.txt",
        inputs={
            "session_id": session_id,
            "synthesis_elapsed_ms": synthesis_elapsed_ms,
            "slot_idx": slot_idx,
            "joke_text": joke_text,
            "cut_off": True,
        },
        output={"interrupted": True, "barge_in_ack": BARGE_IN_ACK},
        rationale=(
            "User spoke during synthesis (barge-in). "
            f"In-flight synthesis cancelled after {synthesis_elapsed_ms} ms "
            f"on slot {slot_idx}: {joke_text[:80]!r}. "
            "In-character acknowledgment spoken; listening continues concurrently."
        ),
        latency_ms=synthesis_elapsed_ms,
        cost=None,
        session=session,
    )
    return BARGE_IN_ACK


async def _configure_session(
    openai_ws: websockets.ClientConnection,
    session_state: orchestrator.SessionState,
) -> None:
    await openai_ws.send(
        json.dumps(
            {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "voice": "shimmer",
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {"model": "whisper-1"},
                    "turn_detection": {
                        "type": "server_vad",
                        "silence_duration_ms": 600,
                        "create_response": True,
                    },
                    "tools": TOOL_SCHEMAS,
                    "tool_choice": "auto",
                    "instructions": orchestrator.render_set_instructions(session_state),
                },
            }
        )
    )


def _instructions_for_set(session_state: orchestrator.SessionState) -> str:
    return orchestrator.render_set_instructions(session_state)


async def _relay_to_openai(
    client_ws: WebSocket,
    openai_ws: websockets.ClientConnection,
) -> None:
    """Forward client audio (and optional JSON control) to OpenAI concurrently with TTS."""
    try:
        while True:
            message = await client_ws.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                await openai_ws.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(message["bytes"]).decode(),
                        }
                    )
                )
            elif message.get("text") is not None:
                await openai_ws.send(message["text"])
    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed):
        pass


async def _relay_to_client(
    client_ws: WebSocket,
    openai_ws: websockets.ClientConnection,
    session_id: str,
    db_session: AsyncSession,
    tracker: LatencyTracker,
    session_state: orchestrator.SessionState,
) -> None:
    pending_tool_call: dict | None = None
    delivery_start: float | None = None
    session_t0 = time.monotonic()
    current_slot_idx = 0
    reaction_transcript_parts: list[str] = []
    background_tasks: set[asyncio.Task] = set()
    interrupted_current = False

    try:
        async for raw in openai_ws:
            event = json.loads(raw)
            etype = event.get("type", "")

            if etype == "response.audio.delta":
                if delivery_start is None:
                    delivery_start = time.monotonic()
                    tracker.record(
                        Stage.TTS_FIRST_BYTE,
                        int((delivery_start - session_t0) * 1000),
                    )
                await client_ws.send_bytes(_decode_audio_delta(event.get("delta", "")))

            elif etype == "input_audio_buffer.speech_started":
                barge_in_ms = (
                    int((time.monotonic() - delivery_start) * 1000)
                    if delivery_start is not None
                    else 0
                )
                if delivery_start is not None:
                    interrupted_current = True
                cut_slot = (
                    session_state.joke_set.slots[current_slot_idx]
                    if current_slot_idx < len(session_state.joke_set.slots)
                    else None
                )

                async def _cancel() -> None:
                    await openai_ws.send(json.dumps({"type": "response.cancel"}))

                async def _ack() -> None:
                    await client_ws.send_json(
                        {"type": "barge_in_ack", "text": BARGE_IN_ACK}
                    )

                async def _speak_ack() -> None:
                    await openai_ws.send(
                        json.dumps(
                            {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "message",
                                    "role": "assistant",
                                    "content": [
                                        {"type": "input_text", "text": BARGE_IN_ACK}
                                    ],
                                },
                            }
                        )
                    )
                    await openai_ws.send(json.dumps({"type": "response.create"}))

                await handle_speech_started(
                    session_id=session_id,
                    session=db_session,
                    synthesis_elapsed_ms=barge_in_ms,
                    cancel_synthesis=_cancel,
                    send_ack=_ack,
                    speak_ack=_speak_ack,
                    slot_idx=current_slot_idx,
                    joke_text=(cut_slot.joke_text if cut_slot else ""),
                )
                delivery_start = None

            elif etype == "input_audio_buffer.speech_stopped":
                skip_file = interrupted_current
                interrupted_current = False
                await record_step(
                    artifact_id=session_id,
                    artifact_type="session",
                    kind="reaction_capture",
                    actor="joker.realtime",
                    model=REALTIME_MODEL,
                    prompt_ref=None,
                    inputs={
                        "session_id": session_id,
                        "slot_idx": current_slot_idx,
                        "interrupted": skip_file,
                    },
                    output={"event": "speech_stopped"},
                    rationale=(
                        "User finished speaking; reaction window closed."
                        + (" Barged slot was not filed." if skip_file else "")
                    ),
                    latency_ms=0,
                    cost=None,
                    session=db_session,
                )
                tracker.record(Stage.REACTION, 0)

                if (
                    not skip_file
                    and current_slot_idx < len(session_state.joke_set.slots)
                    and current_slot_idx in session_state.generations
                ):
                    user_reaction = " ".join(reaction_transcript_parts).strip() or (
                        "(no speech transcript captured for this reaction window)"
                    )
                    task = asyncio.create_task(
                        _process_reaction_task(
                            session_state=session_state,
                            slot_idx=current_slot_idx,
                            user_reaction=user_reaction,
                            db_session=db_session,
                            openai_ws=openai_ws,
                            tracker=tracker,
                        )
                    )
                    background_tasks.add(task)
                    task.add_done_callback(background_tasks.discard)
                    current_slot_idx += 1
                elif skip_file:
                    current_slot_idx += 1
                reaction_transcript_parts = []

            elif etype == "conversation.item.input_audio_transcription.completed":
                transcript = event.get("transcript", "")
                if transcript:
                    reaction_transcript_parts.append(transcript)

            elif etype == "response.function_call_arguments.delta":
                if pending_tool_call is None:
                    pending_tool_call = {
                        "call_id": event.get("call_id"),
                        "name": event.get("name", ""),
                        "arguments": "",
                    }
                pending_tool_call["arguments"] += event.get("delta", "")

            elif etype == "response.function_call_arguments.done":
                name = event.get("name") or (
                    pending_tool_call["name"] if pending_tool_call else ""
                )
                call_id = event.get("call_id") or (
                    pending_tool_call["call_id"] if pending_tool_call else None
                )
                arguments = event.get("arguments") or (
                    pending_tool_call["arguments"] if pending_tool_call else "{}"
                )
                await _handle_tool_call(
                    openai_ws,
                    {"call_id": call_id, "name": name, "arguments": arguments},
                    db_session,
                )
                pending_tool_call = None

            elif etype == "response.audio.done":
                if delivery_start is not None:
                    tracker.record(
                        Stage.TTS_FIRST_BYTE,
                        int((time.monotonic() - delivery_start) * 1000),
                    )
                delivered = (
                    session_state.joke_set.slots[current_slot_idx]
                    if current_slot_idx < len(session_state.joke_set.slots)
                    else None
                )
                gen = session_state.generations.get(current_slot_idx)
                await record_step(
                    artifact_id=(gen.joke_id if gen else session_id),
                    artifact_type="joke" if gen else "session",
                    kind="delivery",
                    actor="joker.realtime",
                    model=REALTIME_MODEL,
                    prompt_ref="prompts/realtime_perform_v1.txt",
                    inputs={
                        "session_id": session_id,
                        "slot_idx": current_slot_idx,
                        "joke_text": delivered.joke_text if delivered else "",
                    },
                    output={"interrupted": False},
                    rationale=(
                        f"Completed TTS delivery of slot {current_slot_idx} "
                        f"via {REALTIME_MODEL}."
                    ),
                    latency_ms=int((time.monotonic() - delivery_start) * 1000)
                    if delivery_start is not None
                    else 0,
                    cost=None,
                    session=db_session,
                )
                delivery_start = None

            else:
                await client_ws.send_text(raw)

    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed):
        pass
    finally:
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)


async def _process_reaction_task(
    *,
    session_state: orchestrator.SessionState,
    slot_idx: int,
    user_reaction: str,
    db_session: AsyncSession,
    openai_ws: websockets.ClientConnection,
    tracker: LatencyTracker,
) -> None:
    """Run orchestrator.process_reaction() off the audio-relay hot path."""
    result = await orchestrator.process_reaction(
        state=session_state,
        slot_idx=slot_idx,
        user_reaction=user_reaction,
        session=db_session,
        tracker=tracker,
    )
    await db_session.commit()

    instructions = result.get("session_instructions")
    if instructions:
        await openai_ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {"instructions": instructions},
                }
            )
        )
    recovery_line = result.get("recovery_line")
    if result.get("bombed") and recovery_line:
        await openai_ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "input_text", "text": recovery_line}],
                    },
                }
            )
        )
        await openai_ws.send(json.dumps({"type": "response.create"}))


async def _handle_tool_call(
    openai_ws: websockets.ClientConnection,
    tool_call: dict,
    session: AsyncSession,
) -> None:
    try:
        arguments = json.loads(tool_call["arguments"] or "{}")
        result = await dispatch_tool(tool_call["name"], arguments, session)
        output = json.dumps(result)
    except Exception as exc:  # noqa: BLE001
        output = json.dumps({"error": str(exc)})

    await openai_ws.send(
        json.dumps(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": tool_call["call_id"],
                    "output": output,
                },
            }
        )
    )
    await openai_ws.send(json.dumps({"type": "response.create"}))


def _decode_audio_delta(delta: str) -> bytes:
    try:
        return base64.b64decode(delta)
    except Exception:
        return b""
