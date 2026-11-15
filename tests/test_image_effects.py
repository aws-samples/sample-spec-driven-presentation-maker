# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Image element helpers: source path resolution and picture effects.

``sdpm.utils.image.apply_image_effects`` writes the OOXML that
``converter/elements/media.py`` reads back into ``_originalEffects`` (crop ->
``a:srcRect`` in 1/1000 %, mask -> ``a:prstGeom`` + ``a:avLst``, brightness /
contrast -> ``a:lum``, saturation -> ``a:satMod``, duotone -> ``a:duotone``).
The tests pin those encodings on a bare ``<p:pic>``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls, qn

from sdpm.utils.image import apply_image_effects, resolve_image_path

_PIC_XML = (
    f'<p:pic {nsdecls("p", "a", "r")}>'
    '<p:nvPicPr><p:cNvPr id="2" name="p"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>'
    '<p:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
    '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="10" cy="10"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
    '</p:pic>'
)


def _pic():
    return parse_xml(_PIC_XML)


def _blip(pic):
    return pic.find(qn("p:blipFill")).find(qn("a:blip"))


def _geom(pic):
    geoms = pic.find(qn("p:spPr")).findall(qn("a:prstGeom"))
    assert len(geoms) == 1, "mask must replace, not add, the geometry"
    return geoms[0]


# ---------------------------------------------------------------------------
# resolve_image_path
# ---------------------------------------------------------------------------

