"""Single Box I/O module.

Every read and write to the Box goes through this file. BOX_BASE_URL is the
swap point when the winning Box is announced. Callers pass an AsyncSession
when they already share the Box process (Librarian tests, in-process reads);
otherwise this module uses HTTP against BOX_BASE_URL.
"""

from __future__ import annotations

import os
import time

import httpx
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.models import Cabinet, Drawer, File, Joke
from box.schema.records import JokeMetadata, JokeRecord
from shared.trace import record_step

BOX_BASE_URL = os.environ.get("BOX_BASE_URL", "http://localhost:8000")


def _client_factory() -> httpx.AsyncClient:
    """Build the AsyncClient used for Box HTTP calls.

    Tests monkeypatch this attribute to inject an httpx.MockTransport.
    """
    return httpx.AsyncClient(
        base_url=os.environ.get("BOX_BASE_URL", BOX_BASE_URL),
        timeout=120.0,
    )


async def http_post(path: str, payload: dict) -> httpx.Response:
    async with _client_factory() as client:
        return await client.post(path, json=payload)


async def http_put(path: str, payload: dict, api_key: str) -> httpx.Response:
    async with _client_factory() as client:
        return await client.put(
            path,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )


def _api_key(explicit: str | None) -> str:
    return explicit if explicit is not None else os.environ.get("BOX_API_KEY", "")


def _use_http() -> bool:
    """HTTP is the production path. SQL is used only when a session is given
    AND BOX_TRANSPORT is not forced to http (tests / in-process Librarian)."""
    return os.environ.get("BOX_TRANSPORT", "").lower() == "http"


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


async def upsert_joke(
    *,
    cabinet: str,
    drawer: str,
    file: str,
    record: JokeRecord,
    session: AsyncSession | None = None,
    api_key: str | None = None,
) -> dict:
    """Call PUT /box/upsert with the given path and joke record."""
    key = _api_key(api_key)
    payload = {
        "cabinet": cabinet,
        "drawer": drawer,
        "file": file,
        "joke": record.model_dump(mode="json"),
    }

    t0 = time.monotonic()
    async with _client_factory() as client:
        response = await client.put(
            "/box/upsert",
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
        )
    latency_ms = int((time.monotonic() - t0) * 1000)

    response.raise_for_status()
    result = response.json()

    if session is not None:
        await record_step(
            artifact_id=result["joke_id"],
            artifact_type="joke",
            kind="filing",
            actor="joker.box_client",
            model=None,
            prompt_ref=None,
            inputs={"cabinet": cabinet, "drawer": drawer, "file": file},
            output=result,
            rationale=(
                f"PUT /box/upsert succeeded for path '{cabinet}/{drawer}/{file}'; "
                f"joke filed as {result['joke_id']} in a single transaction "
                "across cabinet, drawer, file, and joke rows."
            ),
            latency_ms=latency_ms,
            cost=None,
            session=session,
        )

    return result


async def update_joke_landing(
    *,
    joke_id: str,
    user_reaction: str,
    score: int,
    category: str,
    metadata: JokeMetadata,
    session: AsyncSession | None = None,
    api_key: str | None = None,
) -> dict:
    """Update score and reaction on a joke already filed at tell-time."""
    key = _api_key(api_key)
    payload = {
        "user_reaction": user_reaction,
        "score": score,
        "category": category,
        "metadata": metadata.model_dump(mode="json"),
    }
    t0 = time.monotonic()
    async with _client_factory() as client:
        response = await client.put(
            f"/jokes/{joke_id}",
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
        )
    latency_ms = int((time.monotonic() - t0) * 1000)
    response.raise_for_status()
    result = response.json()
    if session is not None:
        await record_step(
            artifact_id=joke_id,
            artifact_type="joke",
            kind="filing",
            actor="joker.box_client",
            model=None,
            prompt_ref=None,
            inputs={"joke_id": joke_id, "score": score},
            output={"joke_id": joke_id, "score": score},
            rationale=(
                f"Updated landing on already-filed joke {joke_id}: "
                f"score {score}/10, reaction captured."
            ),
            latency_ms=latency_ms,
            cost=None,
            session=session,
        )
    return result


# ---------------------------------------------------------------------------
# Reads — HTTP or SQL, one function each
# ---------------------------------------------------------------------------


