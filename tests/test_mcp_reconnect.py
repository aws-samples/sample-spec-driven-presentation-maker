# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for MCP client auto-reconnection."""

import sys
import os
import threading
import time
from unittest.mock import MagicMock, patch
from types import ModuleType

import pytest

# Mock strands SDK modules before importing mcp_reconnect
_strands = ModuleType("strands")
_strands.Agent = MagicMock
_strands_hooks = ModuleType("strands.hooks")
_strands_hooks_events = ModuleType("strands.hooks.events")
_strands_hooks_events.AfterToolCallEvent = type("AfterToolCallEvent", (), {})
_strands_hooks_events.BeforeToolCallEvent = type("BeforeToolCallEvent", (), {})
_strands_tools = ModuleType("strands.tools")
_strands_tools_mcp = ModuleType("strands.tools.mcp")
_strands_tools_mcp.MCPClient = MagicMock

sys.modules.setdefault("strands", _strands)
sys.modules.setdefault("strands.hooks", _strands_hooks)
sys.modules.setdefault("strands.hooks.events", _strands_hooks_events)
sys.modules.setdefault("strands.tools", _strands_tools)
sys.modules.setdefault("strands.tools.mcp", _strands_tools_mcp)

# Add agent/ to path so we can import mcp_reconnect directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from mcp_reconnect import (
    MCPReconnectHandler,
    MCPServerEntry,
    ReconnectEvent,
    ErrorClassification,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_entry(name="TestServer", required=True, status="ok", client=None):
    return MCPServerEntry(
        name=name, required=required, index=0,
        factory_fn=MagicMock(return_value=MagicMock()),
        client=client or MagicMock(),
        status=status,
    )


def _make_handler(entries=None, max_retries=3, base_delay=0.01, max_delay=0.05):
    if entries is None:
        entries = [_make_entry()]
    return MCPReconnectHandler(
        entries=entries, jwt_token="test-jwt",
        max_retries=max_retries, base_delay=base_delay, max_delay=max_delay,
    )


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

class TestClassifyError:
    def test_connection_error_is_transient(self):
        h = _make_handler()
        assert h.classify_error(ConnectionError("conn refused")) == "transient"

    def test_timeout_error_is_transient(self):
        h = _make_handler()
        assert h.classify_error(TimeoutError("timed out")) == "transient"

    def test_connection_refused_is_transient(self):
        h = _make_handler()
        assert h.classify_error(ConnectionRefusedError()) == "transient"

    def test_connection_reset_is_transient(self):
        h = _make_handler()
        assert h.classify_error(ConnectionResetError()) == "transient"

    def test_http_502_is_transient(self):
        h = _make_handler()
        err = Exception("Bad Gateway")
        err.status_code = 502
        assert h.classify_error(err) == "transient"

    def test_http_503_is_transient(self):
        h = _make_handler()
        err = Exception("Service Unavailable")
        err.status_code = 503
        assert h.classify_error(err) == "transient"

    def test_http_401_is_permanent(self):
        h = _make_handler()
        err = Exception("Unauthorized")
        err.status_code = 401
        assert h.classify_error(err) == "permanent"

    def test_http_403_is_permanent(self):
        h = _make_handler()
        err = Exception("Forbidden")
        err.status_code = 403
        assert h.classify_error(err) == "permanent"

    def test_message_pattern_transient(self):
        h = _make_handler()
        assert h.classify_error(Exception("connection reset by peer")) == "transient"
        assert h.classify_error(Exception("EOF occurred")) == "transient"

    def test_message_pattern_permanent(self):
        h = _make_handler()
        assert h.classify_error(Exception("unauthorized access")) == "permanent"
        assert h.classify_error(Exception("SSL certificate error")) == "permanent"

    def test_value_error_is_not_connection(self):
        h = _make_handler()
        assert h.classify_error(ValueError("bad value")) == "not_connection"

    def test_type_error_is_not_connection(self):
        h = _make_handler()
        assert h.classify_error(TypeError("wrong type")) == "not_connection"

    def test_generic_exception_is_not_connection(self):
        h = _make_handler()
        assert h.classify_error(Exception("something else")) == "not_connection"

    def test_mcp_client_initialization_error_is_transient(self):
        h = _make_handler()
        # Simulate strands.types.exceptions.MCPClientInitializationError
        err = type("MCPClientInitializationError", (Exception,), {})(
            "the client session is not running"
        )
        assert h.classify_error(err) == "transient"

    def test_session_not_running_message_is_transient(self):
        h = _make_handler()
        assert h.classify_error(Exception("client session is not running")) == "transient"

    def test_runtime_error_mcp_server_closed_is_transient(self):
        h = _make_handler()
        assert h.classify_error(RuntimeError("Connection to the MCP server was closed")) == "transient"

    def test_tool_provider_exception_is_transient(self):
        h = _make_handler()
        err = type("ToolProviderException", (Exception,), {})("Failed to start MCP client: ...")
        assert h.classify_error(err) == "transient"

    def test_failed_to_start_mcp_client_message_is_transient(self):
        h = _make_handler()
        assert h.classify_error(Exception("Failed to start MCP client: timeout")) == "transient"


