# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A session's numbered events (the ring) and their WebSocket frames. Pure: no I/O.

Every event the session publishes gets the next ``seq`` (monotonic for the life of
the process). The ring keeps the current work period, so a client that reconnects
(reload, sleep, a dropped network) asks for what it missed with ``resume(from_seq)``.

Text deltas are most of a turn's events (about 2,000 in a 2.5-minute turn on dev),
and replaying them one frame each got the connection closed with 1008 (frame-rate
limit). So consecutive text (or reasoning-text) deltas of one content block are
coalesced when published: the first one goes out at once, later ones are merged and
flushed after COALESCE_S, at COALESCE_BYTES, or when any other event arrives. Live
subscribers and a replay see the same items.

frames() packs items into WebSocket text frames of at most ``budget`` UTF-8 bytes:
one item as is, several as ``{"batch": [...]}``, and an item larger than the budget
as consecutive ``{"chunk", "i", "n", "data"}`` frames that concatenate to its JSON.
"""

import json
import secrets
import time
from collections import deque
from typing import Callable

MAX_ITEMS = 20_000
MAX_BYTES = 16 * 1024 * 1024
COALESCE_S = 0.1
COALESCE_BYTES = 2048
# Frame payload budget: below the smaller documented frame limit (32 KB) with room
# for the wrapper.
FRAME_BUDGET = 24_000


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _delta_text(ev: dict) -> tuple[tuple[str, int], str] | None:
    """((kind, block index), text) for a plain text or reasoning-text delta, else None."""
    event = ev.get("event") if isinstance(ev, dict) else None
    block = event.get("contentBlockDelta") if isinstance(event, dict) else None
    if not isinstance(block, dict) or set(event) != {"contentBlockDelta"}:
        return None
    delta = block.get("delta")
    index = block.get("contentBlockIndex", 0)
    if not isinstance(delta, dict) or len(delta) != 1:
        return None
    if isinstance(delta.get("text"), str):
        return ("text", index), delta["text"]
    reasoning = delta.get("reasoningContent")
    if isinstance(reasoning, dict) and set(reasoning) == {"text"} and isinstance(reasoning["text"], str):
        return ("reasoning", index), reasoning["text"]
    return None


def _with_text(ev: dict, kind: str, text: str) -> dict:
    block = dict(ev["event"]["contentBlockDelta"])
    block["delta"] = {"text": text} if kind == "text" else {"reasoningContent": {"text": text}}
    return {"event": {"contentBlockDelta": block}}


class EventRing:
    """Numbered events of one session (see the module docstring). Not thread-safe:
    the session runtime calls it under the session's lock."""

    def __init__(self, max_items: int = MAX_ITEMS, max_bytes: int = MAX_BYTES,
                 clock: Callable[[], float] = time.monotonic):
        self.max_items = max_items
        self.max_bytes = max_bytes
        self.clock = clock
        self.head = 0  # the last seq given out
        self.period_start = 1  # the first seq of the current work period
        self._items: deque[tuple[dict, int]] = deque()
        self._bytes = 0
        self._dropped_through = 0  # the last seq dropped by the caps
        self._block: tuple[str, int] | None = None  # the content block deltas are streaming into
        self._pending: dict | None = None  # merged deltas not given a seq yet

    # -- publishing -------------------------------------------------------------

    def publish(self, ev: dict) -> list[dict]:
        """Add an event; returns the items ({"seq", "ev"}) to send now."""
        found = _delta_text(ev)
        if found is not None:
            key, text = found
            if self._block == key:
                pending = self._pending
                if pending is None:
                    self._pending = {"ev": ev, "kind": key[0], "text": text, "since": self.clock()}
                else:
                    pending["text"] += text
                if len(self._pending["text"].encode("utf-8")) >= COALESCE_BYTES or self.due():
                    return self.flush()
                return []
            out = self.flush()
            self._block = key
            out.append(self._add(ev))
            return out
        out = self.flush()
        self._block = None
        out.append(self._add(ev))
        return out

    def due(self) -> bool:
        """True when merged deltas have waited COALESCE_S."""
        return self._pending is not None and self.clock() - self._pending["since"] >= COALESCE_S

    @property
    def pending(self) -> bool:
        return self._pending is not None

    def flush(self) -> list[dict]:
        """Give the merged deltas their seq; returns them as items to send (or [])."""
        pending, self._pending = self._pending, None
        if pending is None:
            return []
        return [self._add(_with_text(pending["ev"], pending["kind"], pending["text"]))]

    def _add(self, ev: dict) -> dict:
        self.head += 1
        item = {"seq": self.head, "ev": ev}
        size = len(_dumps(item).encode("utf-8"))
        self._items.append((item, size))
        self._bytes += size
        while self._items and (len(self._items) > self.max_items or self._bytes > self.max_bytes):
            dropped, dropped_size = self._items.popleft()
            self._bytes -= dropped_size
            self._dropped_through = dropped["seq"]
        return item

    # -- periods and replay -----------------------------------------------------

    def start_period(self) -> None:
        """A new work period starts: forget the previous one (seq keeps counting)."""
        self._items.clear()
        self._bytes = 0
        self._pending = None
        self._block = None
        self.period_start = self.head + 1
        self._dropped_through = 0

    def replay(self, from_seq: int) -> tuple[list[dict], int, bool]:
        """Items after ``from_seq`` in the current period.

        Returns (items, the first seq replayed or head + 1, complete). A ``from_seq``
        before the period starts replays the whole period; ``complete`` is False when
        the caps dropped items the client did not have.
        """
        first_needed = max(int(from_seq) + 1, self.period_start)
        items = [item for item, _ in self._items if item["seq"] >= first_needed]
        complete = self._dropped_through < first_needed
        replay_from = items[0]["seq"] if items else self.head + 1
        return items, replay_from, complete


