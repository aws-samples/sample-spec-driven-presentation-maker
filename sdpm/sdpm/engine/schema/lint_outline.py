# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Outline.md linter — validates format before save."""

from __future__ import annotations

from sdpm.engine.schema.slugs import OUTLINE_LINE_RE, OUTLINE_SLUG_RE


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
        m = OUTLINE_LINE_RE.match(stripped)
        if not m:
            continue
        slug = m.group(1)
        if not OUTLINE_SLUG_RE.fullmatch(slug):
            diagnostics.append({"line": i, "rule": "slug-pattern"})
        elif slug in seen_slugs:
            diagnostics.append({"line": i, "rule": "slug-duplicate"})
        else:
            seen_slugs.add(slug)

    if not seen_slugs and not diagnostics:
        diagnostics.append({"line": 0, "rule": "no-slides"})

    return diagnostics
