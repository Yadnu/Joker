"""004 add api_key to accounts.

Revision ID: 004
Revises: 003
Create Date: 2026-09-01

Adds the api_key column to accounts.  Existing rows get a generated UUID
so the column can be made non-null without a default on the DB side.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add nullable first so existing rows are valid, then backfill, then constrain.
    op.add_column("accounts", sa.Column("api_key", sa.String(), nullable=True))
    op.execute("UPDATE accounts SET api_key = gen_random_uuid()::text WHERE api_key IS NULL")
    op.alter_column("accounts", "api_key", nullable=False)


def downgrade() -> None:
    op.drop_column("accounts", "api_key")
