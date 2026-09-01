"""SQLAlchemy 2.0 ORM models for the Jokebox hierarchy and trace log.

Table layout mirrors the hierarchy spec:
  cabinets -> drawers -> files -> jokes
  traces   (append-only event log; one row per record_step call)

JSONB columns are used for nested joke fields to keep the fixed
top-level names (as specified in records.py) visible as first-class
columns while storing sub-objects efficiently.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Account(Base):
    """One row per registered account.  Attribution references this by id."""

    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # sha256 hex digest of the plaintext key returned once at creation.
    # The plaintext is never stored; only the hash is kept for validation.
    api_key_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    __table_args__ = (UniqueConstraint("name", name="uq_account_name"),)

    jokes: Mapped[list["Joke"]] = relationship("Joke", back_populates="account_obj")



class Cabinet(Base):
    __tablename__ = "cabinets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    label: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    __table_args__ = (UniqueConstraint("label", name="uq_cabinet_label"),)

    drawers: Mapped[list[Drawer]] = relationship(
        "Drawer", back_populates="cabinet", cascade="all, delete-orphan"
    )


class Drawer(Base):
    __tablename__ = "drawers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    label: Mapped[str] = mapped_column(String, nullable=False)
    cabinet_id: Mapped[str] = mapped_column(
        String, ForeignKey("cabinets.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    __table_args__ = (
        UniqueConstraint("cabinet_id", "label", name="uq_drawer_cabinet_label"),
    )

    cabinet: Mapped[Cabinet] = relationship("Cabinet", back_populates="drawers")
    files: Mapped[list[File]] = relationship(
        "File", back_populates="drawer", cascade="all, delete-orphan"
    )


class File(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    label: Mapped[str] = mapped_column(String, nullable=False)
    drawer_id: Mapped[str] = mapped_column(
        String, ForeignKey("drawers.id", ondelete="CASCADE"), nullable=False
    )
    # Populated only when is_new=True in ClassificationResponse; required then.
    category_justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    __table_args__ = (
        UniqueConstraint("drawer_id", "label", name="uq_file_drawer_label"),
    )

    drawer: Mapped[Drawer] = relationship("Drawer", back_populates="files")
    jokes: Mapped[list[Joke]] = relationship(
        "Joke", back_populates="file", cascade="all, delete-orphan"
    )


class Joke(Base):
    """One row per joke.  The ten fixed field names from records.py map directly
    onto columns; nested shapes are stored as JSONB."""

    __tablename__ = "jokes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    file_id: Mapped[str] = mapped_column(
        String, ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    # Nullable FK — jokes filed before accounts existed remain valid.
    account_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )

    # Fixed field names — do not rename.
    prompt_responses: Mapped[dict] = mapped_column(JSONB, nullable=False)
    joke_text: Mapped[str] = mapped_column(Text, nullable=False)
    user_reaction: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    # "metadata" is reserved by SQLAlchemy Declarative; column name stays
    # "metadata" in the DB but the Python attribute is "joke_metadata".
    joke_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False)
    # Structured per-session listener snapshot (UserContext Pydantic model).
    # Stored as JSONB so all optional sub-fields are first-class queryable keys.
    user_context: Mapped[dict] = mapped_column(JSONB, nullable=False)
    attribution: Mapped[dict] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)
    set_id: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    file: Mapped[File] = relationship("File", back_populates="jokes")
    account_obj: Mapped["Account | None"] = relationship("Account", back_populates="jokes")


class Trace(Base):
    """Append-only event log.  One row per record_step call.
    Columns mirror the record_step signature exactly."""

    __tablename__ = "traces"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    artifact_id: Mapped[str] = mapped_column(String, nullable=False)
    artifact_type: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
