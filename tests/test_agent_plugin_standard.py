# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Layer 1 — the portable Agent Plugins 1.0.0 package.

``plugin.json`` and ``mcp.json`` make the repository root loadable as an Agent
Plugin by Kiro, Cursor, Copilot and VS Code. Both schemas are **closed**
(``additionalProperties: false``), and a rejected manifest is not a soft
failure: an invalid ``mcp.json`` disables the plugin's MCP servers outright,
which would take the sdpm tools away from every skill in the package.

The 1.0.0 constraints are encoded here rather than validated against a
downloaded copy of the schemas. A vendored copy is frozen just like this code,
so it would add a third-party asset and a jsonschema dependency without
detecting any drift the maintainers would not already see when bumping the
targeted version.

Normative sources:
  https://agent-plugins.org/schemas/1.0.0/plugin.schema.json
  https://agent-plugins.org/schemas/1.0.0/mcp.schema.json
  https://agent-plugins.org/plugin-authors/mcp-servers
"""

import json
import re
from pathlib import Path

import pytest

import sdpm

_REPO = Path(__file__).resolve().parent.parent
_PLUGIN_JSON = _REPO / "plugin.json"
_MCP_JSON = _REPO / "mcp.json"

_SCHEMA_BASE = "https://agent-plugins.org/schemas/1.0.0"

# plugin.schema.json: every key it allows, and the two it requires.
_PLUGIN_ALLOWED = {
    "$schema",
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "extensions",
}
_PLUGIN_REQUIRED = {"$schema", "name"}
# author is an object limited to these keys.
_AUTHOR_ALLOWED = {"name", "email", "url"}
# name: 1-64 chars, lowercase alnum / '.' / '-', alnum at both ends, no '--' or '..'
_NAME_PATTERN = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")

_STDIO_ALLOWED = {"type", "command", "args", "env", "cwd"}
_STDIO_REQUIRED = {"type", "command"}
# ${PLUGIN_ROOT} and ${PLUGIN_DATA} are supplied by the client, so a plugin
# must not try to define them itself.
_RESERVED_ENV_NAMES = {"PLUGIN_ROOT", "PLUGIN_DATA"}


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(_PLUGIN_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def mcp_config() -> dict:
    return json.loads(_MCP_JSON.read_text(encoding="utf-8"))


class TestPluginManifest:
    def test_declares_the_targeted_schema_version(self, manifest):
        assert manifest["$schema"] == f"{_SCHEMA_BASE}/plugin.schema.json"

    def test_has_the_required_keys(self, manifest):
        assert _PLUGIN_REQUIRED <= set(manifest)

    def test_has_no_keys_outside_the_closed_schema(self, manifest):
        unknown = set(manifest) - _PLUGIN_ALLOWED
        assert not unknown, f"plugin.json has keys the 1.0.0 schema rejects: {sorted(unknown)}"

    def test_name_matches_the_specified_pattern(self, manifest):
        name = manifest["name"]
        assert 1 <= len(name) <= 64
        assert _NAME_PATTERN.match(name), f"invalid plugin name: {name!r}"

    def test_author_is_an_object_with_only_allowed_keys(self, manifest):
        author = manifest["author"]
        assert isinstance(author, dict)
        unknown = set(author) - _AUTHOR_ALLOWED
        assert not unknown, f"author has keys the schema rejects: {sorted(unknown)}"

    def test_keywords_are_strings(self, manifest):
        assert all(isinstance(k, str) for k in manifest["keywords"])

    def test_version_tracks_the_engine_version(self, manifest):
        # Single source of truth is sdpm/sdpm/__init__.py (see steering/versioning).
        assert manifest["version"] == sdpm.__version__


class TestMcpConfig:
    def test_declares_the_targeted_schema_version(self, mcp_config):
        assert mcp_config["$schema"] == f"{_SCHEMA_BASE}/mcp.schema.json"

    def test_has_no_keys_outside_the_closed_schema(self, mcp_config):
        assert set(mcp_config) == {"$schema", "mcpServers"}

    def test_declares_the_sdpm_server(self, mcp_config):
        assert "sdpm" in mcp_config["mcpServers"]

    @pytest.fixture
    def server(self, mcp_config) -> dict:
        return mcp_config["mcpServers"]["sdpm"]

    def test_transport_type_is_declared(self, server):
        # Omitting `type` is the easy mistake: it is required, and the whole
        # plugin's MCP configuration is discarded without it.
        assert _STDIO_REQUIRED <= set(server)
        assert server["type"] == "stdio"

    def test_has_no_keys_outside_the_stdio_schema(self, server):
        unknown = set(server) - _STDIO_ALLOWED
        assert not unknown, f"stdio server has keys the schema rejects: {sorted(unknown)}"

    def test_command_is_a_bare_executable_token(self, server):
        # Placeholders are NOT expanded in `command`; it must resolve as a
        # single executable token (bare name, or a ./-relative plugin path).
        command = server["command"]
        assert "${" not in command
        assert " " not in command
        assert not command.startswith("/")

    def test_server_directory_is_rooted_at_the_plugin_root(self, server):
        args = server["args"]
        directory = args[args.index("--directory") + 1]
        assert directory.startswith("${PLUGIN_ROOT}/"), (
            "the MCP server directory must be resolved from ${PLUGIN_ROOT} so it "
            "does not depend on the client's default working directory"
        )

    def test_server_directory_exists_in_the_checkout(self, server):
        args = server["args"]
        directory = args[args.index("--directory") + 1]
        resolved = _REPO / directory.replace("${PLUGIN_ROOT}/", "")
        assert (resolved / "server.py").is_file(), f"missing MCP server entry point under {resolved}"

    def test_env_does_not_shadow_client_supplied_placeholders(self, server):
        assert not (_RESERVED_ENV_NAMES & set(server.get("env", {})))

    def test_uv_virtualenv_lives_in_the_writable_data_directory(self, server):
        # Clients copy the plugin into an install cache that may be read-only
        # and is replaced on update, so uv must not create .venv next to the
        # project. PLUGIN_DATA is the writable location that survives updates.
        assert server["env"]["UV_PROJECT_ENVIRONMENT"].startswith("${PLUGIN_DATA}/")

    def test_placeholders_are_only_the_two_defined_by_the_spec(self, server):
        used = set(re.findall(r"\$\{([A-Z_]+)\}", json.dumps(server)))
        assert used <= _RESERVED_ENV_NAMES, f"unknown placeholders: {sorted(used - _RESERVED_ENV_NAMES)}"
