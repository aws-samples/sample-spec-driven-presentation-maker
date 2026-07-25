# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Deck-structure text summary: slide dicts → readable text.

Pure "dict → text" logic shared by the Local (filesystem) and Cloud (S3)
upload-reading paths. Each consumer performs its own I/O (reading slide
JSONs) and output formatting (pagination, line numbering); this module owns
only the summary content so agents receive identical text from both modes.
"""

from __future__ import annotations

from collections.abc import Iterable


def extract_slide_title(data: dict) -> str:
    """Return the slide title from ``title`` (plain string or dict-with-text).

    Args:
        data: A slide JSON dict.

    Returns:
        Title string, or "" when absent.
    """
    t = data.get("title")
    if isinstance(t, str):
        return t
    if isinstance(t, dict):
        return t.get("text", "") or ""
    return ""


def collect_slide_text(node, out: list[str]) -> None:
    """Recursively append human-readable text found in a slide element.

    Collects element ``text``, ``subtitle``, ``label``, ``date``, ``notes``,
    ``paragraphs[].text``, ``items``, table ``headers`` / ``rows``, and
    recurses into group ``elements``.

    Args:
        node: Slide element (dict) or arbitrary JSON node.
        out: List to append found strings to (in document order).
    """
    if isinstance(node, dict):
        for key in ("text", "subtitle", "label", "date", "notes"):
            v = node.get(key)
            if isinstance(v, str) and v.strip():
                out.append(v)
        for p in node.get("paragraphs", []) or []:
            if isinstance(p, dict):
                t = p.get("text")
                if isinstance(t, str) and t.strip():
                    out.append(t)
        for item in node.get("items", []) or []:
            if isinstance(item, str) and item.strip():
                out.append(item)
        headers = node.get("headers")
        if isinstance(headers, list):
            out.extend(str(c) for c in headers if c)
        rows = node.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, list):
                    out.extend(str(c) for c in row if c)
        for child in node.get("elements", []) or []:
            collect_slide_text(child, out)


def deck_text_summary(slides: Iterable[dict]) -> str:
    """Format ordered slide dicts as a markdown-style text summary.

    Output shape::

        --- Slide 1: <title> ---
        <body text>

        --- Slide 2: <title> ---
        ...

    Args:
        slides: Slide JSON dicts in presentation order.

    Returns:
        Summary text (sections joined by blank lines).
    """
    sections: list[str] = []
    for i, data in enumerate(slides, start=1):
        title = extract_slide_title(data)
        header = f"--- Slide {i}: {title} ---" if title else f"--- Slide {i} ---"
        body_parts: list[str] = []
        for el in data.get("elements", []) or []:
            collect_slide_text(el, body_parts)
        # Drop duplicates while keeping order
        seen: set[str] = set()
        deduped: list[str] = []
        for p in body_parts:
            if p not in seen:
                seen.add(p)
                deduped.append(p)
        body = "\n".join(deduped)
        sections.append(f"{header}\n{body}".rstrip())
    return "\n\n".join(sections)
