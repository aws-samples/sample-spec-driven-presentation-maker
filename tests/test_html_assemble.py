# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Assembly of slides/<slug>.html into one offline reveal.js output.html."""

from __future__ import annotations

import base64
import dataclasses
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


def _assemble(deck: Path, *, deck_css: str | None = None, slides: dict[str, str] | None = None,
              template=None):
    meta = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
    if template is None:
        template = load_template_html(TEMPLATES_DIR / f"{meta['template']}.pptx",
                                      cache_root=deck.parent / "template-cache")
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


def test_vendored_code_carries_license_notices(built) -> None:
    _, result, doc = built
    vendor_css = doc.xpath("//head/style")[0].text
    assert vendor_css.startswith("/*! reveal.js ") and "MIT License" in vendor_css.splitlines()[0]
    notes = [s.text for s in doc.xpath("//body/script") if "RevealNotes" in (s.text or "")
             and "Reveal.initialize" not in s.text][0]
    head = notes.splitlines()[:2]
    assert head[0].startswith("/*! reveal.js ") and head[1].startswith("/*! Includes marked | MIT License")


def test_reveal_initialize_config(built) -> None:
    _, result, _ = built
    config = re.search(r"var o=\{(.*?)\};", result.html).group(1)
    for part in ("width:1920", "height:1080", "center:false", "hash:true", "RevealNotes"):
        assert part in config
    assert "Reveal.initialize(o);" in result.html


_DECORATION_RULE = r'section\[data-layout="([^"]+)"\]\{background-image:url\("data:image/svg\+xml;base64,'


def test_template_without_decorations_adds_no_background_image(built) -> None:
    _, _, doc = built
    deck_rules = doc.xpath('//style[@id="sdpm-deck"]')[0].text
    assert re.findall(_DECORATION_RULE, deck_rules) == []


def test_one_decoration_background_per_used_layout(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path)
    plain = load_template_html(TEMPLATES_DIR / "blank-light.pptx", cache_root=tmp_path / "template-cache")
    svgs = {}
    for name in ("Title Slide", "Title Only", "Blank"):  # Blank is not used by SLIDES
        svg = tmp_path / f"{name}.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="9" height="9"/></svg>',
                       encoding="utf-8")
        svgs[name] = svg
    result = _assemble(deck, template=dataclasses.replace(plain, svg_paths=svgs))
    doc = lxml_html.document_fromstring(result.html)
    deck_rules = doc.xpath('//style[@id="sdpm-deck"]')[0].text
    assert re.findall(_DECORATION_RULE, deck_rules) == ["Title Slide", "Title Only"]
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


def test_nested_section_slide_is_skipped(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path)
    slides = {"ok": SLIDES["cover"],
              "stack": '<section data-layout="Blank"><section>inner</section></section>'}
    result = _assemble(deck, slides=slides)
    assert result.slugs == ["ok"]
    assert any(w.startswith("stack: slide skipped") and "nested <section>" in w for w in result.warnings)


def test_non_nestable_at_rules_are_hoisted_and_keyframes_renamed(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path)
    slides = {"anim": (
        '<section data-layout="Blank"><style>'
        "/* pulse */ @keyframes pulse { from { opacity: .3 } to { opacity: 1 } }\n"
        ".dot { animation: pulse 1s infinite; }\n"
        "@font-face { font-family: Demo; src: local(Demo); }\n"
        "@media (prefers-reduced-motion) { .dot { animation-name: none } }"
        "</style><style>.ring { animation-name: pulse, fade; }</style>"
        '<div class="dot" style="animation:pulse 2s">x</div></section>')}
    result = _assemble(deck, slides=slides)
    doc = lxml_html.document_fromstring(result.html)
    css = doc.xpath('//style[@id="sdpm-slides"]')[0].text
    wrapper = css.index('section[data-slug="anim"]{')
    assert css.index("@keyframes sdpm-anim-pulse {") < wrapper
    assert css.index("@font-face { font-family: Demo;") < wrapper
    assert "@keyframes pulse" not in css
    assert ".dot { animation: sdpm-anim-pulse 1s infinite; }" in css[wrapper:]
    assert "@media (prefers-reduced-motion) { .dot { animation-name: none } }" in css[wrapper:]
    assert ".ring { animation-name: sdpm-anim-pulse, fade; }" in css
    assert doc.xpath('//div[@class="dot"]')[0].get("style") == "animation:sdpm-anim-pulse 2s"


def test_leading_at_keyword_skips_comments_without_backtracking() -> None:
    from sdpm.engine.html.assemble import _leading_at_keyword

    m = _leading_at_keyword(" /* a */\n/* b */ @keyframes pulse {}")
    assert m is not None and m.group(1) == "keyframes"
    assert _leading_at_keyword(".dot { color: red }") is None
    assert _leading_at_keyword("/* unterminated @keyframes x {}") is None
    # CodeQL py/redos input for the former regex: "/*" plus many "*//*" and no "@".
    assert _leading_at_keyword("/*" + "*//*" * 50_000) is None


