"""Pydantic v2 models for the canonical joke record.

Field names are fixed and graded against a written spec.
Do not rename, pluralize, or paraphrase any top-level field name.
Nested shapes may use their own names freely.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared vocabulary — used by BOTH JokeMetadata.sensitivity_flags and
# UserContext.humor_preferences / UserContext.humor_avoid so the downstream
# Audience Categorizer can map listener traits onto sensitivity flags without
# any translation layer.
# ---------------------------------------------------------------------------

class HumorStyle(str, Enum):
    wordplay = "wordplay"
    observational = "observational"
    absurdist = "absurdist"
    deadpan = "deadpan"
    dark = "dark"
    physical = "physical"
    self_deprecating = "self_deprecating"
    topical = "topical"


# ---------------------------------------------------------------------------
# UserContext — per-session listener snapshot.
#
# Non-identifying by design: coarse buckets rather than precise values.
#
# Explicitly DO NOT store: name, date of birth, exact age, email, employer,
# city, or any other value that could identify a specific person.
# This satisfies the brief's "light, non-identifying" requirement.
# Age is stored as a band (under_25 / 25_40 / 40_60 / over_60) rather than
# a DOB or exact age because (a) comedy references land generationally so a
# band is all that is useful, and (b) a DOB would violate the non-identifying
# requirement.  See docs/DECISIONS.md entry dated 2026-09-01.
#
# humor_avoid is a HARD constraint on generation, not a soft preference.
# ---------------------------------------------------------------------------

class AgeBand(str, Enum):
    under_25 = "under_25"
    band_25_40 = "25_40"    # Python attr cannot start with a digit; value is "25_40"
    band_40_60 = "40_60"
    over_60 = "over_60"


class OccupationField(str, Enum):
    tech = "tech"
    healthcare = "healthcare"
    education = "education"
    trades = "trades"
    finance = "finance"
    student = "student"
    retired = "retired"
    other = "other"


class EnergyLevel(str, Enum):
    warm = "warm"
    dry = "dry"
    rowdy = "rowdy"
    reserved = "reserved"


class UserContext(BaseModel):
    """Per-session listener snapshot attached to every joke told in the session.

    All fields are optional so a session with only one field filled in works.
    No field here identifies a specific person; see module docstring above.
    """

    age_band: AgeBand | None = None
    region: str | None = Field(
        default=None,
        description="Coarse locale, e.g. 'US West', 'UK', 'South Asia'. Not a city.",
    )
    occupation_field: OccupationField | None = None
    humor_preferences: list[HumorStyle] = Field(
        default_factory=list,
        description="Styles the listener says they enjoy.",
    )
    humor_avoid: list[HumorStyle] = Field(
        default_factory=list,
        description="HARD CONSTRAINT: styles or subjects to steer clear of.",
    )
    energy: EnergyLevel | None = Field(
        default=None,
        description="How the room feels.",
    )
    first_time: bool | None = Field(
        default=None,
        description="Whether this listener has heard this Joker before.",
    )
    session_notes: str | None = Field(
        default=None,
        description="One short free-text line the Joker can add mid-session.",
    )


# ---------------------------------------------------------------------------
# Joke sub-types
# ---------------------------------------------------------------------------

class PromptTurn(BaseModel):
    role: str
    content: str


class JokeMetadata(BaseModel):
    topic: str
    style: str
    length: str
    # Uses HumorStyle so the Audience Categorizer can map listener traits
    # (humor_preferences / humor_avoid) onto sensitivity flags without translation.
    sensitivity_flags: list[HumorStyle] = Field(default_factory=list)


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


# ---------------------------------------------------------------------------
# Canonical joke record — ten fixed fields
# ---------------------------------------------------------------------------

class JokeRecord(BaseModel):
    """The ten fixed fields.  Order matches the spec; do not reorder for grading."""

    prompt_responses: list[PromptTurn]
    joke_text: str
    user_reaction: str
    score: int = Field(ge=0, le=10)
    category: str
    metadata: JokeMetadata
    user_context: UserContext
    attribution: Attribution
    provenance: Provenance
    set_id: SetId
