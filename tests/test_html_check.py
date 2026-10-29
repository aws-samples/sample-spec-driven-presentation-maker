# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Browser-free static checks for HTML decks (sdpm.engine.html.check)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sdpm.engine.html.check import (
    check_deck_css,
    check_html_font_sizes,
    check_slide_html,
    format_check_report,
    html_preview_unavailable,
)

LAYOUTS = {"Title Slide", "Title Only", "Blank"}
CHROME_KEYS = {"10", "11", "12"}

CLEAN = (
    '<section data-layout="Title Only" data-auto-animate>\n'
    "  <style>.k { font-size: calc(var(--fs-body) * var(--sdpm-pt-scale)); }</style>\n"
    '  <h1 data-ph="title">Claim</h1>\n'
    '  <div data-region="body" data-id="b" style="left:96px;top:210px;width:1728px;height:640px">\n'
    '    <img src="assets:aws/Arch_AWS-Lambda_48" alt="Lambda">\n'
    '    <img src="images/chart.png" alt="chart">\n'
    '    <p class="fragment">See <a href="https://example.com/docs">the docs</a></p>\n'
    "  </div>\n"
    '  <aside class="notes">Details at https://example.com</aside>\n'
    "</section>\n"
)


def _rules(text: str) -> list[str]:
    return [d["rule"] for d in check_slide_html("s", text, layouts=LAYOUTS, chrome_keys=CHROME_KEYS)]


def _section(inner: str, attrs: str = 'data-layout="Blank"') -> str:
    return f"<section {attrs}>{inner}</section>"


@pytest.fixture
def art_direction(tmp_path: Path) -> Path:
    path = tmp_path / "art-direction.html"
    path.write_text("<style>:root{--color-text:#111; --fs-body: 24pt; --fs-title: 40pt;}</style>",
                    encoding="utf-8")
    return path


def test_clean_slide_has_no_diagnostics() -> None:
    assert _rules(CLEAN) == []


@pytest.mark.parametrize("text", [
    "<div>no section</div>",
    "<section data-layout='Blank'></section><section data-layout='Blank'></section>",
    "<section data-layout='Blank'></section><p>outside</p>",
    _section("<section>vertical</section>"),
    "",
])
def test_structure(text: str) -> None:
    assert "structure" in _rules(text)


def test_layout_missing_and_unknown() -> None:
    assert _rules("<section><h1>x</h1></section>") == ["layout-missing"]
    diags = check_slide_html("s", _section("", 'data-layout="Nope"'), layouts=LAYOUTS)
    assert [d["rule"] for d in diags] == ["layout-unknown"]
    assert "'Blank'" in diags[0]["message"]


@pytest.mark.parametrize("inner", [
    "<script>alert(1)</script>",
    '<div onclick="go()">x</div>',
    '<svg><rect onload="go()"/></svg>',
    '<a href="javascript:go()">x</a>',
    '<div style="background:url(javascript:go())"></div>',
])
def test_script(inner: str) -> None:
    assert "script" in _rules(_section(inner))


@pytest.mark.parametrize("inner", [
    '<img src="https://example.com/a.png">',
    '<img src="//cdn.example.com/a.png">',
    '<img srcset="a.png 1x, https://example.com/b.png 2x">',
    '<link rel="stylesheet" href="https://example.com/a.css">',
    '<video poster="http://example.com/p.jpg"></video>',
    '<object data="https://example.com/x.svg"></object>',
    '<svg><use xlink:href="https://example.com/s.svg#i"/></svg>',
    '<div style="background:url(https://example.com/a.png)"></div>',
    "<style>.x{background:url('https://example.com/a.png')}</style>",
    "<style>@import url(https://fonts.example.com/f.css);</style>",
    "<style>@import 'local.css';</style>",
])
def test_external_url(inner: str) -> None:
    assert "external-url" in _rules(_section(inner))


def test_anchor_href_and_fragment_refs_are_allowed() -> None:
    inner = ('<a href="https://example.com">link</a><svg><use href="#icon"/></svg>'
             '<img src="data:image/png;base64,AAAA">')
    assert _rules(_section(inner)) == []


