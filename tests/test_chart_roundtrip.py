# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Chart round-trip tests: chart JSON → PPTX (generate) → JSON (pptx_to_json).

Covers the builder (``engine/builder/elements/chart.py``) and the extractor
(``engine/converter/chart.py``) together: chart types, series, categories,
axes, labels and colours must come back as they went in. Style options the
extractor does not read back are checked on the generated chart XML instead.
"""

import json
import re
from pathlib import Path

import pytest
from pptx import Presentation

from sdpm.api import generate
from sdpm.engine.converter.pipeline import pptx_to_json
from sdpm.engine.schema.chart import chart_fingerprint
from sdpm.engine.schema.minimal import minimize
from test_roundtrip import _make_deck, _roundtrip

_C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_HEX = re.compile(r"^#[0-9A-F]{6}$")


def _chart(**props) -> dict:
    return {"type": "chart", "x": 100, "y": 100, "width": 800, "height": 500, **props}


def _charts(slide: dict) -> list[dict]:
    return [e for e in slide["elements"] if e["type"] == "chart"]


def _one_chart(tmp_path: Path, **props) -> dict:
    charts = _charts(_roundtrip(tmp_path, [_chart(**props)]))
    assert len(charts) == 1
    return charts[0]


def _built_chart(tmp_path: Path, **props):
    """Generate a one-chart deck and return the python-pptx chart object."""
    deck = _make_deck(tmp_path, [_chart(**props)])
    out = tmp_path / "out.pptx"
    generate(deck, output_path=out)
    frames = [s for s in Presentation(str(out)).slides[0].shapes if s.has_chart]
    assert len(frames) == 1
    return frames[0].chart


TWO_SERIES = [
    {"name": "p50", "values": [12, 45, 89], "color": "#FF9900"},
    {"name": "p99", "values": [34, 120, 250], "color": "#41B3FF"},
]


class TestChartTypes:
    @pytest.mark.parametrize("stacked,horizontal", [
        (False, False), (True, False), (False, True), (True, True),
    ])
    def test_bar_variants(self, tmp_path, stacked, horizontal):
        ch = _one_chart(tmp_path, chartType="bar", stacked=stacked, horizontal=horizontal,
                        categories=["Lambda", "ECS", "EC2"], series=TWO_SERIES)
        assert ch["chartType"] == "bar"
        assert ch.get("stacked", False) is stacked
        assert ch.get("horizontal", False) is horizontal

    @pytest.mark.parametrize("markers", [True, False])
    def test_line_markers(self, tmp_path, markers):
        ch = _one_chart(tmp_path, chartType="line", markers=markers,
                        categories=["Q1", "Q2"], series=[{"name": "r", "values": [1.5, 2.5]}])
        assert ch["chartType"] == "line"
        assert ch.get("markers", True) is markers

    def test_pie(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="pie", categories=["A", "B", "C"],
                        series=[{"name": "share", "values": [20, 30, 50]}])
        assert ch["chartType"] == "pie"
        assert "valueAxis" not in ch and "categoryAxis" not in ch

    def test_donut_hole_size(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="donut", categories=["A", "B"],
                        series=[{"name": "s", "values": [30, 70]}], holeSize=60)
        assert ch["chartType"] == "donut"
        assert ch["holeSize"] == 60

    def test_geometry(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A"],
                        series=[{"name": "s", "values": [1]}])
        assert (ch["x"], ch["y"], ch["width"], ch["height"]) == (100, 100, 800, 500)


class TestSeriesAndCategories:
    def test_names_values_categories(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["Lambda", "ECS", "EC2"],
                        series=TWO_SERIES)
        assert ch["categories"] == ["Lambda", "ECS", "EC2"]
        assert [s["name"] for s in ch["series"]] == ["p50", "p99"]
        assert [s["values"] for s in ch["series"]] == [[12, 45, 89], [34, 120, 250]]

    def test_non_ascii_and_float_values(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="line", categories=["一月", "二月"],
                        series=[{"name": "売上", "values": [1.25, -3.5]}])
        assert ch["categories"] == ["一月", "二月"]
        assert ch["series"][0]["name"] == "売上"
        assert ch["series"][0]["values"] == [1.25, -3.5]

    def test_missing_categories_get_placeholders(self, tmp_path):
        # Donut charts are often written without categories; the builder fills them in.
        ch = _one_chart(tmp_path, chartType="donut", series=[{"name": "s", "values": [1, 2, 3]}])
        assert ch["categories"] == ["Cat1", "Cat2", "Cat3"]


class TestColors:
    def test_bar_series_colors(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A", "B", "C"], series=TWO_SERIES)
        assert [s["color"] for s in ch["series"]] == ["#FF9900", "#41B3FF"]

    def test_line_series_color(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="line", categories=["A", "B"],
                        series=[{"name": "s", "values": [1, 2], "color": "#00FF00"}])
        assert ch["series"][0]["color"] == "#00FF00"

    def test_default_colors_are_distinct_theme_colors(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A"],
                        series=[{"name": "a", "values": [1]}, {"name": "b", "values": [2]}])
        colors = [s["color"] for s in ch["series"]]
        assert all(_HEX.match(c) for c in colors)
        assert colors[0] != colors[1]

    def test_bar_point_colors(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A", "B", "C"],
                        series=[{"name": "s", "values": [1, 2, 3], "pointColors": {"2": "#123456"}}])
        assert ch["series"][0]["pointColors"] == {"2": "#123456"}

    def test_pie_colors_come_back_as_point_colors(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="pie", categories=["A", "B"],
                        series=[{"name": "s", "values": [30, 70], "colors": ["#FF0000", "#00FF00"]}])
        assert ch["series"][0]["pointColors"] == {"0": "#FF0000", "1": "#00FF00"}

    def test_pie_point_colors_survive_minimal_rebuild(self, tmp_path):
        # minimal output drops _chartXml, so the rebuild runs the builder on the
        # extracted keys alone: pointColors (what the extractor emits) must be honoured.
        first = _one_chart(tmp_path / "a", chartType="pie", categories=["A", "B"],
                           series=[{"name": "s", "values": [30, 70], "colors": ["#FF0000", "#00FF00"]}])
        [clean] = minimize([first])
        assert "_chartXml" not in clean
        again = _one_chart(tmp_path / "b", **{k: v for k, v in clean.items() if k != "type"})
        assert again["series"][0]["pointColors"] == {"0": "#FF0000", "1": "#00FF00"}

    def test_gradient_point_xml(self, tmp_path):
        grad = (f'<c:spPr xmlns:c="{_C[1:-1]}" xmlns:a="{_A[1:-1]}"><a:gradFill><a:gsLst>'
                '<a:gs pos="0"><a:srgbClr val="FF0000"/></a:gs>'
                '<a:gs pos="100000"><a:srgbClr val="0000FF"/></a:gs>'
                '</a:gsLst></a:gradFill></c:spPr>')
        ch = _one_chart(tmp_path, chartType="bar", categories=["A", "B"],
                        series=[{"name": "s", "values": [1, 2], "_pointXml": {"1": grad}}])
        point_xml = ch["series"][0]["_pointXml"]
        assert list(point_xml) == ["1"]
        assert "gradFill" in point_xml["1"] and "0000FF" in point_xml["1"]


class TestTitleAndLabels:
    def test_title_text_color_size(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A"], series=[{"name": "s", "values": [1]}],
                        title="Latency", titleFontColor="#112233", titleFontSize=20)
        assert ch["title"] == "Latency"
        assert ch["titleFontColor"] == "#112233"
        assert ch["titleFontSize"] == 20

    def test_no_title(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A"], series=[{"name": "s", "values": [1]}])
        assert "title" not in ch

    def test_bar_data_labels_number_format(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A", "B", "C"], series=TWO_SERIES,
                        dataLabels=True, numberFormat="$#,##0")
        assert ch["dataLabels"] is True
        assert ch["numberFormat"] == "$#,##0"

    def test_pie_data_labels_default_to_percent(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="pie", categories=["A", "B"],
                        series=[{"name": "s", "values": [1, 3]}], dataLabels=True)
        assert ch["dataLabels"] is True
        assert ch["numberFormat"] == "0%"

    def test_pie_value_labels(self, tmp_path):
        chart = _built_chart(tmp_path, chartType="pie", categories=["A", "B"],
                             series=[{"name": "s", "values": [1, 3]}], dataLabels=True, numberFormat="#,##0")
        dl = chart.plots[0].data_labels
        assert dl.show_value is True and dl.show_percentage is False

    def test_no_data_labels(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A"], series=[{"name": "s", "values": [1]}])
        assert "dataLabels" not in ch


class TestLegend:
    def test_single_series_bar_hides_legend(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A"], series=[{"name": "s", "values": [1]}])
        assert ch["legend"] is False

    def test_single_series_bar_legend_on_request(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A"], series=[{"name": "s", "values": [1]}],
                        legend=True)
        assert ch["legend"] is True

    def test_multi_series_legend_off(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A", "B", "C"], series=TWO_SERIES, legend=False)
        assert ch["legend"] is False

    @pytest.mark.parametrize("position,expected", [
        ("top", "TOP"), ("left", "LEFT"), ("right", "RIGHT"), (None, "BOTTOM"), ("nowhere", "BOTTOM"),
    ])
    def test_legend_position(self, tmp_path, position, expected):
        style = {"legendPosition": position} if position else {}
        chart = _built_chart(tmp_path, chartType="bar", categories=["A", "B", "C"], series=TWO_SERIES,
                             style=style)
        assert chart.legend.position.name == expected


class TestAxes:
    def test_value_axis_settings(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A", "B"],
                        series=[{"name": "s", "values": [1, 2]}],
                        valueAxis={"min": 0, "max": 10, "majorUnit": 2, "gridlines": False,
                                   "line": "none", "tickMark": "none"},
                        categoryAxis={"tickMark": "none"})
        assert ch["valueAxis"] == {"min": 0, "max": 10, "majorUnit": 2, "gridlines": False,
                                   "line": "none", "tickMark": "none"}
        assert ch["categoryAxis"]["tickMark"] == "none"

    def test_default_axes_have_value_gridlines(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="line", categories=["A", "B"], series=[{"name": "s", "values": [1, 2]}])
        assert "valueAxis" not in ch  # gridlines on, no scaling: nothing to record

    def test_gridline_and_axis_style(self, tmp_path):
        chart = _built_chart(tmp_path, chartType="bar", categories=["A", "B"],
                             series=[{"name": "s", "values": [1, 2]}],
                             style={"gridlineColor": "#ABCDEF", "gridlineWidth": 1, "gridlineDash": "dot",
                                    "axisColor": "#010203", "axisWidth": 2, "fontColor": "#334455",
                                    "fontSize": 12})
        cs = chart._chartSpace
        gl_ln = cs.find(f".//{_C}valAx/{_C}majorGridlines/{_C}spPr/{_A}ln")
        assert gl_ln.get("w") == "12700"
        assert gl_ln.find(f"{_A}solidFill/{_A}srgbClr").get("val") == "ABCDEF"
        assert gl_ln.find(f"{_A}prstDash").get("val") == "dot"
        for ax in ("valAx", "catAx"):
            ln = cs.find(f".//{_C}{ax}/{_C}spPr/{_A}ln")
            assert ln.get("w") == "25400"
            assert ln.find(f"{_A}solidFill/{_A}srgbClr").get("val") == "010203"
        assert chart.value_axis.tick_labels.font.size.pt == 12
        assert cs.find(f".//{_C}minorGridlines") is None

    def test_explicit_gridlines_true_keeps_styled_gridlines(self, tmp_path):
        chart = _built_chart(tmp_path, chartType="bar", categories=["A"], series=[{"name": "s", "values": [1]}],
                             valueAxis={"gridlines": True, "max": 5})
        assert chart.value_axis.has_major_gridlines
        assert chart.value_axis.maximum_scale == 5

    def test_chart_font_size_applies_with_axis_defs(self, tmp_path):
        chart = _built_chart(tmp_path, chartType="bar", categories=["A"], series=[{"name": "s", "values": [1]}],
                             valueAxis={"max": 5}, dataLabels=True, _chartFontSize=1400)
        assert chart.value_axis.tick_labels.font.size.pt == 14
        assert chart.plots[0].data_labels.font.size.pt == 14


class TestBarAndLineStyle:
    def test_gap_width_and_overlap(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A", "B", "C"], series=TWO_SERIES,
                        gapWidth=50, overlap=20)
        assert (ch["gapWidth"], ch["overlap"]) == (50, 20)

    @pytest.mark.parametrize("stacked,expected", [(False, 80), (True, 60)])
    def test_default_gap_width(self, tmp_path, stacked, expected):
        ch = _one_chart(tmp_path, chartType="bar", stacked=stacked, categories=["A", "B", "C"], series=TWO_SERIES)
        assert ch["gapWidth"] == expected

    def test_style_gap_width(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A", "B", "C"], series=TWO_SERIES,
                        style={"gapWidth": 120})
        assert ch["gapWidth"] == 120

    def test_line_width_marker_size(self, tmp_path):
        chart = _built_chart(tmp_path, chartType="line", categories=["A", "B"],
                             series=[{"name": "s", "values": [1, 2], "color": "#00FF00"}],
                             style={"lineWidth": 4, "markerSize": 11})
        series = chart.plots[0].series[0]
        assert series.format.line.width.pt == 4
        assert series.marker.size == 11
        assert series.marker.style.name == "CIRCLE"

    def test_smooth_is_written(self, tmp_path):
        chart = _built_chart(tmp_path, chartType="line", categories=["A", "B"],
                             series=[{"name": "s", "values": [1, 2]}], smooth=True)
        smooth = chart._chartSpace.find(f".//{_C}ser/{_C}smooth")
        assert smooth is not None and smooth.get("val") == "1"

    def test_smooth_round_trips(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="line", categories=["A", "B"],
                        series=[{"name": "s", "values": [1, 2]}], smooth=True)
        assert ch.get("smooth") is True

    def test_not_smooth_is_not_recorded(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="line", categories=["A", "B"],
                        series=[{"name": "s", "values": [1, 2]}])
        assert "smooth" not in ch


class TestRebuildFromExtracted:
    """The extractor keeps the whole chart XML in ``_chartXml``; rebuilding restores it
    while the structured fields still match ``_chartFingerprint``."""

    def test_second_round_trip_is_stable(self, tmp_path):
        first = _one_chart(tmp_path / "a", chartType="bar", categories=["A", "B", "C"], series=TWO_SERIES,
                           title="T", dataLabels=True, numberFormat="#,##0")
        assert "<c:barChart>" in first["_chartXml"]
        again = _one_chart(tmp_path / "b", **{k: v for k, v in first.items() if k != "type"})
        for key in ("chartType", "categories", "series", "title", "dataLabels", "numberFormat", "legend"):
            assert again[key] == first[key], key

    def test_user_shapes_survive(self, tmp_path):
        first = _one_chart(tmp_path / "a", chartType="bar", categories=["A"], series=[{"name": "s", "values": [1]}])
        drawing = ('<c:userShapes xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
                   'xmlns:cdr="http://schemas.openxmlformats.org/drawingml/2006/chartDrawing"/>')
        props = {k: v for k, v in first.items() if k != "type"}
        props["_chartUserShapes"] = drawing
        again = _one_chart(tmp_path / "b", **props)
        assert again["_chartUserShapes"] == drawing

    def test_edited_values_win_over_chart_xml(self, tmp_path):
        first = _one_chart(tmp_path / "a", chartType="bar", categories=["A", "B"],
                           series=[{"name": "s", "values": [1, 2]}])
        props = {k: v for k, v in first.items() if k != "type"}
        props["categories"] = ["X", "Y"]
        props["series"][0]["values"] = [7, 9]
        again = _one_chart(tmp_path / "b", **props)
        assert again["categories"] == ["X", "Y"]
        assert again["series"][0]["values"] == [7, 9]

    def test_edited_title_and_color_win_over_chart_xml(self, tmp_path):
        first = _one_chart(tmp_path / "a", chartType="line", categories=["A", "B"], title="Old",
                           series=[{"name": "s", "values": [1, 2], "color": "#FF0000"}], smooth=True)
        props = {k: v for k, v in first.items() if k != "type"}
        props["title"] = "New"
        props["series"][0]["color"] = "#00FF00"
        again = _one_chart(tmp_path / "b", **props)
        assert again["title"] == "New"
        assert again["series"][0]["color"] == "#00FF00"
        assert again["smooth"] is True

    def _tagged(self, tmp_path: Path) -> dict:
        """Extracted chart whose _chartXml title differs from its JSON title."""
        out = _one_chart(tmp_path, chartType="bar", categories=["A", "B"], title="JSON",
                         series=[{"name": "s", "values": [1, 2]}])
        assert ">JSON<" in out["_chartXml"]
        out["_chartXml"] = out["_chartXml"].replace(">JSON<", ">FROM_XML<")
        return {k: v for k, v in out.items() if k != "type"}

    def test_unedited_chart_restores_chart_xml(self, tmp_path):
        props = self._tagged(tmp_path / "a")
        props["x"] += 50  # geometry is not chart content
        props["series"][0]["values"] = [1.0, 2.0]  # same numbers, other spelling
        assert _one_chart(tmp_path / "b", **props)["title"] == "FROM_XML"

    def test_chart_xml_without_fingerprint_is_restored(self, tmp_path):
        # JSON extracted before the fingerprint existed keeps the old behaviour
        props = self._tagged(tmp_path / "a")
        del props["_chartFingerprint"]
        props["title"] = "Edited"
        assert _one_chart(tmp_path / "b", **props)["title"] == "FROM_XML"

    def test_edit_skips_chart_xml(self, tmp_path):
        props = self._tagged(tmp_path / "a")
        props["title"] = "Edited"
        assert _one_chart(tmp_path / "b", **props)["title"] == "Edited"

    def test_fingerprint_survives_the_written_json(self, tmp_path):
        # what an agent edits is the slide file on disk, not the in-memory dict
        deck = _make_deck(tmp_path, [_chart(chartType="line", categories=["A", "B"], smooth=True,
                                            series=[{"name": "s", "values": [1.5, 2]}])])
        generate(deck, output_path=tmp_path / "out.pptx")
        pptx_to_json(tmp_path / "out.pptx", tmp_path / "x")
        [slide_file] = (tmp_path / "x" / "slides").glob("slide-*.json")
        [ch] = _charts(json.loads(slide_file.read_text()))
        assert ch["_chartFingerprint"] == chart_fingerprint(ch)

    def test_broken_chart_xml_falls_back_to_normal_build(self, tmp_path, capsys):
        ch = _one_chart(tmp_path, chartType="line", categories=["A", "B"],
                        series=[{"name": "s", "values": [1, 2], "color": "#00FF00"}], _chartXml="<not xml")
        assert "chart XML restore failed" in capsys.readouterr().err
        assert ch["chartType"] == "line"
        assert ch["series"][0]["color"] == "#00FF00"

    def test_user_shapes_survive_an_edit(self, tmp_path):
        props = self._tagged(tmp_path / "a")
        props["_chartUserShapes"] = _USER_SHAPES
        props["title"] = "Edited"
        again = _one_chart(tmp_path / "b", **props)
        assert again["title"] == "Edited"  # built from its JSON
        assert again["_chartUserShapes"] == _USER_SHAPES

    def test_built_chart_is_rebuildable(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A"], series=[{"name": "s", "values": [1]}])
        assert "_chartRebuildable" not in ch


_USER_SHAPES = ('<c:userShapes xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
                'xmlns:cdr="http://schemas.openxmlformats.org/drawingml/2006/chartDrawing"/>')


def _plot_tags(pptx: Path) -> list[str]:
    """Plot element names (barChart, areaChart…) of the chart on a PPTX's last slide."""
    [frame] = [s for s in list(Presentation(str(pptx)).slides)[-1].shapes if s.has_chart]
    plot_area = frame.chart._chartSpace.find(f".//{_C}plotArea")
    return [el.tag.removeprefix(_C) for el in plot_area if el.tag.endswith("Chart")]


