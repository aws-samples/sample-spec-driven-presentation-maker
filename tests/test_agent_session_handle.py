# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A session keeps its MCP clients, Agent and Memory session manager across turns.

agent/session_handle.py with the factory's edges faked: the Presentation Maker client,
the resident AWS clients, the model, the Agent and the Memory session manager.
"""

import base64
import json
import threading
import time

import pytest

from agent_modules import load


def _jwt(sub: str, n: int = 0) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"sub": sub, "n": n}).encode()).decode().rstrip("=")
    return f"h.{body}.s"


class _PM:
    """Presentation Maker client: connects once, answers start_presentation."""

    server_instructions = ""

    def __init__(self, state, session_id, tool_filters, token):
        self.state = state
        self.session_id = session_id
        self.tool_filters = tool_filters
        self.token = token
        self.started = False
        self.connects = 0
        self.restarts = 0
        self.dead = False
        self.stopped = False
        self.consumers: set = set()

    async def load_tools(self, **kwargs):
        if not self.started:
            self.started = True
            self.connects += 1
        return []

    def alive(self):
        return not self.dead

    def restart(self):
        self.restarts += 1
        self.dead = False

    def add_consumer(self, consumer_id, **kwargs):
        self.consumers.add(consumer_id)

    def remove_consumer(self, consumer_id, **kwargs):
        self.consumers.discard(consumer_id)
        if not self.consumers:
            self.stopped = True

    def stop(self, *exc):
        self.stopped = True

    def call_tool_sync(self, tool_use_id, name, arguments, **kwargs):
        self.state["calls"].append((self.token.token if self.token else "", name))
        payload = {"static": {"workflow": "# Orchestrator"}, "styles": [], "templates": []}
        return {"status": "success", "content": [{"text": json.dumps(payload)}]}


class _Resident:
    server_instructions = ""

    def __init__(self, name, gate=None):
        self.name = name
        self.gate = gate
        self.stopped = False

    def add_consumer(self, consumer_id, **kwargs):
        pass

    async def load_tools(self, **kwargs):
        if self.gate is not None:
            assert self.gate.wait(5)
        return []

    def list_tools_sync(self, *args, **kwargs):
        return []

    def stop(self, *exc):
        self.stopped = True


class _Hooks:
    def __init__(self):
        self.callbacks = []

    def add_callback(self, event, callback):
        self.callbacks.append((event, callback))


class _Registry:
    def __init__(self):
        self.added = []

    def process_tools(self, tools):
        self.added.extend(tools)
        return []


class _Agent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.messages = []
        self.hooks = _Hooks()
        # Strands registers the management tool with the background plugin.
        self.tool_names = [load("background").MANAGE_TOOL] if "background_tasks" in kwargs else []
        self.system_prompt = ""
        self.tool_registry = _Registry()
        self.cleaned = False
        self.state: dict = {}  # agent.state.get(key), where Strands keeps the task snapshots
        self.middleware: list = []
        self.added_hooks: list = []

    def add_middleware(self, stage, handler):
        self.middleware.append((stage, handler))

    def add_hook(self, callback, event_type=None, **kwargs):
        self.added_hooks.append((event_type, callback))

    def cleanup(self):
        self.cleaned = True


@pytest.fixture
def env(monkeypatch):
    factory = load("factory")
    session_handle = load("session_handle")
    import composition
    import mcp_clients

    composition.clear_process_cache()
    mcp_clients.close_resident_clients()
    state = {"calls": [], "pm": [], "residents": [], "managers": [], "composer": None, "gate": None}

    def runtime(jwt_token="", session_id="", tool_filters=None, token=None):
        client = _PM(state, session_id, tool_filters, token)
        state["pm"].append(client)
        return client

    def resident(name):
        client = _Resident(name, gate=state["gate"])
        state["residents"].append(client)
        return client

    def session_manager(memory_id, session_id, user_id, region):
        manager = object()
        state["managers"].append((manager, session_id, user_id))
        return manager

    def make_compose_slides(mcp_servers, model, composer_mcp_factory, **kwargs):
        state["composer"] = composer_mcp_factory
        state["compose_servers"] = mcp_servers
        return object()

    monkeypatch.setenv("MEMORY_ID", "mem-1")
    monkeypatch.setattr(factory, "mcp_agentcore_runtime", runtime)
    monkeypatch.setattr(factory, "mcp_aws_knowledge", lambda: resident("AWS Knowledge"))
    monkeypatch.setattr(factory, "mcp_aws_pricing", lambda: resident("AWS Pricing"))
    monkeypatch.setattr(factory, "BedrockModel", lambda **kwargs: object())
    monkeypatch.setattr(factory, "make_compose_slides", make_compose_slides)
    monkeypatch.setattr(factory, "Agent", _Agent)
    monkeypatch.setattr(factory, "_session_manager", session_manager)
    state["factory"] = factory
    state["handle"] = lambda sub="user-1", sid="s1": session_handle.SessionHandle(sid, sub)
    try:
        yield state
    finally:
        if state["gate"] is not None:
            state["gate"].set()
        mcp_clients.close_resident_clients()
        composition.clear_process_cache()


def _wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_the_second_turn_reuses_the_clients_and_the_agent(env):
    handle = env["handle"]()
    first, _ = handle.begin_turn(_jwt("user-1"))
    handle.end_turn()
    second, status = handle.begin_turn(_jwt("user-1", 1))

    assert second is first
    (pm,) = env["pm"]
    assert pm.connects == 1
    assert [c[1] for c in env["calls"]] == ["start_presentation"]
    assert len(env["managers"]) == 1
    assert status[0] == {"name": "Presentation Maker", "status": "ok"}


def test_each_turn_swaps_the_token(env):
    handle = env["handle"]()
    handle.begin_turn(_jwt("user-1", 0))
    (pm,) = env["pm"]
    composer = env["composer"]("s1-g1")
    handle.end_turn()

    handle.begin_turn(_jwt("user-1", 1))
    pm.call_tool_sync("t", "run_python", {})

    assert pm.token is handle.holder
    assert env["calls"][-1] == (_jwt("user-1", 1), "run_python")
    assert composer.token is handle.holder


def test_a_dead_presentation_maker_client_is_restarted_at_the_turn_start(env):
    handle = env["handle"]()
    handle.begin_turn(_jwt("user-1"))
    handle.end_turn()
    (pm,) = env["pm"]
    pm.dead = True

    handle.begin_turn(_jwt("user-1"))

    assert pm.restarts == 1
    assert len(env["pm"]) == 1


def test_spec_to_vibe_rebuilds_the_agent_but_keeps_the_client(env):
    handle = env["handle"]()
    spec, _ = handle.begin_turn(_jwt("user-1"), mode="spec")
    handle.end_turn()
    vibe, _ = handle.begin_turn(_jwt("user-1"), mode="vibe")

    assert vibe is not spec and spec.cleaned
    assert len(env["pm"]) == 1
    assert len(env["managers"]) == 2, "a new Agent needs its own session manager"
    assert vibe.kwargs["session_manager"] is env["managers"][1][0]


def test_style_creator_gets_its_own_allowlisted_client(env):
    handle = env["handle"]()
    handle.begin_turn(_jwt("user-1"), mode="spec")
    handle.end_turn()
    handle.begin_turn(_jwt("user-1"), mode="style_creator")

    assert len(env["pm"]) == 2
    assert env["pm"][1].tool_filters == {"allowed": load("modes").MODES["style_creator"].allowed_tools}


def test_a_model_change_rebuilds_the_agent_with_a_new_session_manager(env, monkeypatch):
    factory = env["factory"]
    monkeypatch.setattr(factory, "_ALLOWED_MODEL_IDS", {"m-a", "m-b"})
    handle = env["handle"]()
    first, _ = handle.begin_turn(_jwt("user-1"), chat_model_id="m-a")
    handle.end_turn()
    same, _ = handle.begin_turn(_jwt("user-1"), chat_model_id="m-a")
    handle.end_turn()
    other, _ = handle.begin_turn(_jwt("user-1"), chat_model_id="m-b")

    assert same is first
    assert other is not first and first.cleaned
    assert len(env["managers"]) == 2
    assert env["pm"][0].connects == 1


def test_a_turn_of_another_user_is_refused(env):
    handle = env["handle"]()
    agent, _ = handle.begin_turn(_jwt("user-1"))
    handle.end_turn()

    with pytest.raises(PermissionError):
        handle.begin_turn(_jwt("user-2"))
    with pytest.raises(PermissionError):
        handle.update_token(_jwt("user-2"))

    assert handle.holder.token == _jwt("user-1")
    again, _ = handle.begin_turn(_jwt("user-1"))
    assert again is agent


def test_prepare_builds_no_session_manager_and_the_first_prompt_one(env):
    handle = env["handle"]()

    status = handle.prepare(_jwt("user-1")).result(5)

    assert status[0] == {"name": "Presentation Maker", "status": "ok"}
    assert env["managers"] == []
    (pm,) = env["pm"]
    assert pm.connects == 1
    assert [c[1] for c in env["calls"]] == ["start_presentation"]
    assert handle.prepare(_jwt("user-1")).result(5) == status, "idempotent"

    agent, _ = handle.begin_turn(_jwt("user-1"))

    assert len(env["managers"]) == 1
    assert agent.kwargs["session_manager"] is env["managers"][0][0]
    assert pm.connects == 1
    assert [c[1] for c in env["calls"]] == ["start_presentation"]


def test_a_stopped_turn_leaves_the_handle_reusable(env):
    handle = env["handle"]()
    stop = threading.Event()
    first, _ = handle.begin_turn(_jwt("user-1"), stop=stop)
    stop.set()
    assert handle.stopped()
    handle.end_turn()

    second, _ = handle.begin_turn(_jwt("user-1"))

    assert second is first and not handle.stopped()
    assert env["pm"][0].connects == 1 and not env["pm"][0].stopped


def test_the_agents_hooks_act_on_the_current_turn(env):
    handle = env["handle"]()
    handle.begin_turn(_jwt("user-1"))
    guard_1 = handle.loop_guard
    handle.end_turn()
    handle.begin_turn(_jwt("user-1"))

    assert handle.loop_guard is not None and handle.loop_guard is not guard_1


def test_a_resident_that_connects_later_joins_the_agent(env):
    env["gate"] = threading.Event()  # the resident servers connect only once released
    handle = env["handle"]()
    agent, first = handle.begin_turn(_jwt("user-1"))
    assert [s["status"] for s in first] == ["ok", "error", "error"]
    handle.end_turn()
    env["gate"].set()
    import mcp_clients

    assert _wait_for(lambda: all(r.connected is not None for r in mcp_clients._RESIDENT_CLIENTS.values()))

    again, second = handle.begin_turn(_jwt("user-1"))

    assert again is agent
    assert [s["status"] for s in second] == ["ok", "ok", "ok"]
    assert sorted(c.name for c in agent.tool_registry.added) == ["AWS Knowledge", "AWS Pricing"]
    # compose_slides holds the same list, so composers get them too.
    assert len(env["compose_servers"]) == 3


def test_close_releases_the_presentation_maker_client_and_keeps_residents(env):
    handle = env["handle"]()
    agent, _ = handle.begin_turn(_jwt("user-1"))
    handle.end_turn()
    import mcp_clients

    assert _wait_for(lambda: len(mcp_clients._RESIDENT_CLIENTS) == 2
                     and all(r.connected is not None for r in mcp_clients._RESIDENT_CLIENTS.values()))

    handle.close()

    assert agent.cleaned
    assert env["pm"][0].stopped
    assert not any(r.stopped for r in env["residents"])
    with pytest.raises(RuntimeError):
        handle.begin_turn(_jwt("user-1"))


# --- background compose ------------------------------------------------------------


def _open_task(agent, status="working"):
    agent.state[load("background").STATE_KEY] = [{"task_id": "k1", "tool_use_id": "t1", "tool_name": "compose_slides",
                                                 "status": status}]


def test_an_orchestrator_runs_compose_in_the_background_and_a_style_agent_does_not(env):
    background = load("background")
    from strands.hooks.events import AfterInvocationEvent, BeforeModelCallEvent, BeforeToolCallEvent
    from strands.middleware.stages import InvokeModelStage

    handle = env["handle"]()
    spec, _ = handle.begin_turn(_jwt("user-1"), mode="spec")
    handle.end_turn()
    style = env["handle"](sid="s2")
    styler, _ = style.begin_turn(_jwt("user-1"), mode="style_creator")

    assert spec.kwargs["background_tasks"] is background.CONFIG
    assert spec.kwargs["callback_handler"] == handle.on_agent_callback
    assert [stage for stage, _ in spec.middleware] == [InvokeModelStage.Input], "the manage tool is hidden"
    assert [event for event, _ in spec.added_hooks] == [
        BeforeToolCallEvent, BeforeModelCallEvent, AfterInvocationEvent], "refused by name; deliveries as text"
    assert "background_tasks" not in styler.kwargs and "callback_handler" not in styler.kwargs
    assert styler.middleware == [] and styler.added_hooks == []


def test_only_a_background_tools_progress_reaches_the_session(env):
    handle = env["handle"]()
    events: list = []
    handle.on_background_event = events.append

    handle.on_agent_callback(tool_stream_event={"tool_use": {"name": "compose_slides", "toolUseId": "t1"}, "data": {"n": 1}})
    handle.on_agent_callback(tool_stream_event={"tool_use": {"name": "run_python", "toolUseId": "t2"}, "data": {"n": 2}})
    handle.on_agent_callback(tool_stream_event={"tool_use": {"name": "compose_slides", "toolUseId": "t1"}, "data": "text"})
    handle.on_agent_callback(data="a model text delta")

    assert events == [{"toolStream": {"toolUseId": "t1", "name": "compose_slides", "data": {"n": 1}}}]


def test_the_agent_is_kept_while_its_tasks_are_open_and_rebuilt_once_they_are_delivered(env):
    handle = env["handle"]()
    spec, _ = handle.begin_turn(_jwt("user-1"), mode="spec")
    handle.end_turn()
    _open_task(spec)

    kept, _ = handle.begin_turn(_jwt("user-1"), mode="vibe")
    handle.end_turn()
    _open_task(spec, status="completed")  # settled, not delivered yet
    still, _ = handle.begin_turn(_jwt("user-1"), mode="vibe")
    handle.end_turn()
    cleaned_while_open = spec.cleaned
    spec.state.clear()  # delivered: Strands dropped the snapshot
    vibe, _ = handle.begin_turn(_jwt("user-1"), mode="vibe")

    assert kept is spec and still is spec and not cleaned_while_open
    assert vibe is not spec and spec.cleaned
    assert handle._agent_key[0] == "vibe"


def test_a_delivered_result_reaches_the_session(env):
    handle = env["handle"]()
    ended: list = []
    handle.on_task_end = ended.append
    task = {"task_id": "k1", "tool_use_id": "t1", "tool_name": "compose_slides", "status": "completed",
            "result": {"content": [{"text": "{}"}]}}

    handle.note_delivered(task)

    assert ended == [task]
