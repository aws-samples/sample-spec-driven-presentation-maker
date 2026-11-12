# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Display-time icon drawing for style HTML (sdpm.knowledge.assets.style_icons)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdpm.knowledge.assets import style_icons
from sdpm.knowledge.assets.style_icons import (
    icon_symbol,
    inline_style_icons,
    inline_style_icons_many,
    missing_icon_ids,
)

HUB = b'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 -960 960 960"><path d="M1 1h2"/></svg>'
AWS = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">'
    b'<g clip-path="url(#g)"><rect width="64" height="64" fill="#8C4FFF"/></g>'
    b'<defs><clipPath id="g"><rect width="64" height="64"/></clipPath></defs></svg>'
)


def _doc(body: str) -> str:
    return f"<html><head><title>t</title></head><body>\n{body}\n</body></html>"


class _Loader:
    def __init__(self, icons: dict[str, bytes]) -> None:
        self.icons = icons
        self.calls: list[set[str]] = []

    def __call__(self, ids: set[str]) -> dict[str, bytes]:
        self.calls.append(set(ids))
        return {i: self.icons[i] for i in ids if i in self.icons}


def test_inserts_symbol_right_after_body() -> None:
    html = _doc('<div class="slide"><svg class="icon"><use href="#material/hub"/></svg></div>')
    out = inline_style_icons(html, _Loader({"material/hub": HUB}))
    head, rest = out.split("<body>", 1)
    assert head == html.split("<body>", 1)[0]
    assert rest.startswith('\n<svg width="0" height="0" style="position:absolute" aria-hidden="true" data-sdpm-icons>'
                           '<symbol id="material/hub" viewBox="0 -960 960 960">')
    assert rest.count("<symbol") == 1
    assert out.endswith(html.split("<body>", 1)[1])


def test_defined_symbol_is_used_as_is() -> None:
    html = _doc('<svg width="0" height="0"><symbol id="material/hub" viewBox="0 0 1 1"><path d="x"/></symbol></svg>'
                '<div class="slide"><svg><use href="#material/hub"/></svg></div>')
    loader = _Loader({"material/hub": HUB})
    assert inline_style_icons(html, loader) == html
    assert loader.calls == []


def test_unknown_id_leaves_html_unchanged() -> None:
    html = _doc('<div class="slide"><svg><use href="#material/nope"/></svg></div>')
    loader = _Loader({})
    assert inline_style_icons(html, loader) == html
    assert loader.calls == [{"material/nope"}]


def test_no_use_does_not_call_loader() -> None:
    html = _doc('<div class="slide">text</div>')
    loader = _Loader({"material/hub": HUB})
    assert inline_style_icons(html, loader) == html
    assert loader.calls == []


def test_batch_calls_loader_once_with_union() -> None:
    a = _doc('<svg><use href="#material/hub"/></svg>')
    b = _doc('<svg><use xlink:href="#aws/Arch_X_48"/></svg><svg><use href="#material/hub"/></svg>')
    c = _doc("plain")
    loader = _Loader({"material/hub": HUB, "aws/Arch_X_48": AWS})
    out = inline_style_icons_many([a, b, c], loader)
    assert loader.calls == [{"material/hub", "aws/Arch_X_48"}]
    assert out[0].count("<symbol") == 1
    assert out[1].count("<symbol") == 2
    assert out[2] == c


@pytest.mark.parametrize("ref", ["../x", "a/../b", "local", "a/b/c", "/abs", "a/.hidden"])
def test_malformed_ids_never_reach_loader(ref: str) -> None:
    html = _doc(f'<svg><use href="#{ref}"/></svg>')
    loader = _Loader({})
    assert inline_style_icons(html, loader) == html
    assert loader.calls == []
    assert missing_icon_ids(html) == []


def test_root_presentation_attrs_and_viewbox_carry_over() -> None:
    sym = icon_symbol("aws/Arch_X_48", AWS)
    assert sym is not None
    assert sym.startswith('<symbol id="aws/Arch_X_48" viewBox="0 0 64 64" fill="none">')
    assert 'width="64" height="64" viewBox' not in sym.split(">", 1)[0]
    assert "xmlns" not in sym


def test_view_box_from_size_when_missing() -> None:
    sym = icon_symbol("t/x", b'<svg xmlns="http://www.w3.org/2000/svg" width="24px" height="20"><path d="M0 0"/></svg>')
    assert sym is not None and 'viewBox="0 0 24 20"' in sym


def test_internal_ids_are_prefixed_consistently() -> None:
    sym = icon_symbol("aws/Arch_X_48", AWS)
    assert sym is not None
    assert 'clip-path="url(#aws/Arch_X_48--g)"' in sym
    assert 'id="aws/Arch_X_48--g"' in sym
    assert 'id="g"' not in sym


def test_scripts_and_handlers_are_stripped() -> None:
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 1 1" onload="x()">'
           b'<script>alert(1)</script><foreignObject><div/></foreignObject>'
           b'<a href="https://example.com" xlink:href="javascript:x()"><path d="M0 0" onclick="y()"/></a></svg>')
    sym = icon_symbol("t/x", svg)
    assert sym is not None
    for bad in ("script", "foreignObject", "onload", "onclick", "example.com", "javascript"):
        assert bad not in sym


def test_non_svg_is_rejected() -> None:
    assert icon_symbol("t/x", b"not xml") is None
    assert icon_symbol("t/x", b"<html/>") is None


def test_sprite_goes_before_first_slide_without_body() -> None:
    html = '<style>x</style><div class="slide"><svg><use href="#material/hub"/></svg></div>'
    out = inline_style_icons(html, _Loader({"material/hub": HUB}))
    assert out.startswith('<style>x</style><svg width="0"')
    assert out.endswith(html.split("</style>", 1)[1])


@pytest.fixture
def isolated_user_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from sdpm.knowledge.assets import invalidate_manifest_cache
    invalidate_manifest_cache()
    yield tmp_path / "sdpm"
    invalidate_manifest_cache()


def test_default_loader_reads_the_catalog(isolated_user_config: Path) -> None:
    source = isolated_user_config / "assets" / "tcat"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text(json.dumps(
        {"source": "tcat", "icons": [{"name": "Hub", "file": "hub.svg", "category": "x", "type": "icon"}]}))
    (source / "hub.svg").write_bytes(HUB)
    assert style_icons.load_catalog_icons({"tcat/hub", "tcat/missing"}) == {"tcat/hub": HUB}
    out = inline_style_icons(_doc('<svg><use href="#tcat/hub"/></svg>'))
    assert '<symbol id="tcat/hub" viewBox="0 -960 960 960"><path d="M1 1h2"/></symbol>' in out
