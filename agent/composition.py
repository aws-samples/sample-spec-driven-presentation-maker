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

import json
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
    pick: str = ""

    @classmethod
    def file(cls, name: str) -> "Source":
        """Load prompts/{name}.md."""
        return cls(type="file", value=name)

    @classmethod
    def mcp(cls, tool_name: str, args: dict, pick: str = "") -> "Source":
        """Call MCP tool and use returned text as content.

        ``pick`` selects part of a JSON result: a dotted path (``static.workflow``)
        yields that value (strings verbatim, anything else re-serialised as JSON);
        a comma-separated list of paths (``styles,templates``) yields a JSON object
        keyed by the last path segment. Identical (tool, args) calls are made once
        per resolve_parts run, so several parts may pick from one response.
        """
        return cls(type="mcp", value=tool_name, args=args, pick=pick)

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
    prefill_text: str = ""


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


def _walk(payload: Any, path: str) -> Any:
    node = payload
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            raise KeyError(f"'{path}' not in tool result")
        node = node[key]
    return node


def pick_from_text(text: str, pick: str) -> str:
    """Apply a Source.mcp ``pick`` expression to a JSON tool result."""
    if not pick:
        return text
    payload = json.loads(text)
    paths = [p.strip() for p in pick.split(",") if p.strip()]
    if len(paths) == 1:
        value = _walk(payload, paths[0])
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    picked = {path.rsplit(".", 1)[-1]: _walk(payload, path) for path in paths}
    return json.dumps(picked, ensure_ascii=False)


def _resolve_source(source: Source, mcp_client, context: dict, memo: dict | None = None) -> str:
    if source.type == "file":
        return _read_file(source.value)
    if source.type == "mcp":
        # Only picking sources share one call: they exist to slice a single
        # response. Plain Source.mcp keeps its one-call-per-part semantics.
        key = (source.value, json.dumps(source.args, sort_keys=True))
        if source.pick and memo is not None and key in memo:
            text = memo[key]
        else:
            text = _call_mcp(mcp_client, source.value, source.args)
            if source.pick and memo is not None:
                memo[key] = text
        return pick_from_text(text, source.pick) if text else text
    if source.type == "callable":
        return source.value(context)
    raise ValueError(f"Unknown source type: {source.type}")


def _tool_result_pair(
    label: str, content: str, prefill_text: str = "", tool_input: dict | None = None,
) -> list[dict]:
    """Build assistant toolUse + user toolResult pair for prefill."""
    tool_use_id = f"prefill-{uuid.uuid4().hex[:8]}"
    text = prefill_text or f"I'll read {label}."
    return [
        {
            "role": "assistant",
            "content": [
                {"text": text},
                {"toolUse": {"toolUseId": tool_use_id, "name": label, "input": tool_input or {}}},
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
    enable_cache: bool = True,
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
    memo: dict = {}

    for part in parts:
        content = _resolve_source(part.source, mcp_client, context, memo)
        if not content:
            continue
        if part.target == "system":
            system_chunks.append((content, part.cache_point))
        elif part.target == "history:tool_result":
            tool_input = part.source.args if part.source.type == "mcp" else None
            messages.extend(_tool_result_pair(
                part.label or "prefill", content, part.prefill_text, tool_input))
        elif part.target == "history:user":
            messages.append({"role": "user", "content": [{"text": content}]})
        elif part.target == "history:assistant":
            messages.append({"role": "assistant", "content": [{"text": content}]})
        else:
            raise ValueError(f"Unknown target: {part.target}")

    has_cache_point = enable_cache and any(cp for _, cp in system_chunks)

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
