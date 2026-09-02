"""test_router_traces.py

GET /traces/{artifact_id} generalizes GET /jokes/{joke_id}/trace to any
artifact_id — jokes, sets, and categories all have trace steps but only
jokes previously had a dedicated read route.
"""

from __future__ import annotations

import pytest

from box.tests.helpers import joke_payload


@pytest.mark.asyncio
async def test_traces_returns_steps_for_a_joke_artifact(client):
    """A joke's generation trace (written during upsert-adjacent flows in
    other tests) is not written by /box/upsert itself, so instead assert
    the endpoint at least responds correctly and returns an empty list for
    a joke id with no separately-recorded trace steps."""
    p = joke_payload(cabinet="TraceCab", drawer="TraceDrw", file="TraceFile")
    r = await client.put("/box/upsert", json=p)
    assert r.status_code == 201, r.text
    joke_id = r.json()["joke_id"]

    r2 = await client.get(f"/traces/{joke_id}")
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["artifact_id"] == joke_id
    assert body["steps"] == []


@pytest.mark.asyncio
async def test_traces_works_for_non_joke_artifact_types(db):
    """kind='set_construction' and kind='classification' traces are written
    directly against set_id / category artifact_ids, not joke_ids — the
    generalized endpoint must read those the same way.

    Calls the route function directly against the `db` fixture's session
    (rather than through the `client` fixture's HTTP round-trip) because the
    trace rows are only flushed, not committed, and the `client` fixture
    reads via a separate DB connection that cannot see uncommitted rows.
    """
    from box.router import get_traces
    from shared.trace import record_step

    await record_step(
        artifact_id="set_test_123",
        artifact_type="set",
        kind="set_construction",
        actor="joker.setbuilder",
        model="o3",
        prompt_ref="prompts/setbuilder_v1.txt",
        inputs={"angles": []},
        output={"set_id": "set_test_123"},
        rationale="Built a 4-slot set for the trace read test.",
        latency_ms=10,
        cost=None,
        session=db,
    )
    await record_step(
        artifact_id="category:TestGenre",
        artifact_type="category",
        kind="classification",
        actor="librarian.classify",
        model="o3",
        prompt_ref="prompts/classify_v1.txt",
        inputs={"joke_text": "x"},
        output={"category": "TestGenre", "is_new": False},
        rationale="Existing label fits.",
        latency_ms=10,
        cost=None,
        session=db,
    )

    set_body = await get_traces(artifact_id="set_test_123", session=db)
    assert set_body.artifact_id == "set_test_123"
    assert len(set_body.steps) == 1
    assert set_body.steps[0].kind == "set_construction"
    assert set_body.steps[0].model == "o3"
    assert set_body.steps[0].prompt_ref == "prompts/setbuilder_v1.txt"
    assert set_body.steps[0].inputs == {"angles": []}
    assert set_body.steps[0].output == {"set_id": "set_test_123"}
    assert set_body.steps[0].cost is None

    cat_body = await get_traces(artifact_id="category:TestGenre", session=db)
    assert cat_body.artifact_id == "category:TestGenre"
    assert len(cat_body.steps) == 1
    assert cat_body.steps[0].kind == "classification"


@pytest.mark.asyncio
async def test_traces_unknown_artifact_returns_empty_not_404(client):
    r = await client.get("/traces/no-such-artifact-id-xyz")
    assert r.status_code == 200
    assert r.json()["steps"] == []


def test_app_mounts_voice_socket_and_traces_route():
    from box.main import app

    def _paths(routes) -> set[str]:
        found: set[str] = set()
        for route in routes:
            path = getattr(route, "path", None)
            if path:
                found.add(path)
            nested = getattr(route, "routes", None)
            if nested:
                found |= _paths(nested)
            original = getattr(route, "original_router", None)
            if original is not None:
                found |= _paths(original.routes)
        return found

    paths = _paths(app.routes)
    assert "/ws/session/{session_id}" in paths
    assert "/traces/{artifact_id}" in paths
    assert "/jokes/top" in paths
