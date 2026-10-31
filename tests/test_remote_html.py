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
from sdpm.engine.html import browser_check
from sdpm.engine.html.browser import DISABLED_NOTE
from sdpm.engine.html.check import CHECK_REPORT_HEADER
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


def test_init_returns_format_notes_for_html_only():
    from sdpm.entry import format_notes

    _, html = _init("html")
    assert html["format_notes"] == format_notes("html") and html["format_notes"]
    for fmt in (None, "pptx"):
        _, result = _init(fmt)
        assert "format_notes" not in result


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


def test_run_python_html_drops_previews_of_slides_not_in_the_build(server, storage, monkeypatch):
    """A slide output.html leaves out keeps no preview, so thumbnail and player indexes agree."""
    _no_pptx(monkeypatch)
    old_cover, gone = "html/d1/preview/cover_100.html", "html/d1/preview/gone_100.html"
    storage.objects.update({old_cover: b"x", gone: b"x", "html/d1/preview/body_100.html": b"x"})
    _sandbox(monkeypatch, ["slides/body.html"])

    out = _run(server)

    assert "html_error" not in out, out
    assert gone in storage.deleted
    assert old_cover not in storage.deleted


def test_run_python_html_measure_reports_and_previews_measured(server, storage, monkeypatch):
    _no_pptx(monkeypatch)
    storage.objects.update({"html/d1/preview/cover_100.html": b"x", "html/d1/preview/body_100.html": b"x"})
    _sandbox(monkeypatch, [])

    out = _run(server, measure=["cover"])

    assert list(out["previews"]) == ["cover"]
    assert "cover" in out["measure"]
    assert out["measure"].startswith(CHECK_REPORT_HEADER)
    # SDPM_BROWSER=none (conftest): the core's unavailable preview passes through.
    assert out["preview"] == {"status": "unavailable", "reason": "browser-skipped", "note": DISABLED_NOTE}
    assert out["png_previews"] == [] and "preview_files" not in out


def test_run_python_html_non_build_change_does_nothing(server, storage, monkeypatch):
    _no_pptx(monkeypatch)
    _sandbox(monkeypatch, ["specs/brief.md"])
    out = _run(server)
    assert storage.html_keys() == [] and "html" not in out


def test_run_python_html_record_failure_reports_stale_html(server, storage, monkeypatch):
    _no_pptx(monkeypatch)
    _fake_check(monkeypatch)  # the check writes PNGs, which must go with the previews
    _sandbox(monkeypatch, ["deck.css"])
    monkeypatch.setattr(storage, "update_deck", MagicMock(side_effect=RuntimeError("DynamoDB down")))

    out = _run(server)

    assert "stale" in out["html_error"]
    assert storage.html_keys() == []  # the orphaned upload was deleted
    assert storage.preview_keys() == []  # so were this run's previews and PNGs
    assert not any(k.startswith("html/d1/png/") for k in storage.objects)


def test_run_python_html_single_preview_upload_failure_publishes_nothing(server, storage, monkeypatch):
    _no_pptx(monkeypatch)
    storage.record["htmlS3Key"] = "html/d1/old.html"
    storage.objects["html/d1/old.html"] = b"old"
    upload = storage.upload_file

    def flaky(key, data, content_type="", tagging=""):
        if "/preview/body_" in key:
            raise RuntimeError("S3 down")
        upload(key, data, content_type, tagging)

    monkeypatch.setattr(storage, "upload_file", flaky)
    _sandbox(monkeypatch, ["deck.css"])

    out = _run(server)

    assert "body" in out["html_error"] and "stale" in out["html_error"]
    assert not {"html", "previews", "png_previews"} & set(out)
    assert storage.record["htmlS3Key"] == "html/d1/old.html" and storage.html_keys() == []
    assert storage.preview_keys() == []


def test_run_python_html_same_clock_writes_get_new_keys(server, storage, monkeypatch):
    _no_pptx(monkeypatch)
    monkeypatch.setattr(html_deck.time, "time_ns", lambda: 1_800_000_000_000 * 1_000_000)
    _sandbox(monkeypatch, ["slides/cover.html"])

    first = _run(server)["previews"]["cover"]
    second = _run(server)["previews"]["cover"]

    assert int(_PREVIEW_KEY.match(second).group(2)) > int(_PREVIEW_KEY.match(first).group(2))
    assert first in storage.deleted and first not in storage.objects


