# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Per-slide text summary of HTML slides (sdpm.engine.html.text)."""

from __future__ import annotations

from sdpm.engine.html.text import MAX_TEXT_CHARS, slide_text_summary


def test_title_placeholder_notes_and_text() -> None:
    text = (
        '<section data-layout="Title Only">\n'
        "  <style>.k { color: red; }</style>\n"
        '  <h2>Kicker</h2>\n'
        '  <h1 data-ph="title">The\n   claim</h1>\n'
        '  <ul data-region="body"><li class="fragment">first</li><li>second</li></ul>\n'
        '  <aside class="notes">Speak  slowly.\n Then pause.</aside>\n'
        "  <!-- comment -->tail\n"
        "</section>\n"
    )
    assert slide_text_summary(text) == {
        "layout": "Title Only",
        "title": "The claim",
        "notes": "Speak slowly. Then pause.",
        "text": "Kicker The claim first second tail",
    }


def test_title_falls_back_to_first_heading() -> None:
    summary = slide_text_summary('<section data-layout="Blank"><p>intro</p><h2>Sub</h2><h1>Main</h1></section>')
    assert summary["title"] == "Sub"
    assert slide_text_summary('<section data-layout="Blank"><p>no heading</p></section>')["title"] == ""


def test_svg_text_is_included_and_text_is_capped() -> None:
    summary = slide_text_summary('<section data-layout="Blank"><svg><text>Label</text></svg>'
                                 f"<p>{'word ' * 2000}</p></section>")
    assert summary["text"].startswith("Label word")
    assert len(summary["text"]) == MAX_TEXT_CHARS == 4000


def test_unusable_slide() -> None:
    assert slide_text_summary("<div>no section</div>") == {"layout": None, "title": "", "notes": "", "text": ""}
    assert slide_text_summary('<section><h1 data-ph="title">x</h1></section>')["layout"] is None
