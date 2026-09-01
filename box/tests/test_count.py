"""test_count.py

Counts at cabinet, drawer, file, and joke level against a known seeded tree.
"""

import pytest
from box.tests.helpers import joke_payload


@pytest.mark.asyncio
async def test_counts_match_seeded_tree(client):
    """Seed a 2-cabinet × 2-drawer × 2-file × 2-joke tree and verify counts."""
    cabinets = ["CountCab1", "CountCab2"]
    drawers = ["CountDrw1", "CountDrw2"]
    files = ["CountFile1", "CountFile2"]

    positions = iter(range(1, 100))
    jokes_written = 0

    for cab in cabinets:
        for drw in drawers:
            for fil in files:
                for pos in range(2):  # 2 jokes per file
                    p = joke_payload(
                        cabinet=cab, drawer=drw, file=fil,
                        position=next(positions),
                        joke_text=f"Joke in {cab}/{drw}/{fil} #{pos}",
                    )
                    r = await client.put("/box/upsert", json=p)
                    assert r.status_code == 201
                    jokes_written += 1

    # 2 cabs × 2 drawers × 2 files × 2 jokes = 16 jokes
    # 2 cabs, 4 drawers, 8 files
    assert jokes_written == 16

    r = await client.get("/counts")
    assert r.status_code == 200
    data = r.json()

    # Each label is unique within the test (using "Count" prefix)
    # We only care that our added counts are present — other tests may have
    # added rows too (tests run in separate transactions but the session-scoped
    # schema persists). So we use >= not ==.
    assert data["cabinets"] >= 2
    assert data["drawers"] >= 4
    assert data["files"] >= 8
    assert data["jokes"] >= 16


@pytest.mark.asyncio
async def test_cabinet_count_per_cabinet(client):
    """GET /cabinets/{id} reports the correct drawer count."""
    p = joke_payload(cabinet="CntCab", drawer="Drw1", file="Fil1")
    r = await client.put("/box/upsert", json=p)
    assert r.status_code == 201
    cab_id = r.json()["cabinet_id"]

    # Add a second drawer to the same cabinet
    p2 = joke_payload(cabinet="CntCab", drawer="Drw2", file="Fil1")
    await client.put("/box/upsert", json=p2)

    r2 = await client.get(f"/cabinets/{cab_id}")
    assert r2.status_code == 200
    assert len(r2.json()["drawers"]) == 2
