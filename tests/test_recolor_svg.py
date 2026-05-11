# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for sdpm.utils.svg._recolor_svg.

Focus: detection of CSS named colors so that multi-color SVGs mixing hex with
named colors (e.g. AWS DevOps Agent icon: `#E7157B` background + `white` glyph)
are not silently flattened to a single color by the recolor pass.
"""

from sdpm.utils.svg import _recolor_svg


class TestRecolorSVGSingleColor:
    def test_single_hex_recolored(self):
        svg = b'<svg><path fill="#000000" d="M0 0h10v10H0z"/></svg>'
        out = _recolor_svg(svg, "#FF0000")
        assert b'fill="#FF0000"' in out
        assert b"#000000" not in out

    def test_single_named_color_recolored(self):
        svg = b'<svg><path fill="black" d="M0 0h10v10H0z"/></svg>'
        out = _recolor_svg(svg, "#FF0000")
        assert b'fill="#FF0000"' in out
        assert b"black" not in out

    def test_target_matches_original_hex_returns_none(self):
        svg = b'<svg><path fill="#FF0000"/></svg>'
        assert _recolor_svg(svg, "#ff0000") is None

    def test_no_explicit_fill_adds_root_fill(self):
        svg = b'<svg viewBox="0 0 10 10"><path d="M0 0h10v10H0z"/></svg>'
        out = _recolor_svg(svg, "#123456")
        assert b'<svg fill="#123456"' in out


class TestRecolorSVGMultiColor:
    def test_two_hex_colors_skipped(self):
        svg = (
            b'<svg>'
            b'<rect fill="#E7157B"/>'
            b'<path fill="#FFFFFF"/>'
            b'</svg>'
        )
        assert _recolor_svg(svg, "#000000") is None

    def test_hex_and_named_color_skipped(self):
        # Reproducer for AWS DevOps Agent icon: hex background + named-color glyph.
        # Without named-color detection, unique-color count drops to 1 and the SVG
        # is mis-classified as single-color, then both colors collapse to the target.
        svg = (
            b'<svg>'
            b'<rect fill="#E7157B"/>'
            b'<path fill="white"/>'
            b'</svg>'
        )
        assert _recolor_svg(svg, "#000000") is None

    def test_two_named_colors_skipped(self):
        svg = (
            b'<svg>'
            b'<rect fill="black"/>'
            b'<path fill="white"/>'
            b'</svg>'
        )
        assert _recolor_svg(svg, "#000000") is None


class TestRecolorSVGPaintServerKeywords:
    """Non-color keywords (none, currentColor, url(...), inherit) must not be
    counted as colors — otherwise a single-color SVG with `fill="none"` on a
    container would be mis-classified as multi-color and skipped.
    """

    def test_fill_none_does_not_count_as_color(self):
        svg = b'<svg><g fill="none"><path fill="#000000"/></g></svg>'
        out = _recolor_svg(svg, "#FF0000")
        assert out is not None
        assert b'fill="#FF0000"' in out
        # `none` must remain unchanged
        assert b'fill="none"' in out

    def test_current_color_does_not_count(self):
        svg = b'<svg><g fill="currentColor"><path fill="#000000"/></g></svg>'
        out = _recolor_svg(svg, "#FF0000")
        assert out is not None
        assert b'fill="#FF0000"' in out
        assert b'fill="currentColor"' in out

    def test_url_reference_does_not_count(self):
        svg = b'<svg><path fill="url(#grad)" stroke="#000000"/></svg>'
        out = _recolor_svg(svg, "#FF0000")
        assert out is not None
        assert b'stroke="#FF0000"' in out
        assert b'fill="url(#grad)"' in out


class TestRecolorSVGNamedColorBoundary:
    """Word-boundary anchoring: replacing `white` must not match inside
    `whitesmoke` and corrupt a color value.
    """

    def test_white_does_not_match_inside_whitesmoke(self):
        # Two distinct named colors → multi-color → skipped (return None).
        # The point of this test is to lock the behavior; if boundary anchoring
        # were missing we'd risk mis-detection in single-color paths.
        svg = b'<svg><rect fill="white"/><path fill="whitesmoke"/></svg>'
        assert _recolor_svg(svg, "#000000") is None
