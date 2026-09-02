"""ElevenLabs Conversational AI voice session implementation.

Architecture
------------
  Client ── PCM16 ──> session.send_audio() ──> _BrowserAudioBridge ──> ElevenLabs
  Client <── PCM16 ─── on_audio_chunk ─────── AsyncConversation <───── ElevenLabs

The SDK's AsyncConversation handles the full agent loop: VAD, turn detection,
barge-in, tool calls.  We implement a custom AsyncAudioInterface that bridges
the browser WebSocket PCM16 stream to/from the SDK.

Full-duplex proof
-----------------
_BrowserAudioBridge.start() launches a feeder task that continuously pulls
chunks from self._queue and passes them to input_callback.  Audio chunks
arrive through output() concurrently.  Neither direction blocks the other.
The feeder and the ElevenLabs message-receive loop run as separate asyncio
tasks inside AsyncConversation._run().

Barge-in
--------
ElevenLabs server-side VAD detects user speech.  The server sends:
  1. interruption event  → SDK drops audio chunks with stale event_ids
                          → SDK calls audio_interface.interrupt()
                          → _BrowserAudioBridge.interrupt() fires on_barge_in
  2. agent_response_correction → SDK fires callback_agent_response_correction
                          → we fire on_barge_in with cut_text and at_ms

Tool calling
-----------
Tool schemas are created/reused on the ElevenLabs platform at session startup
via _ensure_tools().  ClientTools.register() connects the schema to our Box
function handlers.  The SDK handles the client_tool_call / client_tool_result
round-trip.

Amplitude
---------
ElevenLabs does not expose per-chunk amplitude.  We compute RMS from each
PCM16 chunk in output() and forward it via on_audio_chunk.  The browser's
existing enqueuePCM16 computes amplitude on the same bytes — no behaviour
change required.

speak() semantics
-----------------
No OpenAI-equivalent "inject assistant message + trigger response" exists in
ElevenLabs.  speak() uses send_contextual_update() to strongly direct the
agent's next turn.  The agent may paraphrase in Eddie Voss's voice rather than
reading the text verbatim.  See docs/DECISIONS.md 2026-09-02.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

from elevenlabs import ElevenLabs
from elevenlabs.conversational_ai.conversation import (
    AsyncAudioInterface,
    AsyncConversation,
    ClientTools,
    ConversationInitiationData,
)
from elevenlabs.types import (
    AgentConfig,
    ConversationalConfig,
    PromptAgentApiModelOutput,
    ToolRequestModel,
    TtsConversationalConfigOutput,
)

from joker.voice.protocol import VoiceCallbacks, VoiceSession

# Voice that best matches a late-night monologue host: assured, mid-range,
# enough range to land a punchline.  Configurable via ELEVENLABS_VOICE_ID.
# Default: "Charlie" (IKne3meq5aSn9XLyUdCD) — casual US male, expressive.
# See docs/DECISIONS.md 2026-09-02 for voice selection rationale.
_DEFAULT_VOICE_ID = "IKne3meq5aSn9XLyUdCD"
_BROWSER_HZ = 24000
_ELEVEN_HZ = 16000


def _resample_pcm16(data: bytes, src_hz: int, dst_hz: int) -> bytes:
    """Linear-resample mono PCM16. ElevenLabs is 16 kHz; the browser is 24 kHz."""
    if src_hz == dst_hz or not data:
        return data
    src = memoryview(data).cast("h")
    n_src = len(src)
    if n_src == 0:
        return data
    n_dst = max(1, int(round(n_src * dst_hz / src_hz)))
    out = bytearray(n_dst * 2)
    dst = memoryview(out).cast("h")
    scale = (n_src - 1) / (n_dst - 1) if n_dst > 1 else 0.0
    for i in range(n_dst):
        pos = i * scale
        j = int(pos)
        frac = pos - j
        a = src[j]
        b = src[min(j + 1, n_src - 1)]
        dst[i] = int(a + (b - a) * frac)
    return bytes(out)


# ---------------------------------------------------------------------------
# Audio bridge
# ---------------------------------------------------------------------------


class _BrowserAudioBridge(AsyncAudioInterface):
    """Bridge between the browser WebSocket PCM16 stream and the ElevenLabs SDK.

    The SDK calls start(input_callback) once; we feed chunks from a queue.
    output(audio) forwards PCM16 from ElevenLabs back to the browser.
    interrupt() is called when the server detects user barge-in.
    """

    def __init__(
        self,
        on_audio_out: Callable[[bytes], Awaitable[None]],
        on_interrupt: Callable[[], Awaitable[None]],
        on_delivery_start: Callable[[], Awaitable[None]],
        on_transport_error: Callable[[BaseException], Awaitable[None]] | None = None,
    ) -> None:
        self._on_audio_out = on_audio_out
        self._on_interrupt = on_interrupt
        self._on_delivery_start = on_delivery_start
        self._on_transport_error = on_transport_error
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._feeder: asyncio.Task | None = None
        self._delivering = False

    async def start(self, input_callback: Callable[[bytes], Awaitable[None]]) -> None:
        async def _feed() -> None:
            while True:
                chunk = await self._queue.get()
                if chunk is None:
                    break
                try:
                    await input_callback(chunk)
                except Exception as exc:
                    if self._on_transport_error is not None:
                        await self._on_transport_error(exc)
                    break

        self._feeder = asyncio.create_task(_feed())

    async def stop(self) -> None:
        await self._queue.put(None)
        if self._feeder and not self._feeder.done():
            try:
                await asyncio.wait_for(self._feeder, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._feeder.cancel()

    async def output(self, audio: bytes) -> None:
        if not self._delivering:
            self._delivering = True
            await self._on_delivery_start()
        await self._on_audio_out(_resample_pcm16(audio, _ELEVEN_HZ, _BROWSER_HZ))

    async def interrupt(self) -> None:
        self._delivering = False
        await self._on_interrupt()

    async def push(self, chunk: bytes) -> None:
        """Called by ElevenLabsVoiceSession.send_audio() from the relay loop."""
        await self._queue.put(_resample_pcm16(chunk, _BROWSER_HZ, _ELEVEN_HZ))

    def reset_delivery(self) -> None:
        self._delivering = False


# ---------------------------------------------------------------------------
# Tool helpers
# ---------------------------------------------------------------------------

_EL_TOOL_CONFIGS = [
    {
        "type": "client",
        "name": "funniest_in_genre",
        "description": (
            "Return the top jokes by score for a given genre. "
            "Use this to find proven material before deciding what to try next."
        ),
        "expects_response": True,
        "parameters": {
            "type": "object",
            "properties": {
                "genre": {
                    "type": "string",
                    "description": "The genre / category label to query.",
                },
                "n": {
                    "type": "integer",
                    "description": "How many jokes to return (max 10).",
                },
            },
            "required": ["genre"],
        },
    },
    {
        "type": "client",
        "name": "get_thin_genres",
        "description": (
            "Return genres with fewer than 3 jokes in the archive. "
            "Use to find under-explored territory."
        ),
        "expects_response": True,
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "client",
        "name": "get_recent_scores",
        "description": (
            "Return the most recent N joke scores. "
            "Use to gauge how the current audience is responding."
        ),
        "expects_response": True,
        "parameters": {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "description": "Number of recent scores to return.",
                }
            },
            "required": [],
        },
    },
    {
        "type": "client",
        "name": "search_jokes",
        "description": (
            "Search the joke archive by keyword. "
            "Use to find previously filed jokes on a specific topic."
        ),
        "expects_response": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term to match against joke text.",
                }
            },
            "required": ["query"],
        },
    },
]


_TOOL_ID_CACHE: list[str] | None = None


async def _ensure_tools(client: ElevenLabs) -> list[str]:
    """Create or retrieve ElevenLabs tool IDs for our Box client functions.

    Tool names are used as the stable identity key.  If a tool with the same
    name already exists, we reuse its ID rather than creating a duplicate.
    Returns a list of tool IDs in the same order as _EL_TOOL_CONFIGS.
    Cached after the first successful lookup so later sessions skip the HTTP.
    """
    global _TOOL_ID_CACHE
    if _TOOL_ID_CACHE:
        return _TOOL_ID_CACHE
    try:
        tool_list = client.conversational_ai.tools.list()
        existing: dict[str, str] = {}
        for t in tool_list.tools:
            try:
                # tool_config is a discriminated union; all client tools have .name
                cfg = t.tool_config
                name = getattr(cfg, "name", None)
                if name:
                    existing[name] = t.id
            except Exception:
                pass
    except Exception:
        existing = {}

    ids: list[str] = []
    for cfg in _EL_TOOL_CONFIGS:
        name = cfg["name"]
        if name in existing:
            ids.append(existing[name])
            continue
        try:
            tool = client.conversational_ai.tools.create(
                request=ToolRequestModel(tool_config=cfg)  # type: ignore[arg-type]
            )
            ids.append(tool.id)
        except Exception:
            if name in existing:
                ids.append(existing[name])
    _TOOL_ID_CACHE = ids
    return ids


async def _ensure_agent(client: ElevenLabs, tool_ids: list[str], voice_id: str) -> str:
    """Find the Joker agent or create it with the Box tool schemas.

    If ELEVENLABS_AGENT_ID is set in the environment, that agent is used as-is.
    Tool IDs are overridden per-session via conversation_config_override so the
    agent config is not stale even if new Box tools are added.
    Otherwise, we search for an agent tagged "joker-box" and create one if absent.
    """
    agent_id_env = os.environ.get("ELEVENLABS_AGENT_ID", "").strip()
    if agent_id_env:
        return agent_id_env

    # Search for an existing Joker agent by name prefix
    try:
        page = client.conversational_ai.agents.list(search="joker-box")
        for agent in page.agents:
            if "joker-box" in (agent.tags or []):
                return agent.agent_id
    except Exception:
        pass

    # Create a new agent
    try:
        agent = client.conversational_ai.agents.create(
            name="joker-box",
            tags=["joker-box"],
            conversation_config=ConversationalConfig(
                agent=AgentConfig(
                    prompt=PromptAgentApiModelOutput(
                        prompt="You are Eddie Voss, a late-night stand-up host.",
                        tool_ids=tool_ids,
                        llm="gpt-4o",
                    ),
                    first_message="",
                ),
                tts=TtsConversationalConfigOutput(
                    voice_id=voice_id,
                ),
            ),
        )
        return agent.agent_id
    except Exception as exc:
        raise RuntimeError(
            "Could not find or create ElevenLabs Joker agent.  "
            "Set ELEVENLABS_AGENT_ID in your environment."
        ) from exc


# ---------------------------------------------------------------------------
# ElevenLabs session
# ---------------------------------------------------------------------------


class ElevenLabsVoiceSession(VoiceSession):
    """Full-duplex voice via ElevenLabs Conversational AI SDK.

    Fires VoiceCallbacks so the orchestrator contains no ElevenLabs-specific
    protocol code.
    """

    def __init__(self, callbacks: VoiceCallbacks) -> None:
        super().__init__(callbacks)
        self._bridge: _BrowserAudioBridge | None = None
        self._conversation: AsyncConversation | None = None
        self._client: ElevenLabs | None = None
        self._task_done = asyncio.Event()
        self._delivery_start_time: float | None = None
        self._last_agent_response = ""
        self._interrupt_fired = False
        self._dead = False

    async def start(
        self,
        *,
        system_prompt: str,
        first_message: str | None = None,
    ) -> None:
        api_key = os.environ["ELEVENLABS_API_KEY"]
        voice_id = os.environ.get("ELEVENLABS_VOICE_ID", _DEFAULT_VOICE_ID)

        self._client = ElevenLabs(api_key=api_key)

        tool_ids = await _ensure_tools(self._client)
        agent_id = await _ensure_agent(self._client, tool_ids, voice_id)

        # Register Box tool handlers (each gets its own db session)
        client_tools = _make_client_tools(self.callbacks.on_tool_call)

        # Do not PATCH the agent or send conversation_config_override here.
        # Both are extra HTTP / 1008 policy violations and they delay first
        # audio. The agent already has a prompt; the set script arrives later
        # via send_contextual_update while he is already talking.
        from joker.timing import mark as _tmark

        if first_message:
            try:
                await asyncio.to_thread(
                    self._client.conversational_ai.agents.update,
                    agent_id,
                    conversation_config=ConversationalConfig(
                        agent=AgentConfig(first_message=first_message)
                    ),
                )
            except Exception as exc:
                print(f"[elevenlabs] first_message patch failed: {exc}", flush=True)

        config = ConversationInitiationData()

        cb = self.callbacks

        async def _on_interrupt_from_bridge() -> None:
            self._interrupt_fired = True
            # The full barge-in event fires from _on_agent_correction when
            # agent_response_correction arrives.  Here we just note it happened.

        self._bridge = _BrowserAudioBridge(
            on_audio_out=cb.on_audio_chunk,
            on_interrupt=_on_interrupt_from_bridge,
            on_delivery_start=self._handle_delivery_start,
            on_transport_error=self._fail_if_quota,
        )

        self._conversation = AsyncConversation(
            client=self._client,
            agent_id=agent_id,
            requires_auth=True,
            audio_interface=self._bridge,
            config=config,
            client_tools=client_tools,
            callback_agent_response=self._on_agent_response,
            callback_agent_response_correction=self._on_agent_correction,
            callback_user_transcript=self._on_user_transcript,
            callback_latency_measurement=self._on_latency,
            callback_end_session=self._on_session_end,
        )

        await cb.on_state_change("connected")
        await self._conversation.start_session()

    async def _handle_delivery_start(self) -> None:
        self._delivery_start_time = time.monotonic()
        await self.callbacks.on_delivery_start()
        await self.callbacks.on_state_change("speaking")

    async def _on_agent_response(self, response: str) -> None:
        self._last_agent_response = response
        # In voice mode, agent_response carries the complete text, not deltas.
        # Emit the whole text as both a delta and the done signal so the
        # transcript feed on the show page gets the content immediately.
        await self.callbacks.on_agent_transcript_delta(response)
        await self.callbacks.on_agent_transcript_done(response)

        latency_ms = (
            int((time.monotonic() - self._delivery_start_time) * 1000)
            if self._delivery_start_time is not None
            else 0
        )
        await self.callbacks.on_delivery_done(latency_ms, response)
        await self.callbacks.on_state_change("connected")
        self._delivery_start_time = None
        self._bridge.reset_delivery() if self._bridge else None

    async def _on_agent_correction(self, original: str, corrected: str) -> None:
        """Fires when the user barges in; original = intended, corrected = delivered."""
        if self._delivery_start_time is None and not self._interrupt_fired:
            # Correction with no in-flight audio is not a barge-in (0ms fake cut).
            return
        at_ms = (
            int((time.monotonic() - self._delivery_start_time) * 1000)
            if self._delivery_start_time is not None
            else 0
        )
        # cut_text = what the agent intended but hadn't finished saying
        cut_text = original
        await self.callbacks.on_barge_in(cut_text, at_ms)
        await self.callbacks.on_state_change("listening")
        self._delivery_start_time = None
        self._interrupt_fired = False
        if self._bridge:
            self._bridge.reset_delivery()

    async def _on_user_transcript(self, transcript: str) -> None:
        await self.callbacks.on_user_transcript(transcript)
        await self.callbacks.on_state_change("idle")
        await self.callbacks.on_user_speech_stop()

    async def _on_latency(self, latency_ms: int) -> None:
        # ElevenLabs ping-pong latency; logged but not forwarded to tracker
        # since it measures round-trip websocket ping, not TTS first-byte.
        pass

    async def _on_session_end(self) -> None:
        self._task_done.set()

    async def send_audio(self, chunk: bytes) -> None:
        if self._dead or self._bridge is None:
            return
        try:
            await self._bridge.push(chunk)
        except Exception as exc:
            await self._fail_if_quota(exc)

    async def _fail_if_quota(self, exc: BaseException) -> None:
        msg = str(exc)
        if self._dead:
            return
        if "quota" not in msg.lower() and "1002" not in msg:
            return
        self._dead = True
        print(f"[elevenlabs] quota/session dead: {msg}", flush=True)
        try:
            await self.callbacks.on_provider_error(
                "ElevenLabs quota exceeded. Add credits in the ElevenLabs "
                "dashboard, then start a new session."
            )
        except Exception:
            pass
        self._task_done.set()

    async def update_instructions(self, instructions: str) -> None:
        """Send a contextual update with the new set instructions."""
        if self._conversation is None:
            return
        try:
            await self._conversation.send_contextual_update(instructions)
        except Exception:
            pass

    async def speak(self, text: str) -> None:
        """Direct the agent to speak a specific line next.

        ElevenLabs has no "inject assistant message" primitive.  We send a
        strong contextual directive; the agent will respond in Eddie Voss's
        voice, which may differ slightly from the literal text.
        See docs/DECISIONS.md 2026-09-02 for the accepted trade-off.
        """
        if self._conversation is None:
            return
        try:
            await self._conversation.send_contextual_update(
                f"[HOST DIRECTIVE — say this next, in your voice]: {text}"
            )
        except Exception:
            pass

    async def wait(self) -> None:
        await self._task_done.wait()

    async def close(self) -> None:
        if self._conversation:
            try:
                await self._conversation.end_session()
            except Exception:
                pass
        self._task_done.set()


# ---------------------------------------------------------------------------
# ClientTools factory
# ---------------------------------------------------------------------------


def _make_client_tools(
    on_tool_call: Callable[[str, dict], Awaitable[Any]],
) -> ClientTools:
    """Register all Box tools with an ElevenLabs ClientTools instance.

    Each handler is async and routes through the orchestrator's on_tool_call
    callback so the dispatch_tool() call (and its db session) lives in
    realtime.py, not here.
    """
    client_tools = ClientTools()

    for tool_name in ("funniest_in_genre", "get_thin_genres", "get_recent_scores", "search_jokes"):
        # Create a closure binding the tool_name
        def _make_handler(name: str) -> Callable[[dict], Awaitable[Any]]:
            async def _handler(params: dict) -> Any:
                return await on_tool_call(name, params)

            return _handler

        client_tools.register(tool_name, _make_handler(tool_name), is_async=True)

    return client_tools
