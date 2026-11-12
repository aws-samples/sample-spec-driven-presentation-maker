# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The two slug grammars and the outline.md parsers (slide slugs, display entries), each defined once.

- Outline grammar ``[a-z0-9-]+`` (``OUTLINE_SLUG_RE``): the slugs of specs/outline.md
  slide lines ``- [slug] message`` — what the build, check_specs and the outline lint accept.
- Artifact grammar ``[a-z0-9][a-z0-9_-]*`` (``SLUG_RE``): the slugs in artifact names and
  keys (preview images, browser-check PNGs, HTML previews, review comments). It also
  accepts the legacy numbered slugs ``slide_NN`` of pre-outline decks.

The two are deliberately different (widening the outline grammar would change lint
results). Both regexes are meant for ``fullmatch``. The Web UI copies them; their
parity is checked by tests/test_slug_parity.py.
"""

from __future__ import annotations

import re

OUTLINE_SLUG = r"[a-z0-9-]+"
SLUG = r"[a-z0-9][a-z0-9_-]*"

OUTLINE_SLUG_RE = re.compile(OUTLINE_SLUG)
SLUG_RE = re.compile(SLUG)

# A slide line as the build reads it (raw line, ``match``): a valid slug, message optional.
OUTLINE_ENTRY_RE = re.compile(rf"^-\s*\[({OUTLINE_SLUG})\]")
# A slide line as the lint and check_specs read it (stripped line): any bracketed
# text followed by a message, so an invalid slug is reported instead of skipped.
OUTLINE_LINE_RE = re.compile(r"^-\s+\[([^\]]+)\]\s+.+")


def parse_outline_text(text: str) -> list[str]:
    """Slugs of the slide lines ``- [slug] message`` of outline.md text, in document order.

    Lines whose bracketed text is not an outline slug are skipped (the lint reports them).
    """
    slugs: list[str] = []
    for line in text.splitlines():
        m = OUTLINE_ENTRY_RE.match(line)
        if m:
            slugs.append(m.group(1))
    return slugs


# The Web UI outline view's line grammar (web-ui/src/components/deck/outlineParser.ts).
_ENTRY_SLIDE_RE = re.compile(r"^-\s*\[([^\]]+)\]\s*(.*)")
_ENTRY_SUB_ITEM_RE = re.compile(r"^\s+-\s*(body|visual|evidence):\s*(.*)")
_ENTRY_SECTION_RE = re.compile(r"^##\s+(.+)")


def parse_outline_entries(text: str) -> list[dict]:
    """outline.md text as display entries in document order, as the Web UI outline view reads it.

    - ``{"type": "slide", "slug", "message", "subItems": [{"key", "value"}]}`` for
      ``- [slug] message`` (any bracketed text; sub-items ``  - body|visual|evidence: …``
      follow their slide)
    - ``{"type": "section", "title"}`` for ``## Title``
    - ``{"type": "prose", "text"}`` for any other non-blank line, kept as written

    A section or prose line ends the slide's sub-items. The Python port of the Web UI's
    ``parseOutline``; CRLF lines parse like LF.
    """
    entries: list[dict] = []
    slide: dict | None = None
    for raw in text.split("\n"):
        line = raw[:-1] if raw.endswith("\r") else raw
        m = _ENTRY_SLIDE_RE.match(line)
        if m:
            slide = {"type": "slide", "slug": m.group(1), "message": m.group(2).strip(), "subItems": []}
            entries.append(slide)
            continue
        m = _ENTRY_SUB_ITEM_RE.match(line)
        if m and slide is not None:
            slide["subItems"].append({"key": m.group(1), "value": m.group(2).strip()})
            continue
        m = _ENTRY_SECTION_RE.match(line)
        if m:
            slide = None
            entries.append({"type": "section", "title": m.group(1).strip()})
            continue
        if line.strip() == "":
            continue
        slide = None
        entries.append({"type": "prose", "text": line})
    return entries
