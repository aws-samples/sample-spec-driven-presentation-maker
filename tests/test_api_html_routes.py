# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Route-level tests for the HTML deck endpoints of api/index.py.

aws_lambda_powertools is not a dev dependency, so the module is imported with a
minimal stand-in for the parts it uses at import time (Logger, Metrics, the HTTP
resolver's route decorators and current_event). The route functions are then
called directly with a fake S3 client and a stubbed ``authorize``.
"""

import importlib
import io
import json
import logging
import sys
import types
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from shared.authz import AccessDecision

_API_DIR = Path(__file__).resolve().parent.parent / "api"
_API_MODULES = ("index", "authz", "common", "chat_history", "html_presign")
BUCKET = "sdpm-pptx-test"
REGION = "ap-northeast-1"
HTML_KEY = "html/d1/0b0e6c3e-7f6b-4c4c-9a39-1d0f8f5f0a11.html"


class _Resolver:
    """Route decorators that return the function unchanged; tests set current_event."""

    def __init__(self, *args, **kwargs):
        self.current_event = None

    def _route(self, *args, **kwargs):
        return lambda fn: fn

    get = post = put = patch = delete = _route

    def resolve(self, event, context):  # pragma: no cover - not used by the tests
        raise NotImplementedError


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
    def __init__(self, user_id: str, query: dict | None = None):
        self.raw_event = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": user_id}}}}}
        self._query = query or {}

    def get_query_string_value(self, name, default_value=None):
        return self._query.get(name, default_value)


class _FakeS3:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def list_objects_v2(self, Bucket, Prefix):
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


def _setup(monkeypatch, index, *, allowed=True, role="owner", deck=None, objects=None, query=None, user="u1"):
    calls: list[tuple] = []
    record = {"deckId": "d1", "name": "Q3 Review", **(deck or {})}

    def authorize(user_id, deck_id, action, table):
        calls.append((user_id, deck_id, action))
        if not allowed:
            return AccessDecision(allowed=False, role="none", reason="no access")
        return AccessDecision(allowed=True, role=role, deck=record)

    monkeypatch.setattr(index, "authorize", authorize)
    monkeypatch.setattr(index, "s3_client", _FakeS3(dict(objects or {})))
    index.app.current_event = _Event(user, query)
    return calls


def _regional(url: str) -> tuple[str, dict]:
    parts = urlsplit(url)
    assert parts.scheme == "https" and parts.netloc == f"{BUCKET}.s3.{REGION}.amazonaws.com"
    return parts.path, parse_qs(parts.query)


# --- GET /decks/{id}/html ----------------------------------------------------


def test_html_denied_before_purpose_and_record_checks(monkeypatch, index):
    calls = _setup(monkeypatch, index, allowed=False, query={"purpose": "bogus"})
    body, status = index.get_deck_html("d1")
    assert status == 403 and body == {"error": "no access"}
    assert calls == [("u1", "d1", "read")]


def test_html_bad_purpose_is_400(monkeypatch, index):
    _setup(monkeypatch, index, deck={"htmlS3Key": HTML_KEY}, query={"purpose": "view"})
    assert index.get_deck_html("d1")[1] == 400


def test_html_not_built_is_404(monkeypatch, index):
    _setup(monkeypatch, index, query={"purpose": "present"})
    assert index.get_deck_html("d1") == ({"error": "HTML not built yet"}, 404)


def test_html_refuses_a_non_html_key(monkeypatch, index):
    _setup(monkeypatch, index, deck={"htmlS3Key": "uploads/u1/a.pdf"}, query={"purpose": "present"})
    assert index.get_deck_html("d1")[1] == 404


@pytest.mark.parametrize("role", ["owner", "collaborator", "viewer"])
def test_html_present_is_a_regional_inline_presign(monkeypatch, index, role):
    _setup(monkeypatch, index, role=role, deck={"htmlS3Key": HTML_KEY}, query={"purpose": "present"})
    result = index.get_deck_html("d1")
    assert result["expiresIn"] == 14400
    path, query = _regional(result["url"])
    assert path == f"/{HTML_KEY}"
    assert query["response-content-type"] == ["text/html; charset=utf-8"]
    assert query["response-content-disposition"] == ["inline"]
    assert query["X-Amz-Expires"] == ["14400"]


def test_html_download_is_an_attachment(monkeypatch, index):
    _setup(monkeypatch, index, deck={"htmlS3Key": HTML_KEY}, query={"purpose": "download"})
    result = index.get_deck_html("d1")
    assert result["expiresIn"] == 900
    _, query = _regional(result["url"])
    assert query["response-content-disposition"][0].startswith('attachment; filename="Q3 Review.html"')


# --- GET /decks/{id} ---------------------------------------------------------


_OUTLINE = b"- [cover] Cover\n- [body] Body\n"


def test_get_deck_denied_is_403(monkeypatch, index):
    _setup(monkeypatch, index, allowed=False)
    assert index.get_deck("d1") == ({"error": "no access"}, 403)


def test_get_deck_pptx_shape_unchanged(monkeypatch, index):
    _setup(monkeypatch, index, deck={"pptxS3Key": "pptx/d1/out.pptx"}, objects={
        "decks/d1/deck.json": json.dumps({"template": "blank-dark"}).encode(),
        "decks/d1/specs/outline.md": _OUTLINE,
        "decks/d1/slides/cover.json": b"{}",
        "decks/d1/slides/body.json": b"{}",
        "previews/d1/cover_100.webp": b"x",
    })
    result = index.get_deck("d1")
    assert "outputFormat" not in result and "htmlUrl" not in result and "scriptWarnings" not in result
    assert [s["slug"] for s in result["slides"]] == ["cover", "body"]
    assert result["slides"][0]["previewUrl"] == "https://app-origin.example/previews/d1/cover_100.webp"
    assert result["slides"][1]["previewUrl"] is None
    assert result["pptxUrl"] == "https://app-origin.example/pptx/d1/out.pptx"
    assert result["template"] == "blank-dark" and result["isOwner"] is True


def test_get_deck_html_uses_regional_presigns_only(monkeypatch, index):
    preview = "html/d1/preview/cover_100.html"
    _setup(monkeypatch, index, role="viewer", deck={"htmlS3Key": HTML_KEY}, objects={
        "decks/d1/deck.json": json.dumps({"outputFormat": "html", "template": "blank-dark"}).encode(),
        "decks/d1/specs/outline.md": _OUTLINE,
        "decks/d1/slides/cover.html": b"<section></section>",
        "decks/d1/slides/body.html": b"<section></section>",
        preview: b"x",
    })
    result = index.get_deck("d1")
    assert result["outputFormat"] == "html" and result["pptxUrl"] is None and result["defsUrl"] is None
    assert result["slideSize"] == {"width": 1920, "height": 1080}
    assert _regional(result["htmlUrl"])[0] == f"/{HTML_KEY}"
    cover, body = result["slides"]
    assert (cover["slug"], body["slug"]) == ("cover", "body")
    assert _regional(cover["previewUrl"])[0] == f"/{preview}"
    assert body["previewUrl"] is None
    assert result["isOwner"] is False and result["role"] == "viewer"
    assert result["scriptWarnings"] == []


def test_get_deck_html_script_warnings_keep_only_valid_entries(monkeypatch, index):
    _setup(monkeypatch, index, deck={"htmlS3Key": HTML_KEY, "htmlScriptExternal": [
        {"slug": "cover", "kinds": ["navigation", "external-url"]},
        {"slug": "Bad Slug<script>", "kinds": ["popup"]},
        {"slug": "body", "kinds": ["popup", "exfiltrate"]},
        {"slug": "chart_2", "kinds": ["webrtc"]},
        "not-a-dict",
    ]}, objects={
        "decks/d1/deck.json": json.dumps({"outputFormat": "html"}).encode(),
        "decks/d1/specs/outline.md": _OUTLINE,
    })
    assert index.get_deck("d1")["scriptWarnings"] == [
        {"slug": "cover", "kinds": ["navigation", "external-url"]},
        {"slug": "chart_2", "kinds": ["webrtc"]},
    ]


def test_script_warnings_are_capped(index):
    many = [{"slug": f"s{i}", "kinds": ["popup"]} for i in range(250)]
    assert len(index._script_warnings(many)) == 200
    assert index._script_warnings(None) == [] and index._script_warnings("x") == []
