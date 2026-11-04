# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The agent's /ws entry (agent/ws_entry.py) over a real WebSocket.

basic_agent.app runs under uvicorn on 127.0.0.1 in a thread; the client is the
``websockets`` sync client with timeouts. Below the session runtime the turns are faked
(test_agent_session_runtime._Turns), except in the prepare test, which builds a real
session handle on fakes at the edges (agent_stop_fakes).
"""

import base64
import json
import socket
import threading
import time
import uuid

import pytest

from agent_modules import load
from test_agent_session_runtime import OWNED, _Busy, _jwt, _Turns

websockets_client = pytest.importorskip("websockets.sync.client")
uvicorn = pytest.importorskip("uvicorn")

SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
SUBPROTOCOL = "base64UrlBearerAuthorization"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def port():
    from test_agent_tool_exposure import _basic_agent

    app = _basic_agent().app
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    end = time.monotonic() + 10
    while not server.started and time.monotonic() < end:
        time.sleep(0.02)
    assert server.started
    yield port
    server.should_exit = True
    thread.join(5)


@pytest.fixture
def ctx(monkeypatch, port):
    from shared.session_owner import ProcessOwner

    runtime = load("session_runtime")
    session_guard = load("session_guard")
    resilience = load("resilience")
    stop_guard = load("stop_guard")
    monkeypatch.setattr(resilience, "_writes_closed", threading.Event())
    monkeypatch.setattr(stop_guard, "_running", {})
    monkeypatch.setattr(session_guard, "_process_owner", ProcessOwner())
    monkeypatch.setattr(session_guard, "_owned_legacy", set())
    busy = _Busy()
    registry = runtime.Registry(busy=busy)
    monkeypatch.setattr(runtime, "registry", registry)

    class Ctx:
        pass

    c = Ctx()
    c.port, c.busy, c.registry, c.runtime, c.monkeypatch = port, busy, registry, runtime, monkeypatch
    c.turns = None
    c.clients = []

    def fake_turns():
        c.turns = _Turns(monkeypatch, runtime)
        return c.turns

    c.fake_turns = fake_turns
    c.connect = lambda sub="user-1", sid=OWNED: _Client(c, sub, sid)
    try:
        yield c
    finally:
        if c.turns is not None:
            for gate in c.turns.gates.values():
                gate.set()
        for client in c.clients:
            client.close()


class _Client:
    """A WebSocket client that decodes frames and records their sizes and times."""

    def __init__(self, ctx, sub, sid):
        self.ws = websockets_client.connect(
            f"ws://127.0.0.1:{ctx.port}/ws",
            additional_headers={"Authorization": f"Bearer {_jwt(sub)}", SESSION_HEADER: sid},
            subprotocols=[SUBPROTOCOL],
            max_size=None,
            open_timeout=5,
            legacy=True,  # used without a with block; closed by the fixture
        )
        ctx.clients.append(self)
        self.ctl: list[dict] = []
        self.items: list[dict] = []
        self.frames: list[tuple[float, int]] = []
        self._chunks: dict = {}

    def send(self, **message):
        self.ws.send(json.dumps(message))

    def _take(self, timeout):
        frame = self.ws.recv(timeout=timeout)
        self.frames.append((time.monotonic(), len(frame.encode("utf-8"))))
        obj = json.loads(frame)
        if "ctl" in obj:
            self.ctl.append(obj)
        elif "batch" in obj:
            self.items.extend(obj["batch"])
        elif "chunk" in obj:
            parts = self._chunks.setdefault(obj["chunk"], {})
            parts[obj["i"]] = obj["data"]
            if len(parts) == obj["n"]:
                self.items.append(json.loads("".join(parts[i] for i in range(obj["n"]))))
        else:
            self.items.append(obj)

    def until(self, predicate, timeout=5.0):
        """Receive until predicate(ctl or ev) holds for something received."""
        end = time.monotonic() + timeout
        while not (any(predicate(c) for c in self.ctl) or any(predicate(i["ev"]) for i in self.items)):
            left = end - time.monotonic()
            if left <= 0:
                raise AssertionError(f"timed out; ctl={self.ctl} items={[i['ev'] for i in self.items]}")
            try:
                self._take(left)
            except TimeoutError:
                pass
        return self

    def close(self):
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


def _ctl(name):
    return lambda obj: obj.get("ctl") == name


def _idle(ev):
    return ev.get("work", {}).get("state") == "idle"


def _wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_nothing_is_sent_before_the_client_speaks(ctx):
    client = ctx.connect()

    assert client.ws.subprotocol == SUBPROTOCOL
    with pytest.raises(TimeoutError):
        client.ws.recv(timeout=0.5)
    client.send(type="ping")
    client.until(_ctl("pong"))


def test_a_prompt_runs_a_work_period(ctx):
    turns = ctx.fake_turns()
    client = ctx.connect()

    client.send(type="prompt", id="p1", prompt="hello", mode="spec")
    client.until(_ctl("accepted"))
    client.until(lambda ev: "event" in ev)
    assert ctx.busy.active == 1
    turns.release("hello")
    client.until(_idle)

    accepted = next(c for c in client.ctl if c["ctl"] == "accepted")
    assert accepted["id"] == "p1" and accepted["as"] == "turn"
    evs = [i["ev"] for i in client.items]
    assert evs[0] == {"work": {"state": "busy"}}
    assert evs[-1] == {"work": {"state": "idle", "how": "finished"}}
    seqs = [i["seq"] for i in client.items]
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))
    assert _wait_for(lambda: ctx.busy.active == 0)


def test_a_disconnect_does_not_stop_the_turn_and_resume_gets_the_missed_items(ctx):
    turns = ctx.fake_turns()
    first = ctx.connect()
    first.send(type="prompt", id="p1", prompt="work")
    first.until(lambda ev: "event" in ev)
    last = first.items[-1]["seq"]
    first.close()

    session = ctx.registry.get(OWNED, "user-1")
    assert _wait_for(lambda: session.subs == {})
    turns.release("work")
    assert _wait_for(lambda: not session.working), "the turn finished with nobody connected"

    second = ctx.connect()
    second.send(type="resume", from_seq=last)
    second.until(_idle)
    ack = next(c for c in second.ctl if c["ctl"] == "resumeAck")
    assert ack["working"] is False and ack["complete"] is True and ack["replay_from"] == last + 1
    assert [i["seq"] for i in second.items] == list(range(last + 1, session.ring.head + 1))
    assert [i["ev"]["turnEnd"]["how"] for i in second.items if "turnEnd" in i["ev"]] == ["finished"]


def test_a_reconnected_client_can_resume_the_live_tail_and_cancel(ctx):
    ctx.fake_turns()
    first = ctx.connect()
    first.send(type="prompt", id="p1", prompt="work")
    first.until(lambda ev: "event" in ev)
    first.close()

    second = ctx.connect()
    second.send(type="resume", from_seq=0)
    second.until(_ctl("resumeAck"))
    ack = next(c for c in second.ctl if c["ctl"] == "resumeAck")
    assert ack["working"] is True
    second.send(type="cancel", id="c1")
    second.until(_ctl("cancelAck")).until(_idle)

    assert next(c for c in second.ctl if c["ctl"] == "cancelAck") == {"ctl": "cancelAck", "id": "c1", "result": "cancelling"}
    evs = [i["ev"] for i in second.items]
    assert evs[0] == {"work": {"state": "busy"}}, "resume from 0 replays the period from its start"
    assert evs[-1]["work"]["how"] == "cancelled"


def test_resume_of_a_session_this_process_does_not_have(ctx):
    client = ctx.connect()
    client.send(type="resume", from_seq=12)
    client.until(_ctl("resumeAck"))

    ack = next(c for c in client.ctl if c["ctl"] == "resumeAck")
    assert ack["working"] is False and ack["head"] == 0
    assert ctx.registry._sessions == {}


@pytest.mark.parametrize("message", [
    {"type": "prompt", "id": "x", "prompt": "take over"},
    {"type": "steer", "id": "x", "text": "steer"},
    {"type": "cancel", "id": "x"},
    {"type": "resume", "from_seq": 0},
    {"type": "ping"},
])
def test_another_user_is_refused_and_the_owners_turn_is_untouched(ctx, message):
    ctx.fake_turns()
    owner = ctx.connect()
    owner.send(type="prompt", id="p1", prompt="work")
    owner.until(lambda ev: "event" in ev)

    other = ctx.connect(sub="user-2")
    other.ws.send(json.dumps(message))
    other.until(_ctl("error"))

    assert other.ctl[-1] == {"ctl": "error", "code": "auth", "error": "Session not available"}
    with pytest.raises(Exception):  # closed with 4403
        for _ in range(5):
            other.ws.recv(timeout=2)
    assert other.ws.close_code == 4403
    session = ctx.registry.get(OWNED, "user-1")
    assert session.working and not session.turn.stop.is_set()
    assert len(session.subs) == 1


def test_every_message_rechecks_the_owner(ctx):
    ctx.fake_turns()
    client = ctx.connect()
    client.send(type="prompt", id="p1", prompt="work")
    client.until(lambda ev: "event" in ev)
    session = ctx.registry.get(OWNED, "user-1")
    session.sub = "user-x"  # the session now belongs to someone else

    client.send(type="cancel", id="c1")
    client.until(_ctl("error"))

    assert client.ctl[-1]["code"] == "auth"
    assert not session.turn.stop.is_set()
    session.sub = "user-1"


def test_a_steer_mid_turn_is_accepted_then_delivered(ctx):
    turns = ctx.fake_turns()
    client = ctx.connect()
    client.send(type="prompt", id="p1", prompt="work")
    client.until(lambda ev: "event" in ev)

    client.send(type="steer", id="s1", text="make it blue")
    client.until(lambda c: c.get("ctl") == "accepted" and c.get("as") == "steer")
    client.until(lambda ev: ev.get("steer", {}).get("state") == "accepted")
    turns.release("work")
    client.until(lambda ev: ev.get("steer", {}).get("state") == "delivered")
    turns.release("make it blue")
    client.until(_idle)

    steer = [i["ev"]["steer"] for i in client.items if "steer" in i["ev"]]
    assert steer == [
        {"id": "s1", "text": "make it blue", "state": "accepted"},
        {"id": "s1", "state": "delivered", "how": "turn"},
    ]


def test_bad_messages_get_bad_input(ctx):
    client = ctx.connect()
    client.ws.send("not json")
    client.until(_ctl("error"))
    client.send(type="dance")
    client.send(type="prompt", prompt=["blocks"])
    client.send(type="resume", from_seq=-1)
    client.send(type="prompt", prompt="hi", mode="nope")
    client.until(lambda c: sum(1 for x in client.ctl if x.get("ctl") == "error") >= 5)

    assert [c["code"] for c in client.ctl if c.get("ctl") == "error"] == ["bad_input"] * 5
    assert ctx.registry._sessions == {}


def test_frames_stay_under_32_kb_and_the_rate_limit(ctx):
    session = ctx.registry.get_or_create(OWNED, "user-1")
    for n in range(100):
        session.publish({"toolStream": {"toolUseId": "t1", "name": "x", "data": {"blob": "あ" * 5000, "n": n}}})
    for n in range(2000):
        session.publish({"toolStream": {"toolUseId": "t1", "name": "x", "data": {"n": n}}})
    big = "スライド" * 30_000
    session.publish({"toolResult": {"toolUseId": "t1", "name": "x", "status": "success", "content": big}})

    client = ctx.connect()
    client.send(type="resume", from_seq=0)
    client.until(lambda ev: ev.get("toolResult", {}).get("content") == big, timeout=30)

    assert len(client.items) == 2101
    assert all(size <= 32 * 1024 for _, size in client.frames)
    times = [t for t, _ in client.frames]
    worst = max(sum(1 for u in times if t <= u < t + 1.0) for t in times)
    assert worst <= 51, worst
    small_frames = len(client.frames) - 100 - 1  # the 15 KB items go one per frame
    assert small_frames < 2000 / 20


# --- prepare ---------------------------------------------------------------------


@pytest.fixture
def real_handle(ctx, monkeypatch, tmp_path):
    """The real session handle on fakes at the edges; Memory's network calls recorded."""
    from agent_stop_fakes import FakeMCP, Recorder, ScriptedModel
    from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager as M

    factory = load("factory")
    import composition

    composition.clear_process_cache()
    recorder = Recorder(tmp_path / "calls.jsonl")

    def create_message(self, session_id, agent_id, session_message, **kwargs):
        recorder.log("memory", "create_message")
        return {"eventId": f"e{uuid.uuid4().hex[:8]}"}

    def create_agent(self, session_id, session_agent, **kwargs):
        recorder.log("memory", "create_agent")
        self._agent_created_at_cache[session_agent.agent_id] = session_agent.created_at

    def read_session(self, session_id, **kwargs):
        recorder.log("memory", "read_session")
        return None

    monkeypatch.setattr(M, "create_message", create_message)
    monkeypatch.setattr(M, "create_agent", create_agent)
    monkeypatch.setattr(M, "create_session", lambda self, session, **kwargs: recorder.log("memory", "create_session") or session)
    monkeypatch.setattr(M, "read_session", read_session)
    monkeypatch.setattr(M, "read_agent", lambda self, session_id, agent_id, **kwargs: None)
    monkeypatch.setattr(M, "list_messages", lambda self, *args, **kwargs: [])
    monkeypatch.setenv("MEMORY_ID", "memory-test")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    managers: list = []
    original = factory._session_manager

    def session_manager(*args):
        managers.append(args)
        return original(*args)

    monkeypatch.setattr(factory, "_session_manager", session_manager)
    monkeypatch.setattr(factory, "BedrockModel", lambda **kwargs: ScriptedModel(recorder))
    monkeypatch.setattr(factory, "_MCP_FACTORIES", [
        lambda jwt_token, session_id="", tool_filters=None, meta=None, **kwargs: FakeMCP(recorder, "parent", meta=meta),
    ])

    async def stream(agent, text, session_id, takeover, stop, **kwargs):
        recorder.log("stream", "turn", detail={"agent": id(agent)})
        yield {"event": {"contentBlockDelta": {"delta": {"text": "hi"}, "contentBlockIndex": 0}}}

    monkeypatch.setattr(ctx.runtime, "stream_agent", stream)
    try:
        yield recorder, managers
    finally:
        composition.clear_process_cache()


