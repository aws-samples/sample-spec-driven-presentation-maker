# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Session runtime: each session's turns, one at a time, and what a client sees of them.

A session is *working* while a turn runs, a follow-on turn is queued (a steer that
raced the end of a turn), a background task (compose_slides, background.py) has not
settled, or a settled one's result has not been delivered. One work period is that
whole stretch; it publishes ``work busy`` at its start and ``work idle`` at its end,
and holds a HealthyBusy task (``/ping``) the whole time, so the platform does not
reclaim the microVM while nobody is connected (R8).

Between turns, while a background task works, the period waits. A task that settles
publishes ``taskEnd``; when no turn runs, the runtime then starts one with no input
(``turn {why: "wake"}``), and Strands delivers the result before its model call. A wake
that leaves the same tasks undelivered does not start another.

What reaches a session while it works:
- a message is a steer (steer_inbox.py), never a cancel: folded into the running turn,
  or a turn of its own at once when none runs. An HTTP prompt that arrives while an
  HTTP-started turn runs takes that turn over, as /invocations always did;
- ``cancel`` (the stop button) discards the steers not yet delivered, sets the period's
  stop event (the one tools and background tasks see), then the running turn's, then
  cancels the background tasks; with no turn running it fences the decks the tasks
  write (an idle TurnFence). A message sent while the stop finishes opens a new period
  after it;
- a client going away cancels nothing, except an HTTP client's own running HTTP turn
  (as before). Besides cancel, only the work-period watchdog (WORK_LIMIT_S) and
  SIGTERM stop the work.
- a composer's report_to_orchestrator (compose_messaging.py) publishes ``composerNote``
  and is delivered like a steer, as a ``<composer_note>`` text: folded into the running
  turn, or a turn of its own (``turn {why: "report"}``); it never makes a ``steer`` event.

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
import html
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass

import background
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
TASK_POLL_S = 0.25  # how often a period looks at its background tasks
STOP_SETTLE_S = 5.0  # a stopped period waits this long at most for its tasks to settle

# Events of the session runtime itself; HTTP responses keep today's shapes without them
# (``taskEnd`` reaches them as the toolResult the dispatch used to be).
RUNTIME_EVENTS = ("work", "turn", "turnEnd", "steer", "taskStart", "composerNote")

# Inbox ids of composer notes (Session.report): delivered like steers, never a steer event.
NOTE_PREFIX = "note-"


def _is_note(item_id: str) -> bool:
    return item_id.startswith(NOTE_PREFIX)


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


class Period:
    """One work period: its stop event (registered with stop_guard for the whole period,
    so SIGTERM sets it; tools and background tasks see it as TURN_STOP_KEY), why it was
    stopped, and the work loop's wake-up."""

    def __init__(self, number: int, on_stop):
        self.number = number
        self.stop = stop_guard.begin_turn(on_stop=lambda: on_stop(self))
        self.stopped_how: str | None = None
        self.stopped_at: float | None = None
        self.wake = asyncio.Event()
        self.undelivered_seen: set[str] = set()  # task ids a wake turn was started for
        self.monitor: asyncio.Task | None = None
        self._claim = threading.RLock()  # re-entrant: SIGTERM's handler may interrupt a holder
        self._claimed = False

    def claim_stop(self, how: str) -> bool:
        """Stop the period; True for the first caller only."""
        with self._claim:
            first = not self._claimed
            self._claimed = True
            if first:
                self.stopped_how = how
                self.stopped_at = time.monotonic()
        self.stop.set()
        return first


