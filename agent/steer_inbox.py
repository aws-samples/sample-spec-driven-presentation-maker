# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Steer: a message the user sends while the session is working reaches the running turn.

Strands 1.63 has no public API to add user input to a running invocation, so the
SteerInbox plugin uses two public hooks:

- MessageAddedEvent, ordered SDK_FIRST so it runs before the session manager persists
  the message: a user message being added (a tool-result message, or the prompt)
  gets one text block per pending steer. The model sees it on its next call and
  Memory stores it at that point, as the user's words.
- AfterInvocationEvent: when the turn is about to end (end_turn / stop_sequence) with
  steers still pending, ``event.resume`` continues the same invocation with them.

A steer that arrives after the last of these points stays in the inbox; the session
runtime starts a new turn with it (session_runtime.py). Nothing is delivered once the
turn's stop event is set: a cancel discards the inbox first (R2).

Each composer of a running compose_slides has an inbox of its own, delivered the same way
with a prefix that names the orchestrator as the sender (compose_messaging.py).
"""

import threading
from typing import Callable

from strands.hooks import AfterInvocationEvent, HookOrder, MessageAddedEvent
from strands.plugins import Plugin

_ENDING = ("end_turn", "stop_sequence")


class Inbox:
    """Pending steers of one session, as (id, text) pairs. Thread-safe."""

    def __init__(self):
        self._lock = threading.Lock()
        self._items: list[tuple[str, str]] = []

    def put(self, item_id: str, text: str) -> None:
        with self._lock:
            self._items.append((item_id, text))

    def drain(self) -> list[tuple[str, str]]:
        """Take every pending steer (oldest first)."""
        with self._lock:
            items, self._items = self._items, []
        return items

    def discard(self) -> list[tuple[str, str]]:
        """Drop every pending steer; returns what was dropped."""
        return self.drain()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def __bool__(self) -> bool:
        return len(self) > 0


class SteerInbox(Plugin):
    """Delivers a session's pending steers into the running invocation (see module doc)."""

    name = "sdpm-steer-inbox"

    def __init__(
        self,
        inbox: Inbox,
        stopped: Callable[[], bool],
        on_delivered: Callable[[list[tuple[str, str]], str], None] | None = None,
        prefix: str = "",
    ):
        self.inbox = inbox
        self.stopped = stopped
        self.on_delivered = on_delivered
        self.prefix = prefix  # put before each delivered text (a composer's messages)
        super().__init__()

    def init_agent(self, agent) -> None:
        agent.add_hook(self._on_message_added, MessageAddedEvent, order=HookOrder.SDK_FIRST)
        agent.add_hook(self._after_invocation, AfterInvocationEvent)

    def _delivered(self, items: list[tuple[str, str]], how: str) -> None:
        if self.on_delivered is not None:
            self.on_delivered(items, how)

    def _on_message_added(self, event: MessageAddedEvent) -> None:
        message = event.message
        if message.get("role") != "user" or not self.inbox or self.stopped():
            return
        items = self.inbox.drain()
        if not items:
            return
        message["content"].extend({"text": self.prefix + text} for _, text in items)
        self._delivered(items, "fold")

    def _after_invocation(self, event: AfterInvocationEvent) -> None:
        if not self.inbox or self.stopped():
            return
        result = event.result
        if result is None or result.stop_reason not in _ENDING:
            return
        items = self.inbox.drain()
        if not items:
            return
        event.resume = [{"text": self.prefix + text} for _, text in items]
        self._delivered(items, "resume")
