"""test_funniest_in_genre.py

Returns the highest-scoring joke in a genre.
Covers:
  - a genre with several jokes (returns the highest scorer)
  - a tie between two equal scores (both may be returned; order is score desc)
  - a genre with no jokes (must not 500; returns empty list)
"""

import pytest
from box.tests.helpers import joke_payload

# We test this through the joker/tools layer using DB directly
# since there is no dedicated HTTP endpoint for funniest_in_genre.
# Tests import the tool function and run it with a live session.


@pytest.mark.asyncio
async def test_funniest_returns_highest_scorer(test_session_factory):
    from joker.tools import funniest_in_genre
    from box.tests.helpers import joke_payload
    from httpx import ASGITransport, AsyncClient
    from box.main import app
    from shared import db as db_module

    db_module.SessionFactory = test_session_factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Write three jokes in the same genre with different scores
        genre = "FunniestTestGenre"
        for score, pos in [(3, 1), (9, 2), (6, 3)]:
            p = joke_payload(
                cabinet="FunniestCab", drawer="FunniestDrw", file="FunniestFile",
                category=genre, score=score, position=pos,
                joke_text=f"Joke score={score}",
            )
            r = await ac.put("/box/upsert", json=p)
            assert r.status_code == 201, r.text

    async with test_session_factory() as session:
        results = await funniest_in_genre(genre=genre, n=1, session=session)

    assert len(results) == 1
    assert results[0]["score"] == 9


@pytest.mark.asyncio
async def test_funniest_tie_returns_both(test_session_factory):
    from joker.tools import funniest_in_genre
    from httpx import ASGITransport, AsyncClient
    from box.main import app
    from shared import db as db_module

    db_module.SessionFactory = test_session_factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        genre = "TieGenre"
        for pos in [1, 2]:
            p = joke_payload(
                cabinet="TieCab", drawer="TieDrw", file="TieFile",
                category=genre, score=8, position=pos,
                joke_text=f"Tied joke #{pos}",
            )
            r = await ac.put("/box/upsert", json=p)
            assert r.status_code == 201

    async with test_session_factory() as session:
        results = await funniest_in_genre(genre=genre, n=2, session=session)

    assert len(results) == 2
    assert all(r["score"] == 8 for r in results)


@pytest.mark.asyncio
async def test_funniest_empty_genre_does_not_500(test_session_factory):
    from joker.tools import funniest_in_genre

    async with test_session_factory() as session:
        results = await funniest_in_genre(genre="NonExistentGenreXYZ", n=5, session=session)

    assert results == []
    # Must not raise — returning an empty list is correct
