# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The two slug grammars and the outline.md slide-line parsers, each defined once.

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
