# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A session's MCP clients read the latest JWT per request and restart an ended session.

agent/token_holder.py (TokenHolder, HolderAuth) and mcp_clients.ReconnectingMCPClient.
The MCP side runs in memory (FastMCP), so a restart is a real new MCP session.
"""

import asyncio
import base64
import json
import threading

import anyio
import httpx
import pytest
from mcp.server.fastmcp import FastMCP

from agent_modules import load


def _jwt(sub: str, n: int = 0) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"sub": sub, "n": n}).encode()).decode().rstrip("=")
    return f"h.{body}.s"


def _holder(sub="user-1", n=0):
    return load("token_holder").TokenHolder(sub, _jwt(sub, n))


def _client(holder, handler):
    return httpx.Client(transport=httpx.MockTransport(handler), auth=load("token_holder").HolderAuth(holder))


def test_each_request_carries_the_latest_token():
    holder = _holder()
    seen: list[str] = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        return httpx.Response(200)

    with _client(holder, handler) as client:
        client.get("https://mcp.test/")
        holder.set(_jwt("user-1", 1))
        client.get("https://mcp.test/")

    assert seen == [f"Bearer {_jwt('user-1', 0)}", f"Bearer {_jwt('user-1', 1)}"]
    assert holder.version == 2


def test_a_401_is_retried_once_with_a_newer_token():
    holder = _holder()
    seen: list[str] = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        if len(seen) == 1:
            holder.set(_jwt("user-1", 1))  # a turn swapped the token while the request ran
            return httpx.Response(401)
        return httpx.Response(200)

    with _client(holder, handler) as client:
        assert client.get("https://mcp.test/").status_code == 200

    assert seen == [f"Bearer {_jwt('user-1', 0)}", f"Bearer {_jwt('user-1', 1)}"]
    assert holder.unauthorized_at is None


def test_a_401_without_a_newer_token_is_not_retried():
    holder = _holder()
    calls: list = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401)

    with _client(holder, handler) as client:
        assert client.get("https://mcp.test/").status_code == 401

    assert len(calls) == 1
    assert holder.unauthorized_at is not None
    holder.set(_jwt("user-1", 1))
    assert holder.unauthorized_at is None


@pytest.mark.parametrize("token", [_jwt("user-2"), "not-a-jwt", ""])
def test_a_token_of_another_user_is_refused(token):
    holder = _holder()

    with pytest.raises(PermissionError):
        holder.set(token)

    assert holder.token == _jwt("user-1") and holder.version == 1


def test_a_holder_needs_its_owners_token():
    with pytest.raises(PermissionError):
        load("token_holder").TokenHolder("user-1", _jwt("user-2"))


# --- ReconnectingMCPClient ---------------------------------------------------


def _server(calls: list, entered: threading.Event | None = None) -> FastMCP:
    server = FastMCP("fake-presentation-maker")

    async def echo(text: str) -> str:
        calls.append(text)
        return text

    async def slow() -> str:
        calls.append("slow")
        if entered is not None:
            entered.set()
        await anyio.sleep(10)
        return "late"

    server.add_tool(echo, name="echo", description="echo")
    server.add_tool(slow, name="slow", description="slow")
    return server


def _reconnecting(server: FastMCP):
    from test_agent_tool_exposure import _in_memory_transport

    mcp_clients = load("mcp_clients")
    client = mcp_clients.ReconnectingMCPClient(lambda: _in_memory_transport(server))
    asyncio.run(client.load_tools())
    return client


def test_an_ended_session_is_restarted_and_the_call_sent_once():
    calls: list = []
    client = _reconnecting(_server(calls))
    client.add_consumer("session-handle")
    try:
        client.stop(None, None, None)  # the session ended (401, dropped connection)
        client.add_consumer("session-handle")  # stop() forgets consumers; the handle's comes back
        assert not client.alive()

        result = client.call_tool_sync(tool_use_id="t1", name="echo", arguments={"text": "hi"})

        assert result["status"] == "success"
        assert calls == ["hi"]
        assert client.alive()
        assert "session-handle" in client._consumers
        assert [t.tool_name for t in asyncio.run(client.load_tools())] == ["echo", "slow"]
    finally:
        client.stop(None, None, None)


def test_an_ended_session_is_restarted_for_an_async_call():
    calls: list = []
    client = _reconnecting(_server(calls))
    try:
        client.stop(None, None, None)

        async def call():
            return await client.call_tool_async(tool_use_id="t1", name="echo", arguments={"text": "a"})

        assert asyncio.run(call())["status"] == "success"
        assert calls == ["a"]
    finally:
        client.stop(None, None, None)


def test_a_call_that_fails_in_flight_is_not_sent_again():
    calls: list = []
    entered = threading.Event()
    client = _reconnecting(_server(calls, entered))
    results: list = []
    worker = threading.Thread(
        target=lambda: results.append(client.call_tool_sync(tool_use_id="t1", name="slow", arguments={})),
    )
    try:
        worker.start()
        assert entered.wait(5)
        client.stop(None, None, None)  # the connection drops while the call runs
        worker.join(10)

        assert results and results[0]["status"] == "error"
        assert calls == ["slow"]
    finally:
        client.stop(None, None, None)


def test_a_restart_from_inside_a_running_loop_works():
    """compose_slides calls MCP synchronously from the agent's event loop."""
    calls: list = []
    client = _reconnecting(_server(calls))
    try:
        client.stop(None, None, None)

        async def inside_loop():
            return client.call_tool_sync(tool_use_id="t1", name="echo", arguments={"text": "x"})

        assert asyncio.run(inside_loop())["status"] == "success"
        assert calls == ["x"]
    finally:
        client.stop(None, None, None)
