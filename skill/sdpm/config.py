# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Centralized config loader for skill/assets/config.json."""

import json
from pathlib import Path
from typing import Optional

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

_DEFAULTS = {
    "output_dir": "~/Documents/SDPM-Presentations",
    "extra_sources": [],
}

_cache: Optional[dict] = None


def get_config() -> dict:
    """Load and cache config. Returns defaults for missing file/keys."""
    global _cache
    if _cache is not None:
        return _cache
    config_path = ASSETS_DIR / "config.json"
    data = {}
    if config_path.exists():
        with open(config_path) as f:
            data = json.load(f)
    _cache = {**_DEFAULTS, **data}
    return _cache


def get_output_dir() -> Path:
    """Resolved output base directory with tilde expansion."""
    return Path(get_config()["output_dir"]).expanduser()


def get_extra_sources() -> list[dict]:
    """Extra asset sources list."""
    return get_config().get("extra_sources", [])
