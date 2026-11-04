# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A delivered background result restores the same history from Memory
(agent/background.py deliver_as_text, agent/stop_guard.py GatedMemorySessionManager).

The result reaches the history as a user ``<compose_result>`` text: a message of its own
after the turn's answer or on a wake, or folded into a tool result mid-turn. In the
folded case Strands announces the grown message again, and the gated manager stores it
once. Neither the live nor the restored history names the management tool. A real Agent with background compose runs against an in-memory AgentCore Memory
(agent_memory_fake); a new Agent with a new session manager then restores the session.
"""

import asyncio
import json
import threading
import uuid

import pytest
from strands import Agent, tool

from agent_memory_fake import patch_memory
from agent_modules import load
from test_agent_background import PolicyModel, _until, fake_compose, last_user_text, result_text, tool_results


@pytest.fixture
def memory(monkeypatch):
    resilience = load("resilience")
    monkeypatch.setattr(resilience, "_writes_closed", threading.Event())
    return patch_memory(monkeypatch)


def _manager(cls, session_id):
    from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig

    return cls(
        agentcore_memory_config=AgentCoreMemoryConfig(memory_id="mem-test", session_id=session_id, actor_id="user-1"),
        region_name="us-east-1",
    )


def _gated():
    return load("stop_guard").GatedMemorySessionManager


def _policy(slow_answer: float = 0.0, slow_tool: bool = False):
    background = load("background")

    def policy(messages):
        if "make" in last_user_text(messages):
            return ("tool", "compose_slides", {"deck_id": "d1"})
        if background.delivered(messages[-1]):
            return ("text", "Report seen.")
        results = tool_results(messages[-1])
        if results and "Background task dispatched" in result_text(results[0]):
            if slow_tool:
                return ("tool", "check", {})
            return ("text", "Composers started.", slow_answer) if slow_answer else ("text", "Composers started.")
        if results:
            return ("text", "Checked.")
        return ("text", "ok")
    return policy


@tool
async def check() -> str:
    """Check the deck (slow: the compose finishes meanwhile)."""
    await asyncio.sleep(0.6)
    return "checked"


def _agent(manager, policy, compose_s=0.3, plugins=()):
    background = load("background")
    agent = Agent(model=PolicyModel(policy), tools=[fake_compose(compose_s), check], session_manager=manager,
                  plugins=list(plugins), callback_handler=None, background_tasks=background.CONFIG)
    background.hide_manage_tool(agent)
    background.deliver_as_text(agent)
    return agent


def _restore(cls, session_id) -> list[dict]:
    return _agent(_manager(cls, session_id), _policy()).messages


def _turns(messages) -> list[tuple[str, list]]:
    return [(m["role"], m["content"]) for m in messages]


def _consecutive(messages) -> list[int]:
    return [i for i in range(1, len(messages)) if messages[i]["role"] == messages[i - 1]["role"]]


def _no_manage_tool(messages) -> bool:
    return load("background").MANAGE_TOOL not in json.dumps(messages, default=str)


async def _wake_case(cls, session_id, before_wake=None, plugins=()):
    background = load("background")
    agent = _agent(_manager(cls, session_id), _policy(), plugins=plugins)
    await agent.invoke_async("make a deck")
    await _until(lambda: background.undelivered(agent))
    if before_wake is not None:
        before_wake()
    await agent.invoke_async(None)  # the wake
    return agent


def test_a_wake_delivers_the_result_as_user_text_and_restores_the_live_history(memory):
    background = load("background")
    sid = f"s-{uuid.uuid4().hex}"
    agent = asyncio.run(_wake_case(_gated(), sid))
    live = agent.messages

    delivered = live[-2]
    assert delivered["role"] == "user" and [next(iter(b)) for b in delivered["content"]] == ["text"]
    (task,) = background.delivered(delivered)
    assert task["status"] == "completed" and json.loads(background.result_text(task))["status"] == "completed"
    assert live[-1]["content"] == [{"text": "Report seen."}]
    assert background.tasks(agent) == [], "Strands dropped the delivered task (on_appended ran)"
    restored = _restore(_gated(), sid)
    assert _turns(restored) == _turns(live)
    assert _consecutive(restored) == []
    assert _no_manage_tool(live) and _no_manage_tool(restored) and _no_manage_tool(memory.messages(sid))


def test_a_delivery_at_the_end_of_the_turn_restores_the_live_history(memory):
    background = load("background")
    sid = f"s-{uuid.uuid4().hex}"

    async def run():
        # The answer takes longer than the compose: the result is ready at the turn's end.
        agent = _agent(_manager(_gated(), sid), _policy(slow_answer=0.6))
        await agent.invoke_async("make a deck")
        return agent

    agent = asyncio.run(run())
    live = agent.messages

    assert background.tasks(agent) == [], "delivered within the invocation"
    assert [m["role"] for m in live[-3:]] == ["assistant", "user", "assistant"]
    assert background.delivered(live[-2])
    assert live[-1]["content"] == [{"text": "Report seen."}]
    restored = _restore(_gated(), sid)
    assert _turns(restored) == _turns(live)
    assert _consecutive(restored) == []
    assert _no_manage_tool(restored)


def _mid_turn_case(cls, session_id):
    background = load("background")

    async def run():
        # A slow foreground tool: the compose settles meanwhile and its result is folded
        # into that tool's result message before the next model call.
        agent = _agent(_manager(cls, session_id), _policy(slow_tool=True))
        await agent.invoke_async("make a deck")
        return agent

    agent = asyncio.run(run())
    assert background.tasks(agent) == []
    return agent.messages


def test_a_delivery_folded_into_a_tool_result_is_stored_once(memory):
    background = load("background")
    sid = f"s-{uuid.uuid4().hex}"
    live = _mid_turn_case(_gated(), sid)

    folded = live[-2]
    assert folded["role"] == "user" and [next(iter(b)) for b in folded["content"]] == ["toolResult", "text"]
    assert background.delivered(folded)
    restored = _restore(_gated(), sid)
    assert _turns(restored) == _turns(live)
    assert _consecutive(restored) == []
    assert any(op == "delete" for op, _ in memory.ops), "the grown message replaced its first event"
    assert _no_manage_tool(restored)


def test_a_steer_folded_into_the_delivered_result_restores_the_live_history(memory):
    background = load("background")
    steer = load("steer_inbox")
    inbox = steer.Inbox()
    sid = f"s-{uuid.uuid4().hex}"

    live = asyncio.run(_wake_case(
        _gated(), sid, before_wake=lambda: inbox.put("m1", "STEER: use blue"),
        plugins=[steer.SteerInbox(inbox, lambda: False)],
    )).messages

    delivered = live[-2]
    assert delivered["role"] == "user" and delivered["content"][-1] == {"text": "STEER: use blue"}
    assert background.delivered(delivered)
    restored = _restore(_gated(), sid)
    assert _turns(restored) == _turns(live)
    assert _consecutive(restored) == []


def test_without_the_fix_the_grown_message_is_stored_twice(memory):
    # Documents the upstream behaviour the fix covers.
    from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

    sid = f"s-{uuid.uuid4().hex}"
    live = _mid_turn_case(AgentCoreMemorySessionManager, sid)

    restored = _restore(AgentCoreMemorySessionManager, sid)

    assert _consecutive(live) == []
    assert _consecutive(restored) != []
    assert _turns(restored) != _turns(live)


def test_with_writes_closed_the_replacement_writes_nothing(memory):
    resilience = load("resilience")
    sid = f"s-{uuid.uuid4().hex}"
    seen: dict = {}

    def close():
        resilience.close_writes()
        seen["ops"] = list(memory.ops)

    agent = asyncio.run(_wake_case(_gated(), sid, before_wake=close))

    assert agent.messages[-1]["content"] == [{"text": "Report seen."}]
    assert memory.ops == seen["ops"], "no event created or deleted after the gate closed"
