# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for writing guide directory resolution."""

import os
from pathlib import Path

import pytest

from sdpm.api import get_writings_dirs
from sdpm.knowledge.reference import BUNDLED_WRITINGS_DIR


@pytest.fixture
def temp_writings_dir(tmp_path: Path) -> Path:
    d = tmp_path / "writing"
    d.mkdir()
    (d / "house.md").write_text("---\ndescription: House wording\n---\n\n# House\n")
    return d


def test_writings_dir_includes_bundled() -> None:
    assert BUNDLED_WRITINGS_DIR in get_writings_dirs()


def test_writings_dir_respects_env(monkeypatch: pytest.MonkeyPatch, temp_writings_dir: Path) -> None:
    monkeypatch.setenv("SDPM_WRITINGS_DIR", str(temp_writings_dir))
    assert get_writings_dirs()[0] == temp_writings_dir


def test_writings_dir_includes_user_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """User-local writing dir appears between env override and bundled."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SDPM_WRITINGS_DIR", raising=False)
    dirs = get_writings_dirs()
    assert dirs[0] == tmp_path / "sdpm" / "writing"
    assert dirs[-1] == BUNDLED_WRITINGS_DIR


def test_writings_dir_supports_multiple_env_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    monkeypatch.setenv("SDPM_WRITINGS_DIR", f"{d1}{os.pathsep}{d2}")
    dirs = get_writings_dirs()
    assert dirs[0] == d1
    assert dirs[1] == d2


def test_bundled_writings_dir_is_under_examples() -> None:
    """The bundled default lives beside styles, not among the technical guides."""
    assert BUNDLED_WRITINGS_DIR.parent.name == "examples"
    assert BUNDLED_WRITINGS_DIR.name == "writing"


# ---------------------------------------------------------------------------
# list_guides_listing / list_writings
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_writings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SDPM_WRITINGS_DIR", raising=False)
    d = tmp_path / "sdpm" / "writing"
    d.mkdir(parents=True)
    (d / "house.md").write_text("---\ndescription: House wording\n---\n\n# House\n")
    return d


def test_writings_listing_returns_the_five_fields(isolated_writings: Path) -> None:
    from sdpm.api import get_writings_dirs, list_guides_listing

    items = list_guides_listing(get_writings_dirs(), "writing", [], "")
    assert items
    for item in items:
        assert set(item) >= {"name", "source", "description", "pinned", "default"}


def test_writings_listing_keeps_the_bundled_ja_until_pins_narrow_it(isolated_writings: Path) -> None:
    """The bundled default is listed; the shared pin filter is what removes it."""
    from sdpm.api import get_writings_dirs, list_guides_listing

    unpinned = {i["name"]: i["source"] for i in list_guides_listing(get_writings_dirs(), "writing", [], "")}
    assert unpinned["house"] == "user"

    pinned = [i["name"] for i in list_guides_listing(get_writings_dirs(), "writing", ["house"], "")]
    assert pinned == ["house"], "ja is neither pinned nor the user's own"


def test_a_user_guide_of_the_same_name_shadows_the_bundled_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SDPM_WRITINGS_DIR", raising=False)
    d = tmp_path / "sdpm" / "writing"
    d.mkdir(parents=True)
    (d / "ja.md").write_text("---\ndescription: My own Japanese rules\n---\n")

    from sdpm.api import get_writings_dirs, list_guides_listing

    items = {i["name"]: i for i in list_guides_listing(get_writings_dirs(), "writing", [], "")}
    assert items["ja"]["source"] == "user"
    assert items["ja"]["description"] == "My own Japanese rules"


def test_list_writings_tool_marks_the_default_and_shows_the_scopes(
    isolated_writings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A writing guide belongs to a language, so the listing shows which scope each
    default serves — one boolean could not say whether ja or en2ja was meant."""
    from sdpm import config
    from sdpm.tools import list_writings

    config.invalidate_cache()
    (isolated_writings.parent / "state.json").write_text(
        '{"default_writing": {"ja": "ja", "en2ja": "house"}}'
    )
    result = list_writings()
    items = {i["name"]: i for i in result["writings"]}
    assert result["defaults"] == {"ja": "ja", "en2ja": "house"}
    assert items["ja"]["default"] is True
    assert items["house"]["default"] is True


def test_a_writing_guide_that_is_no_scopes_default_is_not_marked(
    isolated_writings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sdpm import config
    from sdpm.tools import list_writings

    config.invalidate_cache()
    (isolated_writings.parent / "state.json").write_text('{"default_writing": {"ja": "ja"}}')
    items = {i["name"]: i for i in list_writings()["writings"]}
    assert items["house"]["default"] is False
