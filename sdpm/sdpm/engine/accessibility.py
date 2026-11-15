# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Accessibility metadata shared by the builder and the converter.

Element level: ``alt`` -> ``p:cNvPr@descr`` (the alt text PowerPoint shows and
screen readers read) and ``decorative`` -> PowerPoint's ``adec:decorative``
extension. Deck level: ``title`` / ``language`` -> ``docProps/core.xml``
``dc:title`` / ``dc:language``.
"""

from __future__ import annotations

import re

from lxml import etree
from pptx.oxml.ns import qn

DECORATIVE_URI = "{C183D7F6-B498-43B3-948B-1728B52AA6E4}"
_ADEC_NS = "http://schemas.microsoft.com/office/drawing/2017/decorative"

# python-pptx writes the image file name as descr; that is not alt text.
# shortcut: a bare file name is treated as "no alt"; widen if other tools'
# placeholder descriptions show up in imported decks.
_FILENAME_DESCR = re.compile(r"^[^/\\]+\.(?:png|jpe?g|gif|bmp|svg|webp|tiff?|emf|wmf)$", re.IGNORECASE)


def _cnvpr(node):
    """Return the node's own ``cNvPr`` (first child is its ``nv*Pr``), or None."""
    found = node.xpath("./*[1]/*[local-name()='cNvPr']")
    return found[0] if found else None


def write_element_metadata(node, elem: dict) -> None:
    """Write ``alt`` / ``decorative`` from *elem* onto *node*'s ``cNvPr``.

    Elements without either key are left as built.
    """
    alt = elem.get("alt")
    decorative = elem.get("decorative") is True
    if alt is None and not decorative:
        return
    cnvpr = _cnvpr(node)
    if cnvpr is None:
        return
    if decorative:
        # A decorative object carries no description, so screen readers skip it.
        cnvpr.attrib.pop("descr", None)
        ext_lst = cnvpr.find(qn("a:extLst"))
        if ext_lst is None:
            ext_lst = etree.SubElement(cnvpr, qn("a:extLst"))
        if not any(e.get("uri") == DECORATIVE_URI for e in ext_lst):
            ext = etree.SubElement(ext_lst, qn("a:ext"), uri=DECORATIVE_URI)
            etree.SubElement(ext, f"{{{_ADEC_NS}}}decorative", nsmap={"adec": _ADEC_NS}, val="1")
    elif isinstance(alt, str):
        cnvpr.set("descr", alt)


def read_element_metadata(node) -> dict:
    """Return ``{"alt": ..., "decorative": True}`` read from *node*'s ``cNvPr``."""
    cnvpr = _cnvpr(node)
    if cnvpr is None:
        return {}
    for ext in cnvpr.iterfind(f"{qn('a:extLst')}/{qn('a:ext')}"):
        if ext.get("uri") == DECORATIVE_URI:
            flag = ext.find(f"{{{_ADEC_NS}}}decorative")
            if flag is not None and flag.get("val") in ("1", "true"):
                return {"decorative": True}
    descr = cnvpr.get("descr")
    if descr and descr.strip() and not _FILENAME_DESCR.match(descr.strip()):
        return {"alt": descr}
    return {}


def write_document_properties(prs, title: str | None = None, language: str | None = None) -> None:
    """Set ``dc:title`` (fallback: the first slide's title) and ``dc:language``."""
    if not isinstance(title, str) or not title.strip():
        title = None
        if len(prs.slides):
            title_shape = prs.slides[0].shapes.title
            if title_shape is not None and title_shape.has_text_frame:
                title = " ".join(title_shape.text_frame.text.split())
    # Core properties are limited to 255 characters each.
    if title:
        prs.core_properties.title = title[:255]
    if isinstance(language, str) and language.strip():
        prs.core_properties.language = language.strip()[:255]


def read_document_properties(prs) -> dict:
    """Return the deck-level ``title`` / ``language`` stored in core properties."""
    props = prs.core_properties
    out: dict = {}
    if props.title and props.title.strip():
        out["title"] = props.title
    if props.language and props.language.strip():
        out["language"] = props.language
    return out
