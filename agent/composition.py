# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Prompt composition — declarative agent prompt/history assembly.

Source: how content is fetched (file / mcp / callable).
Part: Source + target (system / history:*).
resolve_parts: turns list[Part] into (system_prompt, messages).

When any Part has cache_point=True, the system prompt is returned as
Bedrock content blocks (list[dict]) with a cachePoint inserted after that part.
Otherwise it is returned as a plain string.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Union

SourceType = Literal["file", "mcp", "callable"]
Target = Literal["system", "history:user", "history:assistant", "history:tool_result"]

_PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class Source:
    """Content fetch method."""
    type: SourceType
    value: Union[str, Callable[[dict], str]]
    args: dict = field(default_factory=dict)

    @classmethod
    def file(cls, name: str) -> "Source":
        """Load prompts/{name}.md."""
        return cls(type="file", value=name)

    @classmethod
    def mcp(cls, tool_name: str, args: dict) -> "Source":
        """Call MCP tool and use returned text as content."""
        return cls(type="mcp", value=tool_name, args=args)

    @classmethod
    def call(cls, fn: Callable[[dict], str]) -> "Source":
        """Invoke fn(context) at resolve time for dynamic content."""
        return cls(type="callable", value=fn)


@dataclass
class Part:
    """Prompt part: content source + injection target.

    Set cache_point=True to insert a Bedrock cachePoint after this part's
    system text.  Parts after the cache point hold dynamic content (e.g.
    timestamps) that should not invalidate the cache.
    """
    source: Source
    target: Target
    label: str = ""
    cache_point: bool = False


def _read_file(name: str) -> str:
    return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def _call_mcp(mcp_client, tool_name: str, args: dict) -> str:
    """Call an MCP tool synchronously and concatenate text content."""
    if mcp_client is None:
        return ""
    result = mcp_client.call_tool_sync(
        tool_use_id=f"resolve-{uuid.uuid4().hex[:8]}",
        name=tool_name,
        arguments=args,
    )
    if result.get("status") == "error":
        raise RuntimeError(f"MCP call failed ({tool_name}): {result.get('content')}")
    text = ""
    for item in result.get("content", []):
        if isinstance(item, dict) and "text" in item:
            text += item["text"]
    return text


def _resolve_source(source: Source, mcp_client, context: dict) -> str:
    if source.type == "file":
        return _read_file(source.value)
    if source.type == "mcp":
        return _call_mcp(mcp_client, source.value, source.args)
    if source.type == "callable":
        return source.value(context)
    raise ValueError(f"Unknown source type: {source.type}")


def _tool_result_pair(label: str, content: str) -> list[dict]:
    """Build assistant toolUse + user toolResult pair for prefill."""
    tool_use_id = f"prefill-{uuid.uuid4().hex[:8]}"
    return [
        {
            "role": "assistant",
            "content": [
                {"text": f"I'll read {label}."},
                {"toolUse": {"toolUseId": tool_use_id, "name": label, "input": {}}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"toolResult": {
                    "toolUseId": tool_use_id,
                    "content": [{"text": content}],
                    "status": "success",
                }},
            ],
        },
    ]


def _apply_placeholders(text: str, context: dict) -> str:
    """Replace {now} and any context keys in text."""
    jst = timezone(timedelta(hours=9))
    out = text.replace("{now}", datetime.now(jst).strftime("%Y-%m-%d %H:%M JST"))
    for k, v in context.items():
        if isinstance(v, str):
            out = out.replace("{" + k + "}", v)
    return out


def resolve_parts(
    parts: list[Part],
    mcp_client: Any = None,
    context: dict | None = None,
) -> tuple[str | list[dict], list[dict]]:
    """Resolve parts into (system_prompt, messages).

    Args:
        parts: List of Part definitions.
        mcp_client: MCP client for Source.mcp (may be None if no mcp sources).
        context: Values for callable sources and placeholder substitution.

    Returns:
        Tuple of (system prompt, initial messages list).
        system prompt is a plain string when no cache_point is used,
        or a list of Bedrock content blocks when cache_point is present.
    """
    context = context or {}
    # Collect system chunks as (text, cache_point_after) pairs
    system_chunks: list[tuple[str, bool]] = []
    messages: list[dict] = []

    for part in parts:
        content = _resolve_source(part.source, mcp_client, context)
        if not content:
            continue
        if part.target == "system":
            system_chunks.append((content, part.cache_point))
        elif part.target == "history:tool_result":
            messages.extend(_tool_result_pair(part.label or "prefill", content))
        elif part.target == "history:user":
            messages.append({"role": "user", "content": [{"text": content}]})
        elif part.target == "history:assistant":
            messages.append({"role": "assistant", "content": [{"text": content}]})
        else:
            raise ValueError(f"Unknown target: {part.target}")

    has_cache_point = any(cp for _, cp in system_chunks)

    if has_cache_point:
        # Build Bedrock content blocks, grouping consecutive chunks between cache points
        blocks: list[dict] = []
        buf: list[str] = []
        for text, cp in system_chunks:
            buf.append(text)
            if cp:
                blocks.append({"text": _apply_placeholders("\n\n".join(buf), context)})
                blocks.append({"cachePoint": {"type": "default"}})
                buf = []
        if buf:
            blocks.append({"text": _apply_placeholders("\n\n".join(buf), context)})
        return blocks, messages
    else:
        all_text = "\n\n".join(t for t, _ in system_chunks)
        return _apply_placeholders(all_text, context), messages
