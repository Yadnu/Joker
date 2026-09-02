"""Voice-model tools include funniest-in-genre against the archive."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from box.schema.models import Joke
from joker.tools import dispatch_tool, funniest_in_genre
from box.tests.archive_seed import seed_two_genres


@pytest.mark.asyncio
async def test_funniest_in_genre_returns_top_scores(db):
    await seed_two_genres(db)
    rows = await funniest_in_genre("AirportSecurity", n=2, session=db)
    assert [r["score"] for r in rows] == [9, 8]
    assert all(r["category"] == "AirportSecurity" for r in rows)


@pytest.mark.asyncio
async def test_dispatch_funniest_in_genre(db):
    await seed_two_genres(db)
    result = await dispatch_tool(
        "funniest_in_genre",
        {"genre": "AirportSecurity", "n": 1},
        db,
    )
    assert result[0]["score"] == 9
    archive = (await db.execute(select(Joke).where(Joke.category == "AirportSecurity"))).scalars().all()
    assert len(archive) >= 2
