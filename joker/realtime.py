"""Joker — full-duplex voice over FastAPI WebSocket.

Architecture
------------
One FastAPI WebSocket endpoint bridges the client to the OpenAI Realtime API:

    Client <──── audio bytes (PCM16 / base64) ────> _relay_to_openai()
    Client <──── audio bytes + text events   ────── _relay_to_client()

Both relay coroutines run concurrently via asyncio.gather so listening and
speaking happen at the same time.

Barge-in handling
-----------------
When OpenAI sends `input_audio_buffer.speech_started`, the Joker:
  1. Sends `{"type": "response.cancel"}` to OpenAI immediately (stops synthesis).
  2. Writes a trace with kind="delivery" and a barge-in rationale.
  3. Sends a short in-character acknowledgment back to the client so the
     interruption is handled gracefully rather than silently.

Tools
-----
The session is configured with all tool schemas from joker/tools.py.
Incoming `response.function_call_arguments.done` events are dispatched
to the matching Python function and the result is sent back as a
`conversation.item.create` + `response.create`.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from joker.latency import LatencyTracker
from joker.tools import TOOL_SCHEMAS, dispatch_tool
from shared.db import SessionFactory
from shared.trace import record_step

router = APIRouter()

_OPENAI_REALTIME_URL = (
    "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17"
)

_BARGE_IN_ACK = (
    "Sorry—go on, I'm listening."
)


@router.websocket("/ws/session/{session_id}")
async def voice_session(websocket: WebSocket, session_id: str) -> None:
    """Full-duplex voice bridge between the client and OpenAI Realtime API."""
    await websocket.accept()

    tracker = LatencyTracker()

    async with SessionFactory() as db_session:
        import os

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
                await _configure_session(openai_ws)

                await asyncio.gather(
                    _relay_to_openai(websocket, openai_ws),
                    _relay_to_client(
                        websocket,
                        openai_ws,
                        session_id,
                        db_session,
                        tracker,
                    ),
                )
        except WebSocketDisconnect:
            pass
        finally:
            from pathlib import Path
            tracker.flush_to_topography(Path("docs/TOPOGRAPHY.md"))


async def _configure_session(openai_ws: websockets.ClientConnection) -> None:
    """Send session.update with tools and voice settings."""
    await openai_ws.send(
        json.dumps(
            {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "voice": "shimmer",
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "turn_detection": {
                        "type": "server_vad",
                        "silence_duration_ms": 600,
                        "create_response": True,
                    },
                    "tools": TOOL_SCHEMAS,
                    "tool_choice": "auto",
                    "instructions": (
                        "You are a stand-up comedian performing live. "
                        "Tell jokes, respond to the audience, and stay in character. "
                        "When interrupted, acknowledge gracefully and continue."
                    ),
                },
            }
        )
    )


async def _relay_to_openai(
    client_ws: WebSocket,
    openai_ws: websockets.ClientConnection,
) -> None:
    """Forward raw bytes / JSON from the client to OpenAI."""
    try:
        while True:
            data = await client_ws.receive_bytes()
            # Client sends raw PCM16; wrap in audio buffer append event
            import base64

            await openai_ws.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(data).decode(),
                    }
                )
            )
    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed):
        pass


async def _relay_to_client(
    client_ws: WebSocket,
    openai_ws: websockets.ClientConnection,
    session_id: str,
    db_session: AsyncSession,
    tracker: LatencyTracker,
) -> None:
    """Forward events from OpenAI to the client; handle barge-in and tool calls."""
    pending_tool_call: dict | None = None
    delivery_start: float | None = None

    try:
        async for raw in openai_ws:
            event = json.loads(raw)
            etype = event.get("type", "")

            # ---- Synthesis started: start delivery timer ----------------
            if etype == "response.audio.delta":
                if delivery_start is None:
                    delivery_start = time.monotonic()
                    tracker.record(
                        from_import("joker.latency", "Stage").TTS_FIRST_BYTE,
                        0,
                    )
                await client_ws.send_bytes(
                    _decode_audio_delta(event.get("delta", ""))
                )

            # ---- Barge-in: user spoke during synthesis ------------------
            elif etype == "input_audio_buffer.speech_started":
                barge_in_ms = (
                    int((time.monotonic() - delivery_start) * 1000)
                    if delivery_start is not None
                    else 0
                )
                await openai_ws.send(json.dumps({"type": "response.cancel"}))
                await client_ws.send_json(
                    {"type": "barge_in_ack", "text": _BARGE_IN_ACK}
                )

                await record_step(
                    artifact_id=session_id,
                    artifact_type="session",
                    kind="delivery",
                    actor="joker.realtime",
                    model=None,
                    prompt_ref=None,
                    inputs={"session_id": session_id},
                    output={"interrupted": True, "barge_in_ack": _BARGE_IN_ACK},
                    rationale=(
                        "User spoke during synthesis. "
                        f"Synthesis cancelled after {barge_in_ms} ms. "
                        "In-character acknowledgment sent."
                    ),
                    latency_ms=barge_in_ms,
                    cost=None,
                    session=db_session,
                )
                delivery_start = None

            # ---- Reaction: user finished speaking -----------------------
            elif etype == "input_audio_buffer.speech_stopped":
                await record_step(
                    artifact_id=session_id,
                    artifact_type="session",
                    kind="reaction_capture",
                    actor="joker.realtime",
                    model=None,
                    prompt_ref=None,
                    inputs={"session_id": session_id},
                    output={"event": "speech_stopped"},
                    rationale="User finished speaking; reaction window closed.",
                    latency_ms=0,
                    cost=None,
                    session=db_session,
                )

            # ---- Tool call: accumulate arguments -----------------------
            elif etype == "response.function_call_arguments.delta":
                if pending_tool_call is None:
                    pending_tool_call = {
                        "call_id": event.get("call_id"),
                        "name": event.get("name", ""),
                        "arguments": "",
                    }
                pending_tool_call["arguments"] += event.get("delta", "")

            # ---- Tool call done: dispatch and return result ------------
            elif etype == "response.function_call_arguments.done":
                if pending_tool_call is not None:
                    await _handle_tool_call(
                        openai_ws, pending_tool_call, db_session
                    )
                    pending_tool_call = None

            # ---- Delivery complete: reset timer ------------------------
            elif etype == "response.audio.done":
                if delivery_start is not None:
                    ms = int((time.monotonic() - delivery_start) * 1000)
                    tracker.record(
                        _stage_tts(),
                        ms,
                    )
                delivery_start = None

            # ---- Forward all other events to client --------------------
            else:
                await client_ws.send_text(raw)

    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed):
        pass


async def _handle_tool_call(
    openai_ws: websockets.ClientConnection,
    tool_call: dict,
    session: AsyncSession,
) -> None:
    """Execute a tool and send the result back to the Realtime session."""
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
    import base64

    try:
        return base64.b64decode(delta)
    except Exception:
        return b""


# Avoid a circular import from using Stage directly in the coroutine.
def _stage_tts():  # type: ignore[return]
    from joker.latency import Stage

    return Stage.TTS_FIRST_BYTE


def from_import(module: str, name: str):  # type: ignore[return]
    import importlib

    return getattr(importlib.import_module(module), name)
