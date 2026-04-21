# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Strands Agent entrypoint for spec-driven-presentation-maker.

AI model outputs should be reviewed before use in production contexts.

Uses Amazon Bedrock AgentCore Runtime for deployment.
JWT Bearer authentication — caller's JWT is forwarded to MCP Server.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.
"""

import asyncio
import base64
import json
import logging
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from modes.separated.factory import create_separated_agent
from modes.single.factory import create_single_agent
from streaming import stream_agent

logger = logging.getLogger("sdpm.agent")

app = BedrockAgentCoreApp()

# Cancel registry: session_id → asyncio.Event.
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

    # Extract JWT from Authorization header
    auth_header = ""
    if hasattr(context, "request_headers") and context.request_headers:
        auth_header = context.request_headers.get("authorization", "") or context.request_headers.get("Authorization", "")
    jwt_token = auth_header.removeprefix("Bearer ").removeprefix("bearer ").strip()

    if not jwt_token:
        yield {"status": "error", "error": "No JWT token found in Authorization header"}
        return

    # Extract user_id from JWT sub
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

    # Cancel previous request for the same session
    prev_cancel = _cancel_events.get(session_id)
    if prev_cancel is not None:
        prev_cancel.set()
        logger.info("Signalled previous request cancellation for session %s", session_id[:12])

    cancel = asyncio.Event()
    _cancel_events[session_id] = cancel

    try:
        os.environ["_CURRENT_SESSION_ID"] = session_id
        mode = payload.get("mode", "separated")
        if mode == "single":
            agent, mcp_status = create_single_agent(user_id=user_id, session_id=session_id, jwt_token=jwt_token)
        elif mode == "vibe":
            agent, mcp_status = create_separated_agent(user_id=user_id, session_id=session_id, jwt_token=jwt_token, prompt_key="vibe_agent")
        else:
            agent, mcp_status = create_separated_agent(user_id=user_id, session_id=session_id, jwt_token=jwt_token)

        yield {"mcp_status": mcp_status}

        async for event in stream_agent(agent, user_query, session_id, cancel):
            yield event

    except Exception as e:
        logger.exception("Agent stream error for session %s", session_id[:12])
        yield {"status": "error", "error": str(e)}
    finally:
        if _cancel_events.get(session_id) is cancel:
            del _cancel_events[session_id]


if __name__ == "__main__":
    app.run()
