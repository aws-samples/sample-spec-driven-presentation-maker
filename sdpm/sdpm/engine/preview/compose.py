# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""SVG composition: split LibreOffice SVG into optimized per-slide components.

Consumed by the Web UI live preview (build animation). Both servers call it
after ``run_python``: MCP Local writes the result to ``compose/`` in the deck
directory, MCP Remote uploads it to S3. Storage and file naming stay in the
servers; everything here is computation on the SVG and on compose payloads.
"""

import base64
import hashlib
import io
import json
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

_INHERITABLE_ATTRS = ("fill-rule", "stroke-width", "stroke-linejoin")
"""Presentation attributes that LibreOffice sets once on root <svg> and children inherit."""


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


XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
_BITMAP_REF_RE = re.compile(r"#bitmap\(\d+\)")
_TRANSLATE_RE = re.compile(r"translate\(\s*(-?[\d.]+)[\s,]+(-?[\d.]+)\s*\)")
_SCALE_RE = re.compile(r"scale\(\s*(-?[\d.eE+-]+)[\s,]+(-?[\d.eE+-]+)\s*\)")


def _repair_bitmap_refs(root: etree._Element) -> None:
    """Replace LibreOffice's dangling ``<use xlink:href="#bitmap(N)">`` with the image it means.

    LibreOffice writes a bitmap's first occurrence as an inline ``<image>`` and every later
    occurrence of the same bitmap (the same logo on another layout, the same picture on
    another slide) as ``<use xlink:href="#bitmap(N)" transform="translate(source - point)
    scale(size / source)">``, but never gives the first ``<image>`` that id, so the copies draw
    nothing. The source is the earlier ``<image>`` whose rect, run through that transform,
    lands on the shape's BoundingBox. Ambiguous or unmatched references are left as they are.
    """
    images = []  # (x, y, w, h, href) of inline images, in document order
    for el in root.iter(f"{{{SVG_NS}}}image", f"{{{SVG_NS}}}use"):
        if el.tag == f"{{{SVG_NS}}}image":
            try:
                images.append(tuple(float(el.get(a, "")) for a in ("x", "y", "width", "height"))
                              + (el.get(XLINK_HREF),))
            except ValueError:
                pass
            continue
        ref = el.get(XLINK_HREF, "")
        if not _BITMAP_REF_RE.fullmatch(ref) or root.find(f".//*[@id='{ref[1:]}']") is not None:
            continue
        bbox = el.getparent().find(f"{{{SVG_NS}}}rect[@class='BoundingBox']")
        if bbox is None:
            continue
        try:
            box = tuple(float(bbox.get(a, "")) for a in ("x", "y", "width", "height"))
        except ValueError:
            continue
        transform = el.get("transform", "")
        t = _TRANSLATE_RE.search(transform)
        s = _SCALE_RE.search(transform)
        sx, sy = (float(s.group(1)), float(s.group(2))) if s else (1.0, 1.0)
        matches = []
        for x, y, w, h, href in images:
            # No translate means LibreOffice placed the copy at the origin.
            px, py = (x - float(t.group(1)), y - float(t.group(2))) if t else (0.0, 0.0)
            rect = (px, py, w * sx, h * sy)
            if href and all(abs(a - b) <= 2 for a, b in zip(rect, box)):
                matches.append((rect, href))
        if len({href for _, href in matches}) != 1:
            continue
        (px, py, pw, ph), href = matches[0]
        image = etree.Element(f"{{{SVG_NS}}}image", {
            "x": f"{px:g}", "y": f"{py:g}", "width": f"{pw:g}", "height": f"{ph:g}",
            "preserveAspectRatio": "none", XLINK_HREF: href,
        })
        image.tail = el.tail
        el.getparent().replace(el, image)


def load_svg(svg_path: Path) -> etree._ElementTree:
    """Parse a LibreOffice SVG once so several extractions can share the tree."""
    tree = etree.parse(str(svg_path))
    _repair_bitmap_refs(tree.getroot())
    return tree


def _as_tree(svg: "Path | etree._ElementTree") -> etree._ElementTree:
    return svg if isinstance(svg, etree._ElementTree) else load_svg(svg)


def count_slides(svg_path: "Path | etree._ElementTree") -> int:
    """Return the number of slides in a LibreOffice SVG.

    Accepts a path or a tree from :func:`load_svg`.
    """
    root = _as_tree(svg_path).getroot()
    return len(root.findall(f".//{{{SVG_NS}}}g[@class='Slide']"))


def extract_optimized_defs(svg_path: "Path | etree._ElementTree") -> dict:
    """Extract shared defs: strip SVG fonts, convert PNG→WebP.

    Accepts a path or a tree from :func:`load_svg`.
    Returns {"version": 1, "defs": str}.
    """
    tree = _as_tree(svg_path)
    root = tree.getroot()
    defs_elements = root.findall(f"{{{SVG_NS}}}defs")
    for d in defs_elements:
        _strip_fonts(d)
    defs_svg = "".join(etree.tostring(d, encoding="unicode") for d in defs_elements)
    return {"version": 1, "defs": _convert_images(defs_svg)}


def _propagate_root_attrs(element: etree._Element, root_attrs: dict) -> None:
    """Copy inheritable root attrs onto element if not already present."""
    for attr, value in root_attrs.items():
        if element.get(attr) is None:
            element.set(attr, value)


def split_slide_components(svg_path: "Path | etree._ElementTree", slide_num: int) -> dict:
    """Split one slide into component fragments with metadata (defs excluded).

    Accepts a path or a tree from :func:`load_svg`; the tree is only read
    (attributes are propagated onto the slide's own elements), so one parse
    can serve every slide.
    Returns {"version": 1, "viewBox": str, "bgFill": str,
             "bgSvg": str|None, "components": [...]}.
    """
    tree = _as_tree(svg_path)
    root = tree.getroot()
    view_box = root.get("viewBox", "0 0 33867 19050")

    # Collect inheritable presentation attributes from root <svg>
    root_attrs = {}
    for attr in _INHERITABLE_ATTRS:
        val = root.get(attr)
        if val is not None:
            root_attrs[attr] = val

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
                _propagate_root_attrs(child, root_attrs)
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
                            _propagate_root_attrs(bg_g, root_attrs)
                            parts.append(etree.tostring(bg_g, encoding="unicode"))
                            for el in bg_g.iter():
                                f = el.get("fill")
                                if f and f != "none":
                                    bg_fill = f
                                    break
                        bo_g = master_g.find(f"{{{SVG_NS}}}g[@class='BackgroundObjects']")
                        if bo_g is not None:
                            for child in bo_g:
                                # Layout placeholders (com.sun.star.presentation.SubtitleShape, ...)
                                # carry the layout's prompt text; LibreOffice hides only the title
                                # and outline ones on master pages, and slides never draw them.
                                # DateTime / Footer / PageNumber have their own classes.
                                if (child.get("visibility") != "hidden"
                                        and not child.get("class", "").startswith("com.sun.star.presentation.")):
                                    _propagate_root_attrs(child, root_attrs)
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
        _propagate_root_attrs(shape_g, root_attrs)
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


# --- The defs one slide draws from ---

# A local reference: href="#id" / xlink:href="#id" / url(#id) / url('#id').
_LOCAL_REF_RE = re.compile(r"""(?:href\s*=\s*["']#([^"']+)["']|url\(\s*["']?#([^"')\s]+))""")


def _local_refs(text: str) -> set[str]:
    return {a or b for a, b in _LOCAL_REF_RE.findall(text)}


def referenced_defs(defs: str, fragments: "list[str]") -> str:
    """The elements of the deck's ``defs`` (``extract_optimized_defs``) that ``fragments`` (a
    slide's ``bgSvg`` and component SVGs) reference, followed transitively, as one ``<defs>``.

    The deck's defs also hold every master page, whose background images are already inlined
    into each slide's ``bgSvg``; inside ``<defs>`` they are never drawn. Returns ``""`` when
    nothing is referenced, and ``defs`` unchanged when it cannot be parsed.
    """
    wanted = set().union(*(_local_refs(f) for f in fragments)) if fragments else set()
    if not wanted or not defs:
        return ""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        root = etree.fromstring(f'<svg xmlns="{SVG_NS}">{defs}</svg>', parser)
    except etree.XMLSyntaxError:
        return defs
    by_id = {el.get("id"): el for el in root.iter() if isinstance(el.tag, str) and el.get("id")}
    picked: set[str] = set()
    todo = [i for i in wanted if i in by_id]
    while todo:
        ref = todo.pop()
        if ref in picked:
            continue
        picked.add(ref)
        todo.extend(i for i in _local_refs(etree.tostring(by_id[ref], encoding="unicode")) if i in by_id)
    # Document order; an element inside one already picked comes with it.
    out = [
        el for el in root.iter()
        if isinstance(el.tag, str) and el.get("id") in picked
        and not any(a.get("id") in picked for a in el.iterancestors())
    ]
    if not out:
        return ""
    body = "".join(etree.tostring(el, encoding="unicode", with_tail=False) for el in out)
    return f'<defs xmlns="{SVG_NS}">{body}</defs>'


# --- Component-level diff against the previous compose of the same slide ---


def source_hash(slide: dict) -> str:
    """Content hash of a slide's JSON, stored as ``sourceHash`` in the compose payload."""
    return hashlib.md5(
        json.dumps(slide, sort_keys=True, ensure_ascii=False).encode(),
        usedforsecurity=False,
    ).hexdigest()


def _mk(c: dict) -> str:
    """Match key: class + bbox identifies "the same component" across builds."""
    b = c.get("bbox")
    return f"{c['class']}|{b['x']},{b['y']},{b['w']},{b['h']}" if b else f"{c['class']}|none"


def _fp(c: dict) -> str:
    """Fingerprint: class + text decides whether a matched component changed."""
    return f"{c['class']}|{c.get('text', '')}"


def mark_changed(
    components: list[dict],
    prev_components: "list[dict] | None",
    src_hash: str = "",
    prev_hash: "str | None" = None,
) -> None:
    """Set ``changed`` on each component by comparing with the previous compose.

    - No previous compose (``prev_components is None``): every component changed.
    - Same non-empty ``src_hash`` as the previous compose: nothing changed.
    - Otherwise a component changed when no previous component has the same
      class + bbox, or the matched one had different text.
    """
    if prev_components is None:
        for c in components:
            c["changed"] = True
    elif src_hash and prev_hash == src_hash:
        for c in components:
            c["changed"] = False
    else:
        prev_map = {_mk(c): _fp(c) for c in prev_components}
        for c in components:
            k = _mk(c)
            c["changed"] = k not in prev_map or prev_map[k] != _fp(c)
