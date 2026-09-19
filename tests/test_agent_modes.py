# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""L4 agent modes load canonical role workflows through the shared port."""

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_AGENT_DIR = _ROOT / "agent"

sys.path.insert(0, str(_AGENT_DIR))
try:
    from composition import resolve_parts
    from modes import MODES
finally:
    sys.path.remove(str(_AGENT_DIR))

from sdpm import tools as contract  # noqa: E402

_PROMPTS_DIR = _AGENT_DIR / "prompts"
_WORKFLOW_BY_MODE = {
    "orchestrator": "orchestrator",
    "vibe": "orchestrator",
    "spec": "orchestrator",
    "separated": "orchestrator",
    "single": "orchestrator",
    "composer": "composer",
    "style_creator": "style",
}


class ContractFakeMCPClient:
    """Fake MCP client dispatching synchronously to the real contract."""

    def call_tool_sync(self, tool_use_id: str, name: str, arguments: dict):
        del tool_use_id
        fn = getattr(contract, name)
        result = fn(**arguments)
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return {"status": "success", "content": [{"text": text}]}


@pytest.mark.parametrize("mode,workflow", sorted(_WORKFLOW_BY_MODE.items()))
def test_mode_fetches_workflow_via_port(mode, workflow):
    parts = MODES[mode].parts
    workflow_parts = [
        part for part in parts
        if part.source.type == "mcp" and part.source.value == "read_workflows"
    ]
    assert len(workflow_parts) == 1
    assert workflow_parts[0].source.args == {"names": [workflow]}
    assert workflow_parts[0].target == "system"


def _file_parts(mode):
    return [str(p.source.value) for p in MODES[mode].parts if p.source.type == "file"]


@pytest.mark.parametrize("mode,token", [
    ("vibe", "wiring/interaction_fast"),
    ("spec", "wiring/interaction_dialogue"),
    ("separated", "wiring/interaction_dialogue"),
    ("single", "wiring/interaction_dialogue"),
])
def test_ui_modes_pass_interaction_token_only(mode, token):
    """Spec/Vibe differ from the plain orchestrator by exactly one token part."""
    assert token in _file_parts(mode)
    assert "wiring/interaction_fast" not in _file_parts("orchestrator")
    assert "wiring/interaction_dialogue" not in _file_parts("orchestrator")


def test_interaction_tokens_are_bare_lines_defined_by_the_workflow():
    for name in ("interaction_dialogue", "interaction_fast"):
        text = (_PROMPTS_DIR / "wiring" / f"{name}.md").read_text().strip()
        assert text.startswith("Interaction mode: ")
        assert "\n" not in text
    workflow = contract.read_workflows(["orchestrator"])["documents"][0]["content"]
    assert "`Interaction mode: dialogue`" in workflow
    assert "`Interaction mode: fast`" in workflow


def test_single_mode_composes_without_composer_agents():
    single = MODES["single"]
    assert single.use_composer is False
    assert single.agent_model == "create"
    assert "wiring/no_composers" in _file_parts("single")
    assert "wiring/compose_report" not in _file_parts("single")
    assert MODES["separated"].use_composer is True


def test_no_mode_uses_local_role_files():
    for config in MODES.values():
        for part in config.parts:
            if part.source.type == "file":
                assert not str(part.source.value).startswith("role/")


def test_all_file_sources_exist():
    for config in MODES.values():
        for part in config.parts:
            if part.source.type == "file":
                path = _PROMPTS_DIR / f"{part.source.value}.md"
                assert path.is_file(), f"missing prompt file {path}"


@pytest.mark.parametrize("mode,workflow", sorted(_WORKFLOW_BY_MODE.items()))
def test_resolve_parts_embeds_workflow_text(mode, workflow):
    system_prompt, _messages = resolve_parts(
        MODES[mode].parts,
        mcp_client=ContractFakeMCPClient(),
        context={},
        enable_cache=False,
    )
    document = contract.read_workflows([workflow])["documents"][0]["content"]
    assert document.splitlines()[0] in system_prompt


def test_composer_loads_only_its_role_workflow():
    mcp_parts = [part for part in MODES["composer"].parts if part.source.type == "mcp"]
    assert [(part.source.value, part.source.args) for part in mcp_parts] == [
        ("read_workflows", {"names": ["composer"]}),
    ]


def test_orchestrator_carries_compose_report_wiring():
    values = [
        part.source.value
        for part in MODES["orchestrator"].parts
        if part.source.type == "file"
    ]
    assert "wiring/compose_report" in values


def test_style_creator_carries_remote_sandbox_wiring():
    values = [
        part.source.value
        for part in MODES["style_creator"].parts
        if part.source.type == "file"
    ]
    assert "wiring/style_remote" in values
    wiring_text = (_PROMPTS_DIR / "wiring" / "style_remote.md").read_text(encoding="utf-8")
    for token in ("style_name", "ref_styles", "persisted automatically"):
        assert token in wiring_text
    assert "save=True" not in wiring_text
