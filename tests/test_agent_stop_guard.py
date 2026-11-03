# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A stopped turn stays stopped: nothing is written after SIGTERM, and composers stop
even after the parent invocation has ended.

Background (measured on AgentCore, .agents reports on StopRuntimeSession): the platform
sends SIGTERM right after StopRuntimeSession, uvicorn then waited for the running
/invocations without limit, and the turn kept writing to S3, MCP and Memory until the
platform killed the microVM 10-60 s later. Separately, a composer ran on for 198 s after
a cancel, because Strands clears the parent agent's cancel_signal when the parent's
invocation ends and a cancelled compose_slides returns without waiting for composers.
"""

import asyncio
import base64
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agent"

from agent_stop_fakes import FakeMCP, Recorder, ScriptedModel  # noqa: E402

# The signal reaches the handler on the server's main thread within milliseconds; a call
# recorded later than this after the test sent it came after the guard closed the gate.
SLACK_S = 0.05
# How long the fake fence_turn takes in the SIGTERM test (below stop_guard.EXIT_AFTER_S).
FENCE_SECONDS = 1.0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for(predicate, timeout: float, what: str) -> None:
    deadline = time.time() + timeout
    while not predicate():
        if time.time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.05)


def _composer_tool_calls(recorder: Recorder) -> list[dict]:
    return [r for r in recorder.read() if r["kind"] == "tool" and r["who"] == "composer"]


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM delivery is POSIX")
def test_sigterm_during_compose_stops_every_write_and_exits(tmp_path):
    port = _free_port()
    recorder = Recorder(tmp_path / "calls.jsonl")
    log_path = tmp_path / "server.log"
    # fence_turn takes longer than the turn takes to shut down (about 0.5-1.1 s on dev),
    # like a cold MCP runtime: the process must still wait for it before it exits.
    env = {**os.environ, "FAKE_FENCE_SECONDS": str(FENCE_SECONDS)}
    with log_path.open("w") as log:
        server = subprocess.Popen(
            [sys.executable, str(ROOT / "tests" / "agent_stop_server.py"), str(port), str(recorder.path)],
            cwd=AGENT_DIR, stdout=log, stderr=subprocess.STDOUT, env=env,
        )
    try:
        def up() -> bool:
            try:
                return httpx.get(f"http://127.0.0.1:{port}/ping", timeout=0.5).status_code == 200
            except httpx.HTTPError:
                return False

        _wait_for(up, 60, "the server to start")

        claims = base64.urlsafe_b64encode(json.dumps({"sub": "user-1"}).encode()).decode().rstrip("=")

        def client() -> None:  # keeps the connection open, like the Web UI's stream
            try:
                with httpx.stream(
                    "POST", f"http://127.0.0.1:{port}/invocations", timeout=30,
                    json={"prompt": "Make the deck.", "runtimeSessionId": "s" * 33},
                    headers={"Authorization": f"Bearer h.{claims}.s"},
                ) as response:
                    for _ in response.iter_lines():
                        pass
            except httpx.HTTPError:
                pass

        threading.Thread(target=client, daemon=True).start()
        # Both composers are working (each has called its write tool at least once).
        _wait_for(lambda: len(_composer_tool_calls(recorder)) >= 4, 30, "the composers to write")

        sent = time.time()
        server.send_signal(signal.SIGTERM)
        server.wait(timeout=4)
        lived = time.time() - sent
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()

    records = recorder.read()
    late = [r for r in records if r["t"] > sent + SLACK_S]
    detail = log_path.read_text(errors="replace")[-4000:]
    assert lived < 4, detail
    assert {r["kind"] for r in records if r["t"] < sent} >= {"memory", "mcp", "model", "tool"}, records
    # The only call after the signal fences the turn's deck (turn_fence.py), with the
    # generation every Presentation Maker client of the turn carries, composers' included.
    fences = [r for r in records if r["name"] == "fence_turn"]
    assert [r for r in late if r["name"] != "fence_turn"] == [], (late, detail)
    assert [(r["kind"], r["who"]) for r in fences] == [("mcp", "parent")], (fences, detail)
    assert fences[0]["t"] >= sent + FENCE_SECONDS
    assert fences[0]["detail"]["arguments"] == {"deck_ids": ["deck1"]}
    generation = fences[0]["detail"]["meta"]["sdpm/generation"]
    clients = [r for r in records if r["kind"] == "client"]
    assert {r["who"] for r in clients} == {"parent", "composer"}
    assert all(r["detail"]["meta"] == {"sdpm/generation": generation} for r in clients), clients
    direct = [r for r in records if r["kind"] == "mcp" and r["name"] != "fence_turn"]
    assert direct and all(r["detail"]["meta"] == {"sdpm/generation": generation} for r in direct), direct


def test_composers_stop_after_the_parent_invocation_ended(tmp_path, monkeypatch):
    # agent/ only for this test: its top-level ``tools`` package would shadow
    # servers/remote's for the modules collected after this one.
    monkeypatch.syspath_prepend(str(AGENT_DIR))
    from strands import Agent

    import streaming
    from modes.composer import make_compose_slides

    # LoopGuard ends a composer that misses the cancel after a few writes, so a regression
    # fails here instead of keeping the test process alive.
    monkeypatch.setenv("COMPOSER_MAX_TOOL_CALLS", "4")
    recorder = Recorder(tmp_path / "calls.jsonl")
    model = ScriptedModel(recorder)
    # Each composer write holds its composer's event loop for longer than the parent takes
    # to end, so a cancel that lives only during the parent's invocation is gone by the
    # time the composer looks again.
    compose_slides = make_compose_slides(
        [FakeMCP(recorder, "parent")], model,
        composer_mcp_factory=lambda _session_id: FakeMCP(recorder, "composer", tool_seconds=1.5, hold_loop=True),
    )
    parent = Agent(model=model, tools=[compose_slides], callback_handler=None)
    stop = threading.Event()

    async def run() -> tuple[list, float, float]:
        async def cancel_when_composers_write() -> float:
            while len(_composer_tool_calls(recorder)) < 2:
                await asyncio.sleep(0.02)
            stop.set()
            return time.time()

        canceller = asyncio.create_task(cancel_when_composers_write())
        events = [e async for e in streaming.stream_agent(parent, "Make the deck.", "s" * 33, asyncio.Event(), stop)]
        return events, await canceller, time.time()

    events, cancelled_at, parent_ended_at = asyncio.run(asyncio.wait_for(run(), 30))

    results = [e["toolResult"] for e in events if "toolResult" in e and e["toolResult"]["name"] == "compose_slides"]
    assert len(results) == 1
    assert json.loads(results[0]["content"])["status"] == "cancelled"
    # compose returned without waiting for the composers' running writes (1.5 s each) ...
    assert parent_ended_at - cancelled_at < 1.0
    # ... and the parent's own cancel signal is already cleared by Strands.
    assert not parent.cancel_signal.is_set()

    # Give the composers time to finish their running write and look at the stop event.
    time.sleep(2.5)
    late = [r for r in recorder.read() if r["who"] == "composer" and r["t"] > cancelled_at + SLACK_S]
    assert late == []


def test_prompt_prefetch_does_not_call_mcp_once_writes_are_closed(monkeypatch):
    # On dev, SIGTERM arrived while compose's check_specs was running; compose then
    # prefetched the composer prompt (resolve_parts -> start_composing) after the signal.
    monkeypatch.syspath_prepend(str(AGENT_DIR))
    import resilience
    from composition import Part, Source, resolve_parts

    calls = []

    class Client:
        def call_tool_sync(self, tool_use_id, name, arguments):
            calls.append(name)
            return {"status": "success", "content": [{"text": "{}"}]}

    closed = threading.Event()
    closed.set()
    monkeypatch.setattr(resilience, "_writes_closed", closed)
    with pytest.raises(resilience.WritesClosed):
        resolve_parts([Part(Source.mcp("start_composing", {}), target="system")], mcp_client=Client())
    assert calls == []


def test_sigterm_closes_the_resident_mcp_clients_without_holding_the_handler(monkeypatch):
    # AWS Knowledge and AWS Pricing (a stdio subprocess) stay connected for the process;
    # SIGTERM closes them on a side thread, so a slow close never delays the exit path.
    monkeypatch.syspath_prepend(str(AGENT_DIR))
    import mcp_clients
    import resilience
    import stop_guard

    monkeypatch.setattr(resilience, "_writes_closed", threading.Event())
    monkeypatch.setattr(stop_guard, "_exiting", threading.Event())
    monkeypatch.setattr(stop_guard, "_exit_at", None)
    monkeypatch.setattr(mcp_clients, "_RESIDENT_CLIENTS", {})
    watchdog = threading.Event()
    monkeypatch.setattr(stop_guard, "_exit_after", lambda delay: watchdog.set())  # no os._exit here

    class Client:
        """AWS Pricing's client: stop() waits for its stdio subprocess."""

        def __init__(self):
            self.stopped = threading.Event()

        def add_consumer(self, consumer_id, **kwargs):
            pass

        async def load_tools(self, **kwargs):
            return []

        def stop(self, *exc):
            time.sleep(1.0)
            self.stopped.set()

    client = Client()
    resident = mcp_clients.resident_client("AWS Pricing", lambda: client)
    assert resident.connect() is client
    uvicorn = []

    handler = stop_guard._on_sigterm(lambda signum, frame: uvicorn.append(signum))
    started = time.monotonic()
    handler(signal.SIGTERM, None)
    took = time.monotonic() - started

    assert took < 0.5
    assert uvicorn == [signal.SIGTERM]
    assert watchdog.wait(1)
    assert client.stopped.wait(3)
    assert resident.connected is None
    assert mcp_clients._RESIDENT_CLIENTS == {}


