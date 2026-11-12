# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Element round-trip tests: shape, freeform, line, textbox, group and image.

JSON → PPTX (generate) → JSON (pptx_to_json), as in ``test_roundtrip.py``,
covering the builder (``engine/builder/elements/*``, ``formatting.py``) and
the extractor (``engine/converter/elements/*``) together. A property must
come back as it went in; a property the extractor does not read back is
checked on the generated XML instead. Known losses are ``xfail(strict=True)``
so a fix flips them.
"""

from pathlib import Path

import pytest
from lxml import etree
from PIL import Image
from pptx import Presentation

from sdpm.api import generate
from sdpm.engine.builder.elements.shape import ShapeMixin
from test_roundtrip import _make_deck, _plain_text, _roundtrip

_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"

GRADIENT = {"angle": 45, "stops": [{"position": 0, "color": "#FF0000"},
                                   {"position": 1, "color": "#0000FF"}]}


def _of_type(slide: dict, kind: str) -> list[dict]:
    return [e for e in slide["elements"] if e["type"] == kind]


def _one(tmp_path: Path, elem: dict) -> dict:
    """Round-trip a single element and return the one element that comes back."""
    elements = _roundtrip(tmp_path, [elem])["elements"]
    assert len(elements) == 1, [e["type"] for e in elements]
    return elements[0]


def _built_shapes(tmp_path: Path, elements: list[dict]) -> list:
    """Generate a one-slide deck and return its python-pptx shapes."""
    deck = _make_deck(tmp_path, elements)
    out = tmp_path / "out.pptx"
    generate(deck, output_path=out)
    return list(Presentation(str(out)).slides[0].shapes)


def _tags(el) -> list[str]:
    return [c.tag.split("}")[1] for c in el]


def _shape(**props) -> dict:
    return {"type": "shape", "shape": "rectangle", "x": 100, "y": 100,
            "width": 300, "height": 200, "fill": "#123456", **props}


def _prst_dash(sp) -> str | None:
    el = sp._element.spPr.find(f"{_A}ln/{_A}prstDash")
    return None if el is None else el.get("val")


def _assert_dash_stable(tmp_path: Path, elem: dict) -> None:
    """Build, extract, rebuild: both builds must carry the same prstDash."""
    (first,) = _built_shapes(tmp_path / "first", [elem])
    extracted = _one(tmp_path / "rt", elem)
    (second,) = _built_shapes(tmp_path / "second", [extracted])
    assert _prst_dash(first) is not None
    assert _prst_dash(second) == _prst_dash(first)


def _png(path: Path, size=(400, 200)) -> Path:
    Image.new("RGB", size, "red").save(path)
    return path


# ── shape ────────────────────────────────────────────────────────────────

class TestShapePresets:
    @pytest.mark.parametrize("name", [
        "arrow_right", "chevron", "cylinder", "callout_oval", "flowchart_decision",
        "star_5_point", "cloud", "left_brace", "pie_wedge",
    ])
    def test_named_preset_survives(self, tmp_path, name):
        assert _one(tmp_path, _shape(shape=name))["shape"] == name

    def test_unknown_name_passes_through_as_raw_preset(self, tmp_path):
        # Names outside the friendly map are written verbatim as prstGeom.
        (sp,) = _built_shapes(tmp_path, [_shape(shape="heart")])
        assert sp._element.spPr.find(f"{_A}prstGeom").get("prst") == "heart"
        assert _one(tmp_path / "rt", _shape(shape="heart"))["shape"] == "heart"

    def test_circle_is_squared_to_the_shorter_side(self, tmp_path):
        out = _one(tmp_path, _shape(shape="circle", width=300, height=200))
        assert (out["width"], out["height"]) == (200, 200)

    def test_adjustments_survive(self, tmp_path):
        out = _one(tmp_path, _shape(shape="rounded_rectangle", adjustments=[0.3]))
        assert out["adjustments"] == [0.3]

    def test_arc_round_trip_is_stable(self, tmp_path):
        # Counter-clockwise arc: the extractor rewrites it as the equivalent
        # clockwise [start, sweep], which rebuilds the same geometry.
        out = _one(tmp_path, _shape(shape="arc", fill="none", line="#FFFFFF",
                                    adjustments=[0, 90, False]))
        assert out["adjustments"] == [270.0, 90.0]

    def test_block_arc_round_trip_is_stable(self, tmp_path):
        elem = _shape(shape="block_arc", adjustments=[270, "50%", 0.2])
        out = _one(tmp_path / "rt", elem)
        assert out["adjustments"] == [270.0, 180.0, 0.2]
        (first,) = _built_shapes(tmp_path / "first", [elem])
        (second,) = _built_shapes(tmp_path / "second", [out])
        assert list(second.adjustments) == list(first.adjustments)


class TestArcAdjustmentConversion:
    """``_convert_arc_adjustments``: [start, sweep, …] → OOXML adj (deg × 0.6)."""

    def test_clockwise_arc(self):
        assert ShapeMixin._convert_arc_adjustments("arc", [270, 90]) == [162.0, 0.0]

    def test_counter_clockwise_arc_swaps_ends(self):
        assert ShapeMixin._convert_arc_adjustments("arc", [0, 90, False]) == [162.0, 0.0]

    def test_percent_sweep(self):
        assert ShapeMixin._convert_arc_adjustments("arc", [0, "25%"]) == [0.0, 54.0]

    def test_block_arc_default_thickness(self):
        assert ShapeMixin._convert_arc_adjustments("block_arc", [0, 180]) == [0.0, 108.0, 0.25]

    def test_block_arc_thickness_and_direction(self):
        assert ShapeMixin._convert_arc_adjustments(
            "block_arc", [90, 90, 0.1, False]) == [0.0, 54.0, 0.1]

    def test_too_short_is_returned_unchanged(self):
        assert ShapeMixin._convert_arc_adjustments("arc", [45]) == [45]


class TestShapeFill:
    def test_linear_gradient_survives(self, tmp_path):
        out = _one(tmp_path, _shape(fill=None, gradient=GRADIENT))
        assert out["gradient"]["angle"] == 45
        assert [s["color"] for s in out["gradient"]["stops"]] == ["#FF0000", "#0000FF"]
        assert "fill" not in out

    def test_radial_gradient_survives(self, tmp_path):
        grad = {"type": "circle", "stops": GRADIENT["stops"],
                "fillToRect": {"l": 50000, "t": 50000, "r": 50000, "b": 50000}}
        out = _one(tmp_path, _shape(fill=None, gradient=grad))
        assert out["gradient"]["type"] == "circle"
        assert out["gradient"]["fillToRect"] == grad["fillToRect"]

    def test_opacity_survives(self, tmp_path):
        assert _one(tmp_path, _shape(opacity=0.5))["opacity"] == 0.5

    def test_pattern_fill_survives_and_precedes_line(self, tmp_path):
        patt = {"pattern": "ltDnDiag", "fgColor": "#FF0000", "bgColor": "#00FF00"}
        out = _one(tmp_path, _shape(fill=None, patternFill=patt, line="#FFFFFF"))
        assert out["patternFill"] == patt
        (sp,) = _built_shapes(tmp_path / "xml", [_shape(fill=None, patternFill=patt, line="#FFFFFF")])
        tags = _tags(sp._element.spPr)
        assert tags.index("pattFill") < tags.index("ln")

    def test_fill_none_is_transparent(self, tmp_path):
        assert _one(tmp_path, _shape(fill="none", line="#FFFFFF"))["fill"] == "none"


class TestShapeLine:
    def test_color_and_width_survive(self, tmp_path):
        out = _one(tmp_path, _shape(line="#FFFFFF", lineWidth=3))
        assert (out["line"], out["lineWidth"]) == ("#FFFFFF", 3.0)

    @pytest.mark.parametrize("dash", ["dash", "dot", "square_dot", "sysDashDot"])
    def test_dash_style_survives_a_second_build(self, tmp_path, dash):
        # The extractor writes the OOXML name (dot → sysDot); what matters is
        # that rebuilding the extracted JSON draws the same dash.
        _assert_dash_stable(tmp_path, _shape(line="#FFFFFF", dashStyle=dash))

    def test_line_gradient_survives(self, tmp_path):
        out = _one(tmp_path, _shape(lineGradient=GRADIENT, lineWidth=3))
        assert [s["color"] for s in out["lineGradient"]["stops"]] == ["#FF0000", "#0000FF"]
        assert out["lineWidth"] == 3.0

    def test_no_line_by_default(self, tmp_path):
        assert _one(tmp_path, _shape())["line"] == "none"


class TestShapeTransformAndLink:
    def test_rotation_and_flips_survive(self, tmp_path):
        out = _one(tmp_path, _shape(rotation=30, flipH=True, flipV=True))
        assert (out["rotation"], out["flipH"], out["flipV"]) == (30.0, True, True)

    def test_link_survives(self, tmp_path):
        assert _one(tmp_path, _shape(link="https://example.com"))["link"] == "https://example.com"

    def test_arrow_heads_survive(self, tmp_path):
        out = _one(tmp_path, _shape(shape="arc", fill="none", line="#FFFFFF",
                                    arrowStart="triangle", arrowEnd="oval"))
        assert (out["arrowStart"], out["arrowEnd"]) == ("triangle", "oval")

    def test_no_theme_style_when_effects_off(self, tmp_path):
        (sp,) = _built_shapes(tmp_path, [_shape(_noEffects=True)])
        assert sp._element.find(f"{_P}style") is None
        assert sp._element.spPr.find(f"{_A}effectLst") is not None


class TestShapeText:
    def test_items_become_bullets(self, tmp_path):
        out = _one(tmp_path, _shape(items=["one", "two"], align="left", verticalAlign="top",
                                    marginLeft=10))
        assert [_plain_text(t) for t in out["items"]] == ["one", "two"]
        assert (out["align"], out["verticalAlign"], out["marginLeft"]) == ("left", "top", 10)

    def test_multiline_text_survives(self, tmp_path):
        out = _one(tmp_path, _shape(text="first\\nsecond", fontColor="#B22222", align="right"))
        assert _plain_text(out["text"]).split("\n") == ["first", "second"]
        assert out["align"] == "right"

    def test_text_direction_and_auto_width_survive(self, tmp_path):
        out = _one(tmp_path, _shape(text="v", textDirection="vert270", autoWidth=True))
        assert (out["textDirection"], out["autoWidth"]) == ("vert270", True)

    def test_paragraph_bullet_and_alignment_written(self, tmp_path):
        (sp,) = _built_shapes(tmp_path, [_shape(paragraphs=[
            {"text": "Title", "align": "right"}, {"text": "Body", "bullet": "–"},
            {"text": "", "endFontSize": 20},
        ])])
        ps = sp.text_frame.paragraphs
        assert [p.text for p in ps] == ["Title", "Body", ""]
        assert ps[0]._p.pPr.get("algn") == "r"
        assert ps[1]._p.pPr.find(f"{_A}buChar").get("char") == "–"
        assert ps[2]._p.find(f"{_A}endParaRPr").get("sz") == "2000"

    @pytest.mark.xfail(strict=True, reason="shape paragraphs read 'bullet'; the documented "
                       "key is list: {type: disc} (slide-json-elements.md), which is ignored")
    def test_documented_paragraph_list_makes_a_bullet(self, tmp_path):
        (sp,) = _built_shapes(tmp_path, [_shape(paragraphs=[
            {"text": "Body", "list": {"type": "disc"}}])])
        assert sp.text_frame.paragraphs[0]._p.pPr is not None
        assert sp.text_frame.paragraphs[0]._p.pPr.find(f"{_A}buChar") is not None

    @pytest.mark.xfail(strict=True, reason="lineOpacity is documented for shape but only "
                       "applied to freeforms")
    def test_line_opacity(self, tmp_path):
        assert _one(tmp_path, _shape(line="#FFFFFF", lineOpacity=0.5)).get("lineOpacity") == 0.5


class TestShapeDropped:
    def test_missing_shape_key_warns(self, tmp_path, capsys):
        assert _built_shapes(tmp_path, [{"type": "shape", "x": 0, "y": 0}]) == []
        assert "without 'shape' key" in capsys.readouterr().err


# ── freeform ─────────────────────────────────────────────────────────────

def _freeform(**props) -> dict:
    return {"type": "freeform", "x": 10, "y": 10, "width": 200, "height": 200, **props}


CLOSED_PATH = [
    {"cmd": "M", "x": 0, "y": 0}, {"cmd": "L", "x": 200, "y": 0},
    {"cmd": "C", "pts": [[200, 100], [100, 200], [0, 200]]},
    {"cmd": "Q", "pts": [[50, 50], [0, 0]]}, {"cmd": "Z"},
]


class TestFreeform:
    def test_path_commands_survive(self, tmp_path):
        out = _one(tmp_path, _freeform(fill="#FF0000", path=CLOSED_PATH))
        assert out["type"] == "freeform"
        assert [c["cmd"] for c in out["path"]] == ["M", "L", "C", "Q", "Z"]
        assert out["path"][2]["pts"] == [[200.0, 100.0], [100.0, 200.0], [0.0, 200.0]]
        assert out["fill"] == "#FF0000"

    def test_open_arc_path_is_not_filled(self, tmp_path):
        arc = [{"cmd": "M", "x": 0, "y": 100},
               {"cmd": "A", "wR": 100, "hR": 100, "stAng": 180, "swAng": 180}]
        out = _one(tmp_path, _freeform(line="#00FF00", paths=[arc]))
        assert out["path"][1] == {"cmd": "A", "wR": 100.0, "hR": 100.0, "stAng": 180.0, "swAng": 180.0}
        assert out["pathFill"] == "none"

    def test_arrow_heads_survive(self, tmp_path):
        out = _one(tmp_path, _freeform(line="#00FF00", headEnd="triangle", tailEnd="oval",
                                       path=CLOSED_PATH[:2]))
        assert (out["headEnd"], out["tailEnd"]) == ("triangle", "oval")

    def test_line_opacity_and_transform_survive(self, tmp_path):
        out = _one(tmp_path, _freeform(fill="#FF0000", line="#FFFFFF", lineOpacity=0.5,
                                       rotation=90, flipV=True, path=CLOSED_PATH))
        assert (out["lineOpacity"], out["rotation"], out["flipV"]) == (0.5, 90.0, True)

    def test_gradient_survives(self, tmp_path):
        out = _one(tmp_path, _freeform(gradient=GRADIENT, line="#FFFFFF", path=CLOSED_PATH))
        assert out["gradient"]["angle"] == 45

    def test_text_survives(self, tmp_path):
        out = _one(tmp_path, _freeform(fill="#FF0000", path=CLOSED_PATH, text="hi",
                                       fontColor="#00FF00", align="right", verticalAlign="bottom"))
        assert _plain_text(out["text"]) == "hi"
        assert (out["align"], out["verticalAlign"]) == ("right", "bottom")

    def test_raw_custom_geometry_is_used(self, tmp_path):
        geom = (f'<a:custGeom xmlns:a="{_A[1:-1]}"><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>'
                '<a:rect l="l" t="t" r="r" b="b"/><a:pathLst><a:path w="100" h="100">'
                '<a:moveTo><a:pt x="0" y="0"/></a:moveTo><a:lnTo><a:pt x="100" y="100"/></a:lnTo>'
                '</a:path></a:pathLst></a:custGeom>')
        (sp,) = _built_shapes(tmp_path, [_freeform(line="#FFFFFF", customGeometry=geom)])
        sp_pr = sp._element.spPr
        assert sp_pr.find(f"{_A}prstGeom") is None
        assert _tags(sp_pr)[:2] == ["xfrm", "custGeom"]

    def test_broken_custom_geometry_warns_and_keeps_shape(self, tmp_path, capsys):
        shapes = _built_shapes(tmp_path, [_freeform(fill="#FF0000", customGeometry="<not-xml")])
        assert len(shapes) == 1
        assert "Failed to apply freeform geometry" in capsys.readouterr().err


# ── line / connector / polyline ──────────────────────────────────────────

def _line(**props) -> dict:
    return {"type": "line", "x1": 100, "y1": 400, "x2": 500, "y2": 600, "color": "#FF0000", **props}


class TestConnector:
    @pytest.mark.parametrize("kind,preset", [
        ("straight", "line"), ("elbow", "bentConnector3"), ("curved", "curvedConnector3"),
    ])
    def test_connector_type_survives(self, tmp_path, kind, preset):
        out = _one(tmp_path, _line(connectorType=kind))
        assert out.get("connectorType", "straight") == kind
        assert out["preset"] == preset
        assert (out["x1"], out["y1"], out["x2"], out["y2"]) == (100, 400, 500, 600)

    def test_vertical_first_elbow_keeps_end_points(self, tmp_path):
        out = _one(tmp_path, _line(connectorType="elbow", elbowStart="vertical"))
        assert out["elbowStart"] == "vertical"
        assert (out["x1"], out["y1"], out["x2"], out["y2"]) == (100, 400, 500, 600)

    @pytest.mark.parametrize("adj,preset", [
        ([0.3], "bentConnector3"), ([0.3, 0.7], "bentConnector4"), ([0.2, 0.5, 0.8], "bentConnector5"),
    ])
    def test_elbow_adjustments_pick_preset(self, tmp_path, adj, preset):
        out = _one(tmp_path, _line(connectorType="elbow", adjustments=adj))
        assert out["adjustments"] == adj
        assert out["preset"] == preset

    def test_arrows_with_size_survive(self, tmp_path):
        out = _one(tmp_path, _line(arrowStart="oval", arrowEnd="stealth", arrowEndWidth="lg",
                                   arrowStartLength="sm"))
        assert (out["arrowStart"], out["arrowEnd"]) == ("oval", "stealth")
        assert (out["arrowEndWidth"], out["arrowStartLength"]) == ("lg", "sm")

    @pytest.mark.parametrize("dash", ["dash", "dot", "sysDot"])
    def test_dash_style_survives_a_second_build(self, tmp_path, dash):
        _assert_dash_stable(tmp_path, _line(dashStyle=dash))

    def test_width_and_color_survive(self, tmp_path):
        out = _one(tmp_path, _line(lineWidth=2))
        assert (out["color"], out["lineWidth"]) == ("#FF0000", 2.0)

    def test_line_gradient_survives(self, tmp_path):
        out = _one(tmp_path, _line(lineGradient=GRADIENT, lineWidth=4))
        assert [s["color"] for s in out["lineGradient"]["stops"]] == ["#FF0000", "#0000FF"]
        assert out["lineWidth"] == 4.0

    def test_no_coordinates_warns_and_drops(self, tmp_path, capsys):
        assert _built_shapes(tmp_path, [{"type": "line", "x": 0, "y": 0}]) == []
        assert "without coordinates" in capsys.readouterr().err


class TestPolyline:
    def test_points_become_an_open_freeform(self, tmp_path):
        out = _one(tmp_path, _line(points=[[700, 400], [800, 450], [900, 400]], color="#0000FF",
                                   arrowStart="oval", arrowEnd="triangle"))
        assert out["type"] == "freeform"
        assert (out["x"], out["y"], out["width"], out["height"]) == (700, 400, 200, 50)
        assert [(c["x"], c["y"]) for c in out["path"]] == [(0, 0), (100, 50), (200, 0)]
        assert (out["fill"], out["line"]) == ("none", "#0000FF")
        assert (out["headEnd"], out["tailEnd"]) == ("oval", "triangle")

    def test_flat_polyline_keeps_its_points(self, tmp_path):
        out = _one(tmp_path, _line(points=[[0, 100], [200, 100]]))
        assert [(c["x"], c["y"]) for c in out["path"]] == [(0, 0), (200, 0)]


class TestLinePropertiesOrder:
    """a:ln children follow the schema sequence (PowerPoint drops what does not)."""

    _ORDER = ["solidFill", "prstDash", "headEnd", "tailEnd"]

    @pytest.mark.parametrize("elem", [
        _shape(line="#FFFFFF", arrowStart="triangle", arrowEnd="oval", dashStyle="sysDash"),
        _freeform(line="#FFFFFF", headEnd="triangle", tailEnd="oval", dashStyle="sysDash",
                  path=CLOSED_PATH[:2]),
        _line(arrowStart="triangle", arrowEnd="stealth", dashStyle="sysDot"),
        _line(points=[[0, 0], [100, 50], [200, 0]], arrowStart="oval", arrowEnd="triangle"),
    ], ids=["shape", "freeform", "connector", "polyline"])
    def test_ln_children_in_schema_order(self, tmp_path, elem):
        (sp,) = _built_shapes(tmp_path, [elem])
        tags = _tags(sp._element.spPr.find(f"{_A}ln"))
        assert tags == [t for t in self._ORDER if t in tags]
        assert {"headEnd", "tailEnd"} <= set(tags)


# ── textbox ──────────────────────────────────────────────────────────────

def _textbox(**props) -> dict:
    return {"type": "textbox", "x": 0, "y": 0, "width": 500, "height": 300, **props}


class TestTextboxParagraphs:
    def test_lists_levels_and_spacing_survive(self, tmp_path):
        out = _one(tmp_path, _textbox(fontSize=18, paragraphs=[
            {"text": "a", "list": {"type": "disc"}, "lineSpacingPct": 150000, "spaceAfter": 600},
            {"text": "b", "list": {"type": "arabicPeriod", "level": 1}, "spaceBefore": 300},
            "plain",
        ]))
        a, b, plain = out["paragraphs"]
        assert a["list"] == {"type": "disc"}
        assert (a["lineSpacingPct"], a["spaceAfter"]) == (150000, 600)
        assert b["list"] == {"type": "arabicPeriod", "level": 1}
        assert b["spaceBefore"] == 300
        assert "list" not in plain
        assert [_plain_text(p["text"]) for p in out["paragraphs"]] == ["a", "b", "plain"]

    def test_indent_and_alignment_survive(self, tmp_path):
        out = _one(tmp_path, _textbox(align="center", paragraphs=[
            {"text": "x", "marL": 457200, "indent": -228600},
            {"text": "y", "align": "right"},
        ]))
        x, y = out["paragraphs"]
        assert (x["marL"], x["indent"], x["align"]) == (457200, -228600, "center")
        assert y["align"] == "right"

    def test_line_spacing_precedes_bullets(self, tmp_path):
        (sp,) = _built_shapes(tmp_path, [_textbox(paragraphs=[
            {"text": "a", "list": {"type": "disc"}, "lineSpacingPct": 150000, "spaceBefore": 600},
            {"text": "b", "list": {"type": "arabicPeriod"}, "lineSpacingPct": 120000},
        ])])
        for p in sp.text_frame.paragraphs:
            tags = _tags(p._p.pPr)
            assert tags[0] == "lnSpc", tags

    @pytest.mark.xfail(strict=True, reason="the converter writes fixed paragraph line spacing "
                       "as 'lineSpacing' (1/100 pt), which the builder does not read")
    def test_fixed_line_spacing_survives_a_second_build(self, tmp_path):
        first = _one(tmp_path / "a", _textbox(text="one\ntwo", lineSpacingPt=24))
        (sp,) = _built_shapes(tmp_path / "b", [first])
        p_pr = sp.text_frame.paragraphs[0]._p.pPr
        assert p_pr is not None and p_pr.find(f"{_A}lnSpc/{_A}spcPts") is not None


class TestTextboxBox:
    def test_box_properties_survive(self, tmp_path):
        out = _one(tmp_path, _textbox(text="t", fill="#112233", opacity=0.4, line="#FF0000",
                                      lineWidth=2, rotation=15, flipV=True, verticalAlign="bottom",
                                      textDirection="vert270", marginTop=5, autoWidth=True))
        assert (out["fill"], out["opacity"]) == ("#112233", 0.4)
        assert (out["line"], out["lineWidth"]) == ("#FF0000", 2.0)
        assert (out["rotation"], out["flipV"]) == (15.0, True)
        assert (out["verticalAlign"], out["textDirection"]) == ("bottom", "vert270")
        assert (out["marginTop"], out["autoWidth"]) == (5, True)

    def test_text_gradient_survives(self, tmp_path):
        out = _one(tmp_path, _textbox(text="grad", fontSize=40,
                                      textGradient={"angle": 0, "stops": GRADIENT["stops"]}))
        assert out["textGradient"]["angle"] == 0
        assert [s["color"] for s in out["textGradient"]["stops"]] == ["#FF0000", "#0000FF"]

    def test_gradient_on_one_run_only(self, tmp_path):
        (sp,) = _built_shapes(tmp_path, [_textbox(
            text="plain {{bold:shiny}}",
            _textGradientRuns=[{"text": "shiny", "gradient": GRADIENT}])])
        runs = {r.text: r._r for r in sp.text_frame.paragraphs[0].runs}
        assert runs["shiny"].find(f"{_A}rPr/{_A}gradFill") is not None
        assert runs["plain "].find(f"{_A}rPr/{_A}gradFill") is None

    def test_character_spacing_and_end_paragraph_size_written(self, tmp_path):
        (sp,) = _built_shapes(tmp_path, [_textbox(text="spaced", _spc=300, _endParaSize=20)])
        p = sp.text_frame.paragraphs[0]._p
        assert p.find(f"{_A}r/{_A}rPr").get("spc") == "300"
        assert p.find(f"{_A}endParaRPr").get("sz") == "2000"


# ── group / arch-group / rawShape ────────────────────────────────────────

class TestGroup:
    def test_children_are_flattened_onto_the_slide(self, tmp_path):
        slide = _roundtrip(tmp_path, [{"type": "group", "elements": [
            _textbox(text="inside"),
            _shape(),
            _line(),
            {"type": "group", "elements": [_shape(shape="oval", fill="#00FF00")]},
        ]}])
        kinds = sorted(e["type"] for e in slide["elements"])
        assert kinds == ["line", "shape", "shape", "textbox"]

    def test_raw_group_xml_is_injected(self, tmp_path):
        src = tmp_path / "src.pptx"
        prs = Presentation()
        grp = prs.slides.add_slide(prs.slide_layouts[6]).shapes.add_group_shape()
        grp.shapes.add_textbox(0, 0, 914400, 457200).text_frame.text = "grouped"
        grp.shapes.add_textbox(914400, 0, 914400, 457200).text_frame.text = "twin"
        prs.save(str(src))
        xml = etree.tostring(grp._element, encoding="unicode")

        shapes = _built_shapes(tmp_path / "out", [{"type": "group", "_groupXml": xml}])
        assert len(shapes) == 1 and shapes[0].shape_type == 6  # GROUP
        assert sorted(s.text_frame.text for s in shapes[0].shapes) == ["grouped", "twin"]

    def test_raw_shape_is_injected(self, tmp_path):
        prs = Presentation()
        tb = prs.slides.add_slide(prs.slide_layouts[6]).shapes.add_textbox(0, 0, 914400, 457200)
        tb.text_frame.text = "verbatim"
        xml = etree.tostring(tb._element, encoding="unicode")
        shapes = _built_shapes(tmp_path, [{"type": "rawShape", "_shapeXml": xml},
                                          {"type": "rawShape"}])
        assert [s.text_frame.text for s in shapes] == ["verbatim"]


class TestArchGroup:
    def test_custom_group_without_icon_centres_its_label(self, tmp_path):
        out = _one(tmp_path, {"type": "arch-group", "groupType": "custom", "x": 100, "y": 100,
                              "width": 600, "height": 400, "label": "VPC", "color": "#8C4FFF",
                              "dashStyle": "dash"})
        assert (out["shape"], out["fill"], out["line"]) == ("rectangle", "none", "#8C4FFF")
        assert out["dashStyle"] == "dash"
        assert _plain_text(out["text"]) == "VPC"
        assert (out["align"], out["verticalAlign"]) == ("center", "top")

    def test_unknown_group_type_falls_back_to_generic(self, tmp_path):
        out = _one(tmp_path, {"type": "arch-group", "groupType": "nope", "x": 0, "y": 0,
                              "width": 300, "height": 200})
        assert out["shape"] == "rectangle"
        assert out["fill"] == "none"


# ── image ────────────────────────────────────────────────────────────────

def _image(src: Path | str, **props) -> dict:
    return {"type": "image", "src": str(src), "x": 100, "y": 100, **props}


class TestImageFit:
    def test_contain_keeps_aspect_ratio(self, tmp_path, capsys):
        out = _one(tmp_path, _image(_png(tmp_path / "wide.png"), width=200, height=200, fit="contain"))
        assert (out["width"], out["height"]) == (200, 100)
        assert "padding within the box" in capsys.readouterr().err

    def test_cover_crops_both_sides_evenly(self, tmp_path):
        out = _one(tmp_path, _image(_png(tmp_path / "wide.png"), width=200, height=200, fit="cover"))
        assert (out["width"], out["height"]) == (200, 200)
        assert out["_originalEffects"]["crop"] == {"left": 25.0, "right": 25.0}

    def test_cover_on_tall_image_crops_top_and_bottom(self, tmp_path):
        out = _one(tmp_path, _image(_png(tmp_path / "tall.png", (200, 400)), width=200, height=200,
                                    fit="cover"))
        assert out["_originalEffects"]["crop"] == {"top": 25.0, "bottom": 25.0}

    def test_width_only_derives_height(self, tmp_path):
        out = _one(tmp_path, _image(_png(tmp_path / "wide.png"), width=300))
        assert (out["width"], out["height"]) == (300, 150)

    def test_relative_src_resolves_against_deck(self, tmp_path):
        deck = _make_deck(tmp_path, [_image("pic.png", width=100)])
        _png(deck / "pic.png")
        out = tmp_path / "out.pptx"
        generate(deck, output_path=out)
        assert [s.shape_type for s in Presentation(str(out)).slides[0].shapes] == [13]  # PICTURE

    def test_missing_file_warns_and_drops(self, tmp_path, capsys):
        assert _built_shapes(tmp_path, [_image(tmp_path / "nope.png", width=10, height=10)]) == []
        assert "Image not found" in capsys.readouterr().err


class TestImageProperties:
    def test_transform_and_link_survive(self, tmp_path):
        out = _one(tmp_path, _image(_png(tmp_path / "p.png"), width=200, height=100, flipH=True,
                                    rotation=10, link="https://example.com"))
        assert (out["flipH"], out["rotation"], out["link"]) == (True, 10.0, "https://example.com")

    def test_border_is_written(self, tmp_path):
        (pic,) = _built_shapes(tmp_path, [_image(_png(tmp_path / "p.png"), width=200, height=100,
                                                 line="#00FF00", lineWidth=2)])
        assert str(pic.line.color.rgb) == "00FF00"
        assert pic.line.width.pt == 2.0

    @pytest.mark.xfail(strict=True, reason="picture borders are not extracted by the converter")
    def test_border_survives(self, tmp_path):
        out = _one(tmp_path, _image(_png(tmp_path / "p.png"), width=200, height=100,
                                    line="#00FF00", lineWidth=2))
        assert out.get("line") == "#00FF00"

    def test_icon_color_on_raster_warns(self, tmp_path, capsys):
        _built_shapes(tmp_path, [_image(_png(tmp_path / "p.png"), width=20, iconColor="#FF0000")])
        assert "iconColor ignored (not SVG)" in capsys.readouterr().err


SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">'
       '<path fill="#000000" d="M0 0h48v48H0z"/></svg>')


def _svg_blob(pic) -> bytes:
    """Return the SVG part bytes of a picture built from an SVG source."""
    ext_blip = pic._element.find(".//{http://schemas.microsoft.com/office/drawing/2016/SVG/main}svgBlip")
    r_id = ext_blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
    return pic.part.related_part(r_id).blob


class TestSvgImage:
    def test_svg_is_recoloured(self, tmp_path):
        (tmp_path / "icon.svg").write_text(SVG)
        (pic,) = _built_shapes(tmp_path, [_image(tmp_path / "icon.svg", width=60, height=60,
                                                 iconColor="#FF0000")])
        blob = _svg_blob(pic).upper()
        assert b"FF0000" in blob and b"#000000" not in blob

    def test_icon_color_none_keeps_own_colours(self, tmp_path):
        (tmp_path / "icon.svg").write_text(SVG)
        (pic,) = _built_shapes(tmp_path, [_image(tmp_path / "icon.svg", width=60, height=60,
                                                 iconColor="none")])
        assert b"#000000" in _svg_blob(pic)

    def test_svg_round_trip_opts_out_of_recolour(self, tmp_path):
        (tmp_path / "icon.svg").write_text(SVG)
        out = _one(tmp_path, _image(tmp_path / "icon.svg", width=60, height=60, rotation=45))
        assert out["src"].endswith(".svg")
        assert (out["iconColor"], out["rotation"]) == ("none", 45.0)

    def test_svg_without_size_uses_its_own(self, tmp_path):
        (tmp_path / "icon.svg").write_text(SVG)
        out = _one(tmp_path, _image(tmp_path / "icon.svg"))
        assert (out["width"], out["height"]) == (48, 48)


class TestImageLabel:
    def test_right_label_sits_beside_the_icon(self, tmp_path):
        slide = _roundtrip(tmp_path, [_image(_png(tmp_path / "p.png", (60, 60)), width=60,
                                             height=60, label="Lambda", labelPosition="right")])
        (img,) = _of_type(slide, "image")
        (label,) = _of_type(slide, "textbox")
        assert _plain_text(label["text"]) == "Lambda"
        assert label["x"] > img["x"] + img["width"]
        assert label["align"] == "left"

    def test_label_none_adds_no_textbox(self, tmp_path):
        slide = _roundtrip(tmp_path, [_image(_png(tmp_path / "p.png"), width=60, label="x",
                                             labelPosition="none")])
        assert _of_type(slide, "textbox") == []


class TestQrImage:
    def test_qr_code_with_label(self, tmp_path):
        slide = _roundtrip(tmp_path, [{"type": "image", "src": "qr:https://example.com",
                                       "x": 300, "y": 400, "width": 150, "height": 150,
                                       "label": "scan", "rotation": 90}])
        (img,) = _of_type(slide, "image")
        (label,) = _of_type(slide, "textbox")
        assert img["src"].endswith(".svg")
        assert (img["width"], img["height"], img["rotation"]) == (150, 150, 90.0)
        assert _plain_text(label["text"]) == "scan"
        assert label["y"] > img["y"] + img["height"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
