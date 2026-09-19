# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for agent/message_hooks.py.

Background: OpenAI GPT models on Bedrock Converse reject `image` blocks nested
inside a `toolResult` ("This model doesn't support the image field for user
messages") but accept the same block as a sibling of the toolResult. Claude
accepts both shapes, so the rewrite runs unconditionally.
"""

import copy
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


_REQUIRED_SYMBOLS = ("BeforeModelCallEvent", "HookProvider", "HookRegistry")


def _require_strands_hooks():
    """Return strands.hooks, skipping unless it really provides what we need.

    A bare ``importorskip`` is not enough: a stale editable install can leave
    ``strands`` importable as an empty namespace package ("unknown location"),
    in which case the import succeeds but the symbols are missing.
    """
    hooks = pytest.importorskip(
        "strands.hooks", reason="strands-agents is an agent-container dependency"
    )
    missing = [name for name in _REQUIRED_SYMBOLS if not hasattr(hooks, name)]
    if missing:
        pytest.skip(f"strands.hooks is missing {missing} (stale or namespace-only install)")
    return hooks


@pytest.fixture
def lift():
    _require_strands_hooks()
    from message_hooks import lift_tool_result_images

    return lift_tool_result_images


def _img(tag: bytes = b"png-bytes"):
    return {"image": {"format": "png", "source": {"bytes": tag}}}


def _tool_result(*content, tool_use_id="tu_1"):
    return {"toolResult": {"toolUseId": tool_use_id, "status": "success",
                           "content": list(content)}}


def _kinds(message):
    return [next(iter(block)) for block in message["content"]]


def test_image_is_lifted_out_of_tool_result(lift):
    messages = [{"role": "user", "content": [_tool_result({"text": "rendered"}, _img())]}]
    assert lift(messages) == 1
    assert _kinds(messages[0]) == ["toolResult", "image"]
    # toolResult keeps its text, loses the image
    assert messages[0]["content"][0]["toolResult"]["content"] == [{"text": "rendered"}]


def test_tool_result_never_left_empty(lift):
    """A toolResult whose only content was an image gets a placeholder text."""
    messages = [{"role": "user", "content": [_tool_result(_img())]}]
    assert lift(messages) == 1
    inner = messages[0]["content"][0]["toolResult"]["content"]
    assert len(inner) == 1
    assert "text" in inner[0]
    assert inner[0]["text"]


def test_multiple_images_preserve_order(lift):
    a, b, c = _img(b"a"), _img(b"b"), _img(b"c")
    messages = [{"role": "user", "content": [_tool_result({"text": "t"}, a, b, c)]}]
    assert lift(messages) == 3
    lifted = [x for x in messages[0]["content"] if "image" in x]
    assert [x["image"]["source"]["bytes"] for x in lifted] == [b"a", b"b", b"c"]


def test_multiple_tool_results_in_one_message(lift):
    messages = [{"role": "user", "content": [
        _tool_result({"text": "one"}, _img(b"1"), tool_use_id="tu_1"),
        _tool_result({"text": "two"}, _img(b"2"), tool_use_id="tu_2"),
    ]}]
    assert lift(messages) == 2
    assert _kinds(messages[0]) == ["toolResult", "toolResult", "image", "image"]


def test_idempotent(lift):
    messages = [{"role": "user", "content": [_tool_result({"text": "t"}, _img(), _img())]}]
    assert lift(messages) == 2
    for _ in range(3):
        assert lift(messages) == 0
    assert sum(1 for x in messages[0]["content"] if "image" in x) == 2


def test_user_attachment_images_untouched(lift):
    """Images already directly in a user message must not be moved or duplicated."""
    original = [{"role": "user", "content": [{"text": "look"}, _img()]}]
    messages = copy.deepcopy(original)
    assert lift(messages) == 0
    assert messages == original


def test_assistant_messages_untouched(lift):
    original = [{"role": "assistant", "content": [
        {"toolUse": {"toolUseId": "tu_1", "name": "render", "input": {}}}]}]
    messages = copy.deepcopy(original)
    assert lift(messages) == 0
    assert messages == original


def test_malformed_blocks_are_skipped(lift):
    messages = [
        {"role": "user"},                                    # no content
        {"role": "user", "content": "not-a-list"},           # content not a list
        {"role": "user", "content": [None, "str", 42]},      # non-dict blocks
        {"role": "user", "content": [{"toolResult": "bad"}]},        # toolResult not a dict
        {"role": "user", "content": [{"toolResult": {"content": "x"}}]},  # inner not a list
    ]
    assert lift(messages) == 0


def test_hook_registers_on_before_model_call():
    hooks = _require_strands_hooks()

    from message_hooks import LiftToolResultImages

    registry = hooks.HookRegistry()
    registry.add_hook(LiftToolResultImages())
    callbacks = list(registry.get_callbacks_for(
        hooks.BeforeModelCallEvent.__new__(hooks.BeforeModelCallEvent)
    ))
    assert callbacks, "LiftToolResultImages must register a BeforeModelCallEvent callback"
