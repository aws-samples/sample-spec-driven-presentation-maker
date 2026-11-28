# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Keys the builder honours must be named in the guide composers read.

A composer writes slide JSON from ``slide-json-elements.md`` alone, so a key
the builder honours but the guide never names does not exist in practice. Both
sets below were implemented and undocumented: radial gradients were built by
hand out of concentric circles, and arrowheads on thick lines were left blunt.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "sdpm"
ELEMENTS_GUIDE = (ROOT / "references" / "guides" / "slide-json-elements.md").read_text()

# Nested inside gradient.stops[] and shown in the guide's JSON examples.
_STOP_KEYS = {"stops", "position", "color", "opacity"}


def _keys_read_from(source: Path, subject: str) -> set[str]:
    """Public keys the source reads off ``subject`` (``subject.get("k")``...)."""
    text = source.read_text()
    found = set(re.findall(rf'{subject}\.get\(\s*[\'"]([A-Za-z_]\w*)[\'"]', text))
    found |= set(re.findall(rf'{subject}\[\s*[\'"]([A-Za-z_]\w*)[\'"]\s*\]', text))
    return {k for k in found if not k.startswith("_")}


GRADIENT_KEYS = sorted(
    _keys_read_from(ROOT / "sdpm" / "engine" / "builder" / "formatting.py", "gradient")
    - _STOP_KEYS
)
ARROW_KEYS = sorted(
    k for k in _keys_read_from(ROOT / "sdpm" / "engine" / "builder" / "elements" / "line.py", "elem")
    if k.startswith("arrow")
)


def test_the_key_sets_were_found_at_all():
    # A rename that breaks the extraction must fail here, not pass silently.
    assert {"type", "fillToRect", "angle", "scaled"} <= set(GRADIENT_KEYS)
    assert {"arrowStart", "arrowEnd", "arrowStartWidth", "arrowEndLength"} <= set(ARROW_KEYS)


@pytest.mark.parametrize("key", GRADIENT_KEYS)
def test_every_gradient_key_is_documented(key):
    assert key in ELEMENTS_GUIDE, (
        f"formatting.py honours gradient.{key}, and slide-json-elements.md "
        f"never names it — a composer cannot reach it"
    )


@pytest.mark.parametrize("key", ARROW_KEYS)
def test_every_arrowhead_key_is_documented(key):
    assert key in ELEMENTS_GUIDE, (
        f"line.py honours {key}, and slide-json-elements.md never names it"
    )