class Session:
    """One session's runtime state (see the module docstring). Thread-safe."""

    def __init__(self, session_id: str, sub: str, busy: BusyTracker):
        self.id = session_id
        self.sub = sub
        self.busy = busy
        self.handle = SessionHandle(session_id, sub)
        self.handle.on_steer_delivered = self._steer_delivered
        self.handle.on_background_event = self.publish
        self.handle.on_task_end = self._task_ended
        self.handle.compose_messaging.on_report = self.report
        self.inbox = self.handle.inbox
        self.ring = EventRing()
        self.lock = threading.RLock()
        self.subs: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = {}
        self.turn: Turn | None = None
        # (mode, chat model, create model) of the latest turn, kept after its period
        # ends: a steer, which carries none of them, runs with these.
        self.settings: tuple[str, str | None, str | None] = ("spec", None, None)
        self.next_prompts: list[Prompt] = []
        self.working = False
        self.period = 0
        self.closed = False
        self.last_active = time.monotonic()
        self._period_started = 0.0
        self._period: Period | None = None
        self._ended_tasks: set[str] = set()  # task ids whose taskEnd was published
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

    def submit(self, text: str, origin: str, token: str, mode: str | None = "spec",
               chat_model_id: str | None = None, create_model_id: str | None = None,
               item_id: str = "", inherit: bool = False) -> tuple[str, str]:
        """A user message: a new turn when idle, a steer while working.

        ``inherit`` (a WebSocket ``steer``): a mode or model left as None is that of the
        latest turn, or of the message queued to run next, so a steer that becomes a turn
        runs where the conversation was (``spec`` and the default models only before the
        session's first turn).

        Returns (``"turn"`` | ``"steer"``, id). Raises PermissionError for another
        user's token and RuntimeError once the session is closed.
        """
        self.handle.update_token(token)
        with self.lock:
            if self.closed:
                raise RuntimeError("session closed")
            if inherit:
                last = self.next_prompts[-1] if self.next_prompts else None
                last_mode, last_chat, last_create = (
                    (last.mode, last.chat_model_id, last.create_model_id) if last else self.settings)
                mode = mode or last_mode
                chat_model_id = chat_model_id or last_chat
                create_model_id = create_model_id or last_create
            prompt = Prompt(text, origin, mode or "spec", chat_model_id, create_model_id, id=item_id)
            self.last_active = time.monotonic()
            if not self.working:
                self._start_period(prompt)
                return "turn", prompt.id
            current = self.turn
            idle_turn = current is None or current.done
            if self._period.stop.is_set() or (not idle_turn and current.stop.is_set()):
                # A stop is finishing: this runs once it has (after a stopped period, in a
                # new one).
                self.next_prompts.append(prompt)
                return "turn", prompt.id
            if origin == "http" and current is not None and current.prompt.origin == "http":
                # /invocations as before: a newer HTTP prompt takes over the HTTP turn
                # once its running tool has returned (or follows it if it just ended).
                if not current.done:
                    current.how = "takeover"
                    runtime_loop().call_soon_threadsafe(current.takeover.set)
                self.next_prompts.append(prompt)
                self._wake_soon()
                return "turn", prompt.id
            self.inbox.put(prompt.id, text)
            self.publish({"steer": {"id": prompt.id, "text": text, "state": "accepted"}})
            _log("session_steer", state="accepted", session_id=self.id[:12], period=self.period)
            if idle_turn:
                self._wake_soon()  # working with no turn running (a background task): a turn now
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
            if _is_note(item_id):
                continue
            self.publish({"steer": {"id": item_id, "state": "discarded", "how": how}})
            _log("session_steer", state="discarded", session_id=self.id[:12], period=self.period, how=how)

    def report(self, tool_use_id: str, group: int, slugs: list[str], text: str) -> bool:
        """A composer's report_to_orchestrator (compose_messaging.py, on a composer's thread):
        publish ``composerNote`` and put the note into the inbox, where it is folded into
        the running turn or starts one (``why: "report"``). False once the work is stopped."""
        with self.lock:
            period = self._period
            if self.closed or period is None or period.stop.is_set() or writes_closed():
                return False
            label = ", ".join(slugs)
            self.publish({"composerNote": {"toolUseId": tool_use_id, "group": group, "slugs": label, "text": text}})
            # Escaped, so the composer's text cannot close the note (chatHistory.ts unescapes).
            self.inbox.put(f"{NOTE_PREFIX}{secrets.token_hex(6)}",
                           f'<composer_note group="{group}" slugs="{html.escape(label)}">'
                           f'{html.escape(text, quote=False)}</composer_note>')
        self._wake_soon(period)
        return True

    def _stop_locked(self, how: str) -> None:
        # Steers first, so none is folded into the closing tool result (R2).
        self._discard_steers_locked(how)
        period = self._period
        if period is None:
            return
        # The period's stop first: what tools and background tasks see.
        first = period.claim_stop(how)
        current = self.turn
        if current is not None and not current.done and not current.stop.is_set():
            current.how = current.how or how
            current.stop.set()
        if first:
            stop_guard.hold(self._after_stop(period))

    def _period_stopped(self, period: Period):
        """stop_guard's callback for a period's stop event (SIGTERM, on the signal
        handler's thread): non-blocking; returns the idle fence's thread, if any."""
        if not period.claim_stop("sigterm"):
            return None
        return self._after_stop(period)

    def _after_stop(self, period: Period):
        """After a period's stop event is set: fence the background tasks' decks when no
        turn runs (a running turn's own fence has them), cancel the tasks, wake the work
        loop. Returns the fence call's thread or None."""
        current = self.turn
        thread = self._idle_fence() if current is None or current.done else None
        agent = self.handle.agent
        if background.pending(agent):
            loop = runtime_loop()
            loop.call_soon_threadsafe(lambda: loop.create_task(background.cancel_all(agent)))
        self._wake_soon(period)
        return thread

    def _idle_fence(self):
        """A fence for the decks the session's background tasks write, minted now (its
        generation is later than any turn's that started them)."""
        fence = TurnFence()
        fence.bind(self.handle.fence_client())
        fence.note_decks(list(self.handle.task_decks))
        return fence.advance()

    def _wake_soon(self, period: Period | None = None) -> None:
        """Wake the period's work loop (thread-safe)."""
        period = period or self._period
        if period is None:
            return
        try:
            runtime_loop().call_soon_threadsafe(period.wake.set)
        except RuntimeError:  # the loop is closed (process exit)
            pass

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
        self.settings = (prompt.mode, prompt.chat_model_id, prompt.create_model_id)
        self.publish({"turn": {"id": turn.id, "why": prompt.why, "text": prompt.text}})
        return turn

    def _start_period(self, prompt: Prompt) -> None:
        self.working = True
        self.period += 1
        period = self._period = Period(self.period, self._period_stopped)
        self._period_started = time.monotonic()
        self.ring.start_period()
        self.publish({"work": {"state": "busy"}})
        _log("session_work", state="busy", session_id=self.id[:12], period=self.period)
        turn = self._new_turn_locked(prompt)
        context = contextvars.copy_context()
        loop = runtime_loop()

        def start() -> None:
            self._task = loop.create_task(self._work(period, turn), context=context)

        loop.call_soon_threadsafe(start)

    def _watchdog(self) -> None:
        with self.lock:
            if not self.working:
                return
            logger.warning("Session %s: work period over %.0fs; stopping it", self.id[:12], WORK_LIMIT_S)
            self.next_prompts.clear()
            self._stop_locked("watchdog")

    def _next_turn_locked(self, period: Period) -> Turn | None:
        """The period's next turn: a queued prompt, the pending steers, or a wake for
        settled background results; none once the period is stopped."""
        if period.stop.is_set() or writes_closed():
            if period.stopped_how == "watchdog" or writes_closed():
                self.next_prompts.clear()
            self._discard_steers_locked(period.stopped_how or "sigterm")
            return None
        if self.next_prompts:
            return self._new_turn_locked(self.next_prompts.pop(0))
        mode, chat_model_id, create_model_id = self.settings
        items = self.inbox.drain()
        if items:
            steers = [item_id for item_id, _ in items if not _is_note(item_id)]
            for item_id in steers:
                self.publish({"steer": {"id": item_id, "state": "delivered", "how": "turn"}})
            if steers:
                _log("session_steer", state="delivered", session_id=self.id[:12], period=self.period, how="turn",
                     n=len(steers))
            return self._new_turn_locked(Prompt(
                "\n\n".join(text for _, text in items), "steer", mode, chat_model_id,
                create_model_id, why="steer" if steers else "report",
            ))
        settled = {task["task_id"] for task in background.undelivered(self.handle.agent)}
        if settled - period.undelivered_seen:
            # A wake that leaves the same tasks undelivered does not start another.
            period.undelivered_seen |= settled
            _log("session_wake", session_id=self.id[:12], period=self.period, tasks=len(settled))
            return self._new_turn_locked(Prompt("", "wake", mode, chat_model_id, create_model_id, why="wake"))
        return None

    def _waiting_locked(self, period: Period) -> bool:
        """Whether the period waits for background tasks (a stopped one, briefly)."""
        if not background.pending(self.handle.agent):
            return False
        if not period.stop.is_set():
            return True
        if period.stopped_at is None:
            period.stopped_at = time.monotonic()
        return time.monotonic() - period.stopped_at < STOP_SETTLE_S

    def _end_period_locked(self, period: Period, how: str) -> None:
        how = period.stopped_how or how
        self.publish({"work": {"state": "idle", "how": how}})
        _log("session_work", state="idle", session_id=self.id[:12], period=self.period, how=how,
             ms=int((time.monotonic() - self._period_started) * 1000))
        self.working = False
        self.turn = None
        self._period = None
        self.last_active = time.monotonic()
        if self.next_prompts and not self.closed and not writes_closed():
            # Sent while a stop finished: a new period, with a fresh stop event.
            self._start_period(self.next_prompts.pop(0))

    async def _work(self, period: Period, turn: Turn | None) -> None:
        busy = self.busy.start("sdpm-session-work", {"session": self.id[:12], "period": period.number})
        watchdog = asyncio.get_running_loop().call_later(WORK_LIMIT_S, self._watchdog)
        how = "error"
        try:
            while True:
                if turn is not None:
                    how = await self._run_turn(period, turn)
                self._scan_tasks()
                if background.pending(self.handle.agent):
                    self._ensure_monitor(period)
                with self.lock:
                    turn = self._next_turn_locked(period)
                    if turn is not None:
                        continue
                    if not self._waiting_locked(period):
                        self._end_period_locked(period, how)
                        break
                    period.wake.clear()
                try:
                    await asyncio.wait_for(period.wake.wait(), TASK_POLL_S)
                except asyncio.TimeoutError:
                    pass
        finally:
            watchdog.cancel()
            stop_guard.end_turn(period.stop)
            if period.monitor is not None:
                period.monitor.cancel()
            with self.lock:
                if self._period is period and (self.turn is None or self.turn.done):
                    self._end_period_locked(period, how)
            self.busy.complete(busy)

    # -- background tasks ------------------------------------------------------------

    def _ensure_monitor(self, period: Period) -> None:
        if period.monitor is None or period.monitor.done():
            period.monitor = asyncio.get_running_loop().create_task(self._monitor())

    async def _monitor(self) -> None:
        """While a background task is pending: publish each one that settles."""
        while True:
            self._scan_tasks()
            if not background.pending(self.handle.agent):
                self.handle.task_decks.clear()
                return
            await asyncio.sleep(TASK_POLL_S)

    def _scan_tasks(self) -> None:
        for task in background.undelivered(self.handle.agent):
            self._task_ended(task)

    def _task_ended(self, task: dict) -> None:
        """A task settled (seen in the Agent's snapshots, or in the message that delivers
        it): publish ``taskEnd`` once, and wake the work loop."""
        task_id = task.get("task_id")
        with self.lock:
            if not task_id or task_id in self._ended_tasks:
                return
            self._ended_tasks.add(task_id)
            self.publish({"taskEnd": {
                "toolUseId": task.get("tool_use_id", ""), "taskId": task_id, "name": task.get("tool_name", ""),
                "status": task.get("status", ""), "content": background.result_text(task),
            }})
            _log("session_task", state="end", status=task.get("status"), session_id=self.id[:12], period=self.period)
        self._wake_soon()

    async def _run_turn(self, period: Period, turn: Turn) -> str:
        prompt, stop = turn.prompt, turn.stop
        how = "finished"
        try:
            # The holder's token, not the prompt's: a later steer may have brought a newer one.
            agent, mcp_status = await asyncio.to_thread(
                self.handle.begin_turn, self.handle.holder.token, turn.fence, prompt.mode,
                prompt.chat_model_id, prompt.create_model_id, stop,
            )
            self.publish({"mcp_status": mcp_status})
            text = None if prompt.why == "wake" else prompt.text
            async for event in stream_agent(agent, text, self.id, turn.takeover, stop, tool_stop=period.stop):
                if isinstance(event, dict) and "keepalive" in event:
                    continue
                self.publish(event)
                if isinstance(event, dict) and "taskStart" in event:
                    _log("session_task", state="start", name=event["taskStart"].get("name"),
                         session_id=self.id[:12], period=self.period)
                    self._ensure_monitor(period)
        except Exception as e:
            logger.exception("Agent stream error for session %s", self.id[:12])
            self.publish(error_event(e))
            how = "error"
        finally:
            stop_guard.end_turn(stop)
            self.handle.end_turn()
            with self.lock:
                # Under the lock: a stop either sees this turn running (and sets its stop
                # before this point) or done (and fences the tasks' decks itself).
                # Stopped (cancel, watchdog, an HTTP takeover or its client gone, SIGTERM):
                # fence the turn's decks. hold: a SIGTERM that follows (StopRuntimeSession
                # after a cancel) waits for the call.
                if stop.is_set():
                    stop_guard.hold(turn.fence.advance())
                    how = turn.how or ("sigterm" if writes_closed() else "cancelled")
                else:
                    turn.fence.release()
                turn.done = True
                self.publish({"turnEnd": {"id": turn.id, "how": how}})
        return how

    def _steer_delivered(self, items, how: str) -> None:
        steers = [item_id for item_id, _ in items if not _is_note(item_id)]
        if not steers:
            return
        for item_id in steers:
            self.publish({"steer": {"id": item_id, "state": "delivered", "how": how}})
        _log("session_steer", state="delivered", session_id=self.id[:12], period=self.period, how=how, n=len(steers))

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