def test_run_python_html_revision_beats_older_second_epochs(server, storage, monkeypatch):
    from shared.html_artifacts import build_html_preview_key_map

    _no_pptx(monkeypatch)
    old = "html/d1/preview/cover_1793374283.html"
    storage.objects[old] = b"x"
    _sandbox(monkeypatch, ["slides/cover.html"])

    out = _run(server)

    assert build_html_preview_key_map([old, out["previews"]["cover"]])["cover"] == out["previews"]["cover"]


def test_js_deck_reports_the_skipped_browser_check(server, storage, tmp_path, monkeypatch):
    """With SDPM_BROWSER=none (conftest), run_python of a deck carries the one-line skip
    note among the warnings the agent reads; generate_pptx (finalize) checks nothing."""
    _no_pptx(monkeypatch)
    body = SLIDES["body"].replace("</section>", "<script>var x = 1;</script></section>")
    _seed_html_deck(storage, tmp_path / "js", {"cover": SLIDES["cover"], "body": body})
    _sandbox(monkeypatch, ["slides/body.html"])
    note = f"output.html: {DISABLED_NOTE}"

    out = _run(server)
    assert note in out["warnings"], out
    assert out["browser_check"] == {"status": "skipped", "slides": 0, "note": DISABLED_NOTE}
    assert note in _run(server, measure=["cover"])["warnings"]
    result = json.loads(server.generate_pptx(deck_id="d1"))
    assert note not in (result.get("warnings") or {}).get("build", []), result


def test_unreachable_agentcore_browser_is_one_warning_line(server, storage, monkeypatch):
    """AgentCore Browser that cannot be started: run_python says so in one line, never clean."""
    from tools import agentcore_browser
    from sdpm.engine.html import browser as browser_mod

    class DeniedClient:
        def start_browser_session(self, **_kw):
            raise RuntimeError("AccessDeniedException: not authorized")

        def stop_browser_session(self, **_kw):  # pragma: no cover - nothing started
            pytest.fail("stopped a session that never started")

    _no_pptx(monkeypatch)
    monkeypatch.delenv("SDPM_BROWSER")
    monkeypatch.setattr(browser_mod, "_registered", agentcore_browser.make_source(
        "ap-northeast-1", client_factory=DeniedClient))
    _sandbox(monkeypatch, ["slides/body.html"])

    out = _run(server)

    lines = [w for w in out["warnings"] if w.startswith("output.html: Browser check")]
    assert lines == [lines[0]] and "\n" not in lines[0], out["warnings"]
    assert lines[0].startswith("output.html: Browser check could not run (AgentCore Browser): RuntimeError: "
                               "AccessDeniedException")
    assert out["browser_check"]["status"] == "failed" and out["png_previews"] == []


# --- browser check PNGs -----------------------------------------------------------

_PNG_KEY = re.compile(r"^html/d1/png/([a-z0-9-]+)_(\d+)\.png$")


def _png_bytes(size=(1280, 720)) -> bytes:
    import io

    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("RGB", size, (30, 60, 90)).save(buf, format="PNG")
    return buf.getvalue()


def _fake_check(monkeypatch, *, no_png: frozenset = frozenset(), seen: list | None = None):
    """check_deck stand-in: a PNG per checked slug (except ``no_png``), status ok."""

    def fake(output_html, slugs, *, slide_size, line_map, layouts, decorations, png_dir=None, deadline=None):
        if seen is not None:
            seen.append(list(slugs))
        pngs = {}
        for slug in slugs:
            if slug in no_png or png_dir is None:
                continue
            Path(png_dir).mkdir(parents=True, exist_ok=True)
            path = Path(png_dir) / f"{slug}.png"
            path.write_bytes(_png_bytes())
            pngs[slug] = str(path)
        status = "timeout" if no_png else "ok"
        result = {"status": status, "browser": "AgentCore Browser", "seconds": 1.5, "slides": len(pngs),
                  "checked": list(pngs), "findings": {}, "errors": [], "pngs": pngs,
                  "timings": {"acquire": 0.9, "connect": 0.1, "load": 0.2, "slides": 0.3, "release": 0.1},
                  "network_blocked": True, "blocked_requests": 0}
        if no_png:
            result["note"] = "Browser check did not finish within 33 s; …"
        return result

    monkeypatch.setattr(browser_check, "check_deck", fake)


def _png_keys(storage) -> list[str]:
    return sorted(k for k in storage.objects if _PNG_KEY.match(k))


