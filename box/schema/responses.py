"""Pydantic response models for the Box API.

Every endpoint in box/router.py declares one of these as its response_model.
This causes FastAPI to:
  1. Generate typed response schemas in /openapi.json.
  2. Validate and serialize the returned dict against the declared shape.
  3. Strip undeclared fields before sending.

Nested shapes reuse the canonical types from records.py so the response
schema matches the write schema exactly.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from box.schema.records import Attribution, JokeMetadata, PromptTurn, Provenance, SetId, UserContext


# ---------------------------------------------------------------------------
# Shared leaf types
# ---------------------------------------------------------------------------

class NodeOut(BaseModel):
    """Minimal id + label reference used inside nested trees."""
    id: str
    label: str


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthOut(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class AccountOut(BaseModel):
    """Returned by GET /accounts and GET /accounts/{id}.  Key is never included."""
    id: str
    name: str
    created_at: datetime


class AccountCreateOut(BaseModel):
    """Returned only by POST /accounts.  api_key is shown exactly once."""
    id: str
    name: str
    api_key: str   # plaintext; store it now — it cannot be retrieved again
    created_at: datetime


class AccountListOut(BaseModel):
    accounts: list[AccountOut]


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

class UpsertOut(BaseModel):
    joke_id: str
    cabinet_id: str
    drawer_id: str
    file_id: str


# ---------------------------------------------------------------------------
# Jokes
# ---------------------------------------------------------------------------

class JokeOut(BaseModel):
    id: str
    file_id: str
    account_id: str | None = None
    prompt_responses: list[PromptTurn]
    joke_text: str
    user_reaction: str
    score: int
    category: str
    metadata: JokeMetadata
    user_context: UserContext
    attribution: Attribution
    provenance: Provenance
    set_id: SetId


class JokeSummaryOut(BaseModel):
    """Minimal joke reference used inside file-detail and tree responses."""
    id: str
    score: int
    joke_text: str = ""
    category: str = ""
    source: str = ""
    set: str = ""


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------

class TraceStepOut(BaseModel):
    id: str
    kind: str
    actor: str
    rationale: str
    latency_ms: int
    model: str | None = None
    prompt_ref: str | None = None
    inputs: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)
    cost: float | None = None


class TraceOut(BaseModel):
    joke_id: str
    steps: list[TraceStepOut]


class ArtifactTraceOut(BaseModel):
    """Returned by GET /traces/{artifact_id}.

    Generalizes TraceOut to any artifact_id (joke, set, category, session, ...)
    rather than only jokes.  An artifact with no recorded steps returns an
    empty list, not a 404 — the endpoint does not know or enforce which
    artifact_type an id belongs to.
    """

    artifact_id: str
    steps: list[TraceStepOut]


# ---------------------------------------------------------------------------
# Hierarchy reads
# ---------------------------------------------------------------------------

class DrawerSummaryOut(BaseModel):
    """Used in flat drawer lists and cabinet-detail drawer arrays."""
    id: str
    label: str
    cabinet_id: str | None = None  # present in flat list; omitted in nested tree


class FileSummaryOut(BaseModel):
    id: str
    label: str
    joke_count: int


class CabinetDetailOut(BaseModel):
    id: str
    label: str
    drawers: list[NodeOut]


class CabinetListOut(BaseModel):
    cabinets: list[NodeOut]


class DrawerListOut(BaseModel):
    drawers: list[DrawerSummaryOut]


class DrawerDetailOut(BaseModel):
    id: str
    label: str
    cabinet_id: str
    files: list[NodeOut]


class FileDetailOut(BaseModel):
    id: str
    label: str
    drawer_id: str
    jokes: list[JokeSummaryOut]


# ---------------------------------------------------------------------------
# Tree (GET /box)
# ---------------------------------------------------------------------------

class TreeFileOut(BaseModel):
    id: str
    label: str
    joke_count: int
    jokes: list[JokeSummaryOut] = Field(default_factory=list)


class TreeDrawerOut(BaseModel):
    id: str
    label: str
    files: list[TreeFileOut]


class TreeCabinetOut(BaseModel):
    id: str
    label: str
    drawers: list[TreeDrawerOut]


class TreeOut(BaseModel):
    cabinets: list[TreeCabinetOut]


# ---------------------------------------------------------------------------
# Path read (GET /box/{cabinet}/{drawer}/{file})
# ---------------------------------------------------------------------------

class PathReadOut(BaseModel):
    cabinet: NodeOut
    drawer: NodeOut
    file: NodeOut
    jokes: list[JokeOut]


# ---------------------------------------------------------------------------
# Funniest in genre
# ---------------------------------------------------------------------------

class FunniestOut(BaseModel):
    genre: str
    jokes: list[JokeOut]


class TopJokesOut(BaseModel):
    jokes: list[JokeOut]


class GenreCoverageOut(BaseModel):
    coverage: dict[str, int]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class ExportFileOut(BaseModel):
    id: str
    label: str
    jokes: list[JokeOut]


class ExportDrawerOut(BaseModel):
    id: str
    label: str
    files: list[ExportFileOut]


class ExportCabinetOut(BaseModel):
    id: str
    label: str
    drawers: list[ExportDrawerOut]


class ExportOut(BaseModel):
    cabinets: list[ExportCabinetOut]


# ---------------------------------------------------------------------------
# Scoped counts
# ---------------------------------------------------------------------------

class CabinetCountsOut(BaseModel):
    cabinet_id: str
    drawers: int
    files: int
    jokes: int


class DrawerCountsOut(BaseModel):
    drawer_id: str
    files: int
    jokes: int


class FileCountsOut(BaseModel):
    file_id: str
    jokes: int


class GlobalCountsOut(BaseModel):
    cabinets: int
    drawers: int
    files: int
    jokes: int


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------

class ViolationOut(BaseModel):
    level: str
    path: str
    child_count: int
    reason: str


class ComplianceOut(BaseModel):
    compliant: bool
    violations: list[ViolationOut]