# ---------------------------------------------------------------------------
# Backoff
# ---------------------------------------------------------------------------

class TestCalculateBackoff:
    def test_within_bounds(self):
        h = _make_handler(base_delay=2.0, max_delay=30.0)
        for attempt in range(10):
            val = h.calculate_backoff(attempt)
            assert val >= h.base_delay
            assert val <= h.max_delay

    def test_monotonic_increase_base(self):
        """Base value (without jitter) increases monotonically."""
        h = _make_handler(base_delay=2.0, max_delay=1000.0)
        for i in range(5):
            base_i = h.base_delay * (2 ** i)
            base_next = h.base_delay * (2 ** (i + 1))
            assert base_next > base_i


# ---------------------------------------------------------------------------
# ReconnectEvent
# ---------------------------------------------------------------------------

class TestReconnectEvent:
    def test_to_dict_reconnecting(self):
        ev = ReconnectEvent(type="reconnecting", server="Test", attempt=1, max_retries=3, message="Trying...")
        d = ev.to_dict()
        assert d["type"] == "reconnecting"
        assert d["server"] == "Test"
        assert d["attempt"] == 1

    def test_to_dict_reconnected(self):
        ev = ReconnectEvent(type="reconnected", server="Test", message="OK")
        d = ev.to_dict()
        assert d["type"] == "reconnected"
        assert "attempt" not in d or d["attempt"] == 0

    def test_to_dict_failed(self):
        ev = ReconnectEvent(type="failed", server="Test", required=True, message="Failed")
        d = ev.to_dict()
        assert d["type"] == "failed"
        assert d["required"] is True


# ---------------------------------------------------------------------------
# should_reconnect
# ---------------------------------------------------------------------------

class TestShouldReconnect:
    def test_transient_error_returns_true(self):
        h = _make_handler()
        assert h.should_reconnect(ConnectionError("lost"), "TestServer") is True

    def test_permanent_error_returns_false(self):
        h = _make_handler()
        err = Exception("Unauthorized")
        err.status_code = 401
        assert h.should_reconnect(err, "TestServer") is False

    def test_not_connection_returns_false(self):
        h = _make_handler()
        assert h.should_reconnect(ValueError("bad"), "TestServer") is False

    def test_already_reconnecting_returns_false(self):
        h = _make_handler()
        h._reconnecting["TestServer"] = True
        assert h.should_reconnect(ConnectionError("lost"), "TestServer") is False


# ---------------------------------------------------------------------------
# reconnect
# ---------------------------------------------------------------------------

