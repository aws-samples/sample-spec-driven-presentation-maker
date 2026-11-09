# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""``parse_outline_entries``: outline.md as the Web UI outline view reads it (outlineParser.ts)."""

from __future__ import annotations

from pathlib import Path

from sdpm.engine.schema import parse_outline_entries, parse_outline_text

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "style-sample-deck" / "outline.md"


def _slide(slug: str, message: str, sub: list[tuple[str, str]] | None = None) -> dict:
    return {"type": "slide", "slug": slug, "message": message,
            "subItems": [{"key": k, "value": v} for k, v in (sub or [])]}


def test_skeleton_and_enriched_slides() -> None:
    text = "- [cover] Title slide\n- [why]   Why now  \n  - body: three points \n  - visual: a chart\n  - evidence: brief.md\n"
    assert parse_outline_entries(text) == [
        _slide("cover", "Title slide"),
        _slide("why", "Why now", [("body", "three points"), ("visual", "a chart"), ("evidence", "brief.md")]),
    ]


def test_a_sub_item_before_any_slide_is_prose() -> None:
    assert parse_outline_entries("  - body: orphan\n- [a] A") == [
        {"type": "prose", "text": "  - body: orphan"},
        _slide("a", "A"),
    ]


def test_a_section_and_prose_end_the_slide_context() -> None:
    text = "# Deck title\n- [a] A\n## Part two\n  - body: not a\n- [b] B\nfree text\n  - body: not b\n"
    assert parse_outline_entries(text) == [
        {"type": "prose", "text": "# Deck title"},
        _slide("a", "A"),
        {"type": "section", "title": "Part two"},
        {"type": "prose", "text": "  - body: not a"},
        _slide("b", "B"),
        {"type": "prose", "text": "free text"},
        {"type": "prose", "text": "  - body: not b"},
    ]


def test_blank_lines_are_skipped_and_legacy_slugs_kept_verbatim() -> None:
    assert parse_outline_entries("\n   \n- [1: Name] Msg\n\n") == [_slide("1: Name", "Msg")]


def test_crlf_parses_like_lf() -> None:
    text = "## S\n- [a] A\n  - body: x\n"
    assert parse_outline_entries(text.replace("\n", "\r\n")) == parse_outline_entries(text)


def test_the_bundled_sample_outline() -> None:
    text = _FIXTURE.read_text(encoding="utf-8")
    entries = parse_outline_entries(text)
    assert [e["slug"] for e in entries if e["type"] == "slide"] == parse_outline_text(text)
    assert len([e for e in entries if e["type"] == "section"]) == 4
    assert all(len(e["subItems"]) == 3 for e in entries if e["type"] == "slide")
