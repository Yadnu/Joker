"""003 enrich user_context: TEXT -> JSONB.

Revision ID: 003
Revises: 002
Create Date: 2026-09-01

Converts the jokes.user_context column from plain TEXT to JSONB so the
structured UserContext Pydantic model can be stored and queried natively.

Existing rows that hold plain text (from before this migration) are wrapped
into {"session_notes": "<original text>"} so their content is preserved and
the column remains non-null.  Rows that already contain valid JSON objects
are cast directly.
"""

from __future__ import annotations

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE jokes
        ALTER COLUMN user_context TYPE JSONB
        USING CASE
            WHEN user_context ~ '^\\s*\\{'
                THEN user_context::jsonb
            ELSE
                jsonb_build_object('session_notes', user_context)
        END
        """
    )


def downgrade() -> None:
    # Restore as TEXT; preserve session_notes string if present, else '{}'.
    op.execute(
        """
        ALTER TABLE jokes
        ALTER COLUMN user_context TYPE TEXT
        USING COALESCE(user_context->>'session_notes', user_context::text)
        """
    )
