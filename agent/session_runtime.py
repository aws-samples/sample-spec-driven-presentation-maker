# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Session runtime: each session's turns, one at a time, and what a client sees of them.

A session is *working* while a turn runs or a follow-on turn is queued (a steer that
raced the end of a turn, a message sent while a stop finished). One work period is a
chain of turns; it publishes ``work busy`` at its start and ``work idle`` at its end,
and holds a HealthyBusy task (``/ping``) the whole time, so the platform does not
reclaim the microVM while nobody is connected (R8).

What reaches a session while it works:
- a message is a steer (steer_inbox.py), never a cancel. An HTTP prompt that arrives
  while an HTTP-started turn runs takes that turn over, as /invocations always did;
- ``cancel`` (the stop button) discards the steers not yet delivered, then sets the
  turn's stop event. A message sent while the stop finishes runs after it;
- a client going away cancels nothing, except an HTTP client's own HTTP turn (as
  before). Besides cancel, only the work-period watchdog (WORK_LIMIT_S) and SIGTERM
  stop a turn.

Every turn of every session runs on one event-loop thread (``sdpm-session-runtime``),
so a turn never depends on the connection that started it. Events go into the
session's EventRing (event_ring.py) and out to its subscribers (WebSocket connections,
HTTP responses), each with its own event loop and queue.

Subscriber queues receive ``("ctl", dict)`` and ``("items", [ring items])`` entries,
in publication order.
"""

import asyncio
import contextvars
import hmac
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass

import stop_guard
from errors import AUTH, SERVICE_UNAVAILABLE, error_event
from event_ring import COALESCE_S, EventRing
from resilience import writes_closed
from session_handle import SessionHandle
from streaming import stream_agent
from turn_fence import TurnFence

logger = logging.getLogger("sdpm.agent")

WORK_LIMIT_S = 3600.0  # the watchdog: one work period at most (the longest seen was 41 min)
IDLE_CLOSE_S = 30 * 60.0  # a session not working and unused this long is closed (lazily)
MAX_SESSIONS = 16
KEEPALIVE_S = 5.0

# Events of the session runtime itself; HTTP responses keep today's shapes without them.
RUNTIME_EVENTS = ("work", "turn", "turnEnd", "steer")


# -- the runtime loop ---------------------------------------------------------

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def runtime_loop() -> asyncio.AbstractEventLoop:
    """The event loop every session's turns run on (started on first use)."""
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            loop = asyncio.new_event_loop()
            ready = threading.Event()

            def run() -> None:
                asyncio.set_event_loop(loop)
                loop.call_soon(ready.set)
                loop.run_forever()

            threading.Thread(target=run, daemon=True, name="sdpm-session-runtime").start()
            ready.wait(10)
            _loop = loop
        return _loop


def _log(kind: str, **fields) -> None:
    logger.info(json.dumps({"kind": kind, **fields}, ensure_ascii=False))


class BusyTracker:
    """HealthyBusy for ``/ping``: BedrockAgentCoreApp.add_async_task / complete_async_task."""

    def __init__(self, add=None, complete=None):
        self._add = add
        self._complete = complete

    def start(self, name: str, metadata: dict | None = None):
        return self._add(name, metadata) if self._add is not None else None

    def complete(self, task_id) -> None:
        if self._complete is not None and task_id is not None:
            self._complete(task_id)


@dataclass
class Prompt:
    text: str
    origin: str  # "ws" | "http" | "steer"
    mode: str = "spec"
    chat_model_id: str | None = None
    create_model_id: str | None = None
    why: str = "prompt"
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = secrets.token_hex(6)


class Turn:
    """One running turn: its write fence, its stop event (set on SIGTERM too) and the
    HTTP takeover event (stream_agent's ``cancel``)."""

    def __init__(self, prompt: Prompt):
        self.prompt = prompt
        self.id = prompt.id
        self.fence = TurnFence()
        self.stop = stop_guard.begin_turn(on_stop=self.fence.advance)
        self.takeover = asyncio.Event()
        self.how: str | None = None  # why it was stopped (cancelled, watchdog, takeover)
        self.done = False


