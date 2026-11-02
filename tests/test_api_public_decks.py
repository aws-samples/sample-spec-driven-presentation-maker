# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Another user's public deck: no response carries the owner's id or chat session.

Same harness as tests/test_api_html_routes.py, but with the real ``authorize`` over a
small in-memory table, so the deck record the routes see includes ``PK=USER#<owner>``
and ``createdBy`` like the stored one.
"""

import json

import pytest

from test_api_html_routes import HTML_KEY, _Event, _FakeS3, index  # noqa: F401 — index is a fixture

OWNER = "u-OWNER-SENTINEL-5e1d"
VIEWER = "u-viewer-0c2a"
SESSION = "chat-session-9f8e"
_OUTLINE = b"- [cover] Cover\n"


class _Table:
    """get_item by key; GSI queries return the public decks (narrowed by :sk when given)."""

    def __init__(self, items: list[dict]):
        self.items = items

    def get_item(self, Key):
        for item in self.items:
            if item["PK"] == Key["PK"] and item["SK"] == Key["SK"]:
                return {"Item": item}
        return {}

    def query(self, IndexName=None, ExpressionAttributeValues=None, **kwargs):
        assert IndexName, "only the PublicDecks GSI is queried in these tests"
        sk = (ExpressionAttributeValues or {}).get(":sk")
        return {"Items": [i for i in self.items if i.get("GSI1PK") and (sk is None or i["SK"] == sk)]}


def _record(index, **extra) -> dict:
    return {
        "PK": index.deck_pk(OWNER), "SK": index.deck_sk("d1"),
        "GSI1PK": index.public_gsi1pk(), "GSI1SK": "2026-11-01T00:00:00Z",
        "name": "Q3 Review", "slideCount": 1, "updatedAt": "2026-11-01T00:00:00Z",
        "visibility": "public", "createdBy": OWNER, "chatSessionId": SESSION,
        "thumbnailS3Key": "previews/d1/cover_100.webp",
        **extra,
    }


def _serve(monkeypatch, index, record: dict, objects: dict, user: str) -> None:
    monkeypatch.setattr(index, "table", _Table([record]))
    monkeypatch.setattr(index, "s3_client", _FakeS3(objects))
    index.app.current_event = _Event(user)


_PPTX_OBJECTS = {
    "decks/d1/deck.json": json.dumps({"template": "blank-dark"}).encode(),
    "decks/d1/specs/outline.md": _OUTLINE,
    "decks/d1/slides/cover.json": b"{}",
    "previews/d1/cover_100.webp": b"x",
}
_HTML_OBJECTS = {
    "decks/d1/deck.json": json.dumps({"outputFormat": "html"}).encode(),
    "decks/d1/specs/outline.md": _OUTLINE,
    "decks/d1/slides/cover.html": b"<section></section>",
}


def test_list_public_has_no_owner_id(monkeypatch, index):  # noqa: F811
    _serve(monkeypatch, index, _record(index), {}, VIEWER)

    result = index.list_public()

    assert [d["deckId"] for d in result["decks"]] == ["d1"]
    assert OWNER not in json.dumps(result)
    assert "createdBy" not in result["decks"][0]


def test_deck_summary_has_no_created_by(index):  # noqa: F811
    assert "createdBy" not in index._deck_summary(_record(index), {})


@pytest.mark.parametrize("extra,objects", [
    ({"pptxS3Key": "pptx/d1/out.pptx"}, _PPTX_OBJECTS),
    ({"htmlS3Key": HTML_KEY}, _HTML_OBJECTS),
], ids=["pptx", "html"])
def test_get_deck_for_a_viewer_has_no_owner_id_or_session(monkeypatch, index, extra, objects):  # noqa: F811
    _serve(monkeypatch, index, _record(index, **extra), objects, VIEWER)

    result = index.get_deck("d1")

    assert result["role"] == "viewer" and result["isOwner"] is False
    assert result["chatSessionId"] is None
    dumped = json.dumps(result)
    assert OWNER not in dumped and SESSION not in dumped


@pytest.mark.parametrize("extra,objects", [
    ({"pptxS3Key": "pptx/d1/out.pptx"}, _PPTX_OBJECTS),
    ({"htmlS3Key": HTML_KEY}, _HTML_OBJECTS),
], ids=["pptx", "html"])
def test_get_deck_for_the_owner_keeps_the_session(monkeypatch, index, extra, objects):  # noqa: F811
    _serve(monkeypatch, index, _record(index, **extra), objects, OWNER)

    result = index.get_deck("d1")

    assert result["role"] == "owner" and result["chatSessionId"] == SESSION
