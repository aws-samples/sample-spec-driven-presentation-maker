# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The agent entry admits an invocation only for the owner of its session.

Drives basic_agent.agent_stream in process with the agent build and the stream faked,
and AgentCore Memory replaced by a recording fake.
"""

import asyncio
import base64
import json

import pytest

from shared.session_owner import ProcessOwner
from test_agent_tool_exposure import _basic_agent, patch_turn

P1 = "c6c289e49e9c05b2"  # owner_prefix("user-1")  # pragma: allowlist secret
P2 = "d92b69cfb82cecab"  # owner_prefix("user-2")  # pragma: allowlist secret
OWN = f"{P1}-00000000-0000-4000-8000-000000000000"
OTHER = f"{P2}-00000000-0000-4000-8000-000000000000"
LEGACY = "0f8c6a4e-2b1d-4c3e-9a7f-5d6e7f8a9b0c"


class _Context:
    def __init__(self, sub: str, session_id: str | None = None):
        claims = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
        self.request_headers = {"authorization": f"Bearer h.{claims}.s"}
        self.session_id = session_id


class _Memory:
    def __init__(self, events=(), error: Exception | None = None):
        self.events = list(events)
        self.error = error
        self.calls: list[dict] = []

    def list_events(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"events": self.events}


@pytest.fixture()
def agent(monkeypatch):
    basic_agent = _basic_agent()
    guard = basic_agent.session_guard
    monkeypatch.setattr(guard, "_process_owner", ProcessOwner())
    monkeypatch.setattr(guard, "_owned_legacy", set())
    monkeypatch.setenv("MEMORY_ID", "memory-test")
    built: list[dict] = []

    async def fake_stream(agent, user_query, session_id, cancel, stop, **kwargs):
        yield {"done": True}

    patch_turn(monkeypatch, basic_agent, fake_stream, built)
    basic_agent.built = built
    yield basic_agent
    del basic_agent.built


def _memory(monkeypatch, agent, **kwargs) -> _Memory:
    memory = _Memory(**kwargs)
    monkeypatch.setattr(agent.session_guard, "_memory_client", lambda: memory)
    return memory


def _run(agent, session_id: str, sub: str = "user-1", header: str | None = None) -> list[dict]:
    async def collect():
        payload = {"prompt": "hello", "runtimeSessionId": session_id}
        return [e async for e in agent.agent_stream(payload, _Context(sub, header))]

    return asyncio.run(collect())


def _code(events):
    assert len(events) == 1 and events[0]["status"] == "error", events
    return events[0]["code"]


def test_own_prefixed_id_reaches_the_agent(agent, monkeypatch):
    memory = _memory(monkeypatch, agent)

    events = _run(agent, OWN, header=OWN)

    assert events[-1] == {"done": True}
    assert agent.built[0]["session_id"] == OWN
    assert memory.calls == []


def test_other_users_prefixed_id_is_refused_before_the_session_registry(agent):
    events = _run(agent, OTHER, header=OTHER)

    assert events == [{"status": "error", "code": "auth", "error": "Session not available"}]
    assert agent.built == []
    assert agent.session_runtime.registry._sessions == {}


def test_header_and_payload_mismatch_is_bad_input(agent):
    assert _code(_run(agent, OWN, header=f"{P1}-ffffffff-0000-4000-8000-000000000000")) == "bad_input"
    assert agent.built == []


def test_header_id_is_checked_and_used(agent):
    assert _code(_run(agent, OTHER, header=OTHER)) == "auth"

    _run(agent, OWN, header=OWN)

    assert agent.built[0]["session_id"] == OWN


def test_legacy_id_with_own_events_is_admitted_and_cached(agent, monkeypatch):
    memory = _memory(monkeypatch, agent, events=[{"eventId": "e1"}])

    assert _run(agent, LEGACY)[-1] == {"done": True}
    assert _run(agent, LEGACY)[-1] == {"done": True}

    assert memory.calls == [{
        "memoryId": "memory-test", "actorId": "user-1", "sessionId": LEGACY,
        "maxResults": 1, "includePayloads": False,
    }]
    assert [b["session_id"] for b in agent.built] == [LEGACY, LEGACY]


def test_legacy_id_without_own_events_asks_for_a_reload(agent, monkeypatch):
    memory = _memory(monkeypatch, agent)

    events = _run(agent, LEGACY)

    assert events == [{"status": "error", "code": "session_reload_required", "error": "Reload the page"}]
    assert agent.built == []
    # A negative answer is not cached.
    _run(agent, LEGACY)
    assert len(memory.calls) == 2


@pytest.mark.parametrize("memory_id", ["", "PLACEHOLDER"])
def test_legacy_id_without_memory_asks_for_a_reload(agent, monkeypatch, memory_id):
    memory = _memory(monkeypatch, agent, events=[{"eventId": "e1"}])
    monkeypatch.setenv("MEMORY_ID", memory_id)

    assert _code(_run(agent, LEGACY)) == "session_reload_required"
    assert memory.calls == []


def test_memory_error_fails_closed(agent, monkeypatch):
    _memory(monkeypatch, agent, error=RuntimeError("boom"))

    events = _run(agent, LEGACY)

    assert _code(events) == "service_unavailable"
    assert "boom" not in events[0]["error"]
    assert agent.built == []


def test_deck_id_of_an_owner_is_admitted_without_memory(agent, monkeypatch):
    memory = _memory(monkeypatch, agent)
    deck_sid = P1 + "-" + "a1b2c3d4".ljust(36, "0")
    assert len(deck_sid) == 53

    assert _run(agent, deck_sid)[-1] == {"done": True}
    assert memory.calls == []


def test_deck_id_of_an_owner_is_refused_for_another_user(agent):
    deck_sid = P1 + "-" + "a1b2c3d4".ljust(36, "0")

    assert _code(_run(agent, deck_sid, sub="user-2")) == "auth"


def test_process_serves_only_its_first_user(agent):
    assert _run(agent, OWN)[-1] == {"done": True}

    assert _code(_run(agent, OTHER, sub="user-2")) == "auth"
    assert len(agent.built) == 1


def test_refused_call_does_not_bind_the_process(agent):
    assert _code(_run(agent, OTHER)) == "auth"

    assert _run(agent, OTHER, sub="user-2")[-1] == {"done": True}
