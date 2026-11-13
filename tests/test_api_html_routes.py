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
        self.presigned: list[dict] = []

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def list_objects_v2(self, Bucket, Prefix):
        return {"Contents": [{"Key": k} for k in sorted(self.objects) if k.startswith(Prefix)]}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        self.presigned.append(Params)
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


@pytest.mark.parametrize("role", ["owner", "viewer"])
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


# --- PPTX download URL and GET /decks/{id}/pptx ------------------------------

PPTX_KEY = "pptx/d1/0b0e6c3e-7f6b-4c4c-9a39-1d0f8f5f0a11.pptx"


def test_pptx_denied_is_403_before_reading_the_deck(monkeypatch, index):
    calls = _setup(monkeypatch, index, allowed=False)
    assert index.get_deck_pptx("d1") == ({"error": "no access"}, 403)
    assert calls == [("u1", "d1", "read")]


CF_DOMAIN = "d111111abcdef8.cloudfront.net"
JP_DISPOSITION = (
    "attachment; filename=\"deck.pptx\"; filename*=UTF-8''"
    "%E5%9B%9B%E5%8D%8A%E6%9C%9F%E3%83%AC%E3%83%93%E3%83%A5%E3%83%BC.pptx"
)


@pytest.fixture()
def cf(monkeypatch, index):
    """CloudFront signing configured with a throwaway RSA key; yields its public key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption(),
    ).decode()
    monkeypatch.setattr(index, "CF_DOMAIN", CF_DOMAIN)
    monkeypatch.setattr(index, "CF_KEY_PAIR_ID", "K2JCJMDEHXQW5F")
    monkeypatch.setattr(index, "CF_PRIVATE_KEY_PARAM", "/sdpm/cf-private-key")
    monkeypatch.setattr(index, "_get_cf_private_key", lambda: pem)
    return key.public_key()


def _cf_b64decode(value: str) -> bytes:
    import base64

    return base64.b64decode(value.replace("-", "+").replace("_", "=").replace("~", "/"))


def _verified_cf(url: str, public_key) -> tuple[str, dict]:
    """Check a CloudFront signed URL the way CloudFront does; return (path, origin query)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    base, _, signing = url.rpartition("&Policy=") if "&Policy=" in url else url.rpartition("?Policy=")
    policy_b64, rest = signing.split("&Signature=")
    signature_b64, key_pair = rest.split("&Key-Pair-Id=")
    assert key_pair == "K2JCJMDEHXQW5F"
    policy = _cf_b64decode(policy_b64)
    public_key.verify(_cf_b64decode(signature_b64), policy, padding.PKCS1v15(), hashes.SHA1())  # nosec B303
    statement = json.loads(policy)["Statement"][0]
    assert statement["Resource"] == base  # the origin parameters are inside the signed Resource
    parts = urlsplit(base)
    assert parts.scheme == "https" and parts.netloc == CF_DOMAIN
    return parts.path, parse_qs(parts.query)


@pytest.mark.parametrize("role", ["owner", "viewer"])
def test_pptx_is_a_cloudfront_attachment_named_after_the_deck(monkeypatch, index, cf, role):
    _setup(monkeypatch, index, role=role, deck={"pptxS3Key": PPTX_KEY, "name": "四半期レビュー"})
    result = index.get_deck_pptx("d1")
    assert result["expiresIn"] == 900
    path, query = _verified_cf(result["url"], cf)
    assert path == f"/{PPTX_KEY}"
    assert query == {"response-content-disposition": [JP_DISPOSITION]}


def test_pptx_disposition_is_encoded_once(index, cf):
    url = index._pptx_download_url(PPTX_KEY, "四半期レビュー")
    raw = urlsplit(url).query.split("&Policy=")[0]
    assert raw == (
        "response-content-disposition=attachment%3B%20filename%3D%22deck.pptx%22%3B%20"
        "filename%2A%3DUTF-8%27%27%25E5%259B%259B%25E5%258D%258A%25E6%259C%259F"
        "%25E3%2583%25AC%25E3%2583%2593%25E3%2583%25A5%25E3%2583%25BC.pptx"
    )


def test_pptx_signature_covers_the_disposition(index, cf):
    """Changing the file name in the URL leaves a Resource that no longer matches the request."""
    url = index._pptx_download_url(PPTX_KEY, "Q3 Review")
    tampered = url.replace("Q3%2520Review", "evil", 1)
    assert tampered != url
    with pytest.raises(AssertionError):
        _verified_cf(tampered, cf)


def test_pptx_without_cloudfront_falls_back_to_an_s3_presign(monkeypatch, index):
    _setup(monkeypatch, index)
    assert index._pptx_download_url(PPTX_KEY, "四半期レビュー") == f"https://app-origin.example/{PPTX_KEY}"
    assert index.s3_client.presigned == [
        {"Bucket": BUCKET, "Key": PPTX_KEY, "ResponseContentDisposition": JP_DISPOSITION},
    ]


@pytest.mark.parametrize("key", ["uploads/u1/a.pptx", "pptx/../uploads/a.pptx", "pptx/d1/a.pdf", None])
def test_pptx_url_refuses_other_keys(index, cf, key):
    assert index._pptx_download_url(key, "Deck") is None


