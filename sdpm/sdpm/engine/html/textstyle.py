# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Resolve the inherited text style of a layout placeholder.

PowerPoint resolves a placeholder's text formatting through a chain; the first
defined value wins per field:

1. the layout placeholder's ``a:lstStyle`` (and its ``a:bodyPr``),
2. the master placeholder of the same kind (title/ctrTitle → title,
   body/obj/subTitle → body, else same type, else same idx),
3. the master ``p:txStyles`` (titleStyle / bodyStyle / otherStyle),
4. ``ppt/presentation.xml`` ``p:defaultTextStyle``.

The result is plain data (px / pt / hex) that ``template.py`` turns into CSS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml import parse_xml

from sdpm.engine import emu_per_px
from sdpm.engine.converter.color import (
    _resolve_color_with_transforms,
    apply_element_transforms,
    extract_theme_colors_and_mapping,
)
from sdpm.engine.converter.constants import _NS

LEVELS = 5

# OOXML bodyPr defaults (EMU): left/right 0.1in, top/bottom 0.05in.
_DEFAULT_INSETS = {"lIns": 91440, "tIns": 45720, "rIns": 91440, "bIns": 45720}
_ANCHOR = {"t": "top", "ctr": "middle", "b": "bottom"}
_ALIGN = {"l": "left", "ctr": "center", "r": "right", "just": "justify", "dist": "justify"}
_TITLE_TYPES = ("title", "ctrTitle")
_BODY_TYPES = ("body", "obj", "subTitle")


def _q(tag: str) -> str:
    prefix, local = tag.split(":")
    return f"{{{_NS[prefix]}}}{local}"


def px_value(emu_value: float, emu: float) -> int | float:
    """EMU → px, rounded to 2 decimals; integral values come back as int."""
    value = round(emu_value / emu, 2)
    return int(value) if value == int(value) else value


def _theme_element(master):
    part = master.part.part_related_by(RT.THEME)
    return parse_xml(part.blob)


def load_theme(template_path: str | Path, prs) -> dict[str, Any]:
    """Theme context shared by text-style and ground resolution (slide master 0)."""
    theme_colors, color_mapping, _ = extract_theme_colors_and_mapping(str(template_path), 0)
    master = prs.slide_masters[0]
    fonts: dict[str, str | None] = {"major": None, "minor": None, "majorEa": None, "minorEa": None}
    bg_fill_styles: list = []
    fill_styles: list = []
    try:
        theme = _theme_element(master)
    except (KeyError, ValueError):
        theme = None
    if theme is not None:
        for key, tag in (("major", "majorFont"), ("minor", "minorFont")):
            font = theme.find(f".//a:{tag}", _NS)
            if font is None:
                continue
            latin = font.find("a:latin", _NS)
            ea = font.find("a:ea", _NS)
            fonts[key] = (latin.get("typeface") or None) if latin is not None else None
            fonts[f"{key}Ea"] = (ea.get("typeface") or None) if ea is not None else None
        lst = theme.find(".//a:bgFillStyleLst", _NS)
        bg_fill_styles = list(lst) if lst is not None else []
        lst = theme.find(".//a:fillStyleLst", _NS)
        fill_styles = list(lst) if lst is not None else []
    return {
        "colors": theme_colors,
        "mapping": color_mapping,
        "fonts": fonts,
        "bgFillStyles": bg_fill_styles,
        "fillStyles": fill_styles,
        "emuPerPx": emu_per_px(prs.slide_width),
    }


def resolve_color(parent, theme: dict, override_scheme: str | None = None) -> str | None:
    """Hex colour of the colour choice under ``parent`` (solidFill, buClr, bgRef…)."""
    if parent is None:
        return None
    for child in parent:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "schemeClr":
            return _resolve_color_with_transforms(
                child, theme["colors"], theme["mapping"], override_scheme=override_scheme
            )
        if tag == "srgbClr" and child.get("val"):
            return apply_element_transforms(f"#{child.get('val').upper()}", child)
        if tag == "sysClr" and child.get("lastClr"):
            return apply_element_transforms(f"#{child.get('lastClr').upper()}", child)
    return None


