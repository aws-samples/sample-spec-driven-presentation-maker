# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Importer fill / line / color resolution on raw DrawingML.

``pptx_to_json`` reads every shape's ``<p:spPr>`` through the helpers in
``sdpm.engine.converter.xml_helpers`` and resolves theme colors through
``sdpm.engine.converter.color``. Decks written by PowerPoint, Google Slides
and Canva use every color spelling OOXML allows (srgbClr, schemeClr, sysClr,
prstClr, each with lumMod / tint / shade children), so each spelling is pinned
here against the JSON the builder expects back.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls

from sdpm.engine.converter.color import (
    _apply_shade,
    _apply_tint,
    _resolve_color_with_transforms,
    _resolve_scheme_color,
    apply_color_transforms,
    apply_element_transforms,
    extract_text_color,
    extract_theme_colors_and_mapping,
)
from sdpm.engine.converter.xml_helpers import (
    _apply_srgb_transforms,
    _extract_fill_from_xml,
    _extract_line_from_xml,
    _resolve_line_from_style,
    _sys_hex,
    extract_line_dash,
)

_TEMPLATES = Path(__file__).parent.parent / "sdpm" / "templates"
_THEME = {"accent1": "#4F81BD", "dk1": "#000000", "lt1": "#FFFFFF", 5: "#4F81BD"}


def _sppr(inner: str):
    return parse_xml(f'<p:spPr {nsdecls("p", "a")}>{inner}</p:spPr>')


def _clr(inner: str):
    return parse_xml(f'<a:solidFill {nsdecls("a")}>{inner}</a:solidFill>')[0]


def _near(actual: str | None, expected: str) -> bool:
    """Same color within 1/255 per channel (int() truncation vs Office rounding)."""
    if not actual:
        return False
    return all(abs(int(actual[i:i + 2], 16) - int(expected[i:i + 2], 16)) <= 1 for i in (1, 3, 5))


# ---------------------------------------------------------------------------
# Fill
# ---------------------------------------------------------------------------

