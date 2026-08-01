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

Tool-list differences across the 5 agents were reviewed (2026-08-01,
theme 3) and judged intentional, not accretion:

- ``sdpm-style`` (9): style-only surface — run_style_python + hearing +
  browsing; no deck tools
- ``sdpm-composer`` (22): no dialogue (hearing), no nested dispatch
  (use_subagent), no web fetch/search, no upload/diff — composers only
  compose
- ``sdpm-single`` (27): spec surface minus use_subagent (single agent
  does everything itself, no dispatch)
- ``sdpm-spec`` / ``sdpm-vibe`` (28): full orchestrator surface

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
_EXPECTED_AGENTS = {
    "sdpm-composer": 22,
    "sdpm-single": 27,
    "sdpm-spec": 28,
    "sdpm-style": 9,
    "sdpm-vibe": 28,
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_expected_agent_set():
    assert {p.stem for p in _AGENT_FILES} == set(_EXPECTED_AGENTS)


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


def test_tool_count_snapshot():
    counts = {p.stem: len(_load(p)["tools"]) for p in _AGENT_FILES}
    assert counts == _EXPECTED_AGENTS, (
        "Tool allowlist size changed — widening an agent's surface is a "
        "deliberate decision; review the diff and update the snapshot "
        "(see module docstring for the intent of each surface)."
    )


def test_cloud_deck_tools_are_subset_of_local_orchestrator():
    """Loose cross-layer invariant: every cloud deck tool exists locally.

    The cloud L4 agent (agent/modes) and the local ACP agents bind the same
    contract, but the local list additionally carries local-only tools
    (hearing, upload_file, use_subagent, web_*). The reverse direction is
    cloud-specific (read_uploaded_file, get_preview), so only this
    direction is pinned.
    """
    modes_src = (
        Path(__file__).resolve().parent.parent / "agent" / "modes" / "__init__.py"
    ).read_text(encoding="utf-8")
    import re
    m = re.search(r"_DECK_TOOLS = \[(.*?)\]", modes_src, re.DOTALL)
    assert m, "agent/modes/__init__.py: _DECK_TOOLS not found"
    cloud_tools = set(re.findall(r'"([a-z_]+)"', m.group(1)))
    cloud_only = {"read_uploaded_file", "get_preview"}  # S3/presign transport tools

    spec_tools = {
        t.removeprefix("@sdpm/")
        for t in _load(_ACP_AGENTS_DIR / "sdpm-spec.json")["tools"]
        if t.startswith("@sdpm/")
    }
    missing = cloud_tools - cloud_only - spec_tools
    assert not missing, (
        f"Cloud deck tools missing from the local orchestrator surface: {missing}"
    )
