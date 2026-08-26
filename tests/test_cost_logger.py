# SPDX-License-Identifier: MIT-0
"""Tests for agent/cost_logger.py — per-user usage attribution (issue #326)."""
import json
import logging
import sys
from types import ModuleType, SimpleNamespace

strands = ModuleType("strands")
hooks = ModuleType("strands.hooks")
events = ModuleType("strands.hooks.events")
events.AfterInvocationEvent = object
events.AfterToolCallEvent = object
sys.modules.setdefault("strands", strands)
sys.modules.setdefault("strands.hooks", hooks)
sys.modules.setdefault("strands.hooks.events", events)

from agent.cost_logger import log_slides_composed, log_usage  # noqa: E402


def _event(trace_attributes: dict, usage: dict):
    invocation = SimpleNamespace(usage=usage)
    agent = SimpleNamespace(
        name="SdpmVibeAgent",
        event_loop_metrics=SimpleNamespace(latest_agent_invocation=invocation),
        trace_attributes=trace_attributes,
    )
    return SimpleNamespace(agent=agent)


def _single_record(caplog) -> dict:
    records = [r for r in caplog.records if r.name == "sdpm.cost"]
    assert len(records) == 1
    return json.loads(records[0].message)


def test_log_usage_includes_user_and_session(caplog) -> None:
    event = _event(
        trace_attributes={
            "user.id": "user-123", "session.id": "sess-456",
            "model.id": "m1", "purpose": "chat",
        },
        usage={"inputTokens": 100, "outputTokens": 20, "cacheReadInputTokens": 5},
    )
    with caplog.at_level(logging.INFO, logger="sdpm.cost"):
        log_usage(event)

    payload = _single_record(caplog)
    assert payload["kind"] == "bedrock_usage"
    assert payload["user_id"] == "user-123"
    assert payload["session_id"] == "sess-456"
    assert payload["input"] == 100
    assert payload["output"] == 20
    assert payload["cache_read"] == 5


def test_log_usage_includes_deck_for_composer(caplog) -> None:
    event = _event(
        trace_attributes={
            "user.id": "user-123", "session.id": "sess-456", "deck.id": "deck-789",
            "group.index": 0, "group.slugs": "intro,agenda",
            "model.id": "m1", "purpose": "compose",
        },
        usage={"inputTokens": 1, "outputTokens": 2},
    )
    with caplog.at_level(logging.INFO, logger="sdpm.cost"):
        log_usage(event)

    payload = _single_record(caplog)
    assert payload["deck_id"] == "deck-789"
    assert payload["purpose"] == "compose"
    assert payload["group_slugs"] == "intro,agenda"


def test_log_usage_skips_when_no_invocation(caplog) -> None:
    agent = SimpleNamespace(
        name="A",
        event_loop_metrics=SimpleNamespace(latest_agent_invocation=None),
        trace_attributes={},
    )
    with caplog.at_level(logging.INFO, logger="sdpm.cost"):
        log_usage(SimpleNamespace(agent=agent))
    assert not [r for r in caplog.records if r.name == "sdpm.cost"]


def test_log_slides_composed(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="sdpm.cost"):
        log_slides_composed(
            user_id="user-123", session_id="sess-456", deck_id="deck-789",
            generated=8, total=10, status="partial",
        )

    payload = _single_record(caplog)
    assert payload == {
        "kind": "slides_composed",
        "user_id": "user-123",
        "session_id": "sess-456",
        "deck_id": "deck-789",
        "generated": 8,
        "total": 10,
        "status": "partial",
    }
