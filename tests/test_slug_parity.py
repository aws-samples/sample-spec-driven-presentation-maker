# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Parity between the Python slug / artifact-name grammars and their Web UI copies.

The Local API routes and the review schema run in Node, so they keep their own regexes.
They are read as text, as in tests/test_review_contract.py: a grammar changed on one side
fails CI until the other matches. Each file names its copies; a slug character class
anywhere else in the file is an unpinned copy and fails too.
"""

import re
from pathlib import Path

import pytest

from sdpm.engine.schema.slugs import OUTLINE_ENTRY_RE, OUTLINE_SLUG, SLUG
from shared.artifact_keys import COMPOSE_NAME_RE

_ROOT = Path(__file__).resolve().parent.parent
_WEB = _ROOT / "web-ui" / "src"
_CONST_RE = re.compile(r"^(?:export )?const (\w+) = /(.+)/([a-z]*)$", re.MULTILINE)

# file → {constant: the Python pattern it copies}
_PINNED = {
    "lib/review/schema.ts": {
        "SLUG_RE": f"^{SLUG}$",
    },
    "app/api/decks/[id]/route.ts": {
        "HTML_SLUG_RE": f"^{SLUG}$",
        "OUTLINE_ENTRY_RE": OUTLINE_ENTRY_RE.pattern,
        "COMPOSE_FILE_RE": f"^{COMPOSE_NAME_RE.pattern}$",
        "PREVIEW_PNG_RE": rf"^({OUTLINE_SLUG})\.png$",
    },
    "app/api/decks/route.ts": {
        "HTML_PREVIEW_FILE_RE": rf"^{SLUG}\.html$",
        "OUTLINE_ENTRY_RE": OUTLINE_ENTRY_RE.pattern,
    },
}


def _ts_regexes(text: str) -> dict[str, tuple[str, str]]:
    return {m.group(1): (m.group(2), m.group(3)) for m in _CONST_RE.finditer(text)}


@pytest.mark.parametrize("rel", sorted(_PINNED))
def test_ts_regexes_match_python(rel):
    found = _ts_regexes((_WEB / rel).read_text(encoding="utf-8"))
    for name, expected in _PINNED[rel].items():
        assert name in found, f"{name} not found in {rel}"
        assert found[name] == (expected, ""), f"{rel} {name}"


@pytest.mark.parametrize("rel", sorted(_PINNED))
def test_no_unpinned_slug_regex(rel):
    pinned = _PINNED[rel]
    for line in (_WEB / rel).read_text(encoding="utf-8").splitlines():
        if "[a-z0-9" in line:
            m = _CONST_RE.match(line)
            assert m and m.group(1) in pinned, f"unpinned slug regex in {rel}: {line.strip()}"
