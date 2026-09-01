"""Central model-name registry.

Every component imports its model name from here.
To upgrade or downgrade a role, change one line — or set the corresponding
environment variable to override without touching code.

Roles
-----
CLASSIFY_MODEL   Librarian.classify — taxonomy decisions are permanent;
                 use the best available reasoning model.
GENERATE_GOOD    joker.generate intended_quality="good" — sharp comedy.
GENERATE_BAD     joker.generate intended_quality="bad" — deliberately flat.
SETBUILD_MODEL   joker.setbuilder — narrative set structure.
SUGGEST_MODEL    librarian.suggest — angle ranking; fast, cheap.
SCORE_MODEL      librarian.score   — rubric scoring; fast, cheap.
METADATA_MODEL   librarian.metadata — tag extraction; fast, cheap.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Defaults — override any of these via environment variable of the same name.
# ---------------------------------------------------------------------------

CLASSIFY_MODEL: str  = os.environ.get("CLASSIFY_MODEL",  "o3")
GENERATE_GOOD:  str  = os.environ.get("GENERATE_GOOD",   "o3")
GENERATE_BAD:   str  = os.environ.get("GENERATE_BAD",    "gpt-4o-mini")
SETBUILD_MODEL: str  = os.environ.get("SETBUILD_MODEL",  "o3")
SUGGEST_MODEL:  str  = os.environ.get("SUGGEST_MODEL",   "gpt-4o-mini")
SCORE_MODEL:    str  = os.environ.get("SCORE_MODEL",     "gpt-4o-mini")
METADATA_MODEL: str  = os.environ.get("METADATA_MODEL",  "gpt-4o-mini")

# o3 uses max_completion_tokens instead of max_tokens and does not accept
# a system role — callers check this flag to adapt their request shape.
_O3_FAMILY = {"o3", "o3-mini", "o1", "o1-mini", "o1-preview"}

def is_reasoning_model(model: str) -> bool:
    """Return True if the model is in the o-series reasoning family."""
    return model in _O3_FAMILY


def build_messages(
    system: str,
    user: str,
    model: str,
) -> list[dict]:
    """Return a messages list compatible with both gpt-4o and o3.

    o3 does not accept a 'system' role.  Merge the system prompt into
    the first user message when targeting a reasoning model.
    """
    if is_reasoning_model(model):
        return [{"role": "user", "content": f"{system}\n\n{user}"}]
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def completion_kwargs(model: str, **extra) -> dict:
    """Return keyword args for client.chat.completions.create.

    o3 uses max_completion_tokens; gpt-4o uses max_tokens.
    Pass whichever token-limit key applies and strip the other.
    """
    kwargs: dict = {"model": model, **extra}
    # o3 doesn't accept response_format={"type":"json_object"} — it reasons
    # freely and returns JSON naturally when instructed in the prompt.
    if is_reasoning_model(model):
        kwargs.pop("response_format", None)
        if "max_tokens" in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
    return kwargs