def test_srcset_object_and_svg_image_refs_are_embedded(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path)
    (deck / "images").mkdir()
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    (deck / "images" / "dot.png").write_bytes(png)
    slides = {"refs": (
        '<section data-layout="Blank">'
        '<img src="data:image/png;base64,AAAA" srcset="images/dot.png 1x, data:image/png;base64,AA,BB 2x">'
        '<object data="images/dot.png"></object>'
        '<svg><image href="images/dot.png"/><image xlink:href="images/dot.png"/></svg>'
        '<div style="background-image:image-set(&quot;images/dot.png&quot; 1x, '
        'url(images/dot.png) 2x)"></div></section>')}
    result = _assemble(deck, slides=slides)
    assert not result.warnings
    doc = lxml_html.document_fromstring(result.html)
    section = doc.xpath('//section[@data-slug="refs"]')[0]
    uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    assert section.xpath(".//img")[0].get("srcset") == f"{uri} 1x, data:image/png;base64,AA,BB 2x"
    assert section.xpath(".//object")[0].get("data") == uri
    images = section.xpath(".//image")
    assert images[0].get("href") == uri and images[1].get("xlink:href") == uri
    assert section.xpath(".//div")[0].get("style").count(uri) == 2
    assert "images/" not in lxml_html.tostring(section, encoding="unicode")


def test_linked_stylesheet_is_not_embedded(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path)
    (deck / "images").mkdir()
    (deck / "images" / "extra.css").write_text(".extra{color:red}", encoding="utf-8")
    slides = {"css": '<section data-layout="Blank"><link rel="stylesheet" href="images/extra.css"></section>'}
    result = _assemble(deck, slides=slides)
    doc = lxml_html.document_fromstring(result.html)
    assert doc.xpath('//section[@data-slug="css"]//link')[0].get("href") == "images/extra.css"
    assert ".extra{color:red}" not in result.html and "data:text/css" not in result.html


def test_deck_svg_is_embedded_as_an_inert_image(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path)
    (deck / "images").mkdir()
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" onload="evil()"><script>evil()</script>'
           '<image href="https://evil.example/x.png"/><rect id="r" width="10" height="10"/></svg>')
    (deck / "images" / "chart.svg").write_text(svg, encoding="utf-8")
    slides = {"svg": (
        '<section data-layout="Blank"><img src="images/chart.svg" alt="chart">'
        '<div style="background:url(images/chart.svg)"></div>'
        '<img srcset="images/chart.svg 1x"></section>')}
    result = _assemble(deck, slides=slides)
    assert not result.warnings
    doc = lxml_html.document_fromstring(result.html)
    section = doc.xpath('//section[@data-slug="svg"]')[0]
    uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
    imgs = section.xpath(".//img")
    assert imgs[0].get("src") == uri and imgs[0].get("alt") == "chart"
    assert imgs[1].get("srcset") == f"{uri} 1x"
    assert uri in section.xpath(".//div")[0].get("style")
    text = lxml_html.tostring(section, encoding="unicode")
    assert not section.xpath(".//svg | .//script") and "onload" not in text
    assert "evil" not in result.html


def test_size_warnings(tmp_path: Path, monkeypatch) -> None:
    from sdpm.engine.html import assemble

    deck = _make_deck(tmp_path)
    (deck / "images").mkdir()
    (deck / "images" / "big.png").write_bytes(b"\x89PNG" + b"0" * 2000)
    slides = {"big": '<section data-layout="Blank"><img src="images/big.png"><img src="images/big.png"></section>'}
    assert not _assemble(deck, slides=slides).warnings
    monkeypatch.setattr(assemble, "MAX_EMBEDDED_FILE_BYTES", 1000)
    monkeypatch.setattr(assemble, "MAX_OUTPUT_HTML_BYTES", 1000)
    result = _assemble(deck, slides=slides)
    assert [w.split(":", 1)[0] for w in result.warnings] == ["big", "output.html"]
    assert "images/big.png is 0.0 MB" in result.warnings[0]
    assert result.warnings[1].startswith(f"output.html: {result.bytes / 1048576:.1f} MB")


def test_inline_js_escapes_script_end_and_comment_open() -> None:
    assert inline_js('a="</SCRIPT>";b="<!--"') == 'a="<\\/SCRIPT>";b="<\\!--"'


# ── static per-slide previews ────────────────────────────────────────────

