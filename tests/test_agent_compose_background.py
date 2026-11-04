# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The real compose_slides as a background task of an orchestrator Agent
(agent/modes/composer.py, agent/background.py).

The orchestrator and the composers are real Strands Agents on scripted models; the
Presentation Maker clients are agent_stop_fakes.FakeMCP, which records every composer
write with a timestamp.
"""

import asyncio
import json
import threading
import time

import pytest
from strands import Agent

from agent_modules import load
from agent_stop_fakes import GROUPS, FakeMCP, Recorder, ScriptedModel
from test_agent_background import PolicyModel, _until, result_text, tool_results


def _composer_writes(recorder) -> list[dict]:
    return [r for r in recorder.read() if r["kind"] == "tool" and r["who"] == "composer"]


def _orchestrator_policy(messages):
    last = messages[-1]
    if last["role"] == "user" and any("Make" in b.get("text", "") for b in last["content"]):
        return ("tool", "compose_slides", {"deck_id": "deck1", "slide_groups": GROUPS})
    results = tool_results(last)
    if results and "Background task dispatched" in result_text(results[0]):
        return ("text", "Composers started.")
    return ("text", "Report seen.")


def _finishing_composer(messages):
    """Writes one slide, then answers."""
    results = tool_results(messages[-1])
    if results and "wrote" in result_text(results[0]):
        return ("text", "Done.")
    return ("tool", "write_slide", {"slug": "x"})


@pytest.fixture
def env(monkeypatch, tmp_path):
    resilience = load("resilience")
    monkeypatch.setattr(resilience, "_writes_closed", threading.Event())
    monkeypatch.setenv("COMPOSER_MAX_TOOL_CALLS", "30")  # a composer that misses the stop ends anyway
    import composition

    composition.clear_process_cache()
    recorder = Recorder(tmp_path / "calls.jsonl")

    def build(composer_model):
        background = load("background")
        composer = load("modes.composer")
        parent = [FakeMCP(recorder, "parent")]
        compose_slides = composer.make_compose_slides(
            parent, composer_model,
            composer_mcp_factory=lambda _sid: FakeMCP(recorder, "composer", tool_seconds=0.3),
        )
        orchestrator_model = PolicyModel(_orchestrator_policy)
        agent = Agent(model=orchestrator_model, tools=[compose_slides], callback_handler=None,
                      background_tasks=background.CONFIG)
        background.hide_manage_tool(agent)
        background.deliver_as_text(agent, cancelled_report=composer.make_cancelled_report(parent))
        return agent, orchestrator_model

    try:
        yield recorder, build, resilience.TURN_STOP_KEY, load("background")
    finally:
        composition.clear_process_cache()


def test_the_dispatch_returns_while_composers_run_and_the_report_arrives_on_the_next_invocation(env):
    recorder, build, stop_key, background = env
    stop = threading.Event()

    async def run():
        agent, model = build(PolicyModel(_finishing_composer))
        started = time.monotonic()
        await agent.invoke_async("Make the deck.", invocation_state={stop_key: stop})
        returned = time.monotonic() - started
        running = len(background.pending(agent))
        await _until(lambda: background.undelivered(agent), timeout=10)
        await agent.invoke_async(None, invocation_state={stop_key: stop})
        return agent, model, returned, running

    agent, model, returned, running = asyncio.run(run())

    assert running == 1 and returned < 1.0
    assert not stop.is_set(), "a completed compose leaves the period's stop unset (no GeneratorExit)"
    assert agent.messages[-1]["content"] == [{"text": "Report seen."}]
    (delivered,) = background.delivered(model.calls[-1]["messages"][-1])
    report = json.loads(background.result_text(delivered))
    assert report["status"] == "completed" and sorted(report["generated_slides"]) == ["a", "b"]
    assert any(r["name"] == "generate_pptx" for r in recorder.read() if r["kind"] == "mcp")


def test_cancel_all_sets_the_stop_and_the_composers_stop_without_blocking_the_loop(env):
    recorder, build, stop_key, background = env
    stop = threading.Event()

    async def run():
        agent, _ = build(ScriptedModel(recorder))  # composers write until stopped
        ticks: list[float] = []

        async def ticker():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.05)

        ticking = asyncio.create_task(ticker())
        await agent.invoke_async("Make the deck.", invocation_state={stop_key: stop})
        await _until(lambda: len(_composer_writes(recorder)) >= 2, timeout=10)
        cancelled_at = time.time()
        await background.cancel_all(agent)
        await _until(lambda: not background.pending(agent), timeout=2)
        await asyncio.sleep(1.5)  # the composers' running writes end; nothing new starts
        ticking.cancel()
        gaps = [b - a for a, b in zip(ticks, ticks[1:])]
        return agent, cancelled_at, max(gaps)

    agent, cancelled_at, worst_gap = asyncio.run(run())

    assert stop.is_set(), "compose_slides set the stop on its cancellation"
    assert worst_gap < 0.5
    assert [t["status"] for t in background.undelivered(agent)] == ["cancelled"]
    assert [r for r in _composer_writes(recorder) if r["t"] > cancelled_at + 1.0] == []


def _deck_reads(recorder, after: float) -> list[tuple[str, dict]]:
    return [(r["name"], r["detail"]["arguments"]) for r in recorder.read()
            if r["kind"] == "mcp" and r["who"] == "parent" and r["t"] > after]


def test_a_cancelled_compose_is_delivered_with_the_slides_the_deck_holds(env):
    """cancel_all marks the task cancelled at once and Strands drops what compose returns
    later; the delivery on the next invocation (a new work period: its stop unset) carries a
    report with the deck's slides, read through check_specs and start_composing."""
    recorder, build, stop_key, background = env
    stop = threading.Event()

    async def run():
        agent, model = build(ScriptedModel(recorder))
        await agent.invoke_async("Make the deck.", invocation_state={stop_key: stop})
        await _until(lambda: len(_composer_writes(recorder)) >= 2, timeout=10)
        await background.cancel_all(agent)
        await _until(lambda: background.undelivered(agent), timeout=2)
        cancelled_at = time.time()
        await agent.invoke_async(None, invocation_state={stop_key: threading.Event()})
        return model, cancelled_at

    model, cancelled_at = asyncio.run(run())

    (delivered,) = background.delivered(model.calls[-1]["messages"][-1])
    assert delivered["status"] == "cancelled"
    report = json.loads(background.result_text(delivered))
    assert report["status"] == "cancelled" and report["slides_in_deck"] == ["a"]
    assert "slides_in_deck" in report["notice"]
    assert _deck_reads(recorder, cancelled_at) == [
        ("check_specs", {"deck_id": "deck1"}),
        ("start_composing", {"deck_id": "deck1", "assigned_slugs": []}),
    ]