class TestFill:
    def test_missing_and_no_fill(self):
        assert _extract_fill_from_xml(None) == {"fill": "none"}
        assert _extract_fill_from_xml(_sppr("<a:noFill/>")) == {"fill": "none"}
        assert _extract_fill_from_xml(_sppr("")) == {"fill": "none"}

    def test_srgb_with_alpha(self):
        sp_pr = _sppr('<a:solidFill><a:srgbClr val="FF8800"><a:alpha val="50000"/></a:srgbClr></a:solidFill>')
        assert _extract_fill_from_xml(sp_pr) == {"fill": "#FF8800", "opacity": 0.5}

    def test_scheme_color_resolves_with_transforms(self):
        sp_pr = _sppr('<a:solidFill><a:schemeClr val="accent1"><a:lumMod val="75000"/>'
                      '<a:alpha val="80000"/></a:schemeClr></a:solidFill>')
        out = _extract_fill_from_xml(sp_pr, _THEME, {})
        # Office's "Accent 1, Darker 25%" of 4F81BD is 376092.
        assert out["opacity"] == 0.8 and _near(out["fill"], "#376092")

    def test_unresolvable_scheme_color_is_no_fill(self):
        sp_pr = _sppr('<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>')
        assert _extract_fill_from_xml(sp_pr, {}, {}) == {"fill": "none"}

    def test_sys_color_uses_last_rendered_color(self):
        sp_pr = _sppr('<a:solidFill><a:sysClr val="windowText" lastClr="112233">'
                      '<a:alpha val="25000"/></a:sysClr></a:solidFill>')
        assert _extract_fill_from_xml(sp_pr) == {"fill": "#112233", "opacity": 0.25}

    def test_linear_gradient(self):
        sp_pr = _sppr(
            '<a:gradFill flip="x" rotWithShape="1"><a:gsLst>'
            '<a:gs pos="0"><a:srgbClr val="FF0000"/></a:gs>'
            '<a:gs pos="50000"><a:schemeClr val="accent1"><a:alpha val="60000"/></a:schemeClr></a:gs>'
            '<a:gs pos="100000"><a:sysClr val="window"/></a:gs>'
            '</a:gsLst><a:lin ang="5400000" scaled="1"/></a:gradFill>')
        assert _extract_fill_from_xml(sp_pr, _THEME, {}) == {"gradient": {
            "stops": [
                {"position": 0.0, "color": "#FF0000"},
                {"position": 0.5, "color": "#4F81BD", "opacity": 0.6},
                {"position": 1.0, "color": "#FFFFFF"},
            ],
            "angle": 90.0, "type": "linear", "flip": "x", "rotWithShape": True,
        }}

    def test_unscaled_linear_gradient_is_recorded(self):
        sp_pr = _sppr('<a:gradFill><a:gsLst><a:gs pos="0"><a:srgbClr val="000000"/></a:gs>'
                      '</a:gsLst><a:lin ang="0"/></a:gradFill>')
        assert _extract_fill_from_xml(sp_pr)["gradient"]["scaled"] is False

    def test_path_gradient_keeps_rects(self):
        sp_pr = _sppr(
            '<a:gradFill><a:gsLst><a:gs pos="0"><a:srgbClr val="000000"/></a:gs></a:gsLst>'
            '<a:path path="circle"><a:fillToRect l="50000" t="50000" r="50000" b="50000"/></a:path>'
            '<a:tileRect l="-1" t="-2"/></a:gradFill>')
        g = _extract_fill_from_xml(sp_pr)["gradient"]
        assert g["type"] == "circle"
        assert g["fillToRect"] == {"l": 50000, "t": 50000, "r": 50000, "b": 50000}
        assert g["tileRect"] == {"l": -1, "t": -2, "r": 0, "b": 0}

    def test_gradient_without_direction_defaults_to_vertical(self):
        sp_pr = _sppr('<a:gradFill><a:gsLst><a:gs pos="0"><a:srgbClr val="000000"/></a:gs>'
                      '</a:gsLst></a:gradFill>')
        g = _extract_fill_from_xml(sp_pr)["gradient"]
        assert (g["angle"], g["type"]) == (90, "linear")

    def test_gradient_stop_srgb_tint_is_applied(self):
        sp_pr = _sppr('<a:gradFill><a:gsLst><a:gs pos="0"><a:srgbClr val="B22600">'
                      '<a:tint val="100000"/><a:alpha val="10000"/></a:srgbClr></a:gs></a:gsLst></a:gradFill>')
        stop = _extract_fill_from_xml(sp_pr)["gradient"]["stops"][0]
        assert stop == {"position": 0.0, "color": "#B22600", "opacity": 0.1}

    def test_gradient_with_no_usable_stop_falls_through(self):
        sp_pr = _sppr('<a:gradFill><a:gsLst><a:gs pos="0"><a:schemeClr val="nope"/></a:gs>'
                      '</a:gsLst></a:gradFill>')
        assert _extract_fill_from_xml(sp_pr, {}, {}) == {"fill": "none"}

    def test_pattern_fill(self):
        sp_pr = _sppr('<a:pattFill prst="ltHorz"><a:fgClr><a:srgbClr val="111111"/></a:fgClr>'
                      '<a:bgClr><a:srgbClr val="EEEEEE"/></a:bgClr></a:pattFill>')
        assert _extract_fill_from_xml(sp_pr) == {
            "patternFill": {"pattern": "ltHorz", "fgColor": "#111111", "bgColor": "#EEEEEE"}}


# ---------------------------------------------------------------------------
# Line
# ---------------------------------------------------------------------------