def _task_result(end: dict) -> dict:
    """A ``taskEnd`` as the toolResult /invocations clients know."""
    return {"toolResult": {
        "toolUseId": end.get("toolUseId", ""), "name": end.get("name", ""),
        "status": "error" if end.get("status") == "failed" else "success", "content": end.get("content", ""),
    }}


def _still_queued(session: Session, turn_id: str) -> bool:
    """Whether a prompt is queued to run, or runs now (not dropped by a stop)."""
    with session.lock:
        return any(p.id == turn_id for p in session.next_prompts) or (
            session.turn is not None and session.turn.id == turn_id)


async def http_turn(session_id: str, sub: str, token: str, prompt: str, mode: str = "spec",
                    chat_model_id: str | None = None, create_model_id: str | None = None,
                    sessions: Registry | None = None):
    """/invocations on the session runtime, with today's event shapes.

    A prompt while idle (or one that takes over an HTTP turn) streams its own turn and
    ends with it; a turn that dispatched a background task follows the session until it
    goes idle instead (the wake turn's answer included). A prompt during
    WebSocket-started work is a steer, and the response follows the session until it
    goes idle. A task's ``taskEnd`` arrives as the toolResult its dispatch used to be.
    A client that goes away cancels its own running HTTP turn only.
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
        mine = follow = started = False
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
                    if routed == "turn" and not started and _still_queued(session, turn_id):
                        continue  # a stopped period's end: this prompt runs in the next one
                    return
                if routed == "turn":
                    if "turn" in ev:
                        mine = ev["turn"].get("id") == turn_id
                        started = started or mine
                        continue
                    if "taskStart" in ev:
                        follow = follow or mine
                        continue
                    if "turnEnd" in ev:
                        if ev["turnEnd"].get("id") == turn_id and not follow:
                            return
                        mine = False
                        continue
                    if not (mine or follow):
                        continue
                if "taskEnd" in ev:
                    yield _task_result(ev["taskEnd"])
                elif _http_visible(ev):
                    yield ev
    finally:
        session.unsubscribe(key)
        if routed == "turn":
            session.cancel_turn(turn_id)
