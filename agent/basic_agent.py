# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Strands Agent entrypoint for spec-driven-presentation-maker.

AI model outputs should be reviewed before use in production contexts.

Uses Amazon Bedrock AgentCore Runtime for deployment.
JWT Bearer authentication — caller's JWT is forwarded to MCP Server.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.
"""

import base64
import json
import logging

from bedrock_agentcore.runtime import BedrockAgentCoreApp

import session_guard
import session_runtime
import stop_guard
from errors import BAD_INPUT, AUTH, error_event

logger = logging.getLogger("sdpm.agent")

# The lifespan installs the SIGTERM guard (stop_guard.py) in front of uvicorn's handler.
app = BedrockAgentCoreApp(lifespan=stop_guard.lifespan)

# Sessions and their turns (session_runtime.py): a working session holds a HealthyBusy
# task on /ping, and SIGTERM closes the sessions' clients.
session_runtime.configure(session_runtime.BusyTracker(app.add_async_task, app.complete_async_task))


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

    # Text only: the agent framework also accepts content-block lists, which
    # this entrypoint does not take from callers.
    if user_query is not None and not isinstance(user_query, str):
        yield error_event("Invalid field: prompt must be a string", code=BAD_INPUT)
        return

    if not all([user_query, session_id]):
        yield error_event("Missing required fields: prompt or runtimeSessionId", code=BAD_INPUT)
        return

    # Extract JWT from Authorization header
    auth_header = ""
    if hasattr(context, "request_headers") and context.request_headers:
        auth_header = context.request_headers.get("authorization", "") or context.request_headers.get("Authorization", "")
    jwt_token = auth_header.removeprefix("Bearer ").removeprefix("bearer ").strip()

    if not jwt_token:
        yield error_event("No JWT token found in Authorization header", code=AUTH)
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
        yield error_event("Could not extract user_id from JWT sub claim", code=AUTH)
        return

    # Only the session's owner gets in (session_guard.py); before the session registry,
    # so a refused call never touches a running turn.
    session_id, refusal = await session_guard.admit(session_id, getattr(context, "session_id", None), user_id)
    if refusal is not None:
        yield refusal
        return

    mode = payload.get("mode", "spec")
    async for event in session_runtime.http_turn(
        session_id, user_id, jwt_token, user_query, mode,
        payload.get("chatModelId"), payload.get("createModelId"),
    ):
        yield event


def main(port: int = 8080) -> None:
    # Bounded graceful shutdown: on SIGTERM uvicorn would otherwise wait for the running
    # /invocations without limit (see stop_guard.py).
    app.run(port=port, timeout_graceful_shutdown=stop_guard.GRACEFUL_SHUTDOWN_S)


if __name__ == "__main__":
    main()
