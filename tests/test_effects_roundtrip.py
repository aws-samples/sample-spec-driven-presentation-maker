# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Visual effects survive JSON -> XML -> JSON.

``sdpm.utils.effects.apply_effects`` (builder) and
``sdpm.engine.converter.xml_helpers._extract_visual_effects`` (importer) are
two halves of one contract: whatever the builder writes, the importer must
read back as the same JSON, otherwise a ``pptx_to_json`` -> ``generate`` cycle
drifts. These tests run the pair on a bare ``<p:sp>`` — no template, no
LibreOffice — so each effect key is checked in isolation.
"""

from __future__ import annotations

import pytest
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls, qn

from sdpm.engine.converter.xml_helpers import (
    _extract_3d_from_xml,
    _extract_effects_from_xml,
    _extract_visual_effects,
)
from sdpm.utils.effects import (
    BEVEL_PRESETS,
    GLOW_PRESETS,
    REFLECTION_PRESETS,
    ROTATION3D_PRESETS,
    SHADOW_PRESETS,
    _insert_ordered,
    apply_effects,
)

_SP_XML = (
    f'<p:sp {nsdecls("p", "a")}>'
    '<p:nvSpPr><p:cNvPr id="2" name="s"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
    '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
    '<a:solidFill><a:srgbClr val="FF0000"/></a:solidFill>'
    '<a:ln w="12700"><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln>'
    '</p:spPr>'
    '<p:style><a:lnRef idx="1"><a:schemeClr val="accent1"/></a:lnRef>'
    '<a:fillRef idx="3"><a:schemeClr val="accent1"/></a:fillRef>'
    '<a:effectRef idx="2"><a:schemeClr val="accent1"/></a:effectRef>'
    '<a:fontRef idx="minor"><a:schemeClr val="lt1"/></a:fontRef></p:style>'
    '</p:sp>'
)


def _sp():
    return parse_xml(_SP_XML)


def _roundtrip(elem_def: dict) -> dict:
    sp = _sp()
    apply_effects(sp, elem_def)
    return _extract_visual_effects(sp.find(qn("p:spPr")))


def _child_names(sp_pr) -> list[str]:
    return [c.tag.split("}")[-1] for c in sp_pr]


# ---------------------------------------------------------------------------
# No effect: explicit empty list, theme reference unlinked
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("off", [None, False, "", "none"])
def test_no_effect_spellings_pin_empty_list(off):
    sp = _sp()
    apply_effects(sp, {"shadow": off, "glow": off})
    sp_pr = sp.find(qn("p:spPr"))
    lst = sp_pr.find(qn("a:effectLst"))
    assert lst is not None and len(lst) == 0
    assert sp.find(qn("p:style")).find(qn("a:effectRef")).get("idx") == "0"
    assert _extract_visual_effects(sp_pr) == {}


def test_no_effect_is_idempotent():
    sp = _sp()
    apply_effects(sp, {})
    apply_effects(sp, {})
    assert len(sp.find(qn("p:spPr")).findall(qn("a:effectLst"))) == 1


def test_effect_list_follows_schema_order():
    # spPr children out of schema order are silently dropped by PowerPoint.
    sp = _sp()
    apply_effects(sp, {"shadow": "md", "bevel": "sm", "rotation3d": {"rotX": 10}})
    names = _child_names(sp.find(qn("p:spPr")))
    assert names == ["xfrm", "prstGeom", "solidFill", "ln", "effectLst", "scene3d", "sp3d"]


def test_reapplying_shadow_replaces_previous_list():
    sp = _sp()
    apply_effects(sp, {"shadow": "lg"})
    apply_effects(sp, {"glow": "sm"})
    sp_pr = sp.find(qn("p:spPr"))
    assert len(sp_pr.findall(qn("a:effectLst"))) == 1
    out = _extract_effects_from_xml(sp_pr)
    assert "shadow" not in out and "glow" in out


def test_element_without_sppr_is_left_alone():
    el = parse_xml(f'<p:grpSp {nsdecls("p")}><p:nvGrpSpPr/></p:grpSp>')
    apply_effects(el, {"shadow": "md"})
    assert el.find(qn("a:effectLst")) is None


def test_insert_ordered_appends_unknown_tags():
    sp_pr = _sp().find(qn("p:spPr"))
    unknown = parse_xml(f'<a:extLst {nsdecls("a")}/>')
    _insert_ordered(sp_pr, unknown)
    assert _child_names(sp_pr)[-1] == "extLst"


# ---------------------------------------------------------------------------
# Per-effect round trips
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(SHADOW_PRESETS))
def test_shadow_preset_roundtrip(name):
    assert _roundtrip({"shadow": name})["shadow"] == SHADOW_PRESETS[name]


def test_unknown_shadow_preset_falls_back_to_md():
    assert _roundtrip({"shadow": "huge"})["shadow"] == SHADOW_PRESETS["md"]


def test_inner_shadow_roundtrip():
    spec = {"type": "inner", "blur": 6, "distance": 3, "direction": 45,
            "color": "#123456", "opacity": 0.5}
    assert _roundtrip({"shadow": spec})["shadow"] == spec


@pytest.mark.parametrize("name", sorted(GLOW_PRESETS))
def test_glow_preset_roundtrip(name):
    glow = _roundtrip({"glow": name})["glow"]
    glow.pop("_radiusEmu")
    assert glow == GLOW_PRESETS[name]


def test_glow_radius_emu_is_preserved_exactly():
    # _radiusEmu carries sub-px precision across a re-import.
    out = _roundtrip({"glow": {"radius": 3, "_radiusEmu": 20001, "color": "#00FF00", "opacity": 0.3}})
    assert out["glow"]["_radiusEmu"] == 20001


def test_soft_edge_roundtrip():
    assert _roundtrip({"softEdge": 12})["softEdge"] == 12


@pytest.mark.parametrize("name", sorted(REFLECTION_PRESETS))
def test_reflection_preset_roundtrip(name):
    expected = {k: v for k, v in REFLECTION_PRESETS[name].items() if k != "distance"}
    assert _roundtrip({"reflection": name})["reflection"] == expected


def test_reflection_with_distance_roundtrip():
    spec = {"blur": 3, "distance": 5, "size": 40, "opacity": 0.25}
    assert _roundtrip({"reflection": spec})["reflection"] == spec


@pytest.mark.parametrize("name", sorted(BEVEL_PRESETS))
def test_bevel_preset_roundtrip(name):
    out = _roundtrip({"bevel": name})
    assert out["bevel"] == BEVEL_PRESETS[name]
    assert "rotation3d" not in out  # the orthographic camera is not a rotation


@pytest.mark.parametrize("preset", sorted(ROTATION3D_PRESETS))
def test_rotation3d_preset_roundtrip(preset):
    assert _roundtrip({"rotation3d": preset}).get("rotation3d") == preset


def test_rotation3d_free_rotation_roundtrip():
    spec = {"rotX": 20, "rotY": 30, "rotZ": 5, "perspective": 45}
    assert _roundtrip({"rotation3d": spec})["rotation3d"] == spec


def test_rotation3d_default_perspective_is_written():
    assert _roundtrip({"rotation3d": {"rotY": 15}})["rotation3d"] == {"rotY": 15, "perspective": 120}


def test_rotation3d_orthographic_roundtrip():
    spec = {"rotX": 20, "perspective": 0}
    assert _roundtrip({"rotation3d": spec})["rotation3d"] == spec


def test_bevel_and_rotation_share_one_scene():
    sp = _sp()
    apply_effects(sp, {"bevel": "md", "rotation3d": {"rotX": 10, "perspective": 30}})
    sp_pr = sp.find(qn("p:spPr"))
    assert len(sp_pr.findall(qn("a:scene3d"))) == 1
    out = _extract_3d_from_xml(sp_pr)
    assert out == {"bevel": BEVEL_PRESETS["md"], "rotation3d": {"rotX": 10, "perspective": 30}}


def test_all_effects_together_roundtrip():
    spec = {
        "shadow": "sm", "glow": "lg", "softEdge": 4, "reflection": "md",
        "bevel": "lg", "rotation3d": "perspective-left",
    }
    out = _roundtrip(spec)
    out["glow"].pop("_radiusEmu")
    assert out == {
        "shadow": SHADOW_PRESETS["sm"],
        "glow": GLOW_PRESETS["lg"],
        "softEdge": 4,
        "reflection": {k: v for k, v in REFLECTION_PRESETS["md"].items() if k != "distance"},
        "bevel": BEVEL_PRESETS["lg"],
        "rotation3d": "perspective-left",
    }


def test_custom_emu_scale_is_applied():
    # 4:3 decks use a different px scale; blur doubles with the scale.
    sp = _sp()
    apply_effects(sp, {"softEdge": 10}, emu_per_px=12700)
    se = sp.find(qn("p:spPr")).find(qn("a:effectLst")).find(qn("a:softEdge"))
    assert se.get("rad") == str(10 * 12700)


# ---------------------------------------------------------------------------
# Importer edge cases (XML written by other tools)
# ---------------------------------------------------------------------------

def _sppr(inner: str):
    return parse_xml(f'<p:spPr {nsdecls("p", "a")}>{inner}</p:spPr>')


def test_extract_none_and_missing_lists():
    assert _extract_visual_effects(None) == {}
    assert _extract_visual_effects(_sppr("")) == {}


def test_glow_scheme_color_resolves_through_theme():
    sp_pr = _sppr('<a:effectLst><a:glow rad="63500"><a:schemeClr val="accent2">'
                  '<a:alpha val="40000"/></a:schemeClr></a:glow></a:effectLst>')
    out = _extract_effects_from_xml(sp_pr, {"accent2": "#ABCDEF"}, {})
    assert out["glow"] == {"radius": 10, "_radiusEmu": 63500, "color": "#ABCDEF", "opacity": 0.4}


def test_soft_edge_without_radius_is_ignored():
    assert _extract_effects_from_xml(_sppr("<a:effectLst><a:softEdge/></a:effectLst>")) == {}


def test_free_rotation_with_zero_angles_is_not_a_rotation():
    sp_pr = _sppr('<a:scene3d><a:camera prst="orthographicFront"><a:rot lat="0" lon="0" rev="0"/>'
                  '</a:camera><a:lightRig rig="threePt" dir="t"/></a:scene3d>')
    assert _extract_3d_from_xml(sp_pr) == {}
