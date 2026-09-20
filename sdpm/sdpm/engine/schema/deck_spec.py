# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Deck specification skeleton and pre-composition validation."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from sdpm.engine.schema.lint_outline import lint_outline

DECK_JSON_SKELETON: dict[str, Any] = {
    "template": "",
    "fonts": {"fullwidth": "", "halfwidth": ""},
    "defaultTextColor": "",
    "slideSize": {},
}

_SLIDE_RE = re.compile(r"^-\s+\[([^\]]+)\]\s+.+")
_VALID_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
_SUB_ITEM_RE = re.compile(r"^\s{2,}-\s+(body|visual|evidence)\s*:")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_REQUIRED_SUB_ITEMS = ("body", "visual", "evidence")


def complete_deck_skeleton(deck: dict) -> dict:
    """Return a copy of deck with every deck.json skeleton field present."""
    completed = deepcopy(deck)
    for key, default in DECK_JSON_SKELETON.items():
        completed.setdefault(key, deepcopy(default))

    fonts = completed.get("fonts")
    if not isinstance(fonts, dict):
        fonts = {}
    else:
        fonts = deepcopy(fonts)
    for key, default in DECK_JSON_SKELETON["fonts"].items():
        fonts.setdefault(key, default)
    completed["fonts"] = fonts
    return completed


def _is_non_empty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_positive_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _outline_slugs(lines: list[str]) -> list[str]:
    slugs: list[str] = []
    for line in lines:
        match = _SLIDE_RE.match(line.strip())
        if match and _VALID_SLUG_RE.fullmatch(match.group(1)):
            slugs.append(match.group(1))
    return slugs


def _outline_structure_warnings(lines: list[str]) -> list[str]:
    warnings: list[str] = []
    current: tuple[int, str] | None = None
    found: set[str] = set()

    def finish_slide() -> None:
        if current is None:
            return
        missing = [key for key in _REQUIRED_SUB_ITEMS if key not in found]
        if missing:
            line_number, slug = current
            warnings.append(
                f"outline.md line {line_number}: slide {slug} missing {', '.join(missing)}"
            )

    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        slide_match = _SLIDE_RE.match(stripped)
        if slide_match:
            finish_slide()
            current = (line_number, slide_match.group(1))
            found = set()
            continue
        if current is not None and stripped.startswith("#"):
            finish_slide()
            current = None
            found = set()
            continue
        sub_item_match = _SUB_ITEM_RE.match(line)
        if current is not None and sub_item_match:
            found.add(sub_item_match.group(1))

    finish_slide()
    return warnings


def validate_specs(
    deck_json: dict,
    outline_text: str,
    assigned_slugs: list[str] | None = None,
) -> dict:
    """Validate deck.json and outline.md before slide composition."""
    errors: list[str] = []
    warnings: list[str] = []

    for key in DECK_JSON_SKELETON:
        if key not in deck_json:
            errors.append(f"deck.json missing key: {key}")
    fonts = deck_json.get("fonts")
    if isinstance(fonts, dict):
        if "halfwidth" not in fonts:
            errors.append("deck.json missing key: fonts.halfwidth")
    else:
        fonts = {}

    if "template" in deck_json and not _is_non_empty(deck_json.get("template")):
        errors.append("deck.json template is empty")

    text_color = deck_json.get("defaultTextColor")
    if "defaultTextColor" in deck_json and (
        not isinstance(text_color, str) or not _COLOR_RE.fullmatch(text_color)
    ):
        errors.append("deck.json defaultTextColor must match #RRGGBB")

    if not _is_non_empty(fonts.get("halfwidth")):
        errors.append("deck.json fonts.halfwidth is empty")
    if not _is_non_empty(fonts.get("fullwidth")):
        warnings.append("deck.json fonts.fullwidth is empty")

    slide_size = deck_json.get("slideSize")
    if not isinstance(slide_size, dict) or not all(
        _is_positive_number(slide_size.get(key)) for key in ("width", "height")
    ):
        errors.append("deck.json slideSize requires positive width and height")
    if not isinstance(slide_size, dict) or not slide_size.get("ptPerPx"):
        warnings.append("deck.json slideSize.ptPerPx is missing")

    lines = outline_text.splitlines()
    slugs = _outline_slugs(lines)
    lint_messages = {
        "slug-pattern": "invalid slug",
        "slug-duplicate": "duplicate slug",
        "no-slides": "no slides",
    }
    for diagnostic in lint_outline(outline_text):
        rule = diagnostic["rule"]
        line_number = diagnostic["line"]
        errors.append(f"outline.md line {line_number}: {lint_messages.get(rule, rule)}")

    outline_slug_set = set(slugs)
    for slug in assigned_slugs or []:
        if slug not in outline_slug_set:
            errors.append(f"outline.md assigned slug not found: {slug}")

    warnings.extend(_outline_structure_warnings(lines))
    if "[TBD]" in outline_text:
        warnings.append("outline.md contains [TBD]")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "slugs": slugs,
    }
