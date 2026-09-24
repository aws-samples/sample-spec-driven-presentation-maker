# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for generated clone-free MCP client installation artifacts."""

from __future__ import annotations

import base64
import importlib.util
import json
import re
import subprocess
from pathlib import Path

import sdpm

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "clients" / "uvx-config.json"
SNIPPETS_PATH = ROOT / "clients" / "snippets.md"
GENERATOR_PATH = ROOT / "scripts" / "gen_client_snippets.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_client_snippets", GENERATOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_client_snippets_are_current() -> None:
    generator = _load_generator()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    assert SNIPPETS_PATH.read_text(encoding="utf-8") == generator.render_snippets(config)
    subprocess.run(
        ["uv", "run", "python", str(GENERATOR_PATH), "--check"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_cursor_deep_link_decodes_to_canonical_config() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    snippets = SNIPPETS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"cursor://anysphere\.cursor-deeplink/mcp/install\?name=sdpm&config=([A-Za-z0-9+/=]+)",
        snippets,
    )

    assert match, "generated Cursor deep link not found"
    decoded = json.loads(base64.b64decode(match.group(1), validate=True))
    assert decoded == config


def test_existing_plugin_configs_remain_checkout_based() -> None:
    claude = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    portable = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))

    claude_server = claude["mcpServers"]["sdpm"]
    portable_server = portable["mcpServers"]["sdpm"]
    assert claude_server["command"] == portable_server["command"] == "uv"
    assert "${CLAUDE_PLUGIN_ROOT}/servers/local" in claude_server["args"]
    assert "${PLUGIN_ROOT}/servers/local" in portable_server["args"]
    assert claude_server["command"] != "uvx"
    assert portable_server["command"] != "uvx"


def test_mcpb_manifest_uses_uv_runtime() -> None:
    manifest = json.loads(
        (ROOT / "clients" / "claude-desktop" / "manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["manifest_version"] == "0.4"
    assert manifest["version"] == sdpm.__version__
    assert manifest["server"] == {
        "type": "uv",
        "entry_point": "servers/local/server.py",
        "mcp_config": {
            "command": "uv",
            "args": ["run", "--directory", "${__dirname}", "servers/local/server.py"],
        },
    }
    assert "LibreOffice" in manifest["long_description"]
    assert "poppler" in manifest["long_description"]
    assert "PPTX generation still works" in manifest["long_description"]
