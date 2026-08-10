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
    """The portable mcp.json and Codex's .mcp.json must describe the same server.

    The two files cannot be byte-identical: Codex (verified on 0.146.1) does
    not expand ``${PLUGIN_ROOT}`` / ``${PLUGIN_DATA}`` in ``.mcp.json`` args or
    env — an unexpanded ``${PLUGIN_ROOT}`` in args makes ``uv`` fail with
    "No such file or directory", and an unexpanded ``${PLUGIN_DATA}`` in env
    creates a literal ``${PLUGIN_DATA}`` directory. Relative *args* paths
    resolve against the session workdir (unstable), but a relative ``cwd``
    resolves against the plugin cache root (stable). So ``.mcp.json`` uses
    ``cwd`` while the portable ``mcp.json`` keeps ``${PLUGIN_ROOT}`` — that
    placeholder is guaranteed by the Agent Plugins 1.0.0 spec itself.

    Drift is therefore checked on the *effective* server: same names, same
    command, same server directory (plugin-root relative), same script.
    """

    @staticmethod
    def _effective_server(server: dict) -> tuple:
        """Normalize a server definition to (command, server_dir, tail_args)."""
        args = list(server.get("args", []))
        cwd = server.get("cwd")
        if "--directory" in args:
            i = args.index("--directory")
            directory = args[i + 1]
            tail = args[:i] + args[i + 2 :]
        else:
            directory = cwd or "."
            tail = args
        # Portable form uses the spec-guaranteed placeholder; strip it to the
        # plugin-root-relative path for comparison.
        directory = directory.removeprefix("${PLUGIN_ROOT}/").removeprefix("${PLUGIN_ROOT}")
        return (server.get("command"), directory.strip("/"), tuple(tail))

    def test_same_server_names(self, codex_mcp, portable_mcp):
        assert set(codex_mcp["mcpServers"]) == set(portable_mcp["mcpServers"])

    def test_same_effective_server_definitions(self, codex_mcp, portable_mcp):
        for name, portable_server in portable_mcp["mcpServers"].items():
            assert self._effective_server(
                codex_mcp["mcpServers"][name]
            ) == self._effective_server(portable_server), (
                f"'{name}' differs between mcp.json and .mcp.json — update both "
                "or Codex will run a stale server definition"
            )

    def test_codex_config_has_no_agent_plugins_schema_key(self, codex_mcp):
        # .mcp.json is Codex's own file; claiming the Agent Plugins schema
        # would be a false assertion about which spec validates it.
        assert "$schema" not in codex_mcp

    def test_codex_config_has_no_unexpanded_placeholders(self, codex_mcp):
        # Verified on Codex 0.146.1: ${PLUGIN_ROOT} / ${PLUGIN_DATA} are NOT
        # expanded in .mcp.json args or env. A literal ${PLUGIN_ROOT} in args
        # breaks server startup; a literal ${PLUGIN_DATA} in env creates a
        # directory named '${PLUGIN_DATA}'.
        text = json.dumps(codex_mcp)
        assert "${PLUGIN_ROOT}" not in text
        assert "${PLUGIN_DATA}" not in text

    def test_codex_server_cwd_is_plugin_relative_and_contained(self, codex_mcp):
        # A relative cwd resolves against the plugin cache root (verified),
        # which is the only workdir-independent anchor Codex offers here.
        for name, server in codex_mcp["mcpServers"].items():
            cwd = server.get("cwd")
            assert cwd, f"'{name}' must pin cwd to survive arbitrary session workdirs"
            assert not cwd.startswith("/"), f"'{name}' cwd must be plugin-relative"
            target = (_REPO / cwd).resolve()
            assert target.is_dir(), f"'{name}' cwd points at a missing dir: {cwd}"
            assert target.is_relative_to(_REPO)


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
