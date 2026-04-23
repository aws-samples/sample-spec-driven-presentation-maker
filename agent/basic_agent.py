# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Strands Agent for spec-driven-presentation-maker — uses Amazon Bedrock for LLM inference.

AI model outputs should be reviewed before use in production contexts.

Strands Agent for spec-driven-presentation-maker — connects to L3 MCP Server Runtime directly.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

Uses MCPClient + streamablehttp_client for MCP tool access.
JWT Bearer authentication — caller's JWT is forwarded to MCP Server.
"""

import asyncio
import json
import logging
import os
import traceback
import urllib.parse

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.models import BedrockModel
from strands.models.bedrock import CacheConfig
from strands.tools.mcp import MCPClient
from tools.upload_tools import list_uploads
from tools.web_tools import web_fetch
from tools.hearing_tool import hearing

logger = logging.getLogger("sdpm.agent")

app = BedrockAgentCoreApp()


# ---------------------------------------------------------------------------
# MCP Servers
#
# Register MCP servers here. Three connection patterns are supported:
#
#   Pattern 1: Amazon Bedrock AgentCore Runtime with JWT Bearer
#     - For MCP servers deployed on Amazon Bedrock AgentCore Runtime with JWT authentication
#     - Requires: Runtime ARN, caller's JWT token
#
#   Pattern 2: IAM-authenticated Remote MCP (with public fallback)
#     - For AWS-managed MCP servers (e.g. AWS Knowledge MCP)
#     - Primary: IAM-authenticated endpoint via mcp-proxy-for-aws
#     - Fallback: Public unauthenticated endpoint
#
#   Pattern 3: Local stdio MCP
#     - For MCP servers that run as local processes
#     - Requires: command to execute
#
# To add your own MCP server, create a MCPClient and add it to the
# `tools` list in create_agent().
# ---------------------------------------------------------------------------


def _mcp_agentcore_runtime(jwt_token: str) -> MCPClient:
    """Pattern 1: Amazon Bedrock AgentCore Runtime MCP Server with JWT Bearer authentication.

    Connects to spec-driven-presentation-maker MCP Server deployed on Amazon Bedrock AgentCore Runtime.
    Caller's JWT is forwarded as-is for authentication and user_id propagation.

    Args:
        jwt_token: JWT access token from the caller (without "Bearer " prefix).

    Returns:
        MCPClient for spec-driven-presentation-maker MCP Server.
    """
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    runtime_arn = os.environ["MCP_RUNTIME_ARN"]
    encoded_arn = urllib.parse.quote(runtime_arn, safe="")
    url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"

    return MCPClient(
        lambda: streamablehttp_client(
            url=url,
            headers={"Authorization": f"Bearer {jwt_token}"},
            timeout=120,
            terminate_on_close=False,
        ),
    )


def _mcp_aws_knowledge() -> MCPClient:
    """Pattern 2: IAM-authenticated AWS Knowledge MCP with public fallback.

    AWS Knowledge MCP provides access to AWS documentation, API references,
    What's New, Well-Architected guidance, and blog posts.

    Primary: IAM-authenticated endpoint (higher rate limits).
    Fallback: Public unauthenticated endpoint.

    Note: AWS MCP Server is currently only available in us-east-1.
    We hard-code the endpoint region regardless of the agent's region.

    Returns:
        MCPClient for AWS Knowledge MCP.
    """
    try:
        from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
        return MCPClient(
            lambda: aws_iam_streamablehttp_client(
                endpoint="https://aws-mcp.us-east-1.api.aws/mcp",
                aws_service="aws-mcp",
                aws_region="us-east-1",
            ),
        )
    except Exception:
        logger.warning("IAM auth unavailable for AWS Knowledge MCP, using public endpoint")
        return MCPClient(
            lambda: streamablehttp_client(url="https://knowledge-mcp.global.api.aws"),
        )


def _mcp_aws_pricing() -> MCPClient:
    """Pattern 3: Local stdio MCP Server.

    AWS Pricing MCP provides real-time pricing data via the AWS Pricing API.
    Runs as a local process using stdio transport.

    Returns:
        MCPClient for AWS Pricing MCP.
    """
    from mcp.client.stdio import StdioServerParameters, stdio_client

    # Pricing API is only available in us-east-1 and ap-south-1
    return MCPClient(
        lambda: stdio_client(StdioServerParameters(
            command="awslabs.aws-pricing-mcp-server",
            env={**os.environ, "AWS_REGION": "us-east-1", "FASTMCP_LOG_LEVEL": "ERROR"},
        )),
    )


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """Current date and time: {now}

