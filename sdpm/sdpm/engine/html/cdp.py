# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A small synchronous Chrome DevTools Protocol client over one WebSocket.

``CdpConnection`` uses ``websockets``' sync client (no asyncio), so it works from a
worker thread and from code already running inside an event loop. Every call has a
deadline; events that arrive while a reply is awaited are kept for ``take_events``.
Sessions are flat (``Target.attachToTarget`` with ``flatten``): page commands carry a
``sessionId``.
"""

from __future__ import annotations

import itertools
import json
import time
from typing import Any, Callable, Mapping


class CdpError(RuntimeError):
    """A CDP error reply, a JS exception, or a closed connection."""


class CdpTimeout(CdpError):
    """No reply within the call's timeout."""


class CdpConnection:
    """Context manager holding one DevTools WebSocket (browser-level endpoint)."""

    def __init__(self, url: str, headers: Mapping[str, str] | None = None, *,
                 open_timeout: float = 15, max_size: int = 64 << 20) -> None:
        self.url = url
        self.headers = dict(headers or {})
        self.open_timeout = open_timeout
        self.max_size = max_size
        self._ws = None
        self._ids = itertools.count(1)
        self._events: list[dict] = []
        # Called with each event as it arrives (also while a reply is awaited); an
        # exception it raises propagates out of ``send``.
        self.on_event: Callable[[dict], None] | None = None

    def __enter__(self) -> "CdpConnection":
        try:
            from websockets.sync.client import connect
        except ImportError as exc:
            raise CdpError("websockets is not installed") from exc
        try:
            conn = connect(self.url, additional_headers=self.headers or None,
                           max_size=self.max_size, open_timeout=self.open_timeout)
        except Exception as exc:
            raise CdpError(f"could not connect to the browser: {type(exc).__name__}: {exc}") from exc
        self._ws = conn.__enter__()  # closed in __exit__
        return self

    def __exit__(self, *exc_info) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.__exit__(None, None, None)
            except Exception:  # nosec B110 - closing a socket that is already gone
                pass

    def send(self, method: str, params: dict | None = None, *, session: str | None = None,
             timeout: float = 15.0) -> dict:
        """Send one command and return its ``result``; events read meanwhile are kept."""
        from websockets.exceptions import ConnectionClosed

        if self._ws is None:
            raise CdpError(f"{method}: not connected")
        msg_id = next(self._ids)
        msg: dict[str, Any] = {"id": msg_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        deadline = time.monotonic() + timeout
        try:
            self._ws.send(json.dumps(msg))
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise CdpTimeout(f"{method}: no reply within {timeout:g} s")
                try:
                    raw = self._ws.recv(timeout=left)
                except TimeoutError:
                    raise CdpTimeout(f"{method}: no reply within {timeout:g} s") from None
                reply = json.loads(raw)
                if reply.get("id") == msg_id:
                    if "error" in reply:
                        err = reply["error"]
                        text = err.get("message", err) if isinstance(err, dict) else err
                        raise CdpError(f"{method}: {text}")
                    return reply.get("result", {})
                if "method" in reply:
                    self._events.append(reply)
                    if self.on_event is not None:
                        self.on_event(reply)
        except ConnectionClosed as exc:
            raise CdpError(f"{method}: connection closed ({exc})") from exc

    def evaluate(self, session: str, expr: str, *, await_promise: bool = False,
                 timeout: float = 15.0) -> Any:
        """``Runtime.evaluate`` by value; a thrown JS exception raises ``CdpError``."""
        result = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                                "awaitPromise": await_promise},
                           session=session, timeout=timeout)
        details = result.get("exceptionDetails")
        if details:
            text = (details.get("exception") or {}).get("description") or details.get("text") or "exception"
            raise CdpError(f"evaluate: {text[:400]}")
        return (result.get("result") or {}).get("value")

    def take_events(self) -> list[dict]:
        """Events received so far (each returned once)."""
        events, self._events = self._events, []
        return events


__all__ = ["CdpConnection", "CdpError", "CdpTimeout"]
