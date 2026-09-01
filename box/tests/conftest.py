"""Shared pytest fixtures for Box API tests.

Session-scoped: one real PostgreSQL schema created before any test in the
session, torn down after.  Every test function runs inside a transaction
that is rolled back so tests are isolated without DDL overhead per test.

DATABASE_URL is read from the environment; if not set, it defaults to the
local Docker container started for CI.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Load .env from the project root so credentials are available
# whether pytest is run from the shell or from an IDE.
load_dotenv(Path(__file__).parents[2] / ".env", override=True)


def _normalize_db_url(url: str) -> str:
    """Convert a Neon/psycopg connection string to asyncpg-compatible form."""
    url = url.strip().strip('"').strip("'")
    # Ensure asyncpg dialect
    url = re.sub(r"^postgres(ql)?://", "postgresql+asyncpg://", url)
    # asyncpg uses ssl=require, not sslmode=require
    url = re.sub(r"sslmode=require", "ssl=require", url)
    # asyncpg does not understand channel_binding
    url = re.sub(r"[&?]channel_binding=[^&]*", "", url)
    # Tidy trailing punctuation
    url = re.sub(r"[?&]$", "", url)
    return url


# Prefer TEST_DATABASE_URL; fall back to DATABASE_URL; last resort local PG.
_test_url = _normalize_db_url(
    os.environ.get("TEST_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql+asyncpg://jokebox:jokebox@localhost:5432/jokebox_test"
)

# Set DATABASE_URL before any project imports so shared/db.py doesn't raise.
os.environ["DATABASE_URL"] = _test_url
os.environ["TEST_DATABASE_URL"] = _test_url

from box.main import app  # noqa: E402
from box.schema.models import Base  # noqa: E402
import shared.db as _db_module  # noqa: E402
import uuid  # noqa: E402

# ---------------------------------------------------------------------------
# Test database URL
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = _test_url

# ---------------------------------------------------------------------------
# Session-scoped engine: create schema once, drop after the whole session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for the whole test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def test_session_factory(test_engine):
    factory = async_sessionmaker(
        test_engine, expire_on_commit=False, class_=AsyncSession
    )
    return factory


# ---------------------------------------------------------------------------
# Function-scoped session: each test gets a fresh transaction, rolled back
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(test_session_factory) -> AsyncSession:
    async with test_session_factory() as session:
        async with session.begin():
            yield session
            await session.rollback()


# ---------------------------------------------------------------------------
# HTTP client wired to the test database session
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(test_session_factory) -> AsyncClient:
    """AsyncClient wired to the test DB, pre-authenticated with a fresh account.

    Each test gets its own account (unique name) so that bearer-required routes
    work out of the box without any per-test boilerplate.  Tests that need a
    second account can POST /accounts and pass the returned key as a per-request
    Authorization header override.
    """
    original_factory = _db_module.SessionFactory
    _db_module.SessionFactory = test_session_factory  # type: ignore[assignment]

    # Create a bootstrap account using a plain (unauthenticated) client.
    # POST /accounts is intentionally open so accounts can be created without
    # a prior key (bootstrapping).
    unique_name = f"__fixture_{uuid.uuid4().hex[:12]}__"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as bootstrap:
        r = await bootstrap.post("/accounts", json={"name": unique_name})
        assert r.status_code == 201, f"fixture account creation failed: {r.text}"
        api_key = r.json()["api_key"]

    # Main client includes the bearer header on every request.
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {api_key}"},
    ) as ac:
        yield ac

    _db_module.SessionFactory = original_factory  # type: ignore[assignment]
