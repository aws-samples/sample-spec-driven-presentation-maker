# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Review request contract (shared/review.py).

The submission cases live in tests/fixtures/review_submissions.json; the Web UI mirror
(web-ui/src/lib/review/schema.test.ts) runs the same file.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared.review import (
    REVIEW_ID_RE,
    build_review_file,
    created_at_iso,
    extract_refs,
    is_review_id,
    new_review_id,
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


def test_slug_exists_only_sees_valid_slugs():
    seen = []
    body = {"comments": [{"name": "A", "slide": "../x", "rect": [0, 0, 10, 10], "text": "x"}]}
    validate_review_submission(body, _SIZE, lambda s: seen.append(s) or True)
    assert seen == []


def test_extract_refs_ordered_deduped_known_names_only():
    assert extract_refs("@B と @Bと同じ @Z", ["A", "B"], "A") == ["B"]
    assert extract_refs("@C then @B, also @A", ["A", "B", "C"], "A") == ["C", "B"]
    assert extract_refs("@BC1 and @Bx", ["B", "BC"], "A") == []


def test_new_review_id_format():
    now = datetime(2026, 11, 1, 19, 20, 0, tzinfo=timezone(timedelta(hours=9)))
    review_id = new_review_id(now)
    assert review_id.startswith("20261101-102000-")
    assert REVIEW_ID_RE.fullmatch(review_id) and is_review_id(review_id)
    assert created_at_iso(now) == "2026-11-01T10:20:00Z"


@pytest.mark.parametrize("value", ["../x", "20261101-102000-A1B2", "20261101-102000-a1b2\n", "", None, 1])
def test_is_review_id_rejects(value):
    assert not is_review_id(value)


def test_build_review_file_shape():
    normalized = {"note": "全体的に", "comments": [
        {"name": "A", "slide": "sales", "rect": [1248, 238, 576, 400], "text": "@B と同じ色で"},
        {"name": "B", "slide": "intro", "rect": [0, 0, 10, 10], "text": "見出し @A @A"},
    ]}
    file = build_review_file("20261101-102000-a1b2", "2026-11-01T10:20:00Z", (1920, 1080), normalized)
    assert file == {
        "version": 1,
        "id": "20261101-102000-a1b2",
        "created_at": "2026-11-01T10:20:00Z",
        "note": "全体的に",
        "slide_size": [1920, 1080],
        "comments": [
            {"name": "A", "slide": "sales", "rect": [1248, 238, 576, 400], "text": "@B と同じ色で",
             "refs": ["B"], "status": "open", "reply": None},
            {"name": "B", "slide": "intro", "rect": [0, 0, 10, 10], "text": "見出し @A @A",
             "refs": ["A"], "status": "open", "reply": None},
        ],
    }


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
