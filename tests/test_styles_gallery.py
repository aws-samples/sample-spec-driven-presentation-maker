# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The local browser style gallery (list_styles) draws referenced catalog icons."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from sdpm.knowledge.reference import generate_styles_index

ICON = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0h24"/></svg>'


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
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
    return f"<html><head><title>{title}</title></head><body>\n{body}\n</body></html>"


def test_gallery_shows_display_copies(env: Path) -> None:
    user, bundled = env / "user", env / "bundled"
    user.mkdir()
    bundled.mkdir()
    referencing = _style("a — uses an icon", '<div class="slide"><svg class="icon"><use href="#t/x"/></svg></div>')
    (user / "a.html").write_text(referencing)
    (bundled / "a.html").write_text(_style("a — shadowed", ""))
    (bundled / "b.html").write_text(_style("b — no icons", '<div class="slide">b</div>'))
    copies = env / "tmp" / "sdpm-styles-gallery"
    copies.mkdir()
    (copies / "stale.html").write_text("old")

    index = generate_styles_index([user, bundled]).read_text()

    copy = copies / "a.html"
    assert copy.as_uri() in index
    assert '<symbol id="t/x" viewBox="0 0 24 24">' in copy.read_text()
    assert (user / "a.html").read_text() == referencing
    # nothing to draw: the gallery shows the style's own file
    assert (bundled / "b.html").resolve().as_uri() in index
    assert not (copies / "b.html").exists()
    assert not (copies / "stale.html").exists()
    assert "shadowed" not in index
