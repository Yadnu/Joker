"""Librarian — pre-generation suggestion.

Runs BEFORE generation.  Queries the Box for:
  1. High-scoring jokes whose category overlaps listener context keywords.
  2. Genre coverage counts (genres with < 3 jokes are "thin").

Returns a ranked list of Angles.  An empty result is a RuntimeError because
feeding the Joker material before generation is a hard requirement.
"""

from __future__ import annotations

import time

from openai import AsyncOpenAI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.models import Joke
from librarian.interface import (
    Angle,
    SuggestionRequest,
    SuggestionResponse,
)
from shared.models import SUGGEST_MODEL, build_messages, completion_kwargs
from shared.trace import record_step

_client = AsyncOpenAI()

_THIN_THRESHOLD = 3
_HIGH_SCORE_THRESHOLD = 7


async def suggest(
    request: SuggestionRequest,
    session: AsyncSession,
) -> SuggestionResponse:
    """Return ranked Angles for the Joker to choose from.

    Two DB queries are always run:
      - High-scorers: jokes with score >= 7 filtered by listener context.
      - Thin genres:  genres with fewer than 3 jokes, for variety.

    The model then ranks and writes a rationale for each angle.
    """
    t0 = time.monotonic()

    # --- Query 1: high-scoring jokes relevant to listener context --------
    context_keywords = _extract_keywords(request.user_context)
    high_scorers_stmt = (
        select(Joke.category, Joke.joke_text, Joke.score)
        .where(Joke.score >= _HIGH_SCORE_THRESHOLD)
        .order_by(Joke.score.desc())
        .limit(20)
    )
    high_result = await session.execute(high_scorers_stmt)
    high_rows = high_result.all()

    # --- Query 2: genre coverage counts ----------------------------------
    coverage_stmt = select(Joke.category, func.count(Joke.id).label("n")).group_by(
        Joke.category
    )
    coverage_result = await session.execute(coverage_stmt)
    coverage: dict[str, int] = {row.category: row.n for row in coverage_result.all()}

    thin_genres = [g for g, n in coverage.items() if n < _THIN_THRESHOLD]

    # --- Model call: rank and write rationales ---------------------------
    prompt = _build_prompt(
        user_context=request.user_context,
        listener_history=request.listener_history,
        high_scorers=high_rows,
        thin_genres=thin_genres,
        coverage=coverage,
        context_keywords=context_keywords,
    )

    system = (
        "You are the Librarian for an AI comedian. "
        "Return a JSON object with key 'angles', a list of objects each "
        "with keys: genre, topic, rationale, freshness_score (0.0-1.0). "
        "Thin genres should have higher freshness_score. "
        "Return at least 3 angles."
    )
    model_t0 = time.monotonic()
    response = await _client.chat.completions.create(
        **completion_kwargs(
            SUGGEST_MODEL,
            response_format={"type": "json_object"},
            messages=build_messages(system, prompt, SUGGEST_MODEL),
        )
    )
    model_ms = int((time.monotonic() - model_t0) * 1000)

    import json

    raw = json.loads(response.choices[0].message.content or "{}")
    angles = [
        Angle(
            genre=a["genre"],
            topic=a["topic"],
            rationale=a["rationale"],
            freshness_score=float(a.get("freshness_score", 0.5)),
        )
        for a in raw.get("angles", [])
    ]

    if not angles:
        raise RuntimeError(
            "Librarian.suggest returned zero angles. "
            "Feeding material to the Joker is a hard requirement."
        )

    total_ms = int((time.monotonic() - t0) * 1000)

    await record_step(
        artifact_id=f"suggestion:{request.taxonomy_snapshot_version}",
        artifact_type="suggestion",
        kind="suggestion",
        actor="librarian.suggest",
        model=SUGGEST_MODEL,
        prompt_ref="librarian/suggest_v1",
        inputs={
            "user_context": request.user_context,
            "listener_history": request.listener_history,
            "taxonomy_snapshot_version": request.taxonomy_snapshot_version,
            "high_scorer_count": len(high_rows),
            "thin_genres": thin_genres,
        },
        output={"angles": [a.model_dump() for a in angles]},
        rationale=(
            f"Queried {len(high_rows)} high-scoring jokes and found "
            f"{len(thin_genres)} thin genre(s). "
            f"Model ranked {len(angles)} angles for listener context."
        ),
        latency_ms=total_ms,
        cost=_estimate_cost(response),
        session=session,
    )

    return SuggestionResponse(angles=angles)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_keywords(user_context: str) -> list[str]:
    return [w.lower().strip(".,;:") for w in user_context.split() if len(w) > 3]


def _build_prompt(
    *,
    user_context: str,
    listener_history: list[str],
    high_scorers: list,
    thin_genres: list[str],
    coverage: dict[str, int],
    context_keywords: list[str],
) -> str:
    lines = [
        f"Listener context: {user_context}",
        f"Already delivered genres this session: {', '.join(listener_history) or 'none'}",
        f"Thin genres (< {_THIN_THRESHOLD} jokes): {', '.join(thin_genres) or 'none'}",
        "",
        "Top high-scoring jokes:",
    ]
    for row in high_scorers[:10]:
        lines.append(f"  [{row.score}/10] ({row.category}) {row.joke_text[:80]}")
    lines += [
        "",
        "Genre coverage (jokes per genre):",
    ]
    for genre, n in sorted(coverage.items(), key=lambda x: x[1]):
        lines.append(f"  {genre}: {n}")
    lines += [
        "",
        "Suggest angles that are fresh, relevant, and varied. "
        "Prefer thin genres. Avoid genres already delivered this session.",
    ]
    return "\n".join(lines)


def _estimate_cost(response) -> float | None:  # type: ignore[no-untyped-def]
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    # gpt-4o-mini pricing (approximate): $0.15/1M input, $0.60/1M output
    return (usage.prompt_tokens * 0.15 + usage.completion_tokens * 0.60) / 1_000_000
