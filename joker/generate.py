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

Prompts are versioned files: persona_v2.md + tone_{n}_v2.md are loaded once
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
from shared.models import (
    GENERATE_GOOD,
    GENERATE_BAD,
    build_messages,
    completion_kwargs,
    is_reasoning_model,
)
from shared.trace import record_step

_client = AsyncOpenAI()

GOOD_MODEL = GENERATE_GOOD
BAD_MODEL  = GENERATE_BAD
_CANDIDATE_COUNT = 3

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Load the persona once; it is prepended to every tone prompt.
_PERSONA = (_PROMPTS_DIR / "persona_v3.md").read_text(encoding="utf-8").strip()
_GOOD_SYSTEM = (_PROMPTS_DIR / "generate_good_v3.txt").read_text(encoding="utf-8").strip()

_TONE_FILE_NAMES: dict[int, str] = {
    1: "tone_1_standard_v3.md",
    2: "tone_2_edgier_v3.md",
    3: "tone_3_darkest_v3.md",
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
_GOOD_USER_TEMPLATE = (_PROMPTS_DIR / "generate_good_user_v3.txt").read_text(encoding="utf-8")
_BAD_USER_TEMPLATE = (_PROMPTS_DIR / "generate_bad_user_v1.txt").read_text(encoding="utf-8")

JOKE_SHAPES: tuple[str, ...] = (
    "one-liner",
    "escalating-premise",
    "misdirect",
    "story-gone-wrong",
    "callback",
    "aside",
)

# The mechanism that makes the bit funny, independent of its shape. Rotating
# only the shape still produced eleven variations of "an object acts human".
JOKE_ENGINES: tuple[str, ...] = (
    "reframe",
    "understatement",
    "false-logic",
    "escalation",
    "misdirect",
    "malicious-compliance",
    "wrong-person-indicted",
    "aside",
    "specificity-swap",
    "admission",
    "straight-then-polish",
)

# Constructions that read as machine-written. Candidates containing these are
# ranked last; the prompts also ban them by name.
_CRUTCHES = (
    "like it's",
    "like it was",
    "as if it",
    "living its best life",
    "expects a tip",
    "charging it rent",
    "fine dining",
    "auditioning for",
    "welcome to",
    "let that sink in",
    "plot twist",
    "these days",
    "apparently",
    "basically",
    "the going rate for",
)

_BANNED_TICS = (
    "your move",
    "talk to me",
    "over to you",
    "what do you think",
    "hit me",
    "your turn",
    "how's that",
    "am i right",
    "here's a joke",
    "here is a joke",
    "so anyway",
    "let me tell",
    "you ever notice",
    "so here's the thing",
)

_SESSION_CLOSINGS = (
    "somebody ruin that",
    "i'll wait. i have a suit",
    "if you've got a better ending",
    "that's the bit. you can sit with it",
    "don't clap. think. worse",
    "i'm empty. throw me a noun",
    "i'll pick on the thermostat",
    "your move",
    "talk to me",
    "over to you",
    "keep the floor",
)


def strip_repeated_closings(text: str, used: set[str]) -> str:
    """Drop a closing that already fired this session. Track every hit."""
    kept = text.strip()
    lower = kept.lower()
    for phrase in _SESSION_CLOSINGS:
        if phrase not in lower:
            continue
        if phrase in used:
            parts = [p.strip() for p in kept.replace("?", ".").split(".") if p.strip()]
            if len(parts) > 1:
                kept = ". ".join(parts[:-1]).rstrip(".") + "."
                lower = kept.lower()
        used.add(phrase)
    return kept


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
    shape: str | None = None,
    last_shape: str | None = None,
    engine: str | None = None,
    last_engine: str | None = None,
    form: str = "stand-up bit",
    avoid: list[str] | None = None,
    candidate_count: int | None = None,
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
    user_prompt = _user_prompt(
        topic,
        style,
        user_context,
        intended_quality,
        shape=shape or style,
        last_shape=last_shape or "none",
        engine=engine or next_engine(last_engine=last_engine),
        last_engine=last_engine or "none",
        form=form,
        avoid=avoid or [],
    )
    prompt_ref = _TONE_PROMPT_REFS[tone_level]
    # A live request cannot wait for three full draft-then-sharpen passes; one
    # candidate still drafts three attempts internally before committing.
    n_candidates = candidate_count or _CANDIDATE_COUNT

    t0 = time.monotonic()

    try:
        if is_reasoning_model(model):
            raw_responses = []
            for _ in range(n_candidates):
                r = await _chat(model, system_prompt, user_prompt, n=1)
                raw_responses.append(r.choices[0].message.content or "")
            response = r
            candidates = raw_responses
        else:
            response = await _chat(
                model,
                system_prompt,
                user_prompt,
                n=n_candidates,
                # Push the three candidates apart so the set does not converge
                # on one phrasing; only the good path is ranked for surprise.
                sampling=_GOOD_SAMPLING if intended_quality == "good" else None,
            )
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
            "shape": shape,
            "last_shape": last_shape,
            "engine": engine,
            "last_engine": last_engine,
            "form": form,
            "avoid_count": len(avoid or []),
            "candidate_count": n_candidates,
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
            f"Selected from {n_candidates} candidate(s). {selection_rationale}"
        ),
        latency_ms=latency_ms,
        cost=_estimate_cost(response, model),
        session=session,
    )

    return joke_text, provenance


