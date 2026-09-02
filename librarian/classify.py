"""Librarian — post-generation classification.

Runs AFTER a joke is generated.  Receives the joke, the reaction, and the
current taxonomy snapshot.  Must explicitly branch between:
  - Reusing an existing label (is_new=False, justification explains the fit)
  - Creating a new label  (is_new=True, justification explains why no existing
                           label was adequate; stored on File.category_justification)

An empty justification in either branch raises ValueError, which prevents
taxonomy drift (silent label reuse) and taxonomy explosion (unjustified creation).
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.models import Cabinet, Drawer, File
from librarian.interface import (
    ClassificationRequest,
    ClassificationResponse,
    assert_compatible_version,
)
from shared import box_client
from shared.models import CLASSIFY_MODEL, build_messages, completion_kwargs
from shared.trace import record_step

_client = AsyncOpenAI()

# Versioned prompt file, not an inline f-string. See docs/DECISIONS.md
# 2026-09-01 "Prompts moved to versioned files".
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_SYSTEM_PROMPT = (_PROMPTS_DIR / "classify_v1.txt").read_text(encoding="utf-8").strip()
_USER_TEMPLATE = (_PROMPTS_DIR / "classify_user_v1.txt").read_text(encoding="utf-8")


async def classify(
    request: ClassificationRequest,
    session: AsyncSession,
) -> ClassificationResponse:
    """Assign a category to a joke.

    Fetches the live taxonomy, asks the model to decide reuse vs. create,
    validates the response, and stores category_justification on the File
    row when a new label is created.
    """
    t0 = time.monotonic()
    assert_compatible_version(request.version)

    taxonomy = await _fetch_taxonomy(session)
    prompt = _build_prompt(request, taxonomy)

    system = _SYSTEM_PROMPT
    model_t0 = time.monotonic()
    response = await _client.chat.completions.create(
        **completion_kwargs(
            CLASSIFY_MODEL,
            response_format={"type": "json_object"},
            messages=build_messages(system, prompt, CLASSIFY_MODEL),
        )
    )
    model_ms = int((time.monotonic() - model_t0) * 1000)

    raw = json.loads(response.choices[0].message.content or "{}")

    category: str = raw.get("category", "").strip()
    is_new: bool = bool(raw.get("is_new", False))
    justification: str = raw.get("justification", "").strip()
    path: list[str] = raw.get("path", [])

    if not category:
        raise ValueError("Model returned an empty category.")
    if category.lower() == "general":
        raise ValueError("'General' is not a valid category per AGENTS.md.")
    if not justification:
        raise ValueError(
            "justification is required in ClassificationResponse (is_new="
            f"{is_new}). The model must explain its choice."
        )
    if len(path) != 3:
        raise ValueError(f"path must have exactly 3 elements [cabinet, drawer, file]; got {path}")

    result = ClassificationResponse(
        category=category,
        is_new=is_new,
        justification=justification,
        path=path,
    )

    total_ms = int((time.monotonic() - t0) * 1000)

    await record_step(
        artifact_id=f"category:{category}",
        artifact_type="category",
        kind="classification",
        actor="librarian.classify",
        model=CLASSIFY_MODEL,
        prompt_ref="prompts/classify_user_v1.txt",
        inputs={
            "joke_text": request.joke_text,
            "user_reaction": request.user_reaction,
            "taxonomy_snapshot_version": request.taxonomy_snapshot_version,
            "suggested_path": request.suggested_path,
            "existing_labels": [c["file"] for c in taxonomy],
        },
        output=result.model_dump(),
        rationale=justification,
        latency_ms=total_ms,
        cost=_estimate_cost(response),
        session=session,
    )

    if is_new:
        await _create_category(session, path, justification)
        await record_step(
            artifact_id=f"category:{category}",
            artifact_type="category",
            kind="category_creation",
            actor="librarian.classify",
            model=None,
            prompt_ref=None,
            inputs={"path": path},
            output={"category": category, "justification": justification},
            rationale=(
                f"No existing label adequately matched the joke. "
                f"New path {path} created. Justification: {justification}"
            ),
            latency_ms=0,
            cost=None,
            session=session,
        )

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _fetch_taxonomy(session: AsyncSession) -> list[dict]:
    return await box_client.taxonomy(session=session)


def _build_prompt(request: ClassificationRequest, taxonomy: list[dict]) -> str:
    tax_lines = "\n".join(
        f"  {t['cabinet']} > {t['drawer']} > {t['file']}" for t in taxonomy[:60]
    ) or "  (taxonomy is empty)"
    return _USER_TEMPLATE.format(
        joke_text=request.joke_text,
        user_reaction=request.user_reaction,
        suggested_path=request.suggested_path or "none",
        taxonomy=tax_lines,
    ).strip()


async def _create_category(
    session: AsyncSession, path: list[str], justification: str
) -> None:
    """Upsert cabinet > drawer > file for a new category.

    Uses ON CONFLICT DO NOTHING so concurrent writers cannot double-insert.
    Each level selects the existing row if RETURNING yields nothing.
    New-file justification is stored on File.category_justification.
    """
    cabinet_label, drawer_label, file_label = path
    now = datetime.now(timezone.utc)

    await session.execute(
        pg_insert(Cabinet.__table__)
        .values(id=str(uuid.uuid4()), label=cabinet_label, created_at=now)
        .on_conflict_do_nothing(index_elements=["label"])
    )
    cab_row = (
        await session.execute(select(Cabinet).where(Cabinet.label == cabinet_label))
    ).scalar_one()

    await session.execute(
        pg_insert(Drawer.__table__)
        .values(
            id=str(uuid.uuid4()),
            label=drawer_label,
            cabinet_id=cab_row.id,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["cabinet_id", "label"])
    )
    drw_row = (
        await session.execute(
            select(Drawer).where(
                Drawer.cabinet_id == cab_row.id,
                Drawer.label == drawer_label,
            )
        )
    ).scalar_one()

    await session.execute(
        pg_insert(File.__table__)
        .values(
            id=str(uuid.uuid4()),
            label=file_label,
            drawer_id=drw_row.id,
            category_justification=justification,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["drawer_id", "label"])
    )
    file_row = (
        await session.execute(
            select(File).where(
                File.drawer_id == drw_row.id,
                File.label == file_label,
            )
        )
    ).scalar_one()
    if not file_row.category_justification:
        file_row.category_justification = justification
    await session.flush()


def _estimate_cost(response) -> float | None:  # type: ignore[no-untyped-def]
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    from shared.models import is_reasoning_model
    if is_reasoning_model(CLASSIFY_MODEL):
        # o3 pricing (approximate): $10/1M input, $40/1M output
        return (usage.prompt_tokens * 10 + usage.completion_tokens * 40) / 1_000_000
    # gpt-4o pricing (approximate): $5/1M input, $15/1M output
    return (usage.prompt_tokens * 5 + usage.completion_tokens * 15) / 1_000_000
