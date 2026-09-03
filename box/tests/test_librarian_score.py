"""Score stores rubric version on every scoring trace."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from box.schema.models import Trace
from librarian.score import RUBRIC, RUBRIC_VERSION, score


def _completion(payload: dict):
    response = AsyncMock()
    response.choices = [
        type("Choice", (), {"message": type("Msg", (), {"content": json.dumps(payload)})()})()
    ]
    response.usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 10})()
    return response


def test_rubric_has_written_anchors():
    assert RUBRIC_VERSION == "1.1"
    for anchor in (0, 3, 5, 7, 9):
        assert anchor in RUBRIC
        assert len(RUBRIC[anchor]) > 20


@pytest.mark.asyncio
async def test_score_trace_includes_rubric_version(db):
    with patch(
        "librarian.score._client.chat.completions.create",
        new=AsyncMock(
            return_value=_completion(
                {"score": 8, "rationale": "Two genuine laughs; between 6 and 10 anchors."}
            )
        ),
    ):
        result = await score(
            joke_id="joke_score_1",
            joke_text="TSA packed bags.",
            user_reaction="Ha! That's exactly what happened.",
            user_context="dry tech listener",
            session=db,
        )

    assert result == 8
    row = (
        await db.execute(select(Trace).where(Trace.artifact_id == "joke_score_1"))
    ).scalar_one()
    assert row.kind == "scoring"
    assert row.inputs["rubric_version"] == "1.1"
    assert row.output["score"] == 8
