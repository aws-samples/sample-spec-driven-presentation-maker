# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""create_agent keeps Bedrock's first request behind the Presentation Maker path only.

create_agent runs every turn. On dev (2026-11-03) a warm second message spent about
2.5s in it: three MCP connections (AWS Pricing's stdio server the slowest, ~1.4s),
the Memory session manager (~0.4s) and one start_presentation call (~0.4s), mostly in
series. The assembly now
- starts start_presentation as soon as the Presentation Maker client is up,
- builds the Memory session manager next to the MCP connections,
- drops an optional server still connecting when that path is done, and
- keeps the role documents (per process) and the styles/templates environment
  (per user) from start_presentation, so a later turn makes no call for them.
"""

import json
import threading

import pytest


def _factory():
    # Imported lazily, as in test_agent_tool_exposure: test_mcp_parallel_connect puts
    # agent/ on sys.path when it is imported, and agent/tools would then shadow
    # servers/remote's tools package for the test modules collected after this one.
    from test_mcp_parallel_connect import _factory as load

    return load()


class _Hooks:
    def add_callback(self, *args, **kwargs):
        pass


class _Agent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.messages = []
        self.hooks = _Hooks()
        self.tool_names = []
        self.system_prompt = ""


class _Optional:
    """AWS Knowledge / AWS Pricing client; with a gate it connects only once released."""

    server_instructions = ""

    def __init__(self, gate: threading.Event | None = None):
        self.gate = gate
        self.done = threading.Event()
        self.stopped = threading.Event()

    async def load_tools(self, **kwargs):
        if self.gate is not None:
            assert self.gate.wait(5)
        self.done.set()
        return []

    def stop(self, *exc):
        self.stopped.set()


class _PresentationMaker:
    """Presentation Maker client; the server answers for the user its JWT names."""

    server_instructions = ""

    def __init__(self, user: str, calls: list, called: threading.Event):
        self.user = user
        self.calls = calls
        self.called = called

    async def load_tools(self, **kwargs):
        return []

    def call_tool_sync(self, tool_use_id, name, arguments):
        self.calls.append((self.user, name, arguments))
        self.called.set()
        payload = {
            "static": {"workflow": f"# Orchestrator (fetched for {self.user})"},
            "styles": [{"name": f"style-of-{self.user}"}],
            "templates": [],
        }
        return {"status": "success", "content": [{"text": json.dumps(payload)}]}

    def stop(self, *exc):
        pass


@pytest.fixture
def assembly(monkeypatch):
    """create_agent wired to in-memory MCP clients; the JWT doubles as the user."""
    factory = _factory()
    import composition

    composition.clear_process_cache()
    state = {
        "calls": [],
        "called": threading.Event(),
        "release": threading.Event(),
        "gate_optional": False,
        "optional": [],
    }

    def optional():
        client = _Optional(gate=state["release"] if state["gate_optional"] else None)
        state["optional"].append(client)
        return client

    monkeypatch.delenv("MEMORY_ID", raising=False)
    monkeypatch.setattr(
        factory, "mcp_agentcore_runtime",
        lambda jwt_token, session_id="", tool_filters=None: _PresentationMaker(jwt_token, state["calls"], state["called"]),
    )
    monkeypatch.setattr(factory, "mcp_aws_knowledge", optional)
    monkeypatch.setattr(factory, "mcp_aws_pricing", optional)
    monkeypatch.setattr(factory, "BedrockModel", lambda **kwargs: object())
    monkeypatch.setattr(factory, "make_compose_slides", lambda *args, **kwargs: object())
    monkeypatch.setattr(factory, "Agent", _Agent)

    def create(user: str, session: str = "s1"):
        return factory.create_agent("spec", user_id=user, session_id=session, jwt_token=user)

    state["factory"] = factory
    state["create"] = create
    try:
        yield state
    finally:
        state["release"].set()
        composition.clear_process_cache()


def _text(system_prompt) -> str:
    return system_prompt if isinstance(system_prompt, str) else json.dumps(system_prompt, ensure_ascii=False)


def test_start_presentation_and_memory_do_not_wait_for_optional_servers(assembly, monkeypatch):
    factory = assembly["factory"]
    assembly["gate_optional"] = True  # AWS Knowledge / Pricing connect only after create_agent returns
    monkeypatch.setenv("MEMORY_ID", "mem-1")
    memory = object()
    built: dict = {}

    def session_manager(memory_id, session_id, user_id, region):
        # Built on a side thread: it can see start_presentation run on the request thread.
        built["thread"] = threading.current_thread().name
        built["saw_start_presentation"] = assembly["called"].wait(5)
        return memory

    monkeypatch.setattr(factory, "_session_manager", session_manager)
    request_thread = threading.current_thread().name

    agent, status = assembly["create"]("u1")

    assert assembly["calls"] == [("u1", "start_presentation", {})]
    assert built["saw_start_presentation"] is True
    assert built["thread"] != request_thread
    assert agent.kwargs["session_manager"] is memory
    assert "# Orchestrator" in _text(agent.system_prompt)
    assert status == [
        {"name": "Presentation Maker", "status": "ok"},
        {"name": "AWS Knowledge", "status": "error", "error": factory._LATE_ERROR},
        {"name": "AWS Pricing", "status": "error", "error": factory._LATE_ERROR},
    ]
    assert all(not c.done.is_set() for c in assembly["optional"])

    assembly["release"].set()
    assert all(c.stopped.wait(5) for c in assembly["optional"]), "late optional clients are closed"


def test_second_turn_for_the_same_user_makes_no_start_presentation_call(assembly):
    first, _ = assembly["create"]("u1")
    second, _ = assembly["create"]("u1", session="s2")

    assert assembly["calls"] == [("u1", "start_presentation", {})]
    assert _text(second.system_prompt) == _text(first.system_prompt)
    assert "style-of-u1" in _text(second.system_prompt)


def test_environment_is_cached_per_user_and_role_documents_per_process(assembly):
    assembly["create"]("u1")
    other, _ = assembly["create"]("u2")

    assert assembly["calls"] == [("u1", "start_presentation", {}), ("u2", "start_presentation", {})]
    prompt = _text(other.system_prompt)
    assert "style-of-u2" in prompt and "style-of-u1" not in prompt
    # The role document is user-independent: the process keeps the first fetch.
    assert "# Orchestrator (fetched for u1)" in prompt


def test_failed_prefetch_falls_back_to_resolve_parts(assembly, monkeypatch):
    """A failed prefetch caches nothing, so resolve_parts makes the call itself."""
    attempts: list = []
    original = _PresentationMaker.call_tool_sync

    def flaky(self, tool_use_id, name, arguments):
        attempts.append(name)
        if len(attempts) == 1:
            return {"status": "error", "content": [{"text": "boom"}]}
        return original(self, tool_use_id, name, arguments)

    monkeypatch.setattr(_PresentationMaker, "call_tool_sync", flaky)

    agent, _ = assembly["create"]("u1")

    assert attempts == ["start_presentation", "start_presentation"]
    assert "style-of-u1" in _text(agent.system_prompt)


# --- composition's process cache --------------------------------------------


class _Client:
    def __init__(self, payload: dict, status: str = "success"):
        self.payload = payload
        self.status = status
        self.calls: list = []

    def call_tool_sync(self, tool_use_id, name, arguments):
        self.calls.append((name, arguments))
        return {"status": self.status, "content": [{"text": json.dumps(self.payload)}]}


@pytest.fixture
def composition():
    _factory()
    import composition

    composition.clear_process_cache()
    yield composition
    composition.clear_process_cache()


def _parts(composition):
    Part, Source = composition.Part, composition.Source
    return [
        Part(Source.mcp("start_presentation", {}, pick="static.workflow"), target="system"),
        Part(Source.mcp("start_presentation", {}, pick="styles,templates"), target="system"),
    ]


def test_static_picks_are_cached_without_a_user(composition):
    parts = _parts(composition)[:1]
    client = _Client({"static": {"workflow": "W"}})

    for _ in range(2):
        system, _ = composition.resolve_parts(parts, mcp_client=client, enable_cache=False)
        assert system == "W"

    assert len(client.calls) == 1


def test_environment_without_a_user_is_not_cached(composition):
    parts = _parts(composition)
    client = _Client({"static": {"workflow": "W"}, "styles": [], "templates": []})

    composition.resolve_parts(parts, mcp_client=client, enable_cache=False)
    composition.resolve_parts(parts, mcp_client=client, enable_cache=False)

    assert len(client.calls) == 2


def test_args_are_part_of_the_key(composition):
    Part, Source = composition.Part, composition.Source
    pptx = [Part(Source.mcp("start_composing", {}, pick="static.workflow"), target="system")]
    html = [Part(Source.mcp("start_composing", {"mode": "html"}, pick="static.workflow"), target="system")]

    assert composition.resolve_parts(pptx, mcp_client=_Client({"static": {"workflow": "P"}}))[0] == "P"
    assert composition.resolve_parts(html, mcp_client=_Client({"static": {"workflow": "H"}}))[0] == "H"


def test_a_failed_call_is_not_cached(composition):
    parts = _parts(composition)

    with pytest.raises(RuntimeError):
        composition.prefetch_sources(parts, _Client({}, status="error"), user_id="u1")

    client = _Client({"static": {"workflow": "W"}, "styles": [], "templates": []})
    composition.prefetch_sources(parts, client, user_id="u1")
    assert len(client.calls) == 1
    system, _ = composition.resolve_parts(parts, mcp_client=client, enable_cache=False, user_id="u1")
    assert "W" in system
    assert len(client.calls) == 1
