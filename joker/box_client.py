"""Joker-facing re-export of the single Box client module."""

from __future__ import annotations

from shared.box_client import (  # noqa: F401
    BOX_BASE_URL,
    _client_factory,
    funniest_in_genre,
    genre_coverage,
    high_scorers,
    http_post,
    http_put,
    recent_scores,
    search_jokes,
    taxonomy,
    upsert_joke,
)
