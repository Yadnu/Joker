"""Joker — reroll: escalate a rejected joke one tone level.

The user hears a joke and asks for a darker one.  This module:

  1. Files the rejected joke to the Box with user_reaction="[reroll requested]"
     and a score derived from that rejection.  The rejection IS the reaction.

  2. At tone_level < 3: generates a replacement at tone_level + 1, same topic
     and set position.  Files it with a trace step of kind="reroll" naming
     the original joke it replaced.

  3. At tone_level == 3: no generation happens.  A trace step of
     kind="reroll_refused" records that the ceiling was reached.  The original
     joke is still filed with its rejection reaction.

Both the rejected joke and (if generated) the replacement stay in the archive
permanently.  The rejection is the strongest user-fit signal in the session;
discarding it would make the adaptation invisible to grading.

CEILING REFUSAL LINES — rotate within a session so no line repeats:
  "That's as dark as this room gets."
  "Darker than this is just your future."
  "Any darker and legal gets involved."
  "This is the bottom. I checked."
"""

from __future__ import annotations

import time
import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from box.schema.records import (
    Attribution,
    JokeMetadata,
    JokeRecord,
    Provenance,
    PromptTurn,
    SetId,
    UserContext,
)
from joker import box_client
from joker.generate import generate
from librarian.interface import (
    ClassificationRequest,
    classify,
    extract_metadata,
    score,
)
from shared.trace import record_step

# Rotating refusal lines for tone_level == 3.  The caller supplies an index
# (session reroll count) so the right line is selected without repetition.
REFUSAL_LINES: tuple[str, ...] = (
    "That's as dark as this room gets.",
    "Darker than this is just your future.",
    "Any darker and legal gets involved.",
    "This is the bottom. I checked.",
)

# Score assigned when a joke is filed because the listener explicitly rejected
# it via reroll (not a live spoken reaction, but a strong negative signal).
REJECTION_SCORE = 1

_REJECTION_REACTION = "[reroll requested — listener asked for a darker joke]"


