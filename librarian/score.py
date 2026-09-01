"""Librarian — joke scoring.

Assigns an integer 0–10 against a versioned rubric with written anchors.
The rubric version is stored in every trace so score trends can be compared
across rubric versions.
"""

from __future__ import annotations

import json
import time

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from shared.trace import record_step

_client = AsyncOpenAI()

RUBRIC_VERSION = "1.0"

RUBRIC: dict[int, str] = {
    0: "No reaction or explicit negative response (groan, silence, 'that's terrible').",
    3: "Polite acknowledgment; no laughter or genuine amusement ('haha', said flatly).",
    6: "Clear amusement; one or two genuine laughs or a smile audible in the voice.",
    10: "Sustained laughter; listener repeats the punchline, asks for more, or says it was the best joke they've heard.",
}


async def score(
    *,
    joke_id: str,
    joke_text: str,
    user_reaction: str,
    user_context: str,
    session: AsyncSession,
) -> int:
    """Score a joke 0–10 against RUBRIC.

    The rubric version is stored in the trace inputs so scores produced under
    different rubric versions are never silently mixed.
    """
    t0 = time.monotonic()

    rubric_text = "\n".join(f"  {k}: {v}" for k, v in sorted(RUBRIC.items()))
    prompt = (
        f"Scoring rubric (version {RUBRIC_VERSION}):\n{rubric_text}\n\n"
        f"Joke:\n{joke_text}\n\n"
        f"User reaction:\n{user_reaction}\n\n"
        f"Listener context:\n{user_context}\n\n"
        "Return a JSON object with a single key 'score' (integer 0-10) "
        "and a key 'rationale' (one sentence)."
    )

    response = await _client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a neutral comedy evaluator. "
                    "Score the joke strictly against the provided rubric anchors. "
                    "Interpolate linearly between anchors."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    latency_ms = int((time.monotonic() - t0) * 1000)

    raw = json.loads(response.choices[0].message.content or "{}")
    result_score = int(raw.get("score", 5))
    rationale: str = raw.get("rationale", "No rationale provided by model.").strip()

    # Clamp to valid range
    result_score = max(0, min(10, result_score))

    await record_step(
        artifact_id=joke_id,
        artifact_type="joke",
        kind="scoring",
        actor="librarian.score",
        model="gpt-4o-mini",
        prompt_ref="librarian/score_v1",
        inputs={
            "joke_text": joke_text,
            "user_reaction": user_reaction,
            "user_context": user_context,
            "rubric_version": RUBRIC_VERSION,
        },
        output={"score": result_score, "rationale": rationale},
        rationale=rationale,
        latency_ms=latency_ms,
        cost=_estimate_cost(response),
        session=session,
    )

    return result_score


def _estimate_cost(response) -> float | None:  # type: ignore[no-untyped-def]
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return (usage.prompt_tokens * 0.15 + usage.completion_tokens * 0.60) / 1_000_000
