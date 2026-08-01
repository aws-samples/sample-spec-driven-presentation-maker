# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Client wiring guards.

1. The Claude Code plugin manifest must only reference files that exist —
   deleting an agent definition without updating ``.claude-plugin/plugin.json``
   breaks plugin install/load.
2. Residue guard: since v0.5.x, generic environments (Kiro CLI, plain MCP)
   need NO pre-installed composer agent (composers are self-spawned via the
   persona's spawn template). Stale "install the composer agent" wording in
   personas or docs would send users to a removed flow.
"""

import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_MANIFEST = _REPO / ".claude-plugin" / "plugin.json"


class TestPluginManifest:
    def test_agent_references_exist(self):
        manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
        for ref in manifest.get("agents", []):
            # Plugin refs resolve from the plugin root (the repo checkout),
            # not from the .claude-plugin/ directory
            target = (_REPO / ref).resolve()
            assert target.exists(), (
                f"plugin.json references a missing agent file: {ref} — "
                "agent deletions must update the manifest in the same change."
            )

    def test_mcp_server_directory_reference_exists(self):
        manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
        for server in manifest.get("mcpServers", {}).values():
            args = server.get("args", [])
            for a in args:
                if "${CLAUDE_PLUGIN_ROOT}" in a:
                    rel = a.replace("${CLAUDE_PLUGIN_ROOT}", str(_REPO))
                    assert Path(rel).exists(), f"plugin.json mcpServers path missing: {a}"


# Wording that implies a generic-environment user must pre-install a composer
# agent. personas/ is served to every MCP client; getting-started is the
# install path — neither may point at the removed flow.
_FORBIDDEN = [
    "tell the user to install it",
    "tell the user to install the composer",
    "install the composer agent",
    "generates the composer agent config",
    "composer agent config at `~/.kiro/agents/",
]

_GUARDED_FILES = [
    *sorted((_REPO / "personas").glob("*.md")),
    _REPO / "docs" / "en" / "getting-started.md",
    _REPO / "docs" / "ja" / "getting-started.md",
    _REPO / "README.md",
    _REPO / "README_ja.md",
]


@pytest.mark.parametrize("path", _GUARDED_FILES, ids=lambda p: str(p.relative_to(_REPO)))
def test_no_composer_install_residue(path: Path):
    text = path.read_text(encoding="utf-8")
    hits = [s for s in _FORBIDDEN if s in text]
    assert not hits, (
        f"{path.relative_to(_REPO)} still tells users to pre-install a composer "
        f"agent (self-spawn replaced that flow): {hits}"
    )
