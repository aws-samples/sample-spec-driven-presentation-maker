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

    def __init__(self, state, session_id, tool_filters, meta, token):
        self.state = state
        self.session_id = session_id
        self.tool_filters = tool_filters
        self.meta = meta
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
        self.state["calls"].append((self.token.token if self.token else "", name, dict(self.meta)))
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
        self.tool_names = []
        self.system_prompt = ""
        self.tool_registry = _Registry()
        self.cleaned = False

    def cleanup(self):
        self.cleaned = True


class _Event:
    def __init__(self, deck_id):
        self.tool_use = {"name": "run_python", "toolUseId": "t1", "input": {"deck_id": deck_id}}


@pytest.fixture
def env(monkeypatch):
    factory = load("factory")
    session_handle = load("session_handle")
    import composition
    import mcp_clients

    composition.clear_process_cache()
    mcp_clients.close_resident_clients()
    state = {"calls": [], "pm": [], "residents": [], "managers": [], "composer": None, "gate": None}

    def runtime(jwt_token="", session_id="", tool_filters=None, meta=None, token=None):
        client = _PM(state, session_id, tool_filters, meta, token)
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
    state["fence"] = lambda generation: factory.TurnFence(generation=generation)
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
    first, _ = handle.begin_turn(_jwt("user-1"), env["fence"](1))
    handle.end_turn()
    second, status = handle.begin_turn(_jwt("user-1", 1), env["fence"](2))

    assert second is first
    (pm,) = env["pm"]
    assert pm.connects == 1
    assert [c[1] for c in env["calls"]] == ["start_presentation"]
    assert len(env["managers"]) == 1
    assert status[0] == {"name": "Presentation Maker", "status": "ok"}


def test_each_turn_swaps_the_token_and_the_generation(env):
    handle = env["handle"]()
    handle.begin_turn(_jwt("user-1", 0), env["fence"](1))
    (pm,) = env["pm"]
    composer_turn_1 = env["composer"]("s1-g1")
    handle.end_turn()

    handle.begin_turn(_jwt("user-1", 1), env["fence"](2))
    pm.call_tool_sync("t", "run_python", {})

    assert pm.token is handle.holder
    assert env["calls"][-1] == (_jwt("user-1", 1), "run_python", {"sdpm/generation": 2})
    assert pm.meta is handle.meta
    # A composer keeps the generation of the turn that started it.
    assert composer_turn_1.meta == {"sdpm/generation": 1}
    assert composer_turn_1.token is handle.holder
    assert env["composer"]("s1-g1").meta == {"sdpm/generation": 2}


def test_a_dead_presentation_maker_client_is_restarted_at_the_turn_start(env):
    handle = env["handle"]()
    handle.begin_turn(_jwt("user-1"), None)
    handle.end_turn()
    (pm,) = env["pm"]
    pm.dead = True

    handle.begin_turn(_jwt("user-1"), None)

    assert pm.restarts == 1
    assert len(env["pm"]) == 1


def test_spec_to_vibe_rebuilds_the_agent_but_keeps_the_client(env):
    handle = env["handle"]()
    spec, _ = handle.begin_turn(_jwt("user-1"), None, mode="spec")
    handle.end_turn()
    vibe, _ = handle.begin_turn(_jwt("user-1"), None, mode="vibe")

    assert vibe is not spec and spec.cleaned
    assert len(env["pm"]) == 1
    assert len(env["managers"]) == 2, "a new Agent needs its own session manager"
    assert vibe.kwargs["session_manager"] is env["managers"][1][0]


def test_style_creator_gets_its_own_allowlisted_client(env):
    handle = env["handle"]()
    handle.begin_turn(_jwt("user-1"), None, mode="spec")
    handle.end_turn()
    handle.begin_turn(_jwt("user-1"), None, mode="style_creator")

    assert len(env["pm"]) == 2
    assert env["pm"][1].tool_filters == {"allowed": load("modes").MODES["style_creator"].allowed_tools}