class Session:
    """One session's runtime state (see the module docstring). Thread-safe."""

    def __init__(self, session_id: str, sub: str, busy: BusyTracker):
        self.id = session_id
        self.sub = sub
        self.busy = busy
        self.handle = SessionHandle(session_id, sub)
        self.handle.on_steer_delivered = self._steer_delivered
        self.inbox = self.handle.inbox
        self.ring = EventRing()
        self.lock = threading.RLock()
        self.subs: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = {}
        self.turn: Turn | None = None
        self.next_prompts: list[Prompt] = []
        self.working = False
        self.period = 0
        self.closed = False
        self.last_active = time.monotonic()
        self._period_started = 0.0
        self._period_how: str | None = None  # set by the watchdog / SIGTERM
        self._flush_armed = False
        self._task = None

    # -- events -----------------------------------------------------------------

    def _broadcast(self, items: list[dict]) -> None:
        if not items:
            return
        for loop, queue in list(self.subs.values()):
            try:
                loop.call_soon_threadsafe(queue.put_nowait, ("items", items))
            except RuntimeError:  # the subscriber's loop is gone
                pass

    def publish(self, ev: dict) -> None:
        with self.lock:
            self._broadcast(self.ring.publish(ev))
            if self.ring.pending and not self._flush_armed:
                self._flush_armed = True
                runtime_loop().call_soon_threadsafe(self._arm_flush)

    def _arm_flush(self) -> None:
        runtime_loop().call_later(COALESCE_S, self._flush_due)

    def _flush_due(self) -> None:
        with self.lock:
            self._flush_armed = False
            self._broadcast(self.ring.flush())

    def subscribe(self, key: str, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue,
                  from_seq: int | None = None) -> dict:
        """Register a subscriber. With ``from_seq`` (resume) the queue first gets a
        ``resumeAck`` and the items after it; without, only live items. Returns the
        resume information."""
        with self.lock:
            self.last_active = time.monotonic()
            info = {"working": self.working, "head": self.ring.head, "period_start": self.ring.period_start}
            if from_seq is not None:
                items, replay_from, complete = self.ring.replay(from_seq)
                info.update(replay_from=replay_from, complete=complete)
                loop.call_soon_threadsafe(queue.put_nowait, ("ctl", {"ctl": "resumeAck", **info}))
                if items:
                    loop.call_soon_threadsafe(queue.put_nowait, ("items", items))
            self.subs[key] = (loop, queue)
            return info

    def unsubscribe(self, key: str) -> None:
        """Forget a subscriber. Never cancels anything (a dropped connection is not a stop)."""
        with self.lock:
            self.subs.pop(key, None)
            self.last_active = time.monotonic()

    # -- input ------------------------------------------------------------------

    def submit(self, text: str, origin: str, token: str, mode: str = "spec",
               chat_model_id: str | None = None, create_model_id: str | None = None,
               item_id: str = "") -> tuple[str, str]:
        """A user message: a new turn when idle, a steer while working.

        Returns (``"turn"`` | ``"steer"``, id). Raises PermissionError for another
        user's token and RuntimeError once the session is closed.
        """
        self.handle.update_token(token)
        prompt = Prompt(text, origin, mode or "spec", chat_model_id, create_model_id, id=item_id)
        with self.lock:
            if self.closed:
                raise RuntimeError("session closed")
            self.last_active = time.monotonic()
            if not self.working:
                self._start_period(prompt)
                return "turn", prompt.id
            current = self.turn
            if current is not None and current.stop.is_set():
                # A stop is finishing: this runs as the next turn once it has.
                self.next_prompts.append(prompt)
                return "turn", prompt.id
            if origin == "http" and current is not None and current.prompt.origin == "http":
                # /invocations as before: a newer HTTP prompt takes over the HTTP turn
                # once its running tool has returned (or follows it if it just ended).
                if not current.done:
                    current.how = "takeover"
                    runtime_loop().call_soon_threadsafe(current.takeover.set)
                self.next_prompts.append(prompt)
                return "turn", prompt.id
            self.inbox.put(prompt.id, text)
            self.publish({"steer": {"id": prompt.id, "text": text, "state": "accepted"}})
            _log("session_steer", state="accepted", session_id=self.id[:12], period=self.period)
            return "steer", prompt.id

    def cancel(self) -> str:
        """The stop button: ``"cancelling"`` while working, else ``"idle"``."""
        with self.lock:
            if not self.working:
                return "idle"
            self._stop_locked("cancelled")
            return "cancelling"

    def cancel_turn(self, turn_id: str) -> None:
        """Cancel one turn if it is still running or queued (an HTTP client went away)."""
        with self.lock:
            self.next_prompts = [p for p in self.next_prompts if p.id != turn_id]
            if self.turn is not None and self.turn.id == turn_id and not self.turn.done:
                self._stop_locked("cancelled")

    def _discard_steers_locked(self, how: str) -> None:
        for item_id, _ in self.inbox.discard():
            self.publish({"steer": {"id": item_id, "state": "discarded", "how": how}})
            _log("session_steer", state="discarded", session_id=self.id[:12], period=self.period, how=how)

    def _stop_locked(self, how: str) -> None:
        # Steers first, so none is folded into the closing tool result (R2).
        self._discard_steers_locked(how)
        current = self.turn
        if current is not None and not current.done and not current.stop.is_set():
            current.how = current.how or how
            current.stop.set()

    def prepare(self, token: str, mode: str = "spec", chat_model_id: str | None = None,
                create_model_id: str | None = None):
        """Build the session handle early (no Memory, no HealthyBusy). A Future of the
        MCP status list."""
        with self.lock:
            if self.closed:
                raise RuntimeError("session closed")
            self.last_active = time.monotonic()
        return self.handle.prepare(token, mode or "spec", chat_model_id, create_model_id)

    # -- work -------------------------------------------------------------------

    def _new_turn_locked(self, prompt: Prompt) -> Turn:
        turn = Turn(prompt)
        self.turn = turn
        self.publish({"turn": {"id": turn.id, "why": prompt.why, "text": prompt.text}})
        return turn

    def _start_period(self, prompt: Prompt) -> None:
        self.working = True
        self.period += 1
        self._period_how = None
        self._period_started = time.monotonic()
        self.ring.start_period()
        self.publish({"work": {"state": "busy"}})
        _log("session_work", state="busy", session_id=self.id[:12], period=self.period)
        turn = self._new_turn_locked(prompt)
        context = contextvars.copy_context()
        loop = runtime_loop()

        def start() -> None:
            self._task = loop.create_task(self._work(turn), context=context)

        loop.call_soon_threadsafe(start)

    def _watchdog(self) -> None:
        with self.lock:
            if not self.working:
                return
            logger.warning("Session %s: work period over %.0fs; stopping it", self.id[:12], WORK_LIMIT_S)
            self._period_how = "watchdog"
            self.next_prompts.clear()
            self._stop_locked("watchdog")

    def _next_turn_locked(self) -> Turn | None:
        if self._period_how is not None or writes_closed():
            self.next_prompts.clear()
            self._discard_steers_locked(self._period_how or "sigterm")
            return None
        if self.next_prompts:
            return self._new_turn_locked(self.next_prompts.pop(0))
        items = self.inbox.drain()
        if not items:
            return None
        for item_id, _ in items:
            self.publish({"steer": {"id": item_id, "state": "delivered", "how": "turn"}})
        _log("session_steer", state="delivered", session_id=self.id[:12], period=self.period, how="turn", n=len(items))
        last = self.turn.prompt if self.turn is not None else Prompt("", "steer")
        return self._new_turn_locked(Prompt(
            "\n\n".join(text for _, text in items), "steer", last.mode, last.chat_model_id,
            last.create_model_id, why="steer",
        ))

    def _end_period_locked(self, how: str) -> None:
        how = self._period_how or how
        self.publish({"work": {"state": "idle", "how": how}})
        _log("session_work", state="idle", session_id=self.id[:12], period=self.period, how=how,
             ms=int((time.monotonic() - self._period_started) * 1000))
        self.working = False
        self.turn = None
        self.last_active = time.monotonic()

    async def _work(self, turn: Turn) -> None:
        busy = self.busy.start("sdpm-session-work", {"session": self.id[:12], "period": self.period})
        watchdog = asyncio.get_running_loop().call_later(WORK_LIMIT_S, self._watchdog)
        how = "error"
        try:
            while turn is not None:
                how = await self._run_turn(turn)
                with self.lock:
                    turn = self._next_turn_locked()
                    if turn is None:
                        self._end_period_locked(how)
        finally:
            watchdog.cancel()
            with self.lock:
                if self.working and (self.turn is None or self.turn.done):
                    self._end_period_locked(how)
            self.busy.complete(busy)

    async def _run_turn(self, turn: Turn) -> str:
        prompt, stop = turn.prompt, turn.stop
        how = "finished"
        try:
            # The holder's token, not the prompt's: a later steer may have brought a newer one.
            agent, mcp_status = await asyncio.to_thread(
                self.handle.begin_turn, self.handle.holder.token, turn.fence, prompt.mode,
                prompt.chat_model_id, prompt.create_model_id, stop,
            )
            self.publish({"mcp_status": mcp_status})
            async for event in stream_agent(agent, prompt.text, self.id, turn.takeover, stop):
                if isinstance(event, dict) and "keepalive" in event:
                    continue
                self.publish(event)
        except Exception as e:
            logger.exception("Agent stream error for session %s", self.id[:12])
            self.publish(error_event(e))
            how = "error"
        finally:
            stop_guard.end_turn(stop)
            # Stopped (cancel, watchdog, an HTTP takeover or its client gone, SIGTERM):
            # fence the turn's decks. hold: a SIGTERM that follows (StopRuntimeSession
            # after a cancel) waits for the call.
            if stop.is_set():
                stop_guard.hold(turn.fence.advance())
                how = turn.how or ("sigterm" if writes_closed() else "cancelled")
            else:
                turn.fence.release()
            self.handle.end_turn()
            with self.lock:
                turn.done = True
                self.publish({"turnEnd": {"id": turn.id, "how": how}})
        return how

    def _steer_delivered(self, items, how: str) -> None:
        for item_id, _ in items:
            self.publish({"steer": {"id": item_id, "state": "delivered", "how": how}})
        _log("session_steer", state="delivered", session_id=self.id[:12], period=self.period, how=how, n=len(items))

    # -- lifetime ---------------------------------------------------------------

    def idle_for(self) -> float:
        with self.lock:
            return 0.0 if self.working else time.monotonic() - self.last_active

    def close(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self._stop_locked("sigterm")
        self.handle.close()


class Registry:
    """The sessions of this process, each bound to its owner's ``sub``."""

    def __init__(self, busy: BusyTracker | None = None, max_sessions: int = MAX_SESSIONS,
                 idle_close_s: float = IDLE_CLOSE_S):
        self.busy = busy or BusyTracker()
        self.max_sessions = max_sessions
        self.idle_close_s = idle_close_s
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}

    def get(self, session_id: str, sub: str) -> Session | None:
        """The session if it exists. PermissionError when it belongs to another user."""
        with self._lock:
            session = self._sessions.get(session_id)
        if session is not None and not hmac.compare_digest(session.sub.encode(), sub.encode()):
            raise PermissionError("session of another user")
        return session

    def get_or_create(self, session_id: str, sub: str) -> Session:
        """PermissionError for another user's session; RuntimeError when the process
        already keeps MAX_SESSIONS working sessions."""
        closing: list[Session] = []
        try:
            with self._lock:
                for sid, session in list(self._sessions.items()):
                    if session.idle_for() > self.idle_close_s:
                        closing.append(self._sessions.pop(sid))
                session = self._sessions.get(session_id)
                if session is not None:
                    if not hmac.compare_digest(session.sub.encode(), sub.encode()):
                        raise PermissionError("session of another user")
                    return session
                if len(self._sessions) >= self.max_sessions:
                    idle = sorted((s for s in self._sessions.values() if not s.working), key=lambda s: s.last_active)
                    if not idle:
                        raise RuntimeError("too many working sessions in this process")
                    closing.append(self._sessions.pop(idle[0].id))
                session = self._sessions[session_id] = Session(session_id, sub, self.busy)
                return session
        finally:
            for old in closing:
                old.close()

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                session.close()
            except Exception as e:  # noqa: BLE001 - best effort (SIGTERM)
                logger.warning("Closing session %s failed: %s", session.id[:12], e)


