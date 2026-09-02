"""One-time setup: create the Joker ElevenLabs agent with Box client tools.

Run once before the first session:

    python -m joker.voice.setup_agent

Prints the agent ID.  Copy it into your .env:

    ELEVENLABS_AGENT_ID=<printed id>

After that, the voice session reuses the agent rather than creating a new one.

Re-running is safe: existing tools and agents tagged "joker-box" are reused.
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()

from elevenlabs import ElevenLabs

from joker.voice.elevenlabs_session import (
    _DEFAULT_VOICE_ID,
    _EL_TOOL_CONFIGS,
    _ensure_agent,
    _ensure_tools,
)


def main() -> None:
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        print("Error: ELEVENLABS_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", _DEFAULT_VOICE_ID)
    client = ElevenLabs(api_key=api_key)

    print("Creating/verifying Box client tools...")
    import asyncio
    tool_ids = asyncio.run(_ensure_tools(client))
    print(f"  Tool IDs ({len(tool_ids)}): {tool_ids}")

    print("Creating/verifying Joker agent...")
    agent_id = asyncio.run(_ensure_agent(client, tool_ids, voice_id))
    print(f"\nAgent ID: {agent_id}")
    print(f"\nAdd to your .env:\n  ELEVENLABS_AGENT_ID={agent_id}")


if __name__ == "__main__":
    main()
