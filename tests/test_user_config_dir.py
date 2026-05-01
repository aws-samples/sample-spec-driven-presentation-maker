# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for user config directory resolution and resource dir helper."""

import os
import sys
from pathlib import Path

import pytest

from sdpm.config import (
    _get_resource_dirs,
    get_user_config_dir,
    invalidate_cache,
)


# ---------------------------------------------------------------------------
# get_user_config_dir
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-only test")
def test_user_config_dir_respects_xdg_config_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert get_user_config_dir() == tmp_path / "sdpm"


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-only test")
def test_user_config_dir_defaults_to_home_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert get_user_config_dir() == Path.home() / ".config" / "sdpm"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
def test_user_config_dir_respects_appdata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert get_user_config_dir() == tmp_path / "sdpm"


def test_user_config_dir_is_not_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """get_user_config_dir should read env on each call (needed for tests)."""
    if sys.platform == "win32":
        env_var = "APPDATA"
    else:
        env_var = "XDG_CONFIG_HOME"
    monkeypatch.setenv(env_var, str(tmp_path / "a"))
    first = get_user_config_dir()
    monkeypatch.setenv(env_var, str(tmp_path / "b"))
    second = get_user_config_dir()
    assert first != second


# ---------------------------------------------------------------------------
# _get_resource_dirs
# ---------------------------------------------------------------------------


def test_resource_dirs_order_no_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Order: user-local → bundled when no env var set."""
    monkeypatch.delenv("SDPM_TEST_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    bundled = tmp_path / "bundled"
    dirs = _get_resource_dirs("SDPM_TEST_DIR", "widgets", bundled)
    assert dirs == [tmp_path / "sdpm" / "widgets", bundled]


def test_resource_dirs_env_takes_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Env var paths come first."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    override = tmp_path / "override"
    bundled = tmp_path / "bundled"
    monkeypatch.setenv("SDPM_TEST_DIR", str(override))
    dirs = _get_resource_dirs("SDPM_TEST_DIR", "widgets", bundled)
    assert dirs[0] == override
    assert dirs[-1] == bundled


def test_resource_dirs_multiple_env_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    bundled = tmp_path / "bundled"
    monkeypatch.setenv("SDPM_TEST_DIR", f"{d1}{os.pathsep}{d2}")
    dirs = _get_resource_dirs("SDPM_TEST_DIR", "widgets", bundled)
    assert dirs[0] == d1
    assert dirs[1] == d2
    assert dirs[-1] == bundled


def test_resource_dirs_none_env_var_skips_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Passing env_var=None disables env lookup."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    bundled = tmp_path / "bundled"
    dirs = _get_resource_dirs(None, "widgets", bundled)
    assert dirs == [tmp_path / "sdpm" / "widgets", bundled]


# ---------------------------------------------------------------------------
# invalidate_cache
# ---------------------------------------------------------------------------


def test_invalidate_cache_clears_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import json

    from sdpm.config import get_config

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    invalidate_cache()
    # First read: no config file exists, get_config returns defaults
    cfg1 = get_config()
    assert cfg1["output_dir"] == "~/Documents/SDPM-Presentations"

    # Create user config
    user_dir = get_user_config_dir()
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "config.json").write_text(json.dumps({"output_dir": "/custom/path"}))

    # Without invalidate, stale cache is returned
    cfg_stale = get_config()
    assert cfg_stale["output_dir"] == "~/Documents/SDPM-Presentations"

    # After invalidate, new config is read
    invalidate_cache()
    cfg2 = get_config()
    assert cfg2["output_dir"] == "/custom/path"

    # Cleanup
    invalidate_cache()
