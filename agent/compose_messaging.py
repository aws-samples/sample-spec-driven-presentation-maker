# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Messages between the orchestrator and the composers of a running compose_slides.

compose_slides runs in the background (background.py), so the orchestrator keeps talking
with the user while its composers work. ComposeMessaging (one per session handle) lets
the two sides reach each other meanwhile:

- orchestrator -> composer: ``message_composer(group, text)`` puts the text into that
  group's Inbox; the composer's SteerInbox delivers it at its next step, prefixed with
  COMPOSER_MESSAGE_PREFIX (steer_inbox.py).
- composer -> orchestrator: ``report_to_orchestrator(text)`` calls ``on_report``, which the
  session runtime sets: it publishes ``composerNote`` and puts a ``<composer_note>`` into
  the session inbox (folded into the running turn, or a turn of its own).

Groups are numbered from 1, as in ``slide_groups`` and the compose report. The session runs
one compose at a time (background.CONFIG max_concurrency 1), so a group number names one
running composer.
"""

import json
import logging
import threading
from typing import Callable

from strands import tool as strands_tool

from steer_inbox import Inbox

logger = logging.getLogger("sdpm.agent")

COMPOSER_MESSAGE_PREFIX = "Message from the orchestrator while you work: "


class _Group:
    def __init__(self, tool_use_id: str, slugs: list[str], stopped: Callable[[], bool] | None):
        self.tool_use_id = tool_use_id
        self.slugs = list(slugs)
        self.stopped = stopped or (lambda: False)
        self.inbox = Inbox()


class ComposeMessaging:
    """The running composers' inboxes, by group number, and the report channel back.
    Thread-safe (composers run on pool threads)."""

    def __init__(self, session_id: str = ""):
        self.session_id = session_id
        # Called with (tool_use_id, group, slugs, text); returns whether the note was taken.
        self.on_report: Callable[[str, int, list[str], str], bool] | None = None
        self._lock = threading.Lock()
        self._groups: dict[int, _Group] = {}

    def register(self, tool_use_id: str, group: int, slugs: list[str],
                 stopped: Callable[[], bool] | None = None) -> Inbox:
        """A composer of the compose_slides call ``tool_use_id`` starts: its inbox.
        ``stopped``: true once its work is stopped (nothing is sent to it then)."""
        entry = _Group(tool_use_id, slugs, stopped)
        with self._lock:
            self._groups[group] = entry
        return entry.inbox

    def unregister(self, tool_use_id: str, group: int) -> None:
        """The composer ended (a later call's group of the same number stays)."""
        self.close(tool_use_id, group)

    def close(self, tool_use_id: str, group: int) -> list[tuple[str, str]]:
        """The composer's invocation ended: nothing more is sent to it. Returns what was
        sent after its last step (the composer runs once more with it)."""
        with self._lock:
            entry = self._groups.get(group)
            if entry is None or entry.tool_use_id != tool_use_id:
                return []
            del self._groups[group]
            return entry.inbox.drain()

    def running(self) -> dict[int, list[str]]:
        """Group number -> slugs of the composers that can be messaged now."""
        with self._lock:
            return {g: list(e.slugs) for g, e in sorted(self._groups.items()) if not e.stopped()}

    def send(self, group: int, text: str) -> str | None:
        """Put ``text`` into the running composer's inbox. None when sent, else an error
        text naming the running groups."""
        with self._lock:
            entry = self._groups.get(group)
            if entry is not None and not entry.stopped():
                entry.inbox.put(f"to-{group}", text)
                sent = True
            else:
                sent = False
        if sent:
            _log("to", self.session_id, group)
            return None
        running = self.running()
        if not running:
            return "No composer is running now: compose_slides has finished or has not started its composers."
        listed = "; ".join(f"{g} ({', '.join(slugs)})" for g, slugs in running.items())
        return f"No composer of group {group} is running. Running groups: {listed}."

    def report(self, tool_use_id: str, group: int, slugs: list[str], text: str) -> bool:
        """A composer's note for the orchestrator; False when nobody takes it (no session,
        or its work was stopped)."""
        callback = self.on_report
        if callback is None:
            return False
        return bool(callback(tool_use_id, group, list(slugs), text))


def _log(direction: str, session_id: str, group: int) -> None:
    logger.info(json.dumps({"kind": "composer_message", "dir": direction, "session_id": session_id[:12],
                            "group": group}))


def make_message_composer(messaging: ComposeMessaging):
    """The orchestrator's tool for reaching a running composer."""

    @strands_tool(name="message_composer")
    def message_composer(group: int, text: str) -> str | dict:
        """Send a message to a composer of the compose_slides call running now.

        It reaches the composer at its next step, and the composer applies it to the slides
        it is writing, including the ones it already wrote. A composer's reply, if any,
        arrives later as a <composer_note>.

        Args:
            group: The composer's group: the 1-based index of its group in that call's
                slide_groups.
            text: The message, e.g. the user's new request in the user's words.
        """
        error = messaging.send(group, text)
        if error:
            return {"status": "error", "content": [{"text": error}]}  # the Web UI card shows it was not sent
        return f"Sent to composer {group}; it reads the message at its next step."

    return message_composer


def make_report_tool(messaging: ComposeMessaging, tool_use_id: str, group: int, slugs: list[str]):
    """A composer's tool for telling the orchestrator something."""

    @strands_tool(name="report_to_orchestrator")
    def report_to_orchestrator(text: str) -> str:
        """Answer a message the orchestrator sent you while you work (e.g. that you applied
        it), or tell it something it has to decide before you can finish. Your final
        summary reaches the orchestrator in the compose report, so progress and completion
        belong in that summary. You get no answer here.

        Args:
            text: What to tell, in a sentence or two.
        """
        if messaging.report(tool_use_id, group, slugs, text):
            _log("from", messaging.session_id, group)
            return "Sent to the orchestrator."
        return "Not sent: the orchestrator's work was stopped."

    return report_to_orchestrator
