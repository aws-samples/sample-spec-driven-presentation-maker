# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Plain-text summary of one ``slides/<slug>.html`` (search indexing)."""

from __future__ import annotations

import re

from sdpm.engine.html.assemble import parse_slide

MAX_TEXT_CHARS = 4000

_WS_RE = re.compile(r"\s+")


def _collapse(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def _is_notes(el) -> bool:
    return el.tag == "aside" and "notes" in (el.get("class") or "").split()


def _visible_text(el) -> list[str]:
    """Text of ``el`` without ``aside.notes``, ``<style>`` and ``<script>`` subtrees."""
    parts: list[str] = []
    if isinstance(el.tag, str) and el.tag not in ("style", "script") and not _is_notes(el):
        parts.append(el.text or "")
        for child in el:
            parts.extend(_visible_text(child))
    parts.append(el.tail or "")
    return parts


def slide_text_summary(text: str) -> dict[str, str | None]:
    """``{layout, title, notes, text}`` of a slide file.

    title: the first ``[data-ph="title"]``, else the first ``<h1>`` / ``<h2>``;
    notes: the ``aside.notes`` text; text: the section text without notes and
    styles, whitespace-collapsed, at most ``MAX_TEXT_CHARS`` characters. Empty
    strings (layout None) when the file has no usable ``<section>``.
    """
    section = parse_slide(text).section
    if section is None:
        return {"layout": None, "title": "", "notes": "", "text": ""}
    title_el = next(iter(section.xpath('.//*[@data-ph="title"]')), None)
    if title_el is None:
        title_el = next(iter(section.xpath(".//h1 | .//h2")), None)
    title = _collapse(" ".join(_visible_text(title_el)[:-1])) if title_el is not None else ""
    notes = " ".join(_collapse(el.text_content()) for el in section.iter("aside") if _is_notes(el))
    body = _collapse(" ".join(_visible_text(section)[:-1]))
    return {
        "layout": section.get("data-layout"),
        "title": title,
        "notes": notes.strip(),
        "text": body[:MAX_TEXT_CHARS],
    }


__all__ = ["MAX_TEXT_CHARS", "slide_text_summary"]
