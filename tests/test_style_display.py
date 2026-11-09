# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A style cut into the parts a viewer shows one slide at a time, and styles read by name.

``style_display_parts`` is the Web UI's ``splitStyleSlides`` rule
(web-ui/src/components/StyleSlidePreview.tsx); the MCP Apps style gallery uses it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdpm.api import read_style_htmls
from sdpm.knowledge.assets.style_icons import inline_style_icons
from sdpm.knowledge.reference import BUNDLED_STYLES_DIR, is_style_name, style_display_parts

ICON = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0h24"/></svg>'
BUNDLED = sorted(BUNDLED_STYLES_DIR.glob("*.html"))


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """An isolated user config dir with a one-icon catalog source ``t``."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    source = tmp_path / "cfg" / "sdpm" / "assets" / "t"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text(json.dumps(
        {"source": "t", "icons": [{"name": "X", "file": "x.svg", "category": "c", "type": "icon"}]}))
    (source / "x.svg").write_bytes(ICON)
    from sdpm.knowledge.assets import invalidate_manifest_cache
    invalidate_manifest_cache()
    yield tmp_path
    invalidate_manifest_cache()


def _style(title: str, body: str) -> str:
    return f"<html><head><title>{title}</title><style>.slide{{}}</style></head><body>\n{body}\n</body></html>"


@pytest.mark.parametrize("path", BUNDLED, ids=[p.stem for p in BUNDLED])
def test_every_bundled_style_cuts_into_its_slides(path: Path) -> None:
    html = path.read_text(encoding="utf-8")
    parts = style_display_parts(html)
    assert "whole" not in parts
    assert len(parts["slides"]) == html.count('<div class="slide')
    assert parts["slides"][0].startswith('<div class="slide')
    assert "<style" in parts["head"]
    assert all("</body>" not in s for s in parts["slides"])


def test_the_first_slide_is_the_cover() -> None:
    html = _style("x — y", '<div class="slide cover">A</div>\n<div class="slide">B</div>\n</div>')
    parts = style_display_parts(html)
    # trailing closing tags go (the browser closes the slide), as in the Web UI
    assert parts["slides"] == ['<div class="slide cover">A', '<div class="slide">B']
    assert parts["head"] == "<title>x — y</title><style>.slide{}</style>"
    assert parts["prelude"] == ""


def test_the_prelude_is_the_icon_sprite(env: Path) -> None:
    html = _style("a — icons", '<svg class="deco"></svg>\n<div class="slide"><svg class="icon"><use href="#t/x"/></svg></div>')
    shown = inline_style_icons(html)
    parts = style_display_parts(shown)
    assert parts["prelude"].startswith("<svg") and "data-sdpm-icons" in parts["prelude"]
    assert '<symbol id="t/x" viewBox="0 0 24 24">' in parts["prelude"]
    assert 'class="deco"' not in parts["prelude"]  # an svg without symbols is not a sprite


def test_a_document_without_slides_comes_back_whole() -> None:
    html = "<html><body><p>no slides</p></body></html>"
    assert style_display_parts(html) == {"head": "", "prelude": "", "slides": [html], "whole": True}


def test_style_names() -> None:
    assert is_style_name("aws-light") and is_style_name("my_style2")
    for bad in ("", "../x", "a/b", "a.html", "a b", None, 3):
        assert not is_style_name(bad)


def test_read_style_htmls_user_first_and_leaves_out_the_rest(env: Path) -> None:
    user, bundled = env / "user", env / "bundled"
    user.mkdir()
    bundled.mkdir()
    (user / "a.html").write_text(_style("a — mine", ""))
    (bundled / "a.html").write_text(_style("a — shadowed", ""))
    (bundled / "b.html").write_text(_style("b — bundled", ""))
    (env / "secret.html").write_text("outside")

    got = read_style_htmls(["a", "b", "../secret", "nope", "a"], [user, bundled])

    assert set(got) == {"a", "b"}
    assert "mine" in got["a"] and "bundled" in got["b"]


def test_read_style_htmls_defaults_to_the_styles_dirs(env: Path) -> None:
    got = read_style_htmls(["report"])
    assert got["report"] == (BUNDLED_STYLES_DIR / "report.html").read_text(encoding="utf-8")
