# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Personas are served to every MCP client — they must not hard-require
tools that only some adapters register.

Regression guard for the PR #231 review finding: a persona instructed
`get_preview(...)` unconditionally, but the local server does not register
that tool (it is a remote-only implementation; local previews are the PNG
files under <deck>/preview/). Any persona paragraph mentioning an
adapter-specific tool must present it conditionally and give the
file-based fallback IN THAT SAME PARAGRAPH — a whole-file search would be
satisfied by unrelated conditionals elsewhere (round-3 review note).

This is a targeted guard for the tools registered in _ADAPTER_ONLY_TOOLS,
not an automatic detector of every non-contract tool.
"""

import re
from pathlib import Path

import pytest

_PERSONAS = Path(__file__).resolve().parents[1] / "personas"

# Tools that exist only on some servers (not in the sdpm.tools contract).
# key: tool name, value: substring the same-paragraph fallback must contain.
_ADAPTER_ONLY_TOOLS = {
    "get_preview": "preview/",  # local fallback: <deck>/preview/<slug>.png
}

_CONDITIONAL_MARKERS = ("exists", "if available")


def _paragraphs(text: str) -> list[str]:
    """Split on blank lines — list items with continuation lines stay together."""
    return re.split(r"\n\s*\n", text)


@pytest.mark.parametrize("persona_path", sorted(_PERSONAS.glob("*.md")), ids=lambda p: p.name)
def test_adapter_only_tools_are_conditional_with_fallback(persona_path: Path):
    text = persona_path.read_text(encoding="utf-8")
    for tool, fallback in _ADAPTER_ONLY_TOOLS.items():
        mentions = [p for p in _paragraphs(text) if f"{tool}(" in p]
        for para in mentions:
            assert any(m in para for m in _CONDITIONAL_MARKERS), (
                f"{persona_path.name}: a paragraph calls {tool}() without gating it on "
                f"tool availability. {tool} is not part of the sdpm.tools contract "
                f"(remote-only), so the SAME paragraph must condition it "
                f"(one of {_CONDITIONAL_MARKERS}). Paragraph:\n{para}"
            )
            assert fallback in para, (
                f"{persona_path.name}: a paragraph calls {tool}() without the file-based "
                f"fallback for servers that do not register it (expected {fallback!r} "
                f"in the same paragraph). Paragraph:\n{para}"
            )


def test_guard_actually_fires():
    """Self-test: an unconditional mention must fail both checks."""
    bad = "Then call `get_preview(deck_id, slugs=[...])` to verify the slides."
    paras = _paragraphs(bad)
    assert [p for p in paras if "get_preview(" in p]
    assert not any(m in bad for m in _CONDITIONAL_MARKERS)
    assert "preview/" not in bad
