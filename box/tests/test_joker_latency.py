"""Latency tracker reports p50 and p95 for named stages."""

from __future__ import annotations

from joker.latency import LatencyTracker, Stage


def test_p50_and_p95_from_known_samples():
    tracker = LatencyTracker()
    for ms in (10, 20, 30, 40, 50):
        tracker.record(Stage.GENERATION, ms)
    report = tracker.report()
    assert report[Stage.GENERATION]["p50"] == 30.0
    assert report[Stage.GENERATION]["p95"] == 48.0
    assert report[Stage.GENERATION]["n"] == 5.0
    assert Stage.SUGGESTION not in report
