"""Suggest must feed the Joker ranked angles from archive + thin coverage."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from box.schema.models import Trace
from box.schema.records import HumorStyle, UserContext
from librarian.interface import SuggestionRequest
from librarian.suggest import suggest
from box.tests.archive_seed import seed_two_genres


def _completion(payload: dict):
    response = AsyncMock()
    response.choices = [
        type("Choice", (), {"message": type("Msg", (), {"content": json.dumps(payload)})()})()
    ]
    response.usage = type("U", (), {"prompt_tokens": 20, "completion_tokens": 40})()
    return response


@pytest.mark.asyncio
async def test_suggest_returns_ranked_angles_from_archive(db):
    await seed_two_genres(db)
    payload = {
        "angles": [
            {
                "genre": "ThinOffice",
                "topic": "hot desking",
                "rationale": "Thin coverage plus tech occupation overlap.",
                "freshness_score": 0.9,
            },
            {
                "genre": "AirportSecurity",
                "topic": "TSA shoes",
                "rationale": "High scorers in this genre for a dry tech listener.",
                "freshness_score": 0.2,
            },
            {
                "genre": "BaggageClaim",
                "topic": "identical suitcases",
                "rationale": "Adjacent travel bit without repeating AirportSecurity.",
                "freshness_score": 0.4,
            },
        ]
    }
    with patch("librarian.suggest._client.chat.completions.create", new=AsyncMock(return_value=_completion(payload))) as create:
        result = await suggest(
            SuggestionRequest(
                user_context=UserContext(
                    occupation_field="tech",
                    humor_preferences=[HumorStyle.observational, HumorStyle.deadpan],
                    energy="dry",
                ),
                taxonomy_snapshot_version="2026-09-01",
            ),
            db,
        )

    assert [a.genre for a in result.angles] == [
        "ThinOffice",
        "AirportSecurity",
        "BaggageClaim",
    ]
    assert all(a.rationale for a in result.angles)
    prompt = create.await_args.kwargs["messages"][-1]["content"]
    assert "ThinOffice" in prompt
    assert "TSA packed bags" in prompt or "AirportSecurity" in prompt

    traces = (await db.execute(select(Trace).where(Trace.kind == "suggestion"))).scalars().all()
    assert len(traces) == 1
    assert traces[0].inputs["high_scorer_count"] >= 1
    assert "ThinOffice" in traces[0].inputs["thin_genres"]
    assert "occupation_field" in traces[0].inputs["active_context_fields"]


@pytest.mark.asyncio
async def test_suggest_zero_angles_is_hard_error(db):
    await seed_two_genres(db)
    with patch(
        "librarian.suggest._client.chat.completions.create",
        new=AsyncMock(return_value=_completion({"angles": []})),
    ):
        with pytest.raises(RuntimeError, match="zero angles"):
            await suggest(
                SuggestionRequest(
                    user_context=UserContext(),
                    taxonomy_snapshot_version="2026-09-01",
                ),
                db,
            )
