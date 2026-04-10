# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for sdpm.schema.lint."""

from sdpm.schema.lint import lint


# ===================================================================
# line
# ===================================================================

class TestLintLine:
    def test_valid_line(self):
        assert lint([{"elements": [
            {"type": "line", "x1": 80, "y1": 350, "x2": 700, "y2": 350}
        ]}]) == []

    def test_valid_polyline(self):
        assert lint([{"elements": [
            {"type": "line", "points": [[100, 200], [300, 400]], "arrowEnd": "triangle"}
        ]}]) == []

    def test_bbox_keys(self):
        diags = lint([{"elements": [
            {"type": "line", "x": 80, "y": 350, "x2": 700, "y2": 350}
        ]}])
        assert len(diags) == 1
        assert diags[0]["rule"] == "line-bbox-keys"

    def test_missing_coords(self):
        diags = lint([{"elements": [{"type": "line", "color": "#FF0000"}]}])
        assert any(d["rule"] == "line-missing-coords" for d in diags)

    def test_partial_coords(self):
        diags = lint([{"elements": [{"type": "line", "x1": 80, "y1": 350}]}])
        assert any(d["rule"] == "line-missing-coord" and "x2" in d["message"] for d in diags)

    def test_invalid_arrow(self):
        diags = lint([{"elements": [
            {"type": "line", "x1": 0, "y1": 0, "x2": 100, "y2": 100, "arrowEnd": "bad"}
        ]}])
        assert any(d["rule"] == "line-invalid-arrowEnd" for d in diags)

    def test_invalid_dash(self):
        diags = lint([{"elements": [
            {"type": "line", "x1": 0, "y1": 0, "x2": 100, "y2": 100, "dashStyle": "dotdot"}
        ]}])
        assert any(d["rule"] == "line-invalid-dashStyle" for d in diags)

    def test_invalid_connector(self):
        diags = lint([{"elements": [
            {"type": "line", "x1": 0, "y1": 0, "x2": 100, "y2": 100, "connectorType": "zigzag"}
        ]}])
        assert any(d["rule"] == "line-invalid-connectorType" for d in diags)

    def test_points_too_few(self):
        diags = lint([{"elements": [{"type": "line", "points": [[100, 200]]}]}])
        assert any(d["rule"] == "line-points-invalid" for d in diags)


# ===================================================================
# shape
# ===================================================================

class TestLintShape:
    def test_valid(self):
        assert lint([{"elements": [
            {"type": "shape", "shape": "rectangle", "x": 0, "y": 0, "width": 100, "height": 50}
        ]}]) == []

    def test_unknown_name(self):
        diags = lint([{"elements": [
            {"type": "shape", "shape": "banana", "x": 0, "y": 0}
        ]}])
        assert any(d["rule"] == "shape-unknown-name" for d in diags)

    def test_missing_position(self):
        diags = lint([{"elements": [{"type": "shape", "shape": "rectangle", "width": 100}]}])
        assert any("missing 'x'" in d["message"] for d in diags)


# ===================================================================
# textbox
# ===================================================================

class TestLintTextbox:
    def test_missing_height(self):
        diags = lint([{"elements": [
            {"type": "textbox", "x": 0, "y": 0, "width": 100, "text": "hi"}
        ]}])
        assert any(d["rule"] == "textbox-missing-height" for d in diags)

    def test_valid(self):
        assert lint([{"elements": [
            {"type": "textbox", "x": 0, "y": 0, "width": 100, "height": 40, "text": "hi"}
        ]}]) == []


# ===================================================================
# image
# ===================================================================

class TestLintImage:
    def test_missing_src(self):
        diags = lint([{"elements": [{"type": "image", "x": 0, "y": 0, "width": 100}]}])
        assert any(d["rule"] == "image-missing-src" for d in diags)

    def test_valid(self):
        assert lint([{"elements": [
            {"type": "image", "src": "assets:aws/Lambda_48", "x": 0, "y": 0, "width": 100}
        ]}]) == []


# ===================================================================
# chart
# ===================================================================