def _ph_of(sp) -> tuple[str, str | None]:
    ph = sp.find("p:nvSpPr/p:nvPr/p:ph", _NS)
    if ph is None:
        return "obj", None
    return ph.get("type", "obj"), ph.get("idx")


def placeholder_type(sp) -> str:
    """OOXML placeholder type of a ``p:sp`` (``obj`` when unspecified)."""
    return _ph_of(sp)[0]


def find_master_placeholder(master, ph_type: str, ph_idx: str | None):
    """The master placeholder a layout placeholder inherits from, or None."""
    if ph_type in _TITLE_TYPES:
        wanted = ("title",)
    elif ph_type in _BODY_TYPES:
        wanted = ("body",)
    else:
        wanted = (ph_type,)
    candidates = master._element.findall("p:cSld/p:spTree/p:sp", _NS)
    for sp in candidates:
        if _ph_of(sp)[0] in wanted and sp.find("p:nvSpPr/p:nvPr/p:ph", _NS) is not None:
            return sp
    if ph_idx is not None:
        for sp in candidates:
            ph = sp.find("p:nvSpPr/p:nvPr/p:ph", _NS)
            if ph is not None and ph.get("idx") == ph_idx:
                return sp
    return None


def _tx_style(master, ph_type: str):
    styles = master._element.find("p:txStyles", _NS)
    if styles is None:
        return None
    if ph_type in _TITLE_TYPES:
        return styles.find("p:titleStyle", _NS)
    if ph_type in _BODY_TYPES:
        return styles.find("p:bodyStyle", _NS)
    return styles.find("p:otherStyle", _NS)


def _spacing(el) -> dict | None:
    if el is None:
        return None
    pct = el.find("a:spcPct", _NS)
    if pct is not None and pct.get("val") is not None:
        return {"pct": int(pct.get("val")) / 100000}
    pts = el.find("a:spcPts", _NS)
    if pts is not None and pts.get("val") is not None:
        return {"pt": int(pts.get("val")) / 100}
    return None


def _first(sources: list, getter):
    for ppr in sources:
        if ppr is None:
            continue
        value = getter(ppr)
        if value is not None:
            return value
    return None


def _bool_attr(value: str | None) -> bool | None:
    if value is None:
        return None
    return value in ("1", "true")


