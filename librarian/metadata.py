"""Librarian — joke metadata extraction.

Extracts topic, style, length, sensitivity flags, and theme flags from a
finished joke.  Sensitivity flags use HumorStyle (the same enum as listener
humor_preferences and humor_avoid) so a downstream Audience Categorizer can
map traits onto flags without a translation layer.  Theme flags capture
specific subject-matter territory (mortality, institutional_failure, etc.) at
finer granularity than a single "dark" boolean.

tone_level is injected by the caller and stored directly — it is a generation
parameter, not something to be inferred from the text.
"""

from __future__ import annotations

import json
import time
import warnings
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.records import HumorStyle, JokeMetadata, ThemeFlag
from shared.models import METADATA_MODEL, build_messages, completion_kwargs
from shared.trace import record_step

_client = AsyncOpenAI()

SensitivityFlag = HumorStyle

_FLAG_VALUES = {f.value for f in HumorStyle}
_THEME_VALUES = {f.value for f in ThemeFlag}

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_SYSTEM_PROMPT = (_PROMPTS_DIR / "metadata_v1.txt").read_text(encoding="utf-8").strip()


async def extract_metadata(
    *,
    joke_id: str,
    joke_text: str,
    tone_level: int = 1,
    session: AsyncSession,
    shape: str = "",
    critique: str = "",
) -> JokeMetadata:
    """Extract structured metadata from a joke.

    tone_level is passed in from the generator — it is a generation parameter,
    not inferred from text — and stored on JokeMetadata.tone_level.

    Returns a JokeMetadata instance.  sensitivity_flags and theme_flags contain
    only recognised values; unrecognised ones are dropped with a warning.
    """
    t0 = time.monotonic()

    prompt = (
        f"Joke:\n{joke_text}\n\n"
        "Return JSON with keys:\n"
        "  topic   (str): the main subject matter\n"
        "  style   (str): e.g. one-liner, anecdote, callback, observational\n"
        "  length  (str): short | medium | long\n"
        f"  sensitivity_flags (list[str]): zero or more of {sorted(_FLAG_VALUES)}\n"
        f"  theme_flags (list[str]): zero or more of {sorted(_THEME_VALUES)} — "
        "specific thematic content present (e.g. mortality if the joke touches "
        "on death, workplace if it targets office/employment situations, "
        "institutional_failure if it targets systems or organisations). "
        "Be specific: prefer mortality over dark, workplace over observational "
        "when the subject is clearly one of these named territories.\n"
        "Be conservative: only flag what is clearly present."
    )

    response = await _client.chat.completions.create(
        **completion_kwargs(
            METADATA_MODEL,
            response_format={"type": "json_object"},
            messages=build_messages(
                _SYSTEM_PROMPT,
                prompt,
                METADATA_MODEL,
            ),
        )
    )

    latency_ms = int((time.monotonic() - t0) * 1000)

    raw = json.loads(response.choices[0].message.content or "{}")

    raw_flags: list[str] = raw.get("sensitivity_flags", [])
    valid_flags = [HumorStyle(f) for f in raw_flags if f in _FLAG_VALUES]
    dropped_flags = [f for f in raw_flags if f not in _FLAG_VALUES]
    if dropped_flags:
        warnings.warn(
            f"extract_metadata: unrecognised sensitivity flags dropped: {dropped_flags}",
            stacklevel=2,
        )

    raw_themes: list[str] = raw.get("theme_flags", [])
    valid_themes = [ThemeFlag(t) for t in raw_themes if t in _THEME_VALUES]
    dropped_themes = [t for t in raw_themes if t not in _THEME_VALUES]
    if dropped_themes:
        warnings.warn(
            f"extract_metadata: unrecognised theme flags dropped: {dropped_themes}",
            stacklevel=2,
        )

    metadata = JokeMetadata(
        topic=raw.get("topic", ""),
        style=raw.get("style", ""),
        length=raw.get("length", "short"),
        sensitivity_flags=valid_flags,
        theme_flags=valid_themes,
        tone_level=tone_level,
        shape=shape,
        critique=critique,
    )

    await record_step(
        artifact_id=joke_id,
        artifact_type="joke",
        kind="classification",
        actor="librarian.metadata",
        model=METADATA_MODEL,
        prompt_ref="prompts/metadata_v1.txt",
        inputs={"joke_text": joke_text, "tone_level": tone_level},
        output=metadata.model_dump(mode="json"),
        rationale=(
            "Metadata extraction is a model artifact: the topic, style, length, "
            "sensitivity_flags, and theme_flags are inferred rather than rule-based, "
            "so the call must be traced. tone_level is injected from the generation "
            f"parameters (tone_level={tone_level}) and stored verbatim."
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
