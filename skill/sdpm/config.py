# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Centralized config loader and user-local directory resolution for sdpm."""

import json
import os
import sys
from pathlib import Path
from typing import Optional

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

_DEFAULTS = {
    "output_dir": "~/Documents/SDPM-Presentations",
    "extra_sources": [],
}

_cache: Optional[dict] = None


def get_user_config_dir() -> Path:
    """Return platform-appropriate user config directory for sdpm.

    - Windows: %APPDATA%/sdpm (default: ~/AppData/Roaming/sdpm)
    - macOS/Linux: $XDG_CONFIG_HOME/sdpm (default: ~/.config/sdpm)

    This function always reads the current environment (no caching) so that
    tests can override via monkeypatch.setenv.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "sdpm"


def _get_resource_dirs(env_var: Optional[str], subdir: str, bundled: Path) -> list[Path]:
    """Return ordered list of directories for a resource type.

    Search order (first match wins):
      1. $env_var — os.pathsep-separated list (same semantics as PATH)
         On Windows ';', on Unix ':'
      2. get_user_config_dir()/{subdir}/
      3. bundled (package-shipped directory)

    Common pattern shared by templates and styles. Assets use a 4-layer
    structure (extra_sources → user-local → built-in → legacy) and do not
    use this helper.

    Args:
        env_var: Environment variable name to check for override paths.
                 Pass None to skip environment variable lookup.
        subdir: Subdirectory name under get_user_config_dir() (e.g. "templates").
        bundled: Package-shipped fallback directory.

    Returns:
        Ordered list of directories to search.
    """
    dirs: list[Path] = []
    if env_var:
        val = os.environ.get(env_var)
        if val:
            dirs.extend(Path(p).expanduser() for p in val.split(os.pathsep) if p)
    dirs.append(get_user_config_dir() / subdir)
    dirs.append(bundled)
    return dirs


def invalidate_cache() -> None:
    """Clear config cache so next get_config() reloads from disk.

    Call when user may have edited ~/.config/sdpm/config.json at runtime
    (e.g., MCP Local tool invocations where the process is long-lived).
    """
    global _cache
    _cache = None


def get_config() -> dict:
    """Load and cache config. Returns defaults merged with user-local overrides.

    Merge strategy: _DEFAULTS <- get_user_config_dir()/config.json (key-wise).
    Package-internal config.json is NOT read (it was never shipped and
    would be lost on pip upgrade).
    """
    global _cache
    if _cache is not None:
        return _cache
    merged = dict(_DEFAULTS)
    user_path = get_user_config_dir() / "config.json"
    if user_path.exists():
        with open(user_path) as f:
            merged.update(json.load(f))
    _cache = merged
    return _cache


def get_output_dir() -> Path:
    """Resolved output base directory with tilde expansion."""
    return Path(get_config()["output_dir"]).expanduser()


def get_extra_sources() -> list[dict]:
    """Extra asset sources list."""
    return get_config().get("extra_sources", [])


# ── State (app-managed, separate from user-editable config) ──


def get_state() -> dict:
    """Load app state from state.json. Returns empty dict if missing.

    state.json stores app-managed data (pinned styles, etc.) separately
    from config.json which is user-editable settings.
    """
    state_path = get_user_config_dir() / "state.json"
    if state_path.exists():
        with open(state_path) as f:
            return json.load(f)
    return {}


def update_state(key: str, value: object) -> None:
    """Update a single key in state.json (read-modify-write).

    Creates the file and parent directory if they don't exist.
    """
    config_dir = get_user_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    state_path = config_dir / "state.json"
    state = {}
    if state_path.exists():
        with open(state_path) as f:
            state = json.load(f)
    state[key] = value
    with open(state_path, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