class TestLine:
    def test_missing_line(self):
        assert _extract_line_from_xml(None) == {"line": "none"}
        assert _extract_line_from_xml(_sppr("")) == {"line": "none"}

    def test_no_fill_line_keeps_width(self):
        out = _extract_line_from_xml(_sppr('<a:ln w="25400"><a:noFill/></a:ln>'))
        assert out == {"lineWidth": 2.0, "_lineWidthEmu": 25400, "line": "none"}

    def test_solid_srgb_line_with_round_cap_and_transform(self):
        out = _extract_line_from_xml(_sppr(
            '<a:ln w="12700" cap="rnd"><a:solidFill><a:srgbClr val="4F81BD">'
            '<a:lumMod val="75000"/></a:srgbClr></a:solidFill></a:ln>'))
        line = out.pop("line")
        assert out == {"lineWidth": 1.0, "_lineWidthEmu": 12700, "_lineCap": "rnd"}
        assert _near(line, "#376092")

    def test_solid_scheme_and_sys_lines(self):
        scheme = _sppr('<a:ln><a:solidFill><a:schemeClr val="accent1"/></a:solidFill></a:ln>')
        assert _extract_line_from_xml(scheme, _THEME, {}) == {"line": "#4F81BD"}
        sys_ = _sppr('<a:ln><a:solidFill><a:sysClr val="window"/></a:solidFill></a:ln>')
        assert _extract_line_from_xml(sys_) == {"line": "#FFFFFF"}

    def test_line_without_fill_is_left_for_style_resolution(self):
        assert _extract_line_from_xml(_sppr('<a:ln w="9525"/>')) == {"lineWidth": 0.8, "_lineWidthEmu": 9525}

    def test_gradient_line(self):
        out = _extract_line_from_xml(_sppr(
            '<a:ln><a:gradFill rotWithShape="0" flip="xy"><a:gsLst>'
            '<a:gs pos="0"><a:srgbClr val="FF0000"><a:alpha val="50000"/></a:srgbClr></a:gs>'
            '<a:gs pos="40000"><a:schemeClr val="accent1"><a:alpha val="20000"/></a:schemeClr></a:gs>'
            '<a:gs pos="100000"><a:sysClr val="x" lastClr="00FF00"><a:alpha val="70000"/></a:sysClr></a:gs>'
            '</a:gsLst><a:lin ang="2700000"/></a:gradFill></a:ln>'), _THEME, {})
        assert out == {"lineGradient": {
            "stops": [
                {"position": 0.0, "color": "#FF0000", "opacity": 0.5},
                {"position": 0.4, "color": "#4F81BD", "opacity": 0.2},
                {"position": 1.0, "color": "#00FF00", "opacity": 0.7},
            ],
            "angle": 45.0, "type": "linear", "rotWithShape": False, "flip": "xy",
        }}

    def test_path_gradient_line_and_default_direction(self):
        path = _extract_line_from_xml(_sppr(
            '<a:ln><a:gradFill><a:gsLst><a:gs pos="0"><a:srgbClr val="000000"/></a:gs></a:gsLst>'
            '<a:path path="rect"><a:fillToRect l="1" t="2" r="3" b="4"/></a:path>'
            '<a:tileRect/></a:gradFill></a:ln>'))["lineGradient"]
        assert path["type"] == "rect"
        assert path["fillToRect"] == {"l": 1, "t": 2, "r": 3, "b": 4}
        assert path["tileRect"] == {"l": 0, "t": 0, "r": 0, "b": 0}
        plain = _extract_line_from_xml(_sppr(
            '<a:ln><a:gradFill><a:gsLst><a:gs pos="0"><a:srgbClr val="000000"/></a:gs></a:gsLst>'
            '</a:gradFill></a:ln>'))["lineGradient"]
        assert (plain["angle"], plain["type"]) == (0, "linear")

    def test_line_style_reference(self):
        sp = parse_xml(
            f'<p:sp {nsdecls("p", "a")}><p:spPr/><p:style>'
            '<a:lnRef idx="2"><a:schemeClr val="accent1"/></a:lnRef></p:style></p:sp>')
        shape = type("S", (), {"_element": sp})()
        assert _resolve_line_from_style(shape, _THEME, {}) == {"line": "#4F81BD", "lineWidth": 1.0}
        theme_styles = {"line": ['<a:ln w="6350"/>', '<a:ln w="38100"/>']}
        assert _resolve_line_from_style(shape, _THEME, {}, theme_styles) == {"line": "#4F81BD", "lineWidth": 3.0}

    @pytest.mark.parametrize("style", [
        "",
        "<p:style/>",
        '<p:style><a:lnRef idx="0"><a:schemeClr val="accent1"/></a:lnRef></p:style>',
    ])
    def test_line_style_reference_absent_or_zero(self, style):
        sp = parse_xml(f'<p:sp {nsdecls("p", "a")}><p:spPr/>{style}</p:sp>')
        shape = type("S", (), {"_element": sp})()
        assert _resolve_line_from_style(shape, _THEME, {}) == {"line": "none"}

    def test_line_style_reference_never_raises(self):
        assert _resolve_line_from_style(object(), _THEME, {}) == {"line": "none"}

    def test_line_dash(self):
        def shape(ln):
            return type("S", (), {"_element": parse_xml(
                f'<p:sp {nsdecls("p", "a")}><p:spPr>{ln}</p:spPr></p:sp>')})()
        assert extract_line_dash(shape('<a:ln><a:prstDash val="dash"/></a:ln>')) == "dash"
        assert extract_line_dash(shape('<a:ln><a:prstDash val="solid"/></a:ln>')) is None
        assert extract_line_dash(shape("<a:ln/>")) is None
        assert extract_line_dash(object()) is None


