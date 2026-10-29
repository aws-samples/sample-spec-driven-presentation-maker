# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Remote MCP server: HTML decks (init, start_composing, run_python, generate_pptx,
get_preview, template conversion cache on S3)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sdpm import api
from shared.html_artifacts import HTML_CONTENT_TYPE, TEMPLATE_CACHE_PREFIX
from tools import html_deck, template_html_cache
from tools import init as init_mod
from tools import sandbox as sandbox_mod

_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE = _ROOT / "sdpm" / "templates" / "blank-dark.pptx"

os.environ.setdefault("DECKS_TABLE", "test-table")
os.environ.setdefault("PPTX_BUCKET", "test-pptx")
os.environ.setdefault("RESOURCE_BUCKET", "test-resource")

_spec = importlib.util.spec_from_file_location("remote_server_html_under_test", _ROOT / "servers" / "remote" / "server.py")
remote_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remote_server)

SLIDES = {
    "cover": '<section data-layout="Title Slide"><h1 data-ph="title">Hello</h1>'
             '<aside class="notes">Say hi</aside></section>',
    "body": '<section data-layout="Title Only"><h1 data-ph="title">Claim</h1><p>Point</p></section>',
}
_OUTLINE = "# Remote deck\n\n## S\n" + "".join(
    f"- [{slug}] {slug}\n  - body: b\n  - visual: v\n  - evidence: e\n" for slug in SLIDES
)
_HTML_KEY = re.compile(r"^html/d1/[0-9a-f-]{36}\.html$")
_PREVIEW_KEY = re.compile(r"^html/d1/preview/([a-z0-9-]+)_(\d+)\.html$")


class FakeStorage:
    """Dict-backed stand-in for AwsStorage (pptx bucket + resource bucket + deck record)."""

    pptx_bucket = "test-pptx"

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        self.resource: dict[str, bytes] = {"templates/blank-dark.pptx": _TEMPLATE.read_bytes()}
        self.record: dict = {"deckId": "d1", "name": "Remote deck", "visibility": "private"}
        self.updates: list[dict] = []
        self.deleted: list[str] = []
        self.if_absent: list[str] = []
        self._s3 = MagicMock()

    # deck record
    def get_deck(self, deck_id, user_id):
        return dict(self.record) if deck_id == "d1" else None

    def update_deck(self, deck_id, user_id, updates):
        self.updates.append(dict(updates))
        old = {k: self.record[k] for k in updates if k in self.record}
        for k, v in updates.items():
            if v is None:
                self.record.pop(k, None)
            else:
                self.record[k] = v
        return old

    # deck.json
    def get_deck_json(self, deck_id):
        return json.loads(self.objects[f"decks/{deck_id}/deck.json"])

    def put_deck_json(self, deck_id, data):
        self.objects[f"decks/{deck_id}/deck.json"] = json.dumps(data).encode()

    # objects
    def list_files(self, prefix, bucket=""):
        source = self.objects if bucket == self.pptx_bucket else self.resource
        return sorted(k for k in source if k.startswith(prefix))

    def download_file_from_pptx_bucket(self, key):
        if key not in self.objects:
            raise FileNotFoundError(key)
        return self.objects[key]

    def download_file(self, key):
        if key not in self.resource:
            raise FileNotFoundError(key)
        return self.resource[key]

    def upload_file(self, key, data, content_type="", tagging=""):
        self.objects[key] = data
        self.content_types[key] = content_type

    def upload_file_if_absent(self, key, data, content_type="", checksum_sha256="", tagging=""):
        self.if_absent.append(key)
        if key in self.objects:
            return False
        self.upload_file(key, data, content_type)
        return True

    def delete_object_keys(self, keys):
        for key in keys:
            self.deleted.append(key)
            self.objects.pop(key, None)

    # templates
    def list_templates(self):
        return [{"name": "blank-dark", "s3Key": "templates/blank-dark.pptx"}]

    def get_user_template_metadata(self, user_id, name):
        return None

    def list_user_templates(self, user_id):
        return []

    def html_keys(self):
        return [k for k in self.objects if _HTML_KEY.match(k)]

    def preview_keys(self):
        return sorted(k for k in self.objects if _PREVIEW_KEY.match(k))


