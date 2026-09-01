"""SQLAlchemy async engine and session factory.

DATABASE_URL must be set in the environment (or .env loaded before import).
Example: postgresql+asyncpg://user:pass@localhost/jokebox
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not _DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Set it before importing shared.db."
    )

engine = create_async_engine(
    _DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session() -> AsyncSession:
    """Yield a session suitable for use as a FastAPI dependency."""
    async with SessionFactory() as session:
        yield session