def test_one_static_preview_per_included_slide(built) -> None:
    _, result, _ = built
    assert list(result.previews) == list(SLIDES)
    for slug, text in result.previews.items():
        doc = lxml_html.document_fromstring(text)
        assert "<script" not in text.lower()
        meta = doc.xpath('//head/meta')
        assert meta[0].get("charset") == "utf-8"
        assert meta[1].get("http-equiv") == "Content-Security-Policy"
        policy = meta[1].get("content")
        assert "script-src 'none'" in policy and "frame-src 'none'" in policy
        assert meta[2].get("name") == "referrer" and meta[2].get("content") == "no-referrer"
        sections = doc.xpath("//section")
        assert [s.get("data-slug") for s in sections] == [slug]
        assert "present" in sections[0].get("class").split()


def test_preview_has_only_its_own_slide_css_and_layout(tmp_path: Path) -> None:
    deck = _make_deck(tmp_path)
    plain = load_template_html(TEMPLATES_DIR / "blank-light.pptx", cache_root=tmp_path / "template-cache")
    svgs = {}
    for name in ("Title Slide", "Title Only"):
        svg = tmp_path / f"{name}.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="9" height="9"/></svg>',
                       encoding="utf-8")
        svgs[name] = svg
    result = _assemble(deck, template=dataclasses.replace(plain, svg_paths=svgs), deck_css=".shared{color:red}")
    cover = lxml_html.document_fromstring(result.previews["cover"])
    demo = lxml_html.document_fromstring(result.previews["demo-1"])
    assert re.findall(_DECORATION_RULE, cover.xpath('//style[@id="sdpm-deck"]')[0].text) == ["Title Slide"]
    assert re.findall(_DECORATION_RULE, demo.xpath('//style[@id="sdpm-deck"]')[0].text) == ["Title Only"]
    assert 'section[data-slug="demo-1"]' in demo.xpath('//style[@id="sdpm-slides"]')[0].text
    assert (cover.xpath('//style[@id="sdpm-slides"]')[0].text or "") == ""
    for doc in (cover, demo):
        assert doc.xpath('//style[@id="sdpm-deck-css"]')[0].text == ".shared{color:red}"
        assert doc.xpath('//style[@id="sdpm-theme"]') and doc.xpath('//style[@id="sdpm-style-root"]')


def test_preview_shows_every_fragment_statically(built) -> None:
    _, result, _ = built
    doc = lxml_html.document_fromstring(result.previews["demo-2"])
    css = doc.xpath('//style[@id="sdpm-preview"]')[0].text
    assert "opacity:1!important" in css and "visibility:inherit!important" in css
    assert ".reveal .fragment.fade-up" in css and "transform:none!important" in css
    assert "display:block!important" in css and "width:1920px;height:1080px" in css
    ids = [s.get("id") for s in doc.iter("style") if s.get("id")]
    assert ids[-1] == "sdpm-preview"
    assert len(doc.xpath('//li[@class="fragment"]')) == 2


def test_collect_refs_matches_the_assembler_scan() -> None:
    from sdpm.engine.html.assemble import collect_refs

    slides = [
        '<section data-layout="Blank"><style>.a{background:url("images/a.png#x")}</style>'
        f'<img src="{ICON}"><img src="images/b.png?v=2" srcset="images/c.png 1x, https://x.example/d.png 2x">'
        '<video poster="media/p.jpg" src="media/v.mp4"></video><object data="docs/o.svg"></object>'
        '<svg><image href="images/e.png"/></svg>'
        '<div style="background:image-set(&quot;images/f.png&quot; 1x)"></div>'
        '<a href="other.html">link</a><img src="data:image/png;base64,AA"></section>',
        "<div>not a slide</div>",
    ]
    refs = collect_refs(slides, ".x{background:url(images/g.png)} .y{background:url(https://x.example/h.png)}")
    assert refs["relative"] == {"images/a.png", "images/b.png", "images/c.png", "media/p.jpg",
                                "media/v.mp4", "docs/o.svg", "images/e.png", "images/f.png", "images/g.png"}
    assert refs["assets"] == {ICON}
    assert collect_refs([], None) == {"relative": set(), "assets": set()}


# ── slide scripts and libraries ──────────────────────────────────────────

JS_SLIDES = {
    "chart": ('<section data-layout="Title Only" data-libs="echarts"><div class="c"></div>'
              "<script>var x=1;</script></section>"),
    "chart-2": ('<section data-layout="Title Only" data-libs="ECharts echarts nope">'
                '<h1 data-ph="title">Two</h1>\n<div class="c"></div>\n'
                '<script type="text/javascript">\nvar y = "</div>";\n</script></section>'),
    "kept": ('<section data-layout="Title Only"><h1 data-ph="title">Kept</h1>'
             '<script src="js/x.js"></script><script type="module">export const m = 1;</script></section>'),
    "plain": '<section data-layout="Title Only"><h1 data-ph="title">Plain</h1></section>',
}


