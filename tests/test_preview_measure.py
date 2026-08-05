# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for preview/measure.py — viewBox scaling (Phase 1-4)."""

from pathlib import Path

import pytest

from sdpm.engine.preview.measure import measure_from_svg


def _make_svg(vb_w: float, vb_h: float, rect_x: float, rect_y: float, rect_w: float, rect_h: float) -> str:
    """Create a minimal SVG with one text shape for measurement.

    viewBox is ``0 0 {vb_w} {vb_h}`` — LibreOffice uses EMU-scale values here.
    """
    return f"""\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w} {vb_h}">
  <g class="Slide">
    <g class="Page"><!-- dummy slide 0 --></g>
  </g>
  <g class="Slide">
    <g class="Page">
      <g class="TextBox">
        <rect class="BoundingBox" x="{rect_x}" y="{rect_y}" width="{rect_w}" height="{rect_h}" />
        <text class="SVGTextShape">
          <tspan class="TextPosition">Hello</tspan>
        </text>
      </g>
    </g>
  </g>
</svg>"""


class TestViewBoxScaling:
    """Ensure measure uses width-based equal-aspect scale (not separate x/y)."""

    def test_16x9_scale_unchanged(self, tmp_path: Path):
        """16:9 viewBox: behaviour is identical to before the fix."""
        # 16:9 EMU viewBox: 25400 x 14287.5 (ratio preserving at 6350 emu/px)
        vb_w, vb_h = 25400.0, 14287.5
        # Shape at viewBox coords (2540, 1428.75) with size (5080, 2857.5)
        svg = _make_svg(vb_w, vb_h, 2540, 1428.75, 5080, 2857.5)
        svg_path = tmp_path / "test.svg"
        svg_path.write_text(svg)

        results = measure_from_svg(svg_path)
        assert 1 in results
        bbox = results[1][0]
        # scale = 1920 / 25400 ≈ 0.07559
        assert bbox.x_px == pytest.approx(192.0, abs=0.1)
        assert bbox.y_px == pytest.approx(108.0, abs=0.1)
        assert bbox.w_px == pytest.approx(384.0, abs=0.1)
        assert bbox.h_px == pytest.approx(216.0, abs=0.1)

    def test_4x3_not_compressed(self, tmp_path: Path):
        """4:3 viewBox: y/h must NOT be 0.75x compressed (the bug this fixes)."""
        # 4:3 EMU viewBox: 19050 x 14287.5 (9144000/480 x 6858000/480)
        vb_w, vb_h = 19050.0, 14287.5
        # Shape at viewBox center-ish: (9525, 7143.75) = half of each dimension
        svg = _make_svg(vb_w, vb_h, 9525.0, 7143.75, 1905.0, 1428.75)
        svg_path = tmp_path / "test.svg"
        svg_path.write_text(svg)

        results = measure_from_svg(svg_path)
        assert 1 in results
        bbox = results[1][0]
        # scale = 1920 / 19050 ≈ 0.10079
        # x_px = 9525 * 0.10079 = 960.0
        # y_px = 7143.75 * 0.10079 = 720.0 (NOT 540.0 which old code would give)
        # w_px = 1905 * 0.10079 = 192.0
        # h_px = 1428.75 * 0.10079 = 144.0 (NOT 108.0 which old code would give)
        assert bbox.x_px == pytest.approx(960.0, abs=0.1)
        assert bbox.y_px == pytest.approx(720.0, abs=0.1)
        assert bbox.w_px == pytest.approx(192.0, abs=0.1)
        assert bbox.h_px == pytest.approx(144.0, abs=0.1)

    def test_4x3_y_not_compressed_explicit(self, tmp_path: Path):
        """Explicit check: with old code (scale_y=1080/vb_h) the y would be 0.75x."""
        # 4:3: viewBox 19050 x 14287.5
        # A shape at y=14287.5 (bottom edge) should map to y=1440 (4:3 canvas height)
        # Old code would give: 14287.5 * (1080 / 14287.5) = 1080 (wrong, cuts 25%)
        # New code gives: 14287.5 * (1920 / 19050) = 1440 (correct)
        vb_w, vb_h = 19050.0, 14287.5
        svg = _make_svg(vb_w, vb_h, 0, 14287.5, 19050.0, 0)
        svg_path = tmp_path / "test.svg"
        svg_path.write_text(svg)

        results = measure_from_svg(svg_path)
        assert 1 in results
        bbox = results[1][0]
        # y_px should be 1440 (full 4:3 height), not 1080
        assert bbox.y_px == pytest.approx(1440.0, abs=0.1)