def test_previews_stay_unsigned_by_query(index, cf):
    url = index._cf_signed_url("previews/d1/cover_100.webp")
    assert url.startswith(f"https://{CF_DOMAIN}/previews/d1/cover_100.webp?Policy=")
    assert _verified_cf(url, cf) == ("/previews/d1/cover_100.webp", {})


def test_pptx_not_built_is_404(monkeypatch, index):
    _setup(monkeypatch, index)
    assert index.get_deck_pptx("d1") == ({"error": "PPTX not built yet"}, 404)


def test_pptx_of_an_html_deck_is_404(monkeypatch, index):
    _setup(monkeypatch, index, deck={"pptxS3Key": PPTX_KEY, "htmlS3Key": HTML_KEY}, objects={
        "decks/d1/deck.json": json.dumps({"outputFormat": "html"}).encode(),
    })
    assert index.get_deck_pptx("d1")[1] == 404


def test_pptx_refuses_a_key_outside_pptx(monkeypatch, index):
    _setup(monkeypatch, index, deck={"pptxS3Key": "uploads/u1/a.pptx"})
    assert index.get_deck_pptx("d1")[1] == 404


@pytest.mark.parametrize("record, expected", [({"pptxS3Key": PPTX_KEY}, True), ({}, False)])
def test_deck_summary_says_whether_a_pptx_exists_without_a_url(index, record, expected):
    summary = index._deck_summary({"SK": "DECK#d1", **record}, {})
    assert summary["hasPptx"] is expected
    assert "pptxUrl" not in summary


# --- GET /decks/{id} ---------------------------------------------------------


_OUTLINE = b"- [cover] Cover\n- [body] Body\n"


def test_get_deck_denied_is_403(monkeypatch, index):
    _setup(monkeypatch, index, allowed=False)
    assert index.get_deck("d1") == ({"error": "no access"}, 403)


def test_get_deck_pptx_url_is_cloudfront_with_the_name(monkeypatch, index, cf):
    _setup(monkeypatch, index, deck={"pptxS3Key": "pptx/d1/out.pptx"})
    path, query = _verified_cf(index.get_deck("d1")["pptxUrl"], cf)
    assert path == "/pptx/d1/out.pptx"
    assert query["response-content-disposition"] == [
        "attachment; filename=\"Q3 Review.pptx\"; filename*=UTF-8''Q3%20Review.pptx"
    ]


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
    assert index.s3_client.presigned[-1]["ResponseContentDisposition"] == (
        "attachment; filename=\"Q3 Review.pptx\"; filename*=UTF-8''Q3%20Review.pptx"
    )
    assert result["template"] == "blank-dark" and result["isOwner"] is True


def _compose_urls(result) -> dict:
    return {s["slug"]: s.get("composeUrl", "").removeprefix("https://app-origin.example/") for s in result["slides"]}


def test_get_deck_compose_latest_epoch_per_slug_and_legacy_fallback(monkeypatch, index):
    _setup(monkeypatch, index, objects={
        "decks/d1/specs/outline.md": _OUTLINE,
        "decks/d1/slides/cover.json": b"{}",
        "decks/d1/slides/body.json": b"{}",
        "decks/d1/compose/cover_100.json": b"{}",
        "decks/d1/compose/cover_300.json": b"{}",
        "decks/d1/compose/slide_2_50.json": b"{}",
        "decks/d1/compose/defs_100.json": b"{}",
        "decks/d1/compose/defs_200.json": b"{}",
    })
    result = index.get_deck("d1")
    assert _compose_urls(result) == {
        "cover": "decks/d1/compose/cover_300.json",
        "body": "decks/d1/compose/slide_2_50.json",  # legacy numbered compose of slide 2
    }
    assert result["defsUrl"] == "https://app-origin.example/decks/d1/compose/defs_200.json"


def test_get_deck_compose_slug_slide_does_not_take_legacy_numbered_files(monkeypatch, index):
    """Was a prefix match on ``compose/slide_``: slug ``slide`` got ``slide_3_*.json``."""
    _setup(monkeypatch, index, objects={
        "decks/d1/specs/outline.md": b"- [cover] Cover\n- [slide] Slide\n",
        "decks/d1/slides/cover.json": b"{}",
        "decks/d1/slides/slide.json": b"{}",
        "decks/d1/compose/slide_3_500.json": b"{}",
        "decks/d1/compose/slide_100.json": b"{}",
    })
    assert _compose_urls(index.get_deck("d1")) == {"cover": "", "slide": "decks/d1/compose/slide_100.json"}


def test_get_deck_compose_without_outline_does_not_take_a_longer_slug(monkeypatch, index):
    """Was a prefix match on ``compose/intro_``: slug ``intro`` got ``intro_2_*.json``."""
    _setup(monkeypatch, index, objects={
        "decks/d1/slides/intro.json": b"{}",
        "decks/d1/slides/intro_2.json": b"{}",
        "decks/d1/compose/intro_100.json": b"{}",
        "decks/d1/compose/intro_2_900.json": b"{}",
    })
    assert _compose_urls(index.get_deck("d1")) == {
        "intro": "decks/d1/compose/intro_100.json",
        "intro_2": "decks/d1/compose/intro_2_900.json",
    }


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