def _seed_html_deck(storage: FakeStorage, tmp_path: Path, slides: dict | None = None) -> None:
    deck = tmp_path / "local-deck"
    api.init("t", output_dir=deck, output_format="html")
    assert api.apply_style(deck, style="typographic", template="blank-dark")["status"] == "ok"
    (deck / "specs" / "outline.md").write_text(_OUTLINE, encoding="utf-8")
    (deck / "specs" / "brief.md").write_text("# Brief\n", encoding="utf-8")
    (deck / "deck.css").write_text(".card { padding: 8px; }\n", encoding="utf-8")
    for slug, text in (SLIDES if slides is None else slides).items():
        (deck / "slides" / f"{slug}.html").write_text(text, encoding="utf-8")
    for path in deck.rglob("*"):
        if path.is_file():
            storage.objects[f"decks/d1/{path.relative_to(deck).as_posix()}"] = path.read_bytes()


@pytest.fixture()
def storage(tmp_path):
    s = FakeStorage()
    _seed_html_deck(s, tmp_path)
    return s


@pytest.fixture()
def cache_root(tmp_path, monkeypatch):
    root = tmp_path / "template-cache"
    monkeypatch.setattr(template_html_cache, "CACHE_ROOT", root)
    return root


@pytest.fixture()
def server(storage, cache_root, monkeypatch):
    monkeypatch.setattr(remote_server, "_storage", storage)
    monkeypatch.setattr(remote_server, "_check_deck_access", lambda *a, **k: None)
    monkeypatch.setattr(remote_server, "_get_user_id", lambda: "user1")
    monkeypatch.setattr(remote_server, "_get_kb_sync", lambda: None)
    return remote_server


def _sandbox(monkeypatch, changed: list[str]):
    monkeypatch.setattr(
        remote_server.sandbox_mod, "execute_in_sandbox",
        lambda **kwargs: ("ok", [], [], list(changed)),
    )


def _no_pptx(monkeypatch):
    import tools.generate as gen_mod

    def boom(*a, **k):
        raise AssertionError("PPTX post-processing must not run for an HTML deck")

    monkeypatch.setattr(gen_mod, "_prepare_workspace", boom)
    monkeypatch.setattr(remote_server, "_build_pptx", boom)


# --- init_deck_workspace -----------------------------------------------------


def _init(output_format: str | None):
    storage = MagicMock()
    kwargs = {} if output_format is None else {"output_format": output_format}
    result = init_mod.init_deck_workspace(name="n", user_id="u1", storage=storage, **kwargs)
    return storage, result


def test_init_html_writes_output_format():
    storage, result = _init("html")
    data = storage.put_deck_json.call_args.kwargs["data"]
    assert data["outputFormat"] == "html"
    assert storage.put_deck_json.call_args.kwargs["deck_id"] == result["deckId"]


def test_init_pptx_deck_json_unchanged():
    from sdpm.engine.schema import DECK_JSON_SKELETON, complete_deck_skeleton

    for fmt in (None, "pptx"):
        storage, _ = _init(fmt)
        data = storage.put_deck_json.call_args.kwargs["data"]
        assert data == complete_deck_skeleton(DECK_JSON_SKELETON)
        assert "outputFormat" not in data


def test_init_rejects_unknown_format_before_creating_anything():
    storage = MagicMock()
    with pytest.raises(ValueError):
        init_mod.init_deck_workspace(name="n", user_id="u1", storage=storage, output_format="pdf")
    storage.put_deck.assert_not_called()
    storage.put_deck_json.assert_not_called()


def test_init_tool_passes_output_format(server, monkeypatch):
    seen = {}
    monkeypatch.setattr(remote_server.init_mod, "init_deck_workspace", lambda **kw: seen.update(kw) or {"deckId": "x"})
    remote_server.init_deck_workspace(name="n", output_format="html")
    assert seen["output_format"] == "html"


# --- start_composing / sandbox -----------------------------------------------


def test_start_composing_html_materializes_html_slides_and_template(server, cache_root):
    payload = json.loads(server.start_composing(deck_id="d1", assigned_slugs=["cover"], mode="html"))
    assert payload["static"]["workflow"].startswith("# Composer (HTML)")
    deck = payload["deck"]
    assert deck["specs_ok"] is True
    assert deck["slides_present"] == ["body", "cover"]
    assert deck["existing_slides"] == {"cover": {"html": SLIDES["cover"]}}
    assert deck["deck_css"] == ".card { padding: 8px; }\n"
    assert deck["template_html"]["layouts"] and "template_analysis" not in deck
    # The conversion was persisted to S3 for the next microVM.
    assert any(k.startswith(TEMPLATE_CACHE_PREFIX) and k.endswith("/template.json") for k in server._storage.objects)


