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


# ---------------------------------------------------------------------------
# filter_styles
# ---------------------------------------------------------------------------


from sdpm.reference import filter_styles


def test_filter_styles_adds_pinned_metadata() -> None:
    styles = [{"name": "a", "description": ""}, {"name": "b", "description": ""}]
    result = filter_styles(styles, pinned_names=["a"], include_all=True)
    a = next(s for s in result if s["name"] == "a")
    b = next(s for s in result if s["name"] == "b")
    assert a["pinned"] is True
    assert b["pinned"] is False


def test_filter_styles_defaults_source_to_builtin() -> None:
    styles = [{"name": "a", "description": ""}]
    result = filter_styles(styles, pinned_names=[])
    assert result[0]["source"] == "builtin"


def test_filter_styles_preserves_existing_source() -> None:
    styles = [{"name": "a", "description": "", "source": "user"}]
    result = filter_styles(styles, pinned_names=[])
    assert result[0]["source"] == "user"


def test_filter_styles_include_all_returns_everything() -> None:
    styles = [
        {"name": "a", "description": "", "source": "builtin"},
        {"name": "b", "description": "", "source": "user"},
    ]
    result = filter_styles(styles, pinned_names=["a"], include_all=True)
    assert len(result) == 2


def test_filter_styles_no_pins_returns_all() -> None:
    styles = [
        {"name": "a", "description": ""},
        {"name": "b", "description": ""},
    ]
    result = filter_styles(styles, pinned_names=[], include_all=False)
    assert len(result) == 2


def test_filter_styles_with_pins_filters_to_pinned_and_user() -> None:
    styles = [
        {"name": "a", "description": "", "source": "builtin"},
        {"name": "b", "description": "", "source": "user"},
        {"name": "c", "description": "", "source": "builtin"},
    ]
    result = filter_styles(styles, pinned_names=["a"], include_all=False)
    names = [s["name"] for s in result]
    assert "a" in names  # pinned
    assert "b" in names  # user
    assert "c" not in names  # neither pinned nor user


# ---------------------------------------------------------------------------
# list_styles_filtered (filesystem integration)
# ---------------------------------------------------------------------------


from sdpm.api import list_styles_filtered


def test_list_styles_filtered_tags_user_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))

    user_dir = tmp_path / "sdpm" / "styles"
    user_dir.mkdir(parents=True)
    (user_dir / "my-style.html").write_text("<html><title>My Style</title></html>")

    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "default.html").write_text("<html><title>Default</title></html>")

    result = list_styles_filtered([user_dir, bundled], pinned_names=[], include_all=True)
    my = next(s for s in result if s["name"] == "my-style")
    default = next(s for s in result if s["name"] == "default")
    assert my["source"] == "user"
    assert default["source"] == "builtin"


# ---------------------------------------------------------------------------
# get_state / update_state
# ---------------------------------------------------------------------------


from sdpm.config import get_state, update_state


def test_get_state_returns_empty_when_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert get_state() == {}


def test_update_state_creates_and_updates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    update_state("pinned_styles", ["a", "b"])
    state = get_state()
    assert state["pinned_styles"] == ["a", "b"]

    update_state("pinned_styles", ["a"])
    state = get_state()
    assert state["pinned_styles"] == ["a"]