def test_a_model_change_rebuilds_the_agent_with_a_new_session_manager(env, monkeypatch):
    factory = env["factory"]
    monkeypatch.setattr(factory, "_ALLOWED_MODEL_IDS", {"m-a", "m-b"})
    handle = env["handle"]()
    first, _ = handle.begin_turn(_jwt("user-1"), None, chat_model_id="m-a")
    handle.end_turn()
    same, _ = handle.begin_turn(_jwt("user-1"), None, chat_model_id="m-a")
    handle.end_turn()
    other, _ = handle.begin_turn(_jwt("user-1"), None, chat_model_id="m-b")

    assert same is first
    assert other is not first and first.cleaned
    assert len(env["managers"]) == 2
    assert env["pm"][0].connects == 1


def test_a_turn_of_another_user_is_refused(env):
    handle = env["handle"]()
    agent, _ = handle.begin_turn(_jwt("user-1"), None)
    handle.end_turn()

    with pytest.raises(PermissionError):
        handle.begin_turn(_jwt("user-2"), None)
    with pytest.raises(PermissionError):
        handle.update_token(_jwt("user-2"))

    assert handle.holder.token == _jwt("user-1")
    again, _ = handle.begin_turn(_jwt("user-1"), None)
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

    agent, _ = handle.begin_turn(_jwt("user-1"), env["fence"](1))

    assert len(env["managers"]) == 1
    assert agent.kwargs["session_manager"] is env["managers"][0][0]
    assert pm.connects == 1
    assert [c[1] for c in env["calls"]] == ["start_presentation"]


def test_a_stopped_turn_leaves_the_handle_reusable(env):
    handle = env["handle"]()
    stop = threading.Event()
    first, _ = handle.begin_turn(_jwt("user-1"), env["fence"](1), stop=stop)
    stop.set()
    assert handle.stopped()
    handle.end_turn()

    second, _ = handle.begin_turn(_jwt("user-1"), env["fence"](2))

    assert second is first and not handle.stopped()
    assert env["pm"][0].connects == 1 and not env["pm"][0].stopped


def test_the_agents_hooks_act_on_the_current_turn(env):
    handle = env["handle"]()
    fence_1, fence_2 = env["fence"](1), env["fence"](2)
    handle.begin_turn(_jwt("user-1"), fence_1)
    handle.note_tool_call(_Event("d1"))
    guard_1 = handle.loop_guard
    handle.end_turn()
    handle.begin_turn(_jwt("user-1"), fence_2)
    handle.note_tool_call(_Event("d2"))

    assert fence_1.decks == ["d1"] and fence_2.decks == ["d2"]
    assert handle.loop_guard is not guard_1
    assert "sdpm-turn-fence" in env["pm"][0].consumers


def test_a_resident_that_connects_later_joins_the_agent(env):
    env["gate"] = threading.Event()  # the resident servers connect only once released
    handle = env["handle"]()
    agent, first = handle.begin_turn(_jwt("user-1"), None)
    assert [s["status"] for s in first] == ["ok", "error", "error"]
    handle.end_turn()
    env["gate"].set()
    import mcp_clients

    assert _wait_for(lambda: all(r.connected is not None for r in mcp_clients._RESIDENT_CLIENTS.values()))

    again, second = handle.begin_turn(_jwt("user-1"), None)

    assert again is agent
    assert [s["status"] for s in second] == ["ok", "ok", "ok"]
    assert sorted(c.name for c in agent.tool_registry.added) == ["AWS Knowledge", "AWS Pricing"]
    # compose_slides holds the same list, so composers get them too.
    assert len(env["compose_servers"]) == 3


def test_close_releases_the_presentation_maker_client_and_keeps_residents(env):
    handle = env["handle"]()
    agent, _ = handle.begin_turn(_jwt("user-1"), None)
    handle.end_turn()
    import mcp_clients

    assert _wait_for(lambda: len(mcp_clients._RESIDENT_CLIENTS) == 2
                     and all(r.connected is not None for r in mcp_clients._RESIDENT_CLIENTS.values()))

    handle.close()

    assert agent.cleaned
    assert env["pm"][0].stopped
    assert not any(r.stopped for r in env["residents"])
    with pytest.raises(RuntimeError):
        handle.begin_turn(_jwt("user-1"), None)


def test_close_keeps_a_client_whose_fence_call_still_runs(env):
    handle = env["handle"]()
    fence = env["fence"](1)
    handle.begin_turn(_jwt("user-1"), fence)

    handle.close()  # SIGTERM: the fence holds the client until fence_turn is sent

    assert not env["pm"][0].stopped
    fence.release()
    assert _wait_for(lambda: env["pm"][0].stopped)
