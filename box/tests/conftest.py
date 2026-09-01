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

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set DATABASE_URL before any project imports so shared/db.py doesn't raise.
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://jokebox:jokebox@localhost:5432/jokebox_test",
    ),
)

from box.main import app  # noqa: E402
from box.schema.models import Base  # noqa: E402
import shared.db as _db_module  # noqa: E402

# ---------------------------------------------------------------------------
# Test database URL
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://jokebox:jokebox@localhost:5432/jokebox_test",
)

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
    """AsyncClient that uses the test DB session factory."""
    original_factory = _db_module.SessionFactory
    _db_module.SessionFactory = test_session_factory  # type: ignore[assignment]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    _db_module.SessionFactory = original_factory  # type: ignore[assignment]
