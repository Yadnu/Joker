"""Minimal real-time voice client for the Jokebox.

Usage:
    python scripts/voice_client.py [session-id]

Controls:
    Ctrl+C  — end session

The script connects to ws://localhost:8000/ws/session/{id},
streams microphone audio to the Box (which bridges it to OpenAI Realtime),
and plays back whatever audio the Box sends.

Audio format expected by OpenAI Realtime: PCM16, mono, 24 kHz.
"""

from __future__ import annotations

import asyncio
import base64
import json
import queue
import sys
import threading
import uuid

import numpy as np
import sounddevice as sd
import websockets

BOX_WS_URL = "ws://localhost:8000/ws/session/{session_id}"

SAMPLE_RATE   = 24_000   # Hz — OpenAI Realtime requirement
CHANNELS      = 1        # mono
CHUNK_FRAMES  = 2048     # ~85 ms per chunk sent to server
DTYPE         = "int16"

# Shared queue for outbound mic frames (main thread → send coroutine)
_mic_queue: queue.Queue[bytes] = queue.Queue()

# Shared queue for inbound audio to play (recv coroutine → playback thread)
_play_queue: queue.Queue[bytes] = queue.Queue()


# ---------------------------------------------------------------------------
# Mic capture (runs in a sounddevice callback thread)
# ---------------------------------------------------------------------------

def _mic_callback(indata: np.ndarray, frames: int, time_info, status) -> None:  # noqa: ANN001
    """Called by sounddevice on each input chunk; push raw PCM16 bytes."""
    if status:
        print(f"[mic] {status}", file=sys.stderr)
    _mic_queue.put(indata.tobytes())


# ---------------------------------------------------------------------------
# Playback thread — drains the play queue and pushes to sounddevice output
# ---------------------------------------------------------------------------

def _playback_thread(stop_event: threading.Event) -> None:
    with sd.RawOutputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        blocksize=CHUNK_FRAMES,
    ) as stream:
        while not stop_event.is_set():
            try:
                chunk = _play_queue.get(timeout=0.1)
                stream.write(chunk)
            except queue.Empty:
                pass


# ---------------------------------------------------------------------------
# WebSocket coroutines
# ---------------------------------------------------------------------------

async def _send_mic(ws: websockets.WebSocketClientProtocol) -> None:
    """Read mic chunks from the queue and forward as base64 audio."""
    loop = asyncio.get_running_loop()
    while True:
        pcm_bytes = await loop.run_in_executor(None, _mic_queue.get)
        msg = json.dumps({
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm_bytes).decode(),
        })
        await ws.send(msg)


async def _recv_audio(ws: websockets.WebSocketClientProtocol) -> None:
    """Receive events from Box (which relays OpenAI Realtime events).

    - Binary frames  → raw PCM16 audio → enqueue for playback
    - JSON text       → print notable events
    """
    async for message in ws:
        if isinstance(message, bytes):
            _play_queue.put(message)
        else:
            try:
                event = json.loads(message)
                etype = event.get("type", "")
                if etype in (
                    "session.created",
                    "response.audio_transcript.delta",
                    "response.audio_transcript.done",
                    "input_audio_buffer.speech_started",
                    "input_audio_buffer.speech_stopped",
                    "error",
                ):
                    if etype == "error":
                        print(f"\n[ERROR] {event}", file=sys.stderr)
                    elif etype == "response.audio_transcript.done":
                        transcript = event.get("transcript", "")
                        print(f"\n[Joker] {transcript}")
                    elif etype == "input_audio_buffer.speech_started":
                        print("\n[You]   (speaking...)")
                    elif etype == "session.created":
                        print("[Box]   Session ready — start talking!\n")
            except json.JSONDecodeError:
                pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run(session_id: str) -> None:
    url = BOX_WS_URL.format(session_id=session_id)
    url += "?occupation_field=tech&energy=dry&humor_preferences=observational"

    print(f"Connecting to {url}")
    print("Preparing set (may take a few seconds)...\n")

    async with websockets.connect(url, open_timeout=60) as ws:
        print("[Box]   Connected. Waiting for session startup...")
        stop_event = threading.Event()

        # Start playback thread
        pb_thread = threading.Thread(
            target=_playback_thread, args=(stop_event,), daemon=True
        )
        pb_thread.start()

        # Start mic capture stream
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=CHUNK_FRAMES,
            callback=_mic_callback,
        ):
            try:
                await asyncio.gather(_send_mic(ws), _recv_audio(ws))
            except (websockets.ConnectionClosed, KeyboardInterrupt):
                print("\n[Box]   Session ended.")
            finally:
                stop_event.set()
                pb_thread.join(timeout=2)


def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else uuid.uuid4().hex[:8]
    print(f"Session ID: {session_id}")
    try:
        asyncio.run(run(session_id))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
