"""Barge-in cancels synthesis immediately and writes a delivery trace."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from box.schema.models import Trace
from joker.realtime import handle_speech_started


@pytest.mark.asyncio
async def test_barge_in_cancels_and_traces(db):
    cancel = AsyncMock()
    ack = AsyncMock()
    speak = AsyncMock()

    text = await handle_speech_started(
        session_id="sess_live_1",
        session=db,
        synthesis_elapsed_ms=240,
        cancel_synthesis=cancel,
        send_ack=ack,
        speak_ack=speak,
        slot_idx=1,
        joke_text="Why did the TSA unpack my bags?",
    )

    cancel.assert_awaited_once()
    ack.assert_awaited_once()
    speak.assert_awaited_once()
    assert "listening" in text.lower() or "sorry" in text.lower()
    row = (
        await db.execute(select(Trace).where(Trace.artifact_id == "sess_live_1"))
    ).scalar_one()
    assert row.kind == "delivery"
    assert row.actor == "joker.realtime"
    assert row.output["interrupted"] is True
    assert row.inputs["slot_idx"] == 1
    assert "TSA" in row.inputs["joke_text"]
    assert row.model == "gpt-4o-realtime-preview-2024-12-17"
    assert "cancel" in row.rationale.lower() or "interrupted" in row.rationale.lower() or "spoke" in row.rationale.lower()
