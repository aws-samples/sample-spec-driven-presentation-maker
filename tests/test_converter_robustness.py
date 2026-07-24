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


class TestTableThemeStyle:
    def test_table_style_id_resolves_to_style_dict(self, tmp_path):
        """Tables styled via tableStyleId (theme table styles) must emit a
        table-level style dict; otherwise the builder overwrites the look
        with its own default banding (white rows on dark decks)."""
        import zipfile

        from pptx.util import Inches

        prs = Presentation(str(_template()))
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        gf = slide.shapes.add_table(3, 2, Inches(1), Inches(1), Inches(6), Inches(2))
        tbl = gf.table
        for r in range(3):
            for c in range(2):
                tbl.cell(r, c).text = f"r{r}c{c}"
        # style id python-pptx stamped on the table
        ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
        sid = tbl._tbl.find(f"{{{ns_a}}}tblPr/{{{ns_a}}}tableStyleId").text
        raw_path = tmp_path / "raw.pptx"
        prs.save(str(raw_path))

        # Inject a tableStyles.xml defining that style (fill + border)
        table_styles = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:tblStyleLst xmlns:a="{ns_a}" def="{sid}">
 <a:tblStyle styleId="{sid}" styleName="Test Style">
  <a:wholeTbl>
   <a:tcStyle>
    <a:tcBdr><a:insideH><a:ln w="12700"><a:solidFill><a:srgbClr val="AD5CFF"/></a:solidFill></a:ln></a:insideH></a:tcBdr>
    <a:fill><a:solidFill><a:srgbClr val="112233"/></a:solidFill></a:fill>
   </a:tcStyle>
  </a:wholeTbl>
 </a:tblStyle>
