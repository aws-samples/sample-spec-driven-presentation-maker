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
    """Load just `_prewarm_mcp_clients` out of agent/factory.py.

    Importing the whole module pulls the agent's runtime dependency tree
    (html2text, the MCP clients, the modes package), which is not installed for
    the unit test run. The function under test only needs asyncio, a thread pool
    and a logger, so the module source is compiled in a namespace holding exactly
    those. That keeps the test honest — it exercises the real source rather than a
    copy — without requiring the deployment dependencies.
    """
    import ast
    import asyncio
    import logging
    from concurrent.futures import ThreadPoolExecutor

    source = (AGENT_DIR / "factory.py").read_text()
    tree = ast.parse(source)
    func = next(
        (n for n in tree.body
         if isinstance(n, ast.FunctionDef) and n.name == "_prewarm_mcp_clients"),
        None,
    )
    assert func is not None, "_prewarm_mcp_clients is gone from agent/factory.py"

    namespace: dict = {
        "asyncio": asyncio,
        "ThreadPoolExecutor": ThreadPoolExecutor,
        "logger": logging.getLogger("test.factory"),
        "BaseException": BaseException,
    }
    exec(compile(ast.Module(body=[func], type_ignores=[]), "factory.py", "exec"), namespace)

    class _Ns:
        _prewarm_mcp_clients = staticmethod(namespace["_prewarm_mcp_clients"])

    return _Ns


class _FakeClient:
    """Stands in for MCPClient's ToolProvider surface."""

    def __init__(self, delay: float = 0.0, error: BaseException | None = None):
        self.delay = delay
        self.error = error
        self.calls = 0
        self.thread_names: list[str] = []

    async def load_tools(self, **kwargs):
        self.calls += 1
        self.thread_names.append(threading.current_thread().name)
        time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return []


def test_clients_are_connected_concurrently():
    """Wall clock must track the slowest client, not the sum."""
    factory = _factory()
    delays = [0.30, 0.30, 0.30]
    clients = [_FakeClient(delay=d) for d in delays]

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
    clients = [_FakeClient(), _FakeClient(), _FakeClient()]

    factory._prewarm_mcp_clients(clients, ["a", "b", "c"], [True, False, False])

    assert [c.calls for c in clients] == [1, 1, 1]


def test_optional_server_failure_is_dropped_not_raised():
    """This is what the required flag always claimed to do."""
    factory = _factory()
    ok = _FakeClient()
    broken = _FakeClient(error=RuntimeError("us-east-1 unreachable"))

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
    clients = [_FakeClient(delay=0.05), _FakeClient(delay=0.0), _FakeClient(delay=0.02)]

    _usable, status = factory._prewarm_mcp_clients(
        clients, ["first", "second", "third"], [True, False, False]
    )

    assert [s["name"] for s in status] == ["first", "second", "third"]


def test_no_clients_is_not_an_error():
    factory = _factory()
    usable, status = factory._prewarm_mcp_clients([], [], [])
    assert usable == []
    assert status == []