# -- frames -------------------------------------------------------------------


def _escaped_cost(ch: str) -> int:
    """Bytes ``ch`` takes inside a JSON string (ensure_ascii=False)."""
    if ch in '"\\':
        return 2
    code = ord(ch)
    if code < 0x20:
        return 2 if ch in "\n\r\t\b\f" else 6
    return len(ch.encode("utf-8", "surrogatepass"))


def _split(text: str, limit: int) -> list[str]:
    """Split ``text`` on code-point (UTF-8) boundaries into parts whose JSON-escaped
    size is at most ``limit`` bytes."""
    parts: list[str] = []
    start, size = 0, 0
    for i, ch in enumerate(text):
        cost = _escaped_cost(ch)
        if size + cost > limit and i > start:
            parts.append(text[start:i])
            start, size = i, 0
        size += cost
    parts.append(text[start:])
    return parts


def frames(items: list[dict], budget: int = FRAME_BUDGET) -> list[str]:
    """Pack items into frames of at most ``budget`` UTF-8 bytes (see the module docstring)."""
    out: list[str] = []
    batch: list[str] = []
    batch_size = 0
    wrapper = len('{"batch":[]}')

    def close_batch() -> None:
        nonlocal batch, batch_size
        if len(batch) == 1:
            out.append(batch[0])
        elif batch:
            out.append('{"batch":[' + ",".join(batch) + "]}")
        batch, batch_size = [], 0

    for item in items:
        text = _dumps(item)
        size = len(text.encode("utf-8"))
        if size > budget:
            close_batch()
            chunk_id = secrets.token_hex(4)
            parts = _split(text, budget - 128)
            for i, part in enumerate(parts):
                out.append(_dumps({"chunk": chunk_id, "i": i, "n": len(parts), "data": part}))
            continue
        if batch and wrapper + batch_size + len(batch) + size > budget:
            close_batch()
        batch.append(text)
        batch_size += size
    close_batch()
    return out
