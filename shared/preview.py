# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Slug → S3 preview key resolution (epoch-keyed; latest epoch wins).

Preview S3 layout:
    previews/{deck_id}/{slug}_{epoch}.webp

build_slide_key_map returns slug → key map. The legacy signature returned
page-number → key, but slides are now keyed by slug end-to-end.
"""

import re
from typing import Iterable

# Matches {slug}_{epoch}.(webp|png) at end of S3 key.
# Slug = lowercase letters, digits, hyphens (matches outline.md format).
# Also accepts legacy "slide_NN" as a slug for backwards compatibility.
_PREVIEW_RE = re.compile(r"([a-z0-9][a-z0-9-_]*)_(\d+)\.(?:webp|png)$")


def build_slide_key_map(keys: Iterable[str]) -> dict[str, str]:
    """Build a map of slug → latest S3 key (highest epoch wins)."""
    best: dict[str, tuple[int, str]] = {}
    for key in keys:
        m = _PREVIEW_RE.search(key)
        if not m:
            continue
        slug = m.group(1)
        epoch = int(m.group(2))
        if slug not in best or epoch > best[slug][0]:
            best[slug] = (epoch, key)
    return {slug: key for slug, (_, key) in best.items()}
