# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for style directory resolution and merged listing."""

import os
from pathlib import Path

import pytest

from sdpm.api import _find_style_in_dirs, get_styles_dirs
from sdpm.reference import BUNDLED_STYLES_DIR, list_styles, list_styles_merged


@pytest.fixture
def temp_styles_dir(tmp_path: Path) -> Path:
    d = tmp_path / "styles"
    d.mkdir()
    (d / "elegant-dark.html").write_text("<html><head><title>Elegant Dark — dark theme</title></head></html>")
    (d / "custom-brand.html").write_text("<html><head><title>Custom Brand — my company</title></head></html>")
    return d


# ---------------------------------------------------------------------------
# get_styles_dirs
# ---------------------------------------------------------------------------


def test_styles_dir_includes_bundled() -> None:
    dirs = get_styles_dirs()
    assert BUNDLED_STYLES_DIR in dirs


def test_styles_dir_respects_env(
    monkeypatch: pytest.MonkeyPatch, temp_styles_dir: Path
) -> None:
    monkeypatch.setenv("SDPM_STYLES_DIR", str(temp_styles_dir))
    dirs = get_styles_dirs()
    assert dirs[0] == temp_styles_dir


def test_styles_dir_includes_user_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """User-local styles dir appears between env override and bundled."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SDPM_STYLES_DIR", raising=False)
    dirs = get_styles_dirs()
    assert dirs[0] == tmp_path / "sdpm" / "styles"
    assert dirs[-1] == BUNDLED_STYLES_DIR


def test_styles_dir_supports_multiple_env_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    monkeypatch.setenv("SDPM_STYLES_DIR", f"{d1}{os.pathsep}{d2}")
    dirs = get_styles_dirs()
    assert dirs[0] == d1
    assert dirs[1] == d2


# ---------------------------------------------------------------------------
# _find_style_in_dirs
# ---------------------------------------------------------------------------


def test_find_style_accepts_name_with_or_without_extension(temp_styles_dir: Path) -> None:
    assert _find_style_in_dirs("elegant-dark", [temp_styles_dir]) == temp_styles_dir / "elegant-dark.html"
    assert _find_style_in_dirs("elegant-dark.html", [temp_styles_dir]) == temp_styles_dir / "elegant-dark.html"


def test_find_style_first_match_wins(tmp_path: Path) -> None:
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    (d1 / "shared.html").write_text("d1")
    (d2 / "shared.html").write_text("d2")
    found = _find_style_in_dirs("shared", [d1, d2])
    assert found == d1 / "shared.html"


def test_find_style_returns_none_when_missing(tmp_path: Path) -> None:
    assert _find_style_in_dirs("missing", [tmp_path]) is None


# ---------------------------------------------------------------------------
# list_styles_merged
# ---------------------------------------------------------------------------


def test_list_styles_merged_combines_dirs(tmp_path: Path) -> None:
    user = tmp_path / "user"
    user.mkdir()
    (user / "custom.html").write_text("<html><title>Custom</title></html>")

    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "elegant.html").write_text("<html><title>Elegant</title></html>")

    result = list_styles_merged([user, bundled])
    names = [s["name"] for s in result]
    assert "custom" in names
    assert "elegant" in names


def test_list_styles_merged_user_shadows_bundled(tmp_path: Path) -> None:
    """When a style name exists in multiple dirs, the first dir wins."""
    user = tmp_path / "user"
    user.mkdir()
    (user / "elegant.html").write_text("<html><title>User Override</title></html>")

    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "elegant.html").write_text("<html><title>Bundled Version</title></html>")

    result = list_styles_merged([user, bundled])
    elegant_entries = [s for s in result if s["name"] == "elegant"]
    assert len(elegant_entries) == 1
    assert "User Override" in elegant_entries[0]["description"]


def test_list_styles_merged_skips_missing_dirs(tmp_path: Path) -> None:
    missing = tmp_path / "missing"  # does not exist
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "foo.html").write_text("<html><title>Foo</title></html>")

    result = list_styles_merged([missing, existing])
    assert len(result) == 1
    assert result[0]["name"] == "foo"


def test_list_styles_merged_empty_returns_empty(tmp_path: Path) -> None:
    assert list_styles_merged([tmp_path / "a", tmp_path / "b"]) == []


# ---------------------------------------------------------------------------
# list_styles (single directory, backward compatible)
# ---------------------------------------------------------------------------


def test_list_styles_single_dir_still_works(temp_styles_dir: Path) -> None:
    result = list_styles(temp_styles_dir)
    names = [s["name"] for s in result]
    assert "elegant-dark" in names
    assert "custom-brand" in names
