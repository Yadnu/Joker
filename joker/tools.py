"""Joker — Box functions exposed to the voice model as callable tools.

Each function has:
  - A Python implementation that queries the Box DB directly.
  - An OpenAI-compatible JSON schema (for the Realtime API session.tools payload).

Tool calls are NOT independent model calls and do not emit their own trace
records; they execute within a delivery step that is already traced by
realtime.py.
"""

from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.models import Joke

# ---------------------------------------------------------------------------
# Python implementations
# ---------------------------------------------------------------------------


async def funniest_in_genre(
    genre: str,
    n: int,
    session: AsyncSession,
) -> list[dict]:
    """Return the top-N jokes by score for a given genre."""
    stmt = (
        select(Joke.id, Joke.joke_text, Joke.score, Joke.category)
        .where(Joke.category == genre)
        .order_by(desc(Joke.score))
        .limit(max(1, n))
    )
    rows = (await session.execute(stmt)).all()
    return [
        {"id": r.id, "joke_text": r.joke_text, "score": r.score, "category": r.category}
        for r in rows
    ]


async def get_thin_genres(session: AsyncSession) -> list[str]:
    """Return genres with fewer than 3 jokes (thin coverage)."""
    stmt = (
        select(Joke.category, func.count(Joke.id).label("n"))
        .group_by(Joke.category)
        .having(func.count(Joke.id) < 3)
        .order_by(Joke.category)
    )
    rows = (await session.execute(stmt)).all()
    return [r.category for r in rows]


async def get_recent_scores(n: int, session: AsyncSession) -> list[int]:
    """Return the last N scores recorded (most recent first)."""
    stmt = (
        select(Joke.score)
        .order_by(desc(Joke.created_at))
        .limit(max(1, n))
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def search_jokes(query: str, session: AsyncSession) -> list[dict]:
    """Full-text search over joke_text (case-insensitive LIKE)."""
    stmt = (
        select(Joke.id, Joke.joke_text, Joke.score, Joke.category)
        .where(Joke.joke_text.ilike(f"%{query}%"))
        .order_by(desc(Joke.score))
        .limit(10)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {"id": r.id, "joke_text": r.joke_text, "score": r.score, "category": r.category}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# OpenAI Realtime API tool schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "name": "funniest_in_genre",
        "description": (
            "Return the top jokes by score for a given genre. "
            "Use this to find proven material before deciding what to try next."
        ),
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
                    "default": 3,
                },
            },
            "required": ["genre"],
        },
    },
    {
        "type": "function",
        "name": "get_thin_genres",
        "description": (
            "Return genres with fewer than 3 jokes in the archive. "
            "Use to find under-explored territory."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "get_recent_scores",
        "description": (
            "Return the most recent N joke scores. "
            "Use to gauge how the current audience is responding."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "description": "Number of recent scores to return.",
                    "default": 5,
                }
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "search_jokes",
        "description": (
            "Search the joke archive by keyword. "
            "Use to find previously filed jokes on a specific topic."
        ),
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


async def dispatch_tool(
    name: str,
    arguments: dict,
    session: AsyncSession,
) -> object:
    """Route an incoming tool call from the Realtime API to the implementation."""
    match name:
        case "funniest_in_genre":
            return await funniest_in_genre(
                genre=arguments["genre"],
                n=arguments.get("n", 3),
                session=session,
            )
        case "get_thin_genres":
            return await get_thin_genres(session=session)
        case "get_recent_scores":
            return await get_recent_scores(
                n=arguments.get("n", 5), session=session
            )
        case "search_jokes":
            return await search_jokes(query=arguments["query"], session=session)
        case _:
            raise ValueError(f"Unknown tool: {name!r}")
