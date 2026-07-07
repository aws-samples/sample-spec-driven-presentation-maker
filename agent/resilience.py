# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Hard-stop guards for agent tool loops (fingerprint + hard cap).

Complements the soft-stop prompts (STOP_PROMPT, BUDGET_PROMPT, ERROR_LIMIT_PROMPT)
which nudge the LLM. These enforce termination via agent.cancel() when the LLM
ignores those prompts (observed in production logs).
"""

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field

from strands.hooks.events import AfterToolCallEvent

logger = logging.getLogger("sdpm.agent")


def call_tool_with_retry(mcp_client, *, tool_use_id: str, name: str, arguments: dict,
                         max_attempts: int = 3, base_delay: float = 2.0) -> dict:
    """call_tool_sync with exponential backoff for transient MCP failures.

    Retries only on transport-level exceptions (connection drops, timeouts).
    A result with status="error" is a tool-level failure the caller must
    handle — retrying it would repeat the same deterministic error.
    """
    for attempt in range(max_attempts):
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
        self.fingerprint_counts[fp] = self.fingerprint_counts.get(fp, 0) + 1
        if self.fingerprint_counts[fp] >= self.fingerprint_repeat_limit:
            self._cancel(event, f"fingerprint {fp} repeated {self.fingerprint_counts[fp]}x")

    def _cancel(self, event: AfterToolCallEvent, reason: str) -> None:
        if self.cancelled:
            return
        self.cancelled = True
        self.cancel_reason = reason
        logger.warning("LoopGuard triggered: %s", reason)
        event.agent.cancel()
