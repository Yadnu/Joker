"""Joker — joke generation.

Two-path generation:
  - GOOD_MODEL (gpt-4o)       for intended_quality="good"
  - BAD_MODEL  (gpt-4o-mini)  for intended_quality="bad"

Deliberate quality variance is a hard requirement.  Both paths must be
exercised; routing is explicit and stored in provenance.

For each call, three candidates are generated and the best (for "good") or
worst (for "bad") is selected.  selection_rationale is stored in provenance
and in the trace.
"""

from __future__ import annotations

import time
from typing import Literal

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.records import Provenance
from shared.trace import record_step

_client = AsyncOpenAI()

GOOD_MODEL = "gpt-4o"
BAD_MODEL = "gpt-4o-mini"
_CANDIDATE_COUNT = 3


async def generate(
    *,
    joke_id: str,
    topic: str,
    style: str,
    intended_quality: Literal["good", "bad"],
    user_context: str,
    session: AsyncSession,
) -> tuple[str, Provenance]:
    """Generate a joke and return (joke_text, provenance).

    intended_quality controls both model selection and candidate ranking:
      "good" -> gpt-4o, keep the sharpest candidate.
      "bad"  -> gpt-4o-mini, keep the flattest / most groan-worthy candidate.

    provenance is fully populated so the caller can store it in the joke record.
    """
    model = GOOD_MODEL if intended_quality == "good" else BAD_MODEL
    t0 = time.monotonic()

    system_prompt = _system_prompt(intended_quality)
    user_prompt = _user_prompt(topic, style, user_context, intended_quality)

    response = await _client.chat.completions.create(
        model=model,
        n=_CANDIDATE_COUNT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    latency_ms = int((time.monotonic() - t0) * 1000)

    candidates = [
        choice.message.content or "" for choice in response.choices
    ]

    joke_text, selection_rationale = _select(candidates, intended_quality)

    provenance = Provenance(
        source="generated",
        model=model,
        prompt=user_prompt,
        selection_rationale=selection_rationale,
    )

    await record_step(
        artifact_id=joke_id,
        artifact_type="joke",
        kind="generation",
        actor="joker.generate",
        model=model,
        prompt_ref=f"joker/generate_{intended_quality}_v1",
        inputs={
            "topic": topic,
            "style": style,
            "intended_quality": intended_quality,
            "user_context": user_context,
            "candidate_count": _CANDIDATE_COUNT,
        },
        output={
            "joke_text": joke_text,
            "candidates": candidates,
            "selection_rationale": selection_rationale,
        },
        rationale=(
            f"Used {model} for intended_quality={intended_quality!r}. "
            f"Selected from {_CANDIDATE_COUNT} candidates. {selection_rationale}"
        ),
        latency_ms=latency_ms,
        cost=_estimate_cost(response, model),
        session=session,
    )

    return joke_text, provenance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _system_prompt(intended_quality: Literal["good", "bad"]) -> str:
    if intended_quality == "good":
        return (
            "You are a sharp stand-up comedian. "
            "Write tight, punchy jokes with clear setup and a surprising punchline. "
            "Aim for genuine laughs."
        )
    return (
        "You are a deliberately mediocre comedian. "
        "Write jokes that are predictable, slightly groan-worthy, or use tired tropes. "
        "They should be recognisably joke-shaped but not actually funny."
    )


def _user_prompt(
    topic: str,
    style: str,
    user_context: str,
    intended_quality: Literal["good", "bad"],
) -> str:
    quality_note = (
        "Make it as sharp and funny as possible."
        if intended_quality == "good"
        else "Make it deliberately mediocre or groan-worthy."
    )
    return (
        f"Topic: {topic}\n"
        f"Style: {style}\n"
        f"Listener context: {user_context}\n"
        f"Write one {style} joke about {topic}. {quality_note}"
    )


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
        chosen = max(candidates, key=len)
        rationale = (
            f"Longest of {len(candidates)} candidates; "
            "heuristic for most-developed punchline before live scoring."
        )
    else:
        chosen = min(candidates, key=len)
        rationale = (
            f"Shortest of {len(candidates)} candidates; "
            "heuristic for most predictable / flattest delivery."
        )
    return chosen.strip(), rationale


def _estimate_cost(response, model: str) -> float | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if model == GOOD_MODEL:
        # gpt-4o: ~$5/1M input, $15/1M output
        return (usage.prompt_tokens * 5 + usage.completion_tokens * 15) / 1_000_000
    # gpt-4o-mini: ~$0.15/1M input, $0.60/1M output
    return (usage.prompt_tokens * 0.15 + usage.completion_tokens * 0.60) / 1_000_000