def test_prepare_builds_the_handle_without_memory_or_healthy_busy(ctx, real_handle):
    recorder, managers = real_handle
    client = ctx.connect()

    client.send(type="prepare", mode="spec")
    client.until(_ctl("prepareAck")).until(_ctl("ready"))

    assert [c["ctl"] for c in client.ctl] == ["prepareAck", "ready"]
    assert next(c for c in client.ctl if c["ctl"] == "ready")["mcp_status"][0]["status"] == "ok"
    records = recorder.read()
    assert [r["name"] for r in records if r["kind"] == "client"] == ["created"]
    assert [r["name"] for r in records if r["kind"] == "mcp"] == ["start_presentation"]
    assert not [r for r in records if r["kind"] == "memory"]
    assert managers == [] and ctx.busy.started == []
    session = ctx.registry.get(OWNED, "user-1")
    assert not session.working

    client.send(type="prompt", id="p1", prompt="hello")
    client.until(_idle)

    records = recorder.read()
    assert [r["name"] for r in records if r["kind"] == "client"] == ["created"], "the prompt reused the handle"
    assert [r["name"] for r in records if r["kind"] == "mcp"] == ["start_presentation"]
    assert len(managers) == 1
    assert [r["kind"] for r in records].count("stream") == 1
    assert len(ctx.busy.started) == 1


