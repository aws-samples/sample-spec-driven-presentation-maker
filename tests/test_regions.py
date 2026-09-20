# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for live-preview layout region extraction."""

from sdpm.engine.schema import extract_regions


def test_extracts_named_and_content_regions_with_size_aliases():
    slide = {
        "elements": [
            {"_comment": "region: hero", "x": 10, "y": 20, "w": 300, "h": 200},
            {"_comment": " content region ", "x": 40.5, "y": 50, "width": 600, "height": 400},
            {"_comment": "REGION: sidebar", "x": 700, "y": 50, "w": 200, "height": 800},
        ]
    }

    assert extract_regions(slide) == [
        {"name": "hero", "x": 10, "y": 20, "w": 300, "h": 200},
        {"name": "content", "x": 40.5, "y": 50, "w": 600, "h": 400},
        {"name": "sidebar", "x": 700, "y": 50, "w": 200, "h": 800},
    ]


def test_skips_malformed_regions_and_unrelated_elements():
    slide = {
        "elements": [
            {"_comment": "region: ", "x": 0, "y": 0, "w": 1, "h": 1},
            {"_comment": "region: missing-height", "x": 0, "y": 0, "w": 1},
            {"_comment": "region: string-bound", "x": "0", "y": 0, "w": 1, "h": 1},
            {"_comment": "region: boolean-bound", "x": False, "y": 0, "w": 1, "h": 1},
            {"_comment": "region: infinite-bound", "x": 0, "y": 0, "w": float("inf"), "h": 1},
            {"_comment": "layout note", "x": 0, "y": 0, "w": 1, "h": 1},
            None,
        ]
    }

    assert extract_regions(slide) == []


def test_returns_empty_for_slides_without_an_element_list():
    assert extract_regions({}) == []
    assert extract_regions({"elements": "invalid"}) == []
    assert extract_regions(None) == []  # type: ignore[arg-type]


def test_builder_skips_region_comments_silently(tmp_path, capsys) -> None:
    import json

    from sdpm import api, tools

    r = tools.init_presentation(str(tmp_path / "deck"))
    deck = r.get("output_dir", str(tmp_path / "deck"))
    api.apply_style(deck, "elegant-dark", "blank-dark")
    (tmp_path / "deck" / "specs" / "outline.md").write_text(
        "# O\n\n## A\n- [one] T\n  - body: b\n  - visual: v\n  - evidence: e\n"
    )
    (tmp_path / "deck" / "slides" / "one.json").write_text(json.dumps({
        "layout": "Title Only", "placeholders": {"title": "Hello"}, "notes": "",
        "elements": [{"_comment": "region: body", "x": 96, "y": 210, "w": 1728, "h": 640},
                     {"_comment": "--- section ---"}],
    }))
    capsys.readouterr()
    tools.generate_pptx(deck)
    assert "unknown element type" not in capsys.readouterr().err
