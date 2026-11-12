# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A steer reaches the running turn and is stored where it arrived (agent/steer_inbox.py).

A real Strands Agent with a scripted model and a FileSessionManager: the persisted
session is what Memory would hold, and restoring it gives the same conversation.
"""

import asyncio

from strands import Agent, tool
from strands.models import Model
from strands.session.file_session_manager import FileSessionManager

from agent_modules import load


class _Model(Model):
    """Replies per call from a script: ("tool", name) or ("text", words). ``during``
    runs while a reply streams (a steer arriving mid-response)."""

    def __init__(self, script, during=None):
        self.script = list(script)
        self.during = during or {}
        self.seen: list[list[dict]] = []

    def update_config(self, **model_config):
        pass

    def get_config(self):
        return {}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        call = len(self.seen)
        self.seen.append([dict(m, content=list(m["content"])) for m in messages])
        kind, value = self.script[call]
        yield {"messageStart": {"role": "assistant"}}
        if kind == "tool":
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{call}", "name": value}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": "{}"}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
            return
        yield {"contentBlockDelta": {"delta": {"text": value}}}
        if call in self.during:
            self.during[call]()
        await asyncio.sleep(0)
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}


def _agent(tmp_path, model, inbox, stopped=lambda: False, tools=(), delivered=None, prefix=""):
    steer = load("steer_inbox")
    plugin = steer.SteerInbox(inbox, stopped, (lambda items, how: delivered.append((items, how))) if delivered is not None else None,
                              prefix=prefix)
    manager = FileSessionManager(session_id="s1", storage_dir=str(tmp_path))
    return Agent(model=model, tools=list(tools), session_manager=manager, plugins=[plugin], callback_handler=None)


def _restored(tmp_path) -> list[dict]:
    manager = FileSessionManager(session_id="s1", storage_dir=str(tmp_path))
    return Agent(model=_Model([]), session_manager=manager, callback_handler=None).messages


def _shape(messages) -> list[tuple[str, list[str]]]:
    return [(m["role"], [next(iter(block)) if "text" not in block else f"text:{block['text']}" for block in m["content"]])
            for m in messages]


def test_a_steer_during_a_tool_is_folded_into_the_tool_result_message(tmp_path):
    inbox = load("steer_inbox").Inbox()
    delivered: list = []

    @tool
    def build() -> str:
        """Build the deck."""
        inbox.put("m1", "make it blue")  # the user sends while the tool runs
        return "built"

    model = _Model([("tool", "build"), ("text", "Done, in blue.")])
    agent = _agent(tmp_path, model, inbox, tools=[build], delivered=delivered)

    agent("Make a deck.")

    assert _shape(agent.messages) == [
        ("user", ["text:Make a deck."]),
        ("assistant", ["toolUse"]),
        ("user", ["toolResult", "text:make it blue"]),
        ("assistant", ["text:Done, in blue."]),
    ]
    # The model saw the steer on its next call.
    assert _shape(model.seen[1])[-1] == ("user", ["toolResult", "text:make it blue"])
    assert delivered == [([("m1", "make it blue")], "fold")]
    assert not inbox
    assert _shape(_restored(tmp_path)) == _shape(agent.messages)


def test_a_steer_during_the_final_response_resumes_the_invocation(tmp_path):
    inbox = load("steer_inbox").Inbox()
    delivered: list = []
    model = _Model(
        [("text", "Here is the plan."), ("text", "Adding a summary slide.")],
        during={0: lambda: inbox.put("m2", "also add a summary")},
    )
    agent = _agent(tmp_path, model, inbox, delivered=delivered)

    result = agent("Plan the deck.")

    assert _shape(agent.messages) == [
        ("user", ["text:Plan the deck."]),
        ("assistant", ["text:Here is the plan."]),
        ("user", ["text:also add a summary"]),
        ("assistant", ["text:Adding a summary slide."]),
    ]
    assert str(result).strip() == "Adding a summary slide."
    assert delivered == [([("m2", "also add a summary")], "resume")]
    assert _shape(_restored(tmp_path)) == _shape(agent.messages)


def test_a_prefix_goes_before_each_folded_and_resumed_text(tmp_path):
    inbox = load("steer_inbox").Inbox()
    prefix = "From the orchestrator: "

    @tool
    def build() -> str:
        """Build the deck."""
        inbox.put("m1", "make it blue")
        return "built"

    model = _Model(
        [("tool", "build"), ("text", "Blue."), ("text", "Summary added.")],
        during={1: lambda: inbox.put("m2", "add a summary")},
    )
    agent = _agent(tmp_path, model, inbox, tools=[build], prefix=prefix)

    agent("Make a deck.")

    assert _shape(agent.messages) == [
        ("user", ["text:Make a deck."]),
        ("assistant", ["toolUse"]),
        ("user", ["toolResult", "text:From the orchestrator: make it blue"]),
        ("assistant", ["text:Blue."]),
        ("user", ["text:From the orchestrator: add a summary"]),
        ("assistant", ["text:Summary added."]),
    ]


def test_several_steers_keep_their_order(tmp_path):
    inbox = load("steer_inbox").Inbox()

    @tool
    def build() -> str:
        """Build the deck."""
        inbox.put("a", "first")
        inbox.put("b", "second")
        return "built"

    agent = _agent(tmp_path, _Model([("tool", "build"), ("text", "ok")]), inbox, tools=[build])

    agent("Go.")

    assert _shape(agent.messages)[2] == ("user", ["toolResult", "text:first", "text:second"])


def test_nothing_is_delivered_once_the_turn_is_stopped(tmp_path):
    inbox = load("steer_inbox").Inbox()
    stopped = {"now": False}

    @tool
    def build() -> str:
        """Build the deck."""
        stopped["now"] = True
        inbox.put("m3", "late")
        return "built"

    model = _Model([("tool", "build"), ("text", "ok")], during={1: lambda: inbox.put("m4", "later")})
    agent = _agent(tmp_path, model, inbox, stopped=lambda: stopped["now"], tools=[build])

    agent("Go.")

    assert all("text:late" not in blocks and "text:later" not in blocks for _, blocks in _shape(agent.messages))
    assert [text for _, text in inbox.drain()] == ["late", "later"]


def test_a_steer_after_the_stream_ended_stays_in_the_inbox(tmp_path):
    inbox = load("steer_inbox").Inbox()
    delivered: list = []
    agent = _agent(tmp_path, _Model([("text", "ok")]), inbox, delivered=delivered)

    agent("Go.")
    inbox.put("m5", "one more thing")

    assert delivered == []
    assert inbox.drain() == [("m5", "one more thing")]  # the runtime makes it a new turn


def test_the_inbox_is_thread_safe_and_discard_returns_what_it_dropped():
    inbox = load("steer_inbox").Inbox()
    import threading

    threads = [threading.Thread(target=lambda i=i: inbox.put(str(i), "x")) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(inbox) == 50
    assert len(inbox.discard()) == 50
    assert not inbox
