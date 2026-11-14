# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Accessibility metadata: element ``alt`` / ``decorative`` and deck ``title`` / ``language``.

The builder writes them where PowerPoint's Accessibility Checker and screen
readers look (``p:cNvPr@descr``, the ``adec:decorative`` extension,
``docProps/core.xml``); the converter reads them back.
"""

import json
from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu

from sdpm.api import generate
from sdpm.config import TEMPLATES_DIR
from sdpm.engine.accessibility import DECORATIVE_URI
from sdpm.engine.converter.pipeline import pptx_to_json
from test_roundtrip import _make_deck

_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">'
        '<path d="M0 0h48v48H0z"/></svg>')


def _elements(tmp_path: Path, **props) -> list[dict]:
    """One element of each kind that carries a description."""
    Image.new("RGB", (200, 100), "red").save(tmp_path / "p.png")
    (tmp_path / "i.svg").write_text(_SVG)
    return [
        {"type": "image", "src": str(tmp_path / "p.png"), "x": 0, "y": 0, "width": 200, **props},
        {"type": "image", "src": str(tmp_path / "i.svg"), "x": 300, "y": 0, "width": 48, "height": 48,
         **props},
        {"type": "chart", "chartType": "bar", "x": 0, "y": 300, "width": 600, "height": 400,
         "categories": ["a", "b"], "series": [{"name": "s", "values": [1, 2]}], **props},
        {"type": "table", "x": 700, "y": 300, "width": 600, "height": 200,
         "headers": ["h1", "h2"], "rows": [["1", "2"]], **props},
    ]


def _build(tmp_path: Path, elements: list[dict], deck_meta: dict | None = None) -> Path:
    deck = _make_deck(tmp_path, elements)
    if deck_meta:
        meta = json.loads((deck / "deck.json").read_text())
        (deck / "deck.json").write_text(json.dumps({**meta, **deck_meta}))
    out = tmp_path / "out.pptx"
    generate(deck, output_path=out)
    return out


def _cnvprs(pptx: Path) -> list:
    return [shape._element.xpath("./*[1]/p:cNvPr")[0] for shape in Presentation(str(pptx)).slides[0].shapes]


def _is_decorative(cnvpr) -> bool:
    return bool(cnvpr.xpath(f"a:extLst/a:ext[@uri='{DECORATIVE_URI}']"))


class TestElementAlt:
    def test_alt_is_written_to_descr(self, tmp_path):
        out = _build(tmp_path, _elements(tmp_path, alt="Sales grew 20%"))
        assert [c.get("descr") for c in _cnvprs(out)] == ["Sales grew 20%"] * 4

    def test_without_alt_descr_is_unchanged(self, tmp_path):
        out = _build(tmp_path, _elements(tmp_path))
        # python-pptx's own default (the file name) stays; nothing else gains a descr.
        assert [c.get("descr") for c in _cnvprs(out)] == ["p.png", None, None, None]
        assert not any(_is_decorative(c) for c in _cnvprs(out))

    def test_decorative_marks_and_drops_descr(self, tmp_path):
        out = _build(tmp_path, _elements(tmp_path, decorative=True))
        cnvprs = _cnvprs(out)
        assert all(_is_decorative(c) for c in cnvprs)
        assert all(c.get("descr") is None for c in cnvprs)

    def test_alt_goes_on_the_picture_not_its_label(self, tmp_path):
        Image.new("RGB", (60, 60), "red").save(tmp_path / "p.png")
        out = _build(tmp_path, [{"type": "image", "src": str(tmp_path / "p.png"), "x": 0, "y": 0,
                                 "width": 60, "label": "Lambda", "alt": "AWS Lambda icon"}])
        pic, label = _cnvprs(out)
        assert pic.get("descr") == "AWS Lambda icon"
        assert label.get("descr") is None

    def test_group_children_keep_their_own_alt(self, tmp_path):
        Image.new("RGB", (60, 60), "red").save(tmp_path / "p.png")
        out = _build(tmp_path, [{"type": "group", "alt": "ignored for a flattened group", "elements": [
            {"type": "image", "src": str(tmp_path / "p.png"), "x": 0, "y": 0, "width": 60, "alt": "Icon"},
            {"type": "shape", "shape": "rectangle", "x": 100, "y": 0, "width": 60, "height": 60,
             "decorative": True},
        ]}])
        pic, shape = _cnvprs(out)
        assert pic.get("descr") == "Icon"
        assert _is_decorative(shape)


class TestRoundTrip:
    @pytest.mark.parametrize("props", [{"alt": "Sales grew 20%"}, {"decorative": True}])
    def test_converter_reads_back(self, tmp_path, props):
        out = _build(tmp_path, _elements(tmp_path, **props))
        slide = pptx_to_json(out, tmp_path / "extracted")["slides"][0]
        assert [{k: e.get(k) for k in props} for e in slide["elements"]] == [props] * 4

    def test_file_name_descr_is_not_read_as_alt(self, tmp_path):
        out = _build(tmp_path, _elements(tmp_path))
        slide = pptx_to_json(out, tmp_path / "extracted")["slides"][0]
        assert not any("alt" in e or "decorative" in e for e in slide["elements"])

    def test_file_name_with_spaces_is_not_read_as_alt(self, tmp_path):
        Image.new("RGB", (60, 60), "red").save(tmp_path / "Screenshot 2026-11-14 at 10.00.png")
        out = _build(tmp_path, [{"type": "image", "src": str(tmp_path / "Screenshot 2026-11-14 at 10.00.png"),
                                 "x": 0, "y": 0, "width": 60}])
        assert _cnvprs(out)[0].get("descr") == "Screenshot 2026-11-14 at 10.00.png"
        slide = pptx_to_json(out, tmp_path / "extracted")["slides"][0]
        assert "alt" not in slide["elements"][0]

    def test_flattened_group_alt_is_not_read(self, tmp_path):
        # The builder flattens such a group, so an alt on it would be dropped on rebuild.
        prs = Presentation(str(TEMPLATES_DIR / "blank-light.pptx"))
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        group = slide.shapes.add_group_shape()
        group.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(0), Emu(0), Emu(900000), Emu(900000))
        group.shapes.add_shape(MSO_SHAPE.OVAL, Emu(1000000), Emu(0), Emu(900000), Emu(900000))
        group._element.xpath("./p:nvGrpSpPr/p:cNvPr")[0].set("descr", "Architecture diagram")
        src = tmp_path / "src.pptx"
        prs.save(src)
        groups = [e for s in pptx_to_json(src, tmp_path / "extracted")["slides"]
                  for e in s.get("elements", []) if e.get("type") == "group"]
        assert len(groups) == 1 and "_groupXml" not in groups[0]
        assert "alt" not in groups[0]


class TestDocumentProperties:
    def test_title_and_language_are_written_and_read_back(self, tmp_path):
        out = _build(tmp_path, [], {"title": "Sales Review", "language": "en-US"})
        props = Presentation(str(out)).core_properties
        assert (props.title, props.language) == ("Sales Review", "en-US")
        pptx_to_json(out, tmp_path / "extracted")
        deck = json.loads((tmp_path / "extracted" / "deck.json").read_text())
        assert (deck["title"], deck["language"]) == ("Sales Review", "en-US")

    def test_title_falls_back_to_first_slide_title(self, tmp_path):
        deck = _make_deck(tmp_path, [])
        (deck / "slides" / "s1.json").write_text(json.dumps({"layout": "Title Slide", "placeholders": {
            "0": "Quarterly\nReview"}}))
        out = tmp_path / "out.pptx"
        generate(deck, output_path=out)
        assert Presentation(str(out)).core_properties.title == "Quarterly Review"

    def test_without_title_or_language_core_stays_empty(self, tmp_path):
        out = _build(tmp_path, [])
        props = Presentation(str(out)).core_properties
        assert (props.title, props.language) == ("", "")
