"""joker/orchestrator.py wires suggest -> build_set -> generate -> score ->
classify -> extract_metadata -> upsert_joke, and adapt_set on a bomb.

Librarian calls and the Box client are mocked/patched throughout — none of
these tests require a live voice session or a live Box HTTP server.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from unittest.mock import AsyncMock, patch

from box.schema.models import Trace
from box.schema.records import (
    JokeMetadata,
    Provenance,
    UserContext,
)
from joker import orchestrator
from joker.setbuilder import JokeSet, RecoveryMove, Slot
from librarian.interface import Angle, ClassificationResponse, SuggestionResponse
from shared import box_client


def _mock_box_transport(order: list, joke_id: str = "joke_filed_orch_1"):
    def handler(request: httpx.Request) -> httpx.Response:
        order.append("upsert")
        return httpx.Response(
            201,
            json={
                "joke_id": joke_id,
                "cabinet_id": "cab_1",
                "drawer_id": "drw_1",
                "file_id": "file_1",
            },
        )

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")

    return factory


def _base_state(slot_name: str = "bit") -> orchestrator.SessionState:
    joke_set = JokeSet(
        set_id="set_orch_test_1",
        slots=[
            Slot(name=slot_name, joke_id="joke_orch_1", joke_text="TSA topic", transition_to_next=""),
        ],
        recovery=RecoveryMove(
            action="skip_to_callback", line="anyway", rationale="preserve callback"
        ),
    )
    state = orchestrator.SessionState(
        session_id="sess_orch_1",
        listener_context=UserContext(),
        taxonomy_snapshot_version="2026-09-01",
        joker_name="joker-v1",
        account_name="acct_test",
        box_api_key="jbx_testkey",
        angles=[Angle(genre="AirportSecurity", topic="TSA topic", rationale="r", freshness_score=0.5)],
        joke_set=joke_set,
    )
    state.generations[0] = orchestrator.SlotGeneration(
        joke_id="joke_orch_1",
        topic="TSA topic",
        style="one-liner",
        intended_quality="bad",
        provenance=Provenance(
            source="generated", model="gpt-4o-mini", prompt="Tell a joke about TSA.", selection_rationale="shortest of three"
        ),
    )
    return state


# ---------------------------------------------------------------------------
# start_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_session_calls_suggest_and_returns_angles(db):
    angles = [
        Angle(genre="AirportSecurity", topic="TSA shoes", rationale="high scorer", freshness_score=0.2),
        Angle(genre="ThinOffice", topic="hot desking", rationale="thin coverage", freshness_score=0.9),
    ]
    suggest_mock = AsyncMock(return_value=SuggestionResponse(angles=angles))

    joke_set = JokeSet(
        set_id="set_orch_start_1",
        slots=[
            Slot(name="opener", joke_id=None, joke_text="a", transition_to_next="to bit"),
            Slot(name="bit", joke_id=None, joke_text="b", transition_to_next="to closer"),
            Slot(name="closer", joke_id=None, joke_text="c", transition_to_next=""),
        ],
        recovery=RecoveryMove(action="end_set", line="done", rationale="bomb"),
    )
    build_set_mock = AsyncMock(return_value=joke_set)

    with patch("joker.orchestrator.suggest", new=suggest_mock), \
         patch("joker.orchestrator.build_set", new=build_set_mock):
        state = await orchestrator.start_session(
            session_id="sess_start_1",
            listener_context=UserContext(occupation_field="tech"),
            taxonomy_snapshot_version="2026-09-01",
            session=db,
        )

    suggest_mock.assert_awaited_once()
    build_set_mock.assert_awaited_once()
    assert build_set_mock.await_args.kwargs["angles"] == angles

    assert state.angles == angles
    assert state.joke_set is joke_set

    row = (
        await db.execute(select(Trace).where(Trace.artifact_id == "set_orch_start_1"))
    ).scalar_one()
    assert row.kind == "placement"
    assert row.actor == "joker.orchestrator"
    assert row.output["selected_angles"][0]["genre"] == "AirportSecurity"


# ---------------------------------------------------------------------------
# process_reaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_reaction_calls_pipeline_in_order(db, monkeypatch):
    order: list[str] = []

    def _score_effect(*args, **kwargs):
        order.append("score")
        return 8

    def _classify_effect(*args, **kwargs):
        order.append("classify")
        return ClassificationResponse(
            category="AirportSecurity",
            is_new=False,
            justification="Existing label fits the TSA joke.",
            path=["Travel", "Airports", "AirportSecurity"],
        )

    def _metadata_effect(*args, **kwargs):
        order.append("extract_metadata")
        return JokeMetadata(topic="TSA", style="one-liner", length="short", sensitivity_flags=[])

    monkeypatch.setattr(box_client, "_client_factory", _mock_box_transport(order))

    state = _base_state()

    with patch("joker.orchestrator.score", new=AsyncMock(side_effect=_score_effect)), \
         patch("joker.orchestrator.classify", new=AsyncMock(side_effect=_classify_effect)), \
         patch("joker.orchestrator.extract_metadata", new=AsyncMock(side_effect=_metadata_effect)):
        result = await orchestrator.process_reaction(
            state=state,
            slot_idx=0,
            user_reaction="Ha! That's exactly what happened.",
            session=db,
        )

    assert order == ["score", "classify", "extract_metadata", "upsert"]
    assert result["score"] == 8
    assert result["category"] == "AirportSecurity"
    assert result["bombed"] is False
    assert result["recovery_applied"] is None

    filing_row = (
        await db.execute(select(Trace).where(Trace.kind == "filing"))
    ).scalar_one()
    assert filing_row.actor == "joker.box_client"
    assert filing_row.output["joke_id"] == "joke_filed_orch_1"


@pytest.mark.asyncio
async def test_low_score_triggers_adapt_set(db, monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(box_client, "_client_factory", _mock_box_transport(order))

    state = _base_state()
    adapted_set = JokeSet(
        set_id=state.joke_set.set_id,
        slots=[],
        recovery=state.joke_set.recovery,
    )
    adapt_set_mock = AsyncMock(return_value=adapted_set)

    with patch("joker.orchestrator.score", new=AsyncMock(return_value=2)), \
         patch(
             "joker.orchestrator.classify",
             new=AsyncMock(
                 return_value=ClassificationResponse(
                     category="AirportSecurity",
                     is_new=False,
                     justification="Existing label fits.",
                     path=["Travel", "Airports", "AirportSecurity"],
                 )
             ),
         ), \
         patch(
             "joker.orchestrator.extract_metadata",
             new=AsyncMock(
                 return_value=JokeMetadata(
                     topic="TSA", style="one-liner", length="short", sensitivity_flags=[]
                 )
             ),
         ), \
         patch("joker.orchestrator.adapt_set", new=adapt_set_mock):
        result = await orchestrator.process_reaction(
            state=state,
            slot_idx=0,
            user_reaction="Silence.",
            session=db,
        )

    adapt_set_mock.assert_awaited_once()
    assert adapt_set_mock.await_args.kwargs["bombed_slot_idx"] == 0
    assert state.joke_set is adapted_set
    assert result["bombed"] is True
    assert result["recovery_applied"] == "skip_to_callback"


@pytest.mark.asyncio
async def test_process_reaction_steers_remaining_slot(db, monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(box_client, "_client_factory", _mock_box_transport(order))

    joke_set = JokeSet(
        set_id="set_steer_1",
        slots=[
            Slot(name="opener", joke_id="joke_a", joke_text="first", transition_to_next="to bit"),
            Slot(name="bit", joke_id="joke_b", joke_text="second", transition_to_next=""),
        ],
        recovery=RecoveryMove(action="end_set", line="night", rationale="stop"),
    )
    state = orchestrator.SessionState(
        session_id="sess_steer",
        listener_context=UserContext(),
        taxonomy_snapshot_version="2026-09-01",
        joker_name="joker-v1",
        account_name="acct_test",
        box_api_key="jbx_testkey",
        angles=[Angle(genre="AirportSecurity", topic="TSA", rationale="r", freshness_score=0.5)],
        joke_set=joke_set,
    )
    state.generations[0] = orchestrator.SlotGeneration(
        joke_id="joke_a",
        topic="TSA",
        style="one-liner",
        intended_quality="good",
        provenance=Provenance(
            source="generated",
            model="gpt-4o",
            prompt="p",
            selection_rationale="intended_quality=good; longest",
        ),
    )
    new_angles = [
        Angle(genre="ThinOffice", topic="hot desking", rationale="they liked travel less", freshness_score=0.9)
    ]
    suggest_mock = AsyncMock(return_value=SuggestionResponse(angles=new_angles))
    gen_prov = Provenance(
        source="generated",
        model="gpt-4o",
        prompt="p2",
        selection_rationale="intended_quality=good; longest",
    )
    generate_mock = AsyncMock(return_value=("hot desk lottery joke", gen_prov))

    with patch("joker.orchestrator.score", new=AsyncMock(return_value=8)), \
         patch(
             "joker.orchestrator.classify",
             new=AsyncMock(
                 return_value=ClassificationResponse(
                     category="AirportSecurity",
                     is_new=False,
                     justification="Fits.",
                     path=["Travel", "Airports", "AirportSecurity"],
                 )
             ),
         ), \
         patch(
             "joker.orchestrator.extract_metadata",
             new=AsyncMock(
                 return_value=JokeMetadata(
                     topic="TSA", style="one-liner", length="short", sensitivity_flags=[]
                 )
             ),
         ), \
         patch("joker.orchestrator.suggest", new=suggest_mock), \
         patch("joker.orchestrator.generate", new=generate_mock):
        result = await orchestrator.process_reaction(
            state=state,
            slot_idx=0,
            user_reaction="polite chuckle",
            session=db,
        )

    suggest_mock.assert_awaited()
    generate_mock.assert_awaited()
    assert result["steered"] is True
    assert "hot desk" in state.joke_set.slots[1].joke_text.lower()
    steer_row = (
        await db.execute(select(Trace).where(Trace.kind == "set_adaptation"))
    ).scalar_one()
    assert "ThinOffice" in steer_row.rationale
    assert "session_instructions" in result
    assert "hot desk" in result["session_instructions"].lower()


@pytest.mark.asyncio
async def test_generate_slot_records_generation_latency(db):
    from joker.latency import LatencyTracker, Stage

    state = _base_state("opener")
    tracker = LatencyTracker()
    prov = Provenance(
        source="generated",
        model="o3",
        prompt="p",
        selection_rationale="intended_quality=good; longest of 3",
    )
    with patch(
        "joker.orchestrator.generate",
        new=AsyncMock(return_value=("a developed joke", prov)),
    ):
        text = await orchestrator.generate_slot(
            state=state, slot_idx=0, session=db, tracker=tracker
        )
    assert text == "a developed joke"
    report = tracker.report()
    assert Stage.GENERATION in report
    assert report[Stage.GENERATION]["n"] == 1.0
