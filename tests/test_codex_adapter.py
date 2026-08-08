# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Layer 3 — the Codex adapter.

The Agent Plugins compatible-client list covers *portable components*, not
distribution: Codex discovers a plugin through ``.codex-plugin/plugin.json``,
loads bundled MCP servers from a root ``.mcp.json`` referenced by the manifest,
and installs from a marketplace catalog. So the portable ``plugin.json`` alone
does not make this repository installable in Codex.

Because the server definition now exists twice — once in the portable
``mcp.json`` and once in ``.mcp.json`` — the important guard here is drift:
editing one and forgetting the other would leave Codex running a stale server.
"""

import json
from pathlib import Path

import pytest

import sdpm

_REPO = Path(__file__).resolve().parent.parent
_CODEX_MANIFEST = _REPO / ".codex-plugin" / "plugin.json"
_CODEX_MCP = _REPO / ".mcp.json"
_PORTABLE_MCP = _REPO / "mcp.json"
_MARKETPLACE = _REPO / ".agents" / "plugins" / "marketplace.json"

# Manifest fields that point at bundled components. Codex requires these to
# start with "./", resolve relative to the plugin root, and stay inside it.
_PATH_FIELDS = ("skills", "mcpServers", "apps", "hooks")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(_CODEX_MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def codex_mcp() -> dict:
    return json.loads(_CODEX_MCP.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def portable_mcp() -> dict:
    return json.loads(_PORTABLE_MCP.read_text(encoding="utf-8"))


class TestCodexManifest:
    def test_manifest_is_the_only_file_in_the_codex_directory(self):
        # Codex is explicit: only plugin.json belongs in .codex-plugin/;
        # skills/, hooks/, assets/, .mcp.json and .app.json live at the root.
        assert [p.name for p in _CODEX_MANIFEST.parent.iterdir()] == ["plugin.json"]

    @pytest.mark.parametrize("field", ("name", "version", "description", "skills"))
    def test_required_field_is_present(self, manifest, field):
        assert manifest.get(field)

    def test_name_is_kebab_case(self, manifest):
        name = manifest["name"]
        assert name == name.lower()
        assert " " not in name and "_" not in name

    def test_name_matches_the_portable_manifest(self, manifest):
        portable = json.loads((_REPO / "plugin.json").read_text(encoding="utf-8"))
        assert manifest["name"] == portable["name"]

    def test_version_tracks_the_engine_version(self, manifest):
        assert manifest["version"] == sdpm.__version__

    @pytest.mark.parametrize("field", _PATH_FIELDS)
    def test_component_paths_are_plugin_relative_and_contained(self, manifest, field):
        value = manifest.get(field)
        if value is None:
            pytest.skip(f"{field} not declared")
        for raw in [value] if isinstance(value, str) else value:
            assert raw.startswith("./"), f"{field} must start with './': {raw!r}"
            target = (_REPO / raw).resolve()
            assert target.exists(), f"{field} points at a missing path: {raw}"
            assert target.is_relative_to(_REPO), f"{field} escapes the plugin root: {raw}"

    def test_bundled_mcp_servers_are_declared(self, manifest):
        # Without this the .mcp.json at the root is never read.
        assert manifest["mcpServers"] == "./.mcp.json"

    def test_skills_point_at_the_shared_tree(self, manifest):
        assert manifest["skills"] == "./skills/"


class TestNoDriftBetweenMcpConfigs:
    """The portable mcp.json and Codex's .mcp.json must describe the same server."""

    def test_same_server_names(self, codex_mcp, portable_mcp):
        assert set(codex_mcp["mcpServers"]) == set(portable_mcp["mcpServers"])

    def test_same_server_definitions(self, codex_mcp, portable_mcp):
        for name, portable_server in portable_mcp["mcpServers"].items():
            assert codex_mcp["mcpServers"][name] == portable_server, (
                f"'{name}' differs between mcp.json and .mcp.json — update both "
                "or Codex will run a stale server definition"
            )

    def test_codex_config_has_no_agent_plugins_schema_key(self, codex_mcp):
        # .mcp.json is Codex's own file; claiming the Agent Plugins schema
        # would be a false assertion about which spec validates it.
        assert "$schema" not in codex_mcp

    def test_uv_virtualenv_lives_outside_the_install_cache(self, codex_mcp):
        # Codex installs into ~/.codex/plugins/cache/<marketplace>/<plugin>/<version>/
        # and reloads from there, so a .venv created in place is discarded on
        # every upgrade.
        env = codex_mcp["mcpServers"]["sdpm"]["env"]
        assert env["UV_PROJECT_ENVIRONMENT"].startswith("${PLUGIN_DATA}/")


@pytest.fixture(scope="module")
def marketplace() -> dict:
    return json.loads(_MARKETPLACE.read_text(encoding="utf-8"))


class TestRepoMarketplace:
    """Local installs are marketplace-driven, so the catalog ships with the repo."""

    def test_has_a_marketplace_name(self, marketplace):
        assert marketplace.get("name")

    def test_lists_this_plugin(self, marketplace, manifest):
        names = [p["name"] for p in marketplace["plugins"]]
        assert manifest["name"] in names

    @pytest.mark.parametrize("key", ("policy", "category"))
    def test_entries_carry_install_metadata(self, marketplace, key):
        # Codex expects policy.installation, policy.authentication and category
        # on every entry.
        for entry in marketplace["plugins"]:
            assert key in entry, f"marketplace entry {entry['name']!r} is missing {key}"

    def test_policy_fields_are_complete(self, marketplace):
        for entry in marketplace["plugins"]:
            assert {"installation", "authentication"} <= set(entry["policy"])

    def test_source_paths_are_relative_to_the_marketplace_root(self, marketplace):
        # The marketplace root is the repo root, not .agents/plugins/.
        for entry in marketplace["plugins"]:
            source = entry["source"]
            path = source if isinstance(source, str) else source["path"]
            assert path.startswith("./"), f"source path must start with './': {path!r}"
            assert (_REPO / path).resolve().is_relative_to(_REPO)
