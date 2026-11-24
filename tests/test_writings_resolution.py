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
