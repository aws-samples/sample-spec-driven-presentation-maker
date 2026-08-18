# SPDX-License-Identifier: MIT-0
from types import ModuleType, SimpleNamespace
import sys

strands = ModuleType("strands")
hooks = ModuleType("strands.hooks")
events = ModuleType("strands.hooks.events")
events.AfterToolCallEvent = object
sys.modules.setdefault("strands", strands)
sys.modules.setdefault("strands.hooks", hooks)
sys.modules.setdefault("strands.hooks.events", events)

from agent.resilience import LoopGuard  # noqa: E402


class _Agent:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


def _event(stages: list[str]):
    return SimpleNamespace(
        tool_use={"name": "import_attachment", "input": {"source": "s", "deck_id": "d"}},
        result={"code": "IMPORT_INCOMPLETE", "completedStages": stages},
        agent=_Agent(),
    )


def test_loop_guard_resets_repeats_when_completed_stages_advance() -> None:
    guard = LoopGuard(max_tool_calls=20, fingerprint_repeat_limit=3)
    for stages in (["materialize"], ["materialize", "extract_text"], ["materialize", "extract_text", "extract_images"]):
        event = _event(stages)
        guard.after_tool(event)
        assert not event.agent.cancelled
        assert not guard.cancelled


def test_loop_guard_stops_three_no_progress_retries() -> None:
    guard = LoopGuard(max_tool_calls=20, fingerprint_repeat_limit=3)
    first = _event(["materialize"])
    guard.after_tool(first)
    second = _event(["materialize"])
    guard.after_tool(second)
    assert not guard.cancelled
    third = _event(["materialize"])
    guard.after_tool(third)
    assert guard.cancelled
    assert third.agent.cancelled
