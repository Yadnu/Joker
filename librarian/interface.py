"""Librarian <-> Joker contract.

This file IS the documented interface between the two components.
Both sides import exclusively from here; neither side reaches into the
other's internals.  Versioned so callers can detect breaking changes.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from box.schema.records import UserContext

INTERFACE_VERSION = "1.0"

# Few-shot joke turns (independent of spoken JOKE_SHAPES / engines).
FEW_SHOT_SHAPES: tuple[str, ...] = (
    "reversal",
    "literalism",
    "definition",
    "wrong-detail",
    "compression",
    "misdirect",
)


def assert_compatible_version(version: str) -> None:
    """Reject requests stamped with a different contract version."""
    if version != INTERFACE_VERSION:
        raise ValueError(
            f"Unsupported interface version {version!r}; expected {INTERFACE_VERSION}"
        )


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
    # Per-session tone preference signal.  None means no preference established
    # yet (use the listener's humor_preferences if set, otherwise default to 1).
    # Computed by the orchestrator from the running tone-score history.
    preferred_tone_level: int | None = Field(
        default=None,
        ge=1,
        le=3,
        description=(
            "The tone level that has scored highest for this listener so far. "
            "None until at least one scored joke exists in the session."
        ),
    )
    recent_critiques: list[dict] = Field(
        default_factory=list,
        description="Last five {score, shape, critique} rows from this session.",
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
    # Recommended tone level for this angle, set by the Librarian based on
    # listener preference history.  1 is the safe default for new listeners.
    tone_level: int = Field(
        default=1,
        ge=1,
        le=3,
        description=(
            "Tone level that the Librarian recommends for this angle "
            "given the listener's scored history (1=standard, 2=edgier, 3=darkest)."
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
    critique: str = Field(
        default="",
        description=(
            "One sentence, max twenty words, naming one mechanism. "
            "Does not replace score."
        ),
    )


# ---------------------------------------------------------------------------
# Call facade — Joker imports these, never librarian.suggest/classify/score.
# Lazy imports avoid a cycle (those modules import the models above).
# ---------------------------------------------------------------------------


async def suggest(request: SuggestionRequest, session: object) -> SuggestionResponse:
    from librarian.suggest import suggest as _suggest

    return await _suggest(request, session)


async def classify(
    request: ClassificationRequest, session: object
) -> ClassificationResponse:
    from librarian.classify import classify as _classify

    return await _classify(request, session)


async def score(
    *,
    joke_id: str,
    joke_text: str,
    user_reaction: str,
    user_context: str,
    session: object,
) -> int:
    from librarian.score import score as _score

    return await _score(
        joke_id=joke_id,
        joke_text=joke_text,
        user_reaction=user_reaction,
        user_context=user_context,
        session=session,
    )


async def extract_metadata(
    *,
    joke_id: str,
    joke_text: str,
    tone_level: int = 1,
    session: object,
    shape: str = "",
    critique: str = "",
):
    from librarian.metadata import extract_metadata as _extract

    return await _extract(
        joke_id=joke_id,
        joke_text=joke_text,
        tone_level=tone_level,
        session=session,
        shape=shape,
        critique=critique,
    )
