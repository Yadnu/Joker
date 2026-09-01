"""001 initial schema

Revision ID: 001
Revises:
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cabinets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("label", name="uq_cabinet_label"),
    )

    op.create_table(
        "drawers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("cabinet_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["cabinet_id"], ["cabinets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cabinet_id", "label", name="uq_drawer_cabinet_label"),
    )

    op.create_table(
        "files",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("drawer_id", sa.String(), nullable=False),
        sa.Column("category_justification", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["drawer_id"], ["drawers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("drawer_id", "label", name="uq_file_drawer_label"),
    )

    op.create_table(
        "jokes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("file_id", sa.String(), nullable=False),
        sa.Column("prompt_responses", postgresql.JSONB(), nullable=False),
        sa.Column("joke_text", sa.Text(), nullable=False),
        sa.Column("user_reaction", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("user_context", sa.Text(), nullable=False),
        sa.Column("attribution", postgresql.JSONB(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("set_id", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "traces",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("artifact_id", sa.String(), nullable=False),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("prompt_ref", sa.String(), nullable=True),
        sa.Column("inputs", postgresql.JSONB(), nullable=False),
        sa.Column("output", postgresql.JSONB(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Indexes for common query patterns
    op.create_index("ix_jokes_category", "jokes", ["category"])
    op.create_index("ix_jokes_score", "jokes", ["score"])
    op.create_index("ix_jokes_file_id", "jokes", ["file_id"])
    op.create_index("ix_traces_artifact_id", "traces", ["artifact_id"])
    op.create_index("ix_traces_kind", "traces", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_traces_kind", table_name="traces")
    op.drop_index("ix_traces_artifact_id", table_name="traces")
    op.drop_index("ix_jokes_file_id", table_name="jokes")
    op.drop_index("ix_jokes_score", table_name="jokes")
    op.drop_index("ix_jokes_category", table_name="jokes")
    op.drop_table("traces")
    op.drop_table("jokes")
    op.drop_table("files")
    op.drop_table("drawers")
    op.drop_table("cabinets")
