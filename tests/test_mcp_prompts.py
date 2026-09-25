# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP prompts are thin user-invoked entry points: one per role, naming the entry tool."""

import asyncio
import re
from pathlib import Path

import pytest

from sdpm.tools import prompts

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PROSE = ("# Role", "Layout pass.", "specs/brief.md", "## Skeleton")


@pytest.mark.parametrize("fn", prompts.PROMPTS, ids=lambda f: f.__name__)
def test_prompt_names_an_entry_tool_and_nothing_more(fn):
    kwargs = {"deck_id": "/tmp/deck", "language": "ja"} if fn is prompts.translate else {}
    text = fn(**kwargs)
    assert re.search(r"`start_(presentation|style|translation)\(", text)
    assert "follow the role document it returns" in text
    assert not any(p in text for p in _WORKFLOW_PROSE)
    assert len(text.splitlines()) <= 5


def test_vibe_and_spec_carry_the_interaction_token_the_orchestrator_defines():
    orchestrator = (_ROOT / "sdpm" / "references" / "workflows" / "orchestrator.md").read_text(encoding="utf-8")
    assert "`Interaction mode: dialogue`" in orchestrator and "`Interaction mode: fast`" in orchestrator
    assert prompts.vibe().startswith("Interaction mode: fast\n")
    assert prompts.spec().startswith("Interaction mode: dialogue\n")
    assert prompts.vibe("some material").rstrip().endswith("some material")


def test_prompts_are_registered_on_the_local_server():
    import importlib.util
    import sys

    local = _ROOT / "servers" / "local"
    for p in (str(local), str(_ROOT / "sdpm")):
        sys.path.insert(0, p)
    try:
        spec = importlib.util.spec_from_file_location("sdpm_local_server_prompts_test", local / "server.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        names = {p.name for p in asyncio.run(module.mcp.list_prompts())}
    finally:
        for p in (str(local), str(_ROOT / "sdpm")):
            sys.path.remove(p)
    assert names == {"sdpm-vibe", "sdpm-spec", "sdpm-style", "sdpm-translate"}
