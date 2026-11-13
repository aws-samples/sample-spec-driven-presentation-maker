# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A failing tool's message reaches the agent (sdpm/sdpm/tools/tool_errors.py).

mcp 2.x hides the text of any exception but ToolError; the servers keep mcp 1.x's
``Error executing tool <name>: <reason>`` so the agent can act on a refusal.
"""

import asyncio

from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from sdpm.tools import tool_errors


def _server(install: bool) -> MCPServer:
    server = MCPServer("errors")

    def refuses(name: str) -> str:
        raise ValueError(f"Invalid style name: {name}")

    def deliberate() -> str:
        raise ToolError("not now")

    async def fine() -> str:
        return "ok"

    for fn in (refuses, deliberate, fine):
        server.add_tool(fn)
    if install:
        tool_errors.install(server)
    return server


def _call(server: MCPServer, name: str, arguments: dict):
    async def run():
        async with Client(server, mode="legacy") as client:
            return await client.call_tool(name, arguments)

    return asyncio.run(run())


def test_the_reason_of_a_raised_exception_reaches_the_caller():
    result = _call(_server(True), "refuses", {"name": "../x"})
    assert result.is_error
    assert result.content[0].text == "Error executing tool refuses: Invalid style name: ../x"


def test_without_it_the_sdk_hides_the_reason():
    result = _call(_server(False), "refuses", {"name": "../x"})
    assert result.is_error and result.content[0].text == "Error executing tool refuses"


def test_tool_errors_and_results_are_unchanged():
    server = _server(True)
    deliberate = _call(server, "deliberate", {})
    assert deliberate.is_error and deliberate.content[0].text == "Error executing tool deliberate: not now"
    fine = _call(server, "fine", {})
    assert not fine.is_error and fine.content[0].text == "ok"