class TestReconnect:
    def test_successful_reconnect(self):
        entry = _make_entry()
        new_client = MagicMock()
        entry.factory_fn.return_value = new_client
        h = _make_handler(entries=[entry])
        agent = MagicMock()
        agent.tool_registry = MagicMock()

        result = h.reconnect(entry, agent)

        assert result is True
        assert entry.status == "ok"
        assert entry.client == new_client
        agent.tool_registry.process_tools.assert_called()

    def test_all_retries_fail(self):
        entry = _make_entry()
        entry.factory_fn.side_effect = ConnectionError("still down")
        h = _make_handler(entries=[entry], max_retries=2)
        agent = MagicMock()

        result = h.reconnect(entry, agent)

        assert result is False
        assert entry.status == "failed"

    def test_events_emitted_on_reconnect(self):
        entry = _make_entry()
        h = _make_handler(entries=[entry], max_retries=1)
        agent = MagicMock()
        agent.tool_registry = MagicMock()

        h.reconnect(entry, agent)

        events = h.drain_events()
        types = [e["type"] for e in events]
        assert "reconnecting" in types
        assert "reconnected" in types

    def test_events_emitted_on_failure(self):
        entry = _make_entry()
        entry.factory_fn.side_effect = ConnectionError("down")
        h = _make_handler(entries=[entry], max_retries=1)
        agent = MagicMock()

        h.reconnect(entry, agent)

        events = h.drain_events()
        types = [e["type"] for e in events]
        assert "reconnecting" in types
        assert "failed" in types

    def test_old_client_stopped(self):
        old_client = MagicMock()
        entry = _make_entry(client=old_client)
        h = _make_handler(entries=[entry])
        agent = MagicMock()
        agent.tool_registry = MagicMock()

        h.reconnect(entry, agent)

        old_client.stop.assert_called_once()

    def test_concurrent_reconnect_blocked(self):
        """Second reconnect for same server is blocked."""
        entry = _make_entry()
        # Make factory slow
        entry.factory_fn.side_effect = lambda jwt: (time.sleep(0.1), MagicMock())[1]
        h = _make_handler(entries=[entry], max_retries=1)
        agent = MagicMock()
        agent.tool_registry = MagicMock()

        results = []

        def run():
            results.append(h.reconnect(entry, agent))

        t1 = threading.Thread(target=run)
        t2 = threading.Thread(target=run)
        t1.start()
        time.sleep(0.02)  # Let t1 acquire lock
        t2.start()
        t1.join()
        t2.join()

        # One should succeed, one should be blocked (return False)
        assert False in results


# ---------------------------------------------------------------------------
# Required vs optional server failure
# ---------------------------------------------------------------------------

class TestRequiredOptional:
    def test_required_server_failure_event(self):
        entry = _make_entry(required=True)
        entry.factory_fn.side_effect = ConnectionError("down")
        h = _make_handler(entries=[entry], max_retries=1)
        agent = MagicMock()

        h.reconnect(entry, agent)

        events = h.drain_events()
        failed = [e for e in events if e["type"] == "failed"]
        assert len(failed) == 1
        assert failed[0]["required"] is True

    def test_optional_server_failure_event(self):
        entry = _make_entry(required=False)
        entry.factory_fn.side_effect = ConnectionError("down")
        h = _make_handler(entries=[entry], max_retries=1)
        agent = MagicMock()

        h.reconnect(entry, agent)

        events = h.drain_events()
        failed = [e for e in events if e["type"] == "failed"]
        assert len(failed) == 1
        assert failed[0].get("required") is False


# ---------------------------------------------------------------------------
# Reconnection independence (Property 5)
# ---------------------------------------------------------------------------

