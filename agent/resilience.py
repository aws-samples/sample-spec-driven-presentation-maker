# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Hard-stop guards for agent tool loops (fingerprint + hard cap) and the write gate.

Complements ERROR_LIMIT_PROMPT (agent/modes/composer.py), which nudges the LLM.
These enforce termination via agent.cancel() when the LLM ignores that prompt
(observed in production logs).

The write gate closes once the process is told to stop (SIGTERM, see stop_guard.py).
From then on tool calls, compose's direct MCP calls and Memory events are dropped.
"""

import hashlib
import json
import logging
import random
import threading
import time
from dataclasses import dataclass, field

from strands.hooks.events import AfterToolCallEvent, BeforeToolCallEvent

logger = logging.getLogger("sdpm.agent")

# invocation_state key of the turn's stop event (a threading.Event owned by the turn).
# Strands clears the agent's own cancel_signal when the parent invocation ends, so
# compose_slides hands this one to its composers instead: it stays set after a cancel.
TURN_STOP_KEY = "sdpm_turn_stop"

_SHUTTING_DOWN = "Stopped: the agent is shutting down."
_writes_closed = threading.Event()


class WritesClosed(RuntimeError):
    """A direct MCP call was refused because the write gate is closed."""


def close_writes() -> None:
    """Close the write gate for the rest of the process's life."""
    _writes_closed.set()


def writes_closed() -> bool:
    return _writes_closed.is_set()


def gate_tool_call(event: BeforeToolCallEvent) -> None:
    """BeforeToolCallEvent hook: cancel the tool call once the write gate is closed."""
    if _writes_closed.is_set():
        event.cancel_tool = _SHUTTING_DOWN


def call_tool_with_retry(mcp_client, *, tool_use_id: str, name: str, arguments: dict,
                         max_attempts: int = 3, base_delay: float = 2.0) -> dict:
    """call_tool_sync with exponential backoff for transient MCP failures.

    Retries only on transport-level exceptions (connection drops, timeouts).
    A result with status="error" is a tool-level failure the caller must
    handle — retrying it would repeat the same deterministic error.
    Raises WritesClosed instead of calling once the write gate is closed.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    for attempt in range(max_attempts):
        if _writes_closed.is_set():
            raise WritesClosed(f"{name} not called: the agent is shutting down")
        try:
            return mcp_client.call_tool_sync(tool_use_id=tool_use_id, name=name, arguments=arguments)
        except Exception as e:
            if attempt == max_attempts - 1:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            logger.warning("MCP call %s failed (attempt %d/%d): %s — retrying in %.1fs",
                           name, attempt + 1, max_attempts, e, delay)
            time.sleep(delay)
    raise RuntimeError("unreachable")


@dataclass
class LoopGuard:
    """Tracks tool-call fingerprints and enforces hard caps via agent.cancel()."""

    max_tool_calls: int = 150
    fingerprint_repeat_limit: int = 3
    tool_calls: int = 0
    fingerprint_counts: dict[str, int] = field(default_factory=dict)
    fingerprint_progress: dict[str, int] = field(default_factory=dict)
    cancelled: bool = False
    cancel_reason: str = ""

    def _fingerprint(self, event: AfterToolCallEvent) -> str:
        name = event.tool_use.get("name", "")
        args = event.tool_use.get("input", {})
        args_str = json.dumps(args, sort_keys=True, ensure_ascii=False) if isinstance(args, dict) else str(args)
        status = ""
        if isinstance(event.result, dict):
            status = event.result.get("status", "")
        raw = f"{name}|{args_str}|{status}"
        return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()[:12]

    def after_tool(self, event: AfterToolCallEvent) -> None:
        self.tool_calls += 1
        if self.tool_calls >= self.max_tool_calls:
            self._cancel(event, f"max_tool_calls reached ({self.tool_calls})")
            return
        fp = self._fingerprint(event)
        progress = self._completed_stage_count(event.result)
        previous_progress = self.fingerprint_progress.get(fp, -1)
        if progress is not None and progress > previous_progress:
            self.fingerprint_progress[fp] = progress
            self.fingerprint_counts[fp] = 1
        else:
            self.fingerprint_counts[fp] = self.fingerprint_counts.get(fp, 0) + 1
        if self.fingerprint_counts[fp] >= self.fingerprint_repeat_limit:
            self._cancel(event, f"fingerprint {fp} repeated {self.fingerprint_counts[fp]}x")

    @classmethod
    def _completed_stage_count(cls, value: object) -> int | None:
        """Find an IMPORT_INCOMPLETE payload in common Strands result shapes."""
        if isinstance(value, dict):
            if value.get("code") == "IMPORT_INCOMPLETE" and isinstance(value.get("completedStages"), list):
                return len(value["completedStages"])
            for key in ("content", "result", "output"):
                progress = cls._completed_stage_count(value.get(key))
                if progress is not None:
                    return progress
        elif isinstance(value, list):
            for item in value:
                progress = cls._completed_stage_count(item)
                if progress is not None:
                    return progress
        elif isinstance(value, str):
            try:
                return cls._completed_stage_count(json.loads(value))
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    def _cancel(self, event: AfterToolCallEvent, reason: str) -> None:
        if self.cancelled:
            return
        self.cancelled = True
        self.cancel_reason = reason
        logger.warning("LoopGuard triggered: %s", reason)
        event.agent.cancel()
