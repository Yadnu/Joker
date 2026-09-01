"""Box HTTP API — FastAPI router.

Endpoints (per box-api skill):
  GET  /health
  GET  /box
  PUT  /box/upsert
  GET  /cabinets
  GET  /cabinets/{cabinet_id}
  GET  /drawers/{drawer_id}
  GET  /files/{file_id}
  GET  /jokes/{joke_id}
  GET  /jokes/{joke_id}/trace
  GET  /compliance

Classification intelligence lives in the Librarian, not here.
The Box stores what it is handed; it does not infer, default, or repair paths.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.models import Cabinet, Drawer, File, Joke, Trace
from box.schema.records import JokeRecord
from shared.db import get_session

router = APIRouter()


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------

def _level_error(level: str, reason: str, status: int = 404) -> HTTPException:
    return HTTPException(status_code=status, detail={"level": level, "reason": reason})


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

class UpsertRequest(BaseModel):
    cabinet: str
    drawer: str
    file: str
    joke: JokeRecord


@router.put("/box/upsert", status_code=201)
async def upsert(
    body: UpsertRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """File a joke into the path the caller supplies.

    Creates cabinet, drawer, and file if they do not exist.
    Uses ON CONFLICT DO NOTHING so concurrent writes are safe.
    The whole operation runs in a single transaction.
    """
    now = datetime.now(timezone.utc)

    # Cabinet
    await session.execute(
        Cabinet.__table__.insert()
        .prefix_with("ON CONFLICT (label) DO NOTHING")
        .values(id=str(uuid.uuid4()), label=body.cabinet, created_at=now)
    )
    cab = (
        await session.execute(select(Cabinet).where(Cabinet.label == body.cabinet))
    ).scalar_one_or_none()
    if cab is None:
        raise _level_error("cabinet", f"Cabinet '{body.cabinet}' could not be created.", 500)

    # Drawer
    await session.execute(
        Drawer.__table__.insert()
        .prefix_with("ON CONFLICT (cabinet_id, label) DO NOTHING")
        .values(id=str(uuid.uuid4()), label=body.drawer, cabinet_id=cab.id, created_at=now)
    )
    drw = (
        await session.execute(
            select(Drawer).where(Drawer.cabinet_id == cab.id, Drawer.label == body.drawer)
        )
    ).scalar_one_or_none()
    if drw is None:
        raise _level_error("drawer", f"Drawer '{body.drawer}' could not be created.", 500)

    # File
    await session.execute(
        File.__table__.insert()
        .prefix_with("ON CONFLICT (drawer_id, label) DO NOTHING")
        .values(id=str(uuid.uuid4()), label=body.file, drawer_id=drw.id, created_at=now)
    )
    fil = (
        await session.execute(
            select(File).where(File.drawer_id == drw.id, File.label == body.file)
        )
    ).scalar_one_or_none()
    if fil is None:
        raise _level_error("file", f"File '{body.file}' could not be created.", 500)

    # Joke
    joke_id = str(uuid.uuid4())
    record = body.joke
    joke = Joke(
        id=joke_id,
        file_id=fil.id,
        prompt_responses=[t.model_dump() for t in record.prompt_responses],
        joke_text=record.joke_text,
        user_reaction=record.user_reaction,
        score=record.score,
        category=record.category,
        joke_metadata=record.metadata.model_dump(),
        user_context=record.user_context,
        attribution=record.attribution.model_dump(),
        provenance=record.provenance.model_dump(),
        set_id=record.set_id.model_dump(),
        created_at=now,
    )
    session.add(joke)
    await session.commit()

    return {
        "joke_id": joke_id,
        "cabinet_id": cab.id,
        "drawer_id": drw.id,
        "file_id": fil.id,
    }


# ---------------------------------------------------------------------------
# Hierarchy reads
# ---------------------------------------------------------------------------

@router.get("/box")
async def get_box(session: AsyncSession = Depends(get_session)) -> dict:
    cabs = (await session.execute(select(Cabinet))).scalars().all()
    result = []
    for cab in cabs:
        drawers = []
        for drw in (
            await session.execute(select(Drawer).where(Drawer.cabinet_id == cab.id))
        ).scalars().all():
            files = []
            for fil in (
                await session.execute(select(File).where(File.drawer_id == drw.id))
            ).scalars().all():
                jokes = (
                    await session.execute(select(Joke).where(Joke.file_id == fil.id))
                ).scalars().all()
                files.append({
                    "id": fil.id,
                    "label": fil.label,
                    "joke_count": len(jokes),
                })
            drawers.append({"id": drw.id, "label": drw.label, "files": files})
        result.append({"id": cab.id, "label": cab.label, "drawers": drawers})
    return {"cabinets": result}


@router.get("/cabinets")
async def list_cabinets(session: AsyncSession = Depends(get_session)) -> dict:
    rows = (await session.execute(select(Cabinet))).scalars().all()
    return {"cabinets": [{"id": r.id, "label": r.label} for r in rows]}


@router.get("/cabinets/{cabinet_id}")
async def get_cabinet(
    cabinet_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    cab = (
        await session.execute(select(Cabinet).where(Cabinet.id == cabinet_id))
    ).scalar_one_or_none()
    if cab is None:
        raise _level_error("cabinet", f"Cabinet '{cabinet_id}' not found.")
    drawers = (
        await session.execute(select(Drawer).where(Drawer.cabinet_id == cab.id))
    ).scalars().all()
    return {
        "id": cab.id,
        "label": cab.label,
        "drawers": [{"id": d.id, "label": d.label} for d in drawers],
    }


@router.get("/drawers/{drawer_id}")
async def get_drawer(
    drawer_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    drw = (
        await session.execute(select(Drawer).where(Drawer.id == drawer_id))
    ).scalar_one_or_none()
    if drw is None:
        raise _level_error("drawer", f"Drawer '{drawer_id}' not found.")
    files = (
        await session.execute(select(File).where(File.drawer_id == drw.id))
    ).scalars().all()
    return {
        "id": drw.id,
        "label": drw.label,
        "cabinet_id": drw.cabinet_id,
        "files": [{"id": f.id, "label": f.label} for f in files],
    }


@router.get("/files/{file_id}")
async def get_file(
    file_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    fil = (
        await session.execute(select(File).where(File.id == file_id))
    ).scalar_one_or_none()
    if fil is None:
        raise _level_error("file", f"File '{file_id}' not found.")
    jokes = (
        await session.execute(select(Joke).where(Joke.file_id == fil.id))
    ).scalars().all()
    return {
        "id": fil.id,
        "label": fil.label,
        "drawer_id": fil.drawer_id,
        "jokes": [{"id": j.id, "score": j.score} for j in jokes],
    }


@router.get("/jokes/{joke_id}")
async def get_joke(
    joke_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    joke = (
        await session.execute(select(Joke).where(Joke.id == joke_id))
    ).scalar_one_or_none()
    if joke is None:
        raise _level_error("joke", f"Joke '{joke_id}' not found.")
    return _joke_to_dict(joke)


@router.get("/jokes/{joke_id}/trace")
async def get_joke_trace(
    joke_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    joke = (
        await session.execute(select(Joke).where(Joke.id == joke_id))
    ).scalar_one_or_none()
    if joke is None:
        raise _level_error("joke", f"Joke '{joke_id}' not found.")
    traces = (
        await session.execute(
            select(Trace).where(Trace.artifact_id == joke_id).order_by(Trace.created_at)
        )
    ).scalars().all()
    return {
        "joke_id": joke_id,
        "steps": [
            {
                "id": t.id,
                "kind": t.kind,
                "actor": t.actor,
                "rationale": t.rationale,
                "latency_ms": t.latency_ms,
            }
            for t in traces
        ],
    }


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------

@router.get("/compliance")
async def compliance(session: AsyncSession = Depends(get_session)) -> dict:
    """Live hierarchy compliance check.  Never a stored flag."""
    violations = []

    # Cabinets with fewer than 2 drawers
    cab_drawer_counts = (
        await session.execute(
            select(Cabinet.id, Cabinet.label, func.count(Drawer.id).label("n"))
            .outerjoin(Drawer, Drawer.cabinet_id == Cabinet.id)
            .group_by(Cabinet.id, Cabinet.label)
        )
    ).all()
    for cab_id, cab_label, n in cab_drawer_counts:
        if n < 2:
            violations.append({
                "level": "cabinet",
                "path": cab_label,
                "child_count": n,
                "reason": f"Cabinet '{cab_label}' has {n} drawer(s); requires more than one.",
            })

    # Drawers with fewer than 2 files
    drw_file_counts = (
        await session.execute(
            select(Drawer.id, Drawer.label, Cabinet.label.label("cab_label"), func.count(File.id).label("n"))
            .join(Cabinet, Cabinet.id == Drawer.cabinet_id)
            .outerjoin(File, File.drawer_id == Drawer.id)
            .group_by(Drawer.id, Drawer.label, Cabinet.label)
        )
    ).all()
    for drw_id, drw_label, cab_label, n in drw_file_counts:
        if n < 2:
            violations.append({
                "level": "drawer",
                "path": f"{cab_label} > {drw_label}",
                "child_count": n,
                "reason": f"Drawer '{drw_label}' has {n} file(s); requires more than one.",
            })

    # Files with fewer than 2 jokes
    fil_joke_counts = (
        await session.execute(
            select(
                File.id,
                File.label,
                Drawer.label.label("drw_label"),
                Cabinet.label.label("cab_label"),
                func.count(Joke.id).label("n"),
            )
            .join(Drawer, Drawer.id == File.drawer_id)
            .join(Cabinet, Cabinet.id == Drawer.cabinet_id)
            .outerjoin(Joke, Joke.file_id == File.id)
            .group_by(File.id, File.label, Drawer.label, Cabinet.label)
        )
    ).all()
    for fil_id, fil_label, drw_label, cab_label, n in fil_joke_counts:
        if n < 2:
            violations.append({
                "level": "file",
                "path": f"{cab_label} > {drw_label} > {fil_label}",
                "child_count": n,
                "reason": f"File '{fil_label}' has {n} joke(s); requires more than one.",
            })

    return {"compliant": len(violations) == 0, "violations": violations}


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------

@router.get("/counts")
async def counts(session: AsyncSession = Depends(get_session)) -> dict:
    n_cabs = (await session.execute(select(func.count()).select_from(Cabinet))).scalar()
    n_drws = (await session.execute(select(func.count()).select_from(Drawer))).scalar()
    n_fils = (await session.execute(select(func.count()).select_from(File))).scalar()
    n_jokes = (await session.execute(select(func.count()).select_from(Joke))).scalar()
    return {
        "cabinets": n_cabs,
        "drawers": n_drws,
        "files": n_fils,
        "jokes": n_jokes,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _joke_to_dict(joke: Joke) -> dict:
    return {
        "id": joke.id,
        "file_id": joke.file_id,
        "prompt_responses": joke.prompt_responses,
        "joke_text": joke.joke_text,
        "user_reaction": joke.user_reaction,
        "score": joke.score,
        "category": joke.category,
        "metadata": joke.joke_metadata,
        "user_context": joke.user_context,
        "attribution": joke.attribution,
        "provenance": joke.provenance,
        "set_id": joke.set_id,
    }
