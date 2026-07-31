# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Round-trip tests: JSON → PPTX (generate) → JSON (pptx_to_json).

Detects silent data loss in the build/convert pipeline: an element that
generates without error but disappears (or loses key properties) on
re-extraction would previously go unnoticed.
"""

import json
import re
from pathlib import Path

import pytest

from sdpm.api import generate
from sdpm.engine.converter.pipeline import pptx_to_json


def _make_deck(tmp_path: Path, elements: list[dict], notes: str | None = None) -> Path:
    """Write a minimal single-slide deck directory."""
    deck = tmp_path / "deck"
    (deck / "slides").mkdir(parents=True)
    (deck / "specs").mkdir()
    (deck / "deck.json").write_text(json.dumps({
        "template": "blank-dark.pptx",
        "fonts": {"fullwidth": "Meiryo", "halfwidth": "Arial"},
        "defaultTextColor": "#FFFFFF",
    }))
    (deck / "specs" / "outline.md").write_text("- [s1] test slide\n")
    slide: dict = {"layout": "Blank", "elements": elements}
    if notes is not None:
        slide["notes"] = notes
    (deck / "slides" / "s1.json").write_text(json.dumps(slide, ensure_ascii=False))
    return deck


def _roundtrip(tmp_path: Path, elements: list[dict], notes: str | None = None) -> dict:
    """generate → pptx_to_json → first slide dict."""
    deck = _make_deck(tmp_path, elements, notes)
    out_pptx = tmp_path / "out.pptx"
    result = generate(deck, output_path=out_pptx)
    assert result["slide_count"] == 1
    extracted = pptx_to_json(out_pptx, tmp_path / "extracted")
    # On-disk output is deck-structure (deck.json + slides/slide-NN.json)
    assert (tmp_path / "extracted" / "deck.json").exists()
    slide_files = sorted((tmp_path / "extracted" / "slides").glob("slide-*.json"))
    assert len(slide_files) == 1
    # In-memory return keeps the all-in-one {slides: [...]} shape
    assert len(extracted["slides"]) == 1
    return extracted["slides"][0]


def _plain_text(extracted_text: str) -> str:
    """Strip inline formatting markers like {{font=Arial:...}} from extracted text."""
    return re.sub(r"\{\{[^:}]+:([^}]*)\}\}", r"\1", extracted_text)


class TestTextboxRoundTrip:
    def test_text_and_geometry_survive(self, tmp_path):
        slide = _roundtrip(tmp_path, [
            {"type": "textbox", "text": "Hello Round Trip", "x": 100, "y": 100,
             "width": 800, "height": 80, "fontSize": 32},
        ])
        boxes = [e for e in slide["elements"] if e["type"] == "textbox"]
        assert len(boxes) == 1
        tb = boxes[0]
        assert _plain_text(tb["text"]) == "Hello Round Trip"
        assert tb["fontSize"] == 32
        assert (tb["x"], tb["y"], tb["width"], tb["height"]) == (100, 100, 800, 80)

    def test_font_color_survives(self, tmp_path):
        slide = _roundtrip(tmp_path, [
            {"type": "textbox", "text": "Colored", "x": 0, "y": 0,
             "width": 400, "height": 60, "fontSize": 20, "fontColor": "#FF8800"},
        ])
        tb = [e for e in slide["elements"] if e["type"] == "textbox"][0]
        assert json.dumps(tb).count("#FF8800") >= 1


class TestShapeRoundTrip:
    def test_shape_type_and_fill_survive(self, tmp_path):
        slide = _roundtrip(tmp_path, [
            {"type": "shape", "shape": "rounded_rectangle", "x": 100, "y": 300,
             "width": 300, "height": 150, "fill": "#4A90D9"},
        ])
        shapes = [e for e in slide["elements"] if e["type"] == "shape"]
        assert len(shapes) == 1
        assert shapes[0]["shape"] == "rounded_rectangle"
        assert shapes[0]["fill"] == "#4A90D9"

    def test_shape_text_survives(self, tmp_path):
        slide = _roundtrip(tmp_path, [
            {"type": "shape", "shape": "oval", "x": 50, "y": 50,
             "width": 200, "height": 200, "fill": "#112233", "text": "In Shape"},
        ])
        shapes = [e for e in slide["elements"] if e["type"] == "shape"]
        assert "In Shape" in _plain_text(json.dumps(shapes[0], ensure_ascii=False))

    def test_shape_font_color_survives(self, tmp_path):
        # The converter has always emitted fontColor for shapes; the builder
        # used to silently drop it (text rendered in theme color instead).
        slide = _roundtrip(tmp_path, [
            {"type": "shape", "shape": "rectangle", "x": 100, "y": 100,
             "width": 300, "height": 120, "fill": "#EEEEEE",
             "text": "Colored", "fontSize": 20, "fontColor": "#B22222"},
        ])
        shapes = [e for e in slide["elements"] if e["type"] == "shape"]
        flat = json.dumps(shapes[0], ensure_ascii=False).upper()
        assert "#B22222" in flat


class TestLineRoundTrip:
    def test_line_survives(self, tmp_path):
        slide = _roundtrip(tmp_path, [
            {"type": "line", "x1": 100, "y1": 100, "x2": 500, "y2": 100,
             "color": "#00FF00", "lineWidth": 2},
        ])
        lines = [e for e in slide["elements"] if e["type"] == "line"]
        assert len(lines) == 1
        assert lines[0].get("color", "").upper() == "#00FF00"


class TestTableRoundTrip:
    def test_table_cells_survive(self, tmp_path):
        slide = _roundtrip(tmp_path, [
            {"type": "table", "x": 100, "y": 100, "width": 600, "height": 200,
             "rows": [["H1", "H2"], ["a", "b"]]},
        ])
        tables = [e for e in slide["elements"] if e["type"] == "table"]
        assert len(tables) == 1
        flat = _plain_text(json.dumps(tables[0], ensure_ascii=False))
        for cell in ("H1", "H2", "a", "b"):
            assert cell in flat


class TestNotesRoundTrip:
    def test_speaker_notes_survive(self, tmp_path):
        slide = _roundtrip(
            tmp_path,
            [{"type": "textbox", "text": "x", "x": 0, "y": 0, "width": 100, "height": 40}],
            notes="Speaker notes here",
        )
        assert slide.get("notes") == "Speaker notes here"


class TestMultiElementRoundTrip:
    def test_element_count_preserved(self, tmp_path):
        elements = [
            {"type": "textbox", "text": "One", "x": 0, "y": 0, "width": 300, "height": 50},
            {"type": "shape", "shape": "rectangle", "x": 0, "y": 100, "width": 200, "height": 100, "fill": "#333333"},
            {"type": "line", "x1": 0, "y1": 300, "x2": 400, "y2": 300, "color": "#FFFFFF"},
        ]
        slide = _roundtrip(tmp_path, elements)
        assert len(slide["elements"]) == len(elements), (
            f"element count changed: sent {len(elements)}, "
            f"got back {[e['type'] for e in slide['elements']]}"
        )


class TestUnknownShapeIsNotSilentlyDropped:
    """Guard: an element that produces nothing in the PPTX must surface somehow.

    Currently _add_shape returns silently when the 'shape' key is missing —
    this test documents the resulting data loss so a future fix (lint rule
    or builder warning) can flip the expectation.
    """

    def test_missing_shape_key_drops_element(self, tmp_path):
        slide = _roundtrip(tmp_path, [
            {"type": "textbox", "text": "keeper", "x": 0, "y": 0, "width": 300, "height": 50},
            {"type": "shape", "x": 0, "y": 100, "width": 200, "height": 100, "fill": "#333333"},
        ])
        # The shape without a 'shape' key vanishes from the PPTX today.
        assert len(slide["elements"]) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