# ---------------------------------------------------------------------------
# Color transforms
# ---------------------------------------------------------------------------

class TestColorTransforms:
    def test_sys_hex_fallbacks(self):
        assert _sys_hex(parse_xml(f'<a:solidFill {nsdecls("a")}/>')) is None
        assert _sys_hex(parse_xml(f'<a:solidFill {nsdecls("a")}><a:sysClr val="window"/></a:solidFill>')) == "#FFFFFF"
        assert _sys_hex(parse_xml(f'<a:solidFill {nsdecls("a")}><a:sysClr val="menu"/></a:solidFill>')) is None

    def test_sys_hex_applies_children(self):
        solid = parse_xml(f'<a:solidFill {nsdecls("a")}><a:sysClr val="window" lastClr="FFFFFF">'
                          '<a:shade val="50000"/></a:sysClr></a:solidFill>')
        out = _sys_hex(solid)
        assert out != "#FFFFFF" and out[1:3] == out[3:5] == out[5:7]  # darker gray

    def test_srgb_shade_and_lum_off(self):
        assert _apply_srgb_transforms("#FFFFFF", {"shade": "0"}) == "#000000"
        assert _apply_srgb_transforms("#000000", {"lumOff": "100000"}) == "#FFFFFF"

    @pytest.mark.xfail(strict=True, reason=(
        "_apply_srgb_transforms scales lumMod in RGB space; ECMA-376 (and the"
        " schemeClr path) scale HSL luminance, so gradient stops and sysClr"
        " colors come out off (3B608D instead of Office's 376092)"))
    def test_srgb_lum_mod_matches_scheme_path(self):
        assert _near(_apply_srgb_transforms("#4F81BD", {"lumMod": "75000"}), "#376092")

    def test_element_transforms(self):
        assert apply_element_transforms("#4F81BD", _clr('<a:srgbClr val="4F81BD"/>')) == "#4F81BD"
        assert _near(apply_element_transforms("#4F81BD", _clr(
            '<a:srgbClr val="4F81BD"><a:lumMod val="75000"/></a:srgbClr>')), "#376092")
        assert _near(apply_element_transforms("#4F81BD", _clr(
            '<a:srgbClr val="4F81BD"><a:lumMod val="20000"/><a:lumOff val="80000"/></a:srgbClr>')), "#DBE5F1")
        assert apply_element_transforms("#FFFFFF", _clr(
            '<a:srgbClr val="FFFFFF"><a:shade val="0"/></a:srgbClr>')) == "#000000"
        assert apply_element_transforms("#000000", _clr(
            '<a:srgbClr val="000000"><a:tint val="0"/></a:srgbClr>')) == "#FFFFFF"

    def test_scheme_transforms_match_element_transforms(self):
        # Same math, two entry points: a schemeClr and an srgbClr carrying the
        # same children must resolve to the same color.
        for child in ('<a:shade val="60000"/>', '<a:tint val="40000"/>',
                      '<a:lumMod val="60000"/><a:lumOff val="40000"/>'):
            scheme = _clr(f'<a:schemeClr val="accent1">{child}</a:schemeClr>')
            srgb = _clr(f'<a:srgbClr val="4F81BD">{child}</a:srgbClr>')
            assert _resolve_color_with_transforms(scheme, _THEME, {}) == apply_element_transforms("#4F81BD", srgb)

    def test_ph_clr_override(self):
        ph = _clr('<a:schemeClr val="phClr"/>')
        assert _resolve_color_with_transforms(ph, _THEME, {}, override_scheme="accent1") == "#4F81BD"
        assert _resolve_color_with_transforms(ph, {}, {}) is None

    def test_scheme_resolution_order(self):
        # color map first, then the name, then the numeric id, then the fallback palette.
        assert _resolve_scheme_color("tx1", {"lt1": "#EEEEEE"}, {"tx1": "lt1"}) == "#EEEEEE"
        assert _resolve_scheme_color("accent1", _THEME, {}) == "#4F81BD"
        assert _resolve_scheme_color("bg2", {3: "#ABABAB"}, {}) == "#ABABAB"
        assert _resolve_scheme_color("accent6", None, None) == "#FBD332"
        assert _resolve_scheme_color("unknown", None, None) is None

    def test_legacy_transform_helpers(self):
        assert apply_color_transforms("#000000", {"lumMod": "50000", "tint": "25000"}) == "#808080"
        assert apply_color_transforms("#123456", {"lumMod": "50000"}) == "#123456"
        assert _apply_tint("#000000", 0.0) == "#FFFFFF"
        assert _apply_tint("#336699", 1.0) == "#336699"
        assert _apply_shade("#FFFFFF", 0.5) == "#7F7F7F"


