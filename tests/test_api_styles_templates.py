# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Route-level tests for the style and template endpoints of api/index.py.

Same harness as tests/test_api_html_routes.py (its ``index`` fixture imports the
module with a stand-in for aws_lambda_powertools); routes are called directly with
the in-memory S3 client and DynamoDB table from tests/user_library_fakes.py.
"""

import json
import os
from pathlib import Path

import pytest

from test_api_html_routes import BUCKET, _Event, index  # noqa: F401 — index is a fixture
from user_library_fakes import FakeS3, FakeTable, style_html

RESOURCE = "sdpm-resource-test"
_TEMPLATE = Path(__file__).resolve().parents[1] / "sdpm" / "templates" / "blank-dark.pptx"


class _JsonEvent(_Event):
    def __init__(self, user_id: str, body: dict | None = None):
        super().__init__(user_id)
        self.json_body = body or {}


@pytest.fixture()
def api(index, monkeypatch):  # noqa: F811
    s3 = FakeS3({
        BUCKET: {
            "user-styles/u1/report.html": style_html("My report"),
            "user-styles/u1/mine.html": style_html("Mine"),
            "user-styles/u2/theirs.html": style_html("Theirs"),
        },
        RESOURCE: {
            "references/examples/styles/report.html": style_html("Bundled report"),
            "references/examples/styles/minimal.html": style_html("Minimal"),
            "templates/blank-dark.pptx": _TEMPLATE.read_bytes(),
        },
    }, etags={(RESOURCE, "templates/blank-dark.pptx"): '"e1"'})
    table = FakeTable()
    monkeypatch.setattr(index, "s3_client", s3)
    monkeypatch.setattr(index, "table", table)
    monkeypatch.setattr(index, "RESOURCE_BUCKET", RESOURCE)
    monkeypatch.setattr(index, "_styles_cache", None)
    index.app.current_event = _JsonEvent("u1")
    index.s3, index.ddb = s3, table
    return index


def _call(api, fn, *args, user="u1", body=None):
    api.app.current_event = _JsonEvent(user, body)
    return fn(*args)


# --- GET /styles -------------------------------------------------------------


def test_list_styles_one_entry_per_name_user_first(api):
    styles = _call(api, api.list_styles)["styles"]
    assert [(s["name"], s["source"]) for s in styles] == [
        ("mine", "user"), ("report", "user"), ("minimal", "builtin"),
    ]
    report = styles[1]
    assert report == {
        "name": "report", "description": "My report", "html": style_html("My report").decode(),
        "source": "user", "pinned": False,
    }


def test_list_styles_without_user_styles_lists_bundled(api):
    styles = _call(api, api.list_styles, user="u3")["styles"]
    assert [(s["name"], s["description"], s["source"]) for s in styles] == [
        ("minimal", "Minimal", "builtin"), ("report", "Bundled report", "builtin"),
    ]


def test_list_styles_user_listing_failure_still_lists_bundled(api, monkeypatch):
    def broken(*a, **k):
        raise OSError("S3 down")

    monkeypatch.setattr(api.user_library, "list_user_styles", broken)
    styles = _call(api, api.list_styles)["styles"]
    assert {s["source"] for s in styles} == {"builtin"}


def test_list_styles_caches_bundled_styles_only(api):
    _call(api, api.list_styles)
    api.s3.buckets[RESOURCE].pop("references/examples/styles/minimal.html")
    api.s3.buckets[BUCKET]["user-styles/u1/new.html"] = style_html("New")
    names = [s["name"] for s in _call(api, api.list_styles)["styles"]]
    assert "minimal" in names and "new" in names


def test_pin_persists_and_marks_listing(api):
    assert _call(api, api.pin_style, body={"name": "report", "pinned": True}) == {
        "ok": True, "pinned_styles": ["report"],
    }
    assert _call(api, api.pin_style, body={"name": "minimal", "pinned": True})["pinned_styles"] == ["report", "minimal"]
    assert api.ddb.items[("USER#u1", "STYLE_PINS")]["pinned_styles"] == ["report", "minimal"]
    pinned = {s["name"]: s["pinned"] for s in _call(api, api.list_styles)["styles"]}
    assert pinned == {"mine": False, "report": True, "minimal": True}

    assert _call(api, api.pin_style, body={"name": "report", "pinned": False})["pinned_styles"] == ["minimal"]
    # Pins are per user
    assert not any(s["pinned"] for s in _call(api, api.list_styles, user="u2")["styles"])


@pytest.mark.parametrize("name", ["", "../u2/x", "a b"])
def test_pin_rejects_invalid_names(api, name):
    assert _call(api, api.pin_style, body={"name": name, "pinned": True}) == ({"error": "Invalid style name"}, 400)
    assert api.ddb.items == {}


def test_get_style_user_first_then_builtin(api):
    assert _call(api, api.get_style, "report")["source"] == "user"
    assert _call(api, api.get_style, "minimal") == {
        "name": "minimal", "fullHtml": style_html("Minimal").decode(), "source": "builtin",
    }
    assert _call(api, api.get_style, "nope")[1] == 404
    assert _call(api, api.get_style, "../x") == ({"error": "Invalid style name"}, 400)


def test_save_rename_delete_user_style_keep_pins_in_step(api):
    assert _call(api, api.save_user_style, body={"name": "fresh", "html": "<title>F</title>"}) == {"saved": "fresh"}
    assert api.s3.buckets[BUCKET]["user-styles/u1/fresh.html"] == b"<title>F</title>"
    _call(api, api.pin_style, body={"name": "fresh", "pinned": True})

    assert _call(api, api.rename_user_style, "fresh", body={"newName": "renamed"}) == {
        "renamed": {"from": "fresh", "to": "renamed"},
    }
    assert "user-styles/u1/fresh.html" not in api.s3.buckets[BUCKET]
    assert api.ddb.items[("USER#u1", "STYLE_PINS")]["pinned_styles"] == ["renamed"]
    assert _call(api, api.rename_user_style, "renamed", body={"newName": "mine"})[1] == 409

    assert _call(api, api.delete_user_style, "renamed") == {"deleted": "renamed"}
    assert "user-styles/u1/renamed.html" not in api.s3.buckets[BUCKET]
    assert api.ddb.items[("USER#u1", "STYLE_PINS")]["pinned_styles"] == []


@pytest.mark.parametrize("call", [
    lambda api: _call(api, api.save_user_style, body={"name": "a/b", "html": "x"}),
    lambda api: _call(api, api.delete_user_style, "a b"),
    lambda api: _call(api, api.rename_user_style, "..", body={"newName": "ok"}),
])
def test_style_writes_reject_invalid_names(api, call):
    assert call(api) == ({"error": "Invalid style name"}, 400)


def test_rename_rejects_invalid_new_name(api):
    assert _call(api, api.rename_user_style, "mine", body={"newName": "a.b"}) == ({"error": "Invalid new name"}, 400)


# --- GET /templates ----------------------------------------------------------


def test_list_templates_analyzes_uncached_builtin_once_and_cleans_up(api, monkeypatch):
    first = _call(api, api.list_templates)["templates"]
    assert len(first) == 1
    builtin = first[0]
    assert builtin["name"] == "blank-dark" and builtin["source"] == "builtin"
    assert builtin["layout_count"] > 0 and builtin["theme_colors"] and builtin["fonts"]

    row = api.ddb.items[("TEMPLATE#blank-dark", "META")]
    assert row["s3ETag"] == '"e1"' and row["s3Key"] == "templates/blank-dark.pptx"
    # The download went to a temporary directory that no longer exists
    (_, _, filename), = api.s3.downloads
    assert not os.path.exists(os.path.dirname(filename))

    # Second call is served from the cache (no new download), same payload
    assert _call(api, api.list_templates)["templates"] == first
    assert len(api.s3.downloads) == 1


def test_list_templates_reanalyzes_when_etag_changes(api):
    _call(api, api.list_templates)
    api.s3.etags[(RESOURCE, "templates/blank-dark.pptx")] = '"e2"'
    _call(api, api.list_templates)
    assert len(api.s3.downloads) == 2
    assert api.ddb.items[("TEMPLATE#blank-dark", "META")]["s3ETag"] == '"e2"'


def test_list_templates_cached_row_note_and_user_templates(api):
    api.ddb.put_item(Item={
        "PK": "TEMPLATE#blank-dark", "SK": "META", "name": "blank-dark", "s3ETag": '"e1"',
        "description": "Shared", "fonts": {"halfwidth": "Arial"},
        "analysisJson": json.dumps({"layouts": [1, 2, 3], "theme_colors": {"accent1": "#fff"}}),
    })
    api.ddb.put_item(Item={"PK": "USER#u1", "SK": "BUILTIN_NOTE#blank-dark", "name": "blank-dark", "description": "My note"})
    api.ddb.put_item(Item={
        "PK": "USER#u1", "SK": "TEMPLATE#Mine", "name": "Mine", "description": "d",
        "fonts": {"halfwidth": "Meiryo"}, "analysisJson": json.dumps({"layouts": [1], "theme_colors": {"dk1": "#000"}}),
    })
    api.ddb.put_item(Item={"PK": "USER#u2", "SK": "TEMPLATE#Theirs", "name": "Theirs"})

    assert _call(api, api.list_templates) == {"templates": [
        {"name": "blank-dark", "source": "builtin", "description": "My note",
         "theme_colors": {"accent1": "#fff"}, "fonts": {"halfwidth": "Arial"}, "layout_count": 3},
        {"name": "Mine", "source": "user", "description": "d",
         "theme_colors": {"dk1": "#000"}, "fonts": {"halfwidth": "Meiryo"}, "layout_count": 1},
    ]}
    assert api.s3.downloads == []
    # Without a note the shared description shows
    assert _call(api, api.list_templates, user="u2")["templates"][0]["description"] == "Shared"


def test_list_templates_without_resource_bucket_lists_user_templates_only(api, monkeypatch):
    monkeypatch.setattr(api, "RESOURCE_BUCKET", "")
    api.ddb.put_item(Item={"PK": "USER#u1", "SK": "TEMPLATE#Mine", "name": "Mine"})
    assert [t["name"] for t in _call(api, api.list_templates)["templates"]] == ["Mine"]


# --- user templates ----------------------------------------------------------


def test_upload_user_template_analyzes_in_a_temporary_directory(api):
    api.s3.buckets[BUCKET]["user-templates/u1/Brand deck.pptx"] = _TEMPLATE.read_bytes()
    assert _call(api, api.upload_user_template, body={"name": "Brand deck", "description": "ours"}) == {
        "uploaded": "Brand deck",
    }
    item = api.ddb.items[("USER#u1", "TEMPLATE#Brand deck")]
    assert item["s3Key"] == "user-templates/u1/Brand deck.pptx" and item["description"] == "ours"
    assert json.loads(item["analysisJson"])["layouts"]
    (_, _, filename), = api.s3.downloads
    assert not os.path.exists(os.path.dirname(filename))

    listed = [t for t in _call(api, api.list_templates)["templates"] if t["source"] == "user"]
    assert [t["name"] for t in listed] == ["Brand deck"] and listed[0]["layout_count"] > 0


def test_upload_user_template_requires_the_object(api):
    assert _call(api, api.upload_user_template, body={"name": "Missing"})[1] == 400
    assert api.ddb.items == {}


def test_presign_rejects_duplicates(api):
    api.ddb.put_item(Item={"PK": "USER#u1", "SK": "TEMPLATE#Mine", "name": "Mine"})
    assert _call(api, api.presign_template_upload, body={"name": "Mine"})[1] == 409
    ok = _call(api, api.presign_template_upload, body={"name": "Other"})
    assert ok["s3Key"] == "user-templates/u1/Other.pptx"


def test_rename_describe_delete_user_template(api):
    api.s3.buckets[BUCKET]["user-templates/u1/Mine.pptx"] = b"pptx"
    api.ddb.put_item(Item={"PK": "USER#u1", "SK": "TEMPLATE#Mine", "name": "Mine", "s3Key": "user-templates/u1/Mine.pptx"})

    assert _call(api, api.patch_user_template, "Mine", body={"newName": "Ours"}) == {"renamed": {"from": "Mine", "to": "Ours"}}
    assert ("USER#u1", "TEMPLATE#Mine") not in api.ddb.items
    assert api.ddb.items[("USER#u1", "TEMPLATE#Ours")]["s3Key"] == "user-templates/u1/Ours.pptx"
    assert api.s3.buckets[BUCKET]["user-templates/u1/Ours.pptx"] == b"pptx"

    assert _call(api, api.patch_user_template, "Ours", body={"description": "new"}) == {"updated": "Ours", "description": "new"}
    assert api.ddb.items[("USER#u1", "TEMPLATE#Ours")]["description"] == "new"

    assert _call(api, api.delete_user_template, "Ours") == {"deleted": "Ours"}
    assert ("USER#u1", "TEMPLATE#Ours") not in api.ddb.items
    assert "user-templates/u1/Ours.pptx" not in api.s3.buckets[BUCKET]
    assert _call(api, api.delete_user_template, "Ours")[1] == 404


def test_builtin_note_set_and_clear(api):
    assert _call(api, api.patch_builtin_template_note, "blank-dark", body={"description": " Mine "}) == {
        "updated": "blank-dark", "description": "Mine",
    }
    assert api.ddb.items[("USER#u1", "BUILTIN_NOTE#blank-dark")]["description"] == "Mine"
    _call(api, api.patch_builtin_template_note, "blank-dark", body={"description": ""})
    assert ("USER#u1", "BUILTIN_NOTE#blank-dark") not in api.ddb.items
    assert _call(api, api.patch_builtin_template_note, "nope", body={"description": "x"})[1] == 404


def test_download_template_user_first_then_builtin(api):
    api.s3.buckets[BUCKET]["user-templates/u1/blank-dark.pptx"] = b"mine"
    assert f"/{BUCKET}/user-templates/u1/blank-dark.pptx" in _call(api, api.download_template, "blank-dark")["downloadUrl"]
    assert f"/{RESOURCE}/templates/blank-dark.pptx" in _call(api, api.download_template, "blank-dark", user="u2")["downloadUrl"]
    assert _call(api, api.download_template, "nope")[1] == 404