registry = Registry()


def configure(busy: BusyTracker) -> None:
    registry.busy = busy
    stop_guard.add_close_hook(lambda: registry.close_all())


def _http_visible(ev: dict) -> bool:
    return not any(key in ev for key in RUNTIME_EVENTS)


async def http_turn(session_id: str, sub: str, token: str, prompt: str, mode: str = "spec",
                    chat_model_id: str | None = None, create_model_id: str | None = None,
                    sessions: Registry | None = None):
    """/invocations on the session runtime, with today's event shapes.

    A prompt while idle (or one that takes over an HTTP turn) streams its own turn and
    ends with it; a prompt during WebSocket-started work is a steer, and the response
    follows the session until it goes idle. A client that goes away cancels its own
    HTTP turn only.
    """
    sessions = sessions or registry
    try:
        session = sessions.get_or_create(session_id, sub)
    except PermissionError:
        yield error_event("Session not available", code=AUTH)
        return
    except RuntimeError as e:
        yield error_event(str(e), code=SERVICE_UNAVAILABLE)
        return
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    key = f"http-{secrets.token_hex(4)}"
    session.subscribe(key, loop, queue)
    routed, turn_id = None, ""
    try:
        try:
            routed, turn_id = session.submit(prompt, "http", token, mode, chat_model_id, create_model_id)
        except PermissionError:
            yield error_event("Session not available", code=AUTH)
            return
        except RuntimeError as e:
            yield error_event(str(e), code=SERVICE_UNAVAILABLE)
            return
        mine = False
        while True:
            try:
                kind, payload = await asyncio.wait_for(queue.get(), KEEPALIVE_S)
            except asyncio.TimeoutError:
                yield {"keepalive": True}
                continue
            if kind != "items":
                continue
            for item in payload:
                ev = item["ev"]
                if "work" in ev and ev["work"].get("state") == "idle":
                    return
                if routed == "turn":
                    if "turn" in ev:
                        mine = ev["turn"].get("id") == turn_id
                        continue
                    if "turnEnd" in ev and ev["turnEnd"].get("id") == turn_id:
                        return
                    if mine and _http_visible(ev):
                        yield ev
                elif _http_visible(ev):
                    yield ev
    finally:
        session.unsubscribe(key)
        if routed == "turn":
            session.cancel_turn(turn_id)
