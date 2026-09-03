"""Turn context is copied onto every record_step without changing the signature."""

from __future__ import annotations

import inspect

import pytest
from sqlalchemy import select

from box.schema.models import Trace
from shared.trace import bind_turn, clear_turn, record_step


@pytest.fixture(autouse=True)
def _clear_turn_context():
    clear_turn()
    yield
    clear_turn()


def test_record_step_signature_unchanged():
    params = list(inspect.signature(record_step).parameters)
    assert params == [
        "artifact_id",
        "artifact_type",
        "kind",
        "actor",
        "model",
        "prompt_ref",
        "inputs",
        "output",
        "rationale",
        "latency_ms",
        "cost",
        "session",
    ]


@pytest.mark.asyncio
async def test_bound_turn_is_copied_onto_every_step(db):
    bind_turn(
        turn_id="show-1:t3",
        turn_index=3,
        trigger_type="user_request",
        trigger_text="tell me one about airports",
    )
    await record_step(
        artifact_id="joke_turn_a",
        artifact_type="joke",
        kind="suggestion",
        actor="librarian.suggest",
        model="gpt-test",
        prompt_ref="t",
        inputs={},
        output={},
        rationale="Airport security angle ranked first among observational bits.",
        latency_ms=142,
        cost=None,
        session=db,
    )
    await record_step(
        artifact_id="joke_turn_a",
        artifact_type="joke",
        kind="generation",
        actor="joker.generate",
        model="gpt-test",
        prompt_ref="t",
        inputs={"topic": "airports", "set_position": 1},
        output={"joke_text": "setup / punch"},
        rationale="Generated the requested airport bit.",
        latency_ms=890,
        cost=None,
        session=db,
    )
    rows = (
        await db.execute(select(Trace).where(Trace.artifact_id == "joke_turn_a"))
    ).scalars().all()
    assert len(rows) == 2
    for row in rows:
        assert row.trigger_type == "user_request"
        assert row.trigger_text == "tell me one about airports"
        assert row.turn_id == "show-1:t3"
        assert row.turn_index == 3


@pytest.mark.asyncio
async def test_cold_open_forces_null_trigger_text(db):
    bind_turn(
        turn_id="show-1:t1",
        turn_index=1,
        trigger_type="cold_open",
        trigger_text="should be dropped",
    )
    await record_step(
        artifact_id="joke_cold",
        artifact_type="joke",
        kind="generation",
        actor="joker.generate",
        model=None,
        prompt_ref=None,
        inputs={},
        output={},
        rationale="Host opened unprompted; first bit of the planned set.",
        latency_ms=10,
        cost=None,
        session=db,
    )
    row = (
        await db.execute(select(Trace).where(Trace.artifact_id == "joke_cold"))
    ).scalar_one()
    assert row.trigger_type == "cold_open"
    assert row.trigger_text is None


@pytest.mark.asyncio
async def test_trace_dict_includes_trigger_fields(db):
    from box.router import _trace_step_dict

    bind_turn(
        turn_id="show-1:t2",
        turn_index=2,
        trigger_type="set_continuation",
        trigger_text="ignored",
    )
    await record_step(
        artifact_id="joke_cont",
        artifact_type="joke",
        kind="generation",
        actor="joker.generate",
        model="gpt-test",
        prompt_ref="t",
        inputs={"topic": "airport security", "set_position": 3},
        output={"joke_text": "line"},
        rationale="Next bit in the already-planned set.",
        latency_ms=50,
        cost=None,
        session=db,
    )
    row = (
        await db.execute(select(Trace).where(Trace.artifact_id == "joke_cont"))
    ).scalar_one()
    body = _trace_step_dict(row)
    assert body["trigger_type"] == "set_continuation"
    assert body["trigger_text"] is None
    assert body["turn_id"] == "show-1:t2"
    assert body["turn_index"] == 2


@pytest.mark.asyncio
async def test_null_trigger_rows_still_serialize(client):
    from box.tests.helpers import joke_payload

    p = joke_payload(cabinet="NullCab", drawer="NullDrwA", file="NullFile")
    r = await client.put("/box/upsert", json=p)
    assert r.status_code == 201, r.text
    joke_id = r.json()["joke_id"]
    r2 = await client.get(f"/jokes/{joke_id}/trace")
    assert r2.status_code == 200
    for step in r2.json()["steps"]:
        assert "trigger_type" in step
        assert step["trigger_type"] is None or isinstance(step["trigger_type"], str)
