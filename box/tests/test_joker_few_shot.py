"""Few-shot shape rotation and generation traces that cite room critiques."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from box.schema.models import Trace
from joker.generate import FEW_SHOT_SHAPES, generate, next_few_shot_shape
from shared.models import GENERATE_GOOD, is_reasoning_model
from box.tests.test_joker_generate import _response


def test_next_few_shot_shape_never_repeats_adjacent():
    last = None
    seen = []
    for _ in range(20):
        shape = next_few_shot_shape(last_few_shot_shape=last)
        assert shape in FEW_SHOT_SHAPES
        assert shape != last or len(FEW_SHOT_SHAPES) == 1
        seen.append(shape)
        last = shape
    assert len(set(seen)) > 1


@pytest.mark.asyncio
async def test_generation_trace_cites_prior_critiques(db):
    texts = ["short", "medium joke here", "the longest developed punchline of the three"]
    if is_reasoning_model(GENERATE_GOOD):
        create = AsyncMock(side_effect=[_response([t]) for t in texts])
    else:
        create = AsyncMock(return_value=_response(texts))

    critiques = [
        {"score": 3, "shape": "literalism", "critique": "Subject was abstract: people."},
    ]
    with patch("joker.generate._client.chat.completions.create", new=create):
        await generate(
            joke_id="joke_room_fb",
            topic="pharmacies",
            intended_quality="good",
            user_context="dry tech listener",
            session=db,
            few_shot_shape="reversal",
            last_few_shot_shape="compression",
            recent_critiques=critiques,
        )

    row = (
        await db.execute(select(Trace).where(Trace.artifact_id == "joke_room_fb"))
    ).scalar_one()
    assert row.kind == "generation"
    assert row.inputs["few_shot_shape"] == "reversal"
    assert row.inputs["recent_critiques"] == critiques
    assert "abstract" in row.rationale.lower() or "critique" in row.rationale.lower()
    if not is_reasoning_model(GENERATE_GOOD):
        prompt = create.await_args.kwargs["messages"][-1]["content"]
        assert "Your last five bits:" in prompt
        assert "literalism" in prompt
