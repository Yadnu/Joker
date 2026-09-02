"""Librarian — joke scoring.

Assigns an integer 0–10 against a versioned rubric with written anchors.
The rubric version is stored in every trace so score trends can be compared
across rubric versions.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import SCORE_MODEL, build_messages, completion_kwargs
from shared.trace import record_step

_client = AsyncOpenAI()

RUBRIC_VERSION = "1.0"

RUBRIC: dict[int, str] = {
    0: "No reaction or explicit negative response (groan, silence, 'that's terrible').",
    3: "Polite acknowledgment; no laughter or genuine amusement ('haha', said flatly).",
    6: "Clear amusement; one or two genuine laughs or a smile audible in the voice.",
    10: "Sustained laughter; listener repeats the punchline, asks for more, or says it was the best joke they've heard.",
}

# Versioned prompt file, not an inline f-string. See docs/DECISIONS.md
# 2026-09-01 "Prompts moved to versioned files".
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_SYSTEM_PROMPT = (_PROMPTS_DIR / "score_v1.txt").read_text(encoding="utf-8").strip()
_USER_TEMPLATE = (_PROMPTS_DIR / "score_user_v1.txt").read_text(encoding="utf-8")


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
    prompt = _USER_TEMPLATE.format(
        rubric_version=RUBRIC_VERSION,
        rubric_text=rubric_text,
        joke_text=joke_text,
        user_reaction=user_reaction,
        user_context=user_context,
    ).strip()

    system = _SYSTEM_PROMPT
    response = await _client.chat.completions.create(
        **completion_kwargs(
            SCORE_MODEL,
            response_format={"type": "json_object"},
            messages=build_messages(system, prompt, SCORE_MODEL),
        )
    )

    latency_ms = int((time.monotonic() - t0) * 1000)

    raw = json.loads(response.choices[0].message.content or "{}")
    result_score = int(raw.get("score", 5))
    rationale: str = str(raw.get("rationale") or "").strip()
    if not rationale:
        raise ValueError("score rationale is required and must be a non-empty string.")

    # Clamp to valid range
    result_score = max(0, min(10, result_score))

    await record_step(
        artifact_id=joke_id,
        artifact_type="joke",
        kind="scoring",
        actor="librarian.score",
        model=SCORE_MODEL,
        prompt_ref="prompts/score_user_v1.txt",
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
