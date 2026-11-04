# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The agent's half of the MCP write fence (agent/turn_fence.py).

Every Presentation Maker client of a turn (the orchestrator's, each composer group's)
carries the turn's generation in its ``_meta``; a stopped turn calls fence_turn for the
decks its tool calls named, and a turn that ends normally fences nothing. The SIGTERM
path end to end is in test_agent_stop_guard.
"""

import threading

# A session id of user-1 (owner prefix of "user-1", see shared/session_owner.py).
OWNED = "c6c289e49e9c05b2-00000000-0000-4000-8000-000000000000"


# Imported lazily: test_mcp_parallel_connect puts agent/ on sys.path when it is imported,
# and agent/tools would then shadow servers/remote's tools package for the test modules
# collected after this one.
def _factory():
    from test_mcp_parallel_connect import _factory as load

    return load()


def _basic_agent():
    from test_agent_tool_exposure import _basic_agent as load

    return load()


def _run(basic_agent, payload):
    from test_agent_tool_exposure import _run as run

    return run(basic_agent, payload)


class _Agent:
    def __init__(self, **kwargs):
        self.messages = []
        self.tool_names = []
        self.system_prompt = ""


class _Event:
    def __init__(self, tool_input):
        self.tool_use = {"name": "run_python", "toolUseId": "t1", "input": tool_input}


class _Client:
    def __init__(self):
        self.calls: list[dict] = []
        self.consumers: list[tuple[str, str]] = []

    def add_consumer(self, consumer_id, **kwargs):
        self.consumers.append(("add", consumer_id))

    def remove_consumer(self, consumer_id, **kwargs):
        self.consumers.append(("remove", consumer_id))

    def call_tool_sync(self, tool_use_id, name, arguments, **kwargs):
        self.calls.append({"name": name, "arguments": arguments, **kwargs})
        return {"status": "success", "content": [{"text": "{}"}]}


def _fence_class():
    return _factory().TurnFence


def test_a_stopped_turn_fences_the_decks_its_calls_named_once():
    fence = _fence_class()(generation=123)
    client = _Client()
    fence.bind(client)
    fence.note_tool_call(_Event({"deck_id": "d2", "code": "x"}))
    fence.note_tool_call(_Event({"deck_id": "d1"}))
    fence.note_tool_call(_Event({"deck_id": "d1"}))
    fence.note_tool_call(_Event({"query": "no deck"}))
    fence.note_tool_call(_Event("not a dict"))

    thread = fence.advance()
    thread.join(5)

    # The call names the decks and carries the turn's own generation (the client's
    # meta is shared by the session's turns).
    assert client.calls == [{"name": "fence_turn", "arguments": {"deck_ids": ["d1", "d2"]}, "meta": {"sdpm/generation": 123}}]
    assert fence.meta == {"sdpm/generation": 123}
    # Held while the call runs, released after it.
    assert client.consumers == [("add", "sdpm-turn-fence"), ("remove", "sdpm-turn-fence")]
    assert fence.advance() is None  # once: SIGTERM and the turn's finally both call it
    assert len(client.calls) == 1


def test_a_turn_that_ends_normally_fences_nothing():
    fence = _fence_class()(generation=5)
    client = _Client()
    fence.bind(client)
    fence.note_tool_call(_Event({"deck_id": "d1"}))

    fence.release()
    for t in threading.enumerate():
        if t.name == "sdpm-turn-fence":
            t.join(5)

    assert client.calls == []
    assert client.consumers == [("add", "sdpm-turn-fence"), ("remove", "sdpm-turn-fence")]
    assert fence.advance() is None


def test_a_stop_before_any_deck_or_client_does_nothing():
    fence = _fence_class()()
    assert fence.advance() is None  # no client bound yet (SIGTERM during create_agent)
    client = _Client()
    fence.bind(client)  # bound after the stop: never held, never called
    assert client.consumers == [] and client.calls == []


def test_generations_grow_from_turn_to_turn():
    first, second = _fence_class()(), _fence_class()()
    assert 0 < first.generation <= second.generation


def _jwt_of(sub: str) -> str:
    import base64
    import json

    body = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"h.{body}.s"


def test_orchestrator_and_composer_clients_carry_the_generation(monkeypatch):
    factory = _factory()
    runtime_calls: list[dict] = []
    captured: dict = {}
    hooks: list = []

    class _Hooks:
        def add_callback(self, event, callback):
            hooks.append(callback)

    class Agent(_Agent):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.hooks = _Hooks()

    client = _Client()

    def runtime(**kwargs):
        runtime_calls.append({**kwargs, "meta": dict(kwargs["meta"]) if kwargs.get("meta") is not None else None})
        return client

    def make_compose_slides(mcp_servers, model, composer_mcp_factory, **kwargs):
        captured["factory"] = composer_mcp_factory
        return object()

    monkeypatch.delenv("MEMORY_ID", raising=False)
    monkeypatch.setattr(factory, "mcp_agentcore_runtime", runtime)
    monkeypatch.setattr(factory, "mcp_aws_knowledge", lambda: object())
    monkeypatch.setattr(factory, "mcp_aws_pricing", lambda: object())
    monkeypatch.setattr(factory, "_prewarm_mcp_clients", lambda clients, names, required, then=None: (clients, []))
    monkeypatch.setattr(factory, "BedrockModel", lambda **kwargs: object())
    monkeypatch.setattr(factory, "make_compose_slides", make_compose_slides)
    monkeypatch.setattr(factory, "Agent", Agent)
    monkeypatch.setattr(factory, "collect_mcp_instructions", lambda servers: "")
    monkeypatch.setattr(factory, "resolve_parts", lambda *a, **k: ("", []))

    fence = factory.TurnFence(generation=42)
    factory.create_agent("spec", user_id="u1", session_id="s1", jwt_token=_jwt_of("u1"), fence=fence)
    (orchestrator,) = runtime_calls
    runtime_calls.clear()
    captured["factory"]("s1-g1")
    (composer,) = runtime_calls

    assert orchestrator["meta"] == {"sdpm/generation": 42}
    assert composer["meta"] == {"sdpm/generation": 42}
    assert composer["session_id"] == "s1-g1"
    # The fence learns the turn's decks from the orchestrator's tool calls (through the
    # session handle's hook, which acts on the current turn's fence) and fences through
    # the orchestrator's client (compose_slides names its deck there).
    (note,) = [h for h in hooks if getattr(h, "__name__", "") == "note_tool_call"]
    note(_Event({"deck_id": "d9"}))
    assert fence.decks == ["d9"]
    assert ("add", "sdpm-turn-fence") in client.consumers

    # Without a fence (callers other than the entrypoint) the clients carry no generation.
    runtime_calls.clear()
    factory.create_agent("spec", user_id="u1", session_id="s1", jwt_token=_jwt_of("u1"))
    assert not runtime_calls[0]["meta"]


def test_mcp_client_sends_the_meta_with_every_call(monkeypatch):
    import sys

    _factory()
    mcp_clients = sys.modules["mcp_clients"]
    seen: dict = {}

    def fake_client(transport_callable, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(mcp_clients, "MCPClient", fake_client)
    monkeypatch.setenv("MCP_RUNTIME_ARN", "arn:aws:bedrock-agentcore:ap-northeast-1:111122223333:runtime/x")
    mcp_clients.mcp_agentcore_runtime(jwt_token="tok", session_id="s", meta={"sdpm/generation": 7})
    assert seen["meta"] == {"sdpm/generation": 7}
    seen.clear()
    mcp_clients.mcp_agentcore_runtime(jwt_token="tok", session_id="s")
    assert "meta" not in seen


class _FenceSpy:
    instances: list = []

    def __init__(self):
        self.meta = {"sdpm/generation": 1}
        self.events: list[str] = []
        _FenceSpy.instances.append(self)

    def advance(self):
        self.events.append("advance")

    def release(self):
        self.events.append("release")


def _entrypoint(monkeypatch, stream):
    basic_agent = _basic_agent()
    _FenceSpy.instances = []
    seen: dict = {}

    def fake_create_agent(**kwargs):
        seen.update(kwargs)
        return object(), []

    monkeypatch.setattr(basic_agent, "TurnFence", _FenceSpy)
    monkeypatch.setattr(basic_agent, "create_agent", fake_create_agent)
    monkeypatch.setattr(basic_agent, "stream_agent", stream)
    _run(basic_agent, {"prompt": "hello", "runtimeSessionId": OWNED})
    (fence,) = _FenceSpy.instances
    assert seen["fence"] is fence
    return fence


def test_a_cancelled_turn_advances_the_fence(monkeypatch):
    async def cancelled(agent, user_query, session_id, cancel, cancel_signal):
        yield {"keepalive": True}
        cancel_signal.set()  # what stream_agent does when the turn is cancelled

    assert _entrypoint(monkeypatch, cancelled).events == ["advance"]


def test_a_finished_turn_releases_the_fence(monkeypatch):
    async def finished(agent, user_query, session_id, cancel, cancel_signal):
        yield {"done": True}

    assert _entrypoint(monkeypatch, finished).events == ["release"]


def test_sigterm_advances_the_running_turns_fence(monkeypatch):
    import sys

    stop_guard = _basic_agent().stop_guard
    resilience = sys.modules["resilience"]
    monkeypatch.setattr(resilience, "_writes_closed", threading.Event())
    monkeypatch.setattr(stop_guard, "_running", {})
    calls = []
    stop = stop_guard.begin_turn(on_stop=lambda: calls.append("advance"))
    try:
        assert stop_guard.stop_all() == 1
    finally:
        stop_guard.end_turn(stop)
    assert stop.is_set() and calls == ["advance"]


def test_shutdown_waits_for_the_stop_call_until_the_watchdog_exit(monkeypatch):
    # The turn can end (and uvicorn finish) before fence_turn reaches the server; the
    # lifespan's shutdown then waits for the call (wait_held), but not past the watchdog.
    import sys
    import time

    stop_guard = _basic_agent().stop_guard
    resilience = sys.modules["resilience"]
    monkeypatch.setattr(resilience, "_writes_closed", threading.Event())
    monkeypatch.setattr(stop_guard, "_running", {})
    monkeypatch.setattr(stop_guard, "_held", set())
    monkeypatch.setattr(stop_guard, "_exit_at", None)
    sent = threading.Event()

    def advance():
        thread = threading.Thread(target=lambda: (time.sleep(0.3), sent.set()), daemon=True)
        thread.start()
        return thread

    stop = stop_guard.begin_turn(on_stop=advance)
    try:
        stop_guard.stop_all()
    finally:
        stop_guard.end_turn(stop)
    stop_guard.wait_held()
    assert sent.is_set()

    stuck = threading.Event()
    hung = threading.Thread(target=stuck.wait, daemon=True)
    hung.start()
    stop_guard.hold(hung)
    stop_guard.hold(None)  # a turn with nothing to fence
    monkeypatch.setattr(stop_guard, "_exit_at", time.monotonic() + 0.2)
    started = time.monotonic()
    stop_guard.wait_held()
    assert time.monotonic() - started < 1.0
    stuck.set()
