# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP servers must connect concurrently, and MCP_DEFS' required flag must mean something.

Background: Strands connects MCP servers serially. `ToolRegistry.process_tools()`
iterates the tools list and blocks on `await provider.load_tools()` for each
ToolProvider in turn, so three servers — one on AgentCore plus two AWS ones pinned
to us-east-1 — put their handshakes on the critical path one after another. A
profile of `create_agent()` measured roughly 2.6s going to the two AWS servers
alone.

`load_tools()` is the public ToolProvider entry point and caches its result, so
calling it up front means Strands' own call is a cache hit. Doing that in a thread
pool collapses the handshakes into the slowest one.

It also makes the `required` flag in `MCP_DEFS` do what it always claimed. The flag
was only guarding client *construction*, which is lazy and cannot fail; a failure
to reach an optional server surfaced later inside Strands as a hard ValueError
(MCPClient defaults to `continue_on_error=False`).
"""

import sys
import threading
import time
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _factory():
    """Import agent/factory.py with agent's own top-level ``tools`` package.

    The workspace lock installs the agent's dependencies into the test environment,
    so these tests always run. agent/ and servers/remote/ both have a top-level
    ``tools`` package; when another test imported servers/remote's first, it sits in
    sys.modules and ``factory``'s ``from tools.… import`` would hit it. Set it aside
    for the import and put it back afterwards (factory keeps its bound names).
    """
    if "factory" in sys.modules:
        return sys.modules["factory"]
    other = {name: sys.modules.pop(name) for name in list(sys.modules)
             if name == "tools" or name.startswith("tools.")}
    sys.path.insert(0, str(AGENT_DIR))
    try:
        import factory
    finally:
        sys.path.remove(str(AGENT_DIR))
        for name in [n for n in sys.modules if n == "tools" or n.startswith("tools.")]:
            del sys.modules[name]
        sys.modules.update(other)
    return factory


@pytest.fixture(autouse=True)
def _record_events(monkeypatch):
    """Set each fake client's ``recorded`` once its worker has recorded the result."""
    factory = _factory()
    monkeypatch.setattr(factory, "_on_recorded", lambda client: client.recorded.set())


class _FakeClient:
    """Stands in for MCPClient's ToolProvider surface.

    ``after`` holds clients whose results must be recorded before this one's
    connection finishes, so a test can order a required client behind the optional
    ones without racing the optional servers' deadline. ``done`` is set when
    load_tools returns; ``recorded`` once the worker has recorded the result.
    """

    def __init__(self, delay: float = 0.0, error: BaseException | None = None,
                 after: list["_FakeClient"] | None = None, gate: threading.Event | None = None):
        self.delay = delay
        self.error = error
        self.after = after or []
        self.gate = gate
        self.calls = 0
        self.stopped = threading.Event()
        self.done = threading.Event()
        self.recorded = threading.Event()
        self.thread_names: list[str] = []

    async def load_tools(self, **kwargs):
        self.calls += 1
        self.thread_names.append(threading.current_thread().name)
        time.sleep(self.delay)
        for other in self.after:
            assert other.recorded.wait(5)
        if self.gate is not None:
            assert self.gate.wait(5)
        self.done.set()
        if self.error is not None:
            raise self.error
        return []

    def stop(self, *exc):
        self.stopped.set()


def test_clients_are_connected_concurrently():
    """Wall clock must track the slowest client, not the sum."""
    factory = _factory()
    delays = [0.30, 0.30, 0.30]
    optional = [_FakeClient(delay=d) for d in delays[1:]]
    clients = [_FakeClient(delay=delays[0], after=optional), *optional]

    start = time.monotonic()
    usable, status = factory._prewarm_mcp_clients(
        clients, ["a", "b", "c"], [True, False, False]
    )
    elapsed = time.monotonic() - start

    assert len(usable) == 3
    assert all(s["status"] == "ok" for s in status)
    assert elapsed < sum(delays) * 0.7, (
        f"took {elapsed:.2f}s for delays {delays} — the connections are still serial"
    )


def test_each_client_is_loaded_exactly_once():
    """A second load_tools() from Strands must hit the client's cache, not reconnect."""
    factory = _factory()
    optional = [_FakeClient(), _FakeClient()]
    clients = [_FakeClient(after=optional), *optional]

    factory._prewarm_mcp_clients(clients, ["a", "b", "c"], [True, False, False])

    assert [c.calls for c in clients] == [1, 1, 1]