def test_write_gate_covers_tools_of_the_resident_mcp_clients(monkeypatch):
    # A resident client's tools reach the agent as MCPAgentTool, like any MCP tool, so
    # the BeforeToolCallEvent gate stops them too.
    monkeypatch.syspath_prepend(str(AGENT_DIR))
    from mcp.types import Tool
    from strands import Agent
    from strands.hooks.events import BeforeToolCallEvent
    from strands.models import Model
    from strands.tools.mcp.mcp_agent_tool import MCPAgentTool

    import resilience

    calls = []

    class Knowledge:
        async def call_tool_async(self, **kwargs):
            calls.append(kwargs["name"])
            return {"status": "success", "toolUseId": kwargs["tool_use_id"], "content": [{"text": "doc"}]}

    class OneToolCall(Model):
        def update_config(self, **model_config):
            pass

        def get_config(self):
            return {}

        async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
            raise NotImplementedError
            yield  # pragma: no cover

        async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
            yield {"messageStart": {"role": "assistant"}}
            if any("toolResult" in block for m in messages for block in m["content"]):
                yield {"contentBlockDelta": {"delta": {"text": "done"}}}
                yield {"contentBlockStop": {}}
                yield {"messageStop": {"stopReason": "end_turn"}}
                return
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "t1", "name": "aws___search_documentation"}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": "{}"}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}

    tool = MCPAgentTool(Tool(name="aws___search_documentation", inputSchema={"type": "object", "properties": {}}), Knowledge())
    agent = Agent(model=OneToolCall(), tools=[tool], callback_handler=None)
    agent.hooks.add_callback(BeforeToolCallEvent, resilience.gate_tool_call)
    closed = threading.Event()
    closed.set()
    monkeypatch.setattr(resilience, "_writes_closed", closed)

    agent("Look it up.")

    assert calls == []
    results = [block["toolResult"] for m in agent.messages for block in m["content"] if "toolResult" in block]
    assert results and results[0]["status"] == "error"
    assert "shutting down" in json.dumps(results[0])
