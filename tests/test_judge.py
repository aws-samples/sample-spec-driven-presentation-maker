# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for SVG-based layout judgments (sdpm.engine.preview.judge).

Fixtures are minimal SVG documents mirroring real LibreOffice 26.x export
structure (Slide/Page groups, TextPosition tspans with textLength,
BoundingBox rects, shadow groups, fill-opacity). Calibration against the
official reference decks (components.pptx / patterns.pptx) is a local-only
step recorded in the spec notes; these tests pin the judgment logic.
"""

import textwrap

from sdpm.engine.preview.judge import JudgeIssue, contrast_ratio, judge_from_svg
from sdpm.engine.preview.measure import format_measure_report


def _svg_doc(slide_bodies: list[str], bg_fill: str = "rgb(10,22,40)") -> str:
    """Wrap per-slide Page content in a LibreOffice-like SVG document."""
    slides = '<g class="Slide"><g class="Page"></g></g>'  # dummy slide 0
    for body in slide_bodies:
        slides += f'<g class="Slide"><g class="Page">{body}</g></g>'
    return textwrap.dedent(f"""\
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 25400 19050">
         <defs class="SlideBackground">
          <g class="Background">
           <rect fill="{bg_fill}" x="0" y="0" width="25400" height="19050"/>
          </g>
         </defs>
        {slides}
        </svg>""")


def _text(preview: str, x: int, y: int, length: int, fs: int = 800,
          fill: str = "rgb(255,255,255)", lines: list | None = None) -> str:
    """A CustomShape group holding one text element (textbox-like)."""
    if lines is None:
        lines = [(x, y, length, preview)]
    spans = "".join(
        f'<tspan class="TextPosition" x="{lx}" y="{ly}">'
        f'<tspan font-size="{fs}px" textLength="{ll}" fill="{fill}">{lt}</tspan>'
        f"</tspan>"
        for lx, ly, ll, lt in lines
    )
    return (
        '<g class="com.sun.star.drawing.CustomShape"><g>'
        f'<rect class="BoundingBox" fill="none" x="{x}" y="{y - fs}" width="{length}" height="{fs * 2}"/>'
        f'<text class="SVGTextShape"><tspan class="TextParagraph">{spans}</tspan></text>'
        "</g></g>"
    )


def _shape_with_text(preview: str, fill: str, fx: int, fy: int, fw: int, fh: int,
                     tx: int, ty: int, tlen: int, fs: int = 800,
                     tfill: str = "rgb(255,255,255)", extra_path_attrs: str = "",
                     shadow: bool = False) -> str:
    """A CustomShape group with a fill path and a text element."""
    shadow_g = (
        '<g style="opacity: 0.349019607843137">'
        f'<rect x="{fx}" y="{fy}" width="{fw}" height="{fh}" fill="rgb(0,0,0)"/>'
        "</g>"
        if shadow else ""
    )
    d = f"M {fx},{fy} L {fx + fw},{fy} {fx + fw},{fy + fh} {fx},{fy + fh} Z"
    return (
        '<g class="com.sun.star.drawing.CustomShape"><g>'
        f'<rect class="BoundingBox" fill="none" x="{fx}" y="{fy}" width="{fw}" height="{fh}"/>'
        f"{shadow_g}"
        f'<path fill="{fill}" stroke="none" {extra_path_attrs} d="{d}"/>'
        f'<text class="SVGTextShape"><tspan class="TextParagraph">'
        f'<tspan class="TextPosition" x="{tx}" y="{ty}">'
        f'<tspan font-size="{fs}px" textLength="{tlen}" fill="{tfill}">{preview}</tspan>'
        f"</tspan></tspan></text>"
        "</g></g>"
    )


def _judge(svg_text: str, tmp_path):
    p = tmp_path / "t.svg"
    p.write_text(svg_text, encoding="utf-8")
    return judge_from_svg(p)


class TestCollision:
    def test_overlapping_texts_flagged(self, tmp_path):
        body = (
            _text("First long paragraph", 1000, 3000, 8000)
            + _text("Second colliding text", 1000, 3100, 8000)
        )
        res = _judge(_svg_doc([body]), tmp_path)
        assert 1 in res
        assert any(i.kind == "collision" for i in res[1])

    def test_separated_texts_clean(self, tmp_path):
        body = (
            _text("Title text", 1000, 3000, 8000)
            + _text("Body far below", 1000, 8000, 8000)
        )
        assert _judge(_svg_doc([body]), tmp_path) == {}

    def test_title_subtitle_adjacent_lines_clean(self, tmp_path):
        # Standard tight line spacing (subtitle baseline ~1.2x title fs below):
        # the loose em-box would intersect; tight cap-height bbox must not flag
        body = (
            _text("Title", 1000, 3000, 4000, fs=1000)
            + _text("Subtitle", 1000, 4050, 3000, fs=500)
        )
        assert _judge(_svg_doc([body]), tmp_path) == {}

    def test_duplicate_double_draw_clean(self, tmp_path):
        # Highlight pattern: identical string drawn twice at the same position
        body = (
            _text("Phase 2", 5000, 5000, 3000)
            + _text("Phase 2", 5000, 5000, 3000)
        )
        assert _judge(_svg_doc([body]), tmp_path) == {}

    def test_single_glyph_decoration_clean(self, tmp_path):
        # Quote glyph intentionally overlaying the testimonial text
        body = (
            _text("❝", 1000, 3000, 500)
            + _text("Customer testimonial", 1100, 3050, 8000)
        )
        assert _judge(_svg_doc([body]), tmp_path) == {}


class TestOverflow:
    def test_text_wider_than_shape_flagged(self, tmp_path):
        body = _shape_with_text(
            "Way too long", "rgb(68,136,204)",
            fx=5000, fy=5000, fw=2000, fh=1500,
            tx=4500, ty=6000, tlen=4000,
        )
        res = _judge(_svg_doc([body]), tmp_path)
        assert 1 in res
        assert any(i.kind == "overflow" for i in res[1])

    def test_text_inside_shape_clean(self, tmp_path):
        body = _shape_with_text(
            "Fits fine", "rgb(68,136,204)",
            fx=5000, fy=5000, fw=8000, fh=3000,
            tx=6000, ty=6800, tlen=4000,
        )
        assert _judge(_svg_doc([body]), tmp_path) == {}

    def test_plain_textbox_not_judged(self, tmp_path):
        # No fill path → nothing to overflow (textbox height is agent's business)
        body = _text("Standalone textbox with very long content", 1000, 3000, 20000)
        assert _judge(_svg_doc([body]), tmp_path) == {}


class TestContrast:
    def test_dark_on_dark_flagged(self, tmp_path):
        body = _shape_with_text(
            "Dark on dark", "rgb(17,17,17)",
            fx=2000, fy=2000, fw=15000, fh=6000,
            tx=3000, ty=5000, tlen=8000, tfill="rgb(34,34,34)",
        )
        res = _judge(_svg_doc([body]), tmp_path)
        assert 1 in res
        assert any(i.kind == "contrast" for i in res[1])

    def test_white_on_dark_clean(self, tmp_path):
        body = _shape_with_text(
            "Readable", "rgb(17,17,17)",
            fx=2000, fy=2000, fw=15000, fh=6000,
            tx=3000, ty=5000, tlen=8000, tfill="rgb(255,255,255)",
        )
        assert _judge(_svg_doc([body]), tmp_path) == {}

    def test_translucent_fill_composited(self, tmp_path):
        # white fill at 0.078 opacity over dark bg renders dark — white text
        # on it is readable, must NOT flag (components.pptx card pattern)
        body = _shape_with_text(
            "Card title", "rgb(255,255,255)",
            fx=2000, fy=2000, fw=15000, fh=6000,
            tx=3000, ty=5000, tlen=8000, tfill="rgb(255,255,255)",
            extra_path_attrs='fill-opacity="0.078"',
        )
        assert _judge(_svg_doc([body]), tmp_path) == {}

    def test_gradient_fill_skipped(self, tmp_path):
        d = "M 2000,2000 L 17000,2000 17000,8000 2000,8000 Z"
        body = (
            '<g class="com.sun.star.drawing.CustomShape"><g>'
            f'<path style="fill:url(#gradient1)" d="{d}"/>'
            '<text class="SVGTextShape"><tspan class="TextParagraph">'
            '<tspan class="TextPosition" x="3000" y="5000">'
            '<tspan font-size="800px" textLength="8000" fill="rgb(30,30,30)">On gradient</tspan>'
            "</tspan></tspan></text>"
            "</g></g>"
        )
        assert _judge(_svg_doc([body]), tmp_path) == {}

    def test_text_against_slide_background(self, tmp_path):
        # No underlying fill → judged against slide background (near-black)
        body = _text("Invisible", 1000, 3000, 8000, fill="rgb(12,24,42)")
        res = _judge(_svg_doc([body]), tmp_path)
        assert 1 in res
        assert res[1][0].kind == "contrast"

    def test_shadow_group_not_treated_as_fill(self, tmp_path):
        # The shadow rect is white-ish but sits in an opacity group; only the
        # real fill (dark) counts, so dark text on it must flag via real fill
        body = _shape_with_text(
            "Shadowed", "rgb(17,17,17)",
            fx=2000, fy=2000, fw=15000, fh=6000,
            tx=3000, ty=5000, tlen=8000, tfill="rgb(34,34,34)",
            shadow=True,
        )
        res = _judge(_svg_doc([body]), tmp_path)
        assert 1 in res
        assert any(i.kind == "contrast" for i in res[1])


class TestSlideSelection:
    def test_slide_indices_filter(self, tmp_path):
        bad = (
            _text("First long paragraph", 1000, 3000, 8000)
            + _text("Second colliding text", 1000, 3100, 8000)
        )
        clean = _text("Fine", 1000, 3000, 3000)
        svg = _svg_doc([bad, clean, bad])
        p = tmp_path / "t.svg"
        p.write_text(svg, encoding="utf-8")
        res = judge_from_svg(p, slide_indices=[2, 3])
        assert 1 not in res
        assert 3 in res


class TestContrastRatio:
    def test_black_white_is_21(self):
        assert abs(contrast_ratio((0, 0, 0), (255, 255, 255)) - 21.0) < 0.1

    def test_symmetric(self):
        a, b = (34, 34, 34), (17, 17, 17)
        assert contrast_ratio(a, b) == contrast_ratio(b, a)


class TestReportIntegration:
    def test_no_judgments_output_unchanged(self):
        base = format_measure_report({}, page_to_slug={})
        with_none = format_measure_report({}, page_to_slug={}, judgments=None)
        with_empty = format_measure_report({}, page_to_slug={}, judgments={})
        assert base == with_none == with_empty

    def test_judgments_appended_with_slug_labels(self):
        judgments = {2: [JudgeIssue("collision", 'text "A" overlaps "B"')]}
        report = format_measure_report(
            {}, page_to_slug={2: "feature-a"}, judgments=judgments
        )
        assert "Layout issues" in report
        assert "Slide feature-a [collision]" in report
