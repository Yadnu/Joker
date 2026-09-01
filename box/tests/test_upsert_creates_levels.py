"""test_upsert_creates_levels.py

One write into a path where nothing exists creates cabinet, drawer, file,
and joke.  A second write into the same path adds a joke without duplicating
any level.  A write where only the cabinet exists creates the remaining two
levels.
"""

import pytest
from box.tests.helpers import joke_payload


@pytest.mark.asyncio
async def test_first_write_creates_all_levels(client):
    """Writing into a fresh path creates all four levels."""
    p = joke_payload(cabinet="ScienceC", drawer="Physics", file="Quantum")
    r = await client.put("/box/upsert", json=p)
    assert r.status_code == 201, r.text
    ids = r.json()
    assert ids["cabinet_id"]
    assert ids["drawer_id"]
    assert ids["file_id"]
    assert ids["joke_id"]


@pytest.mark.asyncio
async def test_second_write_same_path_no_duplicate_levels(client):
    """Two writes to the same path: one cabinet, one drawer, one file, two jokes."""
    p1 = joke_payload(cabinet="ScienceD", drawer="Chemistry", file="Molecules", position=1)
    p2 = joke_payload(cabinet="ScienceD", drawer="Chemistry", file="Molecules", position=2,
                      joke_text="A neutron walks into a bar...", user_reaction="Nice.")

    r1 = await client.put("/box/upsert", json=p1)
    r2 = await client.put("/box/upsert", json=p2)
    assert r1.status_code == 201
    assert r2.status_code == 201

    # Same cabinet, drawer, file ids
    assert r1.json()["cabinet_id"] == r2.json()["cabinet_id"]
    assert r1.json()["drawer_id"] == r2.json()["drawer_id"]
    assert r1.json()["file_id"] == r2.json()["file_id"]
    # Different joke ids
    assert r1.json()["joke_id"] != r2.json()["joke_id"]

    # Verify via /counts that we have exactly the expected structure
    cabs_r = await client.get("/cabinets")
    cabs = [c for c in cabs_r.json()["cabinets"] if c["label"] == "ScienceD"]
    assert len(cabs) == 1, "Duplicate cabinet created"

    file_r = await client.get(f"/files/{r1.json()['file_id']}")
    assert len(file_r.json()["jokes"]) == 2


@pytest.mark.asyncio
async def test_write_where_cabinet_exists_creates_lower_levels(client):
    """If the cabinet already exists, drawer and file are created fresh."""
    # First write creates the cabinet
    p1 = joke_payload(cabinet="ScienceE", drawer="Biology", file="Cells", position=1)
    r1 = await client.put("/box/upsert", json=p1)
    assert r1.status_code == 201
    existing_cab_id = r1.json()["cabinet_id"]

    # Second write to same cabinet but new drawer/file
    p2 = joke_payload(cabinet="ScienceE", drawer="Genetics", file="DNA", position=1,
                      joke_text="DNA walks into a bar. DNA: I can't find the other half of me.")
    r2 = await client.put("/box/upsert", json=p2)
    assert r2.status_code == 201
    assert r2.json()["cabinet_id"] == existing_cab_id, "Cabinet was duplicated"
    assert r2.json()["drawer_id"] != r1.json()["drawer_id"], "Expected new drawer"
    assert r2.json()["file_id"] != r1.json()["file_id"], "Expected new file"
