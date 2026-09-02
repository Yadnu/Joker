"""Two-path generation stores intended_quality in provenance without a new field."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from box.schema.models import Trace
from joker.generate import generate
from shared.models import GENERATE_BAD, GENERATE_GOOD, is_reasoning_model


def _response(texts: list[str]):
    response = AsyncMock()
    response.choices = [
        type("Choice", (), {"message": type("Msg", (), {"content": t})()})()
        for t in texts
    ]
    response.usage = type("U", (), {"prompt_tokens": 15, "completion_tokens": 25})()
    return response


@pytest.mark.asyncio
async def test_generate_good_path_uses_frontier_model(db):
    texts = ["short", "medium joke here", "the longest developed punchline of the three"]
    if is_reasoning_model(GENERATE_GOOD):
        create = AsyncMock(side_effect=[_response([t]) for t in texts])
    else:
        create = AsyncMock(return_value=_response(texts))

    with patch("joker.generate._client.chat.completions.create", new=create):
        joke_text, provenance = await generate(
            joke_id="joke_good",
            topic="airport security",
            style="one-liner",
            intended_quality="good",
            user_context="dry tech listener",
            session=db,
        )

    assert provenance.source == "generated"
    assert provenance.model == GENERATE_GOOD
    assert "intended_quality=good" in provenance.selection_rationale
    assert "longest" in joke_text.lower() or joke_text == texts[-1]
    row = (await db.execute(select(Trace).where(Trace.artifact_id == "joke_good"))).scalar_one()
    assert row.inputs["intended_quality"] == "good"
    assert row.model == GENERATE_GOOD


@pytest.mark.asyncio
async def test_generate_bad_path_uses_cheap_model(db):
    texts = ["tiny", "a slightly longer groaner", "the longest still-bad joke"]
    if is_reasoning_model(GENERATE_BAD):
        create = AsyncMock(side_effect=[_response([t]) for t in texts])
    else:
        create = AsyncMock(return_value=_response(texts))

    with patch("joker.generate._client.chat.completions.create", new=create):
        joke_text, provenance = await generate(
            joke_id="joke_bad",
            topic="printers",
            style="one-liner",
            intended_quality="bad",
            user_context="rowdy room",
            session=db,
        )

    assert provenance.model == GENERATE_BAD
    assert "intended_quality=bad" in provenance.selection_rationale
    assert joke_text == "tiny"
    row = (await db.execute(select(Trace).where(Trace.artifact_id == "joke_bad"))).scalar_one()
    assert row.inputs["intended_quality"] == "bad"
    assert row.model == GENERATE_BAD
