"""Joker — joke generation.

Two-path generation:
  - GENERATE_GOOD (frontier, default o3) for intended_quality="good"
  - GENERATE_BAD  (cheap, default gpt-4o-mini) for intended_quality="bad"

Deliberate quality variance is a hard requirement.  Both paths must be
exercised; routing is explicit and stored in provenance.

Three tone levels (independent of intended_quality):
  1 STANDARD  — mainstream late-night, no content warnings needed
  2 EDGIER    — gallows humor, cynicism, existential dread played for laughs
  3 DARKEST   — genuinely bleak, still ceiling-bound; no level beyond this

Model routing depends on intended_quality only, never on tone_level.
A level-3 joke can be intended-bad; a level-1 joke can be intended-good.

For each call, three candidates are generated and the best (for "good") or
worst (for "bad") is selected.  selection_rationale is stored in provenance
and in the trace.

Prompts are versioned files: persona_v1.md + tone_{n}_v1.md are loaded once
at import time and concatenated as the system prompt.  prompt_ref in the trace
stores the tone file path so a Viewer can open the exact prompt a joke was
generated under.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Literal

from openai import AsyncOpenAI, RateLimitError
from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.records import Provenance
from shared.models import GENERATE_GOOD, GENERATE_BAD, build_messages, completion_kwargs
from shared.trace import record_step

_client = AsyncOpenAI()

GOOD_MODEL = GENERATE_GOOD
BAD_MODEL  = GENERATE_BAD
_CANDIDATE_COUNT = 3

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Load the persona once; it is prepended to every tone prompt.
_PERSONA = (_PROMPTS_DIR / "persona_v1.md").read_text(encoding="utf-8").strip()
_GOOD_SYSTEM = (_PROMPTS_DIR / "generate_good_v1.txt").read_text(encoding="utf-8").strip()

_TONE_FILE_NAMES: dict[int, str] = {
    1: "tone_1_standard_v1.md",
    2: "tone_2_edgier_v1.md",
    3: "tone_3_darkest_v1.md",
}


def _load_tone(n: int) -> str:
    raw = (_PROMPTS_DIR / _TONE_FILE_NAMES[n]).read_text(encoding="utf-8")
    return raw.format(persona=_PERSONA).strip()


_TONE_PROMPTS: dict[int, str] = {
    1: _load_tone(1),
    2: _load_tone(2),
    3: _load_tone(3),
}

# Tone prompt file paths used as prompt_ref in trace (points to the tone file,
# not the persona, since the tone file governs what kind of joke was requested).
_TONE_PROMPT_REFS: dict[int, str] = {
    n: f"prompts/{_TONE_FILE_NAMES[n]}" for n in (1, 2, 3)
}

# User-prompt templates, kept for the bad-joke path which still uses the
# original templates.  The good path and all tone paths use the same user
# template; the system prompt is what varies by tone.
_GOOD_USER_TEMPLATE = (_PROMPTS_DIR / "generate_good_user_v1.txt").read_text(encoding="utf-8")
_BAD_USER_TEMPLATE = (_PROMPTS_DIR / "generate_bad_user_v1.txt").read_text(encoding="utf-8")


async def generate(
    *,
    joke_id: str,
    topic: str,
    tone_level: Literal[1, 2, 3] = 1,
    intended_quality: Literal["good", "bad"],
    user_context: str,
    set_position: int = 1,
    session: AsyncSession,
    style: str = "one-liner",
) -> tuple[str, Provenance]:
    """Generate a joke and return (joke_text, provenance).

    tone_level and intended_quality are INDEPENDENT axes.
      - tone_level selects the system prompt (1=standard, 2=edgier, 3=darkest)
      - intended_quality selects the model and candidate ranking strategy

    provenance is fully populated so the caller can store it in the joke record.
    """
    model = GOOD_MODEL if intended_quality == "good" else BAD_MODEL
    system_prompt = _TONE_PROMPTS[tone_level]
    if intended_quality == "good":
        system_prompt = f"{system_prompt}\n\n{_GOOD_SYSTEM}"
    user_prompt = _user_prompt(topic, style, user_context, intended_quality)
    prompt_ref = _TONE_PROMPT_REFS[tone_level]

    t0 = time.monotonic()

    from shared.models import is_reasoning_model
    try:
        if is_reasoning_model(model):
            raw_responses = []
            for _ in range(_CANDIDATE_COUNT):
                r = await _chat(model, system_prompt, user_prompt, n=1)
                raw_responses.append(r.choices[0].message.content or "")
            response = r
            candidates = raw_responses
        else:
            response = await _chat(model, system_prompt, user_prompt, n=_CANDIDATE_COUNT)
            candidates = [choice.message.content or "" for choice in response.choices]
    except RateLimitError:
        print("[429] generate: rate limit exhausted; dropping this joke", flush=True)
        raise

    latency_ms = int((time.monotonic() - t0) * 1000)
    joke_text, selection_rationale = _select(candidates, intended_quality)

    provenance = Provenance(
        source="generated",
        model=model,
        prompt=user_prompt,
        selection_rationale=(
            f"intended_quality={intended_quality!r}, tone_level={tone_level}, "
            f"set_position={set_position}. {selection_rationale}"
        ),
    )

    await record_step(
        artifact_id=joke_id,
        artifact_type="joke",
        kind="generation",
        actor="joker.generate",
        model=model,
        prompt_ref=prompt_ref,
        inputs={
            "topic": topic,
            "style": style,
            "tone_level": tone_level,
            "intended_quality": intended_quality,
            "user_context": user_context,
            "set_position": set_position,
            "candidate_count": _CANDIDATE_COUNT,
        },
        output={
            "joke_text": joke_text,
            "candidates": candidates,
            "selection_rationale": selection_rationale,
        },
        rationale=(
            f"Used {model} for intended_quality={intended_quality!r} at "
            f"tone_level={tone_level} (prompt: {prompt_ref}). "
            f"Set position {set_position}. "
            f"Selected from {_CANDIDATE_COUNT} candidates. {selection_rationale}"
        ),
        latency_ms=latency_ms,
        cost=_estimate_cost(response, model),
        session=session,
    )

    return joke_text, provenance


async def _chat(model: str, system_prompt: str, user_prompt: str, n: int):
    delay = 0.4
    last: RateLimitError | None = None
    for attempt in range(4):
        try:
            kwargs = completion_kwargs(
                model,
                messages=build_messages(system_prompt, user_prompt, model),
            )
            if n > 1:
                kwargs["n"] = n
            return await _client.chat.completions.create(**kwargs)
        except RateLimitError as exc:
            last = exc
            print(f"[429] generate attempt {attempt + 1}; backing off {delay}s", flush=True)
            await asyncio.sleep(delay)
            delay *= 2
    assert last is not None
    raise last


def _user_prompt(
    topic: str,
    style: str,
    user_context: str,
    intended_quality: Literal["good", "bad"],
) -> str:
    template = _GOOD_USER_TEMPLATE if intended_quality == "good" else _BAD_USER_TEMPLATE
    return template.format(topic=topic, style=style, user_context=user_context).strip()


def _select(
    candidates: list[str], intended_quality: Literal["good", "bad"]
) -> tuple[str, str]:
    """Select the best or worst candidate.

    For "good": prefer the longest candidate as a heuristic for more developed
    punchline (a real scorer would use the Librarian's score module, but we
    cannot score before delivery).

    For "bad": prefer the shortest, most predictable-looking candidate.
    """
    if not candidates:
        raise ValueError("No candidates returned from model.")

    if intended_quality == "good":
        _BANNED = ("here's a joke", "here is a joke", "so anyway", "let me tell")
        viable = [
            c.strip()
            for c in candidates
            if c.strip() and not any(b in c.lower() for b in _BANNED)
        ] or [c.strip() for c in candidates if c.strip()]
        def _punchiness(text: str) -> tuple[int, int]:
            words = text.split()
            n = len(words)
            # Prefer spoken length; penalize essays and one-word stubs.
            length_score = -abs(n - 28)
            last_is_short = 1 if words and len(words[-1].strip(".,!?")) <= 10 else 0
            return (length_score, last_is_short)
        chosen = max(viable, key=_punchiness)
        rationale = (
            f"intended_quality=good; "
            f"picked punchiest of {len(viable)} candidates (spoken length, last-word punch)."
        )
    else:
        chosen = min(candidates, key=len)
        rationale = (
            f"intended_quality=bad; shortest of {len(candidates)} candidates; "
            "heuristic for most predictable / flattest delivery."
        )
    return chosen.strip(), rationale


def _estimate_cost(response, model: str) -> float | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if model == GOOD_MODEL:
        # o3 pricing (approximate): $10/1M input, $40/1M output
        return (usage.prompt_tokens * 10 + usage.completion_tokens * 40) / 1_000_000
    # gpt-4o-mini: ~$0.15/1M input, $0.60/1M output
    return (usage.prompt_tokens * 0.15 + usage.completion_tokens * 0.60) / 1_000_000
