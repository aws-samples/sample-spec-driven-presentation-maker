# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""shared/user_library.py, its key helpers in shared/schema.py, and the MCP Runtime
paths that use them (AwsStorage, list_styles / start_style / apply_style).

The Web UI routes of api/index.py are covered in tests/test_api_styles_templates.py.
"""

import importlib.util
import json
import os
from pathlib import Path

import pytest

from sdpm.knowledge.reference import BUNDLED_STYLES_DIR, html_title, merge_style_lists
from shared import schema, user_library
from user_library_fakes import FakeS3, FakeTable, style_html

PPTX = "pptx-bucket"
RESOURCE = "resource-bucket"
_ROOT = Path(__file__).resolve().parents[1]


# --- engine rules ------------------------------------------------------------


def test_html_title_strips_and_ignores_case():
    assert html_title("<html><TITLE>  Report style </TITLE></html>") == "Report style"
    assert html_title("<html><head></head></html>") == ""


def test_merge_style_lists_first_occurrence_wins():
    user = [{"name": "report", "source": "user"}, {"name": "mine", "source": "user"}]
    bundled = [{"name": "minimal", "source": "builtin"}, {"name": "report", "source": "builtin"}]
    merged = merge_style_lists(user, bundled)
    assert [(s["name"], s["source"]) for s in merged] == [
        ("report", "user"), ("mine", "user"), ("minimal", "builtin"),
    ]


# --- keys and names ----------------------------------------------------------


def test_ddb_keys_keep_their_stored_format():
    assert schema.style_pins_key("u1") == {"PK": "USER#u1", "SK": "STYLE_PINS"}
    assert schema.user_template_key("u1", "My deck") == {"PK": "USER#u1", "SK": "TEMPLATE#My deck"}
    assert schema.user_template_sk("x") == "TEMPLATE#x"
    assert schema.builtin_note_key("u1", "blank-dark") == {"PK": "USER#u1", "SK": "BUILTIN_NOTE#blank-dark"}
    assert schema.builtin_template_key("blank-dark") == {"PK": "TEMPLATE#blank-dark", "SK": "META"}
    assert schema.deck_pk("u1") == schema.user_pk("u1") == "USER#u1"


def test_s3_keys_keep_their_layout():
    assert user_library.user_style_key("u1", "mine") == "user-styles/u1/mine.html"
    assert user_library.builtin_style_key("report") == "references/examples/styles/report.html"
    assert user_library.user_template_s3_key("u1", "t") == "user-templates/u1/t.pptx"
    assert user_library.builtin_template_s3_key("blank-dark") == "templates/blank-dark.pptx"


@pytest.mark.parametrize("name", ["report", "my_style-2", "A"])
def test_valid_style_names(name):
    assert user_library.is_valid_style_name(name)


@pytest.mark.parametrize("name", ["", "../u2/x", "a b", "a.html", "a/b", "名前", None, 3, "a\n"])
def test_invalid_style_names(name):
    assert not user_library.is_valid_style_name(name)


# --- styles ------------------------------------------------------------------


def _style_s3() -> FakeS3:
    return FakeS3({
        PPTX: {
            "user-styles/u1/report.html": style_html("My report"),
            "user-styles/u1/mine.html": style_html("Mine"),
            "user-styles/u1/notes.txt": b"ignored",
            "user-styles/u2/other.html": style_html("Other user"),
        },
        RESOURCE: {
            "references/examples/styles/report.html": style_html("Bundled report"),
            "references/examples/styles/minimal.html": style_html("Minimal"),
        },
    })


def test_list_user_styles_reads_titles_of_this_user_only():
    styles = user_library.list_user_styles(_style_s3(), PPTX, "u1")
    assert styles == [
        {"name": "mine", "description": "Mine", "source": "user"},
        {"name": "report", "description": "My report", "source": "user"},
    ]


def test_list_user_styles_with_html():
    styles = user_library.list_user_styles(_style_s3(), PPTX, "u1", include_html=True)
    assert styles[0]["html"] == style_html("Mine").decode()


def test_list_user_styles_tolerates_unreadable_body_without_html():
    s3 = _style_s3()
    real_get = s3.get_object

    def flaky(Bucket, Key):
        if Key.endswith("mine.html"):
            raise OSError("boom")
        return real_get(Bucket=Bucket, Key=Key)

    s3.get_object = flaky
    assert user_library.list_user_styles(s3, PPTX, "u1")[0] == {"name": "mine", "description": "", "source": "user"}
    with pytest.raises(OSError):
        user_library.list_user_styles(s3, PPTX, "u1", include_html=True)


def test_list_builtin_styles():
    styles = user_library.list_builtin_styles(_style_s3(), RESOURCE)
    assert [(s["name"], s["description"], s["source"]) for s in styles] == [
        ("minimal", "Minimal", "builtin"), ("report", "Bundled report", "builtin"),
    ]
    assert all(s["html"] for s in styles)


def test_merge_styles_user_replaces_builtin_of_same_name():
    s3 = _style_s3()
    merged = user_library.merge_styles(
        user_library.list_user_styles(s3, PPTX, "u1"), user_library.list_builtin_styles(s3, RESOURCE),
    )
    assert [(s["name"], s["source"]) for s in merged] == [
        ("mine", "user"), ("report", "user"), ("minimal", "builtin"),
    ]
    assert next(s for s in merged if s["name"] == "report")["description"] == "My report"


# --- icon catalog ------------------------------------------------------------


class _CountingS3(FakeS3):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reads: list[str] = []

    def get_object(self, Bucket, Key):
        self.reads.append(Key)
        if Key == "assets/aws/broken.svg":
            raise OSError("throttled")
        return super().get_object(Bucket, Key)


@pytest.fixture()
def icon_s3(monkeypatch):
    monkeypatch.setattr(user_library, "_icon_cache", {})
    return _CountingS3({RESOURCE: {"assets/material/hub.svg": b"<svg/>", "assets/aws/Arch_X_48.svg": b"<svg id='a'/>"}})


def test_load_catalog_icons_hit_and_miss(icon_s3):
    got = user_library.load_catalog_icons(icon_s3, RESOURCE, {"material/hub", "aws/Arch_X_48", "material/nope"})
    assert got == {"material/hub": b"<svg/>", "aws/Arch_X_48": b"<svg id='a'/>"}
    assert sorted(icon_s3.reads) == ["assets/aws/Arch_X_48.svg", "assets/material/hub.svg", "assets/material/nope.svg"]


def test_load_catalog_icons_caches_hits_and_misses_not_errors(icon_s3):
    ids = {"material/hub", "material/nope", "aws/broken"}
    user_library.load_catalog_icons(icon_s3, RESOURCE, ids)
    icon_s3.reads.clear()
    assert user_library.load_catalog_icons(icon_s3, RESOURCE, ids) == {"material/hub": b"<svg/>"}
    assert icon_s3.reads == ["assets/aws/broken.svg"]


@pytest.mark.parametrize("bad", ["../x", "material/../../secret", "nosource", "a/b/c", ""])
def test_load_catalog_icons_never_queries_malformed_ids(icon_s3, bad):
    assert user_library.load_catalog_icons(icon_s3, RESOURCE, {bad}) == {}
    assert icon_s3.reads == []


# --- pins --------------------------------------------------------------------


def test_style_pins_round_trip():
    table = FakeTable()
    assert user_library.get_style_pins(table, "u1") == []
    user_library.put_style_pins(table, "u1", ["report", "mine"])
    assert table.items[("USER#u1", "STYLE_PINS")] == {
        "PK": "USER#u1", "SK": "STYLE_PINS", "pinned_styles": ["report", "mine"],
    }
    assert user_library.get_style_pins(table, "u1") == ["report", "mine"]
    assert user_library.get_style_pins(table, "u2") == []


# --- templates ---------------------------------------------------------------


def _template_fixture():
    s3 = FakeS3(
        {RESOURCE: {"templates/fresh.pptx": b"f", "templates/stale.pptx": b"s",
                    "templates/new.pptx": b"n", "templates/readme.md": b"x"}},
        etags={(RESOURCE, "templates/fresh.pptx"): '"e1"', (RESOURCE, "templates/stale.pptx"): '"e2"',
               (RESOURCE, "templates/new.pptx"): '"e3"'},
    )
    table = FakeTable([
        {"PK": "TEMPLATE#fresh", "SK": "META", "name": "fresh", "s3ETag": '"e1"',
         "description": "cached", "fonts": {"halfwidth": "Arial"}, "analysisJson": '{"layouts": [1, 2]}'},
        {"PK": "TEMPLATE#stale", "SK": "META", "name": "stale", "s3ETag": '"old"',
         "description": "stale note", "fonts": {"halfwidth": "Old"}, "analysisJson": '{"layouts": [1]}'},
        {"PK": "USER#u1", "SK": "TEMPLATE#mine", "name": "mine", "analysisJson": "{}"},
        {"PK": "USER#u1", "SK": "BUILTIN_NOTE#fresh", "name": "fresh", "description": "my note"},
        {"PK": "USER#u2", "SK": "TEMPLATE#theirs", "name": "theirs"},
    ])
    return s3, table


def test_list_builtin_templates_marks_cache_freshness_by_etag():
    s3, table = _template_fixture()
    result = {t["name"]: t for t in user_library.list_builtin_templates(s3, table, RESOURCE)}
    assert set(result) == {"fresh", "stale", "new"}
    assert result["fresh"]["fresh"] and result["fresh"]["cache"]["description"] == "cached"
    assert not result["stale"]["fresh"] and result["stale"]["cache"]["description"] == "stale note"
    assert not result["new"]["fresh"] and result["new"]["cache"] == {}
    assert result["new"]["s3Key"] == "templates/new.pptx" and result["new"]["s3ETag"] == '"e3"'
    keys = table.batch_requests[0][table.name]["Keys"]
    assert {"PK": "TEMPLATE#new", "SK": "META"} in keys


def test_list_builtin_templates_without_objects_skips_ddb():
    table = FakeTable()
    assert user_library.list_builtin_templates(FakeS3(), table, RESOURCE) == []
    assert table.batch_requests == []


def test_builtin_template_cache_item():
    item = user_library.builtin_template_cache_item("t", "templates/t.pptx", '"e"', {"fonts": {"a": "b"}, "layouts": []})
    assert item == {
        "PK": "TEMPLATE#t", "SK": "META", "name": "t", "s3Key": "templates/t.pptx", "s3ETag": '"e"',
        "fonts": {"a": "b"}, "analysisJson": json.dumps({"fonts": {"a": "b"}, "layouts": []}),
    }


def test_user_templates_and_notes_are_per_user():
    _, table = _template_fixture()
    assert [t["name"] for t in user_library.list_user_templates(table, "u1")] == ["mine"]
    assert user_library.list_builtin_template_notes(table, "u1") == {"fresh": "my note"}
    assert user_library.list_builtin_template_notes(table, "u2") == {}


@pytest.mark.parametrize("raw, expected", [
    ("", {}), ("{}", {}), (None, {}), ('{"layouts": [1]}', {"layouts": [1]}), ({"layouts": []}, {"layouts": []}),
])
def test_parse_analysis(raw, expected):
    assert user_library.parse_analysis(raw) == expected


# --- AwsStorage (MCP Runtime) ------------------------------------------------


def _aws_storage(s3, table):
    from storage.aws import AwsStorage

    return AwsStorage(table, s3, PPTX, RESOURCE)


def test_aws_storage_list_templates_keeps_its_shape():
    s3, table = _template_fixture()
    result = {t["name"]: t for t in _aws_storage(s3, table).list_templates()}
    assert result["fresh"] == {
        "name": "fresh", "s3Key": "templates/fresh.pptx", "description": "cached",
        "fonts": {"halfwidth": "Arial"}, "analysisJson": '{"layouts": [1, 2]}',
    }
    # A stale cache row still provides description and fonts, never the analysis
    assert result["stale"] == {
        "name": "stale", "s3Key": "templates/stale.pptx", "description": "stale note",
        "fonts": {"halfwidth": "Old"}, "analysisJson": "{}",
    }
    assert result["new"] == {"name": "new", "s3Key": "templates/new.pptx", "description": "", "fonts": {}, "analysisJson": "{}"}


def test_aws_storage_pins_user_styles_and_templates():
    s3, table = _template_fixture()
    s3.buckets.update(_style_s3().buckets)
    storage = _aws_storage(s3, table)
    storage.put_style_pins("u1", ["report"])
    assert storage.get_style_pins("u1") == ["report"]
    assert [s["name"] for s in storage.list_user_styles("u1")] == ["mine", "report"]
    assert [t["name"] for t in storage.list_user_templates("u1")] == ["mine"]
    assert storage.get_builtin_template_notes("u1") == {"fresh": "my note"}

    storage.put_user_template("u1", "added", b"pptx", {"description": "d"})
    assert s3.buckets[PPTX]["user-templates/u1/added.pptx"] == b"pptx"
    assert table.items[("USER#u1", "TEMPLATE#added")]["s3Key"] == "user-templates/u1/added.pptx"
    storage.rename_user_template("u1", "added", "renamed")
    assert ("USER#u1", "TEMPLATE#added") not in table.items
    assert table.items[("USER#u1", "TEMPLATE#renamed")]["s3Key"] == "user-templates/u1/renamed.pptx"
    assert "user-templates/u1/renamed.pptx" in s3.buckets[PPTX]


# --- MCP tools: one entry per style name, user first --------------------------

os.environ.setdefault("DECKS_TABLE", "test-table")
os.environ.setdefault("PPTX_BUCKET", "test-pptx")
os.environ.setdefault("RESOURCE_BUCKET", "test-resource")
_spec = importlib.util.spec_from_file_location(
    "remote_server_user_library_under_test", _ROOT / "servers" / "remote" / "server.py",
)
remote_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remote_server)

_BUNDLED_REPORT = (BUNDLED_STYLES_DIR / "report.html").read_text(encoding="utf-8")
_USER_REPORT = _BUNDLED_REPORT.replace("<title>", "<title>My own ", 1)


@pytest.fixture()
def remote(monkeypatch):
    s3 = FakeS3({PPTX: {
        "user-styles/u1/report.html": _USER_REPORT.encode(),
        "decks/d1/deck.json": json.dumps({"slides": []}).encode(),
    }})
    table = FakeTable()
    monkeypatch.setattr(remote_server, "_storage", _aws_storage(s3, table))
    monkeypatch.setattr(remote_server, "_check_deck_access", lambda *a, **k: None)
    monkeypatch.setattr(remote_server, "_get_user_id", lambda: "u1")
    return s3


def test_mcp_list_styles_lists_a_shadowed_name_once_as_the_user_style(remote):
    styles = json.loads(remote_server.list_styles(include_all=True))["styles"]
    reports = [s for s in styles if s["name"] == "report"]
    assert len(reports) == 1
    assert reports[0]["source"] == "user"
    assert reports[0]["description"] == html_title(_USER_REPORT)
    # Every other bundled style is still listed
    bundled = {p.stem for p in BUNDLED_STYLES_DIR.glob("*.html")}
    assert {s["name"] for s in styles} == bundled
    assert len(styles) == len(bundled)


def test_mcp_start_style_catalogue_and_base_use_the_user_style(remote):
    result = json.loads(remote_server.start_style(base="report"))
    assert [s["source"] for s in result["styles"] if s["name"] == "report"] == ["user"]
    assert result["base"]["html"] == _USER_REPORT


def test_mcp_apply_style_still_applies_the_user_style(remote):
    result = json.loads(remote_server.apply_style(deck_id="d1", style="report"))
    assert result["applied"] == "report"
    assert remote.buckets[PPTX]["decks/d1/specs/art-direction.html"] == _USER_REPORT.encode()


def test_mcp_apply_style_falls_back_to_the_bundled_style(remote):
    del remote.buckets[PPTX]["user-styles/u1/report.html"]
    remote_server.apply_style(deck_id="d1", style="report")
    assert remote.buckets[PPTX]["decks/d1/specs/art-direction.html"] == _BUNDLED_REPORT.encode()
