"""test_concurrency.py

Two threads simultaneously POST jokes that invent the same cabinet, drawer,
and file labels.  Assert:
  - exactly one of each level exists afterward
  - both jokes are stored
  - neither request errored

Uses real threads against the real database.  The race is not serialised or
mocked.
"""

from __future__ import annotations

import asyncio
import threading

import pytest


def _run_upsert(url: str, payload: dict, results: list, idx: int) -> None:
    """Run one upsert from a real OS thread with its own event loop."""
    import httpx

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        async def _do() -> dict:
            async with httpx.AsyncClient(base_url=url, timeout=30) as ac:
                r = await ac.put("/box/upsert", json=payload)
                return {"status": r.status_code, "body": r.json()}

        results[idx] = loop.run_until_complete(_do())
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_concurrent_upsert_same_path(test_session_factory):
    """Two threads hit /box/upsert with identical cabinet/drawer/file at the same time."""
    import uvicorn
    import threading
    from box.main import app
    from shared import db as db_module

    db_module.SessionFactory = test_session_factory

    # Start a real uvicorn server on a random port so the threads can use
    # plain httpx (not ASGI transport, which is not thread-safe).
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # Wait for the server to be ready
    deadline = asyncio.get_event_loop().time() + 10
    while not server.started:
        await asyncio.sleep(0.05)
        if asyncio.get_event_loop().time() > deadline:
            pytest.fail("uvicorn did not start in time")

    port = server.servers[0].sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    from box.tests.helpers import joke_payload

    shared_path = {
        "cabinet": "RaceCab",
        "drawer": "RaceDrw",
        "file": "RaceFile",
    }

    p1 = joke_payload(**shared_path, position=1, joke_text="Thread 1 joke.")
    p2 = joke_payload(**shared_path, position=2, joke_text="Thread 2 joke.")

    results = [None, None]

    t1 = threading.Thread(target=_run_upsert, args=(base_url, p1, results, 0))
    t2 = threading.Thread(target=_run_upsert, args=(base_url, p2, results, 1))

    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    server.should_exit = True
    server_thread.join(timeout=5)

    # Neither request errored
    assert results[0] is not None, "Thread 0 never completed"
    assert results[1] is not None, "Thread 1 never completed"
    assert results[0]["status"] == 201, f"Thread 0 failed: {results[0]}"
    assert results[1]["status"] == 201, f"Thread 1 failed: {results[1]}"

    # Both jokes stored, different ids
    id0 = results[0]["body"]["joke_id"]
    id1 = results[1]["body"]["joke_id"]
    assert id0 != id1

    # Exactly one cabinet, drawer, and file (not duplicated)
    assert results[0]["body"]["cabinet_id"] == results[1]["body"]["cabinet_id"], \
        "Duplicate cabinet created by concurrent writes"
    assert results[0]["body"]["drawer_id"] == results[1]["body"]["drawer_id"], \
        "Duplicate drawer created by concurrent writes"
    assert results[0]["body"]["file_id"] == results[1]["body"]["file_id"], \
        "Duplicate file created by concurrent writes"
