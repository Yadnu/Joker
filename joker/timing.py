"""Cold-start and stall timing. Print-only; never blocks the audio path."""

from __future__ import annotations

import time


def now() -> float:
    return time.monotonic()


def ms_since(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def mark(t0: float, stage: str, extra: str = "") -> int:
    elapsed = ms_since(t0)
    suffix = f" {extra}" if extra else ""
    print(f"[timing] {stage} +{elapsed}ms{suffix}", flush=True)
    return elapsed
