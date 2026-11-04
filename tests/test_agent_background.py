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
    """Replies per call from ``policy(messages)``: ("tool", name, input) or ("text", words).
    Records the messages and the tool spec names of every call."""

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
    results = tool_results(messages[-1])
    if results:
        body = result_text(results[0])
        if "Background task dispatched" in body:
            return ("tool", "lookup", {"query": "x"})
        if "found x" in body:
            return ("text", "Composers are working.")
        return ("text", "Result seen: " + body[:80])
    return ("text", "ok")


def _agent(model, tools):
    background = load("background")
    agent = Agent(model=model, tools=tools, callback_handler=None, background_tasks=background.CONFIG)
    background.hide_manage_tool(agent)
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
        working = [t["status"] for t in background.tasks(agent)]
        await _until(lambda: background.undelivered(agent))
        return agent, working

    agent, working = asyncio.run(run())

    refused = [r for m in agent.messages for r in tool_results(m)][-1]
    assert refused["status"] == "error" and "delivered automatically" in result_text(refused)
    assert working == ["working"]
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
    assert last_call[-2]["content"][-1]["toolUse"]["name"] == background.MANAGE_TOOL
    (delivered,) = background.delivered(last_call[-1])
    assert delivered["task_id"] == task["task_id"] and delivered["tool_use_id"] == task["tool_use_id"]
    assert background.result_text(delivered) == background.result_text(task)


def test_cancel_all_cancels_a_pending_task():
    background = load("background")

    async def run():
        agent = _agent(PolicyModel(compose_policy), [fake_compose(10.0), lookup])
        await agent.invoke_async("make a deck")
        assert [t["status"] for t in background.pending(agent)] == ["working"]
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
