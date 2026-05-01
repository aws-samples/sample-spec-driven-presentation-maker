# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Outline.md linter — validates format before save."""

from __future__ import annotations

import re

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
_LINE_RE = re.compile(r"^-\s+\[([^\]]+)\]\s+.+")
_SUB_ITEM_RE = re.compile(r"^-\s+\w[\w_]*:\s")


def lint_outline(text: str) -> list[dict]:
    """Lint outline.md text and return diagnostics.

    Returns empty list if valid.
    """
    diagnostics: list[dict] = []
    seen_slugs: set[str] = set()

    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Sub-items (indented `- key: value`) are valid in detailed outlines
        if line[0] in (" ", "\t") and _SUB_ITEM_RE.match(stripped):
            continue
        m = _LINE_RE.match(stripped)
        if not m:
            diagnostics.append({"line": i, "rule": "format"})
            continue
        slug = m.group(1)
        if not _SLUG_RE.match(slug):
            diagnostics.append({"line": i, "rule": "slug-pattern"})
        elif slug in seen_slugs:
            diagnostics.append({"line": i, "rule": "slug-duplicate"})
        else:
            seen_slugs.add(slug)

    return diagnostics
