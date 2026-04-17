# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Session message repair for interrupted sessions."""

import logging

logger = logging.getLogger("sdpm.agent")


def fix_excess_tool_results(messages: list) -> None:
    """Fix message list inconsistencies from interrupted sessions.

    Handles two cases:
    1. toolResult blocks with no matching toolUse in the previous assistant turn.
    2. Trailing assistant message with toolUse but no corresponding toolResult.

    Mutates messages in-place.
    """
    # --- Pass 1: Remove orphaned toolResult blocks ---
    i = 1
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") != "user":
            i += 1
            continue

        tool_results = [c for c in msg.get("content", []) if "toolResult" in c]
        if not tool_results:
            i += 1
            continue

        prev = messages[i - 1] if i > 0 else {}
        tool_use_ids = set()
        if prev.get("role") == "assistant":
            tool_use_ids = {
                c["toolUse"]["toolUseId"]
                for c in prev.get("content", [])
                if "toolUse" in c
            }

        original = msg["content"]
        msg["content"] = [
            c for c in original
            if "toolResult" not in c or c["toolResult"]["toolUseId"] in tool_use_ids
        ]

        if not msg["content"]:
            messages.pop(i)
        else:
            i += 1

    # --- Pass 2: Remove trailing assistant with unmatched toolUse ---
    if not messages:
        return
    last = messages[-1]
    if last.get("role") != "assistant":
        return
    if any("toolUse" in c for c in last.get("content", [])):
        logger.info("Removing trailing assistant message with unmatched toolUse")
        messages.pop()
