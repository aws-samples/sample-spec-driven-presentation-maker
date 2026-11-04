# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Each session's turns, one at a time, and what reaches a working session
(agent/session_runtime.py).

Below the runtime, the session handle's build and the agent's stream are faked
(``_Turns``); one test runs a real Strands Agent to see a steer delivered.
"""

import asyncio
import base64
import json
import threading
import time

import pytest

from agent_modules import load

OWNED = "c6c289e49e9c05b2-00000000-0000-4000-8000-000000000000"  # a session of user-1


def _jwt(sub: str = "user-1", n: int = 0) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"sub": sub, "n": n}).encode()).decode().rstrip("=")
    return f"h.{body}.s"


class _Busy:
    def __init__(self):
        self.lock = threading.Lock()
        self.started: list = []
        self.completed: list = []

    def start(self, name, metadata=None):
        with self.lock:
            self.started.append(name)
            return len(self.started)

    def complete(self, task_id):
        with self.lock:
            self.completed.append(task_id)

    @property
    def active(self) -> int:
        with self.lock:
            return len(self.started) - len(self.completed)


class _Turns:
    """Fake turns. A turn streams one text event, then waits until its gate opens (or it
    is stopped / taken over). ``linger`` keeps a stopped turn finishing a while."""

    def __init__(self, monkeypatch, runtime):
        self.gates: dict[str, threading.Event] = {}
        self.prompts: list[str] = []
        self.handles: list = []
        self.settings: list[tuple] = []
        self.linger = 0.0
        self.fail: set[str] = set()
        handle_class = load("session_handle").SessionHandle
        turns = self

        def begin_turn(handle, token, fence, mode="spec", chat_model_id=None, create_model_id=None, stop=None):
            turns.handles.append(handle)
            turns.settings.append((mode, chat_model_id, create_model_id))
            handle.update_token(token)
            return object(), [{"name": "Presentation Maker", "status": "ok"}]

        async def stream(agent, text, session_id, takeover, stop, **kwargs):
            turns.prompts.append(text)
            if text in turns.fail:
                raise RuntimeError("model unreachable")
            yield {"event": {"contentBlockDelta": {"delta": {"text": f"re:{text}"}, "contentBlockIndex": 0}}}
            gate = turns.gates.setdefault(text, threading.Event())
            while not (gate.is_set() or stop.is_set() or takeover.is_set()):
                await asyncio.sleep(0.01)
            if takeover.is_set():
                stop.set()  # what stream_agent does when it leaves early
            if stop.is_set() and turns.linger:
                await asyncio.sleep(turns.linger)
            yield {"event": {"messageStop": {"stopReason": "end_turn"}}}

        monkeypatch.setattr(handle_class, "begin_turn", begin_turn)
        monkeypatch.setattr(runtime, "stream_agent", stream)

    def release(self, text: str) -> None:
        self.gates.setdefault(text, threading.Event()).set()


class _Tail:
    """A subscriber on its own event loop thread, like a WebSocket connection."""

    def __init__(self, session, from_seq=None, key="tail"):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.queue = asyncio.run_coroutine_threadsafe(self._make_queue(), self.loop).result(5)
        self.session = session
        self.key = key
        self.info = session.subscribe(key, self.loop, self.queue, from_seq)
        self.ctl: list[dict] = []
        self.items: list[dict] = []

    async def _make_queue(self):
        return asyncio.Queue()

    def _take(self, timeout: float):
        kind, payload = asyncio.run_coroutine_threadsafe(asyncio.wait_for(self.queue.get(), timeout), self.loop).result(timeout + 1)
        if kind == "ctl":
            self.ctl.append(payload)
        else:
            self.items.extend(payload)

    def until(self, predicate, timeout: float = 5.0) -> list[dict]:
        end = time.monotonic() + timeout
        while not any(predicate(i["ev"]) for i in self.items):
            left = end - time.monotonic()
            if left <= 0:
                raise AssertionError(f"timed out; got {[i['ev'] for i in self.items]}")
            try:
                self._take(left)
            except (TimeoutError, asyncio.TimeoutError):
                pass
        return [i["ev"] for i in self.items]

    def close(self):
        self.session.unsubscribe(self.key)
        self.loop.call_soon_threadsafe(self.loop.stop)


def _idle(ev) -> bool:
    return ev.get("work", {}).get("state") == "idle"


@pytest.fixture
def rt(monkeypatch):
    runtime = load("session_runtime")
    resilience = load("resilience")
    stop_guard = load("stop_guard")
    monkeypatch.setattr(resilience, "_writes_closed", threading.Event())
    monkeypatch.setattr(stop_guard, "_running", {})
    busy = _Busy()
    registry = runtime.Registry(busy=busy)
    monkeypatch.setattr(runtime, "registry", registry)
    turns = _Turns(monkeypatch, runtime)
    tails: list[_Tail] = []

    class RT:
        pass

    r = RT()
    r.runtime, r.busy, r.registry, r.turns, r.stop_guard = runtime, busy, registry, turns, stop_guard
    r.session = lambda sid=OWNED, sub="user-1": registry.get_or_create(sid, sub)

    def tail(session, from_seq=None):
        t = _Tail(session, from_seq, key=f"tail{len(tails)}")
        tails.append(t)
        return t

    r.tail = tail
    try:
        yield r
    finally:
        for gate in turns.gates.values():
            gate.set()
        for t in tails:
            t.close()


def _wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_a_work_period_is_busy_then_idle_and_holds_healthy_busy(rt):
    session = rt.session()
    tail = rt.tail(session)

    assert session.submit("hello", "ws", _jwt()) == ("turn", session.turn.id)
    tail.until(lambda ev: "event" in ev)
    assert rt.busy.active == 1
    rt.turns.release("hello")
    evs = tail.until(_idle)

    kinds = [next(iter(ev)) for ev in evs]
    assert kinds[0] == "work" and evs[0]["work"] == {"state": "busy"}
    assert kinds[1] == "turn" and evs[1]["turn"]["why"] == "prompt" and evs[1]["turn"]["text"] == "hello"
    assert "mcp_status" in kinds and kinds[-2] == "turnEnd"
    assert evs[-1]["work"] == {"state": "idle", "how": "finished"}
    assert _wait_for(lambda: rt.busy.active == 0)
    assert len(rt.busy.started) == 1
    seqs = [i["seq"] for i in tail.items]
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))
    assert not session.working


def test_healthy_busy_is_removed_when_the_turn_fails(rt):
    session = rt.session()
    tail = rt.tail(session)
    rt.turns.fail.add("boom")

    session.submit("boom", "ws", _jwt())
    evs = tail.until(_idle)

    assert any(ev.get("status") == "error" for ev in evs)
    assert evs[-1]["work"] == {"state": "idle", "how": "error"}
    assert _wait_for(lambda: rt.busy.active == 0)


def test_cancel_stops_the_turn_and_discards_pending_steers(rt):
    session = rt.session()
    tail = rt.tail(session)
    session.submit("work", "ws", _jwt())
    tail.until(lambda ev: "event" in ev)
    assert session.submit("also this", "ws", _jwt())[0] == "steer"

    assert session.cancel() == "cancelling"
    evs = tail.until(_idle)

    steer_states = [ev["steer"]["state"] for ev in evs if "steer" in ev]
    assert steer_states == ["accepted", "discarded"]
    assert [ev["turnEnd"]["how"] for ev in evs if "turnEnd" in ev] == ["cancelled"]
    assert evs[-1]["work"]["how"] == "cancelled"
    assert rt.turns.prompts == ["work"], "the discarded steer never ran"
    assert _wait_for(lambda: rt.busy.active == 0)
    assert session.cancel() == "idle"


def test_a_steer_after_the_last_boundary_becomes_a_new_turn_in_the_same_period(rt):
    session = rt.session()
    tail = rt.tail(session)
    session.submit("first", "ws", _jwt())
    tail.until(lambda ev: "event" in ev)

    routed, steer_id = session.submit("one more thing", "ws", _jwt(n=1))
    rt.turns.release("first")
    tail.until(lambda ev: "turn" in ev and ev["turn"]["why"] == "steer")
    rt.turns.release("one more thing")
    evs = tail.until(_idle)

    assert routed == "steer"
    assert [ev["work"]["state"] for ev in evs if "work" in ev] == ["busy", "idle"]
    assert [ev["turn"]["text"] for ev in evs if "turn" in ev] == ["first", "one more thing"]
    assert {"steer": {"id": steer_id, "state": "delivered", "how": "turn"}} in evs
    assert session.handle.holder.token == _jwt(n=1), "the steer's newer token is used"
    assert len(rt.busy.started) == 1


def test_a_message_sent_while_a_stop_finishes_runs_after_it(rt):
    session = rt.session()
    tail = rt.tail(session)
    rt.turns.linger = 0.2
    session.submit("work", "ws", _jwt())
    tail.until(lambda ev: "event" in ev)

    session.cancel()
    assert session.submit("next", "ws", _jwt())[0] == "turn"
    tail.until(lambda ev: "turn" in ev and ev["turn"]["text"] == "next")
    rt.turns.release("next")
    evs = tail.until(_idle)

    assert [ev["turnEnd"]["how"] for ev in evs if "turnEnd" in ev] == ["cancelled", "finished"]
    assert evs[-1]["work"]["how"] == "finished"


@pytest.mark.parametrize("mode", ["vibe", "style_creator"])
def test_a_steer_after_the_session_went_idle_keeps_the_latest_turns_mode_and_models(rt, mode):
    session = rt.session()
    tail = rt.tail(session)
    session.submit("first", "ws", _jwt(), mode, "chat-x", "create-y")
    rt.turns.release("first")
    tail.until(_idle)

    # The steer raced the end of the turn: it carries no mode or models.
    assert session.submit("one more thing", "ws", _jwt(), None, inherit=True)[0] == "turn"
    rt.turns.release("one more thing")
    assert _wait_for(lambda: not session.working and len(rt.turns.settings) == 2)
    session.submit("a new prompt", "ws", _jwt(), "spec")
    rt.turns.release("a new prompt")
    assert _wait_for(lambda: not session.working and len(rt.turns.settings) == 3)

    assert rt.turns.settings == [(mode, "chat-x", "create-y"), (mode, "chat-x", "create-y"), ("spec", None, None)]


def test_a_steer_sent_while_a_stop_finishes_keeps_the_turns_mode_and_models(rt):
    session = rt.session()
    tail = rt.tail(session)
    rt.turns.linger = 0.2
    session.submit("work", "ws", _jwt(), "vibe", "chat-x")
    tail.until(lambda ev: "event" in ev)

    session.cancel()
    assert session.submit("next", "ws", _jwt(), None, inherit=True)[0] == "turn"
    tail.until(lambda ev: "turn" in ev and ev["turn"]["text"] == "next")
    rt.turns.release("next")
    tail.until(_idle)

    assert rt.turns.settings == [("vibe", "chat-x", None), ("vibe", "chat-x", None)]


def test_a_steer_before_any_turn_runs_in_spec_with_the_default_models(rt):
    session = rt.session()
    session.submit("hello", "ws", _jwt(), None, inherit=True)
    rt.turns.release("hello")
    assert _wait_for(lambda: not session.working and rt.turns.settings)

    assert rt.turns.settings == [("spec", None, None)]


def test_nobody_listening_cancels_nothing(rt):
    session = rt.session()
    tail = rt.tail(session)
    session.submit("work", "ws", _jwt())
    tail.until(lambda ev: "event" in ev)
    tail.close()
    assert session.subs == {}

    time.sleep(0.1)
    assert session.working and not session.turn.stop.is_set()
    rt.turns.release("work")
    assert _wait_for(lambda: not session.working)

    late = rt.tail(session, from_seq=0)
    evs = late.until(_idle)
    assert late.ctl[0]["ctl"] == "resumeAck" and late.ctl[0]["working"] is False
    assert [ev["turnEnd"]["how"] for ev in evs if "turnEnd" in ev] == ["finished"]


def test_resume_replays_what_was_missed_then_the_live_tail(rt):
    session = rt.session()
    first = rt.tail(session)
    session.submit("work", "ws", _jwt())
    first.until(lambda ev: "event" in ev)
    last_seen = first.items[-1]["seq"]
    first.close()

    second = rt.tail(session, from_seq=last_seen - 1)
    rt.turns.release("work")
    second.until(_idle)

    ack = second.ctl[0]
    assert ack["ctl"] == "resumeAck" and ack["working"] is True and ack["complete"] is True
    assert ack["replay_from"] == last_seen
    assert second.items[0]["seq"] == last_seen
    seqs = [i["seq"] for i in second.items]
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))


def test_the_watchdog_ends_a_work_period(rt, monkeypatch):
    monkeypatch.setattr(rt.runtime, "WORK_LIMIT_S", 0.2)
    session = rt.session()
    tail = rt.tail(session)
    session.submit("forever", "ws", _jwt())
    session.submit("pending steer", "ws", _jwt())

    evs = tail.until(_idle, timeout=5)

    assert evs[-1]["work"] == {"state": "idle", "how": "watchdog"}
    assert [ev["turnEnd"]["how"] for ev in evs if "turnEnd" in ev] == ["watchdog"]
    assert any(ev.get("steer", {}).get("state") == "discarded" for ev in evs)
    assert _wait_for(lambda: rt.busy.active == 0)


def test_the_handle_survives_a_cancelled_turn(rt):
    session = rt.session()
    tail = rt.tail(session)
    session.submit("a", "ws", _jwt())
    tail.until(lambda ev: "event" in ev)
    session.cancel()
    tail.until(_idle)
    session.submit("b", "ws", _jwt())
    rt.turns.release("b")
    _wait_for(lambda: not session.working)

    assert rt.turns.handles[0] is rt.turns.handles[1] is session.handle
    assert not session.handle.closed


def test_another_users_token_or_session_is_refused(rt):
    session = rt.session()

    with pytest.raises(PermissionError):
        session.submit("hi", "ws", _jwt("user-2"))
    with pytest.raises(PermissionError):
        rt.registry.get_or_create(OWNED, "user-2")
    with pytest.raises(PermissionError):
        rt.registry.get(OWNED, "user-2")
    assert not session.working


def test_sigterm_stops_the_turn_and_closes_the_sessions(rt, monkeypatch):
    monkeypatch.setattr(rt.stop_guard, "_close_hooks", [])
    rt.stop_guard.add_close_hook(rt.registry.close_all)
    session = rt.session()
    tail = rt.tail(session)
    session.submit("work", "ws", _jwt())
    tail.until(lambda ev: "event" in ev)

    assert rt.stop_guard.stop_all() == 1
    evs = tail.until(_idle)
    rt.stop_guard._close_resident_clients()

    assert [ev["turnEnd"]["how"] for ev in evs if "turnEnd" in ev] == ["sigterm"]
    assert session.handle.closed and session.closed
    assert rt.registry._sessions == {}
    with pytest.raises(RuntimeError):
        session.submit("after", "ws", _jwt())
    assert _wait_for(lambda: rt.busy.active == 0)


def test_idle_sessions_are_closed_lazily_and_the_count_is_capped(rt, monkeypatch):
    registry = rt.runtime.Registry(busy=rt.busy, max_sessions=2, idle_close_s=60)
    a = registry.get_or_create("c6c289e49e9c05b2-a", "user-1")
    b = registry.get_or_create("c6c289e49e9c05b2-b", "user-1")
    c = registry.get_or_create("c6c289e49e9c05b2-c", "user-1")

    assert a.closed and not b.closed and not c.closed, "the least recently used idle one goes"
    b.last_active -= 61
    registry.get_or_create("c6c289e49e9c05b2-c", "user-1")
    assert b.closed
    assert set(registry._sessions) == {"c6c289e49e9c05b2-c"}


# --- HTTP /invocations on the runtime ------------------------------------------


def _http(rt, prompt, sub="user-1", collected=None, stop_after=None):
    """Run http_turn on a thread with its own loop; returns (thread, events)."""
    events = collected if collected is not None else []

    async def run():
        gen = rt.runtime.http_turn(OWNED, sub, _jwt(sub), prompt)
        try:
            async for ev in gen:
                events.append(ev)
                if stop_after is not None and stop_after(ev):
                    break  # the client goes away
        finally:
            await gen.aclose()

    thread = threading.Thread(target=lambda: asyncio.run(run()), daemon=True)
    thread.start()
    return thread, events


def test_an_http_turn_streams_todays_event_shapes(rt):
    thread, events = _http(rt, "hello")
    assert _wait_for(lambda: rt.turns.prompts == ["hello"])
    rt.turns.release("hello")
    thread.join(5)

    assert not thread.is_alive()
    assert events[0] == {"mcp_status": [{"name": "Presentation Maker", "status": "ok"}]}
    assert all(not any(k in ev for k in ("work", "turn", "turnEnd", "steer")) for ev in events)
    assert events[-1] == {"event": {"messageStop": {"stopReason": "end_turn"}}}


def test_a_second_http_prompt_takes_over_the_first_http_turn(rt):
    first, first_events = _http(rt, "one")
    assert _wait_for(lambda: rt.turns.prompts == ["one"])
    second, second_events = _http(rt, "two")
    first.join(5)
    assert _wait_for(lambda: rt.turns.prompts == ["one", "two"])
    rt.turns.release("two")
    second.join(5)

    assert not first.is_alive() and not second.is_alive()
    assert any("re:one" in json.dumps(ev) for ev in first_events)
    assert not any("re:two" in json.dumps(ev) for ev in first_events)
    assert any("re:two" in json.dumps(ev) for ev in second_events)


def test_an_http_client_that_goes_away_cancels_its_own_turn(rt):
    session = rt.session()
    tail = rt.tail(session)
    thread, _ = _http(rt, "hello", stop_after=lambda ev: "event" in ev)
    thread.join(5)

    evs = tail.until(_idle)
    assert [ev["turnEnd"]["how"] for ev in evs if "turnEnd" in ev] == ["cancelled"]


def test_an_http_prompt_during_websocket_work_is_a_steer(rt):
    session = rt.session()
    tail = rt.tail(session)
    session.submit("ws work", "ws", _jwt())
    tail.until(lambda ev: "event" in ev)

    thread, events = _http(rt, "from http", stop_after=lambda ev: False)
    tail.until(lambda ev: "steer" in ev)
    assert not session.turn.stop.is_set(), "the WebSocket turn keeps running"
    rt.turns.release("ws work")
    tail.until(lambda ev: "turn" in ev and ev["turn"]["why"] == "steer")
    rt.turns.release("from http")
    thread.join(5)

    assert not thread.is_alive()
    evs = tail.until(_idle)
    assert [ev["turnEnd"]["how"] for ev in evs if "turnEnd" in ev] == ["finished", "finished"]
    assert any("re:from http" in json.dumps(ev) for ev in events)
    assert all(not any(k in ev for k in ("work", "turn", "turnEnd", "steer")) for ev in events)


def test_an_http_prompt_for_another_users_session_is_refused(rt):
    rt.session()
    thread, events = _http(rt, "hi", sub="user-2")
    thread.join(5)

    assert events == [{"status": "error", "code": "auth", "error": "Session not available"}]


# --- a real agent ------------------------------------------------------------------


def test_a_steer_reaches_a_real_agent_and_is_reported_delivered(rt, monkeypatch, tmp_path):
    from strands import Agent, tool
    from strands.session.file_session_manager import FileSessionManager

    from test_agent_steer_inbox import _Model, _shape

    runtime = rt.runtime
    monkeypatch.setattr(runtime, "stream_agent", load("streaming").stream_agent)
    in_tool = threading.Event()
    release = threading.Event()

    @tool
    def build() -> str:
        """Build the deck."""
        in_tool.set()
        assert release.wait(5)
        return "built"

    agents: list = []

    def begin_turn(handle, token, fence, mode="spec", chat_model_id=None, create_model_id=None, stop=None):
        handle.update_token(token)
        handle.stop = stop
        if not agents:
            agents.append(Agent(
                model=_Model([("tool", "build"), ("text", "Done in blue.")]), tools=[build],
                session_manager=FileSessionManager(session_id="s1", storage_dir=str(tmp_path)),
                plugins=[handle.steer_plugin()], callback_handler=None,
            ))
        return agents[0], []

    monkeypatch.setattr(load("session_handle").SessionHandle, "begin_turn", begin_turn)
    session = rt.session()
    tail = rt.tail(session)
    session.submit("Make a deck.", "ws", _jwt())
    assert in_tool.wait(5)

    _, steer_id = session.submit("make it blue", "ws", _jwt())
    release.set()
    evs = tail.until(_idle)

    assert {"steer": {"id": steer_id, "state": "delivered", "how": "fold"}} in evs
    assert ("user", ["toolResult", "text:make it blue"]) in _shape(agents[0].messages)
    assert [ev["turn"]["text"] for ev in evs if "turn" in ev] == ["Make a deck."], "no extra turn"
