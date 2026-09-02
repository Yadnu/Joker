"""Joker HTTP router — exposes Joker operations over HTTP.

Endpoints:
  POST /joker/reroll

This router is registered in box/main.py alongside the Box router.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.records import Provenance, SetId, UserContext
from joker.reroll import reroll
from shared.db import get_session

router = APIRouter(prefix="/joker")


# ---------------------------------------------------------------------------
# Reroll
# ---------------------------------------------------------------------------

class RerollRequest(BaseModel):
    """All context needed to file the rejected joke and generate the darker one."""

    # --- Original joke (to be filed as rejected) ---
    original_joke_id: str
    original_joke_text: str
    original_prompt_responses: list[dict]
    original_provenance: Provenance

    # --- Generation context ---
    topic: str
    style: str = "one-liner"
    intended_quality: Literal["good", "bad"] = "good"
    tone_level: Literal[1, 2, 3]
    set_id: SetId
    user_context: UserContext

    # --- Session context ---
    taxonomy_snapshot_version: str
    joker_name: str = "joker-v1"
    account_name: str = "joker-live"
    box_api_key: str | None = None

    # How many rerolls have already happened this session (used to rotate
    # refusal lines so no line repeats within a session).
    session_reroll_count: int = 0


class RerollOut(BaseModel):
    original_joke_id: str
    replacement_joke_id: str | None
    replacement_text: str | None
    ceiling_reached: bool
    # One of the four in-character refusal lines; only set when ceiling_reached.
    refusal_line: str | None


@router.post("/reroll", status_code=200, response_model=RerollOut)
async def reroll_joke(
    body: RerollRequest,
    session: AsyncSession = Depends(get_session),
) -> RerollOut:
    """Reject the current joke and request one tone level darker.

    The rejected joke is filed permanently with a rejection reaction — the
    reroll is the signal, not a reason to discard the joke.  A trace step of
    kind='reroll' (or 'reroll_refused' at level 3) records the adaptation.

    At tone_level == 3 no generation occurs; the caller receives the
    in-character refusal line and ceiling_reached=True.

    Viewer rendering guidance:
      - The reroll control label: "Didn't like that one? Make it darker."
      - At tone_level == 3: disable the control and show refusal_line as the
        disabled-state label.
      - In the trace panel: render as an explicit branch — original joke,
        rejection, replacement — linked and readable in that order.
      - tone_level appears on the joke detail screen alongside genre.
    """
    result = await reroll(
        original_joke_id=body.original_joke_id,
        original_joke_text=body.original_joke_text,
        original_prompt_responses=body.original_prompt_responses,
        original_provenance=body.original_provenance,
        topic=body.topic,
        style=body.style,
        intended_quality=body.intended_quality,
        tone_level=body.tone_level,
        set_id=body.set_id,
        user_context=body.user_context,
        taxonomy_snapshot_version=body.taxonomy_snapshot_version,
        joker_name=body.joker_name,
        account_name=body.account_name,
        box_api_key=body.box_api_key,
        session_reroll_count=body.session_reroll_count,
        session=session,
    )

    return RerollOut(**result)
