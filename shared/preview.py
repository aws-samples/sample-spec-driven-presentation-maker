# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Slide number → S3 key resolution for epoch-based preview keys."""

import re
from typing import Iterable

_SLIDE_RE = re.compile(r"slide_(\d+)(?:_(\d+))?\.(?:webp|png)$")


def build_slide_key_map(keys: Iterable[str]) -> dict[int, str]:
    """Build a map of slide number → latest S3 key (highest epoch wins)."""
    best: dict[int, tuple[int, str]] = {}
    for key in keys:
        m = _SLIDE_RE.search(key)
        if not m:
            continue
        num = int(m.group(1))
        epoch = int(m.group(2)) if m.group(2) else 0
        if num not in best or epoch > best[num][0]:
            best[num] = (epoch, key)
    return {num: key for num, (_, key) in best.items()}