def _foreign_chart_pptx(path: Path, kind: str) -> Path:
    """A one-chart PPTX of a kind sdpm's chartType cannot describe."""
    from copy import deepcopy

    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches

    def add(prs, chart_type):
        data = CategoryChartData()
        data.categories = ["A", "B"]
        data.add_series("s", (1, 2))
        slide = prs.slides.add_slide(prs.slide_layouts[-1])
        return slide.shapes.add_chart(chart_type, Inches(1), Inches(1), Inches(6), Inches(4), data).chart

    template = Path(__file__).parent.parent / "sdpm" / "templates" / "blank-dark.pptx"
    prs = Presentation(str(template))
    if kind == "combo":
        # a clustered column chart with a line plot on the same axes
        chart = add(prs, XL_CHART_TYPE.COLUMN_CLUSTERED)
        line = deepcopy(add(Presentation(str(template)), XL_CHART_TYPE.LINE)._chartSpace.find(f".//{_C}lineChart"))
        bar = chart._chartSpace.find(f".//{_C}barChart")
        for mine, theirs in zip(line.findall(f"{_C}axId"), bar.findall(f"{_C}axId")):
            mine.set("val", theirs.get("val"))
        bar.addnext(line)
    else:
        add(prs, {"area": XL_CHART_TYPE.AREA, "radar": XL_CHART_TYPE.RADAR,
                  "stacked100": XL_CHART_TYPE.COLUMN_STACKED_100}[kind])
    prs.save(str(path))
    return path