# ---------------------------------------------------------------------------
# Theme and text color
# ---------------------------------------------------------------------------

class TestThemeAndTextColor:
    def test_theme_extraction_from_bundled_template(self):
        colors, mapping, styles = extract_theme_colors_and_mapping(str(_TEMPLATES / "blank-dark.pptx"), 0)
        for name in ("dk1", "lt1", "accent1"):
            assert colors[name].startswith("#") and len(colors[name]) == 7
        assert colors[1] == colors["lt1"] and colors[14] == colors[1]
        assert set(mapping) >= {"bg1", "tx1"}
        assert styles["line"] and styles["fill"]

    def test_theme_extraction_on_bad_file_warns(self, tmp_path, capsys):
        bad = tmp_path / "bad.pptx"
        bad.write_bytes(b"not a zip")
        assert extract_theme_colors_and_mapping(str(bad), 0) == ({}, {}, {"fill": [], "line": []})
        assert "Could not extract theme colors" in capsys.readouterr().err

    @staticmethod
    def _run():
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        tb = slide.shapes.add_textbox(0, 0, 100, 100)
        return tb.text_frame.paragraphs[0].add_run()

    def test_rgb_run(self):
        run = self._run()
        run.font.color.rgb = RGBColor(0x12, 0x34, 0x56)
        assert extract_text_color(run) == "#123456"

    def test_scheme_run(self):
        run = self._run()
        run.font.color.theme_color = MSO_THEME_COLOR.ACCENT_1
        assert extract_text_color(run, _THEME, {"tx1": "dk1"}) == "#4F81BD"

    def test_default_text_role_is_omitted(self):
        run = self._run()
        run.font.color.theme_color = MSO_THEME_COLOR.TEXT_1
        assert extract_text_color(run, _THEME, {"tx1": "dk1"}) is None
        assert extract_text_color(run, _THEME, {"tx1": "dk1"}, is_placeholder=True) == "#000000"

    def test_default_text_role_with_transform_is_kept(self):
        run = self._run()
        run.font.color.theme_color = MSO_THEME_COLOR.TEXT_1
        run.font.color.brightness = 0.5
        out = extract_text_color(run, _THEME, {"tx1": "dk1"})
        assert out is not None and out != "#000000"

    def test_preset_color_run(self):
        run = self._run()
        rpr = run._r.get_or_add_rPr()
        rpr.append(parse_xml(f'<a:solidFill {nsdecls("a")}><a:prstClr val="red"/></a:solidFill>'))
        assert extract_text_color(run) == "#FF0000"

    def test_uncolored_run_uses_mapped_text_color(self):
        run = self._run()
        assert extract_text_color(run, {"lt1": "#FAFAFA"}, {"tx1": "lt1"}) == "#FAFAFA"
        assert extract_text_color(run, {"lt1": "#FAFAFA"}, {"tx1": "lt1"}, is_placeholder=True) is None
        assert extract_text_color(run) is None