async def funniest_in_genre(
    genre: str,
    n: int = 3,
    *,
    session: AsyncSession | None = None,
    api_key: str | None = None,
) -> list[dict]:
    """Top-N jokes by score for a genre."""
    if session is not None and not _use_http():
        stmt = (
            select(Joke.id, Joke.joke_text, Joke.score, Joke.category)
            .where(Joke.category == genre)
            .order_by(desc(Joke.score))
            .limit(max(1, n))
        )
        rows = (await session.execute(stmt)).all()
        return [
            {"id": r.id, "joke_text": r.joke_text, "score": r.score, "category": r.category}
            for r in rows
        ]

    async with _client_factory() as client:
        response = await client.get(
            f"/genres/{genre}/funniest",
            params={"n": n},
            headers={"Authorization": f"Bearer {_api_key(api_key)}"},
        )
    response.raise_for_status()
    body = response.json()
    return [
        {
            "id": j["id"],
            "joke_text": j["joke_text"],
            "score": j["score"],
            "category": j["category"],
        }
        for j in body.get("jokes", [])
    ]


async def high_scorers(
    *,
    n: int = 20,
    min_score: int = 7,
    session: AsyncSession | None = None,
    api_key: str | None = None,
) -> list:
    """High-scoring jokes for Librarian.suggest.

    SQL path returns Row objects with .category/.joke_text/.score so existing
    prompt formatting keeps working. HTTP path returns simple namespaces.
    """
    if session is not None and not _use_http():
        result = await session.execute(
            select(Joke.category, Joke.joke_text, Joke.score)
            .where(Joke.score >= min_score)
            .order_by(Joke.score.desc())
            .limit(n)
        )
        return result.all()

    async with _client_factory() as client:
        response = await client.get(
            "/jokes/top",
            params={"n": n, "min_score": min_score},
            headers={"Authorization": f"Bearer {_api_key(api_key)}"},
        )
    response.raise_for_status()
    jokes = response.json().get("jokes", [])
    return [
        type("Row", (), {"category": j["category"], "joke_text": j["joke_text"], "score": j["score"]})()
        for j in jokes
    ]


async def genre_coverage(
    *,
    session: AsyncSession | None = None,
    api_key: str | None = None,
) -> dict[str, int]:
    """Joke counts per category."""
    if session is not None and not _use_http():
        result = await session.execute(
            select(Joke.category, func.count(Joke.id).label("n")).group_by(Joke.category)
        )
        return {row.category: row.n for row in result.all()}

    async with _client_factory() as client:
        response = await client.get(
            "/genres/coverage",
            headers={"Authorization": f"Bearer {_api_key(api_key)}"},
        )
    response.raise_for_status()
    return {k: int(v) for k, v in response.json().get("coverage", {}).items()}


async def taxonomy(
    *,
    session: AsyncSession | None = None,
    api_key: str | None = None,
) -> list[dict]:
    """Cabinet > drawer > file snapshot for Librarian.classify."""
    if session is not None and not _use_http():
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

    async with _client_factory() as client:
        response = await client.get(
            "/box",
            headers={"Authorization": f"Bearer {_api_key(api_key)}"},
        )
    response.raise_for_status()
    out: list[dict] = []
    for cab in response.json().get("cabinets", []):
        for drw in cab.get("drawers", []):
            for fil in drw.get("files", []):
                out.append(
                    {
                        "cabinet": cab["label"],
                        "drawer": drw["label"],
                        "file": fil["label"],
                        "file_id": fil["id"],
                    }
                )
    return out


async def search_jokes(
    query: str,
    *,
    session: AsyncSession | None = None,
) -> list[dict]:
    if session is None or _use_http():
        return []
    stmt = (
        select(Joke.id, Joke.joke_text, Joke.score, Joke.category)
        .where(Joke.joke_text.ilike(f"%{query}%"))
        .order_by(desc(Joke.score))
        .limit(10)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {"id": r.id, "joke_text": r.joke_text, "score": r.score, "category": r.category}
        for r in rows
    ]


async def recent_scores(
    n: int = 5,
    *,
    session: AsyncSession | None = None,
) -> list[int]:
    if session is None or _use_http():
        return []
    stmt = select(Joke.score).order_by(desc(Joke.created_at)).limit(max(1, n))
    return list((await session.execute(stmt)).scalars().all())
