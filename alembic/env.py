"""Alembic env.py — async-compatible with SQLAlchemy 2.0."""

from __future__ import annotations

import asyncio
import os
import re
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from box.schema.models import Base

# Load .env so migrations work whether run from an IDE or the shell.
load_dotenv(Path(__file__).parents[1] / ".env", override=True)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _normalize_db_url(url: str) -> str:
    """Convert a Neon/psycopg connection string to asyncpg-compatible form."""
    url = url.strip().strip('"').strip("'")
    url = re.sub(r"^postgres(ql)?://", "postgresql+asyncpg://", url)
    url = re.sub(r"sslmode=require", "ssl=require", url)
    url = re.sub(r"[&?]channel_binding=[^&]*", "", url)
    url = re.sub(r"[?&]$", "", url)
    return url


DATABASE_URL = _normalize_db_url(
    os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url", ""))
)


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
