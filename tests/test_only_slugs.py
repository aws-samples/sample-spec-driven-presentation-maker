# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for only_slugs filtering in generate() and _assemble_slides_from_dir.

Validates Task 8 (asset/template resolution with only_slugs) and
Task 9 (multiple slug batch) from the lockless-measure spec.
"""

import json
from pathlib import Path

from sdpm.api import generate, _assemble_slides_from_dir


def _make_multi_slide_deck(tmp_path: Path, slugs: list[str]) -> Path:
    """Write a deck directory with multiple slides."""
    deck = tmp_path / "deck"
    (deck / "slides").mkdir(parents=True)
    (deck / "specs").mkdir()
    (deck / "deck.json").write_text(json.dumps({
        "template": "blank-dark.pptx",
        "fonts": {"fullwidth": "Meiryo", "halfwidth": "Arial"},
        "defaultTextColor": "#FFFFFF",
    }))
    outline_lines = [f"- [{s}] Slide {s}\n" for s in slugs]
    (deck / "specs" / "outline.md").write_text("".join(outline_lines))
    for s in slugs:
        (deck / "slides" / f"{s}.json").write_text(json.dumps({
            "layout": "Blank",
            "elements": [
                {"type": "textbox", "text": f"Content of {s}",
                 "x": 100, "y": 100, "width": 800, "height": 80, "fontSize": 28},
            ],
        }, ensure_ascii=False))
    return deck


class TestAssembleSlidesOnlySlugs:
    """Unit tests for _assemble_slides_from_dir with only_slugs."""

    def test_none_returns_all_slides(self, tmp_path):
        deck = _make_multi_slide_deck(tmp_path, ["title", "intro", "details", "closing"])
        _, slides = _assemble_slides_from_dir(deck, only_slugs=None)
        assert len(slides) == 4
        assert [s["id"] for s in slides] == ["title", "intro", "details", "closing"]

    def test_single_slug_filter(self, tmp_path):
        deck = _make_multi_slide_deck(tmp_path, ["title", "intro", "details", "closing"])
        _, slides = _assemble_slides_from_dir(deck, only_slugs={"intro"})
        assert len(slides) == 1
        assert slides[0]["id"] == "intro"

    def test_multiple_slugs_preserves_outline_order(self, tmp_path):
        deck = _make_multi_slide_deck(tmp_path, ["title", "intro", "details", "closing"])
        _, slides = _assemble_slides_from_dir(deck, only_slugs={"closing", "title"})
        assert len(slides) == 2
        assert [s["id"] for s in slides] == ["title", "closing"]

    def test_nonexistent_slug_is_ignored(self, tmp_path):
        deck = _make_multi_slide_deck(tmp_path, ["title", "intro"])
        _, slides = _assemble_slides_from_dir(deck, only_slugs={"title", "nonexistent"})
        assert len(slides) == 1
        assert slides[0]["id"] == "title"

    def test_empty_set_returns_no_slides(self, tmp_path):
        deck = _make_multi_slide_deck(tmp_path, ["title", "intro"])
        _, slides = _assemble_slides_from_dir(deck, only_slugs=set())
        assert len(slides) == 0


class TestGenerateOnlySlugs:
    """Integration tests: generate() with only_slugs produces correct PPTX."""

    def test_generate_single_slug(self, tmp_path):
        deck = _make_multi_slide_deck(tmp_path, ["title", "intro", "details"])
        out_pptx = tmp_path / "out.pptx"
        result = generate(deck, output_path=out_pptx, only_slugs={"intro"})
        assert result["slide_count"] == 1
        assert Path(result["output_path"]).exists()

    def test_generate_multiple_slugs(self, tmp_path):
        """Task 9: multiple slug batch (Consistency review scenario)."""
        deck = _make_multi_slide_deck(tmp_path, ["title", "intro", "details", "closing"])
        out_pptx = tmp_path / "out.pptx"
        result = generate(deck, output_path=out_pptx, only_slugs={"title", "details", "closing"})
        assert result["slide_count"] == 3

    def test_generate_none_builds_all(self, tmp_path):
        """Backward compatibility: only_slugs=None builds everything."""
        deck = _make_multi_slide_deck(tmp_path, ["title", "intro", "details"])
        out_pptx = tmp_path / "out.pptx"
        result = generate(deck, output_path=out_pptx, only_slugs=None)
        assert result["slide_count"] == 3

    def test_generate_iso_produces_valid_pptx(self, tmp_path):
        """Task 8: iso.pptx resolves template/assets correctly with only_slugs."""
        deck = _make_multi_slide_deck(tmp_path, ["title", "intro", "details"])
        iso_pptx = tmp_path / "iso.pptx"
        result = generate(deck, output_path=iso_pptx, only_slugs={"details"})
        assert Path(result["output_path"]).exists()
        assert Path(result["output_path"]).stat().st_size > 0
        assert result["slide_count"] == 1
