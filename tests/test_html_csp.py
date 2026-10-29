# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Content-Security-Policy of HTML decks (sdpm.engine.html.csp) and what it covers."""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

import pytest
from lxml import html as lxml_html

from sdpm import api
from sdpm.config import VENDOR_DIR
from sdpm.engine.html.csp import PREVIEW_CSP, deck_csp, script_hash, speaker_view_script

NOTES_JS = (VENDOR_DIR / "revealjs" / "plugin" / "notes.js").read_text(encoding="utf-8")
REVEAL_VERSION = (VENDOR_DIR / "revealjs" / "VERSION").read_text(encoding="utf-8").strip()
SPEAKER_VIEW_HASH_6_0_2 = "sha256-GzCveToXhSIzS3M5eQeRm3McVRB7cYneYKwTkzA3wDk="
_SCRIPT_RE = re.compile(r"<script>(.*?)</script>", re.DOTALL)


def _directives(policy: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for part in policy.split(";"):
        name, *sources = part.split()
        assert name not in out, f"duplicate directive {name}"
        out[name] = sources
    return out


def _deck(tmp_path: Path, slides: dict[str, str]) -> Path:
    deck = tmp_path / "deck"
    api.init("t", output_dir=deck, output_format="html")
    assert api.apply_style(deck, style="typographic", template="blank-light")["status"] == "ok"
    outline = "# CSP deck\n\n" + "".join(f"- [{slug}] {slug}\n" for slug in slides)
    (deck / "specs" / "outline.md").write_text(outline, encoding="utf-8")
    for slug, text in slides.items():
        (deck / "slides" / f"{slug}.html").write_text(text, encoding="utf-8")
    return deck


@pytest.fixture
def output_html(tmp_path: Path) -> str:
    deck = _deck(tmp_path, {
        "cover": '<section data-layout="Title Slide"><h1 data-ph="title">Hi</h1>'
                 '<aside class="notes">notes</aside></section>',
        "steps": '<section data-layout="Title Only"><h1 data-ph="title">Steps</h1>'
                 '<p class="fragment">one</p></section>',
    })
    api.generate_html(deck)
    return (deck / "output.html").read_text(encoding="utf-8")


def _policy_of(html: str) -> str:
    doc = lxml_html.document_fromstring(html)
    return doc.xpath('//meta[@http-equiv="Content-Security-Policy"]')[0].get("content")


# ── the policy ───────────────────────────────────────────────────────────

def test_deck_policy_structure() -> None:
    d = _directives(deck_csp(["sha256-a", "sha256-b"]))
    assert d["default-src"] == ["'none'"]
    assert d["script-src"] == ["'sha256-a'", "'sha256-b'"]
    assert d["style-src"] == ["'unsafe-inline'"]  # no 'self', scheme or host: linked CSS never loads
    for name in ("img-src", "font-src", "media-src"):
        assert d[name] == ["data:"]
    assert d["connect-src"] == ["'none'"]
    assert d["frame-src"] == ["'self'"]  # speaker-view receivers; no data:, blob: or *
    assert d["object-src"] == ["'none'"]
    assert d["base-uri"] == ["'none'"] and d["form-action"] == ["'none'"]


def test_deck_policy_needs_hash_sources() -> None:
    with pytest.raises(ValueError):
        deck_csp([])
    with pytest.raises(ValueError):
        deck_csp(["unsafe-inline"])


def test_preview_policy_runs_nothing() -> None:
    d = _directives(PREVIEW_CSP)
    assert d["script-src"] == ["'none'"] and d["frame-src"] == ["'none'"]
    assert d["default-src"] == ["'none'"] and d["object-src"] == ["'none'"]
    assert d["img-src"] == ["data:"] and d["style-src"] == ["'unsafe-inline'"]


def test_script_hash_normalises_line_breaks() -> None:
    expected = "sha256-" + base64.b64encode(hashlib.sha256(b"a\nb\nc").digest()).decode()
    assert script_hash("a\r\nb\rc") == script_hash("a\nb\nc") == expected


# ── output.html ──────────────────────────────────────────────────────────

def test_csp_meta_follows_charset_then_referrer(output_html: str) -> None:
    head = output_html.split("<head>", 1)[1].lstrip("\n").splitlines()
    assert head[0] == '<meta charset="utf-8">'
    assert head[1].startswith('<meta http-equiv="Content-Security-Policy" content="')
    assert head[2] == '<meta name="referrer" content="no-referrer">'
    assert output_html.index("Content-Security-Policy") < output_html.index("<style")


def test_emitted_policy_lists_only_hashes(output_html: str) -> None:
    d = _directives(_policy_of(output_html))
    assert d["script-src"] and all(re.fullmatch(r"'sha256-[A-Za-z0-9+/]+={0,2}'", s) for s in d["script-src"])
    for banned in ("'unsafe-inline'", "'unsafe-hashes'", "'strict-dynamic'", "'unsafe-eval'", "*", "data:"):
        assert banned not in d["script-src"]
    assert d["frame-src"] == ["'self'"] and d["style-src"] == ["'unsafe-inline'"]


def test_every_emitted_script_and_the_speaker_view_are_hashed(output_html: str) -> None:
    sources = set(_directives(_policy_of(output_html))["script-src"])
    scripts = _SCRIPT_RE.findall(output_html)
    assert len(scripts) == 3
    for text in scripts:
        digest = base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode()
        assert f"'sha256-{digest}'" in sources
    assert f"'{script_hash(speaker_view_script(NOTES_JS))}'" in sources
    assert len(sources) == 4


@pytest.mark.skipif(REVEAL_VERSION != "6.0.2", reason="hash pinned for the vendored reveal.js 6.0.2")
def test_speaker_view_hash_of_vendored_reveal() -> None:
    assert script_hash(speaker_view_script(NOTES_JS)) == SPEAKER_VIEW_HASH_6_0_2


def test_notes_js_shape_guard() -> None:
    # A reveal.js upgrade that changes the speaker view's shape fails here, not in the browser.
    assert NOTES_JS.count(".document.write(`") == 1
    start = NOTES_JS.index(".document.write(`") + len(".document.write(`")
    assert "${" not in NOTES_JS[start:NOTES_JS.index("`", start)]
    body = speaker_view_script(NOTES_JS)
    assert body.strip() and "<script" not in body.lower()


@pytest.mark.parametrize("notes_js, message", [
    ("x.document.write(`<script>a</script>`);y.document.write(`b`)", "exactly one"),
    ("no write here", "exactly one"),
    ("t.document.write(`<p>${x}</p><script>a</script>`)", r"\$\{"),
    ("t.document.write(`<p>no script</p>`)", "exactly one <script>"),
    ("t.document.write(`<script>a</script><script>b</script>`)", "exactly one <script>"),
    ("t.document.write(`<script>a</script>", "not closed"),
])
def test_speaker_view_script_rejects_unexpected_shapes(notes_js: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        speaker_view_script(notes_js)


def test_speaker_view_script_cooks_js_escapes() -> None:
    js = r"t.document.write(`<script>a\xA0b\u00e9\\c\/d\`e\n\tf\qg</script>`)"
    assert speaker_view_script(js) == "a\xa0b\u00e9\\c/d`e\n\tfqg"


def test_config_script_handles_receivers_and_print_through_the_fragment(output_html: str) -> None:
    config = _SCRIPT_RE.findall(output_html)[2]
    assert "o.url=location.href.split('#')[0]+'#sdpm-receiver'" in config
    assert ("receiver|progress|history|transition|autoSlide|backgroundTransition|"
            "scrollActivationWidth|postMessageEvents|controls") in config
    assert "o.keyboard={83:null}" in config
    assert "print-pdf" in config and "o.view='print'" in config
    assert "Reveal.initialize(o);" in config


def test_vendored_files_are_embedded_unmodified(output_html: str) -> None:
    from sdpm.engine.html.assemble import inline_js

    scripts = _SCRIPT_RE.findall(output_html)
    assert scripts[0] == inline_js((VENDOR_DIR / "revealjs" / "reveal.js").read_text(encoding="utf-8"))
    assert scripts[1].endswith(inline_js(NOTES_JS))


# ── phase 1 leftovers: kept in the file, blocked by the CSP, reported by the checks ──

_HOSTILE = {
    "link-external": ('<link rel="stylesheet" href="https://example.com/x.css">', "external-url"),
    "link-data": ('<link rel="stylesheet" href="data:text/css,h1{color:red}">', "external-url"),
    "iframe-data": ('<iframe src="data:text/html,hi"></iframe>', "script"),
    "embed": ('<embed src="data:text/html,embed">', "script"),
    "object-data": ('<object data="data:text/html,object"></object>', "script"),
    "img-external": ('<img src="https://example.com/pixel.png">', "external-url"),
    "onerror": ('<img src="data:image/png;base64,AA" onerror="window.x=1">', "script"),
    "animate-values": ('<svg><a><animate attributeName="href" values="0;javascript:window.x=1"/>'
                       "<text>t</text></a></svg>", "script"),
    "use-href": ('<svg><use href="images/s.svg#a"/></svg>', "external-use"),
    "meta-refresh": ('<meta http-equiv="refresh" content="0;url=https://example.com/">', "script"),
}


def test_hostile_constructs_are_kept_and_reported(tmp_path: Path) -> None:
    slides = {slug: f'<section data-layout="Blank"><h1>{slug}</h1>{inner}</section>'
              for slug, (inner, _) in _HOSTILE.items()}
    deck = _deck(tmp_path, slides)
    result = api.generate_html(deck)
    html = (deck / "output.html").read_text(encoding="utf-8")
    assert result["slide_count"] == len(_HOSTILE)
    doc = lxml_html.document_fromstring(html)
    csp_at = html.index('http-equiv="Content-Security-Policy"')
    present = {
        "link-external": '//link[@href="https://example.com/x.css"]',
        "link-data": '//link[starts-with(@href, "data:text/css")]',
        "iframe-data": '//iframe[starts-with(@src, "data:text/html")]',
        "embed": '//embed[starts-with(@src, "data:text/html")]',
        "object-data": '//object[starts-with(@data, "data:text/html")]',
        "img-external": '//img[@src="https://example.com/pixel.png"]',
        "onerror": "//img[@onerror]",
        "animate-values": '//animate[contains(@values, "javascript:")]',
        "use-href": '//use[@href="images/s.svg#a"]',
        "meta-refresh": '//meta[@http-equiv="refresh"]',
    }
    for slug, xpath in present.items():
        section = doc.xpath(f'//section[@data-slug="{slug}"]')[0]
        assert section.xpath("." + xpath), f"{slug}: construct stripped"
        assert csp_at < html.index(f'data-slug="{slug}"')
    rules = {(d["slug"], d["rule"]) for d in result["diagnostics"]}
    for slug, (_, rule) in _HOSTILE.items():
        assert (slug, rule) in rules, f"{slug}: {rule} not reported"
