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
