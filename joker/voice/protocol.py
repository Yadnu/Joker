"""VoiceSession protocol — the single seam between the Joker orchestrator
and any voice provider.

Nothing outside joker/voice/ may import a vendor SDK directly.  The
orchestrator (realtime.py) only touches this module and the factory in
joker/voice/__init__.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class VoiceCallbacks:
    """Callbacks the orchestrator installs into a VoiceSession before start().

    Every field is mandatory.  Use lambda: None async versions if a callback
    is irrelevant for a particular provider test scenario.
    """

    # PCM16 audio chunk from the provider → forward to browser client
    on_audio_chunk: Callable[[bytes], Awaitable[None]]

    # First PCM16 byte of a new agent turn → record latency, emit "speaking"
    on_delivery_start: Callable[[], Awaitable[None]]

    # Agent turn complete.  latency_ms = time from delivery start to done.
    # text = full agent utterance (may arrive before TTS finishes on ElevenLabs)
    on_delivery_done: Callable[[int, str], Awaitable[None]]

    # Streaming agent transcript delta (character-by-character when available)
    on_agent_transcript_delta: Callable[[str], Awaitable[None]]

    # Complete agent turn text (also fires alongside on_delivery_done)
    on_agent_transcript_done: Callable[[str], Awaitable[None]]

    # Complete user utterance after transcription
    on_user_transcript: Callable[[str], Awaitable[None]]

    # User spoke while agent was speaking (barge-in).
    # cut_text = what the agent said / intended to say in this turn.
    # at_ms   = milliseconds into the agent turn when interrupted.
    on_barge_in: Callable[[str, int], Awaitable[None]]

    # User finished their utterance (reaction window closed)
    on_user_speech_stop: Callable[[], Awaitable[None]]

    # Agent wants to call a Box function.  Return the JSON-serialisable result.
    on_tool_call: Callable[[str, dict], Awaitable[Any]]

    # Provider-level session state change: "connected|speaking|listening|idle"
    on_state_change: Callable[[str], Awaitable[None]]

    # Fatal provider error (quota, auth). Host should stop sending audio.
    on_provider_error: Callable[[str], Awaitable[None]]


class VoiceSession(ABC):
    """Abstract voice transport layer.

    A concrete sub-class handles all provider-specific protocol:
    WebSocket handshake, audio encoding, event parsing, barge-in ACK.
    The orchestrator never imports a vendor SDK directly.

    Lifecycle
    ---------
    session = make_voice_session(provider, callbacks)
    try:
        await session.start(system_prompt=..., first_message=...)
        # concurrently: await session.send_audio(chunk) from browser loop
        # any time:     await session.update_instructions(new_prompt)
        # any time:     await session.speak(recovery_line)
        await session.wait()       # blocks until provider session ends
    finally:
        await session.close()
    """

    def __init__(self, callbacks: VoiceCallbacks) -> None:
        self.callbacks = callbacks

    @abstractmethod
    async def start(
        self,
        *,
        system_prompt: str,
        first_message: str | None = None,
    ) -> None:
        """Connect to the provider and begin the full-duplex session.

        Returns immediately; event processing runs in a background task.
        """

    @abstractmethod
    async def send_audio(self, chunk: bytes) -> None:
        """Push a PCM16 chunk from the browser to the provider."""

    @abstractmethod
    async def update_instructions(self, instructions: str) -> None:
        """Update the agent's system prompt mid-session.

        Called by the orchestrator after each joke reaction is processed.
        """

    @abstractmethod
    async def speak(self, text: str) -> None:
        """Ask the provider to speak a specific line next.

        Semantics differ by provider:
          OpenAI   — injects an assistant message and triggers response.create;
                     the text is spoken verbatim.
          ElevenLabs — sends a contextual update strongly directing the next
                     response; the agent may paraphrase in the host's voice.
        """

    @abstractmethod
    async def wait(self) -> None:
        """Block until the provider session ends (WebSocket closed by either side)."""

    @abstractmethod
    async def close(self) -> None:
        """Cancel background task and release resources."""
