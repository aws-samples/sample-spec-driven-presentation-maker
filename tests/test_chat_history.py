# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for api.chat_history — GET /chat 6MB response shaping."""

import json

from api.chat_history import (
    MAX_INPUT_STR,
    TRUNCATION_MARKER,
    cap_messages_size,
    strip_tool_result_content,
    truncate_tool_inputs,
)


def _tool_use_msg(input_value: dict) -> dict:
    return {
        "role": "assistant",
        "content": [
            {"toolUse": {"toolUseId": "t1", "name": "write_slide", "input": input_value}},
        ],
    }


class TestStripToolResultContent:
    def test_strips_content_keeps_status(self):
        messages = [{
            "role": "user",
            "content": [{
                "toolResult": {
                    "toolUseId": "t1",
                    "status": "success",
                    "content": [{"text": "x" * 100_000}],
                },
            }],
        }]
        strip_tool_result_content(messages)
        tr = messages[0]["content"][0]["toolResult"]
        assert tr["content"] == []
        assert tr["status"] == "success"

    def test_ignores_plain_text_messages(self):
        messages = [{"role": "user", "content": "hello"}]
        strip_tool_result_content(messages)
        assert messages[0]["content"] == "hello"


class TestTruncateToolInputs:
    def test_long_string_truncated_with_marker(self):
        messages = [_tool_use_msg({"slide_json": "x" * (MAX_INPUT_STR + 1000)})]
        truncate_tool_inputs(messages)
        value = messages[0]["content"][0]["toolUse"]["input"]["slide_json"]
        assert len(value) == MAX_INPUT_STR + len(TRUNCATION_MARKER)
        assert value.endswith(TRUNCATION_MARKER)

    def test_short_ui_fields_untouched(self):
        input_value = {
            "slide_id": "intro",
            "purpose": "Compose the intro slide",
            "slide_groups": json.dumps([{"slugs": ["a", "b"], "instruction": "short"}]),
        }
        messages = [_tool_use_msg(dict(input_value))]
        truncate_tool_inputs(messages)
        assert messages[0]["content"][0]["toolUse"]["input"] == input_value

    def test_nested_structures_truncated(self):
        messages = [_tool_use_msg({
            "groups": [{"instruction": "y" * (MAX_INPUT_STR + 1)}],
        })]
        truncate_tool_inputs(messages)
        value = messages[0]["content"][0]["toolUse"]["input"]["groups"][0]["instruction"]
        assert value.endswith(TRUNCATION_MARKER)

    def test_non_string_values_untouched(self):
        messages = [_tool_use_msg({"count": 5, "flag": True, "empty": None})]
        truncate_tool_inputs(messages)
        assert messages[0]["content"][0]["toolUse"]["input"] == {
            "count": 5, "flag": True, "empty": None,
        }


class TestCapMessagesSize:
    def test_under_budget_unchanged(self):
        messages = [{"role": "user", "content": "hi"}] * 3
        result, truncated = cap_messages_size(messages, max_bytes=10_000)
        assert result == messages
        assert truncated is False

    def test_drops_oldest_first(self):
        messages = [
            {"role": "user", "content": f"msg-{i}: " + "x" * 100} for i in range(10)
        ]
        result, truncated = cap_messages_size(messages, max_bytes=500)
        assert truncated is True
        assert result  # newest messages survive
        assert result[-1] == messages[-1]
        assert result[0] != messages[0]

    def test_always_keeps_last_message(self):
        messages = [{"role": "user", "content": "x" * 1000}] * 2
        result, truncated = cap_messages_size(messages, max_bytes=10)
        assert truncated is True
        assert len(result) == 1
        assert result[0] is messages[-1]
