"""Joker — per-session latency tracking.

Timestamps every named stage and computes p50 / p95 across the session.
Results are appended to docs/TOPOGRAPHY.md at session end.
"""

from __future__ import annotations

import statistics
from datetime import date
from enum import Enum
from pathlib import Path


class Stage(str, Enum):
    SUGGESTION = "suggestion"
    GENERATION = "generation"
    TTS_FIRST_BYTE = "tts_first_byte"
    REACTION = "reaction_capture"
    CLASSIFICATION = "classification"
    SCORING = "scoring"
    FILING = "filing"


class LatencyTracker:
    """Collect latency samples for a single session."""

    def __init__(self) -> None:
        self._samples: dict[Stage, list[int]] = {s: [] for s in Stage}

    def record(self, stage: Stage, ms: int) -> None:
        """Record one latency sample (milliseconds) for a stage."""
        self._samples[stage].append(ms)

    def report(self) -> dict[Stage, dict[str, float]]:
        """Return p50 and p95 for each stage that has at least one sample.

        Stages with no samples are omitted from the result.
        """
        result: dict[Stage, dict[str, float]] = {}
        for stage, samples in self._samples.items():
            if not samples:
                continue
            sorted_samples = sorted(samples)
            result[stage] = {
                "p50": _percentile(sorted_samples, 50),
                "p95": _percentile(sorted_samples, 95),
                "n": float(len(samples)),
            }
        return result

    def flush_to_topography(self, path: Path) -> None:
        """Append a dated row to docs/TOPOGRAPHY.md.

        Creates the file with a header if it does not exist.
        """
        data = self.report()
        if not data:
            return

        today = date.today().isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)

        if not path.exists():
            path.write_text(_HEADER, encoding="utf-8")

        lines: list[str] = []
        for stage, stats in data.items():
            lines.append(
                f"| {today} | {stage.value} "
                f"| {stats['p50']:.0f} "
                f"| {stats['p95']:.0f} "
                f"| {int(stats['n'])} |"
            )

        with path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _percentile(sorted_data: list[int], pct: int) -> float:
    if not sorted_data:
        return 0.0
    if len(sorted_data) == 1:
        return float(sorted_data[0])
    rank = (pct / 100) * (len(sorted_data) - 1)
    low = int(rank)
    high = low + 1
    if high >= len(sorted_data):
        return float(sorted_data[-1])
    frac = rank - low
    return sorted_data[low] * (1 - frac) + sorted_data[high] * frac


_HEADER = """\
# Latency Topography

Latency measurements (milliseconds) recorded by `joker/latency.py` at session end.
Each row represents one session's data for one pipeline stage.

| date | stage | p50_ms | p95_ms | n |
|------|-------|-------:|-------:|--:|
"""
