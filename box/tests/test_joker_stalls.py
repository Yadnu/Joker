"""Stalls are session-unique, yaml-backed, and never joke records."""

from __future__ import annotations

from box.schema.records import UserContext
from joker.generate import (
    _extract_final,
    next_engine,
    next_shape,
    strip_repeated_closings,
)
from joker.orchestrator import SessionState
from joker.setbuilder import JokeSet, RecoveryMove, Slot
from joker.stalls import CATEGORIES, _STALLS, pick_stall
from shared.trace import VALID_KINDS


def _state() -> SessionState:
    return SessionState(
        session_id="sess_stalls",
        listener_context=UserContext(),
        taxonomy_snapshot_version="2026-09-02",
        joker_name="joker-v1",
        account_name="joker-live",
        box_api_key=None,
        angles=[],
        joke_set=JokeSet(
            set_id="set_stalls",
            slots=[
                Slot(name="opener", joke_id=None, joke_text="x"),
                Slot(name="bit", joke_id=None, joke_text="y"),
            ],
            recovery=RecoveryMove(action="skip_to_callback", line="x", rationale="t"),
        ),
    )


def test_stall_kind_is_valid():
    assert "stall" in VALID_KINDS


def test_each_category_has_at_least_ten_lines():
    for cat in CATEGORIES:
        assert len(_STALLS[cat]) >= 10


def test_pick_stall_does_not_repeat_in_session():
    state = _state()
    seen: list[str] = []
    for _ in range(len(_STALLS["post_bomb"])):
        line = pick_stall("post_bomb", state)
        assert line is not None
        assert line not in seen
        seen.append(line)
    assert pick_stall("post_bomb", state) is None


def test_topic_ack_substitutes_topic():
    state = _state()
    line = pick_stall("topic_acknowledgment", state, topic="the Eastern Front")
    assert line is not None
    assert "Eastern Front" in line
    assert "{topic}" not in line


def test_next_shape_never_repeats_adjacent():
    last = None
    for i in range(12):
        shape = next_shape(last_shape=last, slot_idx=i)
        assert shape != last
        last = shape


def test_next_engine_never_repeats_adjacent():
    last = None
    for _ in range(20):
        engine = next_engine(last_engine=last)
        assert engine != last
        last = engine


def test_extract_final_drops_the_drafting():
    raw = (
        "Attempt 1: something weak.\n"
        "Attempt 2: worse.\n"
        'FINAL: "There is one Blockbuster left. Bend, Oregon."'
    )
    assert _extract_final(raw) == "There is one Blockbuster left. Bend, Oregon."


def test_extract_final_passes_through_plain_text():
    assert _extract_final("  a bare line.  ") == "a bare line."


def test_strip_repeated_closings_tracks_session():
    used: set[str] = set()
    first = strip_repeated_closings("Bit about kale. Your move.", used)
    assert "your move" in used
    second = strip_repeated_closings("Another bit. Your move.", used)
    assert "your move" not in second.lower()
