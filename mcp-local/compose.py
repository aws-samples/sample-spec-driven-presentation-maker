# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""SVG composition: split LibreOffice SVG into optimized per-slide components.

MCP Remote only — consumed by WebUI for build animation.
Not shared with Engine/CLI/MCP Local (no consumer there).
"""

import base64
import io
import logging
import re
from pathlib import Path

from lxml import etree
from PIL import Image

logger = logging.getLogger("sdpm.compose")

SVG_NS = "http://www.w3.org/2000/svg"
OOO_NS = "http://xml.openoffice.org/svg/export"
_PNG_B64_RE = re.compile(r"data:image/png;base64,([A-Za-z0-9+/=]+)")
# Strip textLength/lengthAdjust on <text>/<tspan> — webkit compresses glyphs
# when these are present, while measure reads BoundingBox rects (unaffected).
_TEXT_LENGTH_RE = re.compile(r'\s(?:textLength|lengthAdjust)="[^"]*"')


def _png_to_webp_b64(match: re.Match) -> str:
    png_data = base64.b64decode(match.group(1))
    img = Image.open(io.BytesIO(png_data))
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=80)
    return f"data:image/webp;base64,{base64.b64encode(buf.getvalue()).decode()}"


def _convert_images(svg_str: str) -> str:
    return _TEXT_LENGTH_RE.sub("", _PNG_B64_RE.sub(_png_to_webp_b64, svg_str))


def _strip_fonts(defs_el: etree._Element) -> None:
    for font in defs_el.findall(f".//{{{SVG_NS}}}font"):
        font.getparent().remove(font)


def count_slides(svg_path: Path) -> int:
    """Return the number of slides in a LibreOffice SVG."""
    root = etree.parse(str(svg_path)).getroot()
    return len(root.findall(f".//{{{SVG_NS}}}g[@class='Slide']"))


def extract_optimized_defs(svg_path: Path) -> dict:
    """Extract shared defs: strip SVG fonts, convert PNG→WebP.

    Returns {"version": 1, "defs": str}.
    """
    tree = etree.parse(str(svg_path))
    root = tree.getroot()
    defs_elements = root.findall(f"{{{SVG_NS}}}defs")
    for d in defs_elements:
        _strip_fonts(d)
    defs_svg = "".join(etree.tostring(d, encoding="unicode") for d in defs_elements)
    return {"version": 1, "defs": _convert_images(defs_svg)}


def split_slide_components(svg_path: Path, slide_num: int) -> dict:
    """Split one slide into component fragments with metadata (defs excluded).

    Returns {"version": 1, "viewBox": str, "bgFill": str,
             "bgSvg": str|None, "components": [...]}.
    """
    tree = etree.parse(str(svg_path))
    root = tree.getroot()
    view_box = root.get("viewBox", "0 0 33867 19050")

    slides = root.findall(f".//{{{SVG_NS}}}g[@class='Slide']")
    if slide_num >= len(slides):
        raise ValueError(f"Slide {slide_num} not found (total: {len(slides) - 1})")

    page_g = slides[slide_num].find(f"{{{SVG_NS}}}g[@class='Page']")
    if page_g is None:
        raise ValueError("No Page group found")

    # --- Background ---
    bg_fill = "#000"
    bg_svg = None

    # 1) Slide-specific custom background (Page > defs.SlideBackground)
    slide_bg_defs = page_g.find(f"{{{SVG_NS}}}defs[@class='SlideBackground']")
    if slide_bg_defs is not None:
        parts = []
        for child in slide_bg_defs:
            cls = child.get("class", "")
            if cls in ("Background", "BackgroundObjects"):
                parts.append(etree.tostring(child, encoding="unicode"))
                if cls == "Background":
                    for el in child.iter():
                        f = el.get("fill")
                        if f and f != "none":
                            bg_fill = f
                            break
        if parts:
            bg_svg = _convert_images("\n".join(parts))

    # 2) Fallback: master page background
    if bg_svg is None:
        meta_slides = root.find(f".//{{{SVG_NS}}}g[@id='ooo:meta_slides']")
        if meta_slides is not None:
            meta = meta_slides.find(f".//{{{SVG_NS}}}g[@id='ooo:meta_slide_{slide_num - 1}']")
            if meta is not None:
                master_id = meta.get(f"{{{OOO_NS}}}master", "")
                if master_id:
                    master_g = root.find(f".//*[@id='{master_id}']")
                    if master_g is not None:
                        parts = []
                        bg_g = master_g.find(f"{{{SVG_NS}}}g[@class='Background']")
                        if bg_g is not None:
                            parts.append(etree.tostring(bg_g, encoding="unicode"))
                            for el in bg_g.iter():
                                f = el.get("fill")
                                if f and f != "none":
                                    bg_fill = f
                                    break
                        bo_g = master_g.find(f"{{{SVG_NS}}}g[@class='BackgroundObjects']")
                        if bo_g is not None:
                            for child in bo_g:
                                if child.get("visibility") != "hidden":
                                    parts.append(etree.tostring(child, encoding="unicode"))
                        if parts:
                            bg_svg = _convert_images("\n".join(parts))

    # --- Components ---
    components = []
    for shape_g in page_g:
        if shape_g.tag != f"{{{SVG_NS}}}g":
            continue
        cls = shape_g.get("class", "")
        bbox_el = shape_g.find(f".//{{{SVG_NS}}}rect[@class='BoundingBox']")
        bbox = None
        if bbox_el is not None:
            bbox = {
                "x": float(bbox_el.get("x", 0)),
                "y": float(bbox_el.get("y", 0)),
                "w": float(bbox_el.get("width", 0)),
                "h": float(bbox_el.get("height", 0)),
            }
        text_el = shape_g.find(f".//{{{SVG_NS}}}text")
        text = ""
        if text_el is not None:
            text = "".join(text_el.itertext()).strip()[:80]
        components.append({
            "class": cls,
            "bbox": bbox,
            "text": text,
            "svg": _convert_images(etree.tostring(shape_g, encoding="unicode")),
        })

    return {
        "version": 1,
        "viewBox": view_box,
        "bgFill": bg_fill,
        "bgSvg": bg_svg,
        "components": components,
    }