class TestChartsTheJsonCannotDescribe:
    """A chart read back as a type chartType does not have (area, radar, 100% stacked,
    combo) keeps its ``_chartXml`` when edited, instead of turning into a bar chart."""

    def _extract(self, tmp_path: Path, kind: str) -> tuple[dict, list[str]]:
        tmp_path.mkdir(parents=True)
        source = _foreign_chart_pptx(tmp_path / "in.pptx", kind)
        out = pptx_to_json(source, tmp_path / "x")
        [ch] = _charts(out["slides"][-1])
        return ch, _plot_tags(source)

    def _build(self, tmp_path: Path, elem: dict) -> tuple[dict, list[str]]:
        deck = _make_deck(tmp_path, [elem])
        result = generate(deck, output_path=tmp_path / "out.pptx")
        return result, _plot_tags(tmp_path / "out.pptx")

    @pytest.mark.parametrize("kind", ["area", "radar", "stacked100", "combo"])
    def test_edited_chart_keeps_its_type(self, tmp_path, kind):
        ch, original = self._extract(tmp_path / "a", kind)
        assert ch["_chartRebuildable"] is False
        ch["series"][0]["values"] = [5, 6]
        result, plots = self._build(tmp_path / "b", ch)
        assert plots == original
        rules = [d["rule"] for d in result.get("errors", {}).get("lintDiagnostics", [])]
        assert "chart-edit-ignored" in rules

    def test_unedited_chart_has_no_diagnostic(self, tmp_path):
        ch, original = self._extract(tmp_path / "a", "area")
        result, plots = self._build(tmp_path / "b", ch)
        assert plots == original
        assert "errors" not in result

    def test_without_chart_xml_it_is_built_from_json(self, tmp_path):
        ch, _ = self._extract(tmp_path / "a", "area")
        ch["series"][0]["values"] = [5, 6]
        del ch["_chartXml"]
        result, plots = self._build(tmp_path / "b", ch)
        assert plots == ["barChart"]
        assert "errors" not in result

    def test_empty_chart_keeps_its_xml(self, tmp_path):
        ch = _one_chart(tmp_path / "a", chartType="line", series=[])
        assert ch["_chartRebuildable"] is False
        ch["series"][0]["values"] = [5]  # the dummy series the extractor adds
        _, plots = self._build(tmp_path / "b", {k: v for k, v in ch.items()})
        assert plots == ["lineChart"]
        [frame] = [s for s in Presentation(str(tmp_path / "b" / "out.pptx")).slides[0].shapes if s.has_chart]
        assert frame.chart._chartSpace.findall(f".//{_C}ser") == []


