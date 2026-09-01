"""002 add accounts table and account_id on jokes.

Revision ID: 002
Revises: 001
Create Date: 2026-09-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_account_name"),
    )
    op.add_column(
        "jokes",
        sa.Column(
            "account_id",
            sa.String(),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_jokes_account_id", "jokes", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_jokes_account_id", table_name="jokes")
    op.drop_column("jokes", "account_id")
    op.drop_table("accounts")