_GOOD_SAMPLING = {
    "temperature": 1.05,
    "frequency_penalty": 0.35,
    "presence_penalty": 0.45,
}


async def _chat(
    model: str,
    system_prompt: str,
    user_prompt: str,
    n: int,
    sampling: dict | None = None,
):
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
            if sampling and not is_reasoning_model(model):
                kwargs.update(sampling)
            return await _client.chat.completions.create(**kwargs)
        except RateLimitError as exc:
            last = exc
            print(f"[429] generate attempt {attempt + 1}; backing off {delay}s", flush=True)
            await asyncio.sleep(delay)
            delay *= 2
    assert last is not None
    raise last


def next_shape(*, last_shape: str | None, slot_idx: int) -> str:
    """Pick a spoken shape. Never the same as last_shape. Callback needs history."""
    import random

    options = [s for s in JOKE_SHAPES if s != last_shape]
    if slot_idx == 0:
        options = [s for s in options if s != "callback"]
    return random.choice(options) if options else "one-liner"


def next_engine(*, last_engine: str | None) -> str:
    """Pick the comic mechanism. Never the same as the previous bit's."""
    import random

    options = [e for e in JOKE_ENGINES if e != last_engine]
    return random.choice(options) if options else "reframe"


def _user_prompt(
    topic: str,
    style: str,
    user_context: str,
    intended_quality: Literal["good", "bad"],
    *,
    shape: str = "one-liner",
    last_shape: str = "none",
    engine: str = "reframe",
    last_engine: str = "none",
    form: str = "stand-up bit",
    avoid: list[str] | None = None,
) -> str:
    if intended_quality == "bad":
        return _BAD_USER_TEMPLATE.format(
            topic=topic, style=style, user_context=user_context
        ).strip()
    spent = avoid or []
    return _GOOD_USER_TEMPLATE.format(
        topic=topic,
        style=style,
        user_context=user_context,
        shape=shape,
        last_shape=last_shape,
        engine=engine,
        last_engine=last_engine,
        form=form,
        avoid="; ".join(spent[-12:]) if spent else "nothing yet",
    ).strip()


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

    cleaned = [_extract_final(c) for c in candidates]

    if intended_quality == "good":
        viable = [
            c
            for c in cleaned
            if c and not any(b in c.lower() for b in _BANNED_TICS)
        ] or [c for c in cleaned if c]

        def _punchiness(text: str) -> tuple[int, int, int, int]:
            lower = text.lower()
            words = text.split()
            n = len(words)
            no_crutch = 0 if any(c in lower for c in _CRUTCHES) else 1
            # A proper noun or a number is the specificity the prompts demand.
            concrete = 1 if any(
                w[:1].isupper() or any(ch.isdigit() for ch in w)
                for w in words[1:]
            ) else 0
            # Prefer spoken length; penalize essays and one-word stubs.
            length_score = -abs(n - 28)
            last_is_short = 1 if words and len(words[-1].strip(".,!?\"'")) <= 10 else 0
            return (no_crutch, concrete, length_score, last_is_short)

        chosen = max(viable, key=_punchiness)
        picked = _punchiness(chosen)
        rationale = (
            f"intended_quality=good; picked best of {len(viable)} candidates on "
            f"crutch-free={bool(picked[0])}, names-something-concrete={bool(picked[1])}, "
            "spoken length, last-word punch."
        )
    else:
        chosen = min(cleaned, key=len)
        rationale = (
            f"intended_quality=bad; shortest of {len(cleaned)} candidates; "
            "heuristic for most predictable / flattest delivery."
        )
    return chosen.strip(), rationale


def _extract_final(text: str) -> str:
    """Return the spoken line from a draft-then-sharpen response.

    The good-path system prompt lets the model write attempts before committing
    to a line prefixed `FINAL:`. Anything before that prefix is working-out and
    must never reach the stage.
    """
    body = (text or "").strip()
    marker = body.rfind("FINAL:")
    if marker >= 0:
        body = body[marker + len("FINAL:"):]
    # Models format multi-part bits as markdown lines; TTS wants one utterance.
    line = " ".join(body.split())
    return line.strip().strip('"').strip()


def _estimate_cost(response, model: str) -> float | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if model == GOOD_MODEL:
        # o3 pricing (approximate): $10/1M input, $40/1M output
        return (usage.prompt_tokens * 10 + usage.completion_tokens * 40) / 1_000_000
    # gpt-4o-mini: ~$0.15/1M input, $0.60/1M output
    return (usage.prompt_tokens * 0.15 + usage.completion_tokens * 0.60) / 1_000_000
