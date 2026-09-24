# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Parity tests for the four canonical ACP role definitions."""

import json
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_ACP_AGENTS_DIR = _REPO / "servers" / "local" / ".kiro" / "acp-agents"
_AGENT_FILES = sorted(_ACP_AGENTS_DIR.glob("*.json"))

_FULL_ORCHESTRATOR = {
    "read",
    "glob",
    "grep",
    "use_subagent",
    "web_fetch",
    "web_search",
    "@sdpm/analyze_template",
    "@sdpm/apply_style",
    "@sdpm/arch_diagram",
    "@sdpm/check_specs",
    "@sdpm/code_to_slide",
    "@sdpm/diff_pptx",
    "@sdpm/generate_pptx",
    "@sdpm/grid",
    "@sdpm/hearing",
    "@sdpm/import_attachment",
    "@sdpm/init_deck_workspace",
    "@sdpm/list_guides",
    "@sdpm/list_styles",
    "@sdpm/list_templates",
    "@sdpm/read_attachment",
    "@sdpm/read_guides",
    "@sdpm/start_presentation",
    "@sdpm/start_translation",
    "@sdpm/run_python",
    "@sdpm/search_assets",
}
_COMPOSER = (_FULL_ORCHESTRATOR - {
    "use_subagent",
    "web_fetch",
    "web_search",
    "@sdpm/hearing",
    "@sdpm/diff_pptx",
    "@sdpm/start_presentation",
    "@sdpm/start_translation",
}) | {"@sdpm/start_composing"}
_EXPECTED_TOOLS = {
    "sdpm-orchestrator": _FULL_ORCHESTRATOR,
    "sdpm-composer": _COMPOSER,
    "sdpm-translate": (_COMPOSER - {"@sdpm/check_specs", "@sdpm/start_composing"}) | {"@sdpm/start_translation"},
    "sdpm-style": {
        "read",
        "glob",
        "grep",
        "web_fetch",
        "web_search",
        "@sdpm/analyze_template",
        "@sdpm/apply_style",
        "@sdpm/generate_pptx",
        "@sdpm/hearing",
        "@sdpm/list_styles",
        "@sdpm/read_guides",
        "@sdpm/run_style_python",
        "@sdpm/start_style",
    },
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_expected_agent_set():
    assert {path.stem for path in _AGENT_FILES} == set(_EXPECTED_TOOLS)


@pytest.mark.parametrize("path", _AGENT_FILES, ids=lambda path: path.stem)
def test_tool_set_snapshot(path: Path):
    actual = set(_load(path)["tools"])
    expected = _EXPECTED_TOOLS[path.stem]
    assert actual == expected, (
        f"{path.name}: allowlist changed\nadded: {sorted(actual - expected)}\nremoved: {sorted(expected - actual)}"
    )


@pytest.mark.parametrize("path", _AGENT_FILES, ids=lambda path: path.stem)
def test_tools_equal_allowed_tools(path: Path):
    data = _load(path)
    tools, allowed = data["tools"], data["allowedTools"]
    assert len(tools) == len(set(tools))
    assert len(allowed) == len(set(allowed))
    assert set(tools) == set(allowed)


@pytest.mark.parametrize("path", _AGENT_FILES, ids=lambda path: path.stem)
def test_name_and_workflow_match_file(path: Path):
    data = _load(path)
    assert data["name"] == path.stem
    prompt = data["prompt"]
    assert prompt.startswith("file://")
    target = (_ACP_AGENTS_DIR / prompt.removeprefix("file://")).resolve()
    assert target.is_file()
    assert target.parent.name == "workflows"
    assert target.stem == path.stem.removeprefix("sdpm-")
    assert data.get("resources") == []


def test_mcp_servers_identical_across_agents():
    blocks = [_load(path)["mcpServers"] for path in _AGENT_FILES]
    assert all(block == blocks[0] for block in blocks)
    assert list(blocks[0]) == ["sdpm"]


def test_cloud_deck_tools_are_subset_of_local_orchestrator():
    modes_src = (_REPO / "agent" / "modes" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r"_DECK_TOOLS = \[(.*?)\]", modes_src, re.DOTALL)
    assert match
    cloud_tools = set(re.findall(r'"([a-z_]+)"', match.group(1)))
    assert "arch_diagram" in cloud_tools
    cloud_only = {"get_preview"}
    local_tools = {
        tool.removeprefix("@sdpm/")
        for tool in _load(_ACP_AGENTS_DIR / "sdpm-orchestrator.json")["tools"]
        if tool.startswith("@sdpm/")
    }
    assert not cloud_tools - cloud_only - local_tools
