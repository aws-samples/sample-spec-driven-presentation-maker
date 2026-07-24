# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Converter robustness tests from real-world PPTX corpus findings.

Each test reproduces a bug found by running pptx_to_json over a corpus of
~140 real presentations (Canva/Google Slides exports, business templates):

1. Chart per-point colors used int dict keys → minimal-mode strip crashed
   with AttributeError on every deck containing such charts.
2. Slides with a duplicate placeholder idx (Google Slides exports emit two
   TITLE/idx=0 shapes on one slide) silently dropped the second shape.
3. Multi-paragraph title placeholders lost every paragraph after the first.
"""

import copy
import json
from pathlib import Path

from pptx import Presentation
from pptx.util import Emu

from sdpm.converter.pipeline import pptx_to_json
from sdpm.schema.minimal import _strip_internal_keys


def _template() -> Path:
    return Path(__file__).parent.parent / "skill" / "templates" / "blank-dark.pptx"


def _title_slide(prs):
    """Add a slide using a layout that has a title placeholder."""
    for layout in prs.slide_layouts:
        try:
            slide = prs.slides.add_slide(layout)
        except Exception:
            continue
        if slide.shapes.title is not None:
            return slide
        # remove unusable slide? keep simple: continue scanning
    raise AssertionError("no layout with title placeholder in template")


class TestMinimalStripNonStrKeys:
    def test_int_keys_do_not_crash(self):
        slide = {
            "layout": "Blank",
            "elements": [{
                "type": "chart",
                "chartType": "pie",
                "series": [{"name": "s", "values": [1, 2], "pointColors": {0: "#FF0000", 1: "#00FF00"}}],
                "_internal": "dropme",
            }],
        }
        out = _strip_internal_keys(slide)
        el = out["elements"][0]
        assert "_internal" not in el
        # int keys survive the strip untouched (previously: AttributeError)
        assert el["series"][0]["pointColors"] == {0: "#FF0000", 1: "#00FF00"}


class TestChartPointColorKeys:
    def test_extracted_point_colors_use_str_keys(self, tmp_path):
        # Build a pie chart with explicit per-point colors via raw dPt XML
        from pptx.chart.data import CategoryChartData
        from pptx.enum.chart import XL_CHART_TYPE
        from lxml import etree

        prs = Presentation(str(_template()))
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        data = CategoryChartData()
        data.categories = ["a", "b"]
        data.add_series("s1", (1.0, 2.0))
        gf = slide.shapes.add_chart(
            XL_CHART_TYPE.PIE, Emu(0), Emu(0), Emu(3000000), Emu(3000000), data
        )
        ser = gf.chart._chartSpace.findall(
            ".//{http://schemas.openxmlformats.org/drawingml/2006/chart}ser")[0]
        ns_c = "http://schemas.openxmlformats.org/drawingml/2006/chart"
        ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
        for i, color in enumerate(["FF0000", "00FF00"]):
            dpt = etree.SubElement(ser, f"{{{ns_c}}}dPt")
            idx = etree.SubElement(dpt, f"{{{ns_c}}}idx")
            idx.set("val", str(i))
            sppr = etree.SubElement(dpt, f"{{{ns_c}}}spPr")
            fill = etree.SubElement(sppr, f"{{{ns_a}}}solidFill")
            srgb = etree.SubElement(fill, f"{{{ns_a}}}srgbClr")
            srgb.set("val", color)
        pptx_path = tmp_path / "chart.pptx"
        prs.save(str(pptx_path))

        # minimal=True used to crash (int keys hit str.startswith in strip)
        result = pptx_to_json(pptx_path, tmp_path / "out", minimal=True)

        charts = [el for s in result["slides"] for el in s.get("elements", []) if el.get("type") == "chart"]
        assert charts, "chart element not extracted"
        pc = charts[0]["series"][0].get("pointColors")
        assert pc, "pointColors not extracted"
        assert all(isinstance(k, str) for k in pc), f"non-str keys: {pc}"


class TestDuplicatePlaceholderIdx:
    def test_second_same_idx_placeholder_is_rescued(self, tmp_path):
        prs = Presentation(str(_template()))
        slide = _title_slide(prs)
        title = slide.shapes.title
        title.text_frame.text = "first title"
        # Clone the title sp element (same placeholder idx) — as emitted by
        # Google Slides exports — and give it different text/position.
        clone = copy.deepcopy(title._element)
        title._element.addnext(clone)
        second = [sh for sh in slide.shapes if sh.shape_id != title.shape_id and sh.is_placeholder][0]
        second.text_frame.text = "second duplicate"
        second.left = Emu(1000000)
        second.top = Emu(2000000)
        pptx_path = tmp_path / "dup.pptx"
        prs.save(str(pptx_path))

        result = pptx_to_json(pptx_path, tmp_path / "out")
        dumped = json.dumps(result["slides"], ensure_ascii=False)
        assert "first title" in dumped
        assert "second duplicate" in dumped, "duplicate-idx placeholder text was dropped"


class TestMultiParagraphTitle:
    def test_title_keeps_all_paragraphs(self, tmp_path):
        prs = Presentation(str(_template()))
        slide = _title_slide(prs)
        tf = slide.shapes.title.text_frame
        tf.text = "line one"
        p2 = tf.add_paragraph()
        p2.text = "line two"
        pptx_path = tmp_path / "multi.pptx"
        prs.save(str(pptx_path))

        result = pptx_to_json(pptx_path, tmp_path / "out")
        dumped = json.dumps(result["slides"], ensure_ascii=False)
        assert "line one" in dumped
        assert "line two" in dumped, "second title paragraph was dropped"


class TestHiddenSlides:
    def test_hidden_flag_roundtrips(self, tmp_path):
        prs = Presentation(str(_template()))
        s1 = prs.slides.add_slide(prs.slide_layouts[0])
        s2 = prs.slides.add_slide(prs.slide_layouts[0])
        s2._element.set("show", "0")  # PowerPoint: Hide Slide
        del s1  # only to silence linters
        pptx_path = tmp_path / "hidden.pptx"
        prs.save(str(pptx_path))

        result = pptx_to_json(pptx_path, tmp_path / "out")
        # template may ship with its own slides — check the last two we added
        hidden_flags = [sl.get("hidden") for sl in result["slides"]]
        assert hidden_flags[-1] is True, f"hidden flag not extracted: {hidden_flags}"
        assert hidden_flags[-2] is not True

        # Builder restores the flag
        from sdpm.builder import PPTXBuilder
        builder = PPTXBuilder(str(_template()), fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"}, default_text_color="#FFFFFF")
        builder.add_slide({"layout": builder_first_layout(builder)})
        builder.add_slide({"layout": builder_first_layout(builder), "hidden": True})
        out = tmp_path / "rebuilt.pptx"
        builder.save(str(out))
        prs2 = Presentation(str(out))
        slides = list(prs2.slides)
        assert slides[0]._element.get("show") != "0"
        assert slides[1]._element.get("show") == "0", "hidden flag not rebuilt"


def builder_first_layout(builder) -> str:
    return next(iter(builder.layouts))


class TestDiffDetectsPlaceholderEdits:
    def test_title_placeholder_edit_is_reported(self, tmp_path):
        from sdpm.diff import diff_report

        base = {"slides": [{"layout": "L", "placeholders": {"0": "original title"}, "elements": []}]}
        edit = {"slides": [{"layout": "L", "placeholders": {"0": "edited title"}, "elements": []}]}
        bp = tmp_path / "base.json"
        ep = tmp_path / "edit.json"
        bp.write_text(json.dumps(base))
        ep.write_text(json.dumps(edit))

        rep = diff_report(bp, ep)
        assert rep["has_diff"], "placeholder edit went undetected"
        assert "placeholder[0]" in rep["report"]


class TestExplicitCropKeepsFrame:
    def test_cropped_image_fills_declared_box(self, tmp_path):
        """With an explicit crop, the frame must NOT shrink to the uncropped
        image's aspect ratio (PowerPoint srcRect semantics: crop fills frame)."""
        from PIL import Image as PILImage

        img = tmp_path / "tall.png"
        PILImage.new("RGB", (400, 800), "red").save(img)  # tall image

        deck = tmp_path / "deck"
        (deck / "slides").mkdir(parents=True)
        (deck / "specs").mkdir()
        (deck / "deck.json").write_text(json.dumps({
            "template": str(_template()),
            "fonts": {"fullwidth": "Meiryo", "halfwidth": "Arial"},
        }))
        (deck / "specs" / "outline.md").write_text("- [s1] test\n")
        (deck / "slides" / "s1.json").write_text(json.dumps({
            "layout": "Blank",
            "elements": [{
                "type": "image", "src": str(img),
                "x": 0, "y": 0, "width": 800, "height": 200,   # wide box
                "crop": {"top": 40.0, "bottom": 35.0},          # crops to wide region
            }],
        }))
        from sdpm.api import generate
        out = tmp_path / "out.pptx"
        generate(deck, output_path=out)

        prs = Presentation(str(out))
        pics = [sh for sh in prs.slides[0].shapes if sh.shape_type == 13]
        assert pics, "picture not built"
        pic = pics[0]
        # Frame keeps the declared 800px-wide box (compare as a fraction of
        # slide width to stay independent of the builder's px scale). The old
        # fit=contain behaviour shrank width to height*aspect = 100px (~5%).
        ratio = pic.width / prs.slide_width
        assert ratio > 0.35, f"frame shrank despite explicit crop: width ratio={ratio:.2f}"
