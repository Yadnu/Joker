"""SQLAlchemy async engine and session factory.

DATABASE_URL must be set in the environment (or .env loaded before import).
Example: postgresql+asyncpg://user:pass@localhost/jokebox
"""

from __future__ import annotations

import os
import re

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _normalize_db_url(url: str) -> str:
    """Convert a Neon/psycopg connection string to asyncpg-compatible form."""
    url = url.strip().strip('"').strip("'")
    url = re.sub(r"^postgres(ql)?://", "postgresql+asyncpg://", url)
    url = re.sub(r"sslmode=require", "ssl=require", url)
    url = re.sub(r"[&?]channel_binding=[^&]*", "", url)
    url = re.sub(r"[?&]$", "", url)
    return url


def _make_engine():
    url = _normalize_db_url(os.environ.get("DATABASE_URL", ""))
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Set it before using the database."
        )
    # When using Neon's PgBouncer pooler (transaction mode), prepared statements
    # must be disabled.  The connect_args below are a no-op against a direct
    # connection or a local PostgreSQL instance.
    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        connect_args={"prepared_statement_cache_size": 0},
    )


def _make_factory():
    return async_sessionmaker(
        _make_engine(),
        expire_on_commit=False,
        class_=AsyncSession,
    )


# Module-level factory; tests replace this attribute directly.
SessionFactory: async_sessionmaker[AsyncSession] = None  # type: ignore[assignment]


def _get_factory() -> async_sessionmaker[AsyncSession]:
    global SessionFactory
    if SessionFactory is None:
        SessionFactory = _make_factory()
    return SessionFactory


def session_maker():
    """Return the process-wide async_sessionmaker, creating it on first use."""
    return _get_factory()


async def get_session() -> AsyncSession:
    """Yield a session suitable for use as a FastAPI dependency."""
    async with _get_factory()() as session:
        yield session
