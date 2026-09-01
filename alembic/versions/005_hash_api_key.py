"""005 hash api_key: replace plaintext with sha256 hash.

Revision ID: 005
Revises: 004
Create Date: 2026-09-01

Replaces the plaintext api_key column on accounts with api_key_hash
(sha256 hex digest).  Existing rows are backfilled so existing accounts
remain usable if the holder still has their old UUID key.

The plaintext is permanently dropped from the database after backfill.
"""

from __future__ import annotations

import hashlib

import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add the new hash column (nullable while backfilling).
    op.add_column("accounts", sa.Column("api_key_hash", sa.String(), nullable=True))

    # 2. Backfill: hash the existing plaintext values.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, api_key FROM accounts")).fetchall()
    for row_id, api_key in rows:
        h = hashlib.sha256(api_key.encode()).hexdigest()
        bind.execute(
            sa.text("UPDATE accounts SET api_key_hash = :h WHERE id = :id"),
            {"h": h, "id": row_id},
        )

    # 3. Constrain non-null now that every row has a value.
    op.alter_column("accounts", "api_key_hash", nullable=False)

    # 4. Index for fast lookup during Bearer validation.
    op.create_index("ix_accounts_api_key_hash", "accounts", ["api_key_hash"])

    # 5. Drop the plaintext column permanently.
    op.drop_column("accounts", "api_key")


def downgrade() -> None:
    # Restore the column as VARCHAR; we cannot recover plaintext from the hash,
    # so restored rows get a sentinel UUID that will fail validation.
    op.add_column("accounts", sa.Column("api_key", sa.String(), nullable=True))
    bind = op.get_bind()
    import uuid
    rows = bind.execute(sa.text("SELECT id FROM accounts")).fetchall()
    for (row_id,) in rows:
        bind.execute(
            sa.text("UPDATE accounts SET api_key = :v WHERE id = :id"),
            {"v": str(uuid.uuid4()), "id": row_id},
        )
    op.alter_column("accounts", "api_key", nullable=False)
    op.drop_index("ix_accounts_api_key_hash", table_name="accounts")
    op.drop_column("accounts", "api_key_hash")
