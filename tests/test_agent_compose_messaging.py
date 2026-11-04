# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Messages between the orchestrator and the running composers (agent/compose_messaging.py).

message_composer reaches a real composer Agent (scripted model, FakeMCP slow tool) at its
next tool result; a composer's report_to_orchestrator reaches the orchestrator through the
session runtime: a ``why: "report"`` turn when it is idle, folded into the running turn
otherwise, and never a ``steer`` event.
"""

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from strands import Agent

import test_agent_session_runtime as runtime_tests
from agent_modules import load
from agent_stop_fakes import FakeMCP, Recorder
from test_agent_background import PolicyModel, _until, result_text, tool_results
from test_agent_session_runtime import _FakeAgent, _idle, _jwt, _kinds, _wait_for, real, rt  # noqa: F401 - fixtures

PREFIX = "Message from the orchestrator while you work: "


def _user_texts(messages) -> list[str]:
    return [b["text"] for m in messages if m["role"] == "user" for b in m["content"] if "text" in b]


# --- ComposeMessaging ----------------------------------------------------------------


def test_send_reaches_the_groups_inbox_and_an_unknown_group_gets_the_running_ones():
    messaging = load("compose_messaging").ComposeMessaging("s1")
    inbox = messaging.register("t1", 1, ["a", "b"])
    messaging.register("t1", 2, ["c"])

    assert messaging.send(1, "make it blue") is None
    assert [text for _, text in inbox.drain()] == ["make it blue"]
    assert messaging.send(3, "x") == "No composer of group 3 is running. Running groups: 1 (a, b); 2 (c)."

    messaging.unregister("t1", 1)
    messaging.unregister("t1", 2)
    assert messaging.send(1, "x").startswith("No composer is running now")


def test_nothing_is_sent_to_a_stopped_composer():
    messaging = load("compose_messaging").ComposeMessaging("s1")
    stop = threading.Event()
    inbox = messaging.register("t1", 1, ["a"], stopped=stop.is_set)
    stop.set()

    assert messaging.send(1, "late").startswith("No composer is running now")
    assert not inbox


def test_unregister_leaves_a_later_calls_group_of_the_same_number():
    messaging = load("compose_messaging").ComposeMessaging("s1")
    messaging.register("t1", 1, ["a"])
    later = messaging.register("t2", 1, ["b"])

    messaging.unregister("t1", 1)

    assert messaging.send(1, "x") is None and len(later) == 1


def test_a_report_without_a_session_is_not_sent():
    compose_messaging = load("compose_messaging")
    messaging = compose_messaging.ComposeMessaging("s1")
    report = compose_messaging.make_report_tool(messaging, "t1", 1, ["a"])

    assert report(text="done") == "Not sent: the orchestrator's work was stopped."
    notes: list = []
    messaging.on_report = lambda *args: notes.append(args) or True
    assert report(text="done") == "Sent to the orchestrator."
    assert notes == [("t1", 1, ["a"], "done")]


# --- message_composer -> a real composer --------------------------------------------


def _composer_until_told(messages):
    """Writes slides until a message from the orchestrator arrives, then answers."""
    if any(text.startswith(PREFIX) for text in _user_texts(messages)):
        return ("text", "Applied.")
    writes = sum(1 for m in messages for b in m["content"] if "toolResult" in b)
    return ("tool", "write_slide", {"slug": f"s{writes}"})  # distinct input: no LoopGuard repeat


def _dispatching_orchestrator(messages):
    last = messages[-1]
    if last["role"] == "user" and any("Make" in b.get("text", "") for b in last["content"]):
        return ("tool", "compose_slides", {"deck_id": "deck1", "slide_groups": [
            {"slugs": ["a"], "instruction": "Compose."}]})
    return ("text", "ok")


@pytest.fixture
def composing(monkeypatch, tmp_path):
    resilience = load("resilience")
    monkeypatch.setattr(resilience, "_writes_closed", threading.Event())
    monkeypatch.setenv("COMPOSER_MAX_TOOL_CALLS", "30")
    import composition

    composition.clear_process_cache()
    recorder = Recorder(tmp_path / "calls.jsonl")
    try:
        yield recorder, resilience.TURN_STOP_KEY
    finally:
        composition.clear_process_cache()


def test_message_composer_reaches_the_running_composer_at_its_next_tool_result(composing):
    recorder, stop_key = composing
    background = load("background")
    compose_messaging = load("compose_messaging")
    messaging = compose_messaging.ComposeMessaging("s1")
    message_composer = compose_messaging.make_message_composer(messaging)
    composer_model = PolicyModel(_composer_until_told)
    compose_slides = load("modes.composer").make_compose_slides(
        [FakeMCP(recorder, "parent")], composer_model,
        composer_mcp_factory=lambda _sid: FakeMCP(recorder, "composer", tool_seconds=0.3),
        messaging=messaging,
    )
    agent = Agent(model=PolicyModel(_dispatching_orchestrator), tools=[compose_slides, message_composer],
                  callback_handler=None, background_tasks=background.CONFIG)
    background.hide_manage_tool(agent)
    background.deliver_as_text(agent)
    stop = threading.Event()

    async def run():
        await agent.invoke_async("Make the deck.", invocation_state={stop_key: stop})
        await _until(lambda: any(r["kind"] == "tool" and r["who"] == "composer" for r in recorder.read()),
                     timeout=10)
        running = messaging.running()
        wrong = message_composer(group=2, text="x")
        sent = message_composer(group=1, text="make it blue")
        await _until(lambda: background.undelivered(agent), timeout=10)
        return running, wrong, sent

    running, wrong, sent = asyncio.run(run())

    assert running == {1: ["a"]}
    assert wrong == {"status": "error", "content": [{"text": "No composer of group 2 is running. Running groups: 1 (a)."}]}
    assert sent.startswith("Sent to composer 1")
    seen = [call["messages"][-1] for call in composer_model.calls]
    (told,) = [m for m in seen if {"text": PREFIX + "make it blue"} in m["content"]]
    assert told["role"] == "user" and "toolResult" in told["content"][0], "folded into the next tool result"
    (task,) = background.undelivered(agent)
    report = json.loads(background.result_text(task))
    assert report["status"] == "completed" and report["summaries"]["a"].strip() == "Applied."
    assert messaging.running() == {}, "the group unregistered when it ended"


def test_close_takes_what_came_after_the_last_step_and_refuses_more():
    messaging = load("compose_messaging").ComposeMessaging("s1")
    messaging.register("t1", 1, ["a"])
    assert messaging.send(1, "late") is None

    assert messaging.close("t1", 1) == [("to-1", "late")]
    assert messaging.send(1, "later").startswith("No composer is running now")
    assert messaging.close("t1", 1) == []


def test_a_message_sent_after_the_composers_last_step_still_reaches_it(composing, monkeypatch):
    recorder, stop_key = composing
    background = load("background")
    compose_messaging = load("compose_messaging")
    steer_inbox = load("steer_inbox")
    messaging = compose_messaging.ComposeMessaging("s1")
    sent: list = []
    original = steer_inbox.SteerInbox._after_invocation

    def after_invocation(self, event):
        original(self, event)
        if self.prefix and not sent:  # the composer's last check is done: a message comes now
            sent.append(messaging.send(1, "make it blue"))

    monkeypatch.setattr(steer_inbox.SteerInbox, "_after_invocation", after_invocation)

    def composer_policy(messages):
        if any(text.startswith(PREFIX) for text in _user_texts(messages)):
            return ("text", "Applied.")
        return ("text", "Done.")

    composer_model = PolicyModel(composer_policy)
    compose_slides = load("modes.composer").make_compose_slides(
        [FakeMCP(recorder, "parent")], composer_model,
        composer_mcp_factory=lambda _sid: FakeMCP(recorder, "composer"), messaging=messaging,
    )
    agent = Agent(model=PolicyModel(_dispatching_orchestrator), tools=[compose_slides],
                  callback_handler=None, background_tasks=background.CONFIG)
    background.hide_manage_tool(agent)
    background.deliver_as_text(agent)

    async def run():
        await agent.invoke_async("Make the deck.", invocation_state={stop_key: threading.Event()})
        await _until(lambda: background.undelivered(agent), timeout=10)

    asyncio.run(run())

    assert sent == [None], "accepted: the composer had not been closed yet"
    assert composer_model.calls[-1]["messages"][-1] == {"role": "user", "content": [{"text": PREFIX + "make it blue"}]}
    (task,) = background.undelivered(agent)
    assert json.loads(background.result_text(task))["summaries"]["a"].strip() == "Applied."


def test_a_composer_has_the_report_tool():
    compose_messaging = load("compose_messaging")
    report = compose_messaging.make_report_tool(compose_messaging.ComposeMessaging(), "t1", 1, ["a"])

    assert report.tool_name == "report_to_orchestrator"
    assert "no answer" in report.tool_spec["description"]


# --- report_to_orchestrator -> the session --------------------------------------------


def _reporting_composer(messages):
    """Group a writes once, reports, then answers; group b writes once and answers."""
    group_a = any("assigned_slugs: a" in text for text in _user_texts(messages))
    results = tool_results(messages[-1])
    last = result_text(results[0]) if results else ""
    if "Sent to the orchestrator" in last:
        return ("text", "Done.")
    if "wrote" in last:
        return ("tool", "report_to_orchestrator", {"text": "Slide a is half done."}) if group_a else ("text", "Done.")
    return ("tool", "write_slide", {"slug": "x"})


def test_a_report_while_the_orchestrator_is_idle_starts_a_report_turn(rt, real, monkeypatch):  # noqa: F811
    monkeypatch.setattr(runtime_tests, "_finishing_composer", _reporting_composer)
    session = rt.session()
    tail = rt.tail(session)

    session.submit("Make the deck.", "ws", _jwt())
    evs = tail.until(_idle, timeout=15)

    note = '<composer_note group="1" slugs="a">Slide a is half done.</composer_note>'
    turns = _kinds(evs, "turn")
    assert turns[0]["why"] == "prompt"
    assert [t["text"] for t in turns if t["why"] == "report"] == [note]
    (start,) = _kinds(evs, "taskStart")
    assert _kinds(evs, "composerNote") == [
        {"toolUseId": start["toolUseId"], "group": 1, "slugs": "a", "text": "Slide a is half done."}]
    assert _kinds(evs, "steer") == [], "a note is not a steer"
    assert any(call["messages"][-1]["content"] == [{"text": note}] for call in real.orchestrator.calls), \
        "the orchestrator's model read the note as the turn's input"
    assert "Report seen: completed" in json.dumps(evs)
    assert evs[-1]["work"] == {"state": "idle", "how": "finished"}


def test_a_report_during_a_turn_is_folded_into_the_next_tool_result(rt, monkeypatch, tmp_path):  # noqa: F811
    from strands import tool
    from strands.session.file_session_manager import FileSessionManager

    from test_agent_steer_inbox import _Model, _shape

    monkeypatch.setattr(rt.runtime, "stream_agent", load("streaming").stream_agent)
    session = rt.session()
    taken: list = []

    @tool
    def build() -> str:
        """Build the deck."""
        taken.append(session.report("t9", 2, ["c", "d"], "Applied blue."))  # a composer reports meanwhile
        return "built"

    agents: list = []

    def begin_turn(handle, token, fence, mode="spec", chat_model_id=None, create_model_id=None, stop=None):
        handle.update_token(token)
        handle.stop = stop
        if not agents:
            agents.append(Agent(
                model=_Model([("tool", "build"), ("text", "Done.")]), tools=[build],
                session_manager=FileSessionManager(session_id="s1", storage_dir=str(tmp_path)),
                plugins=[handle.steer_plugin()], callback_handler=None,
            ))
        return agents[0], []

    monkeypatch.setattr(load("session_handle").SessionHandle, "begin_turn", begin_turn)
    tail = rt.tail(session)
    session.submit("Make a deck.", "ws", _jwt())
    evs = tail.until(_idle)

    note = '<composer_note group="2" slugs="c, d">Applied blue.</composer_note>'
    assert taken == [True]
    assert ("user", ["toolResult", f"text:{note}"]) in _shape(agents[0].messages)
    assert [t["why"] for t in _kinds(evs, "turn")] == ["prompt"], "no extra turn"
    assert _kinds(evs, "composerNote") == [{"toolUseId": "t9", "group": 2, "slugs": "c, d", "text": "Applied blue."}]
    assert _kinds(evs, "steer") == []


def test_a_report_is_published_and_delivered_as_the_web_ui_reads_it(rt):  # noqa: F811
    # The shared fixture: the Web UI tests feed the same event and delivered text.
    fixture = json.loads((Path(__file__).resolve().parent.parent / "web-ui" / "src" / "test" / "fixtures"
                          / "composerNote.json").read_text())
    session = rt.session()
    tail = rt.tail(session)
    session.submit("hello", "ws", _jwt())
    tail.until(lambda ev: "event" in ev)

    assert session.report(fixture["report"]["toolUseId"], fixture["report"]["group"], fixture["report"]["slugs"],
                          fixture["report"]["text"]) is True
    assert session.report("t2", 2, ['a"b'], "ok") is True
    (first, second) = [text for _, text in session.inbox.drain()]
    evs = tail.until(lambda ev: "composerNote" in ev)
    rt.turns.release("hello")

    assert first == fixture["delivered"], "the composer's text cannot close the note"
    assert second == '<composer_note group="2" slugs="a&quot;b">ok</composer_note>'
    assert [ev for ev in evs if "composerNote" in ev][0] == fixture["event"]


def test_nothing_is_put_after_a_stop(rt):  # noqa: F811
    session = rt.session()
    tail = rt.tail(session)
    task = {"task_id": "k1", "tool_use_id": "t1", "tool_name": "compose_slides", "status": "working"}
    session.handle._agent = _FakeAgent([task])
    report = load("compose_messaging").make_report_tool(session.handle.compose_messaging, "t1", 1, ["a"])

    session.submit("hello", "ws", _jwt())
    rt.turns.release("hello")
    tail.until(lambda ev: "turnEnd" in ev)
    assert session.cancel() == "cancelling"
    late = report(text="late")
    task["status"] = "cancelled"  # the task settles; the stopped period ends
    evs = tail.until(_idle)
    time.sleep(0.3)

    assert late == "Not sent: the orchestrator's work was stopped."
    assert not session.inbox
    assert _kinds(evs, "composerNote") == []
    assert [t["why"] for t in _kinds(evs, "turn")] == ["prompt"]
    assert session.report("t1", 1, ["a"], "after") is False, "no work period: nobody takes it"
    assert _wait_for(lambda: not session.working)
