# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Personas are served to every MCP client — they must not hard-require
tools that only some adapters register.

Regression guard for the PR #231 review finding: a persona instructed
`get_preview(...)` unconditionally, but the local server does not register
that tool (it is a remote-only implementation; local previews are the PNG
files under <deck>/preview/). Any persona mentioning an adapter-specific
tool must present it conditionally and give the file-based fallback.
"""

from pathlib import Path

import pytest

_PERSONAS = Path(__file__).resolve().parents[1] / "personas"

# Tools that exist only on some servers (not in the sdpm.tools contract).
# key: tool name, value: substring the fallback instruction must contain.
_ADAPTER_ONLY_TOOLS = {
    "get_preview": "preview/",  # local fallback: <deck>/preview/<slug>.png
}


@pytest.mark.parametrize("persona_path", sorted(_PERSONAS.glob("*.md")), ids=lambda p: p.name)
def test_adapter_only_tools_are_conditional_with_fallback(persona_path: Path):
    text = persona_path.read_text(encoding="utf-8")
    for tool, fallback in _ADAPTER_ONLY_TOOLS.items():
        if f"{tool}(" not in text:
            continue
        assert "exists" in text or "if available" in text, (
            f"{persona_path.name} calls {tool}() unconditionally — it is not part of "
            "the sdpm.tools contract, so gate it on tool availability."
        )
        assert fallback in text, (
            f"{persona_path.name} mentions {tool}() but gives no fallback for servers "
            f"that do not register it (expected mention of {fallback!r})."
        )
