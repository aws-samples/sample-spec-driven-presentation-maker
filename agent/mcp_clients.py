# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP client factories and server instruction collection."""

import logging
import os
import urllib.parse

from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp import MCPClient

logger = logging.getLogger("sdpm.agent")

# MCP server definitions: (display_name, required)
MCP_DEFS: list[tuple[str, bool]] = [
    ("Presentation Maker", True),
    ("AWS Knowledge", False),
    ("AWS Pricing", False),
]


def mcp_agentcore_runtime(jwt_token: str) -> MCPClient:
    """Pattern 1: Amazon Bedrock AgentCore Runtime MCP Server with JWT Bearer authentication.

    Args:
        jwt_token: JWT access token from the caller (without "Bearer " prefix).
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


def mcp_aws_knowledge() -> MCPClient:
    """Pattern 2: IAM-authenticated AWS Knowledge MCP with public fallback.

    Note: AWS MCP Server is currently only available in us-east-1.
    We hard-code the endpoint region regardless of the agent's region.
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
