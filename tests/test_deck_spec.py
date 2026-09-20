# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for deck.json skeleton completion and pre-composition validation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from sdpm.api import check_specs
from sdpm.engine.schema.deck_spec import (
    DECK_JSON_SKELETON,
    complete_deck_skeleton,
    validate_specs,
)

_VALID_DECK = {
    "template": "blank-dark",
    "fonts": {"fullwidth": "Noto Sans JP", "halfwidth": "Amazon Ember"},
    "defaultTextColor": "#A1B2C3",
    "slideSize": {"width": 1920, "height": 1080, "ptPerPx": 0.5},
}
_VALID_OUTLINE = """# Deck

## Opening
- [intro] The opening claim
  - body: State the main point.
  - visual: Show a concise diagram.
  - evidence: Source 1.
"""


def _validate(
    *,
    deck: dict | None = None,
    outline: str = _VALID_OUTLINE,
    assigned_slugs: list[str] | None = None,
) -> dict:
    return validate_specs(
        deepcopy(_VALID_DECK if deck is None else deck),
        outline,
        assigned_slugs,
    )


def test_complete_deck_skeleton_fills_fields_without_mutating_input() -> None:
    original = {"template": "custom", "fonts": {"halfwidth": "Inter"}, "extra": 1}

    completed = complete_deck_skeleton(original)

    assert completed == {
        "template": "custom",
        "fonts": {"fullwidth": "", "halfwidth": "Inter"},
        "defaultTextColor": "",
        "slideSize": {},
        "extra": 1,
    }
    assert original == {"template": "custom", "fonts": {"halfwidth": "Inter"}, "extra": 1}
    assert completed is not DECK_JSON_SKELETON


@pytest.mark.parametrize("key", list(DECK_JSON_SKELETON))
def test_validate_specs_rejects_missing_skeleton_key(key: str) -> None:
    deck = deepcopy(_VALID_DECK)
    del deck[key]

    result = _validate(deck=deck)

    assert f"deck.json missing key: {key}" in result["errors"]
    assert result["ok"] is False


def test_validate_specs_rejects_missing_halfwidth_font_key_only() -> None:
    deck = deepcopy(_VALID_DECK)
    del deck["fonts"]["halfwidth"]
    assert "deck.json missing key: fonts.halfwidth" in _validate(deck=deck)["errors"]

    deck = deepcopy(_VALID_DECK)
    del deck["fonts"]["fullwidth"]
    result = _validate(deck=deck)
    assert not [e for e in result["errors"] if "fullwidth" in e]
    assert "deck.json fonts.fullwidth is empty" in result["warnings"]


def test_validate_specs_rejects_empty_template() -> None:
    deck = deepcopy(_VALID_DECK)
    deck["template"] = ""
    assert "deck.json template is empty" in _validate(deck=deck)["errors"]


@pytest.mark.parametrize("color", ["red", "#12345", "#GGGGGG", ""])
def test_validate_specs_rejects_invalid_default_text_color(color: str) -> None:
    deck = deepcopy(_VALID_DECK)
    deck["defaultTextColor"] = color
    assert "deck.json defaultTextColor must match #RRGGBB" in _validate(deck=deck)["errors"]


def test_validate_specs_rejects_empty_halfwidth_font() -> None:
    deck = deepcopy(_VALID_DECK)
    deck["fonts"]["halfwidth"] = " "
    assert "deck.json fonts.halfwidth is empty" in _validate(deck=deck)["errors"]


@pytest.mark.parametrize(
    "slide_size",
    [
        {"height": 1080, "ptPerPx": 0.5},
        {"width": 1920, "ptPerPx": 0.5},
        {"width": 0, "height": 1080, "ptPerPx": 0.5},
        {"width": 1920, "height": -1, "ptPerPx": 0.5},
    ],
)
def test_validate_specs_rejects_non_positive_or_missing_dimensions(slide_size: dict) -> None:
    deck = deepcopy(_VALID_DECK)
    deck["slideSize"] = slide_size
    assert "deck.json slideSize requires positive width and height" in _validate(deck=deck)["errors"]


@pytest.mark.parametrize(
    "outline,expected",
    [
        ("- [Bad_slug] Invalid slug\n", "outline.md line 1: invalid slug"),
        (
            "- [same] First\n  - body: x\n  - visual: y\n  - evidence: z\n"
            "- [same] Second\n  - body: x\n  - visual: y\n  - evidence: z\n",
            "outline.md line 5: duplicate slug",
        ),
        ("# Empty deck\n", "outline.md line 0: no slides"),
    ],
)
def test_validate_specs_maps_outline_lint_errors_with_line_numbers(
    outline: str,
    expected: str,
) -> None:
    assert expected in _validate(outline=outline)["errors"]


def test_validate_specs_rejects_assigned_slug_absent_from_outline() -> None:
    result = _validate(assigned_slugs=["intro", "missing"])
    assert "outline.md assigned slug not found: missing" in result["errors"]


def test_validate_specs_warns_for_empty_fullwidth_font() -> None:
    deck = deepcopy(_VALID_DECK)
    deck["fonts"]["fullwidth"] = ""
    assert "deck.json fonts.fullwidth is empty" in _validate(deck=deck)["warnings"]


def test_validate_specs_warns_for_missing_pt_per_px() -> None:
    deck = deepcopy(_VALID_DECK)
    del deck["slideSize"]["ptPerPx"]
    assert "deck.json slideSize.ptPerPx is missing" in _validate(deck=deck)["warnings"]


@pytest.mark.parametrize("missing", ["body", "visual", "evidence"])
def test_validate_specs_warns_for_each_missing_slide_sub_item(missing: str) -> None:
    items = {
        "body": "State the point.",
        "visual": "Show the diagram.",
        "evidence": "Source 1.",
    }
    del items[missing]
    outline = "- [intro] Claim\n" + "".join(
        f"  - {key}: {value}\n" for key, value in items.items()
    )

    result = _validate(outline=outline)

    assert f"outline.md line 1: slide intro missing {missing}" in result["warnings"]


def test_validate_specs_warns_when_outline_contains_tbd() -> None:
    outline = _VALID_OUTLINE.replace("Source 1.", "[TBD]")
    assert "outline.md contains [TBD]" in _validate(outline=outline)["warnings"]


def test_validate_specs_returns_validated_slugs() -> None:
    result = _validate(assigned_slugs=["intro"])
    assert result == {"ok": True, "errors": [], "warnings": [], "slugs": ["intro"]}


def test_api_check_specs_reads_tmp_deck(tmp_path: Path) -> None:
    deck_dir = tmp_path / "deck"
    (deck_dir / "specs").mkdir(parents=True)
    (deck_dir / "deck.json").write_text(json.dumps(_VALID_DECK), encoding="utf-8")
    (deck_dir / "specs" / "outline.md").write_text(_VALID_OUTLINE, encoding="utf-8")

    result = check_specs(deck_dir, assigned_slugs=["intro"])

    assert result == {"ok": True, "errors": [], "warnings": [], "slugs": ["intro"]}


def test_api_check_specs_reports_missing_files(tmp_path: Path) -> None:
    result = check_specs(tmp_path)
    assert result == {
        "ok": False,
        "errors": ["deck.json is missing", "specs/outline.md is missing"],
        "warnings": [],
        "slugs": [],
    }
