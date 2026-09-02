"""OpenAI Realtime API voice session implementation.

This is the preserved OpenAI implementation kept alongside the ElevenLabs
one so we can switch back if needed.  See docs/DECISIONS.md 2026-09-02
"ElevenLabs voice layer".

Architecture
------------
  Client ── PCM16 ──> session.send_audio() ──> OpenAI Realtime WebSocket
  Client <── PCM16 ─── on_audio_chunk ────── OpenAI Realtime WebSocket

The WebSocket relay coroutine runs in a background task.  start() returns
immediately.  wait() blocks until the WebSocket is closed.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time

import websockets

from joker.voice.protocol import VoiceCallbacks, VoiceSession

_OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1"
REALTIME_MODEL = "gpt-realtime-2.1"


class OpenAIVoiceSession(VoiceSession):
    """Full-duplex voice via OpenAI Realtime GA API.

    Fires VoiceCallbacks so the orchestrator does not contain any
    OpenAI-specific protocol code.
    """

    def __init__(self, callbacks: VoiceCallbacks) -> None:
        super().__init__(callbacks)
        self._ws: websockets.ClientConnection | None = None
        self._ws_ctx = None
        self._task: asyncio.Task | None = None
        self._system_prompt = ""

    async def start(
        self,
        *,
        system_prompt: str,
        first_message: str | None = None,
    ) -> None:
        self._system_prompt = system_prompt
        api_key = os.environ["OPENAI_API_KEY"]
        self._ws_ctx = websockets.connect(
            _OPENAI_REALTIME_URL,
            additional_headers={"Authorization": f"Bearer {api_key}"},
        )
        self._ws = await self._ws_ctx.__aenter__()
        await _configure_session(self._ws, system_prompt)
        self._task = asyncio.create_task(self._run())

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(chunk).decode(),
                    }
                )
            )
        except Exception:
            pass

    async def update_instructions(self, instructions: str) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": {"type": "realtime", "instructions": instructions},
                    }
                )
            )
        except Exception:
            pass

    async def speak(self, text: str) -> None:
        """Inject an assistant message and trigger an immediate response."""
        if self._ws is None:
            return
        try:
            await self._ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "input_text", "text": text}],
                        },
                    }
                )
            )
            await self._ws.send(json.dumps({"type": "response.create"}))
        except Exception:
            pass

    async def wait(self) -> None:
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def close(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._ws_ctx is not None:
            try:
                await self._ws_ctx.__aexit__(None, None, None)
            except Exception:
                pass
        self._ws = None
        self._ws_ctx = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run(self) -> None:  # noqa: C901
        """Process all events from OpenAI and fire VoiceCallbacks."""
        delivery_start: float | None = None
        pending_tool_call: dict | None = None
        current_text_parts: list[str] = []
        interrupted_current = False
        cb = self.callbacks

        try:
            async for raw in self._ws:
                event = json.loads(raw)
                etype = event.get("type", "")

                if etype == "response.audio.delta":
                    if delivery_start is None:
                        delivery_start = time.monotonic()
                        await cb.on_delivery_start()
                        await cb.on_state_change("speaking")
                    chunk = _decode_delta(event.get("delta", ""))
                    if chunk:
                        await cb.on_audio_chunk(chunk)

                elif etype == "input_audio_buffer.speech_started":
                    barge_in_ms = (
                        int((time.monotonic() - delivery_start) * 1000)
                        if delivery_start is not None
                        else 0
                    )
                    was_speaking = delivery_start is not None
                    if was_speaking:
                        interrupted_current = True
                    # Cancel in-flight synthesis immediately (OpenAI-specific)
                    try:
                        await self._ws.send(json.dumps({"type": "response.cancel"}))
                    except Exception:
                        pass
                    await cb.on_state_change("listening")
                    if was_speaking:
                        await cb.on_barge_in(
                            " ".join(current_text_parts),
                            barge_in_ms,
                        )
                    delivery_start = None

                elif etype == "input_audio_buffer.speech_stopped":
                    await cb.on_state_change("idle")
                    await cb.on_user_speech_stop()
                    current_text_parts = []
                    interrupted_current = False

                elif etype == "response.audio_transcript.delta":
                    delta = event.get("delta", "")
                    if delta:
                        current_text_parts.append(delta)
                        await cb.on_agent_transcript_delta(delta)

                elif etype == "response.audio_transcript.done":
                    text = event.get("transcript", "")
                    await cb.on_agent_transcript_done(text)

                elif etype == "conversation.item.input_audio_transcription.completed":
                    transcript = event.get("transcript", "")
                    if transcript:
                        await cb.on_user_transcript(transcript)

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
                    arguments_str = event.get("arguments") or (
                        pending_tool_call["arguments"] if pending_tool_call else "{}"
                    )
                    try:
                        arguments = json.loads(arguments_str or "{}")
                    except json.JSONDecodeError:
                        arguments = {}
                    try:
                        result = await cb.on_tool_call(name, arguments)
                    except Exception as exc:
                        result = {"error": str(exc)}
                    try:
                        await self._ws.send(
                            json.dumps(
                                {
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": call_id,
                                        "output": json.dumps(result),
                                    },
                                }
                            )
                        )
                        await self._ws.send(json.dumps({"type": "response.create"}))
                    except Exception:
                        pass
                    pending_tool_call = None

                elif etype == "response.audio.done":
                    latency_ms = (
                        int((time.monotonic() - delivery_start) * 1000)
                        if delivery_start is not None
                        else 0
                    )
                    full_text = "".join(current_text_parts)
                    await cb.on_delivery_done(latency_ms, full_text)
                    await cb.on_state_change("connected")
                    delivery_start = None

        except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
            pass
        except Exception:
            pass


async def _configure_session(ws: websockets.ClientConnection, system_prompt: str) -> None:
    """Send session.update to configure the Realtime session (GA API shape)."""
    from joker.tools import TOOL_SCHEMAS

    await ws.send(
        json.dumps(
            {
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "model": REALTIME_MODEL,
                    "output_modalities": ["audio"],
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": 24000},
                            "transcription": {"model": "whisper-1"},
                            "turn_detection": {
                                "type": "server_vad",
                                "silence_duration_ms": 600,
                                "create_response": True,
                            },
                        },
                        "output": {
                            "format": {"type": "audio/pcm", "rate": 24000},
                            "voice": "shimmer",
                        },
                    },
                    "tools": TOOL_SCHEMAS,
                    "tool_choice": "auto",
                    "instructions": system_prompt,
                },
            }
        )
    )


def _decode_delta(delta: str) -> bytes:
    try:
        return base64.b64decode(delta)
    except Exception:
        return b""
