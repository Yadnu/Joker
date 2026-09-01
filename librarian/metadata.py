"""Librarian — joke metadata extraction.

Extracts topic, style, length, and sensitivity flags from a finished joke.
Sensitivity flags use a fixed enum so a downstream feature can map
listener traits onto stable identifiers.
"""

from __future__ import annotations

import json
import time
from enum import Enum

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.records import JokeMetadata
from shared.trace import record_step

_client = AsyncOpenAI()


class SensitivityFlag(str, Enum):
    """Fixed set of sensitivity dimensions.

    Defined generously: a downstream feature maps listener traits onto these
    flags to decide which jokes are appropriate.  Adding a new flag is a
    breaking change that requires a new enum version and a DECISIONS.md entry.
    """

    ADULT = "adult"
    POLITICAL = "political"
    RELIGIOUS = "religious"
    ETHNIC = "ethnic"
    SELF_DEPRECATING = "self_deprecating"
    DARK = "dark"
    BODY = "body"
    MENTAL_HEALTH = "mental_health"


_FLAG_VALUES = {f.value for f in SensitivityFlag}


async def extract_metadata(
    *,
    joke_id: str,
    joke_text: str,
    session: AsyncSession,
) -> JokeMetadata:
    """Extract structured metadata from a joke.

    Returns a JokeMetadata instance.  sensitivity_flags contains only
    recognised SensitivityFlag values; unrecognised values are dropped
    with a warning rather than raising, to avoid hard failures on novel content.
    """
    t0 = time.monotonic()

    prompt = (
        f"Joke:\n{joke_text}\n\n"
        "Return JSON with keys:\n"
        "  topic   (str): the main subject matter\n"
        "  style   (str): e.g. one-liner, anecdote, callback, observational\n"
        "  length  (str): short | medium | long\n"
        f"  sensitivity_flags (list[str]): zero or more of {sorted(_FLAG_VALUES)}\n"
        "Be conservative with sensitivity flags: only flag what is clearly present."
    )

    response = await _client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "You are a comedy metadata extractor. Return only JSON.",
            },
            {"role": "user", "content": prompt},
        ],
    )

    latency_ms = int((time.monotonic() - t0) * 1000)

    raw = json.loads(response.choices[0].message.content or "{}")

    raw_flags: list[str] = raw.get("sensitivity_flags", [])
    valid_flags = [f for f in raw_flags if f in _FLAG_VALUES]
    dropped = [f for f in raw_flags if f not in _FLAG_VALUES]
    if dropped:
        import warnings
        warnings.warn(
            f"extract_metadata: unrecognised sensitivity flags dropped: {dropped}",
            stacklevel=2,
        )

    metadata = JokeMetadata(
        topic=raw.get("topic", ""),
        style=raw.get("style", ""),
        length=raw.get("length", "short"),
        sensitivity_flags=valid_flags,
    )

    await record_step(
        artifact_id=joke_id,
        artifact_type="joke",
        kind="generation",
        actor="librarian.metadata",
        model="gpt-4o-mini",
        prompt_ref="librarian/metadata_v1",
        inputs={"joke_text": joke_text},
        output=metadata.model_dump(),
        rationale=(
            "Metadata extraction is a model artifact: the topic, style, length, "
            "and sensitivity flags are inferred rather than rule-based, so the "
            "call must be traced."
        ),
        latency_ms=latency_ms,
        cost=_estimate_cost(response),
        session=session,
    )

    return metadata


def _estimate_cost(response) -> float | None:  # type: ignore[no-untyped-def]
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return (usage.prompt_tokens * 0.15 + usage.completion_tokens * 0.60) / 1_000_000
