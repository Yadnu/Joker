"""A requested form is generated, not recited, and never repeats in a session."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from box.schema.records import JokeMetadata, Provenance, UserContext
from joker import orchestrator
from joker.setbuilder import JokeSet, RecoveryMove, Slot
from joker.tools import dispatch_tool
from librarian.interface import Angle, ClassificationResponse
from shared import box_client


def _state() -> orchestrator.SessionState:
    return orchestrator.SessionState(
        session_id="sess_fresh",
        listener_context=UserContext(),
        taxonomy_snapshot_version="2026-09-02",
        joker_name="joker-v1",
        account_name="acct_test",
        box_api_key="jbx_testkey",
        angles=[
            Angle(
                genre="Wordplay",
                topic="doors",
                rationale="r",
                freshness_score=0.5,
            )
        ],
        joke_set=JokeSet(
            set_id="set_fresh",
            slots=[
                Slot(
                    name="opener",
                    joke_id="joke_op",
                    joke_text="opener",
                    transition_to_next="",
                )
            ],
            recovery=RecoveryMove(
                action="skip_to_callback", line="anyway", rationale="keep callback"
            ),
        ),
    )


def _box_factory():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "joke_id": "joke_filed_fresh",
                "cabinet_id": "cab",
                "drawer_id": "drw",
                "file_id": "fil",
            },
        )

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        )

    return factory


@pytest.mark.asyncio
async def test_repeated_knock_knock_requests_differ(db, monkeypatch):
    """Two knock-knock requests must not produce the same line."""
    lines = [
        "Knock knock. Who's there? Your landlord. Your landlord who? Exactly.",
        "Knock knock. Who's there? DoorDash. It's outside a building that isn't yours.",
    ]
    calls: list[str] = []

    async def fake_generate(**kwargs):
        calls.append(kwargs["form"])
        # The avoid-list is what makes the second call diverge.
        idx = len(kwargs.get("avoid") or [])
        return lines[min(idx, len(lines) - 1)], Provenance(
            source="generated",
            model="gpt-4o",
            prompt="p",
            selection_rationale="r",
        )

    monkeypatch.setattr(box_client, "_client_factory", _box_factory())
    state = _state()

    with (
        patch("joker.orchestrator.generate", new=fake_generate),
        patch(
            "joker.orchestrator.classify",
            new=AsyncMock(
                return_value=ClassificationResponse(
                    category="Wordplay",
                    path=["Wordplay", "Riddles", "Knock Knock"],
                    justification="knock-knock structure",
                    is_new=False,
                )
            ),
        ),
        patch(
            "joker.orchestrator.extract_metadata",
            new=AsyncMock(
                return_value=JokeMetadata(
                    topic="doors", style="knock-knock", length="short"
                )
            ),
        ),
    ):
        first = await orchestrator.fresh_bit(
            state=state, session=db, topic="doors", form="knock-knock"
        )
        second = await orchestrator.fresh_bit(
            state=state, session=db, topic="doors", form="knock-knock"
        )

    assert calls == ["knock-knock joke", "knock-knock joke"]
    assert first["joke_text"] != second["joke_text"]
    assert first["engine"] != second["engine"]
    assert len(state.told_lines) == 2


@pytest.mark.asyncio
async def test_archive_lookup_does_not_serve_the_same_row_twice(db):
    rows = [
        {"id": "j1", "joke_text": "interrupting cow", "score": 9, "category": "Wordplay"},
        {"id": "j2", "joke_text": "opportunity knocks", "score": 7, "category": "Wordplay"},
    ]
    state = _state()

    with patch(
        "shared.box_client.funniest_in_genre", new=AsyncMock(return_value=rows)
    ):
        first = await dispatch_tool(
            "funniest_in_genre",
            {"genre": "Wordplay", "n": 1},
            db,
            state=state,
        )
        second = await dispatch_tool(
            "funniest_in_genre",
            {"genre": "Wordplay", "n": 1},
            db,
            state=state,
        )
        third = await dispatch_tool(
            "funniest_in_genre",
            {"genre": "Wordplay", "n": 1},
            db,
            state=state,
        )

    assert first[0]["id"] != second[0]["id"]
    assert third == []


@pytest.mark.asyncio
async def test_write_fresh_bit_tool_requires_a_live_set(db):
    result = await dispatch_tool("write_fresh_bit", {"topic": "doors"}, db)
    assert result["error"] == "no_active_set"
