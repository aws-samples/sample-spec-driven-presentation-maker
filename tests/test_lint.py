# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for sdpm.schema.lint."""

import pytest
from sdpm.schema.lint import lint


class TestLintLine:
    """Line element linting."""

    def test_valid_line(self):
        slides = [{"elements": [
            {"type": "line", "x1": 80, "y1": 350, "x2": 700, "y2": 350}
        ]}]
        assert lint(slides) == []

    def test_valid_polyline(self):
        slides = [{"elements": [
            {"type": "line", "points": [[100, 200], [300, 400]], "arrowEnd": "triangle"}
        ]}]
        assert lint(slides) == []

    def test_bbox_keys_instead_of_x1y1(self):
        slides = [{"elements": [
            {"type": "line", "x": 80, "y": 350, "x2": 700, "y2": 350}
        ]}]
        diags = lint(slides)
        assert len(diags) == 1
        assert diags[0]["rule"] == "line-bbox-keys"
        assert "x1/y1" in diags[0]["message"]

    def test_missing_coords(self):
        slides = [{"elements": [
            {"type": "line", "color": "#FF0000"}
        ]}]
        diags = lint(slides)
        assert any(d["rule"] == "line-missing-coords" for d in diags)

    def test_partial_coords(self):
        slides = [{"elements": [
            {"type": "line", "x1": 80, "y1": 350}
        ]}]
        diags = lint(slides)
        assert any(d["rule"] == "line-missing-coord" and "x2" in d["message"] for d in diags)

    def test_invalid_arrow(self):
        slides = [{"elements": [
            {"type": "line", "x1": 0, "y1": 0, "x2": 100, "y2": 100, "arrowEnd": "bad"}
        ]}]
        diags = lint(slides)
        assert any(d["rule"] == "line-invalid-arrowEnd" for d in diags)

    def test_invalid_dash(self):
        slides = [{"elements": [
            {"type": "line", "x1": 0, "y1": 0, "x2": 100, "y2": 100, "dashStyle": "dotdot"}
        ]}]
        diags = lint(slides)
        assert any(d["rule"] == "line-invalid-dashStyle" for d in diags)

    def test_invalid_connector(self):
        slides = [{"elements": [
            {"type": "line", "x1": 0, "y1": 0, "x2": 100, "y2": 100, "connectorType": "zigzag"}
        ]}]
        diags = lint(slides)
        assert any(d["rule"] == "line-invalid-connectorType" for d in diags)

    def test_points_too_few(self):
        slides = [{"elements": [
            {"type": "line", "points": [[100, 200]]}
        ]}]
        diags = lint(slides)
        assert any(d["rule"] == "line-points-invalid" for d in diags)


class TestLintShape:
    """Shape element linting."""

    def test_valid_shape(self):
        slides = [{"elements": [
            {"type": "shape", "shape": "rectangle", "x": 0, "y": 0, "width": 100, "height": 50}
        ]}]
        assert lint(slides) == []

    def test_unknown_shape(self):
        slides = [{"elements": [
            {"type": "shape", "shape": "banana", "x": 0, "y": 0}
        ]}]
        diags = lint(slides)
        assert any(d["rule"] == "shape-unknown-name" for d in diags)

    def test_missing_position(self):
        slides = [{"elements": [
            {"type": "shape", "shape": "rectangle", "width": 100}
        ]}]
        diags = lint(slides)
        assert any("missing 'x'" in d["message"] for d in diags)


class TestLintTextbox:
    """Textbox element linting."""

    def test_missing_height(self):
        slides = [{"elements": [
            {"type": "textbox", "x": 0, "y": 0, "width": 100, "text": "hi"}
        ]}]
        diags = lint(slides)
        assert any(d["rule"] == "textbox-missing-height" for d in diags)

    def test_valid_textbox(self):
        slides = [{"elements": [
            {"type": "textbox", "x": 0, "y": 0, "width": 100, "height": 40, "text": "hi"}
        ]}]
        assert lint(slides) == []


class TestLintImage:
    """Image element linting."""

    def test_missing_src(self):
        slides = [{"elements": [
            {"type": "image", "x": 0, "y": 0, "width": 100}
        ]}]
        diags = lint(slides)
        assert any(d["rule"] == "image-missing-src" for d in diags)


class TestLintCommon:
    """Common checks."""

    def test_missing_type(self):
        slides = [{"elements": [{"x": 0, "y": 0}]}]
        diags = lint(slides)
        assert any(d["rule"] == "missing-type" for d in diags)

    def test_invalid_opacity(self):
        slides = [{"elements": [
            {"type": "shape", "shape": "rectangle", "x": 0, "y": 0, "opacity": 1.5}
        ]}]
        diags = lint(slides)
        assert any(d["rule"] == "invalid-opacity" for d in diags)

    def test_presentation_dict_format(self):
        """lint accepts presentation dict with 'slides' key."""
        data = {"slides": [{"elements": [
            {"type": "line", "x": 80, "y": 350, "x2": 700, "y2": 350}
        ]}]}
        diags = lint(data)
        assert len(diags) == 1
        assert diags[0]["rule"] == "line-bbox-keys"

    def test_multiple_slides(self):
        slides = [
            {"elements": [{"type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 10}]},
            {"elements": [{"type": "line", "x": 0, "y": 0, "x2": 10, "y2": 10}]},
        ]
        diags = lint(slides)
        assert len(diags) == 1
        assert diags[0]["slide"] == 1

    def test_empty_slides(self):
        assert lint([]) == []
        assert lint({"slides": []}) == []