class TestLintChart:
    def _base(self, **overrides):
        elem = {
            "type": "chart", "chartType": "bar", "x": 0, "y": 0,
            "width": 800, "height": 400,
            "categories": ["A", "B"], "series": [{"name": "S1", "values": [1, 2]}],
        }
        elem.update(overrides)
        return [{"elements": [elem]}]

    def test_valid(self):
        assert lint(self._base()) == []

    def test_missing_chartType(self):
        slides = self._base()
        del slides[0]["elements"][0]["chartType"]
        diags = lint(slides)
        assert any(d["rule"] == "chart-missing-chartType" for d in diags)

    def test_invalid_chartType(self):
        diags = lint(self._base(chartType="scatter"))
        assert any(d["rule"] == "chart-invalid-chartType" for d in diags)

    def test_missing_series(self):
        diags = lint(self._base(series=[]))
        assert any(d["rule"] == "chart-missing-series" for d in diags)

    def test_series_values_mismatch(self):
        diags = lint(self._base(
            categories=["A", "B", "C"],
            series=[{"name": "S1", "values": [1, 2]}],
        ))
        assert any(d["rule"] == "chart-series-values-mismatch" for d in diags)

    def test_holeSize_wrong_type(self):
        diags = lint(self._base(chartType="bar", holeSize=50))
        assert any(d["rule"] == "chart-holeSize-wrong-type" for d in diags)

    def test_holeSize_donut_ok(self):
        diags = lint(self._base(chartType="donut", holeSize=50))
        assert not any(d["rule"] == "chart-holeSize-wrong-type" for d in diags)

    def test_stacked_wrong_type(self):
        diags = lint(self._base(chartType="pie", stacked=True))
        assert any(d["rule"] == "chart-stacked-wrong-type" for d in diags)

    def test_stacked_bar_ok(self):
        diags = lint(self._base(chartType="bar", stacked=True))
        assert not any(d["rule"] == "chart-stacked-wrong-type" for d in diags)


# ===================================================================
# table
# ===================================================================

class TestLintTable:
    def _base(self, **overrides):
        elem = {
            "type": "table", "x": 0, "y": 0, "width": 800, "height": 200,
            "headers": ["A", "B", "C"],
            "rows": [["1", "2", "3"], ["4", "5", "6"]],
        }
        elem.update(overrides)
        return [{"elements": [elem]}]

    def test_valid(self):
        assert lint(self._base()) == []

    def test_missing_headers(self):
        slides = self._base()
        del slides[0]["elements"][0]["headers"]
        diags = lint(slides)
        assert any(d["rule"] == "table-missing-headers" for d in diags)

    def test_missing_rows(self):
        slides = self._base()
        del slides[0]["elements"][0]["rows"]
        diags = lint(slides)
        assert any(d["rule"] == "table-missing-rows" for d in diags)

    def test_colWidths_mismatch(self):
        diags = lint(self._base(colWidths=[100, 200]))
        assert any(d["rule"] == "table-column-count-mismatch" for d in diags)

    def test_row_column_mismatch(self):
        diags = lint(self._base(rows=[["1", "2"]]))
        assert any(d["rule"] == "table-column-count-mismatch" for d in diags)


# ===================================================================
# freeform
# ===================================================================

class TestLintFreeform:
    def test_valid(self):
        assert lint([{"elements": [
            {"type": "freeform", "x": 0, "y": 0, "width": 100, "height": 100,
             "path": [{"cmd": "M", "x": 0, "y": 0}, {"cmd": "L", "x": 100, "y": 100}]}
        ]}]) == []

    def test_missing_path(self):
        diags = lint([{"elements": [
            {"type": "freeform", "x": 0, "y": 0, "width": 100, "height": 100}
        ]}])
        assert any(d["rule"] == "freeform-missing-path" for d in diags)

    def test_no_moveTo(self):
        diags = lint([{"elements": [
            {"type": "freeform", "x": 0, "y": 0, "width": 100, "height": 100,
             "path": [{"cmd": "L", "x": 100, "y": 100}]}
        ]}])
        assert any(d["rule"] == "freeform-no-moveTo" for d in diags)

    def test_invalid_cmd(self):
        diags = lint([{"elements": [
            {"type": "freeform", "x": 0, "y": 0, "width": 100, "height": 100,
             "path": [{"cmd": "M", "x": 0, "y": 0}, {"cmd": "X", "x": 50, "y": 50}]}
        ]}])
        assert any(d["rule"] == "freeform-invalid-cmd" for d in diags)

    def test_customGeometry_ok(self):
        diags = lint([{"elements": [
            {"type": "freeform", "x": 0, "y": 0, "width": 100, "height": 100,
             "customGeometry": "<xml/>"}
        ]}])
        assert not any(d["rule"] == "freeform-missing-path" for d in diags)


# ===================================================================
# include
# ===================================================================

class TestLintInclude:
    def test_valid(self):
        assert lint([{"elements": [{"type": "include", "src": "arch.json"}]}]) == []

    def test_missing_src(self):
        diags = lint([{"elements": [{"type": "include"}]}])
        assert any(d["rule"] == "include-missing-src" for d in diags)


# ===================================================================
# video
# ===================================================================

class TestLintVideo:
    def test_valid(self):
        assert lint([{"elements": [
            {"type": "video", "src": "demo.mp4", "x": 0, "y": 0, "width": 800, "height": 450}
        ]}]) == []

    def test_missing_src(self):
        diags = lint([{"elements": [
            {"type": "video", "x": 0, "y": 0, "width": 800, "height": 450}
        ]}])
        assert any(d["rule"] == "video-missing-src" for d in diags)


# ===================================================================
# Common checks
# ===================================================================

