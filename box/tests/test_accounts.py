"""test_accounts.py

Accounts identify who wrote what.  Visibility is always global — no query
filters by account.

Tests:
  - create account returns 201 with id and name
  - duplicate name returns 409
  - list accounts returns all created entries
  - get account by id returns correct record
  - jokes filed with an account_id are readable by anyone (global reads)
  - account_id is stored on the joke and returned in GET /jokes/{id}
  - multiple accounts can write concurrently; all jokes are visible globally
"""

from __future__ import annotations

import pytest

from box.tests.helpers import joke_payload


@pytest.mark.asyncio
async def test_create_account_returns_id_and_name(client):
    r = await client.post("/accounts", json={"name": "Acct-Create-1"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert "id" in body
    assert body["name"] == "Acct-Create-1"
    assert "created_at" in body


@pytest.mark.asyncio
async def test_duplicate_account_name_returns_409(client):
    name = "Acct-Dup-1"
    r1 = await client.post("/accounts", json={"name": name})
    assert r1.status_code == 201
    r2 = await client.post("/accounts", json={"name": name})
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_list_accounts_returns_created_entries(client):
    r_a = await client.post("/accounts", json={"name": "Acct-List-A"})
    r_b = await client.post("/accounts", json={"name": "Acct-List-B"})
    assert r_a.status_code == 201
    assert r_b.status_code == 201

    r = await client.get("/accounts")
    assert r.status_code == 200
    names = [a["name"] for a in r.json()["accounts"]]
    assert "Acct-List-A" in names
    assert "Acct-List-B" in names


@pytest.mark.asyncio
async def test_get_account_by_id(client):
    r = await client.post("/accounts", json={"name": "Acct-GetById"})
    assert r.status_code == 201
    acct_id = r.json()["id"]

    r2 = await client.get(f"/accounts/{acct_id}")
    assert r2.status_code == 200
    assert r2.json()["id"] == acct_id
    assert r2.json()["name"] == "Acct-GetById"


@pytest.mark.asyncio
async def test_missing_account_returns_404(client):
    r = await client.get("/accounts/nonexistent-account-id-xyz")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_account_id_stored_on_joke_and_returned(client):
    """account_id is persisted on the joke and echoed in GET /jokes/{id}."""
    r_acct = await client.post("/accounts", json={"name": "Acct-JokeOwner"})
    assert r_acct.status_code == 201
    acct_id = r_acct.json()["id"]

    p = joke_payload(cabinet="AcctTest", drawer="AcctDrw", file="AcctFile", position=1)
    p["account_id"] = acct_id

    r_upsert = await client.put("/box/upsert", json=p)
    assert r_upsert.status_code == 201
    joke_id = r_upsert.json()["joke_id"]

    r_joke = await client.get(f"/jokes/{joke_id}")
    assert r_joke.status_code == 200
    assert r_joke.json()["account_id"] == acct_id


@pytest.mark.asyncio
async def test_jokes_from_different_accounts_visible_globally(client):
    """Accounts scope attribution only — every account can read the full library."""
    r1 = await client.post("/accounts", json={"name": "Acct-Vis-1"})
    r2 = await client.post("/accounts", json={"name": "Acct-Vis-2"})
    id1 = r1.json()["id"]
    id2 = r2.json()["id"]

    p1 = joke_payload(
        cabinet="GlobalVis", drawer="VisDrw", file="VisFile1",
        position=1, joke_text="Account 1 joke.",
    )
    p2 = joke_payload(
        cabinet="GlobalVis", drawer="VisDrw", file="VisFile2",
        position=2, joke_text="Account 2 joke.",
    )
    p1["account_id"] = id1
    p2["account_id"] = id2

    ur1 = await client.put("/box/upsert", json=p1)
    ur2 = await client.put("/box/upsert", json=p2)
    assert ur1.status_code == 201
    assert ur2.status_code == 201

    joke_id1 = ur1.json()["joke_id"]
    joke_id2 = ur2.json()["joke_id"]

    # Both jokes are readable with no account filter required
    rg1 = await client.get(f"/jokes/{joke_id1}")
    rg2 = await client.get(f"/jokes/{joke_id2}")
    assert rg1.status_code == 200
    assert rg2.status_code == 200

    # Each joke carries the correct account_id for attribution
    assert rg1.json()["account_id"] == id1
    assert rg2.json()["account_id"] == id2

    # The full tree lists both jokes without any account filter
    tree = await client.get("/box")
    assert tree.status_code == 200
    all_joke_ids = [
        j["id"]
        for cab in tree.json()["cabinets"]
        for drw in cab["drawers"]
        for fil in drw["files"]
        for j in fil.get("jokes", [])
    ]
    # GET /box returns joke counts, not full joke objects, so check via export
    export = await client.get("/export")
    assert export.status_code == 200
    export_joke_ids = [
        j["id"]
        for cab in export.json()["cabinets"]
        for drw in cab["drawers"]
        for fil in drw["files"]
        for j in fil["jokes"]
    ]
    assert joke_id1 in export_joke_ids
    assert joke_id2 in export_joke_ids