def test_start_composing_without_deck_returns_html_static(server):
    payload = json.loads(server.start_composing(mode="html"))
    assert set(payload) == {"static"}
    assert payload["static"]["workflow"].startswith("# Composer (HTML)")


def test_start_composing_mode_mismatch_reports_deck_format(server):
    payload = json.loads(server.start_composing(deck_id="d1", assigned_slugs=["cover"]))
    assert payload["specs_ok"] is False and payload["mode"] == "html"


def test_sandbox_syncs_deck_css():
    assert "deck.css" in sandbox_mod._WORKSPACE_PREFIXES


# --- run_python ---------------------------------------------------------------


def _run(server, measure=None):
    return json.loads(server.run_python(purpose="t", code="print(1)", deck_id="d1", measure_slides=measure))


def test_run_python_html_uploads_output_and_all_missing_previews(server, storage, monkeypatch):
    _no_pptx(monkeypatch)
    _sandbox(monkeypatch, ["slides/cover.html"])
    storage.record["htmlS3Key"] = "html/d1/old.html"
    storage.objects["html/d1/old.html"] = b"old"

    out = _run(server)

    assert "html_error" not in out, out
    [key] = storage.html_keys()
    assert out["html"] == key and storage.content_types[key] == HTML_CONTENT_TYPE
    assert storage.objects[key].lower().startswith(b"<!doctype html>")
    assert storage.record["htmlS3Key"] == key and storage.record["slideCount"] == 2
    assert "html/d1/old.html" in storage.deleted
    # No preview existed yet: every slide gets one, slide 1 becomes the thumbnail.
    assert sorted(out["previews"]) == ["body", "cover"]
    assert storage.record["thumbnailS3Key"] == out["previews"]["cover"]
    assert all(storage.content_types[k] == HTML_CONTENT_TYPE for k in storage.preview_keys())
    assert "pptxS3Key" not in storage.record


def test_run_python_html_uploads_only_affected_previews(server, storage, monkeypatch):
    _no_pptx(monkeypatch)
    old_cover, old_body = "html/d1/preview/cover_100.html", "html/d1/preview/body_100.html"
    storage.objects.update({old_cover: b"x", old_body: b"x"})
    storage.record["thumbnailS3Key"] = old_cover
    _sandbox(monkeypatch, ["slides/body.html"])

    out = _run(server)

    assert list(out["previews"]) == ["body"]
    assert old_body in storage.deleted and old_cover not in storage.deleted
    assert storage.record["thumbnailS3Key"] == old_cover  # slide 1 was not re-rendered


def test_run_python_html_measure_reports_and_previews_measured(server, storage, monkeypatch):
    _no_pptx(monkeypatch)
    storage.objects.update({"html/d1/preview/cover_100.html": b"x", "html/d1/preview/body_100.html": b"x"})
    _sandbox(monkeypatch, [])

    out = _run(server, measure=["cover"])

    assert list(out["previews"]) == ["cover"]
    assert "cover" in out["measure"]
    assert out["measure"].startswith(html_deck.REMOTE_CHECK_REPORT_HEADER)
    assert "output.html" not in out["measure"]
    assert out["preview"]["note"] == html_deck.REMOTE_PREVIEW_NOTE and "open" not in out["preview"]


def test_run_python_html_non_build_change_does_nothing(server, storage, monkeypatch):
    _no_pptx(monkeypatch)
    _sandbox(monkeypatch, ["specs/brief.md"])
    out = _run(server)
    assert storage.html_keys() == [] and "html" not in out


def test_run_python_html_record_failure_reports_stale_html(server, storage, monkeypatch):
    _no_pptx(monkeypatch)
    _sandbox(monkeypatch, ["deck.css"])
    monkeypatch.setattr(storage, "update_deck", MagicMock(side_effect=RuntimeError("DynamoDB down")))

    out = _run(server)

    assert "stale" in out["html_error"]
    assert storage.html_keys() == []  # the orphaned upload was deleted


# --- generate_pptx (finalize) -------------------------------------------------


