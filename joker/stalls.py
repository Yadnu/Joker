"""Session-scoped performance filler. Never filed to the Box."""

from __future__ import annotations

import random
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from joker.orchestrator import SessionState

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_STALLS_PATH = _PROMPTS_DIR / "stalls.yaml"

CATEGORIES = (
    "topic_acknowledgment",
    "thinking",
    "post_laugh",
    "post_bomb",
    "crowd_work",
    "transitions",
)


def _parse_stalls_yaml(text: str) -> dict[str, list[str]]:
    data: dict[str, list[str]] = {}
    key: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" ") and line.endswith(":"):
            key = line[:-1].strip()
            data[key] = []
            continue
        stripped = line.strip()
        if key and stripped.startswith("- "):
            data[key].append(stripped[2:].strip())
    return data


_STALLS: dict[str, list[str]] = _parse_stalls_yaml(
    _STALLS_PATH.read_text(encoding="utf-8")
)


def pick_stall(
    category: str,
    state: SessionState,
    *,
    topic: str | None = None,
) -> str | None:
    """Return one unused line for this session, or None if the category is spent."""
    if category not in _STALLS:
        raise ValueError(f"Unknown stall category {category!r}")
    unused = [
        line
        for line in _STALLS[category]
        if f"{category}::{line}" not in state.used_stalls
    ]
    if not unused:
        return None
    if topic:
        tagged = [line for line in unused if "{topic}" in line]
        if tagged:
            unused = tagged
    line = random.choice(unused)
    state.used_stalls.add(f"{category}::{line}")
    if topic and "{topic}" in line:
        snippet = " ".join(topic.split())[:40]
        return line.replace("{topic}", snippet)
    return line.replace("{topic}", "that") if "{topic}" in line else line
