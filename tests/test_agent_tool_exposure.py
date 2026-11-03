# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The agent offers its model only the AWS documentation tools, and takes the prompt as text.

The AWS Knowledge client connects to the public, unauthenticated endpoint and keeps an
allowlist of the documentation tools. The test serves it the full tool set of the
IAM-authenticated AWS MCP Server (tools/list on 2026-11-02) in memory, so the filter is
the one Strands applies when the agent loads its tools.
"""

import asyncio
import base64
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_client_server_memory_streams

AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"


def _factory():
    # Imported lazily: test_mcp_parallel_connect puts agent/ on sys.path when it is
    # imported, and agent/tools would then shadow servers/remote's tools package
    # for the test modules collected after this one.
    from test_mcp_parallel_connect import _factory as load

    return load()

# tools/list of https://aws-mcp.us-east-1.api.aws/mcp (IAM-authenticated), 2026-11-02.
AWS_MCP_SERVER_TOOLS = [
    "aws___get_presigned_url",
    "aws___get_regional_availability",
    "aws___get_tasks",
    "aws___list_regions",
    "aws___read_documentation",
    "aws___retrieve_skill",
    "aws___run_script",
    "aws___search_documentation",
]
API_TOOLS = {"aws___run_script", "aws___get_presigned_url", "aws___get_tasks"}


def _server_with(names: list[str]) -> FastMCP:
    server = FastMCP("fake-aws-mcp")
    for name in names:
        server.add_tool(lambda: "", name=name, description=name)
    return server


def _in_memory_transport(server: FastMCP):
    """A streamablehttp_client stand-in connected to *server* in memory."""

    @asynccontextmanager
    async def transport():
        low = server._mcp_server
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as tg:
                tg.start_soon(lambda: low.run(*server_streams, low.create_initialization_options()))
                yield client_streams[0], client_streams[1], lambda: None
                tg.cancel_scope.cancel()

    return transport()


def _knowledge_tool_names(monkeypatch, server_tools: list[str]) -> tuple[list[str], dict]:
    """Tool names of the AWS Knowledge client the agent factory builds."""
    factory = _factory()
    import mcp_clients

    seen: dict = {}

    def fake_streamablehttp_client(**kwargs):
        seen.update(kwargs)
        return _in_memory_transport(_server_with(server_tools))

    monkeypatch.setattr(mcp_clients, "streamablehttp_client", fake_streamablehttp_client)
    index = [name for name, _ in factory.MCP_DEFS].index("AWS Knowledge")
    client = factory._MCP_FACTORIES[index]("jwt", session_id="s1")
    try:
        # load_tools() is what _prewarm_mcp_clients calls; Strands' own call reuses it.
        tools = asyncio.run(client.load_tools())
        return sorted(t.tool_name for t in tools), seen
    finally:
        client.stop(None, None, None)


def test_knowledge_client_offers_only_documentation_tools(monkeypatch):
    names, _ = _knowledge_tool_names(monkeypatch, AWS_MCP_SERVER_TOOLS)

    assert not API_TOOLS & set(names)
    assert names == sorted([
        "aws___search_documentation",
        "aws___read_documentation",
        "aws___retrieve_skill",
        "aws___list_regions",
        "aws___get_regional_availability",
    ])


def test_knowledge_client_drops_tools_added_later(monkeypatch):
    names, _ = _knowledge_tool_names(monkeypatch, [*AWS_MCP_SERVER_TOOLS, "aws___call_aws"])

    assert "aws___call_aws" not in names


def test_knowledge_client_uses_public_endpoint_without_credentials(monkeypatch):
    _, seen = _knowledge_tool_names(monkeypatch, AWS_MCP_SERVER_TOOLS)

    assert seen["url"] == "https://knowledge-mcp.global.api.aws"
    assert "auth" not in seen and "headers" not in seen


# --- prompt type -------------------------------------------------------------


def _basic_agent():
    _factory()
    if "basic_agent" in sys.modules:
        return sys.modules["basic_agent"]
    sys.path.insert(0, str(AGENT_DIR))
    try:
        import basic_agent
    finally:
        sys.path.remove(str(AGENT_DIR))
    return basic_agent


class _Context:
    def __init__(self):
        claims = base64.urlsafe_b64encode(json.dumps({"sub": "user-1"}).encode()).decode().rstrip("=")
        self.request_headers = {"authorization": f"Bearer h.{claims}.s"}


def _run(basic_agent, payload) -> list[dict]:
    async def collect():
        return [e async for e in basic_agent.agent_stream(payload, _Context())]

    return asyncio.run(collect())


@pytest.mark.parametrize("prompt", [
    [{"role": "user", "content": [{"toolUse": {"toolUseId": "t1", "name": "web_fetch", "input": {}}}]}],
    [{"toolUse": {"toolUseId": "t1", "name": "web_fetch", "input": {}}}],
    {"text": "hello"},
    42,
])
def test_non_string_prompt_is_rejected_before_the_agent_is_built(monkeypatch, prompt):
    basic_agent = _basic_agent()

    def no_agent(**kwargs):
        raise AssertionError("create_agent must not be called")

    monkeypatch.setattr(basic_agent, "create_agent", no_agent)

    events = _run(basic_agent, {"prompt": prompt, "runtimeSessionId": "s" * 33})

    assert events == [{"status": "error", "code": basic_agent.BAD_INPUT, "error": "Invalid field: prompt must be a string"}]


def test_string_prompt_reaches_the_agent(monkeypatch):
    basic_agent = _basic_agent()
    seen: dict = {}

    def fake_create_agent(**kwargs):
        return object(), []

    async def fake_stream(agent, user_query, session_id, cancel, cancel_signal):
        seen["prompt"] = user_query
        yield {"done": True}

    monkeypatch.setattr(basic_agent, "create_agent", fake_create_agent)
    monkeypatch.setattr(basic_agent, "stream_agent", fake_stream)

    events = _run(basic_agent, {"prompt": "hello", "runtimeSessionId": "s" * 33})

    assert seen["prompt"] == "hello"
    assert events[-1] == {"done": True}
