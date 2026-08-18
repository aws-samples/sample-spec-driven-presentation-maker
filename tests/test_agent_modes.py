# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""L4 agent mode definitions — personas served through the start_presentation port.

Verifies that:
- every mode's persona part fetches from the contract (single source of truth),
- every Source.file reference points at an existing file under agent/prompts/,
- resolve_parts embeds the actual personas/*.md text into the system prompt
  (end-to-end through the real sdpm.tools contract).
"""

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_AGENT_DIR = _ROOT / "agent"

# agent/ modules use flat imports (from composition import ...), so agent/ must
# be on sys.path during import — but only during import: leaving it there would
# shadow the servers/remote `tools` package used by other tests.
sys.path.insert(0, str(_AGENT_DIR))
try:
    from composition import resolve_parts
    from modes import MODES
finally:
    sys.path.remove(str(_AGENT_DIR))

from sdpm import tools as contract  # noqa: E402

_PROMPTS_DIR = _AGENT_DIR / "prompts"

# L4 mode id -> persona mode served by start_presentation
_PERSONA_BY_MODE = {
    "separated": "spec",
    "vibe": "vibe",
    "composer": "composer",
    "style_creator": "style",
}


class ContractFakeMCPClient:
    """Fake MCP client that dispatches call_tool_sync to the real contract.

    Mirrors how the remote server binds sdpm.tools functions, so the test
    exercises the actual persona files and reference documents.
    """

    def call_tool_sync(self, tool_use_id: str, name: str, arguments: dict):
        fn = getattr(contract, name)
        result = fn(**arguments)
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return {"status": "success", "content": [{"text": text}]}


@pytest.mark.parametrize("mode,persona", sorted(_PERSONA_BY_MODE.items()))
def test_mode_fetches_persona_via_port(mode, persona):
    """Each mode has exactly one mcp part calling start_presentation(mode=...)."""
    parts = MODES[mode].parts
    persona_parts = [
        p for p in parts
        if p.source.type == "mcp" and p.source.value == "start_presentation"
    ]
    assert len(persona_parts) == 1
    assert persona_parts[0].source.args == {"mode": persona}
    assert persona_parts[0].target == "system"


def test_no_mode_uses_local_role_files():
    """Behavior text must not come from agent-local role files (personas port only).

    single mode is the deliberate exception: a 3-line generic prompt with no
    persona equivalent (not served by start_presentation's _MODES).
    """
    for mode, cfg in MODES.items():
        if mode == "single":
            continue
        for part in cfg.parts:
            if part.source.type == "file":
                assert not str(part.source.value).startswith("role/"), (
                    f"{mode} still reads a local role file: {part.source.value}"
                )


def test_all_file_sources_exist():
    """Every Source.file reference resolves to an existing prompts/*.md file."""
    for mode, cfg in MODES.items():
        for part in cfg.parts:
            if part.source.type == "file":
                path = _PROMPTS_DIR / f"{part.source.value}.md"
                assert path.is_file(), f"{mode}: missing prompt file {path}"


@pytest.mark.parametrize("mode,heading", [
    ("separated", "# SPEC mode"),
    ("vibe", "# VIBE mode"),
    ("composer", "# COMPOSER"),
    ("style_creator", "# STYLE mode"),
])
def test_resolve_parts_embeds_persona_text(mode, heading):
    """resolve_parts pulls the real personas/*.md text into the system prompt."""
    system_prompt, _messages = resolve_parts(
        MODES[mode].parts,
        mcp_client=ContractFakeMCPClient(),
        context={},
        enable_cache=False,
    )
    assert isinstance(system_prompt, str)
    assert heading in system_prompt
    # The persona must land in the system prompt, not just any part
    persona_text = (_ROOT / "personas" / f"{_PERSONA_BY_MODE[mode]}.md").read_text(
        encoding="utf-8"
    )
    assert persona_text.splitlines()[0] in system_prompt


def test_compose_report_wiring_is_l4_delta_only():
    """Orchestrator modes carry the compose_slides report wiring after the persona."""
    for mode in ("separated", "vibe"):
        values = [p.source.value for p in MODES[mode].parts if p.source.type == "file"]
        assert "wiring/compose_report" in values


def test_style_creator_carries_remote_sandbox_wiring():
    """The style persona documents the local read_style/write_style sandbox;
    Remote's run_style_python uses style_name/ref_styles file I/O instead, so
    L4 must inject the adapter-specific I/O as wiring (review finding, PR #231).
    Writes persist automatically (run-python-unified-semantics SPEC) — the
    wiring must say so and must NOT teach a save flag.
    """
    values = [p.source.value for p in MODES["style_creator"].parts if p.source.type == "file"]
    assert "wiring/style_remote" in values
    wiring_text = (_PROMPTS_DIR / "wiring" / "style_remote.md").read_text(encoding="utf-8")
    for token in ("style_name", "ref_styles", "persisted automatically"):
        assert token in wiring_text
    assert "save=True" not in wiring_text