def test_data_background() -> None:
    assert _rules(_section("", 'data-layout="Blank" data-background-color="#000"')) == ["data-background"]
    assert "data-background" in _rules(_section('<div data-background-image="a.png"></div>'))


@pytest.mark.parametrize("inner", [
    '<div data-ph="12">3</div>',
    '<div data-ph="sldNum">3</div>',
    "<footer>© Example</footer>",
    '<div class="page-number">3</div>',
    '<span id="slide-number">3</span>',
    '<div class="footer">© Example</div>',
])
def test_self_chrome(inner: str) -> None:
    assert "self-chrome" in _rules(_section(inner))


def test_component_class_containing_footer_is_not_chrome() -> None:
    assert _rules(_section('<div class="card-footer">x</div>')) == []


def test_root_in_slide_style() -> None:
    assert _rules(_section("<style>:root{--accent:red}</style>")) == ["root-in-slide-style"]


def test_author_data_slug() -> None:
    assert _rules(_section("", 'data-layout="Blank" data-slug="x"')) == ["data-slug"]


def test_font_size_lint(art_direction: Path) -> None:
    slides = {
        "raw": _section('<p style="font-size:24px">x</p>'),
        "unknown": _section("<style>p { font-size: var(--fs-nope); }</style><p>x</p>"),
        "shorthand": _section('<p style="font: 700 2em/1.2 serif">x</p>'),
        "ok": _section('<p style="font-size:calc(var(--fs-body) * var(--sdpm-pt-scale))">x</p>'
                       "<style>h2 { font: 700 calc(var(--fs-title) * var(--sdpm-pt-scale))/1.1 serif; "
                       "font-family: serif; }</style>"),
    }
    diags = check_html_font_sizes(slides, art_direction)
    assert [(d["slug"], d["rule"]) for d in diags] == [
        ("raw", "font-size-token"),
        ("unknown", "font-size-unknown-token"),
        ("shorthand", "font-size-token"),
    ]


def test_font_size_lint_skipped_without_tokens(tmp_path: Path) -> None:
    slides = {"raw": _section('<p style="font-size:24px">x</p>')}
    assert check_html_font_sizes(slides, tmp_path / "missing.html") == []
    plain = tmp_path / "plain.html"
    plain.write_text("<style>:root{--color-text:#111}</style>", encoding="utf-8")
    assert check_html_font_sizes(slides, plain) == []


def test_deck_css_checks(art_direction: Path) -> None:
    css = (
        ".card { font-size: 24px; }\n"
        ".ok { font-size: calc(var(--fs-body) * var(--sdpm-pt-scale)); }\n"
        ".bg { background: url(https://example.com/a.png); }\n"
        ":root { --accent: red; }\n"
        ".x { width: expression(alert(1)); }\n"
    )
    diags = check_deck_css(css, art_direction)
    assert {d["slug"] for d in diags} == {"(deck.css)"}
    assert sorted(d["rule"] for d in diags) == [
        "external-url", "font-size-token", "root-in-deck-css", "script"]
    clean = ".card { font-size: calc(var(--fs-title) * var(--sdpm-pt-scale)); background: url(images/a.png); }"
    assert check_deck_css(clean, art_direction) == []


def test_preview_unavailable_shape(tmp_path: Path) -> None:
    result = html_preview_unavailable(tmp_path / "output.html")
    assert result["status"] == "unavailable" and result["reason"] == "html-deck"
    assert result["open"] == str(tmp_path / "output.html")
    assert "browser" in result["note"]


def test_format_check_report() -> None:
    diags = [{"slug": "a", "rule": "script", "message": "no"},
             {"slug": "(deck.css)", "rule": "root-in-deck-css", "message": "root"}]
    report = format_check_report(diags, ["a", "b"])
    assert "(deck.css): 1 issue(s)" in report and "a: 1 issue(s)" in report and "b: OK" in report
    assert "[script] no" in report
    assert "no issues" in format_check_report([])
