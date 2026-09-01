"""Librarian <-> Joker contract.

This file IS the documented interface between the two components.
Both sides import exclusively from here; neither side reaches into the
other's internals.  Versioned so callers can detect breaking changes.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from box.schema.records import UserContext

INTERFACE_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Suggestion contract
# Used by suggest.py (producer) and joker components (consumer).
# ---------------------------------------------------------------------------


class SuggestionRequest(BaseModel):
    """What the Joker knows about this listener before generation begins."""

    version: str = INTERFACE_VERSION
    user_context: UserContext = Field(
        description="Structured per-session listener snapshot (all fields optional)."
    )
    listener_history: list[str] = Field(
        default_factory=list,
        description="Categories of jokes already delivered in this session.",
    )
    taxonomy_snapshot_version: str = Field(
        description=(
            "ISO-date string identifying which taxonomy snapshot to query. "
            "Pass today's date if you want the live snapshot."
        )
    )


class Angle(BaseModel):
    """A single suggested approach for the next joke."""

    genre: str = Field(description="Target genre / file label.")
    topic: str = Field(description="Specific topic within the genre.")
    rationale: str = Field(
        description="Why this angle suits this listener right now."
    )
    freshness_score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "0 = genre is well-covered (many jokes exist); "
            "1 = genre is thin (fewer than 3 jokes)."
        ),
    )


class SuggestionResponse(BaseModel):
    """Ranked list of angles the Joker should consider."""

    version: str = INTERFACE_VERSION
    angles: list[Angle] = Field(
        min_length=1,
        description=(
            "Ranked angles, most recommended first. "
            "An empty list is never valid; suggest.py raises RuntimeError."
        ),
    )


# ---------------------------------------------------------------------------
# Classification contract
# Used by classify.py (producer) and joker.file (consumer).
# ---------------------------------------------------------------------------


class ClassificationRequest(BaseModel):
    """What the Librarian needs to assign a category."""

    version: str = INTERFACE_VERSION
    joke_text: str
    user_reaction: str
    taxonomy_snapshot_version: str = Field(
        description="ISO-date string; used to fetch the same snapshot used for generation."
    )
    suggested_path: list[str] = Field(
        default_factory=list,
        description=(
            "The path suggested during the pre-generation step. "
            "May be empty if no suggestion was accepted."
        ),
    )


class ClassificationResponse(BaseModel):
    """The Librarian's classification decision.

    justification is required whether is_new is True or False.
    When is_new=False it must explain why the existing label fits.
    When is_new=True it must justify why no existing label was adequate;
    this text is also stored on the File row's category_justification column.
    """

    version: str = INTERFACE_VERSION
    category: str = Field(description="Assigned genre label. Never 'General'.")
    is_new: bool = Field(
        description="True if a new File (and possibly Drawer/Cabinet) row was created."
    )
    justification: str = Field(
        min_length=1,
        description="Required regardless of is_new. Empty string is a ValueError.",
    )
    path: list[str] = Field(
        min_length=3,
        description="[cabinet_label, drawer_label, file_label].",
    )
