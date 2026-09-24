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
# mode -> (entry tool, first heading of the role document)
_ENTRY_BY_MODE = {
    "orchestrator": ("start_presentation", "# Orchestrator"),
    "vibe": ("start_presentation", "# Orchestrator"),
    "spec": ("start_presentation", "# Orchestrator"),
    "composer": ("start_composing", "# Composer"),
    "style_creator": ("start_style", "# Style"),
}


class ContractFakeMCPClient:
    """Fake MCP client dispatching synchronously to the real contract."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def call_tool_sync(self, tool_use_id: str, name: str, arguments: dict):
        del tool_use_id
        self.calls.append((name, arguments))
        fn = getattr(contract, name)
        result = fn(**arguments)
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return {"status": "success", "content": [{"text": text}]}


@pytest.mark.parametrize("mode,entry", sorted((m, e[0]) for m, e in _ENTRY_BY_MODE.items()))
def test_mode_fetches_role_document_via_entry_tool(mode, entry):
    """The role document comes from the role's entry tool, static part only, into system."""
    parts = MODES[mode].parts
    role_parts = [
        part for part in parts
        if part.source.type == "mcp" and part.source.pick == "static.workflow"
    ]
    assert len(role_parts) == 1
    assert role_parts[0].source.value == entry
    assert role_parts[0].source.args == {}
    assert role_parts[0].target == "system"


def test_no_mode_reads_workflows_through_the_retired_reader():
    for config in MODES.values():
        for part in config.parts:
            assert part.source.value not in ("read_workflows", "list_workflows")


def test_entry_tools_are_not_exposed_as_agent_tools():
    """The document is already in system; exposing start_* would invite a redundant call."""
    for config in MODES.values():
        for tool in config.allowed_tools or []:
            assert not tool.startswith("start_"), tool
            assert tool not in ("read_workflows", "list_workflows", "init_presentation")


def test_orchestrator_environment_is_system_after_cache_point():
    """Per-user styles/templates must not sit inside the cached prefix."""
    parts = MODES["orchestrator"].parts
    cache_idx = max(i for i, p in enumerate(parts) if p.cache_point)
    env = [i for i, p in enumerate(parts) if p.source.type == "mcp" and p.source.pick == "styles,templates"]
    assert len(env) == 1 and env[0] > cache_idx
    assert parts[env[0]].target == "system"
    assert "wiring/environment" in _file_parts("orchestrator")


def _file_parts(mode):
    return [str(p.source.value) for p in MODES[mode].parts if p.source.type == "file"]


@pytest.mark.parametrize("mode,token", [
    ("vibe", "wiring/interaction_fast"),
    ("spec", "wiring/interaction_dialogue"),
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
    workflow = contract.start_presentation()["static"]["workflow"]
    assert "`Interaction mode: dialogue`" in workflow
    assert "`Interaction mode: fast`" in workflow


def test_ui_modes_always_have_composers():
    """No mode drops compose_slides: the former "single" (no-composer) mode is gone."""
    for name in ("spec", "vibe", "orchestrator"):
        assert MODES[name].use_composer is True
    assert "single" not in MODES
    assert "separated" not in MODES
    assert not (_PROMPTS_DIR / "wiring" / "no_composers.md").exists()


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


@pytest.mark.parametrize("mode,entry", sorted(_ENTRY_BY_MODE.items()))
def test_resolve_parts_embeds_role_document_text(mode, entry):
    client = ContractFakeMCPClient()
    system_prompt, _messages = resolve_parts(
        MODES[mode].parts, mcp_client=client, context={}, enable_cache=False,
    )
    assert entry[1] in system_prompt
    # one entry call serves every part that picks from it
    assert [name for name, _ in client.calls].count(entry[0]) == 1


def test_orchestrator_system_carries_styles_but_not_deck_data():
    system_prompt, messages = resolve_parts(
        MODES["orchestrator"].parts, mcp_client=ContractFakeMCPClient(), context={}, enable_cache=False,
    )
    styles = contract.start_presentation()["styles"]
    assert styles and styles[0]["name"] in system_prompt
    assert messages == []


def test_composer_static_is_workflow_plus_slide_spec_and_cacheable():
    parts = MODES["composer"].parts
    assert [p.source.value for p in parts] == ["start_composing", "start_composing"]
    assert [p.source.pick for p in parts] == ["static.workflow", "static.slide_spec"]
    assert all(p.source.args == {} for p in parts)
    system_prompt, messages = resolve_parts(parts, mcp_client=ContractFakeMCPClient(), context={}, enable_cache=False)
    assert "# Composer" in system_prompt and "deck.json" in system_prompt
    assert messages == []


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


def test_pick_from_text_selects_paths():
    from composition import pick_from_text

    text = json.dumps({"static": {"workflow": "W"}, "styles": [1], "templates": [2], "x": {"y": {"z": 3}}})
    assert pick_from_text(text, "static.workflow") == "W"
    assert pick_from_text(text, "x.y.z") == "3"
    assert json.loads(pick_from_text(text, "styles,templates")) == {"styles": [1], "templates": [2]}
    assert pick_from_text(text, "") == text
    with pytest.raises(KeyError):
        pick_from_text(text, "static.nope")

