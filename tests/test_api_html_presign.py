# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for api/html_presign.py — presigned S3 URLs for HTML deck artifacts.

api/index.py itself is not importable here (aws_lambda_powertools is not a dev
dependency), so the endpoint's decisions live in html_presign and are tested here.
"""

import re
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import pytest

from api.html_presign import (
    DEFAULT_SLIDE_SIZE,
    PURPOSES,
    VIEW_EXPIRY,
    html_presign_client,
    html_slide_slugs,
    is_html_deck,
    presign_params,
    presigned_html_url,
    safe_download_name,
    slide_size,
)
from shared.html_artifacts import build_html_preview_key_map, output_key, preview_key

_REPO = Path(__file__).resolve().parent.parent
BUCKET = "sdpm-pptx-bucket"
KEY = "html/deck-1/0b0e6c3e-7f6b-4c4c-9a39-1d0f8f5f0a11.html"


# --- presign_params ------------------------------------------------------------


def test_purposes_and_view_expiry():
    assert PURPOSES == {"present": 14400, "download": 900}
    assert VIEW_EXPIRY == 900


@pytest.mark.parametrize("purpose, expires", [("view", 900), ("present", 14400)])
def test_inline_purposes(purpose, expires):
    params, got = presign_params(BUCKET, KEY, purpose, "Deck")
    assert got == expires
    assert params == {
        "Bucket": BUCKET,
        "Key": KEY,
        "ResponseContentType": "text/html; charset=utf-8",
        "ResponseContentDisposition": "inline",
    }


def test_download_is_attachment_with_ascii_and_utf8_names():
    params, expires = presign_params(BUCKET, KEY, "download", "Q3 Review")
    assert expires == 900
    assert params["ResponseContentType"] == "text/html; charset=utf-8"
    assert params["ResponseContentDisposition"] == (
        "attachment; filename=\"Q3 Review.html\"; filename*=UTF-8''Q3%20Review.html"
    )


def test_download_japanese_name():
    params, _ = presign_params(BUCKET, KEY, "download", "営業資料 2026")
    disposition = params["ResponseContentDisposition"]
    assert disposition.isascii()
    assert 'filename="2026.html"' in disposition
    assert f"filename*=UTF-8''{quote('営業資料 2026.html', safe='')}" in disposition


def test_download_all_non_ascii_name_falls_back_to_deck():
    params, _ = presign_params(BUCKET, KEY, "download", "資料")
    assert 'filename="deck.html"' in params["ResponseContentDisposition"]


@pytest.mark.parametrize("purpose", ["", "edit", "PRESENT", None])
def test_unknown_purpose_raises(purpose):
    with pytest.raises(ValueError):
        presign_params(BUCKET, KEY, purpose, "Deck")


@pytest.mark.parametrize("key", [
    "uploads/u1/file.pdf",
    "uploads/u1/evil.html",
    "previews/deck-1/intro_1.html",
    "decks/deck-1/slides/intro.html",
    "html/deck-1/../../uploads/x.html",
    "html/deck-1/output.txt",
    "",
    None,
])
def test_only_html_artifact_keys_are_signed(key):
    with pytest.raises(ValueError):
        presign_params(BUCKET, key, "view")


# --- safe_download_name ------------------------------------------------------------


@pytest.mark.parametrize("name, expected", [
    ("Deck", "Deck.html"),
    ("deck.html", "deck.html"),
    ("Deck.HTML", "Deck.html"),
    ("", "deck.html"),
    (None, "deck.html"),
    ("...", "deck.html"),
    ("../../etc/passwd", "etcpasswd.html"),
    ('a"b\'c\\d/e', "abcde.html"),
    ("line\r\nbreak\tand\x00nul", "linebreakandnul.html"),
    ("bidi\u202eoverride\u200b", "bidioverride.html"),
    ("  spaced   out  ", "spaced out.html"),
    ("営業資料", "営業資料.html"),
])
def test_safe_download_name(name, expected):
    assert safe_download_name(name) == expected


def test_safe_download_name_is_bounded():
    assert len(safe_download_name("x" * 1000)) <= 125


def test_disposition_header_never_breaks_out():
    params, _ = presign_params(BUCKET, KEY, "download", 'x"; filename="evil.exe\r\nSet-Cookie: a=b')
    disposition = params["ResponseContentDisposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert disposition.count('"') == 2
    assert 'filename="x; filename=evil.exeSet-Cookie: a=b.html"' in disposition


# --- signed URL on the regional S3 endpoint --------------------------------------


@pytest.fixture()
def presign_client(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    return html_presign_client("ap-northeast-1")


@pytest.mark.parametrize("purpose", ["present", "download"])
def test_presigned_url_is_sigv4_on_regional_bucket_host(presign_client, purpose):
    url, expires = presigned_html_url(presign_client, BUCKET, KEY, purpose, "Deck")
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert parts.scheme == "https"
    assert parts.netloc == f"{BUCKET}.s3.ap-northeast-1.amazonaws.com"
    assert parts.path == f"/{KEY}"
    assert "cloudfront" not in url
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-Expires"] == [str(PURPOSES[purpose])]
    assert expires == PURPOSES[purpose]
    assert query["response-content-type"] == ["text/html; charset=utf-8"]
    disposition = query["response-content-disposition"][0]
    assert disposition.startswith("attachment;" if purpose == "download" else "inline")
    assert "/ap-northeast-1/s3/aws4_request" in query["X-Amz-Credential"][0]


def test_view_url_expiry(presign_client):
    url, expires = presigned_html_url(presign_client, BUCKET, KEY, "view")
    assert expires == VIEW_EXPIRY
    assert parse_qs(urlsplit(url).query)["X-Amz-Expires"] == ["900"]


# --- key layout round trip with shared.html_artifacts -----------------------------


def test_output_key_is_signable():
    params, _ = presign_params(BUCKET, output_key("deck-1"), "present")
    assert re.fullmatch(r"html/deck-1/[0-9a-f-]{36}\.html", params["Key"])


def test_preview_key_map_round_trip():
    keys = [
        preview_key("deck-1", "intro", 100),
        preview_key("deck-1", "intro", 250),
        preview_key("deck-1", "agenda", 7),
        "html/deck-1/preview/notes.txt",
        "html/deck-1/abcd.html",
    ]
    key_map = build_html_preview_key_map(keys)
    assert key_map == {
        "intro": "html/deck-1/preview/intro_250.html",
        "agenda": "html/deck-1/preview/agenda_7.html",
    }
    for key in key_map.values():
        params, expires = presign_params(BUCKET, key, "view")
        assert params["Key"] == key and expires == VIEW_EXPIRY


# --- deck.json helpers --------------------------------------------------------------


@pytest.mark.parametrize("deck_json, expected", [
    ({"outputFormat": "html"}, True),
    ({"outputFormat": "pptx"}, False),
    ({}, False),
    ({"outputFormat": None}, False),
    ({"outputFormat": "HTML"}, False),
    ([], False),
    (None, False),
])
def test_is_html_deck(deck_json, expected):
    assert is_html_deck(deck_json) is expected


@pytest.mark.parametrize("deck_json, expected", [
    ({"slideSize": {"width": 1280, "height": 720, "ptPerPx": 0.75}}, {"width": 1280, "height": 720}),
    ({"slideSize": {"width": 1024}}, {"width": 1024, "height": 1080}),
    ({"slideSize": {"width": -1, "height": "x"}}, DEFAULT_SLIDE_SIZE),
    ({"slideSize": {"width": True, "height": 0}}, DEFAULT_SLIDE_SIZE),
    ({"slideSize": "16:9"}, DEFAULT_SLIDE_SIZE),
    ({}, DEFAULT_SLIDE_SIZE),
    (None, DEFAULT_SLIDE_SIZE),
])
def test_slide_size(deck_json, expected):
    assert slide_size(deck_json) == expected


def test_html_slide_slugs_keeps_outline_order_and_existing_slides():
    keys = [
        "decks/d1/slides/agenda.html",
        "decks/d1/slides/intro.html",
        "decks/d1/slides/intro.json",
        "decks/d1/slides/sub/x.html",
    ]
    assert html_slide_slugs(["intro", "missing", "agenda"], keys, "d1") == ["intro", "agenda"]


def test_html_slide_slugs_falls_back_to_listed_stems():
    keys = ["decks/d1/slides/a.html", "decks/d1/slides/b.html", "decks/d1/slides/c.json"]
    assert html_slide_slugs([], keys, "d1") == ["a", "b"]


# --- serving boundaries (static guards on infra + api source) --------------------


def test_html_prefix_has_no_cloudfront_behaviour_or_oac_grant():
    web_ui = (_REPO / "infra" / "lib" / "web-ui-stack.ts").read_text(encoding="utf-8")
    data = (_REPO / "infra" / "lib" / "data-stack.ts").read_text(encoding="utf-8")
    patterns = re.findall(r'PathPattern:\s*"([^"]+)"', web_ui)
    assert patterns and not any(p.startswith("html") for p in patterns)
    assert "/html/" not in data


def test_template_html_cache_lifecycle_rule():
    data = (_REPO / "infra" / "lib" / "data-stack.ts").read_text(encoding="utf-8")
    rule = re.search(r'prefix:\s*"template-html-cache/",(.*?)\}', data, re.S)
    assert rule, "template-html-cache/ lifecycle rule missing"
    assert "expiration: cdk.Duration.days(30)" in rule.group(1)
    assert "noncurrentVersionExpiration: cdk.Duration.days(7)" in rule.group(1)


def test_api_signs_html_only_with_regional_client():
    src = (_REPO / "api" / "index.py").read_text(encoding="utf-8")
    body = src.split("def _html_presigned", 1)[1].split("\ndef ", 1)[0]
    assert "html_s3_client" in body
    assert "preview_url(" not in body and "_cf_signed_url(" not in body
    assert '@app.get("/decks/<deck_id>/html")' in src