def test_a_steer_after_the_turn_ended_runs_in_its_mode_and_model_on_the_same_agent(ctx, real_handle, monkeypatch):
    recorder, managers = real_handle
    monkeypatch.setattr(load("factory"), "_ALLOWED_MODEL_IDS", {"chat-x"})
    client = ctx.connect()
    client.send(type="prompt", id="p1", prompt="hello", mode="vibe", chatModelId="chat-x")
    client.until(_idle)
    session = ctx.registry.get(OWNED, "user-1")
    first_agent = session.handle._agent

    client.send(type="steer", id="s1", text="one more thing")
    client.until(lambda c: c.get("ctl") == "accepted" and c.get("id") == "s1")
    assert next(c for c in client.ctl if c.get("id") == "s1")["as"] == "turn"
    assert _wait_for(lambda: [r["kind"] for r in recorder.read()].count("stream") == 2)
    assert _wait_for(lambda: not session.working)

    streams = [r["detail"]["agent"] for r in recorder.read() if r["kind"] == "stream"]
    assert streams[0] == streams[1] == id(first_agent), "the steer reused the vibe Agent"
    assert session.handle._agent_key[0] == "vibe" and "chat-x" in session.handle._agent_key
    assert len(managers) == 1, "no second Memory session manager"


def test_a_ws_steer_sent_while_a_stop_finishes_keeps_the_turns_mode_and_models(ctx):
    turns = ctx.fake_turns()
    turns.linger = 0.2
    client = ctx.connect()
    client.send(type="prompt", id="p1", prompt="work", mode="style_creator", chatModelId="chat-x", createModelId="create-y")
    client.until(lambda ev: "event" in ev)

    client.send(type="cancel", id="c1")
    client.until(_ctl("cancelAck"))
    client.send(type="steer", id="s1", text="next")
    client.until(lambda ev: "turn" in ev and ev["turn"]["text"] == "next")
    turns.release("next")
    client.until(lambda ev: _idle(ev) and ev["work"]["how"] == "finished")

    assert next(c for c in client.ctl if c.get("id") == "s1")["as"] == "turn"
    assert turns.settings == [("style_creator", "chat-x", "create-y")] * 2


