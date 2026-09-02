"""Joker — Box functions exposed to the voice model as callable tools.

Implementations go through shared/box_client.py so swapping BOX_BASE_URL is
the only change when the winning Box is announced.

Tool calls are NOT independent model calls and do not emit their own trace
records; they execute within a delivery step that is already traced by
realtime.py.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared import box_client

# ---------------------------------------------------------------------------
# Python implementations
# ---------------------------------------------------------------------------


async def funniest_in_genre(
    genre: str,
    n: int,
    session: AsyncSession,
    state: Any | None = None,
) -> list[dict]:
    """Return top jokes for a genre, minus anything already served tonight.

    The Box orders by score descending. Handing that straight to the host made
    every lookup return the same highest-scored row, which is why a repeated
    request produced a repeated joke.
    """
    rows = await box_client.funniest_in_genre(genre, max(n, 5), session=session)
    if state is None:
        return rows[:n]
    from joker.orchestrator import dedupe_archive_rows

    return dedupe_archive_rows(rows, state, limit=n)


async def write_fresh_bit(
    topic: str,
    form: str,
    session: AsyncSession,
    state: Any | None = None,
) -> dict:
    """Write and file a NEW bit in a requested form. Never a recital."""
    if state is None:
        return {"error": "no_active_set", "joke_text": ""}
    from joker.orchestrator import fresh_bit

    result = await fresh_bit(
        state=state, session=session, topic=topic, form=form
    )
    return {"joke_text": result["joke_text"], "form": result["form"]}


async def get_thin_genres(session: AsyncSession) -> list[str]:
    """Return genres with fewer than 3 jokes (thin coverage)."""
    coverage = await box_client.genre_coverage(session=session)
    return sorted(g for g, n in coverage.items() if n < 3)


async def get_recent_scores(n: int, session: AsyncSession) -> list[int]:
    """Return the last N scores recorded (most recent first)."""
    return await box_client.recent_scores(n, session=session)


async def search_jokes(
    query: str,
    session: AsyncSession,
    state: Any | None = None,
) -> list[dict]:
    """Full-text search over joke_text (case-insensitive LIKE)."""
    rows = await box_client.search_jokes(query, session=session)
    if state is None:
        return rows
    from joker.orchestrator import dedupe_archive_rows

    return dedupe_archive_rows(rows, state)


# ---------------------------------------------------------------------------
# OpenAI Realtime API tool schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "name": "write_fresh_bit",
        "description": (
            "Write a BRAND NEW bit right now, in a requested form. Call this "
            "whenever the listener asks for a joke, or for a specific kind of "
            "joke — a knock-knock, a riddle, a pun, a one-liner, a dad joke. "
            "Never recite a famous joke and never repeat one from the archive: "
            "this tool returns fresh material every time, and it will differ "
            "from everything already said this session. Say the returned line "
            "in your own voice."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "What the bit is about. Use whatever the listener named; "
                        "if they named nothing, pick something specific yourself."
                    ),
                },
                "form": {
                    "type": "string",
                    "description": (
                        "The requested form: knock-knock, riddle, pun, one-liner, "
                        "dad-joke, limerick, story, or bit."
                    ),
                    "default": "bit",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "type": "function",
        "name": "funniest_in_genre",
        "description": (
            "Look up jokes already proven in the archive for a genre, to decide "
            "what territory to try next. Results exclude anything already used "
            "this session. Do NOT use this to answer a request for a joke — "
            "call write_fresh_bit for that."
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
    state: Any | None = None,
) -> object:
    """Route an incoming tool call from the Realtime API to the implementation.

    `state` is the live SessionState when one exists. It carries what has
    already been said tonight, which is what keeps a repeated request from
    producing a repeated joke.
    """
    match name:
        case "write_fresh_bit":
            return await write_fresh_bit(
                topic=arguments.get("topic", ""),
                form=arguments.get("form", "bit"),
                session=session,
                state=state,
            )
        case "funniest_in_genre":
            return await funniest_in_genre(
                genre=arguments["genre"],
                n=arguments.get("n", 3),
                session=session,
                state=state,
            )
        case "get_thin_genres":
            return await get_thin_genres(session=session)
        case "get_recent_scores":
            return await get_recent_scores(
                n=arguments.get("n", 5), session=session
            )
        case "search_jokes":
            return await search_jokes(
                query=arguments["query"], session=session, state=state
            )
        case _:
            raise ValueError(f"Unknown tool: {name!r}")