You are a helpful assistant. You have access to various tools via MCP.
Follow the instructions provided by each MCP server to use their tools effectively.
Respond in the same language as the user.
{mcp_instructions}
## File Uploads
- When a user message contains [Attached: filename (uploadId: xxx)], use read_uploaded_file(upload_id, deck_id) to read content. If no deck exists yet, call init_presentation() first.
- For uploaded PDFs, use page_start=N to paginate through pages (e.g. page_start=20 reads pages 21-40). Always follow the truncation message to read remaining pages.
- Use list_uploads(session_id) to see all files in the current session

## Web Fetch
- Use web_fetch(url) to read a specific URL as Markdown
- For long HTML pages, use start=N (character offset) to continue reading from where it was truncated
- For PDFs, use page_start=N to paginate through pages (e.g. page_start=5 reads pages 6-10). Always follow the truncation message to read remaining pages.
- If a user message starts with <!--sdpm:include_images=true-->, pass include_images=true when calling web_fetch on HTML pages to preserve image URLs in the output.
- To use a web image in slides: call save_web_image(url, deck_id) with the image URL. It downloads the image to the deck workspace and returns {"src": "images/filename"} for use in slide JSON.
- Do NOT use read_uploaded_file for web images — use save_web_image instead.
"""


def _build_system_prompt(mcp_instructions: str) -> str:
    """Build system prompt with current timestamp and MCP server instructions.

    Args:
        mcp_instructions: Concatenated instructions from MCP servers.

    Returns:
        Formatted system prompt string.
    """
    from datetime import datetime, timedelta, timezone

    jst = timezone(timedelta(hours=9))
    now_str = datetime.now(jst).strftime("%Y-%m-%d %H:%M JST")
    return _SYSTEM_PROMPT_TEMPLATE.replace("{now}", now_str).replace("{mcp_instructions}", mcp_instructions)


# ---------------------------------------------------------------------------
# Agent Factory
# ---------------------------------------------------------------------------

# MCP server definitions: (factory, display_name, required)
_MCP_DEFS: list[tuple[str, bool]] = [
    ("Presentation Maker", True),
    ("AWS Knowledge", False),
    ("AWS Pricing", False),
]


def _collect_mcp_instructions(mcp_servers: list[MCPClient]) -> str:
    """Collect server_instructions from all MCP servers.

    Each MCPClient exposes server_instructions (str | None) after initialization.
    This function concatenates non-None instructions into a single string
    for injection into the system prompt.

    Args:
        mcp_servers: List of initialized MCPClient instances.

    Returns:
        Concatenated instructions string (may be empty if no server provides instructions).
    """
    sections: list[str] = []
    for client in mcp_servers:
        instr = client.server_instructions
        if instr:
            sections.append(instr)
    return "\n\n".join(sections)


def create_agent(user_id: str, session_id: str, jwt_token: str) -> tuple[Agent, list[dict]]:
    """Create a Strands Agent with MCP tools and memory.

    MCP servers are initialized first so that server_instructions can be
    collected and injected into the system prompt (MCP spec compliance).
    Optional MCP servers that fail to initialize are skipped.

    Args:
        user_id: User identifier (JWT sub claim).
        session_id: Conversation session ID.
        jwt_token: JWT access token for MCP Server authentication.

    Returns:
        Tuple of (Configured Strands Agent instance, MCP status list).
    """
    memory_id = os.environ.get("MEMORY_ID", "")
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

    # Set user_id for upload tools
    import tools.upload_tools as _ut
    _ut._current_user_id = user_id

    session_manager = None
    if memory_id and memory_id != "PLACEHOLDER":
        from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
        from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

        memory_config = AgentCoreMemoryConfig(
            memory_id=memory_id, session_id=session_id, actor_id=user_id,
        )
        session_manager = AgentCoreMemorySessionManager(
            agentcore_memory_config=memory_config, region_name=region,
        )

    model = BedrockModel(
        model_id=os.environ.get("MODEL_ID", "global.anthropic.claude-sonnet-4-6"),
        temperature=0.1,
        cache_config=CacheConfig(strategy="auto"),
    )

    # --- Build MCP server list with resilience ---
    factories = [
        lambda: _mcp_agentcore_runtime(jwt_token=jwt_token),
        _mcp_aws_knowledge,
        _mcp_aws_pricing,
    ]

    mcp_servers: list[MCPClient] = []
    mcp_status: list[dict] = []

    for (name, required), factory in zip(_MCP_DEFS, factories):
        try:
            mcp_servers.append(factory())
            mcp_status.append({"name": name, "status": "ok"})
        except Exception as e:
            mcp_status.append({"name": name, "status": "error", "error": str(e)})
            if required:
                raise

    # Agent.__init__ triggers MCP client connections.
    # If optional MCP servers fail during init, retry with required-only.
    tools = [*mcp_servers, list_uploads, web_fetch, hearing]
    try:
        agent = Agent(
            name="SdpmAgent",
            system_prompt="",
            tools=tools,
            model=model,
            session_manager=session_manager,
            trace_attributes={"user.id": user_id, "session.id": session_id},
        )
    except Exception as init_err:
        init_reason = str(init_err)
        logger.warning("Agent init failed with all MCP servers, retrying with required-only: %s", init_reason)
        # Keep only required MCP servers
        required_servers = []
        new_status = []
        for (name, required), st in zip(_MCP_DEFS, mcp_status):
            if required and st["status"] == "ok":
                required_servers.append(mcp_servers[len(new_status)])
                new_status.append(st)
            else:
                if st["status"] == "ok":
                    new_status.append({"name": name, "status": "error", "error": "Service unavailable"})
                else:
                    new_status.append(st)

        mcp_servers = required_servers
        mcp_status = new_status
        agent = Agent(
            name="SdpmAgent",
            system_prompt="",
            tools=[*mcp_servers, list_uploads, web_fetch, hearing],
            model=model,
            session_manager=session_manager,
            trace_attributes={"user.id": user_id, "session.id": session_id},
        )

    # Now that MCP clients are initialized, inject their instructions.
    agent.system_prompt = _build_system_prompt(
        mcp_instructions=_collect_mcp_instructions(mcp_servers),
    )

    return agent, mcp_status


# ---------------------------------------------------------------------------
# Session fix
# ---------------------------------------------------------------------------


def _fix_excess_tool_results(messages: list) -> None:
    """Fix message list inconsistencies from interrupted sessions.

    Handles two cases:
    1. toolResult blocks with no matching toolUse in the previous assistant turn
       (orphaned results from interrupted sessions).
    2. Trailing assistant message with toolUse but no corresponding toolResult
       (interrupted mid-tool-execution — safety net, should not happen with
       safe cancellation points but protects against edge cases).

    Mutates messages in-place.

    Args:
        messages: The agent's message list (restored from session).
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
    has_tool_use = any("toolUse" in c for c in last.get("content", []))
    if not has_tool_use:
        return
    # Check if next message (doesn't exist — it's the last) has matching toolResults
    # Since it's the last message, there's no toolResult → remove it
    logger.info("Removing trailing assistant message with unmatched toolUse")
    messages.pop()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

