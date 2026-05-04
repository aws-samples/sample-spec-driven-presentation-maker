# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP client auto-reconnection: detect connection loss and re-initialize MCPClient.

Uses Agent hook mechanism (AfterToolCallEvent / BeforeToolCallEvent) to detect
connection errors and automatically reconnect with exponential backoff.
"""

from __future__ import annotations

import logging
import queue
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from strands import Agent
from strands.hooks.events import AfterToolCallEvent, BeforeToolCallEvent
from strands.tools.mcp import MCPClient

logger = logging.getLogger("sdpm.agent")

ErrorClassification = Literal["transient", "permanent", "not_connection"]

_TRANSIENT_EXCEPTIONS = (
    ConnectionError,
    ConnectionRefusedError,
    ConnectionResetError,
    TimeoutError,
)

_TRANSIENT_HTTP_CODES = {502, 503, 504}
_PERMANENT_HTTP_CODES = {401, 403}

_TRANSIENT_KEYWORDS = ("connection", "refused", "reset", "timeout", "eof", "broken pipe",
                       "client session is not running", "mcpclientinitialization",
                       "connection to the mcp server was closed", "toolproviderexception",
                       "failed to start mcp client")
_PERMANENT_KEYWORDS = ("unauthorized", "forbidden", "certificate", "ssl")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class MCPServerEntry:
    """MCP server management info."""

    name: str
    required: bool
    index: int
    factory_fn: Callable[..., MCPClient]
    client: MCPClient | None
    status: str = "ok"  # "ok" | "reconnecting" | "failed" | "disabled"


@dataclass
class ReconnectEvent:
    """SSE event for reconnection status."""

    type: str  # "reconnecting" | "reconnected" | "failed"
    server: str
    attempt: int = 0
    max_retries: int = 3
    required: bool = False
    message: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in {
            "type": self.type,
            "server": self.server,
            "attempt": self.attempt,
            "max_retries": self.max_retries,
            "required": self.required,
            "message": self.message,
        }.items() if v or isinstance(v, (bool, int))}


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@dataclass
class MCPReconnectHandler:
    """Detect MCP connection loss and auto-reconnect."""

    entries: list[MCPServerEntry]
    jwt_token: str
    max_retries: int = 3
    base_delay: float = 2.0
    max_delay: float = 30.0
    _reconnect_lock: threading.Lock = field(default_factory=threading.Lock)
    _reconnecting: dict[str, bool] = field(default_factory=dict)
    _event_queue: queue.Queue = field(default_factory=queue.Queue)

    # -- Error classification -----------------------------------------------

    def classify_error(self, error: Exception) -> ErrorClassification:
        """Classify an error as transient, permanent, or not_connection."""
        if isinstance(error, _TRANSIENT_EXCEPTIONS):
            return "transient"

        # Strands SDK MCP errors (session not running, connection closed, provider failure)
        err_type = type(error).__name__
        if "MCPClient" in err_type or "MCPSession" in err_type or "ToolProvider" in err_type:
            return "transient"

        status_code = getattr(error, "status_code", None) or getattr(error, "code", None)
        if isinstance(status_code, int):
            if status_code in _TRANSIENT_HTTP_CODES:
                return "transient"
            if status_code in _PERMANENT_HTTP_CODES:
                return "permanent"

        msg = str(error).lower()
        if any(kw in msg for kw in _TRANSIENT_KEYWORDS):
            return "transient"
        if any(kw in msg for kw in _PERMANENT_KEYWORDS):
            return "permanent"

        return "not_connection"

    # -- Backoff ------------------------------------------------------------

    def calculate_backoff(self, attempt: int) -> float:
        """Exponential backoff with jitter: min(base * 2^attempt + rand, max)."""
        base = self.base_delay * (2 ** attempt) + random.random()
        return min(base, self.max_delay)

    # -- Reconnection -------------------------------------------------------

    def should_reconnect(self, error: Exception, server_name: str) -> bool:
        """Determine if reconnection should be attempted."""
        if self._reconnecting.get(server_name):
            return False
        classification = self.classify_error(error)
        return classification == "transient"

    def _find_entry(self, server_name: str) -> MCPServerEntry | None:
        for e in self.entries:
            if e.name == server_name:
                return e
        return None

    def _find_entry_for_tool(self, tool_name: str) -> MCPServerEntry | None:
        """Find the MCPServerEntry that owns a given tool."""
        for entry in self.entries:
            if entry.client is None:
                continue
            try:
                for tool in entry.client.tool_map.values():
                    if getattr(tool, "tool_name", None) == tool_name:
                        return entry
            except Exception:
                continue
        return None

    def reconnect(self, entry: MCPServerEntry, agent: Agent) -> bool:
        """Re-initialize MCPClient for the given server. Returns True on success."""
        with self._reconnect_lock:
            if self._reconnecting.get(entry.name):
                return False
            self._reconnecting[entry.name] = True

        entry.status = "reconnecting"

        try:
            for attempt in range(self.max_retries):
                self._event_queue.put(ReconnectEvent(
                    type="reconnecting", server=entry.name,
                    attempt=attempt + 1, max_retries=self.max_retries,
                    required=entry.required,
                    message=f"MCP Server '{entry.name}' への再接続を試みています... ({attempt + 1}/{self.max_retries})",
                ))

                delay = self.calculate_backoff(attempt)
                logger.info("MCP reconnecting: server=%s, attempt=%d/%d, backoff=%.1fs",
                            entry.name, attempt + 1, self.max_retries, delay)
                time.sleep(delay)

                try:
                    # Stop old client
                    if entry.client is not None:
                        try:
                            entry.client.stop(None, None, None)
                        except Exception:
                            logger.debug("Failed to stop old MCPClient for %s", entry.name)

                    # Create new client
                    new_client = entry.factory_fn(self.jwt_token)

                    # Replace in agent tool_registry
                    self._replace_mcp_client(entry, new_client, agent)

                    entry.status = "ok"
                    logger.info("MCP reconnected: server=%s, attempts=%d", entry.name, attempt + 1)
                    self._event_queue.put(ReconnectEvent(
                        type="reconnected", server=entry.name,
                        required=entry.required,
                        message=f"MCP Server '{entry.name}' への接続が復旧しました",
                    ))
                    return True

                except Exception as e:
                    logger.warning("MCP reconnect attempt %d failed for %s: %s",
                                   attempt + 1, entry.name, e)

            # All retries exhausted
            entry.status = "failed"
            logger.error("MCP reconnection failed: server=%s, required=%s, attempts=%d",
                         entry.name, entry.required, self.max_retries)
            self._event_queue.put(ReconnectEvent(
                type="failed", server=entry.name,
                required=entry.required,
                message=f"MCP Server '{entry.name}' への接続を復旧できませんでした。セッションを再開始してください。",
            ))
            return False

        finally:
            self._reconnecting[entry.name] = False

    def _replace_mcp_client(
        self, entry: MCPServerEntry, new_client: MCPClient, agent: Agent,
    ) -> None:
        """Replace MCPClient in agent's tool_registry."""
        old_client = entry.client

        # Remove old tools
        if old_client is not None:
            try:
                for tool_name in list(old_client.tool_map.keys()):
                    agent.tool_registry.registry.pop(tool_name, None)
            except Exception:
                logger.debug("Failed to remove old tools for %s", entry.name)

        # Register new tools
        agent.tool_registry.process_tools([new_client])
        entry.client = new_client

    # -- Hooks --------------------------------------------------------------

    def after_tool_hook(self, event: AfterToolCallEvent) -> None:
        """AfterToolCallEvent hook: detect connection errors and start reconnection."""
        # Use the real exception if available (Strands SDK passes it via event.exception)
        real_exception = getattr(event, "exception", None)

        result = event.result
        if not isinstance(result, dict):
            return

        status = result.get("status", "")
        if status != "error":
            return

        # Extract error from result content
        content = result.get("content", [])
        error_text = ""
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and "text" in item:
                error_text = item["text"]
                break
        if not error_text:
            error_text = str(result)

        # Use real exception for classification if available, otherwise synthesize
        error = real_exception if real_exception is not None else ConnectionError(error_text)

        tool_name = event.tool_use.get("name", "")
        entry = self._find_entry_for_tool(tool_name)
        if entry is None:
            return

        if not self.should_reconnect(error, entry.name):
            return

        logger.warning("MCP connection lost: server=%s, error=%s", entry.name, error_text[:200])

        # Run reconnection synchronously (within the hook)
        self.reconnect(entry, event.agent)

    def before_tool_hook(self, event: BeforeToolCallEvent) -> None:
        """BeforeToolCallEvent hook: block tool calls while reconnecting."""
        tool_name = event.tool_use.get("name", "")
        entry = self._find_entry_for_tool(tool_name)
        if entry is None:
            return

        if not self._reconnecting.get(entry.name):
            return

        # Wait for reconnection to complete (max 60s)
        deadline = time.time() + 60
        while self._reconnecting.get(entry.name) and time.time() < deadline:
            time.sleep(0.5)

    # -- Event queue --------------------------------------------------------

    def has_pending_events(self) -> bool:
        return not self._event_queue.empty()

    def drain_events(self) -> list[dict]:
        """Drain all pending events from the queue."""
        events = []
        while not self._event_queue.empty():
            try:
                ev = self._event_queue.get_nowait()
                events.append(ev.to_dict())
            except queue.Empty:
                break
        return events

    # -- Composer support ----------------------------------------------------

    def create_composer_mcp(self) -> MCPClient:
        """Create a new MCPClient for Composer Agent using current JWT."""
        from mcp_clients import mcp_agentcore_runtime
        return mcp_agentcore_runtime(jwt_token=self.jwt_token)