def test_generate_pptx_finalizes_html_deck(server, storage, monkeypatch):
    kb = MagicMock()
    monkeypatch.setattr(remote_server, "_get_kb_sync", lambda: kb)
    stale = ["html/d1/preview/cover_1.html", "html/d1/preview/gone_1.html"]
    storage.objects.update({k: b"x" for k in stale})
    storage.record["htmlS3Key"] = "html/d1/old.html"

    result = json.loads(server.generate_pptx(deck_id="d1"))

    assert result["status"] == "completed" and result["outputFormat"] == "html"
    assert result["slideCount"] == 2 and result["slides"] == ["page01 - cover", "page02 - body"]
    [key] = storage.html_keys()
    assert result["bytes"] == len(storage.objects[key])
    previews = storage.preview_keys()
    assert sorted(_PREVIEW_KEY.match(k).group(1) for k in previews) == ["body", "cover"]
    assert len({_PREVIEW_KEY.match(k).group(2) for k in previews}) == 1  # one epoch
    assert set(stale) <= set(storage.deleted) and "html/d1/old.html" in storage.deleted
    assert storage.record["htmlS3Key"] == key
    assert storage.record["thumbnailS3Key"] in previews and "/cover_" in storage.record["thumbnailS3Key"]
    kwargs = kb.sync_deck.call_args.kwargs
    assert kwargs["deck_id"] == "d1" and kwargs["deck_name"] == "Remote deck"
    cover = kwargs["slides"][0]
    assert cover["id"] == "cover" and cover["layout"] == "Title Slide"
    assert cover["title"] == "Hello" and cover["notes"] == "Say hi"
    assert "Hello" in cover["elements"][0]["text"]
    assert not any(k.startswith("pptx/") for k in storage.objects)


def test_generate_pptx_kb_failure_is_a_warning(server, storage, monkeypatch):
    kb = MagicMock()
    kb.sync_deck.side_effect = RuntimeError("vectors down")
    monkeypatch.setattr(remote_server, "_get_kb_sync", lambda: kb)
    result = json.loads(server.generate_pptx(deck_id="d1"))
    assert result["warnings"]["kbSyncFailed"] == "vectors down"


def test_generate_pptx_partial_preview_upload_removes_this_runs_previews(server, storage, monkeypatch):
    previous = ["html/d1/preview/cover_1.html", "html/d1/preview/body_1.html"]
    storage.objects.update({k: b"x" for k in previous})
    upload = storage.upload_file

    def flaky(key, data, content_type="", tagging=""):
        if "/preview/body_" in key:
            raise RuntimeError("S3 down")
        upload(key, data, content_type, tagging)

    monkeypatch.setattr(storage, "upload_file", flaky)

    result = json.loads(server.generate_pptx(deck_id="d1"))

    assert "body" in result["error"]
    assert storage.preview_keys() == sorted(previous)  # the complete older set stays the latest
    assert storage.html_keys() == [] and "htmlS3Key" not in storage.record


def test_generate_pptx_pptx_deck_takes_the_pptx_path(server, storage, monkeypatch):
    deck_json = storage.get_deck_json("d1")
    deck_json.pop("outputFormat")
    storage.put_deck_json("d1", deck_json)
    called = {}
    monkeypatch.setattr(remote_server.generate, "generate_pptx", lambda **kw: called.update(kw) or {"slideCount": 0})
    json.loads(server.generate_pptx(deck_id="d1"))
    assert called["deck_id"] == "d1"


# --- get_preview ---------------------------------------------------------------


def test_get_preview_html_deck_returns_note(server):
    assert server.get_preview(deck_id="d1", slugs=["cover"]) == [
        {"type": "text", "text": html_deck.REMOTE_PREVIEW_NOTE}
    ]


# --- template conversion cache ---------------------------------------------------


