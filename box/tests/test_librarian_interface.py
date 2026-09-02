"""Librarian <-> Joker contract is versioned and imported as the seam."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from box.schema.records import UserContext
from librarian.interface import (
    INTERFACE_VERSION,
    ClassificationRequest,
    ClassificationResponse,
    SuggestionRequest,
    SuggestionResponse,
    assert_compatible_version,
)


def test_interface_version_is_semver_string():
    assert INTERFACE_VERSION == "1.0"
    assert_compatible_version(INTERFACE_VERSION)


def test_incompatible_version_is_rejected():
    with pytest.raises(ValueError, match="Unsupported interface version"):
        assert_compatible_version("0.9")


def test_suggestion_models_carry_version():
    req = SuggestionRequest(
        user_context=UserContext(),
        taxonomy_snapshot_version="2026-09-01",
    )
    assert req.version == INTERFACE_VERSION
    with pytest.raises(ValidationError):
        SuggestionResponse(version=INTERFACE_VERSION, angles=[])


def test_classification_justification_required_on_both_branches():
    with pytest.raises(ValidationError):
        ClassificationResponse(
            category="Observational",
            is_new=False,
            justification="",
            path=["Travel", "Airports", "Security"],
        )
    reuse = ClassificationResponse(
        category="Observational",
        is_new=False,
        justification="Everyday inconvenience matches the Observational file.",
        path=["Travel", "Airports", "Security"],
    )
    created = ClassificationResponse(
        category="AirportSecurity",
        is_new=True,
        justification="No existing file covers TSA-specific procedural humour.",
        path=["Travel", "Airports", "AirportSecurity"],
    )
    assert reuse.version == created.version == INTERFACE_VERSION
    assert created.is_new is True
    assert reuse.is_new is False


def test_joker_imports_facade_not_librarian_modules():
    import ast
    from pathlib import Path

    src = Path("joker/orchestrator.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    librarian_mods = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("librarian.")
    ]
    assert librarian_mods == ["librarian.interface"]


def test_classification_request_is_versioned():
    req = ClassificationRequest(
        joke_text="j",
        user_reaction="ha",
        taxonomy_snapshot_version="2026-09-01",
    )
    assert req.version == INTERFACE_VERSION
