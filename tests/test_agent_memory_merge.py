# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A background result merged into the latest message is stored once in Memory
(agent/stop_guard.py GatedMemorySessionManager.append_message).

Strands merges a delivered background result into the last message when their roles
match (after the turn's final answer, or on a wake) and announces the merged message
again. A real Agent with background compose runs against an in-memory AgentCore Memory
(agent_memory_fake); a new Agent with a new session manager then restores the session.
"""

import asyncio
import threading
import uuid

import pytest
from strands import Agent

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


def _policy(slow_answer: float = 0.0):
    def policy(messages):
        if "make" in last_user_text(messages):
            return ("tool", "compose_slides", {"deck_id": "d1"})
        results = tool_results(messages[-1])
        if results and "Background task dispatched" in result_text(results[0]):
            return ("text", "Composers started.", slow_answer) if slow_answer else ("text", "Composers started.")
        if results:
            return ("text", "Report seen.")
        return ("text", "ok")
    return policy


def _agent(manager, policy, compose_s=0.3, plugins=()):
    background = load("background")
    agent = Agent(model=PolicyModel(policy), tools=[fake_compose(compose_s)], session_manager=manager,
                  plugins=list(plugins), callback_handler=None, background_tasks=background.CONFIG)
    background.hide_manage_tool(agent)
    return agent


def _restore(cls, session_id) -> list[dict]:
    return _agent(_manager(cls, session_id), _policy()).messages


def _turns(messages) -> list[tuple[str, list]]:
    return [(m["role"], m["content"]) for m in messages]


def _consecutive(messages, role="assistant") -> list[int]:
    return [i for i in range(1, len(messages)) if messages[i]["role"] == messages[i - 1]["role"] == role]


async def _wake_case(cls, session_id, before_wake=None, plugins=()):
    background = load("background")
    agent = _agent(_manager(cls, session_id), _policy(), plugins=plugins)
    await agent.invoke_async("make a deck")
    await _until(lambda: background.undelivered(agent))
    if before_wake is not None:
        before_wake()
    await agent.invoke_async(None)  # the wake
    return agent


def test_a_wake_restores_the_live_history(memory):
    sid = f"s-{uuid.uuid4().hex}"
    live = asyncio.run(_wake_case(_gated(), sid)).messages

    restored = _restore(_gated(), sid)

    merged = live[3]
    assert merged["role"] == "assistant"
    assert [next(iter(b)) for b in merged["content"]] == ["text", "toolUse"], "Strands merged the delivery"
    assert _turns(restored) == _turns(live)
    assert _consecutive(restored) == []
    assert any(op == "delete" for op, _ in memory.ops), "the merged message replaced its first event"


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
    assert live[-1]["content"] == [{"text": "Report seen."}]
    restored = _restore(_gated(), sid)
    assert _turns(restored) == _turns(live)
    assert _consecutive(restored) == []


def test_a_steer_folded_into_the_delivered_result_restores_the_live_history(memory):
    steer = load("steer_inbox")
    inbox = steer.Inbox()
    sid = f"s-{uuid.uuid4().hex}"

    live = asyncio.run(_wake_case(
        _gated(), sid, before_wake=lambda: inbox.put("m1", "STEER: use blue"),
        plugins=[steer.SteerInbox(inbox, lambda: False)],
    )).messages

    delivered = live[4]
    assert delivered["role"] == "user" and delivered["content"][-1] == {"text": "STEER: use blue"}
    assert "toolResult" in delivered["content"][0]
    restored = _restore(_gated(), sid)
    assert _turns(restored) == _turns(live)
    assert _consecutive(restored) == []


def test_without_the_fix_the_merged_message_is_stored_twice(memory):
    # Documents the upstream behaviour the fix covers.
    from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

    sid = f"s-{uuid.uuid4().hex}"
    live = asyncio.run(_wake_case(AgentCoreMemorySessionManager, sid)).messages

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
