"""Trace seam: rationale is required; invalid kinds are rejected; rows persist."""

from __future__ import annotations

import inspect

import pytest
from sqlalchemy import select

from box.schema.models import Trace
from shared.trace import record_step


def test_rationale_has_no_default():
    param = inspect.signature(record_step).parameters["rationale"]
    assert param.default is inspect.Parameter.empty
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.asyncio
async def test_empty_rationale_raises_value_error(db):
    with pytest.raises(ValueError, match="rationale"):
        await record_step(
            artifact_id="joke_1",
            artifact_type="joke",
            kind="generation",
            actor="joker.generate",
            model="gpt-4o-mini",
            prompt_ref="t",
            inputs={},
            output={},
            rationale="   ",
            latency_ms=1,
            cost=None,
            session=db,
        )


@pytest.mark.asyncio
async def test_omitting_rationale_is_type_error(db):
    with pytest.raises(TypeError):
        await record_step(  # type: ignore[call-arg]
            artifact_id="joke_1",
            artifact_type="joke",
            kind="generation",
            actor="joker.generate",
            model=None,
            prompt_ref=None,
            inputs={},
            output={},
            latency_ms=1,
            cost=None,
            session=db,
        )


@pytest.mark.asyncio
async def test_invalid_kind_raises_value_error(db):
    with pytest.raises(ValueError, match="Invalid trace kind"):
        await record_step(
            artifact_id="joke_1",
            artifact_type="joke",
            kind="not_a_kind",
            actor="joker.generate",
            model=None,
            prompt_ref=None,
            inputs={},
            output={},
            rationale="explaining anyway",
            latency_ms=1,
            cost=None,
            session=db,
        )


@pytest.mark.asyncio
async def test_record_step_writes_traces_table(db):
    await record_step(
        artifact_id="joke_a1",
        artifact_type="joke",
        kind="generation",
        actor="joker.generate",
        model="o3",
        prompt_ref="joker/generate_good_v1",
        inputs={"topic": "airports"},
        output={"joke_text": "setup / punch"},
        rationale="Selected the sharpest of three candidates for live delivery.",
        latency_ms=120,
        cost=0.001,
        session=db,
    )
    rows = (await db.execute(select(Trace).where(Trace.artifact_id == "joke_a1"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].rationale.startswith("Selected the sharpest")
    assert rows[0].kind == "generation"
    assert rows[0].actor == "joker.generate"
