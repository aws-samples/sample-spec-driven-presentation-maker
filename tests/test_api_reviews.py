# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Route-level tests for the review request endpoints of api/index.py.

Same harness as tests/test_api_html_routes.py: aws_lambda_powertools is replaced by a
minimal stand-in, routes are called directly with a fake S3 client and a stubbed
``authorize``.
"""

import importlib
import io
import json
import logging
import sys
import types
from pathlib import Path

import pytest

from shared.authz import AccessDecision
from shared.review import MAX_BODY_BYTES, is_review_id

_API_DIR = Path(__file__).resolve().parent.parent / "api"
_API_MODULES = ("index", "authz", "common", "chat_history", "html_presign")
BUCKET = "sdpm-pptx-test"
REGION = "ap-northeast-1"


class _Resolver:
    def __init__(self, *args, **kwargs):
        self.current_event = None

    def _route(self, *args, **kwargs):
        return lambda fn: fn

    get = post = put = patch = delete = _route


class _Metrics:
    def __init__(self, *args, **kwargs):
        pass

    def log_metrics(self, *args, **kwargs):
        return lambda fn: fn


def _powertools_stub() -> dict[str, types.ModuleType]:
    root = types.ModuleType("aws_lambda_powertools")
    root.Logger = lambda *a, **k: logging.getLogger("test-api")
    root.Metrics = _Metrics
    handler = types.ModuleType("aws_lambda_powertools.event_handler")
    handler.APIGatewayHttpResolver = _Resolver
    handler.CORSConfig = lambda **kwargs: kwargs
    utilities = types.ModuleType("aws_lambda_powertools.utilities")
    typing_mod = types.ModuleType("aws_lambda_powertools.utilities.typing")
    typing_mod.LambdaContext = object
    return {
        "aws_lambda_powertools": root,
        "aws_lambda_powertools.event_handler": handler,
        "aws_lambda_powertools.utilities": utilities,
        "aws_lambda_powertools.utilities.typing": typing_mod,
    }


class _Event:
    def __init__(self, user_id: str, body: str | None = None):
        self.raw_event = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": user_id}}}}}
        self.body = body

    @property
    def json_body(self):
        return json.loads(self.body) if self.body is not None else None

    def get_query_string_value(self, name, default_value=None):
        return default_value


class _FakeS3:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects
        self.calls: list[str] = []
        self.puts: list[dict] = []

    def get_object(self, Bucket, Key):
        self.calls.append("get_object")
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def head_object(self, Bucket, Key):
        self.calls.append("head_object")
        if Key not in self.objects:
            raise KeyError(Key)
        return {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.calls.append("put_object")
        self.puts.append({"Key": Key, "ContentType": ContentType})
        self.objects[Key] = Body

    def list_objects_v2(self, Bucket, Prefix):
        self.calls.append("list_objects_v2")
        return {"Contents": [{"Key": k} for k in sorted(self.objects) if k.startswith(Prefix)]}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://app-origin.example/{Params['Key']}"


@pytest.fixture()
def index(monkeypatch):
    for name, module in _powertools_stub().items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("TABLE_NAME", "sdpm-test")
    monkeypatch.setenv("PPTX_BUCKET", BUCKET)
    monkeypatch.setenv("AWS_REGION", REGION)
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    for env in ("KB_ID", "CF_DOMAIN", "CF_KEY_PAIR_ID", "CF_PRIVATE_KEY_PARAM"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.syspath_prepend(str(_API_DIR))
    saved = {name: sys.modules.pop(name) for name in _API_MODULES if name in sys.modules}
    try:
        yield importlib.import_module("index")
    finally:
        for name in _API_MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


_DECK_OBJECTS = {
    "decks/d1/deck.json": json.dumps({"slideSize": {"width": 1280, "height": 720}}).encode(),
    "decks/d1/slides/intro.json": b"{}",
    "decks/d1/slides/sales.html": b"<section></section>",
}


def _setup(monkeypatch, index, *, allowed=True, objects=None, body=None):
    calls: list[tuple] = []

    def authorize(user_id, deck_id, action, table):
        calls.append((user_id, deck_id, action))
        if not allowed:
            return AccessDecision(allowed=False, role="none", reason="no access")
        return AccessDecision(allowed=True, role="owner", deck={"deckId": "d1", "name": "Q3"})

    s3 = _FakeS3(dict(_DECK_OBJECTS if objects is None else objects))
    monkeypatch.setattr(index, "authorize", authorize)
    monkeypatch.setattr(index, "s3_client", s3)
    index.app.current_event = _Event("u1", body)
    return calls, s3


def _submission(**overrides):
    body = {
        "note": "全体的に文字を減らして",
        "comments": [
            {"name": "A", "slide": "sales", "rect": [100, 50, 400, 200], "text": "@B と同じ色で", "refs": ["Z"]},
            {"name": "B", "slide": "intro", "rect": [0, 0, 1280, 720], "text": "この見出し"},
        ],
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)


# --- POST /decks/{id}/reviews ------------------------------------------------


def test_create_denied_writes_nothing(monkeypatch, index):
    calls, s3 = _setup(monkeypatch, index, allowed=False, body=_submission())
    assert index.create_review("d1") == ({"error": "no access"}, 403)
    assert calls == [("u1", "d1", "edit_slide")]
    assert s3.puts == [] and s3.calls == []


def test_create_writes_server_computed_file(monkeypatch, index):
    calls, s3 = _setup(monkeypatch, index, body=_submission())
    review = index.create_review("d1")
    assert calls == [("u1", "d1", "edit_slide")]
    assert is_review_id(review["id"])
    key = f"decks/d1/reviews/{review['id']}.json"
    assert s3.puts == [{"Key": key, "ContentType": "application/json; charset=utf-8"}]
    stored = json.loads(s3.objects[key].decode("utf-8"))
    assert stored == review
    assert review["version"] == 1 and review["slide_size"] == [1280, 720]
    assert review["note"] == "全体的に文字を減らして"
    assert review["created_at"].endswith("Z")
    a, b = review["comments"]
    assert a == {"name": "A", "slide": "sales", "rect": [100, 50, 400, 200], "text": "@B と同じ色で",
                 "refs": ["B"], "status": "open", "reply": None}
    assert b["refs"] == [] and b["status"] == "open"


@pytest.mark.parametrize("comments", [
    [{"name": "A", "slide": "intro", "rect": [1000, 0, 400, 100], "text": "x"}],  # overflows 1280 wide
    [{"name": "A", "slide": "missing", "rect": [0, 0, 10, 10], "text": "x"}],
    [{"name": "A", "slide": "reviews", "rect": [0, 0, 10, 10], "text": "x"}],
    [{"name": "a", "slide": "intro", "rect": [0, 0, 10, 10], "text": "x"}],
    [],
])
def test_create_rejects_invalid_submission(monkeypatch, index, comments):
    _, s3 = _setup(monkeypatch, index, body=_submission(comments=comments))
    body, status = index.create_review("d1")
    assert status == 400 and body["error"]
    assert s3.puts == []


def test_create_rejects_invalid_json(monkeypatch, index):
    _, s3 = _setup(monkeypatch, index, body="{not json")
    body, status = index.create_review("d1")
    assert status == 400 and s3.puts == []


def test_create_rejects_oversize_body(monkeypatch, index):
    _, s3 = _setup(monkeypatch, index, body=_submission(note="x" * MAX_BODY_BYTES))
    body, status = index.create_review("d1")
    assert status == 413 and s3.puts == []


def test_create_regenerates_an_existing_id(monkeypatch, index):
    _, s3 = _setup(monkeypatch, index, body=_submission())
    ids = iter(["20261101-102000-aaaa", "20261101-102000-bbbb"])
    monkeypatch.setattr(index, "new_review_id", lambda now: next(ids))
    s3.objects["decks/d1/reviews/20261101-102000-aaaa.json"] = b"{}"
    review = index.create_review("d1")
    assert review["id"] == "20261101-102000-bbbb"
    assert s3.objects["decks/d1/reviews/20261101-102000-aaaa.json"] == b"{}"


# --- GET /decks/{id}/reviews/{reviewId} -------------------------------------


@pytest.mark.parametrize("review_id", ["../x", "20261101-102000-A1B2", "x.json"])
def test_get_rejects_bad_id_before_any_access(monkeypatch, index, review_id):
    calls, s3 = _setup(monkeypatch, index)
    body, status = index.get_review("d1", review_id)
    assert status == 400
    assert calls == [] and s3.calls == []


def test_get_denied(monkeypatch, index):
    calls, s3 = _setup(monkeypatch, index, allowed=False)
    assert index.get_review("d1", "20261101-102000-a1b2") == ({"error": "no access"}, 403)
    assert calls == [("u1", "d1", "edit_slide")] and s3.calls == []


def test_get_missing_or_not_an_object(monkeypatch, index):
    _, s3 = _setup(monkeypatch, index)
    assert index.get_review("d1", "20261101-102000-a1b2")[1] == 404
    s3.objects["decks/d1/reviews/20261101-102000-a1b2.json"] = b"[1, 2]"
    assert index.get_review("d1", "20261101-102000-a1b2")[1] == 404


def test_get_round_trip(monkeypatch, index):
    _, s3 = _setup(monkeypatch, index, body=_submission())
    review = index.create_review("d1")
    assert index.get_review("d1", review["id"]) == review


# --- get_deck slideSize ------------------------------------------------------


def test_pptx_get_deck_returns_slide_size(monkeypatch, index):
    _setup(monkeypatch, index)
    result = index.get_deck("d1")
    assert "outputFormat" not in result
    assert result["slideSize"] == {"width": 1280, "height": 720}


def test_pptx_get_deck_defaults_slide_size(monkeypatch, index):
    _setup(monkeypatch, index, objects={"decks/d1/slides/intro.json": b"{}"})
    assert index.get_deck("d1")["slideSize"] == {"width": 1920, "height": 1080}
