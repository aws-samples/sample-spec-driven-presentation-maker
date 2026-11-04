# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""``/ws``: the Web UI's connection to its session.

Client messages (JSON, field ``type``):
  prompt {id, prompt, mode?, chatModelId?, createModelId?}   idle: a new turn; working: a steer
  steer {id, text}                                          routed the same way
  cancel {id}  ·  resume {from_seq}  ·  prepare {mode?, chatModelId?, createModelId?}  ·  ping

Server frames: control messages ``{"ctl": ...}`` (accepted, cancelAck, resumeAck,
prepareAck, ready, pong, keepalive, error) and the session's events ``{"seq", "ev"}``,
packed by event_ring.frames into ``{"batch": [...]}`` / ``{"chunk", ...}`` frames of at
most 24,000 bytes, at most one frame per FRAME_INTERVAL_S (the platform closes a
connection over 250 frames/s with 1008).

Rules measured on dev (.agents/tasks/ws-invoke-cancel-2026-11/report.md):
- the client speaks first: a frame sent right after accept never reached a client, so
  nothing is sent before the first client message;
- the platform validates the token the browser passes as a subprotocol and forwards it
  as ``Authorization``; only that header is read here. The session is admitted on the
  first message (session_guard.admit) and its owner checked again on every message;
- a disconnect only unsubscribes: it never cancels the session's work (R8).
"""

import asyncio
import json
import logging
import secrets
import time

from starlette.websockets import WebSocketDisconnect

import session_guard
import session_runtime
from errors import AUTH, BAD_INPUT, INTERNAL, SERVICE_UNAVAILABLE
from event_ring import frames
from modes import MODES
from shared.session_owner import sub_from_jwt

logger = logging.getLogger("sdpm.agent")

SUBPROTOCOL = "base64UrlBearerAuthorization"
SESSION_HEADER = "x-amzn-bedrock-agentcore-runtime-session-id"
FRAME_INTERVAL_S = 0.02
KEEPALIVE_S = 5.0
REFUSED_CLOSE_CODE = 4403
MAX_ID_LEN = 64


def _bearer(headers) -> str:
    auth = ""
    if headers:
        auth = headers.get("Authorization", "") or headers.get("authorization", "")
    return auth.removeprefix("Bearer ").removeprefix("bearer ").strip()


def _item_id(value) -> str:
    if isinstance(value, str) and 0 < len(value) <= MAX_ID_LEN and value.isprintable():
        return value
    return ""


def _error(code: str, message: str) -> dict:
    return {"ctl": "error", "code": code, "error": message}


class Connection:
    """One WebSocket connection: its sender, its subscription and the session it serves."""

    def __init__(self, websocket, context):
        self.ws = websocket
        headers = getattr(context, "request_headers", None) or {}
        self.token = _bearer(headers)
        self.sub = sub_from_jwt(self.token) if self.token else ""
        self.header_session_id = getattr(context, "session_id", None) or websocket.headers.get(SESSION_HEADER, "")
        self.session_id: str | None = None
        self.key = f"ws-{secrets.token_hex(4)}"
        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue = asyncio.Queue()
        self.subscribed: session_runtime.Session | None = None
        self.closed = False
        self._last_send = 0.0
        self._tasks: set[asyncio.Task] = set()

    # -- sending ----------------------------------------------------------------

    def send(self, ctl: dict) -> None:
        self.queue.put_nowait(("ctl", ctl))

    async def _send_frame(self, frame: str) -> None:
        wait = self._last_send + FRAME_INTERVAL_S - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        await self.ws.send_text(frame)
        self._last_send = time.monotonic()

    async def _sender(self) -> None:
        carry = None
        try:
            while True:
                kind, payload = carry if carry is not None else await self.queue.get()
                carry = None
                if kind == "close":
                    await self.ws.close(code=payload)
                    return
                if kind == "ctl":
                    await self._send_frame(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                    continue
                items = list(payload)
                # Take what is queued already, so a replay or a burst goes out batched.
                while not self.queue.empty():
                    nxt = self.queue.get_nowait()
                    if nxt[0] != "items":
                        carry = nxt
                        break
                    items.extend(nxt[1])
                for frame in frames(items):
                    await self._send_frame(frame)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - the connection is gone; the receive loop ends
            logger.info("WS send stopped (conn %s): %s", self.key, e)

    async def _keepalive(self) -> None:
        while True:
            await asyncio.sleep(KEEPALIVE_S)
            session = self.subscribed
            if session is not None and session.working:
                self.send({"ctl": "keepalive"})

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # -- the session ------------------------------------------------------------

    async def _admit(self) -> bool:
        if not self.sub:
            return self._refuse(AUTH, "Session not available", "no identity")
        if not self.header_session_id:
            return self._refuse(BAD_INPUT, "Missing session id", "no session id")
        session_id, refusal = await session_guard.admit(self.header_session_id, self.header_session_id, self.sub)
        if refusal is not None:
            return self._refuse(refusal.get("code", AUTH), refusal.get("error", "Session not available"), "admit")
        self.session_id = session_id
        logger.info("WS session %s admitted (conn %s)", session_id[:12], self.key)
        return True

    def _refuse(self, code: str, message: str, reason: str) -> bool:
        logger.warning("WS refused (%s) for session %s", reason, (self.header_session_id or "")[:12])
        self.send(_error(code, message))
        self.queue.put_nowait(("close", REFUSED_CLOSE_CODE))
        self.closed = True
        return False

    def _session(self, create: bool) -> session_runtime.Session | None:
        """The session, owner checked on every message; PermissionError for another user."""
        registry = session_runtime.registry
        if create:
            return registry.get_or_create(self.session_id, self.sub)
        return registry.get(self.session_id, self.sub)

    def _subscribe(self, session, from_seq: int | None) -> None:
        if self.subscribed is not None:
            self.subscribed.unsubscribe(self.key)
        session.subscribe(self.key, self.loop, self.queue, from_seq)
        self.subscribed = session

    def _unsubscribe(self) -> None:
        if self.subscribed is not None:
            self.subscribed.unsubscribe(self.key)
            self.subscribed = None

    # -- messages ---------------------------------------------------------------

    async def run(self) -> None:
        sender = asyncio.ensure_future(self._sender())
        self._tasks.add(sender)
        self._spawn(self._keepalive())
        try:
            while not self.closed:
                try:
                    text = await self.ws.receive_text()
                except WebSocketDisconnect:
                    break
                try:
                    message = json.loads(text)
                except (TypeError, ValueError):
                    message = None
                if self.session_id is None and not await self._admit():
                    break
                if not isinstance(message, dict) or not isinstance(message.get("type"), str):
                    self.send(_error(BAD_INPUT, "Invalid message"))
                    continue
                try:
                    self._dispatch(message)
                except PermissionError:
                    logger.warning("WS message refused (owner) for session %s", self.session_id[:12])
                    self.send(_error(AUTH, "Session not available"))
                except RuntimeError as e:
                    self.send(_error(SERVICE_UNAVAILABLE, str(e)))
                except Exception:
                    logger.exception("WS message failed for session %s", (self.session_id or "")[:12])
                    self.send(_error(INTERNAL, "Internal error"))
            if self.closed:
                # Let the sender deliver the refusal and close the connection.
                await asyncio.wait({sender}, timeout=2)
        finally:
            self._unsubscribe()
            for task in list(self._tasks):
                task.cancel()
            logger.info("WS closed for session %s (conn %s)", (self.session_id or "")[:12], self.key)

    def _dispatch(self, message: dict) -> None:
        kind = message["type"]
        if kind == "ping":
            self.send({"ctl": "pong"})
        elif kind in ("prompt", "steer"):
            self._on_message(message, message.get("prompt") if kind == "prompt" else message.get("text"))
        elif kind == "cancel":
            session = self._session(create=False)
            result = session.cancel() if session is not None else "idle"
            self.send({"ctl": "cancelAck", "id": _item_id(message.get("id")), "result": result})
        elif kind == "resume":
            from_seq = message.get("from_seq", 0)
            if not isinstance(from_seq, int) or isinstance(from_seq, bool) or from_seq < 0:
                self.send(_error(BAD_INPUT, "Invalid field: from_seq"))
                return
            session = self._session(create=False)
            if session is None:
                # Not in this process (reclaimed, or after StopRuntimeSession): the
                # client shows the Memory history.
                self.send({"ctl": "resumeAck", "working": False, "head": 0, "period_start": 1,
                           "replay_from": 1, "complete": True})
                return
            self._subscribe(session, from_seq)
        elif kind == "prepare":
            mode = message.get("mode") or "spec"
            if mode not in MODES:
                self.send(_error(BAD_INPUT, "Invalid field: mode"))
                return
            session = self._session(create=True)
            future = session.prepare(self.token, mode, message.get("chatModelId"), message.get("createModelId"))
            self.send({"ctl": "prepareAck"})
            self._spawn(self._ready(future))
        else:
            self.send(_error(BAD_INPUT, "Unknown message type"))

    def _on_message(self, message: dict, text) -> None:
        if not isinstance(text, str) or not text:
            self.send(_error(BAD_INPUT, "Invalid field: prompt must be a string"))
            return
        mode = message.get("mode") or "spec"
        if mode not in MODES:
            self.send(_error(BAD_INPUT, "Invalid field: mode"))
            return
        session = self._session(create=True)
        if self.subscribed is not session:
            self._subscribe(session, None)  # the live tail, from now on
        routed, item_id = session.submit(
            text, "ws", self.token, mode, message.get("chatModelId"), message.get("createModelId"),
            item_id=_item_id(message.get("id")),
        )
        self.send({"ctl": "accepted", "id": item_id, "as": routed, "head": session.ring.head})

    async def _ready(self, future) -> None:
        try:
            status = await asyncio.wrap_future(future)
        except Exception as e:  # noqa: BLE001 - reported to the client
            logger.warning("Prepare failed for session %s: %s", (self.session_id or "")[:12], e)
            self.send(_error(SERVICE_UNAVAILABLE, "Prepare failed"))
            return
        self.send({"ctl": "ready", "mcp_status": status})


async def handle(websocket, context) -> None:
    """The ``@app.websocket`` handler."""
    offered = list(websocket.scope.get("subprotocols") or [])
    await websocket.accept(subprotocol=SUBPROTOCOL if SUBPROTOCOL in offered else None)
    await Connection(websocket, context).run()
