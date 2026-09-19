# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the Mcp-Session-Id wiring in agent/mcp_clients.py.

Background: AgentCore routes MCP requests to a microVM by the `Mcp-Session-Id`
header (microVM stickiness). Without it the platform mints a fresh session id per
request, so every agent turn starts a new session on the MCP runtime. Measured in
ap-northeast-1 on 2026-09-19 against the 630 MiB MCP image: 0.18-0.20s with a
consistent id, 0.59s (V1, warm capacity available) without one, and 17.6-19.7s
when no warm capacity existed.
"""

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _require_mcp_clients():
    """Import agent/mcp_clients.py, skipping unless its deps really resolve.

    Mirrors tests/test_message_hooks.py: a bare importorskip is not enough
    because a stale editable install can leave ``strands`` importable as an empty
    namespace package, in which case the import succeeds but MCPClient is absent.
    """
    pytest.importorskip("mcp.client.streamable_http")
    strands_mcp = pytest.importorskip("strands.tools.mcp")
    if not hasattr(strands_mcp, "MCPClient"):
        pytest.skip("strands.tools.mcp does not provide MCPClient (stale install)")
    return pytest.importorskip("mcp_clients")


def _capture(monkeypatch, mcp_clients):
    """Capture the transport kwargs that mcp_agentcore_runtime would use.

    MCPClient receives a zero-arg callable and does not invoke it at construction
    time, so the test stands in for both: it records the callable, then calls it
    to record the kwargs handed to streamablehttp_client.
    """
    seen: dict = {}

    def fake_transport(**kwargs):
        seen["transport_kwargs"] = kwargs
        return object()

    def fake_client(transport_callable, **kwargs):
        seen["client_kwargs"] = kwargs
        transport_callable()
        return object()

    monkeypatch.setattr(mcp_clients, "streamablehttp_client", fake_transport)
    monkeypatch.setattr(mcp_clients, "MCPClient", fake_client)
    monkeypatch.setenv("MCP_RUNTIME_ARN", "arn:aws:bedrock-agentcore:ap-northeast-1:111122223333:runtime/x")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    return seen


def test_session_id_is_sent_as_mcp_session_id_header(monkeypatch):
    mcp_clients = _require_mcp_clients()
    seen = _capture(monkeypatch, mcp_clients)

    mcp_clients.mcp_agentcore_runtime(jwt_token="tok", session_id="sess-1234567890")

    headers = seen["transport_kwargs"]["headers"]
    assert headers["Mcp-Session-Id"] == "sess-1234567890"
    assert headers["Authorization"] == "Bearer tok"


def test_header_is_omitted_when_session_id_is_empty(monkeypatch):
    """Empty session id must not send the header at all.

    An empty value would be worse than omitting it: the platform's own
    generation kicks in only when the header is absent.
    """
    mcp_clients = _require_mcp_clients()
    seen = _capture(monkeypatch, mcp_clients)

    mcp_clients.mcp_agentcore_runtime(jwt_token="tok")

    headers = seen["transport_kwargs"]["headers"]
    assert "Mcp-Session-Id" not in headers
    assert headers["Authorization"] == "Bearer tok"


def test_tool_filters_still_reach_the_client(monkeypatch):
    """session_id must not displace the existing tool_filters argument."""
    mcp_clients = _require_mcp_clients()
    seen = _capture(monkeypatch, mcp_clients)

    mcp_clients.mcp_agentcore_runtime(
        jwt_token="tok", session_id="s-1", tool_filters={"allowed": ["a", "b"]}
    )

    assert seen["client_kwargs"]["tool_filters"] == {"allowed": ["a", "b"]}
    assert seen["transport_kwargs"]["headers"]["Mcp-Session-Id"] == "s-1"


def test_session_id_is_keyword_compatible_with_factory_lambdas(monkeypatch):
    """factory.py passes session_id by keyword to every MCP factory lambda."""
    mcp_clients = _require_mcp_clients()
    seen = _capture(monkeypatch, mcp_clients)

    factory = (
        lambda jwt_token, session_id="", tool_filters=None: mcp_clients.mcp_agentcore_runtime(
            jwt_token=jwt_token, session_id=session_id, tool_filters=tool_filters
        )
    )
    factory("tok", session_id="s-2", tool_filters=None)

    assert seen["transport_kwargs"]["headers"]["Mcp-Session-Id"] == "s-2"


def test_terminate_on_close_stays_false(monkeypatch):
    """Session reuse depends on not tearing the session down on close."""
    mcp_clients = _require_mcp_clients()
    seen = _capture(monkeypatch, mcp_clients)

    mcp_clients.mcp_agentcore_runtime(jwt_token="tok", session_id="s-3")

    assert seen["transport_kwargs"]["terminate_on_close"] is False
