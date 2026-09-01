"""test_read.py

Retrieve by id and by full path (GET /box/{cabinet}/{drawer}/{file}).
Assert a missing path returns 404 with a body naming which level was not found.
Also covers GET /export returning the full tree with all jokes.
"""

import pytest
from box.tests.helpers import joke_payload


@pytest.mark.asyncio
async def test_read_joke_by_id(client):
    p = joke_payload(cabinet="ReadTest", drawer="ById", file="JokeId")
    r = await client.put("/box/upsert", json=p)
    assert r.status_code == 201
    joke_id = r.json()["joke_id"]

    r2 = await client.get(f"/jokes/{joke_id}")
    assert r2.status_code == 200
    assert r2.json()["id"] == joke_id
    assert r2.json()["joke_text"] == p["joke"]["joke_text"]


@pytest.mark.asyncio
async def test_read_file_by_id(client):
    p = joke_payload(cabinet="ReadTest2", drawer="ByFileId", file="Files")
    r = await client.put("/box/upsert", json=p)
    file_id = r.json()["file_id"]

    r2 = await client.get(f"/files/{file_id}")
    assert r2.status_code == 200
    assert r2.json()["id"] == file_id
    assert r2.json()["label"] == "Files"


@pytest.mark.asyncio
async def test_read_drawer_by_id(client):
    p = joke_payload(cabinet="ReadTest3", drawer="ByDrawerId", file="Nested")
    r = await client.put("/box/upsert", json=p)
    drawer_id = r.json()["drawer_id"]

    r2 = await client.get(f"/drawers/{drawer_id}")
    assert r2.status_code == 200
    assert r2.json()["id"] == drawer_id
    assert r2.json()["label"] == "ByDrawerId"


@pytest.mark.asyncio
async def test_read_cabinet_by_id(client):
    p = joke_payload(cabinet="ReadTest4", drawer="ByCabId", file="Nested")
    r = await client.put("/box/upsert", json=p)
    cabinet_id = r.json()["cabinet_id"]

    r2 = await client.get(f"/cabinets/{cabinet_id}")
    assert r2.status_code == 200
    assert r2.json()["id"] == cabinet_id
    assert r2.json()["label"] == "ReadTest4"


@pytest.mark.asyncio
async def test_missing_joke_returns_404_naming_level(client):
    r = await client.get("/jokes/nonexistent-id-xyz")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["level"] == "joke"
    assert "joke" in detail["reason"].lower()


@pytest.mark.asyncio
async def test_missing_cabinet_returns_404_naming_level(client):
    r = await client.get("/cabinets/nonexistent-id-xyz")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["level"] == "cabinet"


@pytest.mark.asyncio
async def test_missing_drawer_returns_404_naming_level(client):
    r = await client.get("/drawers/nonexistent-id-xyz")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["level"] == "drawer"


@pytest.mark.asyncio
async def test_missing_file_returns_404_naming_level(client):
    r = await client.get("/files/nonexistent-id-xyz")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["level"] == "file"


@pytest.mark.asyncio
async def test_read_by_path_returns_jokes(client):
    """GET /box/{cabinet}/{drawer}/{file} returns jokes at that path."""
    p = joke_payload(
        cabinet="PathCab", drawer="PathDrw", file="PathFile",
        joke_text="Path read joke.",
    )
    r = await client.put("/box/upsert", json=p)
    assert r.status_code == 201
    joke_id = r.json()["joke_id"]

    r2 = await client.get("/box/PathCab/PathDrw/PathFile")
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["cabinet"]["label"] == "PathCab"
    assert body["drawer"]["label"] == "PathDrw"
    assert body["file"]["label"] == "PathFile"
    joke_ids = [j["id"] for j in body["jokes"]]
    assert joke_id in joke_ids


@pytest.mark.asyncio
async def test_read_by_path_missing_cabinet_returns_404(client):
    r = await client.get("/box/NoSuchCab/NoSuchDrw/NoSuchFile")
    assert r.status_code == 404
    assert r.json()["detail"]["level"] == "cabinet"


@pytest.mark.asyncio
async def test_read_by_path_missing_drawer_returns_404(client):
    p = joke_payload(cabinet="PathCab2", drawer="PathDrw2", file="PathFile2")
    await client.put("/box/upsert", json=p)

    r = await client.get("/box/PathCab2/NoSuchDrw/NoSuchFile")
    assert r.status_code == 404
    assert r.json()["detail"]["level"] == "drawer"


@pytest.mark.asyncio
async def test_export_contains_all_jokes(client):
    """GET /export returns the full tree with every joke embedded."""
    p = joke_payload(
        cabinet="ExportCab", drawer="ExportDrw", file="ExportFile",
        joke_text="Export test joke.",
    )
    r = await client.put("/box/upsert", json=p)
    assert r.status_code == 201
    joke_id = r.json()["joke_id"]

    r2 = await client.get("/export")
    assert r2.status_code == 200
    all_joke_ids = [
        j["id"]
        for cab in r2.json()["cabinets"]
        for drw in cab["drawers"]
        for fil in drw["files"]
        for j in fil["jokes"]
    ]
    assert joke_id in all_joke_ids


@pytest.mark.asyncio
async def test_scoped_counts_cabinet(client):
    """GET /cabinets/{id}/counts returns drawer/file/joke tallies."""
    p = joke_payload(cabinet="CntCab", drawer="CntDrw", file="CntFile")
    r = await client.put("/box/upsert", json=p)
    assert r.status_code == 201
    cabinet_id = r.json()["cabinet_id"]

    r2 = await client.get(f"/cabinets/{cabinet_id}/counts")
    assert r2.status_code == 200
    body = r2.json()
    assert body["drawers"] >= 1
    assert body["files"] >= 1
    assert body["jokes"] >= 1


@pytest.mark.asyncio
async def test_scoped_counts_file(client):
    """GET /files/{id}/counts returns joke count."""
    p = joke_payload(cabinet="CntCab2", drawer="CntDrw2", file="CntFile2")
    r = await client.put("/box/upsert", json=p)
    assert r.status_code == 201
    file_id = r.json()["file_id"]

    r2 = await client.get(f"/files/{file_id}/counts")
    assert r2.status_code == 200
    assert r2.json()["jokes"] >= 1
