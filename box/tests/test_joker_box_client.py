"""joker/box_client.py is the sole HTTP boundary from Joker to the Box.

Uses httpx.MockTransport (no live Box server) by monkeypatching the
module-level `_client_factory`, mirroring the SessionFactory-swap pattern
already used for the DB layer in box/tests/conftest.py.
"""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from box.schema.models import Trace
from box.schema.records import (
    Attribution,
    JokeMetadata,
    JokeRecord,
    PromptTurn,
    Provenance,
    SetId,
    UserContext,
)
from shared import box_client


def _sample_record() -> JokeRecord:
    return JokeRecord(
        prompt_responses=[PromptTurn(role="assistant", content="setup / punch")],
        joke_text="Why did the chicken cross the road? To get to the other bug tracker.",
        user_reaction="Ha.",
        score=7,
        category="Observational",
        metadata=JokeMetadata(
            topic="chickens", style="one-liner", length="short", sensitivity_flags=[]
        ),
        user_context=UserContext(),
        attribution=Attribution(joker="joker-v1", account="acct_test"),
        provenance=Provenance(
            source="generated",
            model="gpt-4o",
            prompt="Tell a joke about chickens.",
            selection_rationale="Best of three candidates.",
        ),
        set_id=SetId(set="set_x", position=1),
    )


def _mock_factory(handler):
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")

    return factory


@pytest.mark.asyncio
async def test_upsert_joke_calls_put_box_upsert_with_correct_payload(db, monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url_path"] = request.url.path
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "joke_id": "joke_abc123",
                "cabinet_id": "cab_1",
                "drawer_id": "drw_1",
                "file_id": "file_1",
            },
        )

    monkeypatch.setattr(box_client, "_client_factory", _mock_factory(handler))

    record = _sample_record()
    result = await box_client.upsert_joke(
        cabinet="Observational",
        drawer="Everyday Life",
        file="Chickens",
        record=record,
        session=db,
        api_key="jbx_testkey",
    )

    assert captured["method"] == "PUT"
    assert captured["url_path"] == "/box/upsert"
    assert captured["auth"] == "Bearer jbx_testkey"
    assert captured["body"]["cabinet"] == "Observational"
    assert captured["body"]["drawer"] == "Everyday Life"
    assert captured["body"]["file"] == "Chickens"
    assert captured["body"]["joke"]["joke_text"] == record.joke_text
    assert result["joke_id"] == "joke_abc123"


@pytest.mark.asyncio
async def test_upsert_joke_emits_filing_trace_on_success(db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "joke_id": "joke_filed_1",
                "cabinet_id": "c",
                "drawer_id": "d",
                "file_id": "f",
            },
        )

    monkeypatch.setattr(box_client, "_client_factory", _mock_factory(handler))

    await box_client.upsert_joke(
        cabinet="Observational",
        drawer="Everyday Life",
        file="Chickens",
        record=_sample_record(),
        session=db,
        api_key="jbx_testkey",
    )

    row = (
        await db.execute(select(Trace).where(Trace.artifact_id == "joke_filed_1"))
    ).scalar_one()
    assert row.kind == "filing"
    assert row.actor == "joker.box_client"
    assert row.output["joke_id"] == "joke_filed_1"


@pytest.mark.asyncio
async def test_upsert_joke_raises_on_http_error_and_does_not_trace(db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"detail": {"reason": "Invalid or unknown API key."}}
        )

    monkeypatch.setattr(box_client, "_client_factory", _mock_factory(handler))

    with pytest.raises(httpx.HTTPStatusError):
        await box_client.upsert_joke(
            cabinet="Observational",
            drawer="Everyday Life",
            file="Chickens",
            record=_sample_record(),
            session=db,
            api_key="bad-key",
        )

    rows = (
        await db.execute(select(Trace).where(Trace.actor == "joker.box_client"))
    ).scalars().all()
    assert rows == []