def test_run_python_html_uploads_pngs_of_checked_slides(server, storage, monkeypatch, caplog):
    import logging

    _no_pptx(monkeypatch)
    _fake_check(monkeypatch)
    old = {"html/d1/png/body_100.png", "html/d1/png/cover_100.png", "html/d1/png/other_100.png",
           "html/d1/png/broken_100.png"}
    storage.objects.update({k: b"x" for k in old})
    storage.objects["decks/d1/slides/broken.html"] = b"<p>no section</p>"
    _sandbox(monkeypatch, ["slides/body.html"])

    with caplog.at_level(logging.INFO, logger="sdpm.html_deck"):
        out = _run(server)

    assert "html_error" not in out, out
    assert out["png_previews"] == ["body"] and "preview_files" not in out
    [fresh] = [k for k in _png_keys(storage) if k not in old]
    assert _PNG_KEY.match(fresh).group(1) == "body" and storage.content_types[fresh] == "image/png"
    # The superseded body PNG and the PNG of a slide in this snapshot that did not build go;
    # cover was not checked, and "other" is not in this snapshot (a parallel composer may
    # have just written it), so both stay.
    assert "html/d1/png/body_100.png" in storage.deleted and "html/d1/png/broken_100.png" in storage.deleted
    assert "html/d1/png/cover_100.png" in storage.objects and "html/d1/png/other_100.png" in storage.objects
    assert out["browser_check"] == {"status": "ok", "browser": "AgentCore Browser", "seconds": 1.5, "slides": 1}
    [line] = [json.loads(r.getMessage()) for r in caplog.records
              if r.getMessage().startswith('{"kind": "html_browser_check"')]
    assert line["deck_id"] == "d1" and line["user_id"] == "user1" and line["status"] == "ok"
    assert line["slides"] == 1 and line["seconds"] == 1.5 and line["bytes"] > 0
    assert line["timings"]["acquire"] == 0.9 and line["network_blocked"] is True
    assert line["blocked_requests"] == 0


def test_run_python_html_checked_slide_without_png_loses_its_old_png(server, storage, monkeypatch):
    """A check that did not finish leaves no stale PNG for get_preview to show."""
    _no_pptx(monkeypatch)
    _fake_check(monkeypatch, no_png=frozenset({"body"}))
    storage.objects.update({"html/d1/png/body_100.png": b"x", "html/d1/png/cover_100.png": b"x"})
    _sandbox(monkeypatch, [])

    out = _run(server, measure=["body"])

    assert out["png_previews"] == []
    assert out["browser_check"]["status"] == "timeout"
    assert out["preview"]["reason"] == "browser-timeout"
    assert "html/d1/png/body_100.png" in storage.deleted
    assert "html/d1/png/cover_100.png" in storage.objects


def test_get_preview_html_deck_returns_pngs(server, storage, monkeypatch):
    from mcp.server.fastmcp.utilities.types import Image

    _no_pptx(monkeypatch)
    _fake_check(monkeypatch)
    _sandbox(monkeypatch, [])
    _run(server, measure=["cover"])

    out = server.get_preview(deck_id="d1", slugs=["cover", "body"], quality="low")

    assert out[0] == "Slide cover" and isinstance(out[1], Image)
    assert out[2] == 'No PNG for body yet: run run_python with measure_slides=["body"]'
    assert len(out) == 3


def test_get_preview_html_deck_png_gone_before_download(server, storage, monkeypatch):
    """A PNG superseded between the listing and the download gets the text line, not an error."""
    storage.objects["html/d1/png/cover_100.png"] = _png_bytes()
    listed = storage.list_files
    monkeypatch.setattr(storage, "list_files", lambda prefix, bucket="": (
        listed(prefix, bucket), storage.objects.pop("html/d1/png/cover_100.png", None))[0])
    out = server.get_preview(deck_id="d1", slugs=["cover"])
    assert out == ['No PNG for cover yet: run run_python with measure_slides=["cover"]']


def test_get_preview_html_deck_latest_png_wins(server, storage):
    from mcp.server.fastmcp.utilities.types import Image

    storage.objects["html/d1/png/cover_100.png"] = b"not a png"
    storage.objects["html/d1/png/cover_200.png"] = _png_bytes()
    out = server.get_preview(deck_id="d1", slugs=["cover"])
    assert out[0] == "Slide cover" and isinstance(out[1], Image)


