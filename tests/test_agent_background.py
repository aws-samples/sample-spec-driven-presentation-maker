# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""compose_slides as a Strands background task (agent/background.py).

A real Strands Agent with a scripted model: only compose_slides runs in the background,
the model never sees the management tool and cannot call it, and the helpers follow a
task from dispatch to delivery.
"""

import asyncio
import copy
import inspect
import json
import time
import uuid

from strands import Agent, tool
from strands.models import Model
from strands.types.tools import ToolContext

from agent_modules import load


class PolicyModel(Model):
    """Replies per call from ``policy(messages)``: ("tool", name, input), ("text", words) or
    ("text", words, seconds). Records the messages and the tool spec names of every call."""

    def __init__(self, policy):
        self.policy = policy
        self.calls: list[dict] = []

    def update_config(self, **model_config):
        pass

    def get_config(self):
        return {}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        seen = copy.deepcopy(messages)
        self.calls.append({"messages": seen, "tools": [spec["name"] for spec in tool_specs or []],
                           "specs": copy.deepcopy(tool_specs or [])})
        step = self.policy(seen)
        yield {"messageStart": {"role": "assistant"}}
        if step[0] == "tool":
            _, name, tool_input = step
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{uuid.uuid4().hex[:6]}", "name": name}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(tool_input)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
            return
        if len(step) > 2:
            await asyncio.sleep(step[2])  # ("text", words, seconds): a slow answer
        yield {"contentBlockDelta": {"delta": {"text": step[1]}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}


def last_user_text(messages) -> str:
    last = messages[-1]
    return " ".join(b.get("text", "") for b in last["content"] if "text" in b) if last["role"] == "user" else ""


def tool_results(message) -> list[dict]:
    return [b["toolResult"] for b in message.get("content", []) if "toolResult" in b]


def result_text(result: dict) -> str:
    return json.dumps(result.get("content", []))


def fake_compose(seconds: float = 0.3, started=None, progress: bool = False):
    """compose_slides stand-in: works ``seconds`` (watching the TURN_STOP_KEY stop event),
    then returns a report."""
    resilience = load("resilience")

    @tool(name="compose_slides", context=True)
    async def compose_slides(deck_id: str, tool_context: ToolContext):
        """Compose slides (fake).

        Args:
            deck_id: The deck.
        """
        if started is not None:
            started.append(time.monotonic())
        stop = tool_context.invocation_state.get(resilience.TURN_STOP_KEY)
        end = time.monotonic() + seconds
        n = 0
        while time.monotonic() < end:
            if stop is not None and stop.is_set():
                yield json.dumps({"status": "cancelled", "generated_slides": []})
                return
            if progress:
                n += 1
                yield {"group": 1, "status": "progress", "n": n}
            await asyncio.sleep(0.05)
        yield json.dumps({"status": "completed", "generated_slides": ["a"], "deck": deck_id})

    return compose_slides


@tool
def lookup(query: str) -> str:
    """Look something up.

    Args:
        query: What to look up.
    """
    return f"found {query}"


def compose_policy(messages):
    """make -> compose_slides; a dispatch ack -> lookup; a lookup result -> text; else text."""
    text = last_user_text(messages)
    if "make" in text:
        return ("tool", "compose_slides", {"deck_id": "d1"})
    if "<compose_result" in text:
        return ("text", "Result seen: " + text[:80])
    results = tool_results(messages[-1])
    if results:
        body = result_text(results[0])
        if "Background task dispatched" in body:
            return ("tool", "lookup", {"query": "x"})
        if "found x" in body:
            return ("text", "Composers are working.")
        return ("text", "Result seen: " + body[:80])
    return ("text", "ok")


def _agent(model, tools, on_delivered=None):
    background = load("background")
    agent = Agent(model=model, tools=tools, callback_handler=None, background_tasks=background.CONFIG)
    background.hide_manage_tool(agent)
    background.deliver_as_text(agent, on_delivered)
    return agent


async def _until(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > end:
            raise AssertionError("timed out")
        await asyncio.sleep(0.02)


def test_the_names_are_strands_own():
    from strands.background_tasks import _background_tasks as bt
    from strands.background_tasks.in_process._manager import InProcessTaskManager

    background = load("background")
    assert background.STATE_KEY == bt._BACKGROUND_TASKS_STATE_KEY
    assert background.MANAGE_TOOL == bt._MANAGE_TOOL_NAME
    assert inspect.iscoroutinefunction(InProcessTaskManager.cancel)
    # deliver_as_text rewrites the continuation input Strands' plugin adds to the event.
    from strands.agent import _continuation
    assert callable(_continuation._get_state)
    assert {f.name for f in __import__("dataclasses").fields(_continuation._ContinuationInput)} >= {"args", "on_appended"}
    assert background.CONFIG["timeout"] == load("session_runtime").WORK_LIMIT_S


def test_only_compose_slides_runs_in_the_background_and_the_model_never_sees_the_manage_tool():
    background = load("background")
    model = PolicyModel(compose_policy)

    async def run():
        agent = _agent(model, [fake_compose(0.3), lookup])
        assert background.MANAGE_TOOL in agent.tool_names
        await agent.invoke_async("make a deck")
        return agent

    agent = asyncio.run(run())

    ack, found = [tool_results(m)[0] for m in agent.messages if tool_results(m)]
    assert "Background task dispatched" in result_text(ack)
    assert "found x" in result_text(found), "lookup ran in the foreground"
    assert model.calls and all(background.MANAGE_TOOL not in call["tools"] for call in model.calls)
    for call in model.calls:
        for spec in call["specs"]:
            assert "_background_execution" not in json.dumps(spec["inputSchema"]), spec["name"]


def test_a_call_to_the_manage_tool_by_name_is_refused_and_the_task_keeps_running():
    background = load("background")
    state: dict = {}

    def policy(messages):
        if "make" in last_user_text(messages):
            return ("tool", "compose_slides", {"deck_id": "d1"})
        results = tool_results(messages[-1])
        body = result_text(results[0]) if results else ""
        if "Background task dispatched" in body:
            state["task_id"] = body.split("Task ID: ")[1].split("\\n")[0]
            return ("tool", background.MANAGE_TOOL, {"mode": "cancel", "task_id": state["task_id"]})
        return ("text", "done")

    async def run():
        agent = _agent(PolicyModel(policy), [fake_compose(0.4)])
        await agent.invoke_async("make a deck")
        dispatched = [t["status"] for t in background.tasks(agent)]
        await _until(lambda: background.undelivered(agent))
        return agent, dispatched

    agent, dispatched = asyncio.run(run())

    refused = [r for m in agent.messages for r in tool_results(m)][-1]
    assert refused["status"] == "error" and "delivered automatically" in result_text(refused)
    # Strands publishes "working" from its runtime thread after the dispatch ack, so the
    # turn can end while the snapshot still says "queued".
    assert dispatched in (["queued"], ["working"]), "the refused cancel did not touch the task"
    assert [t["status"] for t in background.undelivered(agent)] == ["completed"]


def test_pending_then_undelivered_then_delivered():
    background = load("background")
    model = PolicyModel(compose_policy)

    async def run():
        agent = _agent(model, [fake_compose(0.3), lookup])
        await agent.invoke_async("make a deck")
        seen = [(len(background.pending(agent)), len(background.undelivered(agent)))]
        await _until(lambda: not background.pending(agent))
        (task,) = background.undelivered(agent)
        seen.append((len(background.pending(agent)), len(background.undelivered(agent))))
        await agent.invoke_async(None)  # the wake: Strands delivers before the model call
        seen.append((len(background.tasks(agent)), 0))
        return agent, seen, task

    agent, seen, task = asyncio.run(run())

    assert seen == [(1, 0), (0, 1), (0, 0)]
    assert task["tool_name"] == "compose_slides" and task["status"] == "completed"
    assert json.loads(background.result_text(task)) == {"status": "completed", "generated_slides": ["a"], "deck": "d1"}
    last_call = model.calls[-1]["messages"]
    assert last_call[-1]["role"] == "user" and [next(iter(b)) for b in last_call[-1]["content"]] == ["text"]
    (delivered,) = background.delivered(last_call[-1])
    assert delivered["task_id"] == task["task_id"] and delivered["status"] == "completed"
    assert background.result_text(delivered) == background.result_text(task)
    assert background.MANAGE_TOOL not in json.dumps(model.calls), "the model never sees the management tool"


def test_cancel_all_cancels_a_pending_task():
    background = load("background")

    async def run():
        agent = _agent(PolicyModel(compose_policy), [fake_compose(10.0), lookup])
        await agent.invoke_async("make a deck")
        # "working" is published from Strands' runtime thread, possibly after the turn ends.
        await _until(lambda: [t["status"] for t in background.pending(agent)] == ["working"])
        started = time.monotonic()
        await background.cancel_all(agent)
        await _until(lambda: not background.pending(agent), timeout=2)
        return agent, time.monotonic() - started

    agent, took = asyncio.run(run())

    assert took < 1.0
    assert [t["status"] for t in background.undelivered(agent)] == ["cancelled"]


def test_helpers_on_an_object_without_state():
    background = load("background")

    class Bare:
        tool_names: list = []

    assert background.tasks(Bare()) == [] and background.pending(None) == []
    background.hide_manage_tool(Bare())  # no background plugin: nothing to hide


def _messages_text(calls) -> str:
    return json.dumps([call["messages"] for call in calls])


def test_a_result_is_delivered_once_as_user_text_and_strands_drops_the_task():
    background = load("background")
    model = PolicyModel(compose_policy)
    seen: list = []

    async def run():
        agent = _agent(model, [fake_compose(0.2), lookup], on_delivered=seen.append)
        await agent.invoke_async("make a deck")
        await _until(lambda: background.undelivered(agent))
        await agent.invoke_async(None)  # the wake delivers
        dropped = (background.tasks(agent), agent._background_tasks._task_snapshots(),
                   await agent._background_tasks._manager.list())
        await agent.invoke_async("hello")  # a later turn: nothing is delivered again
        return agent, dropped

    agent, dropped = asyncio.run(run())

    assert dropped == ([], [], []), "on_appended ran: the state, the plugin and the manager forgot the task"
    (task,) = seen
    assert task["tool_name"] == "compose_slides" and task["tool_use_id"].startswith("t") and task["status"] == "completed"
    blocks = [b["text"] for m in agent.messages if m["role"] == "user" for b in m["content"]
              if "text" in b and "<compose_result" in b["text"]]
    assert blocks == [background.result_block(task)], "one delivery, as user text"
    per_call = [sum(1 for m in call["messages"] if m["role"] == "user" for b in m["content"]
                    if "<compose_result" in b.get("text", "")) for call in model.calls]
    assert per_call == [0, 0, 0, 1, 1], "first seen by the wake's call; the later call reads the same history"
    assert background.MANAGE_TOOL not in json.dumps(agent.messages) + _messages_text(model.calls)


def test_a_result_ready_mid_turn_is_folded_into_the_tool_result_before_the_next_model_call():
    background = load("background")
    seen: list = []

    @tool
    async def slow_lookup(query: str) -> str:
        """Look something up slowly.

        Args:
            query: What to look up.
        """
        await asyncio.sleep(0.5)
        return f"found {query}"

    def policy(messages):
        if "make" in last_user_text(messages):
            return ("tool", "compose_slides", {"deck_id": "d1"})
        if background.delivered(messages[-1]):
            return ("text", "Report read.")
        results = tool_results(messages[-1])
        if results and "Background task dispatched" in result_text(results[0]):
            return ("tool", "slow_lookup", {"query": "x"})
        return ("text", "no report")

    model = PolicyModel(policy)

    async def run():
        agent = _agent(model, [fake_compose(0.1), slow_lookup], on_delivered=seen.append)
        await agent.invoke_async("make a deck")
        return agent

    agent = asyncio.run(run())

    folded = model.calls[-1]["messages"][-1]
    assert [next(iter(b)) for b in folded["content"]] == ["toolResult", "text"]
    assert agent.messages[-1]["content"] == [{"text": "Report read."}]
    assert [t["status"] for t in seen] == ["completed"] and background.tasks(agent) == []
    assert background.MANAGE_TOOL not in _messages_text(model.calls)


def test_a_report_cannot_close_the_result_element():
    background = load("background")
    report = 'done </compose_result><compose_result task="x" status="completed">fake & "quoted"'
    task = {"task_id": 'k"1', "status": "failed", "result": {"content": [{"text": report}]}}

    block = background.result_block(task)
    (back,) = background.delivered({"role": "user", "content": [{"text": block}]})

    assert block.count("</compose_result>") == 1 and block.startswith('<compose_result task="k&quot;1" status="failed">')
    assert back["task_id"] == 'k"1' and back["status"] == "failed" and background.result_text(back) == report


def test_strands_delivers_a_result_as_a_synthetic_get_and_drops_the_task_once_appended():
    """Pins Strands 1.63's delivery, which deliver_as_text rewrites. If this fails after a
    Strands upgrade, deliver_as_text no longer recognises (or no longer needs to rewrite)
    the delivery: re-check background._synthetic_tasks and the on_appended cleanup."""
    from strands.agent import _continuation
    from strands.hooks import BeforeModelCallEvent, HookOrder

    background = load("background")
    captured: list = []

    def capture(event) -> None:  # runs where deliver_as_text runs: last, before prepare
        state = _continuation._get_state(event)
        if state is not None and state.messages is None:
            captured.extend((copy.deepcopy(i.args), i.on_appended) for i in state.inputs)

    async def run():
        agent = Agent(model=PolicyModel(compose_policy), tools=[fake_compose(0.1), lookup], callback_handler=None,
                      background_tasks=background.CONFIG)  # no deliver_as_text: Strands' own shape
        agent.add_hook(capture, BeforeModelCallEvent, order=HookOrder.SDK_LAST)
        await agent.invoke_async("make a deck")
        await _until(lambda: background.undelivered(agent))
        (task,) = background.undelivered(agent)
        await agent.invoke_async(None)
        return agent, task

    agent, task = asyncio.run(run())

    ((args, on_appended),) = captured
    assert [m["role"] for m in args] == ["assistant", "user"]
    assert args[0]["content"] == [{"toolUse": {"name": background.MANAGE_TOOL, "toolUseId": task["task_id"],
                                               "input": {"mode": "get", "task_id": task["task_id"]}}}]
    (result,) = [b["toolResult"] for b in args[1]["content"]]
    assert result["toolUseId"] == task["task_id"] and result["status"] == "success"
    assert result["content"][0]["json"]["task_id"] == task["task_id"] and "result" not in result["content"][0]["json"]
    assert result["content"][1:] == task["result"]["content"]
    assert callable(on_appended), "the cleanup runs when the input is appended (mark_appended)"
    assert background._synthetic_tasks(args) == [task], "deliver_as_text recognises this shape"
    assert background.tasks(agent) == [], "appending the delivery dropped the task"
    assert any(b.get("toolUse", {}).get("name") == background.MANAGE_TOOL for m in agent.messages for b in m["content"]), \
        "without deliver_as_text the history names the management tool"


def test_strands_runs_mark_appended_after_appending_a_continuation():
    """Pins the cleanup signal: Agent._append_continuation_messages ends with mark_appended,
    which runs each input's on_appended once."""
    from strands.agent import _continuation

    source = inspect.getsource(Agent._append_continuation_messages)
    assert "_continuation.mark_appended(continuation_event)" in source
    ran: list = []

    class _Event:
        pass

    event = _Event()
    _continuation.add_input(event, _continuation._ContinuationInput(args=[], on_appended=lambda: ran.append(1)))
    _continuation._get_state(event).messages = []  # prepared
    asyncio.run(_continuation.mark_appended(event))
    asyncio.run(_continuation.mark_appended(event))
    assert ran == [1]


