"""006 trace turns: nullable trigger and turn grouping on traces.

Revision ID: 006
Revises: 005
Create Date: 2026-09-02

Adds trigger_type, trigger_text, turn_id, and turn_index to traces.
All columns are nullable. Existing rows are not backfilled.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("traces", sa.Column("trigger_type", sa.String(), nullable=True))
    op.add_column("traces", sa.Column("trigger_text", sa.Text(), nullable=True))
    op.add_column("traces", sa.Column("turn_id", sa.String(), nullable=True))
    op.add_column("traces", sa.Column("turn_index", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("traces", "turn_index")
    op.drop_column("traces", "turn_id")
    op.drop_column("traces", "trigger_text")
    op.drop_column("traces", "trigger_type")