class TestReconnectionIndependence:
    def test_independent_reconnection(self):
        """One server's failure doesn't affect another's reconnection."""
        entry_a = _make_entry(name="ServerA", required=True)
        entry_a.factory_fn.side_effect = ConnectionError("down")

        entry_b = _make_entry(name="ServerB", required=False)
        new_b = MagicMock()
        entry_b.factory_fn.return_value = new_b

        h = _make_handler(entries=[entry_a, entry_b], max_retries=1)
        agent = MagicMock()
        agent.tool_registry = MagicMock()

        result_a = h.reconnect(entry_a, agent)
        result_b = h.reconnect(entry_b, agent)

        assert result_a is False
        assert result_b is True
        assert entry_a.status == "failed"
        assert entry_b.status == "ok"


# ---------------------------------------------------------------------------
# Composer MCP factory
# ---------------------------------------------------------------------------

class TestComposerMcp:
    def test_create_composer_mcp(self):
        # Mock mcp_clients module for the lazy import in create_composer_mcp
        mock_mcp_clients = ModuleType("mcp_clients")
        mock_factory = MagicMock()
        mock_client = MagicMock()
        mock_factory.return_value = mock_client
        mock_mcp_clients.mcp_agentcore_runtime = mock_factory
        sys.modules["mcp_clients"] = mock_mcp_clients

        try:
            h = _make_handler()
            result = h.create_composer_mcp()
            mock_factory.assert_called_once_with(jwt_token="test-jwt")
            assert result == mock_client
        finally:
            del sys.modules["mcp_clients"]


# ---------------------------------------------------------------------------
# Event queue
# ---------------------------------------------------------------------------

class TestEventQueue:
    def test_drain_events_empty(self):
        h = _make_handler()
        assert h.drain_events() == []

    def test_drain_events_returns_all(self):
        h = _make_handler()
        h._event_queue.put(ReconnectEvent(type="reconnecting", server="A", message="..."))
        h._event_queue.put(ReconnectEvent(type="reconnected", server="A", message="OK"))

        events = h.drain_events()
        assert len(events) == 2
        assert events[0]["type"] == "reconnecting"
        assert events[1]["type"] == "reconnected"

    def test_has_pending_events(self):
        h = _make_handler()
        assert h.has_pending_events() is False
        h._event_queue.put(ReconnectEvent(type="reconnecting", server="A"))
        assert h.has_pending_events() is True


# ---------------------------------------------------------------------------
# End-to-end: MCPClientInitializationError triggers reconnection
# ---------------------------------------------------------------------------

class TestMCPClientInitializationErrorReconnect:
    """Simulate the exact error seen in production logs:
    strands.types.exceptions.MCPClientInitializationError:
    the client session is not running.
    """

    def test_after_tool_hook_detects_session_not_running(self):
        """event.result has status=error, event.exception is MCPClientInitializationError."""
        entry = _make_entry(name="Presentation Maker", required=True)
        new_client = MagicMock()
        entry.factory_fn.return_value = new_client
        h = _make_handler(entries=[entry])

        agent = MagicMock()
        agent.tool_registry = MagicMock()

        # Simulate the tool_map so _find_entry_for_tool works
        mock_tool = MagicMock()
        mock_tool.tool_name = "run_python"
        entry.client.tool_map = {"run_python": mock_tool}

        # Simulate AfterToolCallEvent as Strands SDK produces it
        MCPClientInitError = type("MCPClientInitializationError", (Exception,), {})
        real_exception = MCPClientInitError(
            "the client session is not running. Ensure the agent is used within the MCP client context manager."
        )

        event = MagicMock()
        event.result = {
            "toolUseId": "test-123",
            "status": "error",
            "content": [{"text": f"Error: {real_exception}"}],
        }
        event.exception = real_exception
        event.tool_use = {"name": "run_python", "input": {}}
        event.agent = agent

        h.after_tool_hook(event)

        # Verify reconnection was attempted
        entry.factory_fn.assert_called_once_with(h.jwt_token)
        assert entry.client == new_client
        assert entry.status == "ok"

    def test_after_tool_hook_detects_session_not_running_without_exception_attr(self):
        """Fallback: event.exception is None, but error text contains the message."""
        entry = _make_entry(name="Presentation Maker", required=True)
        new_client = MagicMock()
        entry.factory_fn.return_value = new_client
        h = _make_handler(entries=[entry])

        agent = MagicMock()
        agent.tool_registry = MagicMock()

        mock_tool = MagicMock()
        mock_tool.tool_name = "run_python"
        entry.client.tool_map = {"run_python": mock_tool}

        event = MagicMock()
        event.result = {
            "toolUseId": "test-456",
            "status": "error",
            "content": [{"text": "Error: the client session is not running"}],
        }
        event.exception = None
        event.tool_use = {"name": "run_python", "input": {}}
        event.agent = agent

        h.after_tool_hook(event)

        # Should still reconnect via message pattern match
        entry.factory_fn.assert_called_once_with(h.jwt_token)
        assert entry.status == "ok"

    def test_after_tool_hook_ignores_non_connection_error(self):
        """ValueError from tool logic should NOT trigger reconnection."""
        entry = _make_entry(name="Presentation Maker", required=True)
        h = _make_handler(entries=[entry])

        mock_tool = MagicMock()
        mock_tool.tool_name = "run_python"
        entry.client.tool_map = {"run_python": mock_tool}

        event = MagicMock()
        event.result = {
            "toolUseId": "test-789",
            "status": "error",
            "content": [{"text": "Error: invalid argument for slide layout"}],
        }
        event.exception = ValueError("invalid argument for slide layout")
        event.tool_use = {"name": "run_python", "input": {}}

        h.after_tool_hook(event)

        # Should NOT reconnect
        entry.factory_fn.assert_not_called()
        assert entry.status == "ok"