def _resolve_level(pprs: list, theme: dict, emu: float) -> dict[str, Any]:
    fonts = theme["fonts"]
    out: dict[str, Any] = {}

    def rpr_attr(name):
        return lambda p: (p.find("a:defRPr", _NS).get(name) if p.find("a:defRPr", _NS) is not None else None)

    sz = _first(pprs, rpr_attr("sz"))
    if sz is not None:
        out["sizePt"] = int(sz) / 100
    for key in ("b", "i"):
        value = _bool_attr(_first(pprs, rpr_attr(key)))
        if value is not None:
            out["bold" if key == "b" else "italic"] = value
    cap = _first(pprs, rpr_attr("cap"))
    if cap is not None:
        out["caps"] = cap == "all"

    def rpr_child(tag):
        def get(p):
            rpr = p.find("a:defRPr", _NS)
            return rpr.find(tag, _NS) if rpr is not None else None
        return get

    color = resolve_color(_first(pprs, rpr_child("a:solidFill")), theme)
    if color:
        out["color"] = color
    latin = _first(pprs, lambda p: (rpr_child("a:latin")(p).get("typeface")
                                    if rpr_child("a:latin")(p) is not None else None))
    if latin:
        if latin.startswith("+mj"):
            out["fontRef"] = "major"
            latin = fonts.get("major")
        elif latin.startswith("+mn"):
            out["fontRef"] = "minor"
            latin = fonts.get("minor")
        if latin:
            out["font"] = latin

    algn = _first(pprs, lambda p: p.get("algn"))
    if algn in _ALIGN:
        out["align"] = _ALIGN[algn]
    mar_l = _first(pprs, lambda p: p.get("marL"))
    if mar_l is not None:
        out["marginLeftPx"] = px_value(int(mar_l), emu)
    indent = _first(pprs, lambda p: p.get("indent"))
    if indent is not None:
        out["indentPx"] = px_value(int(indent), emu)

    kind_el = _first(pprs, lambda p: next(
        (c for c in p if c.tag in (_q("a:buNone"), _q("a:buChar"), _q("a:buAutoNum"))), None))
    if kind_el is not None:
        bullet: dict[str, Any]
        if kind_el.tag == _q("a:buNone"):
            bullet = {"kind": "none"}
        elif kind_el.tag == _q("a:buChar"):
            bullet = {"kind": "char", "char": kind_el.get("char", "•")}
        else:
            bullet = {"kind": "autonum", "scheme": kind_el.get("type", "arabicPeriod")}
        if bullet["kind"] != "none":
            bu_font = _first(pprs, lambda p: (p.find("a:buFont", _NS).get("typeface")
                                              if p.find("a:buFont", _NS) is not None else None))
            if bu_font:
                bullet["font"] = bu_font
            bu_color = resolve_color(_first(pprs, lambda p: p.find("a:buClr", _NS)), theme)
            if bu_color:
                bullet["color"] = bu_color
            bu_size = _first(pprs, lambda p: (p.find("a:buSzPct", _NS).get("val")
                                              if p.find("a:buSzPct", _NS) is not None else None))
            if bu_size is not None:
                bullet["sizePct"] = round(int(bu_size) / 1000, 2)
        out["bullet"] = bullet

    for key, tag in (("lineSpacing", "a:lnSpc"), ("spaceBefore", "a:spcBef"), ("spaceAfter", "a:spcAft")):
        value = _first(pprs, lambda p, tag=tag: _spacing(p.find(tag, _NS)))
        if value is not None:
            out[key] = value
    return out


def _body_pr(sp):
    return sp.find("p:txBody/a:bodyPr", _NS) if sp is not None else None


def resolve_placeholder_style(prs, layout, ph_element, theme: dict) -> dict[str, Any]:
    """Resolved text style of one layout placeholder (``p:sp`` element).

    Returns ``{"anchor", "insets": {left, top, right, bottom} px, "levels": [...]}``;
    each level carries only the fields some source defines (sizePt, bold, italic,
    caps, color, font, fontRef, align, marginLeftPx, indentPx, bullet, lineSpacing,
    spaceBefore, spaceAfter). Spacing values are ``{"pct": ratio}`` or ``{"pt": n}``.
    """
    emu = theme["emuPerPx"]
    master = layout.slide_master
    ph_type, ph_idx = _ph_of(ph_element)
    master_sp = find_master_placeholder(master, ph_type, ph_idx)
    lst_sources = [
        ph_element.find("p:txBody/a:lstStyle", _NS),
        master_sp.find("p:txBody/a:lstStyle", _NS) if master_sp is not None else None,
        _tx_style(master, ph_type),
        prs._element.find("p:defaultTextStyle", _NS),
    ]

    levels = []
    for n in range(1, LEVELS + 1):
        pprs = [src.find(f"a:lvl{n}pPr", _NS) if src is not None else None for src in lst_sources]
        level = _resolve_level(pprs, theme, emu)
        level["level"] = n
        levels.append(level)

    body_prs = [_body_pr(ph_element), _body_pr(master_sp)]
    anchor = _first(body_prs, lambda b: b.get("anchor"))
    insets = {}
    for attr, key in (("lIns", "left"), ("tIns", "top"), ("rIns", "right"), ("bIns", "bottom")):
        value = _first(body_prs, lambda b, attr=attr: b.get(attr))
        insets[key] = px_value(int(value) if value is not None else _DEFAULT_INSETS[attr], emu)
    return {
        "anchor": _ANCHOR.get(anchor or "t", "top"),
        "insets": insets,
        "levels": levels,
    }
