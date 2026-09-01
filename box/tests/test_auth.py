"""test_auth.py

Authorization: Bearer <key> enforcement on write routes.

Tests:
  - PUT /box/upsert with no Authorization header returns 401 naming the reason
  - PUT /box/upsert with an invalid key returns 401
  - PUT /box/upsert with a valid key returns 201
  - Stored joke attribution.account matches the key's account, not the body value
  - Read routes (GET /jokes/{id}) require no key
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from box.tests.helpers import joke_payload


# ---------------------------------------------------------------------------
# Helpers: a plain unauthenticated client
# ---------------------------------------------------------------------------

@pytest.fixture
async def raw_client(test_session_factory):
    """Client with no default Authorization header."""
    import shared.db as _db_module
    from box.main import app

    original = _db_module.SessionFactory
    _db_module.SessionFactory = test_session_factory  # type: ignore[assignment]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    _db_module.SessionFactory = original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_without_key_returns_401(raw_client):
    """No Authorization header → 401 with a reason body."""
    p = joke_payload(cabinet="AuthCab", drawer="AuthDrw", file="AuthFile")
    r = await raw_client.put("/box/upsert", json=p)
    assert r.status_code == 401
    detail = r.json().get("detail", {})
    assert "reason" in detail
    assert "Authorization" in detail["reason"] or "Missing" in detail["reason"]


@pytest.mark.asyncio
async def test_upsert_with_invalid_key_returns_401(raw_client):
    """A well-formed but unknown Bearer key → 401."""
    p = joke_payload(cabinet="AuthCab", drawer="AuthDrw", file="AuthFile")
    r = await raw_client.put(
        "/box/upsert", json=p,
        headers={"Authorization": "Bearer jbx_thiskeyisnotregistered"},
    )
    assert r.status_code == 401
    detail = r.json().get("detail", {})
    assert "reason" in detail
    assert "Invalid" in detail["reason"] or "unknown" in detail["reason"]


@pytest.mark.asyncio
async def test_upsert_with_valid_key_returns_201(raw_client):
    """A registered key is accepted and the joke is stored."""
    # Create account first (POST /accounts is open — no key required).
    r_acct = await raw_client.post("/accounts", json={"name": "Auth-ValidKey"})
    assert r_acct.status_code == 201
    api_key = r_acct.json()["api_key"]

    p = joke_payload(cabinet="AuthCab", drawer="AuthDrw", file="AuthFile")
    r = await raw_client.put(
        "/box/upsert", json=p,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_attribution_account_comes_from_bearer_not_body(raw_client):
    """attribution.account on the stored joke matches the bearer key's account,
    regardless of what the request body says in attribution.account."""
    r_acct = await raw_client.post("/accounts", json={"name": "Auth-Attribution"})
    assert r_acct.status_code == 201
    real_account_name = r_acct.json()["name"]
    acct_id = r_acct.json()["id"]
    api_key = r_acct.json()["api_key"]

    p = joke_payload(cabinet="AuthCab2", drawer="AuthDrw2", file="AuthFile2")
    # Body says a different account name in attribution — must be overridden.
    p["joke"]["attribution"]["account"] = "spoofed-account-name"

    r = await raw_client.put(
        "/box/upsert", json=p,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert r.status_code == 201, r.text
    joke_id = r.json()["joke_id"]

    r_joke = await raw_client.get(f"/jokes/{joke_id}")
    assert r_joke.status_code == 200
    body = r_joke.json()

    # attribution.account must be the bearer account's name, not the spoofed value
    assert body["attribution"]["account"] == real_account_name
    assert body["attribution"]["account"] != "spoofed-account-name"
    # account_id FK matches the bearer account
    assert body["account_id"] == acct_id


@pytest.mark.asyncio
async def test_read_routes_require_no_key(raw_client):
    """GET routes are open — no Authorization header needed."""
    # A missing joke returns 404, not 401 — confirms reads are unprotected.
    r = await raw_client.get("/jokes/nonexistent-id-for-auth-test")
    assert r.status_code == 404

    r2 = await raw_client.get("/cabinets")
    assert r2.status_code == 200
