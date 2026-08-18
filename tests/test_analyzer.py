# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for sdpm.engine.analyzer — pin existing behavior and verify aspect-ratio fix."""

from pathlib import Path

from sdpm.engine.analyzer import analyze_template, get_layout_placeholders


# ── Phase 0: Pin 16:9 behavior (must pass BEFORE and AFTER the fix) ──────────


class TestAnalyzerPin16x9:
    """Pin 16:9 template behavior to prove the fix does not regress."""

    def test_slide_size_16x9(self, template_16x9: Path):
        """slide_size must be 1920×1080 for 16:9."""
        result = analyze_template(template_16x9)
        assert result["slide_size"] == {"width": 1920, "height": 1080, "ptPerPx": 0.5}

    def test_layouts_present(self, template_16x9: Path):
        """analyze_template returns at least one layout."""
        result = analyze_template(template_16x9)
        assert len(result["layouts"]) > 0
        names = [layout["name"] for layout in result["layouts"]]
        # blank-dark has Title Slide and Title Only (from slides)
        assert "Title Slide" in names

    def test_theme_colors_present(self, template_16x9: Path):
        """Theme colors dict is non-empty."""
        result = analyze_template(template_16x9)
        assert "text" in result["theme_colors"]
        assert "background" in result["theme_colors"]

    def test_fonts_present(self, template_16x9: Path):
        """Fonts are extracted."""
        result = analyze_template(template_16x9)
        assert "halfwidth" in result["fonts"]
        assert "fullwidth" in result["fonts"]

    def test_placeholder_px_values_16x9(self, template_16x9: Path):
        """Pin placeholder px coordinates for Title Slide layout at 16:9.

        EMU_PER_PX = 12192000 / 1920 = 6350.0
        Title placeholder (idx=0): left=682625 → int(682625/6350) = 107
        """
        ph = get_layout_placeholders(template_16x9, "Title Slide")
        assert ph is not None
        assert len(ph["placeholders"]) >= 2

        title = ph["placeholders"][0]
        assert title["idx"] == 0
        assert title["x"] == 107
        assert title["y"] == 335
        assert title["width"] == 1557
        assert title["height"] == 231

        subtitle = ph["placeholders"][1]
        assert subtitle["idx"] == 1
        assert subtitle["x"] == 108
        assert subtitle["y"] == 612
        assert subtitle["width"] == 1537
        assert subtitle["height"] == 122

    def test_get_layout_placeholders_not_found(self, template_16x9: Path):
        """Non-existent layout returns None."""
        result = get_layout_placeholders(template_16x9, "NonExistentLayout")
        assert result is None

    def test_blank_layout_empty_placeholders(self, template_16x9: Path):
        """Blank layout has no content placeholders (types 13,15,16 are filtered)."""
        ph = get_layout_placeholders(template_16x9, "Blank")
        assert ph is not None
        assert ph["placeholders"] == []


# ── Phase 1-2: Verify 4:3 uses correct D1-normalized values ─────────────────


class TestAnalyzer4x3:
    """Verify analyzer produces correct D1-normalized values for 4:3."""

    def test_slide_size_4x3(self, template_4x3: Path):
        """4:3 slide_size must be 1920×1440 (width-1920 invariant).

        9144000 / 1920 = 4762.5 emu_per_px
        6858000 / 4762.5 = 1440 height
        ptPerPx = (9144000 / 12700) / 1920 = 0.375
        """
        result = analyze_template(template_4x3)
        assert result["slide_size"] == {"width": 1920, "height": 1440, "ptPerPx": 0.375}

    def test_placeholder_px_values_4x3(self, template_4x3: Path):
        """4:3 placeholders use emu_per_px = 4762.5 (not 6350).

        Title placeholder left=682625 EMU → int(682625/4762.5) = 143
        The coordinates are LARGER because the pixel grid is finer.
        """
        ph = get_layout_placeholders(template_4x3, "Title Slide")
        assert ph is not None
        assert len(ph["placeholders"]) >= 2

        title = ph["placeholders"][0]
        assert title["idx"] == 0
        assert title["x"] == 143
        assert title["y"] == 447
        assert title["width"] == 2076
        assert title["height"] == 308

    def test_slide_size_consistency_with_engine(self, template_4x3: Path):
        """analyzer slide_size must match engine.slide_size_px()."""
        from sdpm.engine import slide_size_px

        result = analyze_template(template_4x3)
        # 4:3 EMU dimensions
        expected = slide_size_px(9144000, 6858000)
        assert result["slide_size"]["width"] == expected[0]
        assert result["slide_size"]["height"] == expected[1]

    def test_slide_size_consistency_16x9(self, template_16x9: Path):
        """analyzer slide_size must match engine.slide_size_px() for 16:9 too."""
        from sdpm.engine import slide_size_px

        result = analyze_template(template_16x9)
        expected = slide_size_px(12192000, 6858000)
        assert result["slide_size"]["width"] == expected[0]
        assert result["slide_size"]["height"] == expected[1]
