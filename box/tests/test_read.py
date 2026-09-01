"""test_read.py

Retrieve by id and by full path.
Assert a missing path returns 404 with a body naming which level was not found.
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