</a:tblStyleLst>'''
        pptx_path = tmp_path / "styled_table.pptx"
        with zipfile.ZipFile(raw_path) as zin, zipfile.ZipFile(pptx_path, "w") as zout:
            for item in zin.namelist():
                if item == "ppt/tableStyles.xml":
                    zout.writestr(item, table_styles)
                else:
                    zout.writestr(item, zin.read(item))

        result = pptx_to_json(pptx_path, tmp_path / "out")
        tables = [el for s in result["slides"] for el in s.get("elements", []) if el.get("type") == "table"]
        assert tables, "table element not extracted"
        style = tables[0].get("style")
        assert style is not None, "tableStyleId did not resolve to a style dict"
        assert style["body"]["background"] == "#112233"
        assert style["border"]["color"] == "#AD5CFF"


class TestBackgroundFills:
    def test_gradient_background_becomes_fullslide_rect(self, tmp_path):
        """Slides with a gradient background must not silently lose it —
        the converter emits a full-slide gradient rectangle."""
        from lxml import etree

        prs = Presentation(str(_template()))
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
        ns_p = "http://schemas.openxmlformats.org/presentationml/2006/main"
        bg = etree.SubElement(slide._element.find(f"{{{ns_p}}}cSld"), f"{{{ns_p}}}bg")
        bgpr = etree.SubElement(bg, f"{{{ns_p}}}bgPr")
        grad = etree.fromstring(
            f'<a:gradFill xmlns:a="{ns_a}"><a:gsLst>'
            f'<a:gs pos="0"><a:srgbClr val="00FFCC"/></a:gs>'
            f'<a:gs pos="100000"><a:srgbClr val="0066FF"/></a:gs>'
            f'</a:gsLst><a:lin ang="0" scaled="1"/></a:gradFill>')
        bgpr.append(grad)
        etree.SubElement(bgpr, f"{{{ns_a}}}effectLst")
        # move bg before spTree (schema order)
        csld = slide._element.find(f"{{{ns_p}}}cSld")
        csld.remove(bg)
        csld.insert(0, bg)
        pptx_path = tmp_path / "gradbg.pptx"
        prs.save(str(pptx_path))

        result = pptx_to_json(pptx_path, tmp_path / "out")
        last = result["slides"][-1]
        els = last.get("elements", [])
        assert els and els[0].get("type") == "shape" and els[0].get("shape") == "rectangle" \
            and els[0].get("gradient"), f"gradient background not extracted: {els[:1]}"

    def test_image_background_becomes_fullslide_image(self, tmp_path):
        """Slides with a picture-fill background keep it as a cover image."""
        from lxml import etree
        from PIL import Image as PILImage

        img_file = tmp_path / "bg.png"
        PILImage.new("RGB", (32, 18), "blue").save(img_file)

        prs = Presentation(str(_template()))
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        # add picture to obtain an image part + rId, then reference it from bg
        pic = slide.shapes.add_picture(str(img_file), 0, 0)
        ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
        ns_p = "http://schemas.openxmlformats.org/presentationml/2006/main"
        ns_r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        rid = pic._element.find(f".//{{{ns_a}}}blip").get(f"{{{ns_r}}}embed")
        slide.shapes._spTree.remove(pic._element)  # picture itself not needed
        csld = slide._element.find(f"{{{ns_p}}}cSld")
        bg = etree.fromstring(
            f'<p:bg xmlns:p="{ns_p}" xmlns:a="{ns_a}" xmlns:r="{ns_r}"><p:bgPr>'
            f'<a:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></a:blipFill>'
            f'<a:effectLst/></p:bgPr></p:bg>')
        csld.insert(0, bg)
        pptx_path = tmp_path / "imgbg.pptx"
        prs.save(str(pptx_path))

        result = pptx_to_json(pptx_path, tmp_path / "out")
        last = result["slides"][-1]
        els = last.get("elements", [])
        assert els and els[0].get("type") == "image" and "_bg" in els[0].get("src", ""), \
            f"image background not extracted: {els[:1]}"


class TestHideMasterShapes:
    def test_show_master_sp_roundtrips(self, tmp_path):
        """showMasterSp="0" (Hide Background Graphics) must roundtrip;
        losing it lets master decoration cover the slide's own background."""
        prs = Presentation(str(_template()))
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide._element.set("showMasterSp", "0")
        pptx_path = tmp_path / "hidemaster.pptx"
        prs.save(str(pptx_path))

        result = pptx_to_json(pptx_path, tmp_path / "out")
        assert result["slides"][-1].get("hideMasterShapes") is True, \
            "showMasterSp=0 not extracted"

        from sdpm.builder import PPTXBuilder
        builder = PPTXBuilder(str(_template()), fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"}, default_text_color="#FFFFFF")
        builder.add_slide({"layout": builder_first_layout(builder), "hideMasterShapes": True})
        out = tmp_path / "rebuilt.pptx"
        builder.save(str(out))
        prs2 = Presentation(str(out))
        assert list(prs2.slides)[-1]._element.get("showMasterSp") == "0", \
            "showMasterSp=0 not rebuilt"


class TestSrgbColorTransforms:
    def test_lummod_on_srgb_cell_fill(self):
        """<a:srgbClr val="4F81BD"><a:lumMod val="75000"/> must darken the
        color — dropping the transform rendered strong blue instead of the
        original muted tone."""
        from lxml import etree
        from sdpm.converter.color import apply_element_transforms

        ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
        el = etree.fromstring(
            f'<a:srgbClr xmlns:a="{ns}" val="4F81BD"><a:lumMod val="75000"/></a:srgbClr>')
        out = apply_element_transforms("#4F81BD", el)
        assert out != "#4F81BD"
        # darker than the base
        assert int(out[1:3], 16) < 0x4F


class TestPresetColor:
    def test_prstclr_white_extracted(self, tmp_path):
        from lxml import etree

        prs = Presentation(str(_template()))
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        from pptx.util import Emu
        tb = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(2000000), Emu(500000))
        tb.text_frame.text = "PresetRed"
        run = tb.text_frame.paragraphs[0].runs[0]
        rPr = run._r.get_or_add_rPr()
        ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
        fill = etree.SubElement(rPr, f"{{{ns}}}solidFill")
        etree.SubElement(fill, f"{{{ns}}}prstClr").set("val", "red")
        rPr.insert(0, fill)
        pptx_path = tmp_path / "prst.pptx"
        prs.save(str(pptx_path))

        result = pptx_to_json(pptx_path, tmp_path / "out")
        dumped = json.dumps(result["slides"], ensure_ascii=False)
        assert "#FF0000" in dumped and "PresetRed" in dumped


class TestCellVerticalAlignDefault:
    def test_missing_anchor_becomes_top(self, tmp_path):
        """OOXML default cell anchor is top; the builder's default is middle,
        so the converter must emit vertical-align explicitly."""
        from pptx.util import Inches

        prs = Presentation(str(_template()))
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        gf = slide.shapes.add_table(2, 1, Inches(1), Inches(1), Inches(4), Inches(2))
        gf.table.cell(0, 0).text = "a"
        gf.table.cell(1, 0).text = "b"
        # remove anchor attribute if python-pptx set one
        ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
        for tc in gf.table._tbl.iter(f"{{{ns}}}tcPr"):
            tc.attrib.pop("anchor", None)
        pptx_path = tmp_path / "table_anchor.pptx"
        prs.save(str(pptx_path))

        result = pptx_to_json(pptx_path, tmp_path / "out")
        tables = [el for s in result["slides"] for el in s.get("elements", []) if el.get("type") == "table"]
        cell = tables[0]["rows"][0][0]
        assert isinstance(cell, dict) and cell.get("vertical-align") == "top"


class TestRawShapePassthrough:
    def test_wordart_text_warp_roundtrips(self, tmp_path):
        """prstTxWarp (WordArt arch/circle text) can't be expressed in the
        JSON schema — the shape must roundtrip as rawShape XML."""
        from lxml import etree

        prs = Presentation(str(_template()))
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        from pptx.util import Emu
        tb = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(3000000), Emu(3000000))
        tb.text_frame.text = "ARCHED"
        ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
        bodyPr = tb.text_frame._txBody.find(f"{{{ns}}}bodyPr")
        warp = etree.SubElement(bodyPr, f"{{{ns}}}prstTxWarp")
        warp.set("prst", "textArchUp")
        pptx_path = tmp_path / "wordart.pptx"
        prs.save(str(pptx_path))

        result = pptx_to_json(pptx_path, tmp_path / "out")
        raws = [el for s in result["slides"] for el in s.get("elements", []) if el.get("type") == "rawShape"]
        assert raws and "textArchUp" in raws[0].get("_shapeXml", ""), "WordArt not captured as rawShape"

        # builder injects it back
        from sdpm.builder import PPTXBuilder
        builder = PPTXBuilder(str(_template()), fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"}, default_text_color="#FFFFFF")
        builder.add_slide({"layout": builder_first_layout(builder), "elements": [raws[0]]})
        out = tmp_path / "rebuilt.pptx"
        builder.save(str(out))
        import zipfile
        z = zipfile.ZipFile(str(out))
        slides_xml = "".join(z.read(n).decode() for n in z.namelist() if n.startswith("ppt/slides/slide"))
        assert "textArchUp" in slides_xml, "rawShape not injected on rebuild"


class TestGroupImageReattach:
    def test_group_with_picture_keeps_image(self, tmp_path):
        """Images inside raw-XML groups must be re-attached on rebuild (the
        source rIds dangle in the new package otherwise)."""
        from PIL import Image as PILImage
        from pptx.util import Emu

        img = tmp_path / "photo.png"
        PILImage.new("RGB", (60, 40), "magenta").save(img)

        prs = Presentation(str(_template()))
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        pic = slide.shapes.add_picture(str(img), Emu(0), Emu(0))
        tb = slide.shapes.add_textbox(Emu(0), Emu(500000), Emu(1000000), Emu(300000))
        tb.text_frame.text = "label"
        # freeform member forces _groupXml passthrough; use a real group
        grp = slide.shapes.add_group_shape([pic, tb])
        # inject a fake freeform marker: easier — rotate group to force rawXml path
        grp.rotation = 15.0
        pptx_path = tmp_path / "grouped.pptx"
        prs.save(str(pptx_path))

        result = pptx_to_json(pptx_path, tmp_path / "out")
        groups = [el for s in result["slides"] for el in s.get("elements", []) if el.get("type") == "group"]
        assert groups and groups[0].get("_groupXml")
        assert groups[0].get("_groupImages"), "group-referenced image not saved"
        rel = list(groups[0]["_groupImages"].values())[0]
        assert (tmp_path / "out" / rel).exists()
