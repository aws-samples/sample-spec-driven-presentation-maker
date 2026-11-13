# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A failing tool's message reaches the agent (sdpm/sdpm/tools/tool_errors.py).

mcp 2.x hides the text of any exception but ToolError; the servers keep mcp 1.x's
``Error executing tool <name>: <reason>`` so the agent can act on a refusal.
"""

import asyncio
import logging

from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from sdpm.tools import tool_errors
from sdpm.tools.attachment.errors import AttachmentError


def _server(install: bool) -> MCPServer:
    server = MCPServer("errors")

    def refuses(name: str) -> str:
        raise ValueError(f"Invalid style name: {name}")

    def deliberate() -> str:
        raise ToolError("not now")

    async def fine() -> str:
        return "ok"

    def crashes() -> str:
        return {}["missing"]

    def attachment_refusal() -> str:
        raise AttachmentError("SOURCE_NOT_FOUND", "no such source")

    for fn in (refuses, deliberate, fine, crashes, attachment_refusal):
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


def _errors(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == tool_errors.__name__ and r.levelno >= logging.ERROR]


def test_a_crash_is_logged_at_error_with_its_traceback(caplog):
    with caplog.at_level(logging.INFO):
        result = _call(_server(True), "crashes", {})
    assert result.is_error and result.content[0].text == "Error executing tool crashes: 'missing'"
    [record] = _errors(caplog)
    assert "crashes" in record.getMessage()
    assert record.exc_info and record.exc_info[0] is KeyError


def test_a_refusal_is_not_logged_as_an_error(caplog):
    server = _server(True)
    with caplog.at_level(logging.INFO):
        refused = _call(server, "refuses", {"name": "x"})
        attachment = _call(server, "attachment_refusal", {})
        deliberate = _call(server, "deliberate", {})
    assert refused.is_error and attachment.is_error and deliberate.is_error
    assert attachment.content[0].text == "Error executing tool attachment_refusal: no such source"
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
