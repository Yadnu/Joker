"""Box HTTP API — FastAPI router.

Endpoints:
  GET  /health
  POST /accounts
  GET  /accounts
  GET  /accounts/{account_id}
  PUT  /box/upsert
  GET  /box
  GET  /box/{cabinet}/{drawer}/{file}
  GET  /cabinets
  GET  /cabinets/{cabinet_id}
  GET  /cabinets/{cabinet_id}/counts
  GET  /drawers
  GET  /drawers/{drawer_id}
  GET  /drawers/{drawer_id}/counts
  GET  /files/{file_id}
  GET  /files/{file_id}/counts
  GET  /jokes/{joke_id}
  GET  /jokes/{joke_id}/trace
  GET  /genres/{genre}/funniest
  GET  /export
  GET  /compliance
  GET  /counts

Classification intelligence lives in the Librarian, not here.
The Box stores what it is handed; it does not infer, default, or repair paths.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.models import Account, Cabinet, Drawer, File, Joke, Trace
from box.schema.records import JokeRecord
from box.schema.responses import (
    AccountCreateOut,
    AccountListOut,
    AccountOut,
    CabinetCountsOut,
    CabinetDetailOut,
    CabinetListOut,
    ComplianceOut,
    DrawerCountsOut,
    DrawerDetailOut,
    DrawerListOut,
    ExportOut,
    FileCountsOut,
    FileDetailOut,
    FunniestOut,
    GlobalCountsOut,
    HealthOut,
    JokeOut,
    PathReadOut,
    TraceOut,
    TreeOut,
    UpsertOut,
)
from shared.db import get_session

router = APIRouter()


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------

def _level_error(level: str, reason: str, status: int = 404) -> HTTPException:
    return HTTPException(status_code=status, detail={"level": level, "reason": reason})


# ---------------------------------------------------------------------------
# Authentication — Bearer key dependency
# ---------------------------------------------------------------------------

def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def require_account(
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
) -> Account:
    """Resolve an Authorization: Bearer <key> header to an Account.

    Applied to every write route.  Read routes remain open.
    Returns 401 with a body stating the reason if the header is absent or
    the key does not match any account.
    """
    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail={"reason": "Missing Authorization header. Supply 'Authorization: Bearer <key>'."},
        )
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"reason": "Authorization header must use the 'Bearer <key>' scheme."},
        )
    raw_key = authorization.removeprefix("Bearer ").strip()
    key_hash = _hash_key(raw_key)
    acct = (
        await session.execute(select(Account).where(Account.api_key_hash == key_hash))
    ).scalar_one_or_none()
    if acct is None:
        raise HTTPException(
            status_code=401,
            detail={"reason": "Invalid or unknown API key."},
        )
    return acct


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    return HealthOut(status="ok")


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class AccountCreate(BaseModel):
    name: str


@router.post("/accounts", status_code=201, response_model=AccountCreateOut)
async def create_account(
    body: AccountCreate,
    session: AsyncSession = Depends(get_session),
) -> AccountCreateOut:
    """Register a new account.

    Returns the plaintext API key exactly once in the response.
    The key is not stored; only its sha256 hash is kept.
    """
    existing = (
        await session.execute(select(Account).where(Account.name == body.name))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"reason": f"Account '{body.name}' already exists."},
        )
    raw_key = "jbx_" + secrets.token_urlsafe(32)
    acct = Account(name=body.name, api_key_hash=_hash_key(raw_key))
    session.add(acct)
    await session.commit()
    return AccountCreateOut(
        id=acct.id, name=acct.name, api_key=raw_key, created_at=acct.created_at
    )


@router.get("/accounts", response_model=AccountListOut)
async def list_accounts(session: AsyncSession = Depends(get_session)) -> AccountListOut:
    rows = (await session.execute(select(Account))).scalars().all()
    return AccountListOut(
        accounts=[AccountOut(id=r.id, name=r.name, created_at=r.created_at) for r in rows]
    )


@router.get("/accounts/{account_id}", response_model=AccountOut)
async def get_account(
    account_id: str, session: AsyncSession = Depends(get_session)
) -> AccountOut:
    acct = (
        await session.execute(select(Account).where(Account.id == account_id))
    ).scalar_one_or_none()
    if acct is None:
        raise HTTPException(
            status_code=404,
            detail={"level": "account", "reason": f"Account '{account_id}' not found."},
        )
    return AccountOut(id=acct.id, name=acct.name, created_at=acct.created_at)


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

class UpsertRequest(BaseModel):
    cabinet: str
    drawer: str
    file: str
    joke: JokeRecord
    # account_id is intentionally absent: attribution comes from the bearer
    # token resolved by require_account, not from the request body.


@router.put("/box/upsert", status_code=201, response_model=UpsertOut)
async def upsert(
    body: UpsertRequest,
    account: Account = Depends(require_account),
    session: AsyncSession = Depends(get_session),
) -> UpsertOut:
    """File a joke into the path the caller supplies.

    Creates cabinet, drawer, and file if they do not exist.
    Uses ON CONFLICT DO NOTHING so concurrent writes are safe.
    The whole operation runs in a single transaction.
    """
    now = datetime.now(timezone.utc)

    # Cabinet
    await session.execute(
        pg_insert(Cabinet.__table__)
        .values(id=str(uuid.uuid4()), label=body.cabinet, created_at=now)
        .on_conflict_do_nothing(index_elements=["label"])
    )
    cab = (
        await session.execute(select(Cabinet).where(Cabinet.label == body.cabinet))
    ).scalar_one_or_none()
    if cab is None:
        raise _level_error("cabinet", f"Cabinet '{body.cabinet}' could not be created.", 500)

    # Drawer
    await session.execute(
        pg_insert(Drawer.__table__)
        .values(id=str(uuid.uuid4()), label=body.drawer, cabinet_id=cab.id, created_at=now)
        .on_conflict_do_nothing(index_elements=["cabinet_id", "label"])
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
        pg_insert(File.__table__)
        .values(id=str(uuid.uuid4()), label=body.file, drawer_id=drw.id, created_at=now)
        .on_conflict_do_nothing(index_elements=["drawer_id", "label"])
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
    # Attribution: joker comes from the request body; account is always
    # resolved from the bearer token so it cannot be spoofed.
    attribution = record.attribution.model_dump()
    attribution["account"] = account.name
    joke = Joke(
        id=joke_id,
        file_id=fil.id,
        account_id=account.id,          # from bearer, never from body
        prompt_responses=[t.model_dump() for t in record.prompt_responses],
        joke_text=record.joke_text,
        user_reaction=record.user_reaction,
        score=record.score,
        category=record.category,
        joke_metadata=record.metadata.model_dump(mode="json"),
        user_context=record.user_context.model_dump(mode="json"),
        attribution=attribution,        # account field overridden above
        provenance=record.provenance.model_dump(),
        set_id=record.set_id.model_dump(),
        created_at=now,
    )
    session.add(joke)
    await session.commit()

    return UpsertOut(
        joke_id=joke_id,
        cabinet_id=cab.id,
        drawer_id=drw.id,
        file_id=fil.id,
    )


# ---------------------------------------------------------------------------
# Hierarchy reads — tree
# ---------------------------------------------------------------------------

@router.get("/box", response_model=TreeOut)
async def get_box(session: AsyncSession = Depends(get_session)) -> TreeOut:
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
                joke_count = (
                    await session.execute(
                        select(func.count()).select_from(Joke).where(Joke.file_id == fil.id)
                    )
                ).scalar() or 0
                files.append({"id": fil.id, "label": fil.label, "joke_count": joke_count})
            drawers.append({"id": drw.id, "label": drw.label, "files": files})
        result.append({"id": cab.id, "label": cab.label, "drawers": drawers})
    return TreeOut.model_validate({"cabinets": result})


# ---------------------------------------------------------------------------
# Hierarchy reads — cabinets
# ---------------------------------------------------------------------------

@router.get("/cabinets", response_model=CabinetListOut)
async def list_cabinets(session: AsyncSession = Depends(get_session)) -> CabinetListOut:
    rows = (await session.execute(select(Cabinet))).scalars().all()
    return CabinetListOut(cabinets=[{"id": r.id, "label": r.label} for r in rows])


@router.get("/cabinets/{cabinet_id}", response_model=CabinetDetailOut)
async def get_cabinet(
    cabinet_id: str, session: AsyncSession = Depends(get_session)
) -> CabinetDetailOut:
    cab = (
        await session.execute(select(Cabinet).where(Cabinet.id == cabinet_id))
    ).scalar_one_or_none()
    if cab is None:
        raise _level_error("cabinet", f"Cabinet '{cabinet_id}' not found.")
    drawers = (
        await session.execute(select(Drawer).where(Drawer.cabinet_id == cab.id))
    ).scalars().all()
    return CabinetDetailOut(
        id=cab.id,
        label=cab.label,
        drawers=[{"id": d.id, "label": d.label} for d in drawers],
    )


@router.get("/cabinets/{cabinet_id}/counts", response_model=CabinetCountsOut)
async def cabinet_counts(
    cabinet_id: str, session: AsyncSession = Depends(get_session)
) -> CabinetCountsOut:
    """Count of drawers, files, and jokes under a cabinet."""
    cab = (
        await session.execute(select(Cabinet).where(Cabinet.id == cabinet_id))
    ).scalar_one_or_none()
    if cab is None:
        raise _level_error("cabinet", f"Cabinet '{cabinet_id}' not found.")
    n_drw = (
        await session.execute(
            select(func.count()).select_from(Drawer).where(Drawer.cabinet_id == cabinet_id)
        )
    ).scalar() or 0
    drw_ids = (
        await session.execute(select(Drawer.id).where(Drawer.cabinet_id == cabinet_id))
    ).scalars().all()
    n_fil = (
        await session.execute(
            select(func.count()).select_from(File).where(File.drawer_id.in_(drw_ids))
        )
    ).scalar() or 0
    fil_ids = (
        await session.execute(select(File.id).where(File.drawer_id.in_(drw_ids)))
    ).scalars().all()
    n_jokes = (
        await session.execute(
            select(func.count()).select_from(Joke).where(Joke.file_id.in_(fil_ids))
        )
    ).scalar() or 0
    return CabinetCountsOut(
        cabinet_id=cabinet_id, drawers=n_drw, files=n_fil, jokes=n_jokes
    )


# ---------------------------------------------------------------------------
# Hierarchy reads — drawers
# ---------------------------------------------------------------------------

@router.get("/drawers", response_model=DrawerListOut)
async def list_drawers(session: AsyncSession = Depends(get_session)) -> DrawerListOut:
    """List all drawers across all cabinets."""
    rows = (await session.execute(select(Drawer))).scalars().all()
    return DrawerListOut(
        drawers=[{"id": r.id, "label": r.label, "cabinet_id": r.cabinet_id} for r in rows]
    )


@router.get("/drawers/{drawer_id}", response_model=DrawerDetailOut)
async def get_drawer(
    drawer_id: str, session: AsyncSession = Depends(get_session)
) -> DrawerDetailOut:
    drw = (
        await session.execute(select(Drawer).where(Drawer.id == drawer_id))
    ).scalar_one_or_none()
    if drw is None:
        raise _level_error("drawer", f"Drawer '{drawer_id}' not found.")
    files = (
        await session.execute(select(File).where(File.drawer_id == drw.id))
    ).scalars().all()
    return DrawerDetailOut(
        id=drw.id,
        label=drw.label,
        cabinet_id=drw.cabinet_id,
        files=[{"id": f.id, "label": f.label} for f in files],
    )


@router.get("/drawers/{drawer_id}/counts", response_model=DrawerCountsOut)
async def drawer_counts(
    drawer_id: str, session: AsyncSession = Depends(get_session)
) -> DrawerCountsOut:
    """Count of files and jokes under a drawer."""
    drw = (
        await session.execute(select(Drawer).where(Drawer.id == drawer_id))
    ).scalar_one_or_none()
    if drw is None:
        raise _level_error("drawer", f"Drawer '{drawer_id}' not found.")
    n_fil = (
        await session.execute(
            select(func.count()).select_from(File).where(File.drawer_id == drawer_id)
        )
    ).scalar() or 0
    fil_ids = (
        await session.execute(select(File.id).where(File.drawer_id == drawer_id))
    ).scalars().all()
    n_jokes = (
        await session.execute(
            select(func.count()).select_from(Joke).where(Joke.file_id.in_(fil_ids))
        )
    ).scalar() or 0
    return DrawerCountsOut(drawer_id=drawer_id, files=n_fil, jokes=n_jokes)


# ---------------------------------------------------------------------------
# Hierarchy reads — files
# ---------------------------------------------------------------------------

@router.get("/files/{file_id}", response_model=FileDetailOut)
async def get_file(
    file_id: str, session: AsyncSession = Depends(get_session)
) -> FileDetailOut:
    fil = (
        await session.execute(select(File).where(File.id == file_id))
    ).scalar_one_or_none()
    if fil is None:
        raise _level_error("file", f"File '{file_id}' not found.")
    jokes = (
        await session.execute(select(Joke).where(Joke.file_id == fil.id))
    ).scalars().all()
    return FileDetailOut(
        id=fil.id,
        label=fil.label,
        drawer_id=fil.drawer_id,
        jokes=[{"id": j.id, "score": j.score} for j in jokes],
    )


@router.get("/files/{file_id}/counts", response_model=FileCountsOut)
async def file_counts(
    file_id: str, session: AsyncSession = Depends(get_session)
) -> FileCountsOut:
    """Count of jokes in a file."""
    fil = (
        await session.execute(select(File).where(File.id == file_id))
    ).scalar_one_or_none()
    if fil is None:
        raise _level_error("file", f"File '{file_id}' not found.")
    n_jokes = (
        await session.execute(
            select(func.count()).select_from(Joke).where(Joke.file_id == file_id)
        )
    ).scalar() or 0
    return FileCountsOut(file_id=file_id, jokes=n_jokes)


# ---------------------------------------------------------------------------
# Jokes
# ---------------------------------------------------------------------------

@router.get("/jokes/{joke_id}", response_model=JokeOut)
async def get_joke(
    joke_id: str, session: AsyncSession = Depends(get_session)
) -> JokeOut:
    joke = (
        await session.execute(select(Joke).where(Joke.id == joke_id))
    ).scalar_one_or_none()
    if joke is None:
        raise _level_error("joke", f"Joke '{joke_id}' not found.")
    return JokeOut.model_validate(_joke_to_dict(joke))


@router.get("/jokes/{joke_id}/trace", response_model=TraceOut)
async def get_joke_trace(
    joke_id: str, session: AsyncSession = Depends(get_session)
) -> TraceOut:
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
    return TraceOut(
        joke_id=joke_id,
        steps=[
            {
                "id": t.id,
                "kind": t.kind,
                "actor": t.actor,
                "rationale": t.rationale,
                "latency_ms": t.latency_ms,
            }
            for t in traces
        ],
    )


# ---------------------------------------------------------------------------
# Path read
# ---------------------------------------------------------------------------

@router.get("/box/{cabinet}/{drawer}/{file}", response_model=PathReadOut)
async def read_by_path(
    cabinet: str,
    drawer: str,
    file: str,
    session: AsyncSession = Depends(get_session),
) -> PathReadOut:
    """Return all jokes at a specific cabinet/drawer/file path."""
    cab = (
        await session.execute(select(Cabinet).where(Cabinet.label == cabinet))
    ).scalar_one_or_none()
    if cab is None:
        raise _level_error("cabinet", f"Cabinet '{cabinet}' not found.")
    drw = (
        await session.execute(
            select(Drawer).where(Drawer.cabinet_id == cab.id, Drawer.label == drawer)
        )
    ).scalar_one_or_none()
    if drw is None:
        raise _level_error("drawer", f"Drawer '{drawer}' not found.")
    fil = (
        await session.execute(
            select(File).where(File.drawer_id == drw.id, File.label == file)
        )
    ).scalar_one_or_none()
    if fil is None:
        raise _level_error("file", f"File '{file}' not found.")
    jokes = (
        await session.execute(select(Joke).where(Joke.file_id == fil.id))
    ).scalars().all()
    return PathReadOut.model_validate({
        "cabinet": {"id": cab.id, "label": cab.label},
        "drawer": {"id": drw.id, "label": drw.label},
        "file": {"id": fil.id, "label": fil.label},
        "jokes": [_joke_to_dict(j) for j in jokes],
    })


# ---------------------------------------------------------------------------
# Funniest in genre
# ---------------------------------------------------------------------------

@router.get("/genres/{genre}/funniest", response_model=FunniestOut)
async def funniest_in_genre(
    genre: str,
    n: int = Query(default=5, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> FunniestOut:
    """Return up to n highest-scoring jokes in the given genre (category)."""
    jokes = (
        await session.execute(
            select(Joke)
            .where(Joke.category == genre)
            .order_by(Joke.score.desc())
            .limit(n)
        )
    ).scalars().all()
    return FunniestOut.model_validate(
        {"genre": genre, "jokes": [_joke_to_dict(j) for j in jokes]}
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.get("/export", response_model=ExportOut)
async def export(session: AsyncSession = Depends(get_session)) -> ExportOut:
    """Full library export: every cabinet, drawer, file, and joke as JSON."""
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
                    "jokes": [_joke_to_dict(j) for j in jokes],
                })
            drawers.append({"id": drw.id, "label": drw.label, "files": files})
        result.append({"id": cab.id, "label": cab.label, "drawers": drawers})
    return ExportOut.model_validate({"cabinets": result})


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------

@router.get("/compliance", response_model=ComplianceOut)
async def compliance(session: AsyncSession = Depends(get_session)) -> ComplianceOut:
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
            select(
                Drawer.id,
                Drawer.label,
                Cabinet.label.label("cab_label"),
                func.count(File.id).label("n"),
            )
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

    return ComplianceOut.model_validate(
        {"compliant": len(violations) == 0, "violations": violations}
    )


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------

@router.get("/counts", response_model=GlobalCountsOut)
async def counts(session: AsyncSession = Depends(get_session)) -> GlobalCountsOut:
    n_cabs = (await session.execute(select(func.count()).select_from(Cabinet))).scalar() or 0
    n_drws = (await session.execute(select(func.count()).select_from(Drawer))).scalar() or 0
    n_fils = (await session.execute(select(func.count()).select_from(File))).scalar() or 0
    n_jokes = (await session.execute(select(func.count()).select_from(Joke))).scalar() or 0
    return GlobalCountsOut(cabinets=n_cabs, drawers=n_drws, files=n_fils, jokes=n_jokes)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _joke_to_dict(joke: Joke) -> dict:
    return {
        "id": joke.id,
        "file_id": joke.file_id,
        "account_id": joke.account_id,
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