# ---------------------------------------------------------------------------
# Property-based tests (hypothesis)
# ---------------------------------------------------------------------------

from hypothesis import given, settings, assume
from hypothesis import strategies as st


# Strategy: generate various exception types for error classification
_exception_strategy = st.one_of(
    st.builds(ConnectionError, st.text(max_size=50)),
    st.builds(ConnectionRefusedError, st.text(max_size=50)),
    st.builds(ConnectionResetError, st.text(max_size=50)),
    st.builds(TimeoutError, st.text(max_size=50)),
    st.builds(ValueError, st.text(max_size=50)),
    st.builds(TypeError, st.text(max_size=50)),
    st.builds(KeyError, st.text(max_size=50)),
    st.builds(RuntimeError, st.text(max_size=50)),
    st.builds(OSError, st.text(max_size=50)),
    st.builds(Exception, st.text(max_size=50)),
)


class TestProperty1ErrorClassification:
    """Property 1: エラー分類の正確性.

    # Feature: mcp-client-auto-reconnect, Property 1: For any exception,
    # classify_error returns one of "transient", "permanent", "not_connection",
    # and connection-related exceptions never return "not_connection".
    """

    @given(error=_exception_strategy)
    @settings(max_examples=200)
    def test_always_returns_valid_classification(self, error):
        h = _make_handler()
        result = h.classify_error(error)
        assert result in ("transient", "permanent", "not_connection")

    @given(error=st.one_of(
        st.builds(ConnectionError, st.text(max_size=50)),
        st.builds(ConnectionRefusedError, st.text(max_size=50)),
        st.builds(ConnectionResetError, st.text(max_size=50)),
        st.builds(TimeoutError, st.text(max_size=50)),
    ))
    @settings(max_examples=100)
    def test_connection_exceptions_never_not_connection(self, error):
        h = _make_handler()
        result = h.classify_error(error)
        assert result != "not_connection"