def test_a_jwt_payload_is_never_echoed(ctx):
    # The connection's token stays server-side: no frame carries it.
    ctx.fake_turns()
    client = ctx.connect()
    client.send(type="prompt", id="p1", prompt="hello")
    client.until(lambda ev: "event" in ev)
    token_part = _jwt().split(".")[1]

    assert token_part not in json.dumps(client.ctl) + json.dumps(client.items)
    assert base64.urlsafe_b64decode(token_part + "==")  # sanity: it is a payload


# --- background compose ---------------------------------------------------------------


def test_resume_during_the_background_wait_replays_the_task_and_tails_its_end(ctx, monkeypatch, tmp_path):
    from test_agent_session_runtime import real_edges, stop_sessions

    real = real_edges(monkeypatch, tmp_path, ctx.runtime)
    real.composer_seconds = 1.5  # composers still write after the dispatching turn ended
    try:
        first = ctx.connect()
        first.send(type="prompt", id="p1", prompt="Make the deck.")
        first.until(lambda ev: "turnEnd" in ev, timeout=10)
        opened = next(i["seq"] for i in first.items if "turn" in i["ev"])
        first.close()
        session = ctx.registry.get(OWNED, "user-1")
        assert session.working and session.turn.done

        second = ctx.connect()
        second.send(type="resume", from_seq=opened - 1)
        second.until(_idle, timeout=15)

        ack = next(c for c in second.ctl if c["ctl"] == "resumeAck")
        assert ack["working"] is True and ack["complete"] is True
        evs = [i["ev"] for i in second.items]
        kinds = [next(iter(ev)) for ev in evs]
        assert kinds[0] == "turn" and "taskStart" in kinds
        first_end = kinds.index("turnEnd")
        assert "toolStream" in kinds[first_end:], "the composers' progress after the turn"
        assert kinds.index("taskEnd") > first_end
        assert [ev["turn"]["why"] for ev in evs if "turn" in ev] == ["prompt", "wake"]
        assert evs[-1]["work"] == {"state": "idle", "how": "finished"}
    finally:
        stop_sessions(ctx.registry)
