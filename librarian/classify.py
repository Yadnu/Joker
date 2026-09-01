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

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.models import Cabinet, Drawer, File
from librarian.interface import (
    ClassificationRequest,
    ClassificationResponse,
)
from shared.trace import record_step

_client = AsyncOpenAI()


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

    taxonomy = await _fetch_taxonomy(session)
    prompt = _build_prompt(request, taxonomy)

    model_t0 = time.monotonic()
    response = await _client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the Librarian for an AI comedian. "
                    "Given a joke and the current taxonomy, decide whether to "
                    "assign an existing category or create a new one. "
                    "Return JSON with keys: category (str), is_new (bool), "
                    "justification (str, non-empty), "
                    "path ([cabinet_label, drawer_label, file_label]). "
                    "Never use 'General' as a category. "
                    "justification is REQUIRED whether is_new is true or false."
                ),
            },
            {"role": "user", "content": prompt},
        ],
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
        model="gpt-4o",
        prompt_ref="librarian/classify_v1",
        inputs={
            "joke_text": request.joke_text,
            "user_reaction": request.user_reaction,
            "taxonomy_snapshot_version": request.taxonomy_snapshot_version,
            "suggested_path": request.suggested_path,
            "existing_labels": [c["label"] for c in taxonomy],
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
    stmt = (
        select(Cabinet.label, Drawer.label, File.label, File.id)
        .join(Drawer, Drawer.cabinet_id == Cabinet.id)
        .join(File, File.drawer_id == Drawer.id)
        .order_by(Cabinet.label, Drawer.label, File.label)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {"cabinet": r[0], "drawer": r[1], "file": r[2], "file_id": r[3]}
        for r in rows
    ]


def _build_prompt(request: ClassificationRequest, taxonomy: list[dict]) -> str:
    tax_lines = "\n".join(
        f"  {t['cabinet']} > {t['drawer']} > {t['file']}" for t in taxonomy[:60]
    ) or "  (taxonomy is empty)"
    return (
        f"Joke:\n{request.joke_text}\n\n"
        f"User reaction:\n{request.user_reaction}\n\n"
        f"Suggested path from pre-generation step: {request.suggested_path or 'none'}\n\n"
        f"Current taxonomy (cabinet > drawer > file):\n{tax_lines}\n\n"
        "Decide: reuse an existing file label, or create a new path. "
        "Provide a non-empty justification either way."
    )


async def _create_category(
    session: AsyncSession, path: list[str], justification: str
) -> None:
    """Upsert cabinet > drawer > file for a new category.

    Uses ON CONFLICT DO NOTHING so concurrent writers cannot double-insert.
    Each level selects the existing row if RETURNING yields nothing.
    """
    cabinet_label, drawer_label, file_label = path

    # Cabinet
    from box.schema.models import Cabinet as CabinetModel, Drawer as DrawerModel, File as FileModel
    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    await session.execute(
        CabinetModel.__table__.insert()
        .prefix_with("ON CONFLICT (label) DO NOTHING")
        .values(id=str(uuid.uuid4()), label=cabinet_label, created_at=now)
    )
    cab_row = (
        await session.execute(
            select(CabinetModel).where(CabinetModel.label == cabinet_label)
        )
    ).scalar_one()

    await session.execute(
        DrawerModel.__table__.insert()
        .prefix_with("ON CONFLICT (cabinet_id, label) DO NOTHING")
        .values(
            id=str(uuid.uuid4()),
            label=drawer_label,
            cabinet_id=cab_row.id,
            created_at=now,
        )
    )
    drw_row = (
        await session.execute(
            select(DrawerModel).where(
                DrawerModel.cabinet_id == cab_row.id,
                DrawerModel.label == drawer_label,
            )
        )
    ).scalar_one()

    await session.execute(
        FileModel.__table__.insert()
        .prefix_with("ON CONFLICT (drawer_id, label) DO NOTHING")
        .values(
            id=str(uuid.uuid4()),
            label=file_label,
            drawer_id=drw_row.id,
            category_justification=justification,
            created_at=now,
        )
    )
    await session.flush()


def _estimate_cost(response) -> float | None:  # type: ignore[no-untyped-def]
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    # gpt-4o pricing (approximate): $5/1M input, $15/1M output
    return (usage.prompt_tokens * 5 + usage.completion_tokens * 15) / 1_000_000