class TestInvalidInput:
    def test_unknown_chart_type_degrades_to_bar(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="scatter", categories=["A"], series=[{"name": "s", "values": [1]}])
        assert ch["chartType"] == "bar"

    def test_unsupported_combination_drops_flag(self, tmp_path):
        # pie has no stacked/horizontal variant: the flags are ignored, the type kept
        ch = _one_chart(tmp_path, chartType="pie", stacked=True, horizontal=True, categories=["A", "B"],
                        series=[{"name": "s", "values": [1, 2]}])
        assert ch["chartType"] == "pie"
        assert "stacked" not in ch and "horizontal" not in ch

    def test_line_stacked_has_no_variant(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="line", stacked=True, categories=["A"], series=[{"name": "s", "values": [1]}])
        assert ch["chartType"] == "line"
        assert "stacked" not in ch

    def test_short_values_are_kept_short(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A", "B", "C"], series=[{"name": "s", "values": [1]}])
        assert ch["categories"] == ["A", "B", "C"]
        assert ch["series"][0]["values"] == [1]

    def test_missing_values_round_trip_as_none(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="line", categories=["A", "B"],
                        series=[{"name": "s", "values": [1, None]}])
        assert ch["series"][0]["values"] == [1, None]

    def test_no_series_keeps_an_empty_chart(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", series=[])
        # extractor's decorative-chart path: dummy series so the builder can rebuild it
        assert ch["series"] == [{"name": "", "values": [1]}]
        assert "_chartXml" in ch

    def test_bad_point_color_index_is_ignored(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A"],
                        series=[{"name": "s", "values": [1], "pointColors": {"9": "#123456"}}])
        assert ch["series"][0]["values"] == [1]

    def test_bad_point_xml_is_ignored(self, tmp_path):
        ch = _one_chart(tmp_path, chartType="bar", categories=["A"],
                        series=[{"name": "s", "values": [1], "_pointXml": {"0": "<broken"}}])
        assert ch["series"][0]["values"] == [1]

    def test_invalid_series_color_is_an_error(self, tmp_path):
        deck = _make_deck(tmp_path, [_chart(chartType="bar", categories=["A"],
                                            series=[{"name": "s", "values": [1], "color": "red"}])])
        with pytest.raises(ValueError):
            generate(deck, output_path=tmp_path / "out.pptx")


def test_extracted_chart_is_json_serialisable(tmp_path):
    ch = _one_chart(tmp_path, chartType="donut", categories=["A", "B"],
                    series=[{"name": "s", "values": [1, 2]}], holeSize=50, dataLabels=True)
    json.dumps(ch)
    out = pptx_to_json(tmp_path / "out.pptx", tmp_path / "again")
    assert _charts(out["slides"][0])[0]["holeSize"] == 50
