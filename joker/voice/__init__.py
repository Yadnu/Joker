"""joker/voice — provider-isolated voice transport layer.

Select the provider via VOICE_PROVIDER environment variable:
  VOICE_PROVIDER=elevenlabs   (default)
  VOICE_PROVIDER=openai

Nothing outside this package may import a vendor voice SDK directly.
"""

from __future__ import annotations

import os

from joker.voice.protocol import VoiceCallbacks, VoiceSession


def make_voice_session(callbacks: VoiceCallbacks) -> VoiceSession:
    """Return a VoiceSession for the configured provider."""
    provider = os.environ.get("VOICE_PROVIDER", "elevenlabs").lower().strip()

    if provider == "openai":
        from joker.voice.openai_session import OpenAIVoiceSession
        return OpenAIVoiceSession(callbacks)

    if provider == "elevenlabs":
        from joker.voice.elevenlabs_session import ElevenLabsVoiceSession
        return ElevenLabsVoiceSession(callbacks)

    raise ValueError(
        f"Unknown VOICE_PROVIDER={provider!r}. "
        "Supported values: 'elevenlabs', 'openai'."
    )


__all__ = ["VoiceCallbacks", "VoiceSession", "make_voice_session"]