async def reroll(
    *,
    # Identity of the original (rejected) joke
    original_joke_id: str,
    original_joke_text: str,
    original_prompt_responses: list[dict],
    original_provenance: Provenance,
    # Shared context
    topic: str,
    style: str,
    intended_quality: Literal["good", "bad"],
    tone_level: Literal[1, 2, 3],
    set_id: SetId,
    user_context: UserContext,
    taxonomy_snapshot_version: str,
    joker_name: str,
    account_name: str,
    box_api_key: str | None,
    # How many rerolls have happened this session (for refusal-line rotation).
    session_reroll_count: int,
    session: AsyncSession,
) -> dict:
    """File the rejected joke then generate (or refuse) at tone_level + 1.

    Returns a dict with keys:
      original_joke_id:    str
      replacement_joke_id: str | None  (None when ceiling reached)
      replacement_text:    str | None
      ceiling_reached:     bool
      refusal_line:        str | None
    """
    t0_total = time.monotonic()

    # ------------------------------------------------------------------
    # Step 1: score the rejection, classify, extract metadata, file it.
    # The reroll request is the user reaction.
    # ------------------------------------------------------------------

    user_ctx_str = _describe_context(user_context)

    result_score = await score(
        joke_id=original_joke_id,
        joke_text=original_joke_text,
        user_reaction=_REJECTION_REACTION,
        user_context=user_ctx_str,
        session=session,
    )
    # Override with the rejection score (the scoring model doesn't know
    # the semantic weight of a reroll; we apply it deterministically).
    result_score = REJECTION_SCORE

    classification = await classify(
        ClassificationRequest(
            joke_text=original_joke_text,
            user_reaction=_REJECTION_REACTION,
            taxonomy_snapshot_version=taxonomy_snapshot_version,
        ),
        session,
    )

    metadata = await extract_metadata(
        joke_id=original_joke_id,
        joke_text=original_joke_text,
        tone_level=tone_level,
        session=session,
    )

    original_record = JokeRecord(
        prompt_responses=[PromptTurn(**t) for t in original_prompt_responses],
        joke_text=original_joke_text,
        user_reaction=_REJECTION_REACTION,
        score=result_score,
        category=classification.category,
        metadata=metadata,
        user_context=user_context,
        attribution=Attribution(joker=joker_name, account=account_name),
        provenance=original_provenance,
        set_id=set_id,
    )

    await box_client.upsert_joke(
        cabinet=classification.path[0],
        drawer=classification.path[1],
        file=classification.path[2],
        record=original_record,
        session=session,
        api_key=box_api_key,
    )

    # ------------------------------------------------------------------
    # Step 2: ceiling check.
    # ------------------------------------------------------------------

    if tone_level >= 3:
        refusal_line = REFUSAL_LINES[session_reroll_count % len(REFUSAL_LINES)]

        await record_step(
            artifact_id=original_joke_id,
            artifact_type="joke",
            kind="reroll_refused",
            actor="joker.reroll",
            model=None,
            prompt_ref=None,
            inputs={
                "original_joke_id": original_joke_id,
                "tone_level": tone_level,
                "ceiling": 3,
            },
            output={"refusal_line": refusal_line},
            rationale=(
                f"Listener requested escalation from tone_level={tone_level}, "
                "which is the ceiling (level 3). No generation performed. "
                f"Refusal line: {refusal_line!r}"
            ),
            latency_ms=int((time.monotonic() - t0_total) * 1000),
            cost=None,
            session=session,
        )

        return {
            "original_joke_id": original_joke_id,
            "replacement_joke_id": None,
            "replacement_text": None,
            "ceiling_reached": True,
            "refusal_line": refusal_line,
        }

    # ------------------------------------------------------------------
    # Step 3: generate replacement at tone_level + 1.
    # ------------------------------------------------------------------

    new_tone_level: Literal[1, 2, 3] = tone_level + 1  # type: ignore[assignment]
    replacement_id = f"joke_{uuid.uuid4().hex[:12]}"

    t0_gen = time.monotonic()
    replacement_text, replacement_provenance = await generate(
        joke_id=replacement_id,
        topic=topic,
        tone_level=new_tone_level,
        intended_quality=intended_quality,
        user_context=user_ctx_str,
        set_position=set_id.position,
        style=style,
        session=session,
    )
    gen_ms = int((time.monotonic() - t0_gen) * 1000)

    # Amend selection_rationale to name the reroll context.
    replacement_provenance = Provenance(
        source="generated",
        model=replacement_provenance.model,
        prompt=replacement_provenance.prompt,
        selection_rationale=(
            f"Reroll of {original_joke_id}: listener rejected tone_level={tone_level} joke. "
            f"Generated at tone_level={new_tone_level}. "
            + replacement_provenance.selection_rationale
        ),
    )

    # Record the reroll decision as a separate trace step.
    await record_step(
        artifact_id=replacement_id,
        artifact_type="joke",
        kind="reroll",
        actor="joker.reroll",
        model=None,
        prompt_ref=None,
        inputs={
            "original_joke_id": original_joke_id,
            "original_tone_level": tone_level,
            "new_tone_level": new_tone_level,
            "topic": topic,
            "set_position": set_id.position,
        },
        output={
            "replacement_joke_id": replacement_id,
            "replacement_text": replacement_text,
        },
        rationale=(
            f"Listener rejected joke {original_joke_id} (tone_level={tone_level}) "
            f"by requesting a darker version. Generated replacement {replacement_id} "
            f"at tone_level={new_tone_level}, same topic ({topic!r}) and "
            f"set_position={set_id.position}. Original filed with "
            f"score={REJECTION_SCORE} (rejection signal)."
        ),
        latency_ms=gen_ms,
        cost=None,
        session=session,
    )

    # Classify and file the replacement.
    repl_classification = await classify(
        ClassificationRequest(
            joke_text=replacement_text,
            user_reaction="",
            taxonomy_snapshot_version=taxonomy_snapshot_version,
        ),
        session,
    )

    repl_metadata = await extract_metadata(
        joke_id=replacement_id,
        joke_text=replacement_text,
        tone_level=new_tone_level,
        session=session,
    )

    replacement_record = JokeRecord(
        prompt_responses=[
            PromptTurn(role="system", content=replacement_provenance.prompt),
            PromptTurn(role="assistant", content=replacement_text),
        ],
        joke_text=replacement_text,
        user_reaction="",
        score=5,  # neutral placeholder; will be updated after delivery
        category=repl_classification.category,
        metadata=repl_metadata,
        user_context=user_context,
        attribution=Attribution(joker=joker_name, account=account_name),
        provenance=replacement_provenance,
        set_id=SetId(set=set_id.set, position=set_id.position),
    )

    await box_client.upsert_joke(
        cabinet=repl_classification.path[0],
        drawer=repl_classification.path[1],
        file=repl_classification.path[2],
        record=replacement_record,
        session=session,
        api_key=box_api_key,
    )

    return {
        "original_joke_id": original_joke_id,
        "replacement_joke_id": replacement_id,
        "replacement_text": replacement_text,
        "ceiling_reached": False,
        "refusal_line": None,
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _describe_context(ctx: UserContext) -> str:
    parts: list[str] = []
    if ctx.age_band is not None:
        parts.append(f"age {ctx.age_band.value}")
    if ctx.region is not None:
        parts.append(f"region {ctx.region}")
    if ctx.occupation_field is not None:
        parts.append(f"occupation {ctx.occupation_field.value}")
    if ctx.energy is not None:
        parts.append(f"energy {ctx.energy.value}")
    if ctx.humor_preferences:
        parts.append("prefers " + ", ".join(s.value for s in ctx.humor_preferences))
    if ctx.humor_avoid:
        parts.append("avoid " + ", ".join(s.value for s in ctx.humor_avoid))
    if ctx.first_time is not None:
        parts.append("first-time listener" if ctx.first_time else "returning listener")
    if ctx.session_notes:
        parts.append(ctx.session_notes)
    return "; ".join(parts) or "no listener context provided"