def test_resolve_existing_file(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    assert resolve_image_path(str(img)) == img.resolve()


def test_resolve_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_image_path(str(tmp_path / "missing.png"))


def test_resolve_rejects_traversal(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    with pytest.raises(ValueError, match="traversal"):
        resolve_image_path(str(tmp_path / "sub" / ".." / "a.png"))


def test_resolve_asset_refs_delegate_to_assets(monkeypatch):
    seen = []

    def fake(ref, theme):
        seen.append((ref, theme))
        return Path("/resolved")

    monkeypatch.setattr("sdpm.utils.image.resolve_asset_path", fake)
    assert resolve_image_path("icons:aws/lambda", "dark") == Path("/resolved")
    assert resolve_image_path("assets:logo") == Path("/resolved")
    assert seen == [("icons:aws/lambda", "dark"), ("assets:logo", "light")]


# ---------------------------------------------------------------------------
# apply_image_effects
# ---------------------------------------------------------------------------

def test_no_effects_leaves_xml_untouched():
    pic = _pic()
    before = parse_xml(_PIC_XML)
    apply_image_effects(pic, {"src": "x.png"})
    from lxml import etree
    assert etree.tostring(pic) == etree.tostring(before)


def test_crop_writes_src_rect_after_blip():
    pic = _pic()
    apply_image_effects(pic, {"crop": {"left": 10, "top": 5.5, "right": 0, "bottom": 20}})
    fill = pic.find(qn("p:blipFill"))
    names = [c.tag.split("}")[-1] for c in fill]
    assert names[:2] == ["blip", "srcRect"]
    rect = fill.find(qn("a:srcRect"))
    assert dict(rect.attrib) == {"l": "10000", "t": "5500", "b": "20000"}


def test_crop_replaces_previous_crop():
    pic = _pic()
    apply_image_effects(pic, {"crop": {"left": 10}})
    apply_image_effects(pic, {"crop": {"top": 7}})
    rects = pic.find(qn("p:blipFill")).findall(qn("a:srcRect"))
    assert len(rects) == 1 and dict(rects[0].attrib) == {"t": "7000"}


def test_crop_without_blip_goes_first():
    pic = parse_xml(_PIC_XML.replace('<a:blip r:embed="rId1"/>', ""))
    apply_image_effects(pic, {"crop": {"right": 3}})
    assert pic.find(qn("p:blipFill"))[0].tag == qn("a:srcRect")


@pytest.mark.parametrize("mask,prst", [
    ("circle", "ellipse"), ("oval", "ellipse"), ("rounded_rectangle", "roundRect"),
    ("star_5_point", "star5"), ("heart", "heart"), ("snip2SameRect", "snip2SameRect"),
])
def test_mask_maps_friendly_names(mask, prst):
    pic = _pic()
    apply_image_effects(pic, {"mask": mask})
    assert _geom(pic).get("prst") == prst


def test_round_rect_mask_adjustment_uses_half_scale():
    pic = _pic()
    apply_image_effects(pic, {"mask": "roundRect", "maskAdjustments": [0.5]})
    gds = _geom(pic).find(qn("a:avLst")).findall(qn("a:gd"))
    assert [(g.get("name"), g.get("fmla")) for g in gds] == [("adj", "val 25000")]


def test_generic_mask_adjustments_single_and_multi():
    pic = _pic()
    apply_image_effects(pic, {"mask": "round1Rect", "maskAdjustments": [0.2]})
    gds = _geom(pic).find(qn("a:avLst")).findall(qn("a:gd"))
    assert [(g.get("name"), g.get("fmla")) for g in gds] == [("adj", "val 20000")]

    pic = _pic()
    apply_image_effects(pic, {"mask": "round2SameRect", "maskAdjustments": [0.1, 0.3]})
    gds = _geom(pic).find(qn("a:avLst")).findall(qn("a:gd"))
    assert [(g.get("name"), g.get("fmla")) for g in gds] == [("adj1", "val 10000"), ("adj2", "val 30000")]


def test_brightness_and_contrast():
    pic = _pic()
    apply_image_effects(pic, {"brightness": 20, "contrast": -10})
    apply_image_effects(pic, {"brightness": 0})
    lums = _blip(pic).findall(qn("a:lum"))
    assert len(lums) == 1 and dict(lums[0].attrib) == {"bright": "0"}


def test_contrast_only():
    pic = _pic()
    apply_image_effects(pic, {"contrast": 15})
    assert dict(_blip(pic).find(qn("a:lum")).attrib) == {"contrast": "15000"}


@pytest.mark.parametrize("saturation,val", [(-10, "90000"), (50, "150000"), (-150, "0")])
def test_saturation_is_a_sat_mod(saturation, val):
    pic = _pic()
    apply_image_effects(pic, {"saturation": 5})
    apply_image_effects(pic, {"saturation": saturation})
    mods = _blip(pic).findall(qn("a:satMod"))
    assert len(mods) == 1 and mods[0].get("val") == val


def test_duotone_uses_first_two_colors():
    pic = _pic()
    apply_image_effects(pic, {"duotone": ["#000000", "#FF8800", "#FFFFFF"]})
    apply_image_effects(pic, {"duotone": ["#111111", "#222222"]})
    duos = _blip(pic).findall(qn("a:duotone"))
    assert len(duos) == 1
    assert [c.get("val") for c in duos[0]] == ["111111", "222222"]


def test_duotone_needs_two_colors():
    pic = _pic()
    apply_image_effects(pic, {"duotone": ["#000000"]})
    assert _blip(pic).find(qn("a:duotone")) is None


def test_raw_blip_effects_are_replayed():
    pic = _pic()
    raw = f'<a:grayscl {nsdecls("a")}/>'
    apply_image_effects(pic, {"_blipEffects": [raw]})
    assert _blip(pic)[0].tag == qn("a:grayscl")


def test_raw_blip_effects_reject_entities():
    pic = _pic()
    evil = ('<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
            f'<a:grayscl {nsdecls("a")}>&e;</a:grayscl>')
    with pytest.raises(Exception):
        apply_image_effects(pic, {"_blipEffects": [evil]})


def test_pic_namespace_variant_is_supported():
    # Pictures inside graphic frames use pic:blipFill / pic:spPr.
    xml = (_PIC_XML.replace("p:blipFill", "pic:blipFill").replace("p:spPr", "pic:spPr")
           .replace(f'{nsdecls("p", "a", "r")}', f'{nsdecls("p", "a", "r", "pic")}'))
    pic = parse_xml(xml)
    apply_image_effects(pic, {"crop": {"left": 1}, "mask": "circle", "brightness": 5,
                              "saturation": 0, "duotone": ["#000000", "#FFFFFF"]})
    fill = pic.find(qn("pic:blipFill"))
    assert fill.find(qn("a:srcRect")).get("l") == "1000"
    assert pic.find(qn("pic:spPr")).find(qn("a:prstGeom")).get("prst") == "ellipse"
    blip = fill.find(qn("a:blip"))
    assert blip.find(qn("a:lum")) is not None
    assert blip.find(qn("a:satMod")).get("val") == "100000"
    assert blip.find(qn("a:duotone")) is not None
