"""Critique must name a mechanism; vibe language is rejected."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from box.schema.models import Trace
from librarian.classify import classify
from librarian.critique import NO_SHAPE, format_room_feedback, normalize_critique
from librarian.interface import ClassificationRequest
from box.tests.archive_seed import seed_two_genres
from box.tests.test_librarian_classify import _completion


def test_normalize_critique_rejects_vibe_language():
    assert normalize_critique("not funny") == NO_SHAPE
    assert normalize_critique("weak") == NO_SHAPE
    assert normalize_critique("could be better") == NO_SHAPE
    assert normalize_critique("lacks humor") == NO_SHAPE
    assert normalize_critique("") == NO_SHAPE
    assert normalize_critique("nice energy tonight") == NO_SHAPE


def test_normalize_critique_keeps_mechanism():
    text = "Punchline landed mid-sentence; the last six words explained it."
    assert normalize_critique(text) == text


def test_format_room_feedback_lists_last_five():
    buf = [
        {"score": 3, "shape": "literalism", "critique": "Subject was abstract: people."},
        {"score": 7, "shape": "reversal", "critique": "Reversal worked, setup ran long."},
    ]
    blob = format_room_feedback(buf)
    assert "[3] [literalism]" in blob
    assert "Do not repeat the same failure twice." in blob


@pytest.mark.asyncio
async def test_classify_writes_critique_trace(db):
    await seed_two_genres(db)
    payload = {
        "category": "AirportSecurity",
        "is_new": False,
        "justification": "Punchline is TSA procedure; existing AirportSecurity file is exact.",
        "path": ["Travel", "Airports", "AirportSecurity"],
        "critique": "Reversal worked, but the setup ran three words long.",
    }
    with patch(
        "librarian.classify._client.chat.completions.create",
        new=AsyncMock(return_value=_completion(payload)),
    ):
        result = await classify(
            ClassificationRequest(
                joke_text="I packed my own bags. TSA said unpack them.",
                user_reaction="Ha.",
                taxonomy_snapshot_version="2026-09-01",
                suggested_path=["Travel", "Airports", "AirportSecurity"],
            ),
            db,
        )

    assert "Reversal" in result.critique
    rows = (await db.execute(select(Trace).where(Trace.kind == "critique"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].output["critique"] == result.critique
    assert rows[0].rationale