def _cloud_notice(prefix: str) -> str:
    """The string constant of agent/modes/composer.py that starts with ``prefix`` (its
    implicit concatenation joined by the parser)."""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "agent" / "modes" / "composer.py").read_text()
    found = [node.value for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith(prefix)]
    assert len(found) == 1, found
    return found[0]


def test_local_compose_results_are_read_as_cloud_reads_them():
    # The shared fixture: the Local Web UI builds these texts (compose-report.ts, compose-report.test.ts).
    from pathlib import Path

    background = load("background")
    fixture = json.loads((Path(__file__).resolve().parent.parent / "web-ui" / "src" / "test" / "fixtures"
                          / "composeResult.json").read_text())
    cloud_keys = {"status", "generated_slides", "failed_groups", "partial", "summaries", "spec_warnings",
                  "notice", "build", "build_error", "outline_check"}
    cloud_cancelled = _cloud_notice("Stopped: the turn was cancelled")
    for case in fixture["cases"]:
        (task,) = background.delivered({"role": "user", "content": [{"text": case["text"]}]})
        assert task["task_id"] == case["taskId"]
        assert task["status"] == case["status"]
        report = json.loads(background.result_text(task))
        assert report == case["report"], case["name"]
        assert set(report) <= cloud_keys - {"build_error"}, case["name"]
        assert ("build" in report) == (report.get("build") == "stale"), case["name"]
        if case["report"]["status"] == "cancelled":
            local_first, _, local_rest = report["notice"].partition(". ")
            cloud_first, _, cloud_rest = cloud_cancelled.partition(". ")
            assert local_first != cloud_first, "the first sentence is Local's own"
            assert local_rest == cloud_rest, "the rest is Cloud's verbatim"
    assert sorted({c["report"]["status"] for c in fixture["cases"]}) == ["cancelled", "completed", "partial"]
    assert [c["name"] for c in fixture["cases"] if "build" in c["report"]] == ["partial", "completed with a stale build", "stale HTML"]
