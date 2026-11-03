# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP client factories and server instruction collection."""

import os
import urllib.parse

from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp import MCPClient

# MCP server definitions: (display_name, required)
MCP_DEFS: list[tuple[str, bool]] = [
    ("Presentation Maker", True),
    ("AWS Knowledge", False),
    ("AWS Pricing", False),
]


def mcp_agentcore_runtime(
    jwt_token: str,
    session_id: str = "",
    tool_filters: dict | None = None,
) -> MCPClient:
    """Pattern 1: Amazon Bedrock AgentCore Runtime MCP Server with JWT Bearer authentication.

    Args:
        jwt_token: JWT access token from the caller (without "Bearer " prefix).
        session_id: Caller's session id, sent as ``Mcp-Session-Id``. AgentCore
            routes by that header, so omitting it makes every request land on a
            new microVM — see the note below. Empty string disables the header.
        tool_filters: Optional tool filter dict (e.g. {"allowed": ["tool1", "tool2"]}).
    """
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    runtime_arn = os.environ["MCP_RUNTIME_ARN"]
    encoded_arn = urllib.parse.quote(runtime_arn, safe="")
    url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"

    headers = {"Authorization": f"Bearer {jwt_token}"}
    if session_id:
        # microVM stickiness: AgentCore routes MCP requests to a microVM by this
        # header. Without it the platform mints a fresh session id per request,
        # so every agent turn pays a new-session start on the MCP runtime. That
        # runtime's image is large (LibreOffice), and its cold start was measured
        # at 17.6-19.7s in ap-northeast-1 when no warm capacity was available,
        # versus 0.18-0.20s once requests carry a consistent id.
        #
        # An expired id is safe to keep sending: measured 2026-09-19, replaying an
        # id after the 900s idle timeout returns HTTP 200 (the platform treats it
        # like any unknown id and starts a session for it) and the call right
        # after is back to 0.18s. No re-initialize fallback is needed. This holds
        # for the stateless server we run (`stateless_http=True` in
        # servers/remote/server.py); stateful MCP is documented to 404 instead.
        headers["Mcp-Session-Id"] = session_id

    kwargs: dict = {}
    if tool_filters:
        kwargs["tool_filters"] = tool_filters

    return MCPClient(
        lambda: streamablehttp_client(
            url=url,
            headers=headers,
            timeout=120,
            terminate_on_close=False,
        ),
        **kwargs,
    )


AWS_KNOWLEDGE_URL = "https://knowledge-mcp.global.api.aws"

# The AWS documentation tools the agent offers its model. The allowlist pins the
# set even if the endpoint adds tools later.
AWS_KNOWLEDGE_TOOLS: list[str] = [
    "aws___search_documentation",
    "aws___read_documentation",
    "aws___retrieve_skill",
    "aws___list_regions",
    "aws___get_regional_availability",
]


def mcp_aws_knowledge() -> MCPClient:
    """Pattern 2: AWS Knowledge MCP Server (public endpoint, no authentication).

    The agent uses the AWS documentation tools only. The public endpoint serves
    exactly those and is called without the execution role's credentials.
    """
    return MCPClient(
        lambda: streamablehttp_client(url=AWS_KNOWLEDGE_URL),
        tool_filters={"allowed": list(AWS_KNOWLEDGE_TOOLS)},
    )


def mcp_aws_pricing() -> MCPClient:
    """Pattern 3: Local stdio MCP Server for AWS Pricing."""
    from mcp.client.stdio import StdioServerParameters, stdio_client

    return MCPClient(
        lambda: stdio_client(StdioServerParameters(
            command="awslabs.aws-pricing-mcp-server",
            env={**os.environ, "AWS_REGION": "us-east-1", "FASTMCP_LOG_LEVEL": "ERROR"},
        )),
    )


def collect_mcp_instructions(mcp_servers: list[MCPClient]) -> str:
    """Concatenate server_instructions from all MCP servers.

    Args:
        mcp_servers: List of initialized MCPClient instances.

    Returns:
        Concatenated instructions string (may be empty).
    """
    sections = [client.server_instructions for client in mcp_servers if client.server_instructions]
    return "\n\n".join(sections)
