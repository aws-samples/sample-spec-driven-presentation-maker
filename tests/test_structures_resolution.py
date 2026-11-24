# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for structure guide directory resolution."""

import os
from pathlib import Path

import pytest

from sdpm.api import get_structures_dirs
from sdpm.knowledge.reference import BUNDLED_STRUCTURES_DIR


@pytest.fixture
def temp_structures_dir(tmp_path: Path) -> Path:
    d = tmp_path / "structure"
    d.mkdir()
    (d / "scqa-first.md").write_text("---\ndescription: Conclusion first\n---\n\n# SCQA\n")
    return d


def test_structures_dir_includes_bundled() -> None:
    assert BUNDLED_STRUCTURES_DIR in get_structures_dirs()


def test_structures_dir_respects_env(monkeypatch: pytest.MonkeyPatch, temp_structures_dir: Path) -> None:
    monkeypatch.setenv("SDPM_STRUCTURES_DIR", str(temp_structures_dir))
    assert get_structures_dirs()[0] == temp_structures_dir


def test_structures_dir_includes_user_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """User-local structure dir appears between env override and bundled."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SDPM_STRUCTURES_DIR", raising=False)
    dirs = get_structures_dirs()
    assert dirs[0] == tmp_path / "sdpm" / "structure"
    assert dirs[-1] == BUNDLED_STRUCTURES_DIR


def test_structures_dir_supports_multiple_env_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    monkeypatch.setenv("SDPM_STRUCTURES_DIR", f"{d1}{os.pathsep}{d2}")
    dirs = get_structures_dirs()
    assert dirs[0] == d1
    assert dirs[1] == d2


def test_bundled_structures_dir_is_under_examples() -> None:
    """The bundled default lives beside styles, not among the technical guides."""
    assert BUNDLED_STRUCTURES_DIR.parent.name == "examples"
    assert BUNDLED_STRUCTURES_DIR.name == "structure"


# ---------------------------------------------------------------------------
# list_guides_listing / list_structures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_structures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A user-local structure store with two guides, bundled ones still behind it."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SDPM_STRUCTURES_DIR", raising=False)
    d = tmp_path / "sdpm" / "structure"
    d.mkdir(parents=True)
    (d / "scqa-first.md").write_text("---\ndescription: Conclusion first\n---\n\n# SCQA\n")
    (d / "internal-report.md").write_text("---\ndescription: Internal report\n---\n\n# Report\n")
    return d


def test_listing_returns_the_five_fields(isolated_structures: Path) -> None:
    from sdpm.api import get_structures_dirs, list_guides_listing

    items = list_guides_listing(get_structures_dirs(), "structure", [], "")
    assert items, "bundled plus user guides must be listed"
    for item in items:
        assert set(item) >= {"name", "source", "description", "pinned", "default"}


def test_listing_reads_the_frontmatter_description(isolated_structures: Path) -> None:
    from sdpm.api import get_structures_dirs, list_guides_listing

    items = {i["name"]: i for i in list_guides_listing(get_structures_dirs(), "structure", [], "")}
    assert items["scqa-first"]["description"] == "Conclusion first"


def test_listing_tags_the_users_own_guides(isolated_structures: Path) -> None:
    from sdpm.api import get_structures_dirs, list_guides_listing

    items = {i["name"]: i for i in list_guides_listing(get_structures_dirs(), "structure", [], "")}
    assert items["scqa-first"]["source"] == "user"


def test_listing_shows_the_bundled_guide_when_the_user_has_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no pins and no guides of their own, the user sees the bundled default."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SDPM_STRUCTURES_DIR", raising=False)

    from sdpm.api import get_structures_dirs, list_guides_listing

    items = {i["name"]: i for i in list_guides_listing(get_structures_dirs(), "structure", [], "")}
    assert items["by-audience"]["source"] == "builtin"


def test_listing_hides_unpinned_bundled_guides_once_pins_exist(isolated_structures: Path) -> None:
    """Same pin filter as styles: pinned plus the user's own, nothing else."""
    from sdpm.api import get_structures_dirs, list_guides_listing

    names = [i["name"] for i in list_guides_listing(get_structures_dirs(), "structure", ["scqa-first"], "")]
    assert "scqa-first" in names, "pinned"
    assert "internal-report" in names, "the user's own survives without a pin"
    assert "by-audience" not in names, "neither pinned nor the user's own"


def test_listing_keeps_a_default_the_pins_would_hide(isolated_structures: Path) -> None:
    from sdpm.api import get_structures_dirs, list_guides_listing

    items = {
        i["name"]: i
        for i in list_guides_listing(get_structures_dirs(), "structure", ["scqa-first"], "by-audience")
    }
    assert items["by-audience"]["default"] is True


def test_listing_marks_the_pinned_ones(isolated_structures: Path) -> None:
    from sdpm.api import get_structures_dirs, list_guides_listing

    items = {i["name"]: i for i in list_guides_listing(get_structures_dirs(), "structure", ["scqa-first"], "")}
    assert items["scqa-first"]["pinned"] is True
    assert items["internal-report"]["pinned"] is False


def test_listing_marks_only_the_default(isolated_structures: Path) -> None:
    from sdpm.api import get_structures_dirs, list_guides_listing

    items = {i["name"]: i for i in list_guides_listing(get_structures_dirs(), "structure", [], "internal-report")}
    assert items["internal-report"]["default"] is True
    assert [i["name"] for i in items.values() if i["default"]] == ["internal-report"]


def test_listing_marks_nothing_default_when_none_is_set(isolated_structures: Path) -> None:
    from sdpm.api import get_structures_dirs, list_guides_listing

    items = list_guides_listing(get_structures_dirs(), "structure", [], "")
    assert not any(i["default"] for i in items)


def test_list_structures_tool_reads_state(
    isolated_structures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sdpm import config
    from sdpm.tools import list_structures

    config.invalidate_cache()
    (isolated_structures.parent / "state.json").write_text(
        '{"pinned_structures": ["scqa-first"], "default_structure": "scqa-first"}'
    )
    items = {i["name"]: i for i in list_structures()["structures"]}
    assert items["scqa-first"]["pinned"] is True
    assert items["scqa-first"]["default"] is True
