# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for icon label width estimation in sdpm.engine.builder.elements.image."""

from __future__ import annotations

from sdpm.engine.builder.elements.image import _label_line_em, _plain_label_text


def test_plain_text_strips_style_markup():
    assert _plain_label_text("{{bold:Cognito}}") == "Cognito"


def test_latin_label_width():
    # 7 Latin glyphs at 0.85em each.
    assert _label_line_em("Cognito") == 7 * 0.85


def test_cjk_label_wider_than_same_length_latin():
    # Same glyph count, but CJK fullwidth glyphs are square (~1.05em),
    # so the Japanese label must measure wider than the Latin one.
    assert _label_line_em("認証基盤サービス") > _label_line_em("Cognito!")


def test_mixed_label_width():
    # parse_styled_text inserts a space at the CJK/Latin boundary, so
    # "監視DNA" renders as "監視 DNA": 2 CJK (1.05 each) + 4 Latin-width
    # glyphs (0.85 each, including the inserted space).
    assert _label_line_em("監視DNA") == 2 * 1.05 + 4 * 0.85


def test_empty_label():
    assert _label_line_em("") == 0