@pytest.fixture
def js_built(tmp_path: Path):
    deck = _make_deck(tmp_path, slides=JS_SLIDES)
    (deck / "js").mkdir()
    (deck / "js" / "x.js").write_text("window.embedded = 1;", encoding="utf-8")
    result = _assemble(deck, slides=JS_SLIDES)
    return deck, result, lxml_html.document_fromstring(result.html)


def _engine_scripts(doc) -> list[str]:
    return [s.text or "" for s in doc.xpath("//body/script")]


def test_slide_scripts_are_wrapped_and_emitted_in_order(js_built) -> None:
    from sdpm.engine.html.slide_js import SLIDE_HELPER, library_script, wrap_slide_script

    _, result, doc = js_built
    scripts = _engine_scripts(doc)
    assert len(scripts) == 7
    assert scripts[0] == inline_js((VENDOR_DIR / "revealjs" / "reveal.js").read_text(encoding="utf-8"))
    assert "RevealNotes" in scripts[1]
    assert scripts[2] == inline_js(library_script("echarts"))
    assert scripts[3] == SLIDE_HELPER
    assert scripts[4] == inline_js(wrap_slide_script("chart", "var x=1;"))
    assert scripts[4] == '__sdpmSlide("chart",function(section){\nvar x=1;\n});'
    assert scripts[5] == inline_js(wrap_slide_script("chart-2", '\nvar y = "</div>";\n'))
    assert "Reveal.initialize(o);" in scripts[6]
    assert result.slide_scripts == 2
    assert result.libraries == ["echarts"]
    for slug in ("chart", "chart-2", "plain"):
        assert not doc.xpath(f'//section[@data-slug="{slug}"]//script')


def test_declared_library_is_embedded_once_unmodified_with_its_notice(js_built) -> None:
    _, result, doc = js_built
    text = (VENDOR_DIR / "echarts" / "echarts.min.js").read_text(encoding="utf-8")
    assert inline_js(text) == text
    echarts = _engine_scripts(doc)[2]
    assert echarts.startswith("/*!\n")
    assert "Apache ECharts\nCopyright 2017-2026 The Apache Software Foundation" in echarts
    assert "Apache License" in echarts and "Mike Bostock" in echarts  # LICENSE + LICENSE-d3
    assert echarts.endswith(text)
    assert result.html.count(text) == 1
    d3 = (VENDOR_DIR / "d3" / "d3.min.js").read_text(encoding="utf-8")
    assert d3[:200] not in result.html


def test_other_scripts_stay_in_their_section_unembedded(js_built) -> None:
    from sdpm.engine.html.csp import script_hash

    _, result, doc = js_built
    kept = doc.xpath('//section[@data-slug="kept"]')[0]
    assert kept.xpath('.//script[@src="js/x.js"]')
    module = kept.xpath('.//script[@type="module"]')
    assert module and module[0].text == "export const m = 1;"
    assert "window.embedded" not in result.html and "data:text/javascript" not in result.html
    assert script_hash(module[0].text) not in result.html


def test_previews_never_contain_a_script(js_built) -> None:
    _, result, _ = js_built
    assert set(result.previews) == set(JS_SLIDES)
    for slug, text in result.previews.items():
        assert "<script" not in text.lower(), slug
    assert 'class="c"' in result.previews["chart"]


def test_line_map_covers_sections_and_slide_scripts(js_built) -> None:
    _, result, _ = js_built
    lines = result.html.split("\n")

    def ranges(slug: str) -> list[tuple[int, int]]:
        return [(start, end) for start, end, owner in result.line_map if owner == slug]

    for slug in JS_SLIDES:
        (start, end), *scripts = ranges(slug)
        assert start <= end
        assert any(f'data-slug="{slug}"' in lines[i - 1] for i in range(start, end + 1)), slug
        for s_start, s_end in scripts:
            assert any(f'__sdpmSlide("{slug}"' in lines[i - 1] for i in range(s_start, s_end + 1)), slug
    assert len(ranges("chart")) == len(ranges("chart-2")) == 2
    assert len(ranges("kept")) == len(ranges("plain")) == 1
    s_start, s_end = ranges("chart-2")[1]
    assert lines[s_start - 1].startswith('<script>__sdpmSlide("chart-2"')
    assert lines[s_end - 1] == "});</script>"
    covered = [n for start, end, _ in result.line_map for n in range(start, end + 1)]
    assert len(covered) == len(set(covered)) and max(covered) <= len(lines)


def test_deck_without_scripts_has_only_the_engine_scripts(built) -> None:
    _, result, doc = built
    assert len(_engine_scripts(doc)) == 3
    assert "__sdpmSlide" not in result.html and "echarts" not in result.html.lower()
    assert result.libraries == [] and result.slide_scripts == 0
    assert [owner for _, _, owner in result.line_map] == list(SLIDES)