def test_optional_server_failure_is_dropped_not_raised():
    """This is what the required flag always claimed to do."""
    factory = _factory()
    broken = _FakeClient(error=RuntimeError("us-east-1 unreachable"))
    ok = _FakeClient(after=[broken])

    usable, status = factory._prewarm_mcp_clients(
        [ok, broken], ["Presentation Maker", "AWS Knowledge"], [True, False]
    )

    assert usable == [ok], "the failing optional server must not stay in the tools list"
    assert status[0] == {"name": "Presentation Maker", "status": "ok"}
    assert status[1]["name"] == "AWS Knowledge"
    assert status[1]["status"] == "error"
    assert "us-east-1 unreachable" in status[1]["error"]


def test_required_server_failure_is_raised():
    factory = _factory()
    broken = _FakeClient(error=RuntimeError("AgentCore unreachable"))

    with pytest.raises(RuntimeError, match="AgentCore unreachable"):
        factory._prewarm_mcp_clients([broken], ["Presentation Maker"], [True])


def test_status_order_matches_the_input_order():
    """mcp_status is surfaced to the UI, so the order must stay stable."""
    factory = _factory()
    optional = [_FakeClient(delay=0.0), _FakeClient(delay=0.02)]
    clients = [_FakeClient(delay=0.05, after=optional), *optional]

    _usable, status = factory._prewarm_mcp_clients(
        clients, ["first", "second", "third"], [True, False, False]
    )

    assert [s["name"] for s in status] == ["first", "second", "third"]


def test_no_clients_is_not_an_error():
    factory = _factory()
    usable, status = factory._prewarm_mcp_clients([], [], [])
    assert usable == []
    assert status == []


def test_then_runs_once_the_required_server_is_up_while_optional_ones_connect():
    """start_presentation must not wait for AWS Knowledge / AWS Pricing."""
    factory = _factory()
    release = threading.Event()
    required = _FakeClient()
    optional = _FakeClient(gate=release)
    seen: list = []

    def then(required_clients):
        seen.append((list(required_clients), optional.done.is_set()))

    try:
        factory._prewarm_mcp_clients([required, optional], ["pm", "opt"], [True, False], then=then)
    finally:
        release.set()

    assert seen == [([required], False)]


def test_optional_server_still_connecting_at_the_deadline_is_dropped_and_closed():
    """The deadline is the end of *then*; a late optional server is skipped for the turn."""
    factory = _factory()
    release = threading.Event()
    required = _FakeClient()
    early = _FakeClient()
    late = _FakeClient(gate=release)

    def then(_required_clients):
        assert early.recorded.wait(5)

    start = time.monotonic()
    usable, status = factory._prewarm_mcp_clients(
        [required, early, late], ["Presentation Maker", "AWS Knowledge", "AWS Pricing"],
        [True, False, False], then=then,
    )
    elapsed = time.monotonic() - start

    assert usable == [required, early]
    assert status[:2] == [
        {"name": "Presentation Maker", "status": "ok"},
        {"name": "AWS Knowledge", "status": "ok"},
    ]
    assert status[2] == {"name": "AWS Pricing", "status": "error", "error": factory._LATE_ERROR}
    assert elapsed < 2, "the late optional server held up the turn"
    assert not late.stopped.is_set()

    release.set()
    assert late.stopped.wait(5), "the late client must be closed once it connects"
    assert not required.stopped.is_set() and not early.stopped.is_set()


def test_optional_servers_finishing_before_the_deadline_are_kept():
    """*then* extends the deadline: an optional server done by its end is used."""
    factory = _factory()
    required = _FakeClient()
    optional = _FakeClient(delay=0.05)

    def then(_required_clients):
        assert optional.recorded.wait(5)

    usable, status = factory._prewarm_mcp_clients(
        [required, optional], ["pm", "opt"], [True, False], then=then,
    )

    assert usable == [required, optional]
    assert [s["status"] for s in status] == ["ok", "ok"]


def test_required_failure_skips_then():
    factory = _factory()
    called: list = []

    with pytest.raises(RuntimeError, match="AgentCore unreachable"):
        factory._prewarm_mcp_clients(
            [_FakeClient(error=RuntimeError("AgentCore unreachable")), _FakeClient()],
            ["Presentation Maker", "AWS Knowledge"], [True, False], then=called.append,
        )

    assert called == []
