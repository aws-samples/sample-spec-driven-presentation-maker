# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for sdpm.checks.overlay_textbox."""

from __future__ import annotations

from sdpm.checks.overlay_textbox import check_overlay_textbox


def _shape(**overrides):
    base = {
        "type": "shape",
        "shape": "rounded_rectangle",
        "x": 100,
        "y": 200,
        "width": 200,
        "height": 100,
    }
    base.update(overrides)
    return base


def _textbox(**overrides):
    base = {
        "type": "textbox",
        "x": 100,
        "y": 200,
        "width": 200,
        "height": 100,
        "text": "label",
    }
    base.update(overrides)
    return base


class TestOverlayDetected:
    def test_exact_match_no_text_in_shape(self):
        slides = {
            "slides": [
                {"id": "s1", "elements": [_shape(), _textbox()]},
            ]
        }
        warnings = check_overlay_textbox(slides)

        assert warnings, "expected an overlay warning"
        assert "overlay textbox detected" in warnings[0]
        body = "\n".join(warnings[1:])
        assert "page01(s1)" in body
        assert "elements=[0, 1]" in body
        assert "merge text into shape's `text` property" in body

    def test_exact_match_both_carry_text(self):
        """Both elements have non-empty text → suggest dropping the textbox."""
        slides = {
            "slides": [
                {"elements": [_shape(text="A"), _textbox(text="B")]},
            ]
        }
        warnings = check_overlay_textbox(slides)
        body = "\n".join(warnings[1:])
        assert "drop the textbox" in body

    def test_within_tolerance_is_flagged(self):
        """Elements within ±2px on every dimension are still flagged."""
        slides = {
            "slides": [
                {
                    "elements": [
                        _shape(x=100, y=200, width=200, height=100),
                        _textbox(x=101, y=199, width=202, height=98),
                    ]
                }
            ]
        }
        warnings = check_overlay_textbox(slides)
        assert warnings, "tolerance-overlapping pair should be flagged"

    def test_outside_tolerance_not_flagged(self):
        slides = {
            "slides": [
                {
                    "elements": [
                        _shape(x=100, y=200, width=200, height=100),
                        _textbox(x=110, y=200, width=200, height=100),
                    ]
                }
            ]
        }
        assert check_overlay_textbox(slides) == []


class TestOverlayNotDetected:
    def test_shape_with_text_no_textbox(self):
        """The recommended pattern emits no warnings."""
        slides = {
            "slides": [
                {"elements": [_shape(text="label", fontSize=20)]},
            ]
        }
        assert check_overlay_textbox(slides) == []

    def test_separate_textbox_below_shape(self):
        slides = {
            "slides": [
                {
                    "elements": [
                        _shape(),
                        _textbox(y=320),  # well outside the shape's box
                    ]
                }
            ]
        }
        assert check_overlay_textbox(slides) == []

    def test_two_shapes_same_box_not_flagged(self):
        """Only shape+textbox pairs are checked."""
        slides = {
            "slides": [
                {"elements": [_shape(), _shape()]},
            ]
        }
        assert check_overlay_textbox(slides) == []

    def test_empty_text_treated_as_no_text(self):
        slides = {
            "slides": [
                {"elements": [_shape(text=""), _textbox(text="label")]},
            ]
        }
        warnings = check_overlay_textbox(slides)
        body = "\n".join(warnings[1:])
        # shape text is empty → suggest merge, not drop
        assert "merge text into shape's `text` property" in body


class TestEdgeCases:
    def test_empty_slides(self):
        assert check_overlay_textbox({"slides": []}) == []

    def test_missing_slides_key(self):
        assert check_overlay_textbox({}) == []

    def test_slide_without_elements(self):
        assert check_overlay_textbox({"slides": [{"id": "s1"}]}) == []

    def test_non_list_elements_ignored(self):
        assert check_overlay_textbox({"slides": [{"elements": "oops"}]}) == []

    def test_element_missing_dimensions_skipped(self):
        slides = {
            "slides": [
                {
                    "elements": [
                        {"type": "shape", "x": 100, "y": 200},  # no width/height
                        _textbox(),
                    ]
                }
            ]
        }
        assert check_overlay_textbox(slides) == []

    def test_multiple_overlays_across_slides(self):
        slides = {
            "slides": [
                {"id": "first", "elements": [_shape(), _textbox()]},
                {"elements": [_shape(text="ok")]},
                {"id": "third", "elements": [_shape(), _textbox()]},
            ]
        }
        warnings = check_overlay_textbox(slides)
        body = "\n".join(warnings[1:])
        assert "page01(first)" in body
        assert "page03(third)" in body
        assert "page02" not in body  # shape with text alone, no textbox
