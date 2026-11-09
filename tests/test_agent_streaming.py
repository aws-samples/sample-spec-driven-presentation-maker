# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""stream_agent with background tools (agent/streaming.py): a compose dispatch is a
``taskStart``, the tools' stop event is the caller's, and a turn can start with no input.

A real Strands Agent with background compose and a scripted model.
"""

import asyncio
import json
import threading

import pytest
from strands import Agent, tool
from strands.hooks import BeforeToolCallEvent
from strands.types.tools import ToolContext

from agent_modules import load
from test_agent_background import PolicyModel, _until, compose_policy, fake_compose, lookup, tool_results


def _agent(policy, tools):
    background = load("background")
    agent = Agent(model=PolicyModel(policy), tools=tools, callback_handler=None, background_tasks=background.CONFIG)
    background.hide_manage_tool(agent)
    background.deliver_as_text(agent)
    return agent


async def _collect(agent, prompt, stop=None, tool_stop=None):
    stream_agent = load("streaming").stream_agent
    return [ev async for ev in stream_agent(agent, prompt, "s" * 33, asyncio.Event(), stop or threading.Event(),
                                            tool_stop=tool_stop)]


def test_a_compose_dispatch_is_a_task_start_and_a_foreground_result_stays_a_tool_result():
    async def run():
        agent = _agent(compose_policy, [fake_compose(0.3), lookup])
        return await _collect(agent, "make a deck"), agent

    events, agent = asyncio.run(run())

    starts = [ev["taskStart"] for ev in events if "taskStart" in ev]
    results = [ev["toolResult"] for ev in events if "toolResult" in ev]
    (task,) = load("background").tasks(agent)
    assert starts == [{"toolUseId": task["tool_use_id"], "name": "compose_slides", "taskId": task["task_id"]}]
    assert [r["name"] for r in results] == ["lookup"]
    assert results[0]["status"] == "success" and results[0]["content"] == "found x"
    assert any(ev.get("toolStart", {}).get("name") == "compose_slides" for ev in events)


def test_a_refused_dispatch_stays_a_tool_result():
    async def run():
        agent = _agent(compose_policy, [fake_compose(0.3), lookup])

        def refuse(event: BeforeToolCallEvent):
            if event.tool_use["name"] == "compose_slides":
                event.cancel_tool = "Stopped: the agent is shutting down."

        agent.add_hook(refuse, BeforeToolCallEvent)
        return await _collect(agent, "make a deck")

    events = asyncio.run(run())

    assert not [ev for ev in events if "taskStart" in ev]
    (result,) = [ev["toolResult"] for ev in events if "toolResult" in ev and ev["toolResult"]["name"] == "compose_slides"]
    assert result["status"] == "error"


def test_tools_get_the_tool_stop_while_strands_watches_the_turn_stop():
    resilience = load("resilience")
    turn_stop, tool_stop = threading.Event(), threading.Event()
    seen: dict = {}

    @tool(context=True)
    def probe(tool_context: ToolContext) -> str:
        """Probe the invocation state."""
        seen["stop"] = tool_context.invocation_state[resilience.TURN_STOP_KEY]
        turn_stop.set()  # the turn is stopped while the tool runs
        return "probed"

    def policy(messages):
        return ("text", "after") if tool_results(messages[-1]) else ("tool", "probe", {})

    async def run():
        agent = _agent(policy, [probe])
        return await _collect(agent, "probe it", stop=turn_stop, tool_stop=tool_stop), agent

    events, agent = asyncio.run(run())

    assert seen["stop"] is tool_stop
    assert not tool_stop.is_set()
    assert [ev["toolResult"]["content"] for ev in events if "toolResult" in ev] == ["probed"]
    assert len(agent.model.calls) == 1, "the stopped turn made no further model call"


def test_no_input_continues_the_history_with_the_delivered_result():
    background = load("background")

    async def run():
        agent = _agent(compose_policy, [fake_compose(0.2), lookup])
        await _collect(agent, "make a deck")
        await _until(lambda: background.undelivered(agent))
        return await _collect(agent, None), agent

    events, agent = asyncio.run(run())

    text = "".join(ev["event"]["contentBlockDelta"]["delta"].get("text", "")
                   for ev in events if "contentBlockDelta" in ev.get("event", {}))
    assert text.startswith("Result seen: ")
    assert background.tasks(agent) == []
    last = agent.model.calls[-1]["messages"]
    assert [m["role"] for m in last[-2:]] == ["assistant", "user"]
    assert json.loads(background.result_text(background.delivered(last[-1])[0]))["status"] == "completed"
    assert not [ev for ev in events if "toolResult" in ev], "the synthetic delivery is history, not a stream event"


class _FilteredModel(PolicyModel):
    """Stops its reply with ``stop_reason`` and no content, as a content filter does."""

    def __init__(self, stop_reason):
        super().__init__(lambda m: None)
        self.stop_reason = stop_reason

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        yield {"messageStart": {"role": "assistant"}}
        yield {"messageStop": {"stopReason": self.stop_reason}}


@pytest.mark.parametrize("stop_reason", ["content_filtered", "guardrail_intervened"])
def test_a_filtered_stop_ends_with_a_content_filtered_error(stop_reason):
    agent = Agent(model=_FilteredModel(stop_reason), tools=[], callback_handler=None)
    events = asyncio.run(_collect(agent, "hello"))

    errors = [ev for ev in events if ev.get("status") == "error"]
    assert len(errors) == 1
    assert errors[0]["code"] == "content_filtered"
    assert stop_reason in errors[0]["error"]


def test_an_answered_turn_has_no_error_event():
    agent = Agent(model=PolicyModel(lambda m: ("text", "hi")), tools=[], callback_handler=None)
    events = asyncio.run(_collect(agent, "hello"))

    assert not [ev for ev in events if ev.get("status") == "error"]
