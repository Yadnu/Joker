"""Set construction requires named slots, adjacent transitions, and a recovery move."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from box.schema.models import Trace
from joker.setbuilder import JokeSet, RecoveryMove, Slot, adapt_set, build_set
from librarian.interface import Angle


def test_missing_transition_is_construction_failure():
    joke_set = JokeSet(
        set_id="set_shuffle",
        slots=[
            Slot(name="opener", joke_id=None, joke_text="hi", transition_to_next=""),
            Slot(name="closer", joke_id=None, joke_text="bye", transition_to_next=""),
        ],
        recovery=RecoveryMove(action="end_set", line="we're done", rationale="bomb"),
    )
    with pytest.raises(ValueError, match="transition_to_next"):
        joke_set.validate()


def test_ordered_set_with_recovery_validates():
    joke_set = JokeSet(
        set_id="set_ok",
        slots=[
            Slot(
                name="opener",
                joke_id="j1",
                joke_text="warm hello",
                transition_to_next="Opener names TSA so the first bit can pay off shoes-off.",
            ),
            Slot(
                name="bit",
                joke_id="j2",
                joke_text="shoes bit",
                transition_to_next="Callback reuses the TSA agent from the opener.",
            ),
            Slot(
                name="callback",
                joke_id="j3",
                joke_text="agent returns",
                transition_to_next="Closer restates the opener's premise at higher stakes.",
            ),
            Slot(name="closer", joke_id="j4", joke_text="final button", transition_to_next=""),
        ],
        recovery=RecoveryMove(
            action="skip_to_callback",
            line="Alright, scrap that — remember the agent?",
            rationale="Callback still lands if the middle bit dies.",
        ),
    )
    joke_set.validate()
    assert joke_set.recovery.action == "skip_to_callback"


def _completion(payload: dict):
    response = AsyncMock()
    response.choices = [
        type("Choice", (), {"message": type("Msg", (), {"content": json.dumps(payload)})()})()
    ]
    response.usage = type("U", (), {"prompt_tokens": 40, "completion_tokens": 80})()
    return response


@pytest.mark.asyncio
async def test_build_set_records_transitions_and_recovery(db):
    payload = {
        "slots": [
            {
                "name": "opener",
                "joke_text": "hi from the TSA line",
                "transition_to_next": "Names the agent so bit 1 can pay off the bin.",
            },
            {
                "name": "bit",
                "joke_text": "laptop origami",
                "transition_to_next": "Callback needs the bin image from this bit.",
            },
            {
                "name": "callback",
                "joke_text": "the agent again",
                "transition_to_next": "Closer raises the opener's stakes.",
            },
            {
                "name": "closer",
                "joke_text": "we live here now",
                "transition_to_next": "",
            },
        ],
        "recovery": {
            "action": "self_deprecate",
            "line": "That one even I wouldn't heckle.",
            "rationale": "Acknowledge the bomb then keep the callback intact.",
        },
    }
    angles = [
        Angle(genre="AirportSecurity", topic="bins", rationale="high scorer", freshness_score=0.2),
        Angle(genre="ThinOffice", topic="hot desk", rationale="thin", freshness_score=0.9),
    ]
    with patch(
        "joker.setbuilder._client.chat.completions.create",
        new=AsyncMock(return_value=_completion(payload)),
    ):
        joke_set = await build_set(
            angles=angles,
            listener_context="dry tech",
            session=db,
        )

    joke_set.validate()
    assert joke_set.slots[0].transition_to_next
    assert joke_set.recovery.action == "self_deprecate"
    row = (await db.execute(select(Trace).where(Trace.kind == "set_construction"))).scalar_one()
    assert row.output["recovery"]["action"] == "self_deprecate"


@pytest.mark.asyncio
async def test_adapt_set_traces_recovery(db):
    joke_set = JokeSet(
        set_id="set_live",
        slots=[
            Slot(name="opener", joke_id="a", joke_text="a", transition_to_next="to bit"),
            Slot(name="bit", joke_id="b", joke_text="b", transition_to_next="to callback"),
            Slot(name="callback", joke_id="c", joke_text="c", transition_to_next="to closer"),
            Slot(name="closer", joke_id="d", joke_text="d", transition_to_next=""),
        ],
        recovery=RecoveryMove(
            action="skip_to_callback",
            line="anyway — the agent",
            rationale="Preserve callback dependency after a bomb.",
        ),
    )
    adapted = await adapt_set(joke_set=joke_set, bombed_slot_idx=1, session=db)
    assert [s.name for s in adapted.slots] == ["opener", "callback", "closer"]
    row = (await db.execute(select(Trace).where(Trace.kind == "set_adaptation"))).scalar_one()
    assert row.inputs["recovery_action"] == "skip_to_callback"
    assert "bombed" in row.rationale.lower()
