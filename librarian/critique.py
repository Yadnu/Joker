"""Critique validation and the in-session room-feedback buffer.

A critique must name a mechanism from the few-shot shape vocabulary
(or a structural failure). Vibe language is rejected.
"""

from __future__ import annotations

from typing import Any

FEW_SHOT_SHAPES: tuple[str, ...] = (
    "reversal",
    "literalism",
    "definition",
    "wrong-detail",
    "compression",
    "misdirect",
)

_BANNED = (
    "not funny",
    "weak",
    "could be better",
    "lacks humor",
    "lacks humour",
)

_MECHANISM_TOKENS = (
    "reversal",
    "literalism",
    "definition",
    "wrong-detail",
    "wrong detail",
    "compression",
    "misdirect",
    "punchline",
    "setup",
    "mid-sentence",
    "last word",
    "last six",
    "abstract",
    "shape",
    "turn",
    "explained",
    "image",
    "agreement",
    "over-explained",
    "generic",
    "specific",
    "sentence",
    "no identifiable",
)

NO_SHAPE = "no identifiable shape."


def normalize_critique(raw: str) -> str:
    """Return a mechanism critique or the no-shape fallback. Max twenty words."""
    text = " ".join((raw or "").split())
    if not text:
        return NO_SHAPE
    lower = text.lower()
    if any(b in lower for b in _BANNED):
        return NO_SHAPE
    words = text.split()
    if len(words) > 20:
        text = " ".join(words[:20])
        lower = text.lower()
    if not any(token in lower for token in _MECHANISM_TOKENS):
        return NO_SHAPE
    return text


def format_room_feedback(entries: list[dict[str, Any]]) -> str:
    """Render the last-five buffer as room feedback, not as instructions."""
    if not entries:
        return "Your last five bits:\n  (none yet)\nDo not repeat the same failure twice."
    lines = ["Your last five bits:"]
    for item in entries[-5:]:
        score = item.get("score", "?")
        shape = item.get("shape", "?")
        critique = item.get("critique", "")
        lines.append(f"  [{score}] [{shape}] {critique}")
    lines.append("Do not repeat the same failure twice.")
    return "\n".join(lines)
