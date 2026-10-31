# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Parity between the change request contract in Python (shared/review.py) and its consumers.

The Web UI mirror (web-ui/src/lib/review/schema.ts) is parsed as text, as in
tests/test_agent_errors.py, so a limit changed on one side fails CI until the other matches.
The submission cases themselves are shared through tests/fixtures/review_submissions.json.
"""

import re
from pathlib import Path

import pytest

from shared import review

_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA_TS = (_ROOT / "web-ui" / "src" / "lib" / "review" / "schema.ts").read_text(encoding="utf-8")
_MARKER_TS = (_ROOT / "web-ui" / "src" / "lib" / "review" / "marker.ts").read_text(encoding="utf-8")


def _ts_constant(name: str) -> int:
    match = re.search(rf"^export const {name} = ([0-9 *]+)$", _SCHEMA_TS, re.MULTILINE)
    assert match, f"{name} not found in schema.ts"
    value = 1
    for factor in match.group(1).split("*"):
        value *= int(factor.strip())
    return value


@pytest.mark.parametrize("name", ["MAX_COMMENTS", "MAX_TEXT_CHARS", "MAX_NOTE_CHARS", "MAX_BODY_BYTES"])
def test_limits_match(name):
    assert _ts_constant(name) == getattr(review, name)


def test_marker_prefix():
    assert "[review:" in _MARKER_TS


def test_role_documents_do_not_mention_review_files():
    """The comment tool is a Web UI feature: its instructions travel in the message and the file."""
    for doc in (_ROOT / "sdpm" / "references" / "workflows").glob("*.md"):
        text = doc.read_text(encoding="utf-8")
        assert "[review:" not in text and "reviews/" not in text, doc.name