def test_template_cache_round_trip_skips_conversion(tmp_path, monkeypatch):
    from sdpm.engine.html import template as template_mod

    storage = FakeStorage()
    first = tmp_path / "first"
    template_mod.load_template_html(_TEMPLATE, decorations=False, cache_root=first)
    uploaded = template_html_cache.persist(_TEMPLATE, storage, first)
    key = template_mod.cache_key(_TEMPLATE)
    cached = sorted(k for k in storage.objects if k.startswith(f"{TEMPLATE_CACHE_PREFIX}{key}/"))
    assert uploaded == len(cached) and {k.rsplit("/", 1)[1] for k in cached} >= {"template.json", "theme.css"}

    # A second persist uploads nothing new.
    assert template_html_cache.persist(_TEMPLATE, storage, first) == 0

    # A fresh microVM restores instead of converting; non-allowlisted keys are ignored.
    storage.objects[f"{TEMPLATE_CACHE_PREFIX}{key}/evil.sh"] = b"rm -rf /"
    second = tmp_path / "second"
    assert template_html_cache.restore(_TEMPLATE, storage, second) == len(cached)
    assert not (second / key / "evil.sh").exists()
    monkeypatch.setattr(template_mod, "build_template_info", MagicMock(side_effect=AssertionError("converted")))
    converted = template_mod.load_template_html(_TEMPLATE, decorations=False, cache_root=second)
    assert converted.info["layouts"]
    # Already restored: nothing is downloaded again.
    assert template_html_cache.restore(_TEMPLATE, storage, second) == 0


def test_template_cache_persist_uploads_only_missing(tmp_path):
    from sdpm.engine.html import template as template_mod

    storage = FakeStorage()
    root = tmp_path / "c"
    template_mod.load_template_html(_TEMPLATE, decorations=False, cache_root=root)
    key = template_mod.cache_key(_TEMPLATE)
    storage.objects[f"{TEMPLATE_CACHE_PREFIX}{key}/theme.css"] = b"already"
    (root / key / "notes.txt").write_text("not allowlisted", encoding="utf-8")
    template_html_cache.persist(_TEMPLATE, storage, root)
    assert storage.objects[f"{TEMPLATE_CACHE_PREFIX}{key}/theme.css"] == b"already"
    assert f"{TEMPLATE_CACHE_PREFIX}{key}/template.json" in storage.objects
    assert not any(k.endswith("notes.txt") for k in storage.objects)
    assert all(k.startswith(TEMPLATE_CACHE_PREFIX) for k in storage.if_absent)


# --- workspace refs ---------------------------------------------------------------


def test_prepare_rejects_refs_outside_the_deck(tmp_path, cache_root):
    storage = FakeStorage()
    _seed_html_deck(storage, tmp_path, slides={
        "cover": '<section data-layout="Title Slide"><img src="images/a.png"><img src="../../etc/passwd">'
                 '<img src="/abs.png"></section>',
    })
    storage.objects["decks/d1/images/a.png"] = b"png"
    tmpdir, meta = html_deck.prepare_html_workspace("d1", "user1", storage, cache_root)
    try:
        assert (tmpdir / "images" / "a.png").read_bytes() == b"png"
        assert json.loads((tmpdir / "deck.json").read_text())["template"] == "template.pptx"
        assert meta["template"] == "blank-dark"
    finally:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)
    assert html_deck._safe_relative("../x") is None and html_deck._safe_relative("/x") is None
    assert html_deck._safe_relative("a\\b") is None and html_deck._safe_relative("C:x") is None
    assert html_deck._safe_relative("./images/a.png") == "images/a.png"


# --- tool count --------------------------------------------------------------------


def test_remote_tool_count_unchanged():
    """20 tools as before; a configured knowledge base adds only search_slides."""
    import asyncio

    without_kb = {t.name for t in asyncio.run(remote_server.mcp.list_tools())}
    assert len(without_kb) == 20 and "search_slides" not in without_kb

    env = {
        "DECKS_TABLE": "decks-test", "PPTX_BUCKET": "pptx-test", "RESOURCE_BUCKET": "resource-test",
        "KB_SSM_PARAM": "/sdpm/kb-id", "VECTOR_BUCKET_NAME": "vectors-test",
        "VECTOR_INDEX_NAME": "index-test", "AWS_DEFAULT_REGION": "ap-northeast-1",
    }
    with patch.dict("os.environ", env), patch("boto3.client", lambda *a, **k: MagicMock()):
        spec = importlib.util.spec_from_file_location("remote_server_html_count", _ROOT / "servers" / "remote" / "server.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    tools = asyncio.run(module.mcp.list_tools())
    assert {t.name for t in tools} == without_kb | {"search_slides"}
    params = {t.name: set(t.inputSchema.get("properties", {})) for t in tools}
    assert "output_format" in params["init_deck_workspace"]
    assert "mode" in params["start_composing"]