def test_generate_pptx_runs_no_check_and_drops_pngs_of_removed_slides(server, storage, monkeypatch):
    seen: list = []
    _fake_check(monkeypatch, seen=seen)
    storage.objects.update({"html/d1/png/cover_1.png": b"x", "html/d1/png/gone_1.png": b"x"})

    result = json.loads(server.generate_pptx(deck_id="d1"))

    assert result["status"] == "completed", result
    assert seen == []
    assert "html/d1/png/gone_1.png" in storage.deleted
    assert "html/d1/png/cover_1.png" in storage.objects


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


def _misspell_output_format(storage):
    deck_json = storage.get_deck_json("d1")
    deck_json["outputFormat"] = "htlm"
    storage.put_deck_json("d1", deck_json)


def test_run_python_invalid_output_format_stops_the_build(server, storage, monkeypatch):
    _misspell_output_format(storage)
    _no_pptx(monkeypatch)
    _sandbox(monkeypatch, ["slides/cover.html"])
    out = _run(server)
    assert "htlm" in out["errors"]["outputFormat"]
    assert storage.html_keys() == []


def test_generate_pptx_invalid_output_format_returns_error(server, storage, monkeypatch):
    _misspell_output_format(storage)
    called = []
    monkeypatch.setattr(remote_server.generate, "generate_pptx", lambda **kw: called.append(kw))
    result = json.loads(server.generate_pptx(deck_id="d1"))
    assert "outputFormat" in result["error"]
    assert called == []


def test_get_preview_invalid_output_format_returns_error(server, storage):
    _misspell_output_format(storage)
    [item] = server.get_preview(deck_id="d1", slugs=["cover"])
    assert item["type"] == "text" and "outputFormat" in item["text"]


# --- get_preview ---------------------------------------------------------------


def test_get_preview_html_deck_without_pngs_says_how_to_make_them(server):
    assert server.get_preview(deck_id="d1", slugs=["cover"]) == [
        'No PNG for cover yet: run run_python with measure_slides=["cover"]'
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


# --- container image -----------------------------------------------------------------


def test_runtime_image_copies_bundled_html_data():
    """The remote image ships every bundled-data dir the HTML engine reads (SDPM_SKILL_ROOT).

    reveal.js under sdpm/vendor/ is inlined into every HTML deck; without it in the
    image, generate_pptx fails for every HTML deck on the deployed server.
    """
    dockerfile = (_ROOT / "servers" / "remote" / "Dockerfile").read_text(encoding="utf-8")
    copies = set(re.findall(r"^COPY\s+(\S+)", dockerfile, flags=re.MULTILINE))
    for data_dir in ("sdpm/references/", "sdpm/templates/", "sdpm/vendor/"):
        assert data_dir in copies, data_dir
    ignored = (_ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert not any(entry.rstrip("/") in ("sdpm/vendor", "sdpm") for entry in ignored)


def test_runtime_image_pins_websockets():
    """The browser check's only new dependency is pinned for the runtime image, and the
    image no longer turns the check off (AgentCore Browser runs it)."""
    constraints = (_ROOT / "servers" / "remote" / "constraints.txt").read_text(encoding="utf-8")
    assert re.search(r"^websockets==\d+", constraints, flags=re.MULTILINE)
    dockerfile = (_ROOT / "servers" / "remote" / "Dockerfile").read_text(encoding="utf-8")
    # Neither the new switch (SDPM_BROWSER) nor the removed phase-3 one may be set.
    assert not re.search(r"^ENV\s+SDPM_(BROWSER|JS_CHECK)\b", dockerfile, flags=re.MULTILINE)


def test_runtime_image_ships_vendored_libraries():
    """Every vendored file the HTML engine inlines (reveal.js, ECharts, D3 and their
    license files) exists and no .dockerignore entry keeps it out of the image."""
    import fnmatch

    from sdpm.engine.html.slide_js import LIBRARIES

    files = [path for paths in LIBRARIES.values() for path in paths]
    files += ["revealjs/reveal.js", "revealjs/reveal.css", "revealjs/reset.css",
              "revealjs/plugin/notes.js", "revealjs/LICENSE", "revealjs/VERSION",
              "echarts/VERSION", "d3/VERSION"]
    entries = [line.strip().rstrip("/") for line in
               (_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    for name in files:
        rel = f"sdpm/vendor/{name}"
        assert (_ROOT / rel).is_file(), rel
        parts = rel.split("/")
        candidates = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
        for entry in entries:
            matched = [c for c in candidates if fnmatch.fnmatch(c, entry)]
            assert not matched, f".dockerignore entry {entry!r} excludes {matched[0]}"
