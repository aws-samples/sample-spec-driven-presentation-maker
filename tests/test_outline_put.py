# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Validation for outline.md written from the Web UI (api PUT /decks/{id}/specs/outline)."""

from shared.schema import OUTLINE_MAX_BYTES, validate_outline_content


def test_accepts_ordinary_outline():
    md = "# Deck\n\n## 章\n\n- [intro] 主張\n  - body: 本文\n"
    assert validate_outline_content(md) is None


def test_accepts_empty_string():
    assert validate_outline_content("") is None


def test_rejects_non_string():
    assert validate_outline_content(None) == "content must be a string"
    assert validate_outline_content(["- [a] b"]) == "content must be a string"


def test_rejects_nul_bytes():
    assert "NUL" in validate_outline_content("- [a] b\x00")


def test_rejects_oversize():
    assert validate_outline_content("x" * (OUTLINE_MAX_BYTES + 1)) is not None
    assert validate_outline_content("あ" * (OUTLINE_MAX_BYTES // 3 + 1)) is not None
    assert validate_outline_content("x" * OUTLINE_MAX_BYTES) is None
