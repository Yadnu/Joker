"""test_funniest_in_genre.py

GET /genres/{genre}/funniest returns the highest-scoring jokes for a genre.

Tests:
  - a genre with several jokes returns only the highest scorer (n=1)
  - a tie between equal scores returns both (n=2)
  - a genre with no jokes returns an empty list (must not 500)
"""

from __future__ import annotations

import pytest

from box.tests.helpers import joke_payload


@pytest.mark.asyncio
async def test_funniest_returns_highest_scorer(client):
    genre = "FunniestHTTPGenre"
    for score, pos in [(3, 1), (9, 2), (6, 3)]:
        p = joke_payload(
            cabinet="FunniestHTTPCab",
            drawer="FunniestHTTPDrw",
            file="FunniestHTTPFile",
            category=genre,
            score=score,
            position=pos,
            joke_text=f"Joke score={score}",
        )
        r = await client.put("/box/upsert", json=p)
        assert r.status_code == 201, r.text

    r = await client.get(f"/genres/{genre}/funniest?n=1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["genre"] == genre
    assert len(body["jokes"]) == 1
    assert body["jokes"][0]["score"] == 9


@pytest.mark.asyncio
async def test_funniest_tie_returns_both(client):
    genre = "TieHTTPGenre"
    for pos in [1, 2]:
        p = joke_payload(
            cabinet="TieHTTPCab",
            drawer="TieHTTPDrw",
            file="TieHTTPFile",
            category=genre,
            score=8,
            position=pos,
            joke_text=f"Tied joke #{pos}",
        )
        r = await client.put("/box/upsert", json=p)
        assert r.status_code == 201

    r = await client.get(f"/genres/{genre}/funniest?n=2")
    assert r.status_code == 200
    body = r.json()
    assert len(body["jokes"]) == 2
    assert all(j["score"] == 8 for j in body["jokes"])


@pytest.mark.asyncio
async def test_funniest_empty_genre_does_not_500(client):
    r = await client.get("/genres/NonExistentGenreHTTPXYZ/funniest")
    assert r.status_code == 200
    assert r.json()["jokes"] == []


@pytest.mark.asyncio
async def test_jokes_top_and_genre_coverage(client):
    p = joke_payload(
        cabinet="TopCab",
        drawer="TopDrw",
        file="TopFile",
        category="TopGenre",
        score=9,
        position=1,
        joke_text="A high scorer for the archive read.",
    )
    p2 = joke_payload(
        cabinet="TopCab",
        drawer="TopDrw",
        file="TopFile",
        category="TopGenre",
        score=8,
        position=2,
        joke_text="Second high scorer.",
    )
    assert (await client.put("/box/upsert", json=p)).status_code == 201
    assert (await client.put("/box/upsert", json=p2)).status_code == 201

    top = await client.get("/jokes/top?n=5&min_score=7")
    assert top.status_code == 200, top.text
    texts = [j["joke_text"] for j in top.json()["jokes"]]
    assert "A high scorer for the archive read." in texts

    cov = await client.get("/genres/coverage")
    assert cov.status_code == 200, cov.text
    assert cov.json()["coverage"]["TopGenre"] >= 2
