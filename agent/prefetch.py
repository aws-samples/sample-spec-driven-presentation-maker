# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Prefetch helpers — shared by factory.py and composer.py."""

import uuid


def prefetch_sections(mcp_client, prefetch_list: list) -> list[str]:
    """Prefetch references from MCP server via synchronous tool calls."""
    sections = []
    for tool_name, args, label in prefetch_list:
        result = mcp_client.call_tool_sync(
            tool_use_id=f"prefetch-{uuid.uuid4().hex[:8]}",
            name=tool_name,
            arguments=args,
        )
        if result.get("status") == "error":
            raise RuntimeError(f"Failed to prefetch {label}: {result.get('content')}")
        text = ""
        for item in result.get("content", []):
            if isinstance(item, dict) and "text" in item:
                text += item["text"]
        if text:
            sections.append(f"## {label}\n\n{text}")
    return sections


def build_common_context(sections: list[str]) -> str:
    """Build common reference context string from prefetched sections."""
    if not sections:
        return ""
    return "# Pre-loaded References (already executed — do NOT re-fetch)\n\n" + "\n\n---\n\n".join(sections)


def inject_prefill(messages: list, sections: list[str], prefetch_list: list) -> None:
    """Inject prefetched content as fake tool call history.

    Only called when len(agent.messages) == 0 (new session).
    Restored sessions already contain the prefill from the first run.
    """
    for (tool_name, args, label), section in zip(prefetch_list, sections):
        tool_use_id = f"prefill-{uuid.uuid4().hex[:8]}"
        messages.extend([
            {
                "role": "assistant",
                "content": [
                    {"text": f"I'll read the {label} workflow."},
                    {"toolUse": {"toolUseId": tool_use_id, "name": tool_name, "input": args}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"toolResult": {"toolUseId": tool_use_id, "content": [{"text": section}], "status": "success"}},
                ],
            },
        ])