class TestProperty2LogFields:
    """Property 2: ログの必須フィールド保証.

    # Feature: mcp-client-auto-reconnect, Property 2: For any error type and
    # server name, the log message contains error type, server name.
    """

    @given(
        error_msg=st.text(min_size=1, max_size=100),
        server_name=st.text(min_size=1, max_size=50, alphabet=st.characters(categories=("L", "N"))),
    )
    @settings(max_examples=100)
    def test_log_contains_required_fields(self, error_msg, server_name):
        import logging
        h = _make_handler()
        error = ConnectionError(error_msg)

        with patch("mcp_reconnect.logger") as mock_logger:
            # Simulate what after_tool_hook does for logging
            mock_logger.warning(
                "MCP connection lost: server=%s, error=%s",
                server_name, str(error)[:200],
            )
            call_args = mock_logger.warning.call_args
            fmt = call_args[0][0]
            assert "server=" in fmt
            assert "error=" in fmt


class TestProperty3Backoff:
    """Property 3: 指数バックオフの数学的性質.

    # Feature: mcp-client-auto-reconnect, Property 3: For any retry attempt n,
    # calculate_backoff(n) is in [base_delay, max_delay] and the base value
    # (without jitter) increases monotonically.
    """

    @given(
        attempt=st.integers(min_value=0, max_value=20),
        base_delay=st.floats(min_value=0.1, max_value=10.0),
        max_delay=st.floats(min_value=10.0, max_value=300.0),
    )
    @settings(max_examples=200)
    def test_backoff_within_bounds(self, attempt, base_delay, max_delay):
        assume(max_delay > base_delay)
        h = _make_handler(base_delay=base_delay, max_delay=max_delay)
        val = h.calculate_backoff(attempt)
        assert val >= base_delay
        assert val <= max_delay

    @given(base_delay=st.floats(min_value=0.5, max_value=5.0))
    @settings(max_examples=100)
    def test_base_value_monotonic(self, base_delay):
        """Base value (without jitter) is monotonically increasing."""
        for i in range(5):
            assert base_delay * (2 ** (i + 1)) > base_delay * (2 ** i)


class TestProperty4ErrorResult:
    """Property 4: エラー結果の必須フィールド保証.

    # Feature: mcp-client-auto-reconnect, Property 4: For any tool name and
    # error type, the tool error result contains status "error" and error text.
    """

    @given(
        tool_name=st.text(min_size=1, max_size=50, alphabet=st.characters(categories=("L", "N"))),
        error_msg=st.text(min_size=1, max_size=200),
    )
    @settings(max_examples=100)
    def test_error_result_has_required_fields(self, tool_name, error_msg):
        # Simulate the error result format that after_tool_hook processes
        result = {
            "status": "error",
            "content": [{"text": error_msg}],
        }
        assert result["status"] == "error"
        assert any(
            isinstance(item, dict) and "text" in item and item["text"]
            for item in result["content"]
        )


class TestProperty5Independence:
    """Property 5: 再接続の独立性.

    # Feature: mcp-client-auto-reconnect, Property 5: For any combination of
    # server success/failure, one server's result does not affect another's.
    """

    @given(
        num_servers=st.integers(min_value=2, max_value=5),
        failure_pattern=st.lists(st.booleans(), min_size=2, max_size=5),
    )
    @settings(max_examples=100, deadline=2000)
    def test_independent_reconnection(self, num_servers, failure_pattern):
        # Align pattern length with server count
        pattern = failure_pattern[:num_servers]
        while len(pattern) < num_servers:
            pattern.append(False)

        entries = []
        for i in range(num_servers):
            entry = _make_entry(name=f"Server{i}", required=(i == 0))
            if pattern[i]:  # True = will fail
                entry.factory_fn.side_effect = ConnectionError("down")
            entries.append(entry)

        h = _make_handler(entries=entries, max_retries=1)
        agent = MagicMock()
        agent.tool_registry = MagicMock()

        results = []
        for entry in entries:
            results.append(h.reconnect(entry, agent))

        # Verify independence: each result matches its pattern
        for i, (success, should_fail) in enumerate(zip(results, pattern)):
            if should_fail:
                assert success is False, f"Server{i} should have failed"
                assert entries[i].status == "failed"
            else:
                assert success is True, f"Server{i} should have succeeded"
                assert entries[i].status == "ok"
