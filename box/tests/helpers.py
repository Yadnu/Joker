"""Shared test helpers: canonical joke payload factory."""

from __future__ import annotations


def joke_payload(
    *,
    cabinet: str = "Observational",
    drawer: str = "Everyday Life",
    file: str = "Work",
    category: str = "Observational",
    score: int = 7,
    joke_text: str = "Why do programmers prefer dark mode? Because light attracts bugs.",
    user_reaction: str = "Ha! That's true.",
    set_label: str = "set_default",
    position: int = 1,
) -> dict:
    """Return a complete, valid upsert payload with all ten joke fields."""
    return {
        "cabinet": cabinet,
        "drawer": drawer,
        "file": file,
        "joke": {
            "prompt_responses": [
                {"role": "system", "content": "You are a stand-up comedian."},
                {"role": "user", "content": f"Tell me a joke about {file.lower()}."},
                {"role": "assistant", "content": joke_text},
            ],
            "joke_text": joke_text,
            "user_reaction": user_reaction,
            "score": score,
            "category": category,
            "metadata": {
                "topic": file.lower(),
                "style": "one-liner",
                "length": "short",
                "sensitivity_flags": [],
            },
            "user_context": {
                "occupation_field": "tech",
                "humor_preferences": ["observational", "deadpan"],
                "energy": "dry",
            },
            "attribution": {"joker": "joker-v1", "account": "acct_test"},
            "provenance": {
                "source": "generated",
                "model": "gpt-4o",
                "prompt": f"Tell me a joke about {file.lower()}.",
                "selection_rationale": "Best of three candidates.",
            },
            "set_id": {"set": set_label, "position": position},
        },
    }
