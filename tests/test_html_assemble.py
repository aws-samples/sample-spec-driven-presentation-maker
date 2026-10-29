# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Assembly of slides/<slug>.html into one offline reveal.js output.html."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pytest
from lxml import html as lxml_html

from sdpm import api
from sdpm.config import TEMPLATES_DIR, VENDOR_DIR
from sdpm.engine.html.assemble import assemble_deck, inline_js, parse_slide, style_root_css
from sdpm.engine.html.template import load_template_html
from sdpm.knowledge.assets import assets_installed

ICON = "assets:aws/Arch_AWS-Lambda_48"

SLIDES = {
    "cover": (
        '<section data-layout="Title Slide">\n'
        '  <h1 data-ph="title">HTML decks</h1>\n'
        '  <p data-ph="subtitle">Offline, one file</p>\n'
        '  <aside class="notes">Welcome everyone.</aside>\n'
        "</section>\n"
    ),
    "demo-1": (
        '<section data-layout="Title Only" data-auto-animate>\n'
        "  <style>.box { color: var(--accent); }</style>\n"
        '  <h1 data-ph="title">Step one</h1>\n'
        '  <div class="box" data-id="box" style="left:96px;top:300px;width:400px;height:200px">A</div>\n'
        "</section>\n"
    ),
    "demo-2": (
        '<section data-layout="Title Only" data-auto-animate>\n'
        '  <h1 data-ph="title">Step two</h1>\n'
        '  <div data-id="box" style="left:96px;top:300px;width:800px;height:200px">A</div>\n'
        '  <ul data-region="body"><li class="fragment">first</li><li class="fragment">second</li></ul>\n'
        "</section>\n"
    ),
}


def _make_deck(tmp_path: Path, template: str = "blank-light", slides: dict[str, str] | None = None) -> Path:
    deck = tmp_path / "deck"
    api.init("t", output_dir=deck, output_format="html")
    assert api.apply_style(deck, style="typographic", template=template)["status"] == "ok"
    slides = SLIDES if slides is None else slides
    outline = "# Assembly test\n\n" + "".join(f"- [{slug}] {slug}\n" for slug in slides)
    (deck / "specs" / "outline.md").write_text(outline, encoding="utf-8")
    for slug, text in slides.items():
        (deck / "slides" / f"{slug}.html").write_text(text, encoding="utf-8")
    return deck


def _assemble(deck: Path, *, deck_css: str | None = None, slides: dict[str, str] | None = None):
    meta = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
    template = load_template_html(TEMPLATES_DIR / f"{meta['template']}.pptx")
    slides = SLIDES if slides is None else slides
    return assemble_deck(
        slides=list(slides.items()),
        template=template,
        art_direction_html=(deck / "specs" / "art-direction.html").read_text(encoding="utf-8"),
        default_background=meta.get("defaultBackground"),
        default_text_color=meta.get("defaultTextColor"),
        title="Assembly test",
        deck_dir=deck,
        deck_css=deck_css,
    )


@pytest.fixture
def built(tmp_path: Path):
    deck = _make_deck(tmp_path)
    result = _assemble(deck)
    return deck, result, lxml_html.document_fromstring(result.html)


def _style_text(doc) -> str:
    return "\n".join(el.text or "" for el in doc.iter("style"))


def test_sections_in_deck_order_with_slugs(built) -> None:
    _, result, doc = built
    sections = doc.xpath('//div[@class="slides"]/section')
    assert [s.get("data-slug") for s in sections] == list(SLIDES)
    assert [s.get("data-layout") for s in sections] == ["Title Slide", "Title Only", "Title Only"]
    assert result.slugs == list(SLIDES)
    assert result.layouts_used == ["Title Slide", "Title Only"]
    assert result.bytes == len(result.html.encode("utf-8"))


def test_notes_fragments_and_auto_animate_preserved(built) -> None:
    _, _, doc = built
    notes = doc.xpath('//section[@data-slug="cover"]/aside[@class="notes"]')
    assert [n.text for n in notes] == ["Welcome everyone."]
    demo1, demo2 = (doc.xpath(f'//section[@data-slug="{s}"]')[0] for s in ("demo-1", "demo-2"))
    assert demo1.get("data-auto-animate") is not None and demo2.get("data-auto-animate") is not None
    assert demo1.xpath('.//*[@data-id="box"]') and demo2.xpath('.//*[@data-id="box"]')
    assert len(demo2.xpath('.//li[@class="fragment"]')) == 2


def test_reveal_initialize_config(built) -> None:
    _, result, _ = built
    config = re.search(r"Reveal\.initialize\(\{(.*?)\}\);", result.html).group(1)
    for part in ("width:1920", "height:1080", "center:false", "hash:true", "RevealNotes"):
        assert part in config


def test_one_decoration_background_per_used_layout(built) -> None:
    _, result, doc = built
    deck_rules = doc.xpath('//style[@id="sdpm-deck"]')[0].text
    rules = re.findall(r'section\[data-layout="([^"]+)"\]\{background-image:url\("data:image/svg\+xml;base64,',
                       deck_rules)
    assert rules == ["Title Slide", "Title Only"]
    assert result.html.count('section[data-layout="Title Only"]{background-image') == 1


def test_regions_and_chrome_are_absolutely_positioned(built) -> None:
    _, _, doc = built
    deck_rules = doc.xpath('//style[@id="sdpm-deck"]')[0].text
    assert "[data-sdpm-chrome],[data-region]{position:absolute}" in deck_rules


