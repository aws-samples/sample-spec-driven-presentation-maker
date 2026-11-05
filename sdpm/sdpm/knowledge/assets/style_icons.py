# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Draw the icons a style references, for display.

A style file holds icon references only: ``<svg class="icon"><use href="#<source>/<name>"/></svg>``,
where the id is the ``search_assets`` name. This module makes a display copy of a style
by adding one hidden sprite after ``<body>`` with a ``<symbol>`` per referenced id, built
from the asset catalog.

Use it only where a style is shown to a person (Web UI gallery and previews, the local
browser gallery). What agents read stays reference-only: MCP results, ``start_style``,
and the ``specs/art-direction.html`` copy on disk.

Ids already defined by a ``<symbol>`` in the document are used as-is (styles written
before references-only keep working). Ids missing from the catalog stay unresolved.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping

from lxml import etree

from . import AssetsNotInstalledError, resolve_asset_path

#: A catalog icon id: ``<source>/<name>``, one slash, no path traversal.
ICON_ID_RE = re.compile(r"[A-Za-z0-9_-]+/[A-Za-z0-9_][A-Za-z0-9_.-]*")

_USE_RE = re.compile(r"""<use\b[^>]*?\b(?:xlink:)?href\s*=\s*["']#([^"']+)["']""", re.IGNORECASE)
_SYMBOL_ID_RE = re.compile(r"""<symbol\b[^>]*?\bid\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_BODY_RE = re.compile(r"<body\b[^>]*>", re.IGNORECASE)
_FIRST_SLIDE_RE = re.compile(r"""<div\s+class\s*=\s*["']slide[\s"']""", re.IGNORECASE)

_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=True,
                          remove_pis=True, huge_tree=False)
_DROP_ELEMENTS = {"script", "foreignObject", "style"}
_ROOT_SKIP_ATTRS = {"width", "height", "x", "y", "id", "class", "version", "viewBox"}
_URL_REF_RE = re.compile(r"url\(\s*(['\"]?)#([^)'\"]+)\1\s*\)")
_SPRITE_OPEN = '<svg width="0" height="0" style="position:absolute" aria-hidden="true" data-sdpm-icons>'

#: Receives the ids to resolve, returns the SVG bytes of those it found.
IconLoader = Callable[[set[str]], Mapping[str, bytes]]


def is_icon_id(value: str) -> bool:
    """True when ``value`` is a well-formed catalog id (``<source>/<name>``)."""
    return bool(ICON_ID_RE.fullmatch(value)) and ".." not in value


def missing_icon_ids(html: str) -> list[str]:
    """Catalog ids the document references but does not define, in first-seen order."""
    defined = set(_SYMBOL_ID_RE.findall(html))
    seen: dict[str, None] = {}
    for ref in _USE_RE.findall(html):
        if ref not in defined and is_icon_id(ref):
            seen.setdefault(ref, None)
    return list(seen)


def load_catalog_icons(ids: Iterable[str]) -> dict[str, bytes]:
    """Read icons from the local asset catalog (user-local and extra sources included)."""
    found: dict[str, bytes] = {}
    for icon_id in ids:
        if not is_icon_id(icon_id):
            continue
        try:
            path = resolve_asset_path(f"assets:{icon_id}")
        except (FileNotFoundError, AssetsNotInstalledError):
            continue
        if path.suffix.lower() == ".svg":
            found[icon_id] = path.read_bytes()
    return found


def icon_symbol(icon_id: str, svg: bytes) -> str | None:
    """A ``<symbol id=icon_id>`` drawn from a catalog SVG, or None when it is not an SVG."""
    try:
        root = etree.fromstring(svg, _PARSER)
    except etree.XMLSyntaxError:
        return None
    if not isinstance(root.tag, str) or etree.QName(root).localname != "svg":
        return None

    for el in list(root.iter()):
        if el is root:
            continue
        if not isinstance(el.tag, str) or etree.QName(el).localname in _DROP_ELEMENTS:
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)

    prefix = f"{icon_id}--"
    ids = {el.get("id") for el in root.iter() if el is not root and el.get("id")}
    mapping = {old: prefix + old for old in ids}

    def fix_urls(value: str) -> str:
        return _URL_REF_RE.sub(lambda m: f"url(#{mapping.get(m.group(2), m.group(2))})", value)

    for el in root.iter():
        for name, value in list(el.attrib.items()):
            local = etree.QName(name).localname if name.startswith("{") else name
            if local.lower().startswith("on"):
                del el.attrib[name]
            elif name in ("href", _XLINK_HREF):
                if value.startswith("#") and value[1:] in mapping:
                    el.set(name, "#" + mapping[value[1:]])
                elif not value.startswith("#"):
                    del el.attrib[name]
            elif el is not root and name == "id" and value in mapping:
                el.set("id", mapping[value])
            elif "url(" in value:
                el.set(name, fix_urls(value))

    ns = etree.QName(root).namespace
    symbol = etree.Element(f"{{{ns}}}symbol" if ns else "symbol", nsmap={None: ns} if ns else None)
    symbol.set("id", icon_id)
    view_box = root.get("viewBox") or _size_view_box(root)
    if view_box:
        symbol.set("viewBox", view_box)
    for name, value in root.attrib.items():
        if name in _ROOT_SKIP_ATTRS or name.startswith("{") or ":" in name:
            continue
        symbol.set(name, value)
    for child in list(root):
        symbol.append(child)
    text = etree.tostring(symbol, encoding="unicode")
    # the sprite sits in HTML, where the svg namespace is implied
    return text.replace(f' xmlns="{ns}"', "", 1) if ns else text


def _size_view_box(root) -> str | None:
    def number(value: str | None) -> str | None:
        m = re.fullmatch(r"\s*([0-9.]+)\s*(px)?\s*", value or "")
        return m.group(1) if m else None

    w, h = number(root.get("width")), number(root.get("height"))
    return f"0 0 {w} {h}" if w and h else None


def _insert_sprite(html: str, sprite: str) -> str:
    body = _BODY_RE.search(html)
    if body:
        at = body.end()
        return html[:at] + "\n" + sprite + html[at:]
    slide = _FIRST_SLIDE_RE.search(html)
    at = slide.start() if slide else 0
    return html[:at] + sprite + "\n" + html[at:]


def inline_style_icons_many(htmls: list[str], load: IconLoader | None = None) -> list[str]:
    """Display copies of style documents, with their referenced catalog icons drawn in.

    ``load`` is called once with the union of every document's missing ids; it defaults
    to the local asset catalog. A document with nothing to add is returned unchanged.
    """
    wanted = [missing_icon_ids(html) for html in htmls]
    union = {icon_id for ids in wanted for icon_id in ids}
    if not union:
        return list(htmls)
    loaded = (load or load_catalog_icons)(union)
    symbols: dict[str, str] = {}
    for icon_id in union:
        svg = loaded.get(icon_id)
        if svg is None:
            continue
        symbol = icon_symbol(icon_id, svg)
        if symbol:
            symbols[icon_id] = symbol
    out: list[str] = []
    for html, ids in zip(htmls, wanted):
        parts = [symbols[i] for i in ids if i in symbols]
        out.append(_insert_sprite(html, _SPRITE_OPEN + "".join(parts) + "</svg>") if parts else html)
    return out


def inline_style_icons(html: str, load: IconLoader | None = None) -> str:
    """Display copy of one style document (see :func:`inline_style_icons_many`)."""
    return inline_style_icons_many([html], load)[0]