KEEPALIVE_INTERVAL = 5

# Cancel registry: session_id → asyncio.Event.
# When a new request arrives for the same session, the previous request's
# Event is set, signalling it to stop at the next safe point.
_cancel_events: dict[str, asyncio.Event] = {}


@app.entrypoint
async def agent_stream(payload, context):
    """Main entrypoint for Amazon Bedrock AgentCore Runtime streaming invocation.

    Args:
        payload: Dict with prompt, userId, runtimeSessionId.
        context: RequestContext with request_headers (JWT forwarded by Runtime).

    Yields:
        Streaming events (Converse API format + keepalive).
    """
    user_query = payload.get("prompt")
    session_id = payload.get("runtimeSessionId")

    if not all([user_query, session_id]):
        yield {"status": "error", "error": "Missing required fields: prompt or runtimeSessionId"}
        return

    # Extract JWT from Authorization header (forwarded by Runtime via requestHeaderAllowList)
    auth_header = ""
    if hasattr(context, "request_headers") and context.request_headers:
        auth_header = context.request_headers.get("authorization", "") or context.request_headers.get("Authorization", "")
    jwt_token = auth_header.removeprefix("Bearer ").removeprefix("bearer ").strip()

    if not jwt_token:
        yield {"status": "error", "error": "No JWT token found in Authorization header"}
        return

    # Extract user_id from JWT sub (Runtime has already validated the token)
    import base64
    try:
        jwt_payload = jwt_token.split(".")[1]
        jwt_payload += "=" * (4 - len(jwt_payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(jwt_payload))
        user_id = claims.get("sub", "")
    except (IndexError, ValueError, json.JSONDecodeError):
        user_id = ""
    if not user_id:
        yield {"status": "error", "error": "Could not extract user_id from JWT sub claim"}
        return

    # --- Cancel previous request for the same session ---
    prev_cancel = _cancel_events.get(session_id)
    if prev_cancel is not None:
        prev_cancel.set()
        logger.info("Signalled previous request cancellation for session %s", session_id[:12])

    cancel = asyncio.Event()
    _cancel_events[session_id] = cancel

    try:
        os.environ["_CURRENT_SESSION_ID"] = session_id
        agent, mcp_status = create_agent(user_id=user_id, session_id=session_id, jwt_token=jwt_token)

        # Emit MCP status as the first SSE event
        yield {"mcp_status": mcp_status}

        _fix_excess_tool_results(agent.messages)

        async def _next(aiter):
            """Get next event from async iterator."""
            return await aiter.__anext__()

        stream_iter = agent.stream_async(user_query).__aiter__()
        pending = None
        last_tool_use = None
        last_tool_use_id = ""
        last_yielded_input: dict = {}  # track last emitted partial input
        tool_name_map: dict[str, str] = {}  # toolUseId → tool name
        in_tool_execution = False  # True between toolUse emission and toolResult receipt

        def _try_partial_parse(raw) -> dict | None:
            """Attempt partial JSON parse for incremental toolUse streaming."""
            if isinstance(raw, dict):
                return raw if raw else None
            if not isinstance(raw, str) or not raw:
                return None
            try:
                from partial_json_parser import loads as partial_loads
                parsed = partial_loads(raw)
                return parsed if isinstance(parsed, dict) and parsed else None
            except Exception:
                return None

        def _tool_payload(tu: dict) -> dict:
            """Build toolUse SSE payload from accumulated tool use data."""
            import json as _json
            raw = tu.get("input", "")
            try:
                parsed = _json.loads(raw) if isinstance(raw, str) and raw else raw
            except (ValueError, TypeError):
                parsed = {}
            return {"toolUse": {"name": tu.get("name", ""), "toolUseId": tu.get("toolUseId", ""), "input": parsed if isinstance(parsed, dict) else {}}}

        def _should_stop() -> bool:
            """Check if cancellation was requested and it is safe to stop.

            Safe to stop when not in the middle of tool execution
            (between toolUse emission and toolResult receipt).

            Returns:
                True if the stream should be terminated.
            """
            return cancel.is_set() and not in_tool_execution

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
                            last_yielded_input = {}
                            tool_name_map[tu_id] = tu.get("name", "")
                            in_tool_execution = True
                            yield {"toolStart": {"name": tu.get("name", ""), "toolUseId": tu_id}}
                        last_tool_use = dict(tu)
                        # Early-emit partial input so UI can render incrementally
                        parsed = _try_partial_parse(tu.get("input", ""))
                        if parsed and parsed != last_yielded_input:
                            last_yielded_input = parsed
                            yield {"toolUse": {"name": tu.get("name", ""), "toolUseId": tu_id, "input": parsed}}
                    elif isinstance(event, dict) and event.get("type") == "tool_result":
                        # ToolResultEvent — not yielded by stream_async (is_callback_event=False)
                        # Handled via ToolResultMessageEvent below instead
                        pass
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

                    # Check cancellation at safe points
                    if _should_stop():
                        logger.info("Stopping stream for session %s", session_id[:12])
                        break

                except StopAsyncIteration:
                    if last_tool_use:
                        yield _tool_payload(last_tool_use)
                    break
            else:
                yield {"keepalive": True}
                # Also check cancellation during idle periods
                if _should_stop():
                    logger.info("Stopping stream (idle) for session %s", session_id[:12])
                    break

    except Exception as e:
        logger.exception("Agent stream error for session %s", session_id[:12])
        yield {"status": "error", "error": str(e)}
    finally:
        # Clean up cancel registry (only if we still own it)
        if _cancel_events.get(session_id) is cancel:
            del _cancel_events[session_id]


if __name__ == "__main__":
    app.run()
