# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Parity tests for the ACP agent definitions (servers/local/.kiro/acp-agents).

These 5 JSONs are thin wiring: name + persona reference + tool allowlist.
The tests pin the invariants that keep them honest wiring instead of a
second place where behavior accumulates:

- ``tools == allowedTools`` — a tool an agent carries but may not call
  (or vice versa) is always a mistake in this project
- identical ``mcpServers`` block — every agent talks to the same server
- ``prompt`` resolves to an existing ``personas/*.md`` (behavior text
  lives only there; the JSON must not duplicate it)
- ``name`` matches the file name

Tool-list differences across the 5 agents were reviewed (2026-08-02,
stateless-attachments-mcp-cleanup) and judged intentional, not accretion:

- ``sdpm-style`` (9): style-only surface — run_style_python + hearing +
  browsing; no deck tools
- ``sdpm-composer`` (21): no dialogue (hearing), no nested dispatch
  (use_subagent), no web fetch/search, no diff — composers only compose
- ``sdpm-single`` (25): spec surface minus use_subagent (single agent
  does everything itself, no dispatch)
- ``sdpm-spec`` / ``sdpm-vibe`` (26): full orchestrator surface

The snapshot below pins those counts; widening any allowlist is a
deliberate decision that must update this test.
"""

import json
from pathlib import Path

import pytest

_ACP_AGENTS_DIR = (
    Path(__file__).resolve().parent.parent / "servers" / "local" / ".kiro" / "acp-agents"
)
_AGENT_FILES = sorted(_ACP_AGENTS_DIR.glob("*.json"))

# Exact allowlist snapshot. Any change — adding, removing, or swapping a
# tool — is a deliberate decision that must update this test. The
# inter-agent differences were reviewed (2026-08-02) and are
# intentional (see module docstring).
_FULL_ORCHESTRATOR = {
    "read", "glob", "grep", "use_subagent", "web_fetch", "web_search",
    "@sdpm/analyze_template", "@sdpm/apply_style", "@sdpm/arch_diagram",
    "@sdpm/code_to_slide",
    "@sdpm/diff_pptx", "@sdpm/generate_pptx", "@sdpm/grid", "@sdpm/hearing",
    "@sdpm/import_attachment", "@sdpm/init_presentation",
    "@sdpm/list_guides", "@sdpm/list_styles",
    "@sdpm/list_templates", "@sdpm/list_workflows",
    "@sdpm/read_attachment", "@sdpm/read_examples", "@sdpm/read_guides",
    "@sdpm/read_workflows", "@sdpm/run_python", "@sdpm/search_assets",
}
_EXPECTED_TOOLS = {
    "sdpm-spec": _FULL_ORCHESTRATOR,
    "sdpm-vibe": _FULL_ORCHESTRATOR,
    # single agent does everything itself — no dispatch
    "sdpm-single": _FULL_ORCHESTRATOR - {"use_subagent"},
    # composers only compose: no dialogue, no nesting, no web, no diff
    "sdpm-composer": _FULL_ORCHESTRATOR - {
        "use_subagent", "web_fetch", "web_search",
        "@sdpm/hearing", "@sdpm/diff_pptx",
    },
    # style-only surface
    "sdpm-style": {
        "read", "glob", "grep", "web_fetch", "web_search",
        "@sdpm/analyze_template", "@sdpm/hearing", "@sdpm/list_styles",
        "@sdpm/run_style_python",
    },
}
_EXPECTED_AGENTS = set(_EXPECTED_TOOLS)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_expected_agent_set():
    assert {p.stem for p in _AGENT_FILES} == _EXPECTED_AGENTS


@pytest.mark.parametrize("path", _AGENT_FILES, ids=lambda p: p.stem)
def test_tool_set_snapshot(path: Path):
    actual = set(_load(path)["tools"])
    expected = _EXPECTED_TOOLS[path.stem]
    assert actual == expected, (
        f"{path.name}: allowlist changed — widening or swapping an agent's "
        f"surface is a deliberate decision; update the snapshot.\n"
        f"added: {sorted(actual - expected)}\nremoved: {sorted(expected - actual)}"
    )


@pytest.mark.parametrize("path", _AGENT_FILES, ids=lambda p: p.stem)
def test_tools_equal_allowed_tools(path: Path):
    data = _load(path)
    tools, allowed = data["tools"], data["allowedTools"]
    assert len(tools) == len(set(tools)), f"{path.name}: duplicate entries in tools"
    assert len(allowed) == len(set(allowed)), f"{path.name}: duplicate entries in allowedTools"
    # Order carries no meaning — compare as sets
    assert set(tools) == set(allowed), (
        f"{path.name}: tools and allowedTools must contain the same entries — "
        "a tool the agent carries but may not call is dead weight, and an "
        "allowed tool it does not carry can never be called."
    )


@pytest.mark.parametrize("path", _AGENT_FILES, ids=lambda p: p.stem)
def test_name_matches_file_name(path: Path):
    assert _load(path)["name"] == path.stem


@pytest.mark.parametrize("path", _AGENT_FILES, ids=lambda p: p.stem)
def test_prompt_persona_reference_exists(path: Path):
    prompt = _load(path)["prompt"]
    assert prompt.startswith("file://"), f"{path.name}: prompt must reference a persona file"
    target = (_ACP_AGENTS_DIR / prompt.removeprefix("file://")).resolve()
    assert target.exists(), f"{path.name}: {prompt} does not resolve ({target})"
    assert target.parent.name == "personas", (
        f"{path.name}: behavior text must come from personas/, got {target}"
    )


def test_mcp_servers_identical_across_agents():
    blocks = [_load(p)["mcpServers"] for p in _AGENT_FILES]
    assert all(b == blocks[0] for b in blocks), (
        "All ACP agents must talk to the same sdpm server with the same config"
    )
    assert list(blocks[0].keys()) == ["sdpm"]


def test_cloud_deck_tools_are_subset_of_local_orchestrator():
    """Loose cross-layer invariant: every cloud deck tool exists locally.

    The cloud L4 agent (agent/modes) and the local ACP agents bind the same
    contract, but the local list additionally carries local-only tools
    (hearing, use_subagent, web_*). The reverse direction is
    cloud-specific (get_preview), so only this direction is pinned.
    """
    modes_src = (
        Path(__file__).resolve().parent.parent / "agent" / "modes" / "__init__.py"
    ).read_text(encoding="utf-8")
    import re
    m = re.search(r"_DECK_TOOLS = \[(.*?)\]", modes_src, re.DOTALL)
    assert m, "agent/modes/__init__.py: _DECK_TOOLS not found"
    cloud_tools = set(re.findall(r'"([a-z_]+)"', m.group(1)))
    assert "arch_diagram" in cloud_tools, (
        "Cloud deck agents must expose arch_diagram because the compose workflow "
        "requires it for architecture, system, and flow diagrams"
    )
    cloud_only = {"get_preview"}  # S3/presign transport tools

    spec_tools = {
        t.removeprefix("@sdpm/")
        for t in _load(_ACP_AGENTS_DIR / "sdpm-spec.json")["tools"]
        if t.startswith("@sdpm/")
    }
    missing = cloud_tools - cloud_only - spec_tools
    assert not missing, (
        f"Cloud deck tools missing from the local orchestrator surface: {missing}"
    )
