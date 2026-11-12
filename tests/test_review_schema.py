# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Change request contract (shared/review.py).

The submission cases and the expected message / file (``message_case``) live in
tests/fixtures/review_submissions.json; the Web UI mirror (web-ui/src/lib/review/schema.test.ts)
runs the same file. After editing shared/review_template.json, regenerate
``message_case.expected_message`` with ``build_review_message``.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared.review import (
    REVIEW_ID_RE,
    WHITESPACE,
    build_review_file,
    build_review_message,
    create_review,
    new_review_id,
    review_template,
    slide_size_of,
    validate_review_submission,
)

_FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "review_submissions.json").read_text(encoding="utf-8")
)
_SIZE = tuple(_FIXTURE["slide_size"])
_SLUGS = set(_FIXTURE["slugs"])


@pytest.mark.parametrize("case", _FIXTURE["cases"], ids=[c["name"] for c in _FIXTURE["cases"]])
def test_fixture_case(case):
    normalized, error = validate_review_submission(case["body"], _SIZE, lambda s: s in _SLUGS)
    if case["valid"]:
        assert error is None and normalized is not None
        if "normalized" in case:
            assert normalized == case["normalized"]
    else:
        assert normalized is None and isinstance(error, str) and error


def test_fixture_has_enough_cases():
    assert len(_FIXTURE["cases"]) >= 20
    assert any(c["valid"] for c in _FIXTURE["cases"]) and any(not c["valid"] for c in _FIXTURE["cases"])


def test_normalizes_note_and_text():
    body = {"note": "  \n", "comments": [{"name": "A", "slide": "intro", "rect": [0, 0, 10, 10], "text": "  直して \n"}]}
    normalized, error = validate_review_submission(body, _SIZE, lambda s: s in _SLUGS)
    assert error is None
    assert normalized == {"note": None, "comments": [{"name": "A", "slide": "intro", "rect": [0, 0, 10, 10],
                                                      "text": "直して"}]}


def test_whitespace_covers_str_isspace():
    """The shared set strips at least what ``str.strip()`` strips (the TS test checks ``trim()``)."""
    assert {chr(i) for i in range(0x110000) if chr(i).isspace()} <= set(WHITESPACE)


def test_slug_exists_only_sees_valid_slugs():
    seen = []
    body = {"comments": [{"name": "A", "slide": "../x", "rect": [0, 0, 10, 10], "text": "x"}]}
    validate_review_submission(body, _SIZE, lambda s: seen.append(s) or True)
    assert seen == []


def test_new_review_id_format():
    now = datetime(2026, 11, 1, 19, 20, 0, tzinfo=timezone(timedelta(hours=9)))
    review_id = new_review_id(now)
    assert review_id.startswith("20261101-102000-")
    assert REVIEW_ID_RE.fullmatch(review_id)


_CASE = _FIXTURE["message_case"]


def test_build_review_file_holds_only_what_was_sent():
    file = build_review_file(_CASE["id"], tuple(_CASE["slide_size"]), _CASE["normalized"])
    assert file == {**_CASE["expected_file_without_guide"], "guide": review_template()["guide"]}
    assert list(file) == ["id", "note", "slide_size", "guide", "comments"]


def test_build_review_message_matches_fixture():
    assert build_review_message(_CASE["id"], _CASE["normalized"]) == _CASE["expected_message"]


def test_message_json_block_round_trips():
    message = build_review_message(_CASE["id"], _CASE["normalized"])
    assert message.startswith(f"[review:{_CASE['id']}]\n")
    block = message.split("```json\n", 1)[1].split("\n```", 1)[0]
    payload = json.loads(block)
    assert payload["note"] == _CASE["normalized"]["note"]
    flat = [{"slide": s["slide"], **c} for s in payload["slides"] for c in s["comments"]]
    assert sorted(flat, key=lambda c: c["name"]) == sorted(_CASE["normalized"]["comments"], key=lambda c: c["name"])
    assert [s["slide"] for s in payload["slides"]] == ["sales", "intro"]


def test_template_placeholders_are_known():
    used = set(re.findall(r"\{(\w+)\}", "\n".join(review_template()["message"])))
    assert used == {"id", "path", "count", "slides", "payload"}
    assert review_template()["message"][0] == "[review:{id}]"
    assert isinstance(review_template()["guide"], str) and review_template()["guide"]


@pytest.mark.parametrize("deck_json, expected", [
    ({}, (1920, 1080)),
    (None, (1920, 1080)),
    ({"slideSize": "big"}, (1920, 1080)),
    ({"slideSize": {"width": 1280, "height": 720}}, (1280, 720)),
    ({"slideSize": {"width": 1280.7, "height": 720}}, (1280, 720)),
    ({"slideSize": {"width": True, "height": 0}}, (1920, 1080)),
    ({"slideSize": {"width": float("inf"), "height": -5}}, (1920, 1080)),
])
def test_slide_size_of(deck_json, expected):
    assert slide_size_of(deck_json) == expected


# --- create_review: the review routes' steps, storage passed in ---------------------------

_BODY = {"note": "tighter", "comments": [{"name": "A", "slide": "sales", "rect": [10, 20, 30, 40], "text": " bigger "}]}
_NOW = datetime(2026, 11, 9, 1, 2, 3, tzinfo=timezone.utc)


class _Store:
    def __init__(self, taken: int = 0) -> None:
        self.files: dict[str, bytes] = {}
        self.events: list[str] = []
        self.taken = taken

    def clear(self) -> None:
        self.events.append("clear")

    def write_new(self, path: str, data: bytes) -> bool:
        self.events.append(f"write {path}")
        if self.taken:
            self.taken -= 1
            return False
        self.files[path] = data
        return True


def _create(store: _Store, body=_BODY):
    return create_review(body, {"slideSize": {"width": 1280, "height": 720}}, lambda s: s in _SLUGS,
                         clear=store.clear, write_new=store.write_new, now=lambda: _NOW)


def test_create_review_clears_then_writes_the_file_and_returns_the_message():
    store = _Store()
    got = _create(store)
    rid = got["id"]
    assert REVIEW_ID_RE.fullmatch(rid) and rid.startswith("20261109-010203-")
    assert store.events == ["clear", f"write reviews/{rid}.json"]
    normalized, _ = validate_review_submission(_BODY, (1280, 720), lambda s: s in _SLUGS)
    assert json.loads(store.files[f"reviews/{rid}.json"]) == build_review_file(rid, (1280, 720), normalized)
    assert got["message"] == build_review_message(rid, normalized)


def test_create_review_takes_a_new_id_when_one_is_taken(monkeypatch):
    hexes = iter(["aaaa", "bbbb"])
    monkeypatch.setattr("shared.review.secrets.token_hex", lambda n: next(hexes))
    store = _Store(taken=1)
    got = _create(store)
    assert got["id"] == "20261109-010203-bbbb"
    assert list(store.files) == ["reviews/20261109-010203-bbbb.json"]


def test_create_review_gives_up_after_three_taken_ids():
    store = _Store(taken=3)
    with pytest.raises(RuntimeError):
        _create(store)
    assert store.files == {}


@pytest.mark.parametrize("body", [
    {"comments": []},
    {"note": None, "comments": [{"name": "A", "slide": "gone", "rect": [0, 0, 5, 5], "text": "x"}]},
    "not an object",
    {"note": "x" * (512 * 1024), "comments": []},
])
def test_create_review_refuses_a_bad_body_before_clearing(body):
    store = _Store()
    with pytest.raises(ValueError):
        _create(store, body)
    assert store.events == []
