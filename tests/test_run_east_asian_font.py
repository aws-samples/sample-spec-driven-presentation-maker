# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The East Asian typeface (<a:ea>) on every run the builder fonts.

PowerPoint picks a run's font per script: ``a:latin`` for Latin text,
``a:ea`` for CJK. python-pptx writes only ``a:latin``, so a run styled with
the deck's ``fonts.fullwidth`` used to carry that name where PowerPoint never
looks, and Japanese text fell back to the theme's East Asian font — empty in
the bundled templates, so the renderer chose for itself (LibreOffice embedded
Noto Sans for a deck that asked for Noto Serif JP), and a Latin font without
CJK glyphs produced tofu.

Runs whose font is inherited on purpose (a title placeholder, an imported
``_lstStyle``) carry no ``a:latin``, and keep carrying no ``a:ea``.
"""

from pathlib import Path

import pytest
from lxml import etree

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
TEMPLATE = Path(__file__).parent.parent / "sdpm" / "templates" / "blank-dark.pptx"

FULLWIDTH = "Meiryo"
HALFWIDTH = "Arial"


def _slide(slide_def: dict, fonts: dict | None = None):
    """Build one slide in memory and return its python-pptx slide."""
    from sdpm.engine.builder import PPTXBuilder

    builder = PPTXBuilder(
        str(TEMPLATE),
        fonts={"fullwidth": FULLWIDTH, "halfwidth": HALFWIDTH} if fonts is None else fonts,
        default_text_color="#FFFFFF",
    )
    builder.add_slide(slide_def)
    return builder.prs.slides[0]


def _runs(slide) -> list[tuple[str, str | None, str | None]]:
    """(text, a:latin typeface, a:ea typeface) for every run on the slide."""
    out = []
    for sp in slide.shapes:
        for r in sp._element.iter(f"{A}r"):
            t = r.find(f"{A}t")
            rPr = r.find(f"{A}rPr")
            latin = rPr.find(f"{A}latin") if rPr is not None else None
            ea = rPr.find(f"{A}ea") if rPr is not None else None
            out.append((
                t.text if t is not None else "",
                latin.get("typeface") if latin is not None else None,
                ea.get("typeface") if ea is not None else None,
            ))
    return out


def _textbox(**props) -> dict:
    return {"type": "textbox", "x": 100, "y": 100, "width": 900, "height": 200,
            "fontSize": 24, **props}


def _deck(*elements) -> dict:
    return {"layout": "Blank", "elements": list(elements)}


class TestEastAsianFontOnRuns:
    def test_a_cjk_run_names_the_decks_fullwidth_font(self):
        runs = _runs(_slide(_deck(_textbox(text="日本語の見出し"))))
        assert runs == [("日本語の見出し", FULLWIDTH, FULLWIDTH)]

    def test_a_latin_run_names_it_too_so_a_stray_cjk_char_still_resolves(self):
        # Runs are split by character width, so a:latin differs per run while
        # a:ea stays the deck's Japanese font on both.
        runs = _runs(_slide(_deck(_textbox(text="日本語とEnglish"))))
        assert runs == [("日本語と", FULLWIDTH, FULLWIDTH),
                        (" English", HALFWIDTH, FULLWIDTH)]

    def test_ea_follows_latin_as_the_schema_requires(self):
        # CT_TextCharacterProperties is an ordered sequence; PowerPoint drops
        # children that appear out of order.
        slide = _slide(_deck(_textbox(text="日本語")))
        (r,) = list(slide.shapes[0]._element.iter(f"{A}r"))
        tags = [c.tag.split("}")[1] for c in r.find(f"{A}rPr")]
        assert tags.index("ea") == tags.index("latin") + 1

    @pytest.mark.parametrize("element", [
        {"type": "shape", "shape": "rectangle", "x": 10, "y": 10, "width": 400,
         "height": 200, "fill": "#333333", "text": "図形の日本語"},
        {"type": "freeform", "x": 10, "y": 10, "width": 400, "height": 200,
         "fill": "#333333", "text": "図形の日本語",
         "path": [{"cmd": "M", "x": 0, "y": 0}, {"cmd": "L", "x": 400, "y": 0},
                  {"cmd": "L", "x": 400, "y": 200}, {"cmd": "Z"}]},
        {"type": "table", "x": 10, "y": 10, "width": 400, "height": 100,
         "rows": [["表の日本語"]]},
    ], ids=["shape", "freeform", "table"])
    def test_every_text_surface_carries_it(self, element):
        assert (FULLWIDTH, FULLWIDTH) in [(latin, ea) for _, latin, ea in
                                          _runs(_slide(_deck(element)))]

    def test_speaker_notes_carry_it(self):
        slide = _slide({"layout": "Blank", "elements": [], "notes": "日本語のノート"})
        runs = [(latin, ea) for _, latin, ea in
                _runs(slide.notes_slide) if _ == "日本語のノート"]
        assert runs == [(FULLWIDTH, FULLWIDTH)]

    def test_an_inline_font_marker_names_itself_on_both(self):
        runs = _runs(_slide(_deck(_textbox(text="{{font=Yu Gothic:日本語}}"))))
        assert runs == [("日本語", "Yu Gothic", "Yu Gothic")]

    def test_font_family_restyles_latin_only_and_leaves_ea_japanese(self):
        # fontFamily is the halfwidth font (a code face, say) — it must not
        # become the Japanese font.
        runs = _runs(_slide(_deck(_textbox(text="日本語とcode",
                                           fontFamily="Lucida Console"))))
        assert runs == [("日本語と", FULLWIDTH, FULLWIDTH),
                        (" code", "Lucida Console", FULLWIDTH)]

    def test_a_deck_with_no_fullwidth_font_writes_no_ea(self):
        runs = _runs(_slide(_deck(_textbox(text="日本語")),
                            fonts={"fullwidth": None, "halfwidth": HALFWIDTH}))
        assert runs == [("日本語", None, None)]

    def test_a_title_placeholder_keeps_the_templates_own_font(self):
        slide = _slide({"layout": "Title and Content",
                        "placeholders": {"0": "日本語の題"}, "elements": []})
        runs = [(latin, ea) for text, latin, ea in _runs(slide)
                if text == "日本語の題"]
        assert runs == [(None, None)]
