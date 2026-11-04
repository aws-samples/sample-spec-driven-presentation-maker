# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A session's numbered events and their WebSocket frames (agent/event_ring.py).

Replaying a finished turn one event per frame got the connection closed with 1008 on
dev (1,941 items, frame-rate limit); a frame must also stay under 32 KB.
"""

import json

from agent_modules import load


def _ring(**kwargs):
    clock = {"t": 0.0}
    ring = load("event_ring").EventRing(clock=lambda: clock["t"], **kwargs)
    return ring, clock


def _text(t: str, index: int = 0) -> dict:
    return {"event": {"contentBlockDelta": {"delta": {"text": t}, "contentBlockIndex": index}}}


def _reasoning(t: str, index: int = 0) -> dict:
    return {"event": {"contentBlockDelta": {"delta": {"reasoningContent": {"text": t}}, "contentBlockIndex": index}}}


def _texts(items) -> list[str]:
    out = []
    for item in items:
        delta = item["ev"]["event"]["contentBlockDelta"]["delta"]
        out.append(delta["text"] if "text" in delta else "r:" + delta["reasoningContent"]["text"])
    return out


def test_seq_grows_across_periods():
    ring, _ = _ring()
    assert [i["seq"] for i in ring.publish({"a": 1}) + ring.publish({"b": 2})] == [1, 2]
    ring.start_period()
    assert ring.publish({"c": 3})[0]["seq"] == 3
    assert ring.period_start == 3 and ring.head == 3


def test_the_first_delta_of_a_block_goes_out_and_the_rest_are_merged():
    ring, clock = _ring()

    first = ring.publish(_text("Hel"))
    held = ring.publish(_text("lo")) + ring.publish(_text(", "))
    clock["t"] = 0.05
    still = ring.publish(_text("wor"))
    flushed = ring.publish({"toolStart": {"name": "x", "toolUseId": "t1"}})

    assert _texts(first) == ["Hel"]
    assert held == [] and still == []
    assert _texts(flushed[:1]) == ["lo, wor"] and "toolStart" in flushed[1]["ev"]
    assert [i["seq"] for i in first + flushed] == [1, 2, 3]


def test_merged_deltas_flush_after_the_interval_and_at_the_size_cap():
    ring, clock = _ring()
    ring.publish(_text("a"))
    ring.publish(_text("b"))
    assert ring.pending and not ring.due()
    clock["t"] = 0.1
    assert ring.due()
    assert _texts(ring.flush()) == ["b"]
    assert not ring.pending

    out = []
    for _ in range(300):
        out += ring.publish(_text("0123456789"))  # 3,000 bytes in total
    assert _texts(out) == ["0123456789" * 205]  # flushed once at 2 KB


def test_different_blocks_and_kinds_are_not_merged():
    ring, _ = _ring()
    out = (ring.publish(_reasoning("think")) + ring.publish(_reasoning("ing"))
           + ring.publish(_text("Answer", 1)) + ring.publish(_text(" here", 1)) + ring.publish(_text("x", 2)))
    out += ring.flush()

    assert _texts(out) == ["r:think", "r:ing", "Answer", " here", "x"]


def test_replay_from_zero_starts_at_the_current_period():
    ring, _ = _ring()
    ring.publish({"old": 1})
    ring.start_period()
    for n in range(3):
        ring.publish({"new": n})

    items, replay_from, complete = ring.replay(0)

    assert [i["ev"] for i in items] == [{"new": 0}, {"new": 1}, {"new": 2}]
    assert replay_from == 2 and complete


def test_replay_from_inside_returns_only_later_items():
    ring, _ = _ring()
    for n in range(5):
        ring.publish({"n": n})

    items, replay_from, complete = ring.replay(3)

    assert [i["seq"] for i in items] == [4, 5]
    assert replay_from == 4 and complete
    assert ring.replay(5) == ([], 6, True)


def test_the_caps_drop_the_oldest_and_say_so():
    ring, _ = _ring(max_items=3)
    for n in range(5):
        ring.publish({"n": n})

    items, replay_from, complete = ring.replay(0)
    assert [i["seq"] for i in items] == [3, 4, 5] and not complete
    assert ring.replay(2)[2] is True, "nothing the client lacks was dropped"

    ring, _ = _ring(max_bytes=200)
    for n in range(10):
        ring.publish({"payload": "x" * 50, "n": n})
    items, _, complete = ring.replay(0)
    assert len(items) < 10 and not complete


def _frame_ok(frame: str, budget_kb: int = 32) -> None:
    assert len(frame.encode("utf-8")) <= budget_kb * 1024


def _decode(frames: list[str]) -> list[dict]:
    items, chunks = [], {}
    for frame in frames:
        obj = json.loads(frame)
        if "batch" in obj:
            items.extend(obj["batch"])
        elif "chunk" in obj:
            parts = chunks.setdefault(obj["chunk"], {})
            parts[obj["i"]] = obj["data"]
            if len(parts) == obj["n"]:
                items.append(json.loads("".join(parts[i] for i in range(obj["n"]))))
        else:
            items.append(obj)
    return items


def test_many_small_items_go_in_few_batches():
    event_ring = load("event_ring")
    items = [{"seq": n, "ev": {"event": {"contentBlockDelta": {"delta": {"text": "word "}}}}} for n in range(2000)]

    out = event_ring.frames(items)

    assert len(out) < 2000 / 50
    for frame in out:
        _frame_ok(frame)
    assert _decode(out) == items


def test_one_item_is_sent_as_is():
    event_ring = load("event_ring")
    item = {"seq": 7, "ev": {"work": {"state": "busy"}}}

    assert event_ring.frames([item]) == [json.dumps(item, separators=(",", ":"))]


def test_a_large_japanese_tool_result_is_chunked_and_reassembles():
    event_ring = load("event_ring")
    content = ("スライドの構成案：\n" + "「序論」\"引用\" \\ タブ\t制御\x01 " * 2000)[:100_000]
    item = {"seq": 9, "ev": {"toolResult": {"toolUseId": "t1", "name": "read", "status": "success", "content": content}}}
    small = {"seq": 10, "ev": {"work": {"state": "idle"}}}

    out = event_ring.frames([item, small])

    assert len(out) > 4
    for frame in out:
        _frame_ok(frame)
        assert len(frame.encode("utf-8")) <= event_ring.FRAME_BUDGET
    assert _decode(out) == [item, small]
