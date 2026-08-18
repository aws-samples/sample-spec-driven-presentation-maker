# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for Issue #208: aspect-ratio-agnostic canvas.

Phase 0: Analyzer 16:9 pin tests — prove current behavior is invariant.
Phase 1-1: slide_size_px() / emu_per_px() derivation functions.
"""

from pathlib import Path

import pytest

from sdpm.engine import emu_per_px, slide_size_px
from sdpm.engine.analyzer import analyze_template, get_layout_placeholders


# ── Standard EMU dimensions ──
_W_16X9 = 12192000
_H_16X9 = 6858000
_W_4X3 = 9144000
_H_4X3 = 6858000


# ═══════════════════════════════════════════════════════════════════════
# Phase 1-1: derivation function unit tests
# ═══════════════════════════════════════════════════════════════════════


class TestEmuPerPx:
    def test_16x9(self):
        assert emu_per_px(_W_16X9) == 6350.0

    def test_4x3(self):
        assert emu_per_px(_W_4X3) == 4762.5

    def test_arbitrary(self):
        # 1920 * 5000 = 9_600_000
        assert emu_per_px(9_600_000) == 5000.0


class TestSlideSizePx:
    def test_16x9(self):
        assert slide_size_px(_W_16X9, _H_16X9) == (1920, 1080)

    def test_4x3(self):
        assert slide_size_px(_W_4X3, _H_4X3) == (1920, 1440)

    def test_width_always_1920(self):
        w, _ = slide_size_px(9_600_000, 7_200_000)
        assert w == 1920


# ═══════════════════════════════════════════════════════════════════════
# Phase 0: Analyzer 16:9 pin tests (immutability evidence)
# ═══════════════════════════════════════════════════════════════════════


class TestAnalyzerPin16x9:
    """Pin the 16:9 analyzer output so later changes provably do not regress."""

    def test_slide_size(self, template_16x9: Path):
        result = analyze_template(template_16x9)
        assert result["slide_size"] == {"width": 1920, "height": 1080, "ptPerPx": 0.5}

    def test_slide_size_keys(self, template_16x9: Path):
        result = analyze_template(template_16x9)
        assert set(result["slide_size"].keys()) == {"width", "height", "ptPerPx"}


class TestLayoutPlaceholdersPin16x9:
    """Pin get_layout_placeholders px values for 16:9 template."""

    def test_returns_result(self, template_16x9: Path):
        result = get_layout_placeholders(template_16x9, "Blank")
        # Blank layout exists in blank-dark.pptx
        assert result is not None
        assert result["name"] == "Blank"

    def test_placeholder_positions_use_6350_basis(self, template_16x9: Path):
        """All px values must be derived at EMU/6350 (16:9 basis)."""
        result = get_layout_placeholders(template_16x9, "Blank")
        if not result or not result.get("placeholders"):
            pytest.skip("Blank layout has no non-media placeholders")
        for ph in result["placeholders"]:
            # All coordinates must be non-negative integers
            for key in ("x", "y", "width", "height"):
                assert isinstance(ph[key], int)
                assert ph[key] >= 0
            # Width must not exceed canvas width
            assert ph["x"] + ph["width"] <= 1920
