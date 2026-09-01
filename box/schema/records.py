"""Pydantic v2 models for the canonical joke record.

Field names are fixed and graded against a written spec.
Do not rename, pluralize, or paraphrase any top-level field name.
Nested shapes may use their own names freely.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class PromptTurn(BaseModel):
    role: str
    content: str


class JokeMetadata(BaseModel):
    topic: str
    style: str
    length: str
    sensitivity_flags: list[str] = Field(default_factory=list)


class Attribution(BaseModel):
    joker: str
    account: str


class Provenance(BaseModel):
    source: Literal["generated", "curated"]
    model: str
    prompt: str
    selection_rationale: str


class SetId(BaseModel):
    set: str
    position: int


class JokeRecord(BaseModel):
    """The ten fixed fields.  Order matches the spec; do not reorder for grading."""

    prompt_responses: list[PromptTurn]
    joke_text: str
    user_reaction: str
    score: int = Field(ge=0, le=10)
    category: str
    metadata: JokeMetadata
    user_context: str
    attribution: Attribution
    provenance: Provenance
    set_id: SetId
