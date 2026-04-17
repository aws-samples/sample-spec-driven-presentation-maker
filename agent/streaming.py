# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""SSE streaming: event transformation, keepalive, and cancellation management."""

import asyncio
import json
import logging
from typing import AsyncGenerator

from strands import Agent

logger = logging.getLogger("sdpm.agent")

KEEPALIVE_INTERVAL = 5


async def stream_agent(agent: Agent, user_query: str, session_id: str, cancel: asyncio.Event) -> AsyncGenerator:
    """Stream agent responses as SSE events with keepalive and safe cancellation.

    Args:
        agent: Initialized Strands Agent.
        user_query: User's input message.
        session_id: Session ID (for logging).
        cancel: Event that signals cancellation request.

    Yields:
        SSE event dicts.
    """
    last_tool_use = None
    last_tool_use_id = ""
    tool_name_map: dict[str, str] = {}
    in_tool_execution = False

    def _tool_payload(tu: dict) -> dict:
        raw = tu.get("input", "")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) and raw else raw
        except (ValueError, TypeError):
            parsed = {}
        return {"toolUse": {"name": tu.get("name", ""), "toolUseId": tu.get("toolUseId", ""), "input": parsed if isinstance(parsed, dict) else {}}}

    def _should_stop() -> bool:
        return cancel.is_set() and not in_tool_execution

    async def _next(aiter):
        return await aiter.__anext__()

    stream_iter = agent.stream_async(user_query).__aiter__()
    pending = None

    while True:
        if pending is None:
            pending = asyncio.ensure_future(_next(stream_iter))
        done, _ = await asyncio.wait({pending}, timeout=KEEPALIVE_INTERVAL)
        if done:
            try:
                event = pending.result()
                if isinstance(event, dict) and "event" in event:
                    yield event
                elif isinstance(event, dict) and "current_tool_use" in event:
                    tu = event["current_tool_use"]
                    tu_id = tu.get("toolUseId", "")
                    if tu_id and tu_id != last_tool_use_id:
                        if last_tool_use:
                            yield _tool_payload(last_tool_use)
                        last_tool_use_id = tu_id
                        tool_name_map[tu_id] = tu.get("name", "")
                        in_tool_execution = True
                        yield {"toolStart": {"name": tu.get("name", ""), "toolUseId": tu_id}}
                    last_tool_use = dict(tu)
                elif isinstance(event, dict) and "tool_stream_event" in event:
                    tse = event["tool_stream_event"]
                    data = tse.get("data")
                    tu = tse.get("tool_use", {})
                    if isinstance(data, dict):
                        yield {"toolStream": {"toolUseId": tu.get("toolUseId", last_tool_use_id), "name": tu.get("name", ""), "data": data}}
                elif isinstance(event, dict) and "message" in event:
                    msg = event["message"]
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        for block in msg.get("content", []):
                            if isinstance(block, dict) and "toolResult" in block:
                                tr = block["toolResult"]
                                tu_id = tr.get("toolUseId", "")
                                content_text = ""
                                for c in tr.get("content", []):
                                    if isinstance(c, dict) and "text" in c:
                                        content_text = c["text"]
                                        break
                                in_tool_execution = False
                                yield {"toolResult": {
                                    "toolUseId": tu_id,
                                    "name": tool_name_map.get(tu_id, ""),
                                    "status": tr.get("status", "success"),
                                    "content": content_text,
                                }}
                pending = None

                if _should_stop():
                    logger.info("Stopping stream for session %s", session_id[:12])
                    break

            except StopAsyncIteration:
                if last_tool_use:
                    yield _tool_payload(last_tool_use)
                break
        else:
            yield {"keepalive": True}
            if _should_stop():
                logger.info("Stopping stream (idle) for session %s", session_id[:12])
                break