def test_no_external_resource_reference(built) -> None:
    _, result, doc = built
    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue
        for name in ("src", "href", "srcset", "poster", "data", "xlink:href"):
            value = el.get(name)
            if value is None or (name == "href" and el.tag == "a"):
                continue
            assert value.startswith(("data:", "#")), (el.tag, name, value[:80])
    css = _style_text(doc)
    assert "@import" not in css
    for url in re.findall(r"url\(\s*['\"]?([^'\")]*)", css):
        assert url.startswith(("data:", "#")), url[:80]
    scripts = list(doc.iter("script"))
    assert len(scripts) == 3 and all(s.get("src") is None for s in scripts)
    # Only the closing tags of the three inline scripts.
    assert len(re.findall(r"</script", result.html, re.IGNORECASE)) == 3


def test_reveal_assets_are_inlined(built) -> None:
    _, result, _ = built
    head = (VENDOR_DIR / "revealjs" / "reveal.css").read_text(encoding="utf-8")[:200]
    assert head.replace("</", "<\\/") in result.html
    assert "RevealNotes" in result.html


def test_slide_styles_nested_and_removed_from_section(built) -> None:
    _, _, doc = built
    slide_css = doc.xpath('//style[@id="sdpm-slides"]')[0].text
    assert re.search(r'section\[data-slug="demo-1"\]\{\s*\.box \{ color: var\(--accent\); \}\s*\}', slide_css)
    assert not doc.xpath('//section//style')


def test_ground_comes_from_style_color_bg(built) -> None:
    deck, result, _ = built
    meta = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
    assert meta["defaultBackground"]
    assert f":root{{--sdpm-ground:{meta['defaultBackground']}}}" in result.html
    assert f"color:{meta['defaultTextColor']}" in result.html


def test_style_root_embedded_before_theme(built) -> None:
    deck, result, doc = built
    root = style_root_css((deck / "specs" / "art-direction.html").read_text(encoding="utf-8"))
    assert root.startswith(":root{") and "--fs-" in root
    ids = [s.get("id") for s in doc.iter("style") if s.get("id")]
    assert ids == ["sdpm-style-root", "sdpm-theme", "sdpm-deck", "sdpm-slides"]
    assert doc.xpath('//style[@id="sdpm-style-root"]')[0].text == root


def test_slide_number_chrome_drawn_by_assembler(built) -> None:
    _, _, doc = built
    numbers = [el.text_content() for el in doc.xpath('//*[@data-sdpm-chrome="slide-number"]')]
    assert numbers == ["1", "2", "3"]


def test_deck_css_embedded_once_unscoped(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path)
    css = ".card-shared { border: 2px solid var(--color-border); }"
    result = _assemble(deck, deck_css=css)
    doc = lxml_html.document_fromstring(result.html)
    assert result.html.count(css) == 1
    assert doc.xpath('//style[@id="sdpm-deck-css"]')[0].text == css
    ids = [s.get("id") for s in doc.iter("style") if s.get("id")]
    assert ids.index("sdpm-deck-css") == ids.index("sdpm-deck") + 1 == ids.index("sdpm-slides") - 1


def test_deck_relative_image_and_css_url_become_data_uris(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path)
    (deck / "images").mkdir()
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    (deck / "images" / "dot.png").write_bytes(png)
    slides = {"pic": (
        '<section data-layout="Blank"><style>.bg{background:url(images/dot.png)}</style>'
        '<img src="images/dot.png" alt="dot"><div style="background-image:url(\'images/dot.png\')"></div>'
        '<img src="images/missing.png"><img src="../outside.png"></section>')}
    result = _assemble(deck, slides=slides, deck_css=".x{background:url(images/dot.png)}")
    assert result.html.count("data:image/png;base64,") == 4
    assert any("images/missing.png" in w for w in result.warnings)
    assert any("outside the deck" in w for w in result.warnings)


@pytest.mark.skipif(not assets_installed(), reason="asset catalogs not installed")
def test_svg_icon_is_inlined_with_prefixed_ids(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path)
    slides = {"icons": (
        f'<section data-layout="Blank"><img src="{ICON}" alt="Lambda" class="fragment" '
        f'style="width:96px"><img src="{ICON}" alt="Lambda again"></section>')}
    result = _assemble(deck, slides=slides)
    assert not result.warnings
    doc = lxml_html.document_fromstring(result.html)
    svgs = doc.xpath('//section[@data-slug="icons"]/svg')
    assert len(svgs) == 2 and not doc.xpath('//section//img')
    assert svgs[0].get("aria-label") == "Lambda" and svgs[0].get("class") == "fragment"
    ids = [el.get("id") for svg in svgs for el in svg.iter() if isinstance(el.tag, str) and el.get("id")]
    assert ids and len(ids) == len(set(ids))
    assert all(i.startswith(("s1i1-", "s1i2-")) for i in ids)


def test_unparseable_slide_is_skipped_with_warning(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path)
    slides = {"ok": SLIDES["cover"], "bad": "<div>no section</div>"}
    result = _assemble(deck, slides=slides)
    assert result.slugs == ["ok"]
    assert any(w.startswith("bad: slide skipped") for w in result.warnings)


def test_parse_slide_reports_structure() -> None:
    parsed = parse_slide(SLIDES["cover"])
    assert parsed.errors == [] and parsed.layout == "Title Slide" and parsed.has_notes
    assert parse_slide("<section></section><section></section>").errors[0].startswith("expected exactly one")
    assert parse_slide("").section is None


def test_inline_js_escapes_script_end_and_comment_open() -> None:
    assert inline_js('a="</SCRIPT>";b="<!--"') == 'a="<\\/SCRIPT>";b="<\\!--"'
