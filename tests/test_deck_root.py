# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Deck root order shared by the CLI, both local MCP servers and the Local Web UI.

SDPM_DECK_ROOT → SDPM_OUTPUT_DIR → output_dir in config.json (``~`` expanded) → default.
web-ui/src/lib/local/sdpmPaths.test.ts holds the same table for the Web UI side.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from sdpm import config
from sdpm.api import _get_output_base_dir

_ROOT = Path(__file__).resolve().parent.parent
_LOCAL = _ROOT / "servers" / "local"

# (SDPM_DECK_ROOT, SDPM_OUTPUT_DIR, config.json content, expected); "<tmp>" is the test's tmp dir.
_TABLE = [
    (None, None, None, "~/Documents/SDPM-Presentations"),
    (None, None, {"output_dir": "<tmp>/cfg"}, "<tmp>/cfg"),
    (None, None, {"output_dir": "~/cfg-decks"}, "~/cfg-decks"),
    (None, None, {"extra_sources": []}, "~/Documents/SDPM-Presentations"),
    (None, None, "{not json", "~/Documents/SDPM-Presentations"),
    (None, "<tmp>/out", {"output_dir": "<tmp>/cfg"}, "<tmp>/out"),
    ("<tmp>/deck", "<tmp>/out", {"output_dir": "<tmp>/cfg"}, "<tmp>/deck"),
    ("", "<tmp>/out", None, "<tmp>/out"),
]


def _arrange(monkeypatch, tmp_path, deck_root, output_dir, config_json):
    """Point env and config.json at tmp_path; return a function expanding table values."""

    def value(text: str) -> str:
        return text.replace("<tmp>", str(tmp_path))

    for name, raw in (("SDPM_DECK_ROOT", deck_root), ("SDPM_OUTPUT_DIR", output_dir)):
        if raw is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value(raw))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "xdg"))
    config_dir = tmp_path / "xdg" / "sdpm"
    config_dir.mkdir(parents=True)
    if config_json is not None:
        text = config_json if isinstance(config_json, str) else value(json.dumps(config_json))
        (config_dir / "config.json").write_text(text)
    # A config.json that cannot be read falls back without asking PowerShell for Documents.
    monkeypatch.setattr("sdpm.engine.preview.backend._is_wsl", lambda: False)
    config.invalidate_cache()
    return lambda text: Path(value(text)).expanduser()


@pytest.fixture(autouse=True)
def _fresh_config():
    yield
    config.invalidate_cache()


@pytest.mark.parametrize(("deck_root", "output_dir", "config_json", "expected"), _TABLE)
def test_deck_root_order(monkeypatch, tmp_path, deck_root, output_dir, config_json, expected):
    path = _arrange(monkeypatch, tmp_path, deck_root, output_dir, config_json)
    assert _get_output_base_dir() == path(expected)


def test_acp_server_uses_the_same_deck_root(monkeypatch, tmp_path):
    """server_acp.py (the Web UI's MCP server) follows config.json like server.py does."""
    path = _arrange(monkeypatch, tmp_path, None, None, {"output_dir": "<tmp>/cfg"})
    monkeypatch.syspath_prepend(str(_LOCAL))
    spec = importlib.util.spec_from_file_location("sdpm_acp_server_deck_root_test", _LOCAL / "server_acp.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert module._DECK_ROOT == path("<tmp>/cfg").resolve()
    assert module._RAW_ATTACHMENT_ROOT == module._DECK_ROOT / ".attachments"
