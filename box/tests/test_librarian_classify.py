"""Classify must branch reuse vs create-with-justification stored on the file."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from box.schema.models import File, Trace
from librarian.classify import classify
from librarian.interface import ClassificationRequest
from box.tests.archive_seed import seed_two_genres


def _completion(payload: dict):
    response = AsyncMock()
    response.choices = [
        type("Choice", (), {"message": type("Msg", (), {"content": json.dumps(payload)})()})()
    ]
    response.usage = type("U", (), {"prompt_tokens": 30, "completion_tokens": 50})()
    return response


@pytest.mark.asyncio
async def test_classify_reuses_existing_label_with_justification(db):
    await seed_two_genres(db)
    payload = {
        "category": "AirportSecurity",
        "is_new": False,
        "justification": "Punchline is TSA procedure; existing AirportSecurity file is exact.",
        "path": ["Travel", "Airports", "AirportSecurity"],
    }
    with patch(
        "librarian.classify._client.chat.completions.create",
        new=AsyncMock(return_value=_completion(payload)),
    ):
        result = await classify(
            ClassificationRequest(
                joke_text="I packed my own bags. TSA said unpack them.",
                user_reaction="Ha, that's my Tuesday.",
                taxonomy_snapshot_version="2026-09-01",
                suggested_path=["Travel", "Airports", "AirportSecurity"],
            ),
            db,
        )

    assert result.is_new is False
    assert result.category == "AirportSecurity"
    assert "TSA" in result.justification
    files_before = (await db.execute(select(File))).scalars().all()
    assert all(
        f.category_justification is None or f.label != "AirportSecurity"
        for f in files_before
        if f.label == "AirportSecurity"
    )
    traces = (await db.execute(select(Trace).where(Trace.kind == "classification"))).scalars().all()
    assert traces[0].output["is_new"] is False


@pytest.mark.asyncio
async def test_classify_create_stores_justification_on_file(db):
    await seed_two_genres(db)
    payload = {
        "category": "GateHolds",
        "is_new": True,
        "justification": (
            "No existing file covers indefinite gate-hold limbo; "
            "AirportSecurity is procedural screening, not waiting-at-the-gate."
        ),
        "path": ["Travel", "Airports", "GateHolds"],
    }
    with patch(
        "librarian.classify._client.chat.completions.create",
        new=AsyncMock(return_value=_completion(payload)),
    ):
        result = await classify(
            ClassificationRequest(
                joke_text="We've been boarding for forty minutes and nobody has boarded.",
                user_reaction="painful nod",
                taxonomy_snapshot_version="2026-09-01",
            ),
            db,
        )

    assert result.is_new is True
    file_row = (
        await db.execute(select(File).where(File.label == "GateHolds"))
    ).scalar_one()
    assert file_row.category_justification == result.justification
    creation = (
        await db.execute(select(Trace).where(Trace.kind == "category_creation"))
    ).scalars().all()
    assert len(creation) == 1
    assert "GateHolds" in creation[0].rationale


@pytest.mark.asyncio
async def test_classify_rejects_general_and_empty_justification(db):
    await seed_two_genres(db)
    with patch(
        "librarian.classify._client.chat.completions.create",
        new=AsyncMock(
            return_value=_completion(
                {
                    "category": "General",
                    "is_new": False,
                    "justification": "catch-all",
                    "path": ["Misc", "Misc", "General"],
                }
            )
        ),
    ):
        with pytest.raises(ValueError, match="General"):
            await classify(
                ClassificationRequest(
                    joke_text="x",
                    user_reaction="y",
                    taxonomy_snapshot_version="2026-09-01",
                ),
                db,
            )