def test_a_cancelled_compose_is_not_completed_while_the_stop_is_set(env):
    """An invocation whose stop is set makes no deck read: the stop is not delayed (in the
    runtime, Strands abandons that delivery and makes it again in the next period)."""
    recorder, build, stop_key, background = env
    stop = threading.Event()

    async def run():
        agent, model = build(ScriptedModel(recorder))
        await agent.invoke_async("Make the deck.", invocation_state={stop_key: stop})
        await _until(lambda: len(_composer_writes(recorder)) >= 2, timeout=10)
        stop.set()  # the session runtime sets the period's stop before cancel_all
        await background.cancel_all(agent)
        await _until(lambda: background.undelivered(agent), timeout=2)
        cancelled_at = time.time()
        await agent.invoke_async(None, invocation_state={stop_key: stop})
        return model, cancelled_at

    model, cancelled_at = asyncio.run(run())

    (delivered,) = background.delivered(model.calls[-1]["messages"][-1])
    assert delivered["status"] == "cancelled" and background.result_text(delivered) == ""
    assert _deck_reads(recorder, cancelled_at) == []


def test_the_stop_alone_ends_the_task_with_a_cancelled_report(env):
    recorder, build, stop_key, background = env
    stop = threading.Event()

    async def run():
        agent, model = build(ScriptedModel(recorder))
        await agent.invoke_async("Make the deck.", invocation_state={stop_key: stop})
        await _until(lambda: len(_composer_writes(recorder)) >= 2, timeout=10)
        stop.set()
        started = time.monotonic()
        await _until(lambda: background.undelivered(agent), timeout=2)
        took = time.monotonic() - started
        (task,) = background.undelivered(agent)
        await agent.invoke_async(None, invocation_state={stop_key: threading.Event()})
        return task, model, took

    task, model, took = asyncio.run(run())

    assert took < 1.0
    assert task["status"] == "completed"
    assert json.loads(background.result_text(task))["status"] == "cancelled"
    (delivered,) = background.delivered(model.calls[-1]["messages"][-1])
    report = json.loads(background.result_text(delivered))
    assert "generated_slides" in report and report["slides_in_deck"] == ["a"]
