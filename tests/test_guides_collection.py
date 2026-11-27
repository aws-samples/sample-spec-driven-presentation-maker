# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Guide directory resolution — the ordered sources the collection is merged from.

Same three layers as styles and templates, so a user's guide shadows the bundled
guide of that name on every surface that reads the collection.
"""

import os
from pathlib import Path

import pytest

from sdpm.api import get_guides_dirs, get_styles_dirs
from sdpm.knowledge.reference import BUNDLED_GUIDES_DIR


def test_bundled_dir_is_last() -> None:
    dirs = get_guides_dirs()
    assert dirs[-1] == BUNDLED_GUIDES_DIR


def test_env_override_comes_first(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SDPM_GUIDES_DIR", str(tmp_path))
    assert get_guides_dirs()[0] == tmp_path


def test_user_dir_sits_between_env_and_bundled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SDPM_GUIDES_DIR", raising=False)
    dirs = get_guides_dirs()
    assert dirs == [tmp_path / "sdpm" / "guides", BUNDLED_GUIDES_DIR]


def test_user_dir_is_named_guides_not_user_guides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SDPM_GUIDES_DIR", raising=False)
    assert get_guides_dirs()[0].name == "guides"


def test_multiple_env_paths_keep_their_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    monkeypatch.setenv("SDPM_GUIDES_DIR", f"{first}{os.pathsep}{second}")
    assert get_guides_dirs()[:2] == [first, second]


def test_guides_and_styles_resolve_independently(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SDPM_GUIDES_DIR", str(tmp_path / "g"))
    monkeypatch.delenv("SDPM_STYLES_DIR", raising=False)
    assert get_guides_dirs()[0] == tmp_path / "g"
    assert get_styles_dirs()[0] != tmp_path / "g"
