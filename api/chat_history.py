# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Chat history response shaping — keep GET /chat under Lambda's 6MB limit.

Pure functions (no boto3 / Powertools) so they are unit-testable outside
the Lambda bundle. Three defenses, applied in order by get_chat:

1. strip_tool_result_content — toolResult bodies are only needed by the
   agent (which reads AgentCore Memory directly); the UI needs status only.
2. truncate_tool_inputs — toolUse.input can embed entire slide JSON bodies.
   The UI renders only short scalar fields (slide_id, purpose, instruction,
   slide_groups), so long strings are cut.
3. cap_messages_size — backstop: drop oldest messages until the serialized
   payload fits, keeping the most recent conversation visible.
"""

import json
from typing import Any, Dict, List, Tuple

# Per-string cap inside toolUse.input. Generous enough that slide_groups
# (JSON-encoded string parsed by ComposeCard) survives intact in practice,
# while slide JSON bodies (tens of KB each) are slashed.
MAX_INPUT_STR = 8_000

# Serialized messages budget — headroom below the 6MB Lambda response limit
# for the JSON envelope and transport overhead.
MAX_MESSAGES_BYTES = 4_500_000

TRUNCATION_MARKER = "…[truncated]"


def strip_tool_result_content(messages: List[Dict]) -> None:
    """Empty toolResult content blocks in place — frontend needs status only."""
    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and "toolResult" in block:
                    block["toolResult"]["content"] = []


def _truncate_value(value: Any) -> Any:
    """Recursively cap string lengths inside a toolUse input value."""
    if isinstance(value, str) and len(value) > MAX_INPUT_STR:
        return value[:MAX_INPUT_STR] + TRUNCATION_MARKER
    if isinstance(value, dict):
        return {k: _truncate_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate_value(v) for v in value]
    return value


def truncate_tool_inputs(messages: List[Dict]) -> None:
    """Cap long strings inside toolUse.input blocks in place."""
    for msg in messages:
        if not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if isinstance(block, dict) and "toolUse" in block:
                tool_use = block["toolUse"]
                if isinstance(tool_use.get("input"), dict):
                    tool_use["input"] = _truncate_value(tool_use["input"])


def cap_messages_size(
    messages: List[Dict], max_bytes: int = MAX_MESSAGES_BYTES,
) -> Tuple[List[Dict], bool]:
    """Drop oldest messages until the serialized payload fits max_bytes.

    Returns:
        (messages, truncated) — truncated is True if any message was dropped.
    """
    sizes = [len(json.dumps(m, ensure_ascii=False).encode("utf-8")) for m in messages]
    total = sum(sizes)
    if total <= max_bytes:
        return messages, False

    start = 0
    while start < len(messages) - 1 and total > max_bytes:
        total -= sizes[start]
        start += 1
    return messages[start:], True
