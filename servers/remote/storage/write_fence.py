# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Write fence: a stopped agent turn's in-flight tool calls no longer change the deck.

Stopping a Cloud turn does not stop the MCP calls it has already sent: the server is
stateless (``notifications/cancelled`` reaches another request) and tool bodies run on
threads that cannot be interrupted. Measured on dev: run_python wrote 4 slides 1.7 s
after a cancel, and a generate_pptx call's background previews were uploaded 1.5 s after
a StopRuntimeSession.

How it works:
  - The agent mints a generation per turn (an integer that grows over time) and sends
    it in every tool call's ``_meta`` (GENERATION_META_KEY).
  - When the turn is stopped, the agent calls ``fence_turn(deck_ids)`` with that
    generation. ``advance`` raises the deck item's FENCE_ATTR to it with a conditional
    UpdateItem (never lowers it).
  - Every S3 write AwsStorage makes for a request that carries a generation and names a
    deck checks the deck item first (``check``). A generation at or below the fence is a
    stopped turn: the write is skipped and StaleTurn is raised. The deck record update
    that accompanies a build (``update_deck``) carries the same test as its condition, so
    a write racing the fence cannot repoint the deck at a stale artifact.

Requests without a generation (the local server, other MCP clients, older agents) are
not fenced. A newer turn is never fenced by an older turn's stop, and a finished turn's
background work (previews after generate_pptx) is not dropped by the next turn's start.

The fence for a request lives in a ContextVar. ``asyncio.to_thread`` copies it into the
tool's thread; threads the tool starts itself get it through ``carry``.
"""

from __future__ import annotations

import contextvars
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from shared.schema import deck_pk, deck_sk

logger = logging.getLogger("sdpm.mcp")

# _meta key of the caller's turn generation (MCP _meta keys may carry a prefix/name).
GENERATION_META_KEY = "sdpm/generation"
# Deck item attribute: the newest stopped generation. Writes at or below it are skipped.
FENCE_ATTR = "writeFence"

# A generation from further in the future than this is rejected: it would keep the
# deck fenced for the owner's own later turns until the clock caught up.
_FUTURE_SLACK_NS = 300 * 10**9


class StaleTurn(RuntimeError):
    """The request belongs to a stopped turn; its write was skipped."""


@dataclass
class Fence:
    """The fence of one request: its generation and the deck item to check."""

    generation: int
    user_id: str
    deck_id: str
    stale: bool = False

    def error(self) -> StaleTurn:
        return StaleTurn(
            f"Cancelled: the agent turn that made this call was stopped, so its writes to "
            f"deck {self.deck_id} were skipped."
        )


_current: contextvars.ContextVar[Fence | None] = contextvars.ContextVar("sdpm_write_fence", default=None)


def valid_generation(value: Any) -> int | None:
    """The generation as an int, or None when it is missing, not an integer or from the future."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    if value > time.time_ns() + _FUTURE_SLACK_NS:
        return None
    return value


def generation_from_meta(meta: Any) -> int | None:
    """Read the generation from a request's ``_meta`` (a pydantic model with extra fields, or a dict)."""
    if meta is None:
        return None
    extra = meta if isinstance(meta, dict) else (getattr(meta, "model_extra", None) or {})
    if GENERATION_META_KEY not in extra:
        return None
    generation = valid_generation(extra[GENERATION_META_KEY])
    if generation is None:
        logger.warning("write fence: ignoring an invalid generation %r", extra[GENERATION_META_KEY])
    return generation


def bind(fence: Fence) -> contextvars.Token:
    """Make ``fence`` the current request's fence. Pair with ``reset``."""
    return _current.set(fence)


def reset(token: contextvars.Token) -> None:
    _current.reset(token)


def current() -> Fence | None:
    return _current.get()


def carry(fn: Callable) -> Callable:
    """Wrap ``fn`` so it runs under the caller's fence on another thread (Thread targets,
    thread-pool tasks). Only the fence is carried, nothing else from the context."""
    fence = _current.get()
    if fence is None:
        return fn

    def run(*args, **kwargs):
        token = _current.set(fence)
        try:
            return fn(*args, **kwargs)
        finally:
            _current.reset(token)

    return run


def _key(fence: Fence) -> dict:
    return {"PK": deck_pk(fence.user_id), "SK": deck_sk(fence.deck_id)}


def _skip(fence: Fence, floor: Any) -> StaleTurn:
    if not fence.stale:
        fence.stale = True
        logger.info(
            "write fence: deck %s: generation %s is at or below the fence %s; skipping this request's writes",
            fence.deck_id, fence.generation, floor,
        )
    return fence.error()


def check(table: Any) -> None:
    """Raise StaleTurn when the current request's turn has been fenced; no-op without a fence.

    One consistent GetItem per write. Once a request is found stale, its later writes are
    skipped without another read.
    """
    fence = _current.get()
    if fence is None:
        return
    if fence.stale:
        raise fence.error()
    item = table.get_item(
        Key=_key(fence),
        ProjectionExpression="#wf",
        ExpressionAttributeNames={"#wf": FENCE_ATTR},
        ConsistentRead=True,
    ).get("Item")
    floor = (item or {}).get(FENCE_ATTR)
    if floor is not None and fence.generation <= int(floor):
        raise _skip(fence, floor)


def update_condition() -> tuple[Fence, dict] | None:
    """For a fenced request: the fence and the UpdateItem arguments that make a deck
    record update conditional on it. None without a fence."""
    fence = _current.get()
    if fence is None:
        return None
    if fence.stale:
        raise fence.error()
    return fence, {
        "ConditionExpression": "attribute_not_exists(#wf) OR #wf < :wf_gen",
        "ExpressionAttributeNames": {"#wf": FENCE_ATTR},
        "ExpressionAttributeValues": {":wf_gen": fence.generation},
    }


def condition_failed(fence: Fence) -> StaleTurn:
    """The StaleTurn for a conditional deck update that the fence rejected."""
    return _skip(fence, "(conditional update)")


def is_conditional_check_failure(error: Exception) -> bool:
    response = getattr(error, "response", None) or {}
    return response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def advance(table: Any, user_id: str, deck_id: str, generation: int) -> bool:
    """Raise the fence of the caller's own deck to ``generation``.

    Conditional: the item must exist under the caller's key (only an owner fences a
    deck) and its fence must be lower. Returns False when nothing changed.
    """
    try:
        table.update_item(
            Key={"PK": deck_pk(user_id), "SK": deck_sk(deck_id)},
            UpdateExpression="SET #wf = :wf_gen",
            ConditionExpression="attribute_exists(PK) AND (attribute_not_exists(#wf) OR #wf < :wf_gen)",
            ExpressionAttributeNames={"#wf": FENCE_ATTR},
            ExpressionAttributeValues={":wf_gen": generation},
        )
        return True
    except Exception as e:
        if is_conditional_check_failure(e):
            return False
        raise
