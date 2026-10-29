# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""sdpm.api.generate_html / refresh_html (HTML deck facade)."""

from __future__ import annotations

import base64
import re
import shutil
from pathlib import Path

import pytest

import sdpm.config
from conftest import DECORATED_BAND_RGB
from sdpm import api
from sdpm.engine.html import decorations
from sdpm.engine.preview.environment import soffice_path

_needs_lo = pytest.mark.skipif(
    soffice_path() is None or shutil.which("pdftocairo") is None,
    reason="LibreOffice and poppler (pdftocairo) required",
)

SLIDES = {
    "cover": '<section data-layout="Title Slide"><h1 data-ph="title">Hi</h1></section>',
    "body": ('<section data-layout="Title Only"><h1 data-ph="title">Claim</h1>'
             '<p style="font-size:24px">raw size</p></section>'),
    "gone": None,  # listed in the outline, no file
}


def _deck(tmp_path: Path, template: str = "blank-light", slides=None) -> Path:
    deck = tmp_path / "deck"
    api.init("t", output_dir=deck, output_format="html")
    assert api.apply_style(deck, style="typographic", template=template)["status"] == "ok"
    slides = SLIDES if slides is None else slides
    outline = "# API deck\n\n" + "".join(f"- [{slug}] {slug}\n" for slug in slides)
    (deck / "specs" / "outline.md").write_text(outline, encoding="utf-8")
    for slug, text in slides.items():
        if text is not None:
            (deck / "slides" / f"{slug}.html").write_text(text, encoding="utf-8")
    return deck


@pytest.mark.parametrize("template", ["blank-light", "blank-dark"])
def test_generate_html_bundled_templates_without_libreoffice(tmp_path, monkeypatch, template) -> None:
    monkeypatch.setattr(decorations, "soffice_path", lambda: None)
    deck = _deck(tmp_path, template)
    result = api.generate_html(deck)
    out = deck / "output.html"
    assert result["output_path"] == str(out) and out.is_file()
    assert result["bytes"] == out.stat().st_size
    assert result["slide_count"] == 2
    assert result["slides"] == ["page01 - cover", "page02 - body"]
    assert result["layouts_used"] == ["Title Slide", "Title Only"]
    assert "decorations" not in result  # bundled artifacts include the decoration SVGs
    text = out.read_text(encoding="utf-8")
    assert text.count('{background-image:url("data:image/svg+xml;base64,') == 2
    assert "<title>API deck</title>" in text


def test_generate_html_warnings_and_diagnostics(tmp_path) -> None:
    result = api.generate_html(_deck(tmp_path))
    assert "slides/gone.html missing — skipped" in result["warnings"]
    assert any(w.startswith("body: ") and "font-size" in w for w in result["warnings"])
    assert [(d["slug"], d["rule"]) for d in result["diagnostics"]] == [("body", "font-size-token")]


def test_generate_html_custom_output_path(tmp_path) -> None:
    deck = _deck(tmp_path)
    out = tmp_path / "elsewhere" / "deck.html"
    assert api.generate_html(deck, out)["output_path"] == str(out)
    assert out.is_file() and not (deck / "output.html").exists()


def test_generate_html_rejects_pptx_deck(tmp_path) -> None:
    deck = tmp_path / "pptx"
    api.init("t", output_dir=deck)
    with pytest.raises(ValueError, match="PPTX deck"):
        api.generate_html(deck)


def test_deck_css_embedded_once_and_checked(tmp_path) -> None:
    deck = _deck(tmp_path)
    css = ".card { font-size: 24px; background: url(http://example.com/a.png); }\n:root { --x: 1; }"
    (deck / "deck.css").write_text(css, encoding="utf-8")
    result = api.generate_html(deck)
    text = (deck / "output.html").read_text(encoding="utf-8")
    assert text.count(".card { font-size: 24px;") == 1
    assert re.search(r'<style id="sdpm-deck-css">\.card \{', text)
    deck_warnings = [w for w in result["warnings"] if w.startswith("deck.css: ")]
    assert len(deck_warnings) == 3
    rules = {d["rule"] for d in result["diagnostics"] if d["slug"] == "(deck.css)"}
    assert rules == {"font-size-token", "external-url", "root-in-deck-css"}


def test_refresh_html_without_measure(tmp_path) -> None:
    deck = _deck(tmp_path)
    result = api.refresh_html(deck, ["slides/body.html", "slides/body.json"])
    assert set(result) == {"html", "html_bytes", "warnings", "affected"}
    assert result["html"] == str(deck / "output.html")
    assert result["affected"] == ["body"]
    assert api.refresh_html(deck, ["deck.css"])["affected"] == ["cover", "body"]
    assert api.refresh_html(deck)["affected"] == []


def test_refresh_html_with_measure_filters_warnings(tmp_path) -> None:
    deck = _deck(tmp_path)
    (deck / "deck.css").write_text(":root { --x: 1; }", encoding="utf-8")
    result = api.refresh_html(deck, ["slides/cover.html"], measure_slides=["cover"])
    assert set(result) == {"html", "html_bytes", "warnings", "affected", "measure", "preview"}
    assert result["warnings"] == [w for w in result["warnings"] if w.startswith("deck.css: ")]
    assert len(result["warnings"]) == 1  # deck.css always reported; body / gone filtered out
    assert "cover: OK" in result["measure"] and "(deck.css): 1 issue(s)" in result["measure"]
    assert result["preview"]["reason"] == "html-deck"

    body = api.refresh_html(deck, measure_slides=["body"])
    assert any(w.startswith("body: ") for w in body["warnings"])
    assert "[font-size-token]" in body["measure"]


def test_refresh_html_never_raises(tmp_path) -> None:
    deck = tmp_path / "pptx"
    api.init("t", output_dir=deck)
    result = api.refresh_html(deck, ["deck.json"])
    assert set(result) == {"html_error"} and "PPTX deck" in result["html_error"]


@_needs_lo
def test_decorated_template_gets_its_decoration_background(tmp_path, monkeypatch, decorated_template) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    shutil.copy(decorated_template, templates / "decorated.pptx")
    monkeypatch.setenv("SDPM_TEMPLATES_DIR", str(templates))
    monkeypatch.setattr(sdpm.config, "CACHE_DIR", tmp_path / "cache")
    deck = _deck(tmp_path, "decorated", {"head": SLIDES["body"]})
    result = api.generate_html(deck)
    assert "decorations" not in result and result["layouts_used"] == ["Title Only"]
    text = (deck / "output.html").read_text(encoding="utf-8")
    b64 = re.search(r'section\[data-layout="Title Only"\]\{background-image:url\("data:image/svg\+xml;base64,'
                    r'([A-Za-z0-9+/=]+)"\)\}', text).group(1)
    svg = base64.b64decode(b64).decode("utf-8")
    fills = [tuple(float(c) * 255 / 100 for c in m)
             for m in re.findall(r"rgb\(([\d.]+)%, ([\d.]+)%, ([\d.]+)%\)", svg)]
    assert any(all(abs(c - t) <= 1 for c, t in zip(fill, DECORATED_BAND_RGB)) for fill in fills)
    assert "<image" in svg  # master logo