class TestLintCommon:
    def test_missing_type(self):
        diags = lint([{"elements": [{"x": 0, "y": 0}]}])
        assert any(d["rule"] == "missing-type" for d in diags)

    def test_invalid_opacity(self):
        diags = lint([{"elements": [
            {"type": "shape", "shape": "rectangle", "x": 0, "y": 0, "opacity": 1.5}
        ]}])
        assert any(d["rule"] == "invalid-opacity" for d in diags)

    def test_valid_opacity(self):
        diags = lint([{"elements": [
            {"type": "shape", "shape": "rectangle", "x": 0, "y": 0, "opacity": 0.5}
        ]}])
        assert not any(d["rule"] == "invalid-opacity" for d in diags)

    # fontSize
    def test_fontSize_integer_ok(self):
        assert lint([{"elements": [
            {"type": "textbox", "x": 0, "y": 0, "width": 100, "height": 40, "fontSize": 14}
        ]}]) == []

    def test_fontSize_10_5_ok(self):
        assert lint([{"elements": [
            {"type": "textbox", "x": 0, "y": 0, "width": 100, "height": 40, "fontSize": 10.5}
        ]}]) == []

    def test_fontSize_non_integer_float(self):
        diags = lint([{"elements": [
            {"type": "textbox", "x": 0, "y": 0, "width": 100, "height": 40, "fontSize": 11.5}
        ]}])
        assert any(d["rule"] == "invalid-fontSize" for d in diags)

    def test_fontSize_zero(self):
        diags = lint([{"elements": [
            {"type": "textbox", "x": 0, "y": 0, "width": 100, "height": 40, "fontSize": 0}
        ]}])
        assert any(d["rule"] == "invalid-fontSize" for d in diags)

    def test_fontSize_negative(self):
        diags = lint([{"elements": [
            {"type": "textbox", "x": 0, "y": 0, "width": 100, "height": 40, "fontSize": -12}
        ]}])
        assert any(d["rule"] == "invalid-fontSize" for d in diags)

    # color
    def test_invalid_color_short(self):
        diags = lint([{"elements": [
            {"type": "shape", "shape": "rectangle", "x": 0, "y": 0, "fill": "#FFF"}
        ]}])
        assert any(d["rule"] == "invalid-color" for d in diags)

    def test_valid_color(self):
        diags = lint([{"elements": [
            {"type": "shape", "shape": "rectangle", "x": 0, "y": 0, "fill": "#FF9900"}
        ]}])
        assert not any(d["rule"] == "invalid-color" for d in diags)

    def test_color_none_ok(self):
        diags = lint([{"elements": [
            {"type": "shape", "shape": "rectangle", "x": 0, "y": 0, "fill": "none"}
        ]}])
        assert not any(d["rule"] == "invalid-color" for d in diags)

    # align
    def test_invalid_align(self):
        diags = lint([{"elements": [
            {"type": "textbox", "x": 0, "y": 0, "width": 100, "height": 40, "align": "justify"}
        ]}])
        assert any(d["rule"] == "invalid-align" for d in diags)

    def test_invalid_verticalAlign(self):
        diags = lint([{"elements": [
            {"type": "shape", "shape": "rectangle", "x": 0, "y": 0, "verticalAlign": "center"}
        ]}])
        assert any(d["rule"] == "invalid-verticalAlign" for d in diags)

    # out-of-bounds
    def test_out_of_bounds_x(self):
        diags = lint([{"elements": [
            {"type": "shape", "shape": "rectangle", "x": 1800, "y": 0, "width": 200, "height": 50}
        ]}])
        assert any(d["rule"] == "out-of-bounds" for d in diags)

    def test_out_of_bounds_y(self):
        diags = lint([{"elements": [
            {"type": "shape", "shape": "rectangle", "x": 0, "y": 1000, "width": 100, "height": 100}
        ]}])
        assert any(d["rule"] == "out-of-bounds" for d in diags)

    def test_within_bounds(self):
        diags = lint([{"elements": [
            {"type": "shape", "shape": "rectangle", "x": 0, "y": 0, "width": 1920, "height": 1080}
        ]}])
        assert not any(d["rule"] == "out-of-bounds" for d in diags)

    # presentation dict format
    def test_presentation_dict(self):
        diags = lint({"slides": [{"elements": [
            {"type": "line", "x": 80, "y": 350, "x2": 700, "y2": 350}
        ]}]})
        assert any(d["rule"] == "line-bbox-keys" for d in diags)

    def test_multiple_slides(self):
        diags = lint([
            {"elements": [{"type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 10}]},
            {"elements": [{"type": "line", "x": 0, "y": 0, "x2": 10, "y2": 10}]},
        ])
        assert len([d for d in diags if d["rule"] == "line-bbox-keys"]) == 1
        assert diags[0]["slide"] == 1

    def test_empty(self):
        assert lint([]) == []
        assert lint({"slides": []}) == []
