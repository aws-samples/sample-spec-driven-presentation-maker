# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Message normalization hooks applied to every agent.

Currently one concern: OpenAI GPT models on Bedrock Converse reject `image`
blocks nested inside a `toolResult`, while accepting the identical block as a
sibling of the `toolResult` in the same user message. Claude accepts both, so
the rewrite is applied unconditionally rather than gated on a model capability
flag — one shape for every model.
"""

from typing import Any

from strands.hooks import BeforeModelCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

_PLACEHOLDER = "(image returned by the tool; see the attached image below)"


def lift_tool_result_images(messages: list[dict[str, Any]]) -> int:
    """Move `image` blocks out of `toolResult` into the enclosing user message.

    GPT models on Bedrock Converse fail with
    ``ValidationException: This model doesn't support the image field for user
    messages`` when an image is nested inside a ``toolResult``. Moving the block
    up one level keeps the image visible to the model and is accepted by both
    GPT and Claude.

    Images already sitting directly in a user message (e.g. user attachments)
    are left alone. The function is idempotent: a second pass moves nothing.

    Args:
        messages: Conversation messages, mutated in place.

    Returns:
        Number of image blocks moved.
    """
    moved = 0
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        lifted: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            tool_result = block.get("toolResult")
            if not isinstance(tool_result, dict):
                continue
            inner_content = tool_result.get("content")
            if not isinstance(inner_content, list):
                continue
            kept = []
            found = []
            for inner in inner_content:
                if isinstance(inner, dict) and "image" in inner:
                    found.append(inner)
                else:
                    kept.append(inner)
            if found:
                # A toolResult must not end up with empty content.
                tool_result["content"] = kept or [{"text": _PLACEHOLDER}]
                lifted.extend(found)
        if lifted:
            content.extend(lifted)
            moved += len(lifted)
    return moved


class LiftToolResultImages(HookProvider):
    """Normalize tool-result images before every model call.

    Registered on ``BeforeModelCallEvent`` rather than ``MessageAddedEvent`` so
    that it also covers messages the framework did not add itself — pre-seeded
    history (the composer passes ``messages=list(composer_history)``) and
    session-restored history. Runs on every model call and is idempotent.
    """

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        """Register the before-model-call callback."""
        registry.add_callback(BeforeModelCallEvent, self._on_before_model_call)

    def _on_before_model_call(self, event: BeforeModelCallEvent) -> None:
        lift_tool_result_images(event.agent.messages)


# Tools whose deck_id must be the deck the composer was dispatched for.
DECK_SCOPED_TOOLS = frozenset({
    "run_python", "generate_pptx", "get_preview", "check_specs",
    "code_to_slide", "import_attachment", "apply_style",
})


def pin_deck_id(tool_use: dict[str, Any], deck_id: str, names: frozenset[str] = DECK_SCOPED_TOOLS) -> bool:
    """Force ``deck_id`` on a deck-scoped tool call; return True when it was changed.

    A composer that omits deck_id on run_python gets a sandbox with no workspace and
    its writes vanish silently, so the harness pins the value it already knows.
    """
    if tool_use.get("name") not in names:
        return False
    params = tool_use.setdefault("input", {})
    if not isinstance(params, dict):
        return False
    if params.get("deck_id") == deck_id:
        return False
    params["deck_id"] = deck_id
    return True


class PinDeckId(HookProvider):
    """Pin the dispatched deck_id on every deck-scoped tool call of a composer."""

    def __init__(self, deck_id: str) -> None:
        self._deck_id = deck_id

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._on_before_tool_call)

    def _on_before_tool_call(self, event: BeforeToolCallEvent) -> None:
        pin_deck_id(event.tool_use, self._deck_id)
