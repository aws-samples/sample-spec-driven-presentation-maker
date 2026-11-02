# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""run_python PPTX post-processing on both servers, end to end.

The real build, measurement, layout judgments, compose and preview code runs; only
LibreOffice / poppler (tests/fake_libreoffice.py), the cloud sandbox and S3 /
DynamoDB (a dict-backed storage) are fakes. Every assertion about the shape of
the result the agent sees sits in the ``_assert_*_format`` helpers.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pytest

import fake_libreoffice

_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE = _ROOT / "sdpm" / "templates" / "blank-dark.pptx"
_LOCAL = str(_ROOT / "servers" / "local")
if _LOCAL not in sys.path:
    sys.path.insert(0, _LOCAL)

import sandbox_tools  # noqa: E402  (servers/local)

os.environ.setdefault("DECKS_TABLE", "test-table")
os.environ.setdefault("PPTX_BUCKET", "test-pptx")
os.environ.setdefault("RESOURCE_BUCKET", "test-resource")

_spec = importlib.util.spec_from_file_location(
    "remote_server_pptx_characterization", _ROOT / "servers" / "remote" / "server.py"
)
remote_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remote_server)

OUTLINE = "# Deck\n\n- [cover] Cover\n- [body] Body\n- [bad] Bad\n"
BAD_OUTLINE = OUTLINE + "- [Not_A_Slug] Broken line\n"
SLIDES: dict[str, dict] = {
    "cover": {"layout": "Title Slide", "title": "Hello", "elements": []},
    # Top-heavy (layout bias), two overlapping text boxes (judge collision), a shape
    # without text (a Graphic with a holed path in the SVG) and a missing include
    # (a "page02(body)" build warning).
    "body": {
        "layout": "Title Only",
        "title": "Body",
        "elements": [
            {"_comment": "region: content", "x": 60, "y": 160, "width": 900, "height": 400},
            {"type": "textbox", "text": "First block", "x": 60, "y": 160, "width": 500, "height": 80},
            {"type": "textbox", "text": "Second block", "x": 80, "y": 170, "width": 500, "height": 80},
            {"type": "shape", "shape": "rectangle", "x": 60, "y": 260, "width": 100, "height": 100,
             "fill": "#FF9900"},
            {"type": "include", "src": "includes/missing.json"},
        ],
    },
    "bad": {
        "layout": "No Such Layout",
        "title": "Bad",
        "elements": [{"type": "textbox", "text": "Bad layout", "x": 100, "y": 400, "width": 600, "height": 80}],
    },
}
EDITED_BODY = {**SLIDES["body"], "title": "Body edited"}
_EPOCH_KEY = re.compile(r"_(\d+)\.(?:json|webp)$")


def _epoch(key: str) -> int:
    return int(_EPOCH_KEY.search(key).group(1))


# --------------------------------------------------------------------------- Remote


class _S3:
    def __init__(self, storage: "_Storage"):
        self.storage = storage
        self.deleted: list[str] = []

    def delete_object(self, Bucket, Key):  # noqa: N803 — boto3 keyword names
        self.deleted.append(Key)
        self.storage.objects.pop(Key, None)


class _Storage:
    """Dict-backed AwsStorage: pptx bucket objects, resource bucket, deck record."""

    pptx_bucket = "test-pptx"

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.resource: dict[str, bytes] = {"templates/blank-dark.pptx": _TEMPLATE.read_bytes()}
        self.record: dict = {"deckId": "d1", "name": "Deck", "pptxS3Key": "pptx/d1/old.pptx"}
        self.updates: list[dict] = []
        self._s3 = _S3(self)

    def get_deck(self, deck_id, user_id):
        return dict(self.record) if deck_id == "d1" else None

    def update_deck(self, deck_id, user_id, updates):
        self.updates.append(dict(updates))
        old = {k: self.record[k] for k in updates if k in self.record}
        self.record.update(updates)
        return old

    def get_deck_json(self, deck_id):
        return json.loads(self.objects[f"decks/{deck_id}/deck.json"])

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

    def upload_file(self, key, data, content_type=""):
        self.objects[key] = data

    def list_templates(self):
        return [{"name": "blank-dark", "s3Key": "templates/blank-dark.pptx"}]

    def get_user_template_metadata(self, user_id, name):
        return None

    def list_user_templates(self, user_id):
        return []

    def keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))


@pytest.fixture()
def remote(monkeypatch):
    """The real remote run_python on a three-slide S3 deck; returns (run, storage, office)."""
    import sdpm.knowledge.assets as assets_mod

    # _prepare_workspace points the asset lookup at its tmpdir; restore it afterwards.
    for name in ("ASSETS_DIR", "ICON_DIR", "ICON_LOCAL_DIR", "_manifest_cache"):
        monkeypatch.setattr(assets_mod, name, getattr(assets_mod, name))
    office = fake_libreoffice.install(monkeypatch)
    storage = _Storage()
    storage.objects["decks/d1/deck.json"] = json.dumps({"template": "", "defaultTextColor": "#FFFFFF"}).encode()
    storage.objects["decks/d1/specs/outline.md"] = OUTLINE.encode()
    for slug, data in SLIDES.items():
        storage.objects[f"decks/d1/slides/{slug}.json"] = json.dumps(data).encode()

    monkeypatch.setattr(remote_server, "_storage", storage)
    monkeypatch.setattr(remote_server, "_check_deck_access", lambda *a, **k: None)
    monkeypatch.setattr(remote_server, "_get_user_id", lambda: "user1")
    monkeypatch.setattr(remote_server, "_run_in_background", lambda target, *, name: target())

    def run(writes: dict[str, object] | None = None, measure_slides=None, *, outline_warning=False) -> dict:
        def fake_execute(code, storage, region, deck_id=None, persist_writes=True):
            changed = []
            for rel, data in (writes or {}).items():
                body = data if isinstance(data, str) else json.dumps(data)
                storage.objects[f"decks/{deck_id}/{rel}"] = body.encode()
                changed.append(rel)
            return "ok", [{"line": 1}] if outline_warning else [], [], changed

        monkeypatch.setattr(remote_server.sandbox_mod, "execute_in_sandbox", fake_execute)
        return json.loads(remote_server.run_python(
            purpose="t", code="print(1)", deck_id="d1", measure_slides=measure_slides))

    return run, storage, office


def _assert_measure_format(out: dict) -> None:
    """Measured body + bad, the same on both servers: report text with the judge
    findings, structured layout bias and the measured pages' build warnings, invalid
    layout per slug."""
    assert out["measure"].startswith("📐 Text measurement")
    assert "Slide body:" in out["measure"] and "Slide bad:" in out["measure"]
    assert '"First block"' in out["measure"]
    assert "⚠ Layout issues" in out["measure"] and "[collision]" in out["measure"]
    assert {"layoutBias", "build"} <= set(out["warnings"])
    assert [(b["slide"], b["layout"], b["direction"]) for b in out["warnings"]["layoutBias"]] == [
        (2, "Title Only", "top-heavy"),
        (3, "No Such Layout", "top-heavy"),
    ]
    build = out["warnings"]["build"]
    assert any("page02(body)" in w and "includes/missing.json" in w for w in build)
    assert not any("offset:" in w or "auto-detected" in w or "auto-set" in w for w in build)
    assert out["errors"]["bad"]["invalidLayout"] == "No Such Layout"
    assert "Title Only" in out["errors"]["bad"]["available"]
    assert "lint_diagnostics" not in out


_assert_remote_measure_format = _assert_measure_format


def test_remote_edit_with_measure(remote):
    run, storage, office = remote
    out = run({"slides/body.json": EDITED_BODY}, ["body", "bad"])

    assert out["output"] == "ok"
    _assert_remote_measure_format(out)
    assert set(out["errors"]) == {"bad"}
    assert "pptx_error" not in out
    assert "body" in out["previewHint"] and "bad" in out["previewHint"]

    # The artifact follows the change; the superseded one is deleted.
    [pptx_key] = storage.keys("pptx/d1/")
    assert storage.objects[pptx_key][:2] == b"PK"
    assert storage.updates[-1]["pptxS3Key"] == pptx_key and storage.updates[-1]["slideCount"] == 3
    assert storage._s3.deleted == ["pptx/d1/old.pptx"]

    # Previews of the rendered slugs, compose for the rendered slugs plus every slug
    # without compose yet; never for a slide whose layout fell back.
    previews = storage.keys("previews/d1/")
    assert [k.rsplit("/", 1)[1].rsplit("_", 1)[0] for k in previews] == ["bad", "body"]
    assert all(k.endswith(".webp") for k in previews)
    compose = storage.keys("decks/d1/compose/")
    names = sorted(k.rsplit("/", 1)[1].rsplit("_", 1)[0] for k in compose)
    assert names == ["body", "cover", "defs"]
    assert len({_epoch(k) for k in compose + previews}) == 1
    body = json.loads(storage.objects[next(k for k in compose if "/body_" in k)])
    assert body["regions"] == [{"name": "content", "x": 60, "y": 160, "w": 900, "h": 400}]
    assert body["sourceHash"]
    assert body["components"] and all(c["changed"] is True for c in body["components"])
    assert any('fill-rule="evenodd"' in c["svg"] for c in body["components"] if c["class"] == "Graphic")


def test_remote_unchanged_slide_keeps_compose_unchanged_and_drops_old_keys(remote):
    run, storage, office = remote
    run({"slides/body.json": EDITED_BODY}, ["body"])
    first = {k: v for k, v in storage.objects.items() if k.startswith("decks/d1/compose/")}
    # Older keys: a previous epoch of body and a legacy slide_N file.
    old_body = "decks/d1/compose/body_100.json"
    storage.objects[old_body] = next(v for k, v in first.items() if "/body_" in k)
    storage.objects["decks/d1/compose/defs_100.json"] = b"{}"
    storage.objects["decks/d1/compose/slide_1_100.json"] = b"{}"
    for key in first:  # the next run must read the 100-epoch file as the previous compose
        del storage.objects[key]

    artifacts = storage.keys("pptx/d1/")
    out = run(None, ["body"])

    compose = storage.keys("decks/d1/compose/")
    assert old_body not in compose and "decks/d1/compose/defs_100.json" not in compose
    assert "decks/d1/compose/slide_1_100.json" not in compose
    body = json.loads(storage.objects[next(k for k in compose if "/body_" in k)])
    assert all(c["changed"] is False for c in body["components"])
    assert "measure" in out
    assert storage.keys("pptx/d1/") == artifacts  # measure only: no artifact refresh


def test_remote_edit_without_measure(remote):
    run, storage, office = remote
    out = run({"slides/body.json": EDITED_BODY})
    assert "measure" not in out and "warnings" not in out and "errors" not in out
    assert storage.keys("pptx/d1/")
    assert "body" in out["previewHint"]


def test_remote_measure_of_an_unknown_slug(remote):
    run, storage, office = remote
    out = run(None, ["ghost"])
    assert out["measure"] == json.dumps({"error": "No matching slides found for given slugs"})


def test_remote_outline_warning_with_layout_bias(remote):
    run, storage, office = remote
    out = run({"specs/outline.md": BAD_OUTLINE}, ["body"], outline_warning=True)
    _assert_remote_outline_with_bias(out)


def _assert_remote_outline_with_bias(out: dict) -> None:
    # The outline warning stays next to the measured slide's warnings.
    assert set(out["warnings"]) == {"outline", "layoutBias", "build"}
    assert out["warnings"]["outline"].startswith("outline.md format violation")


# --------------------------------------------------------------------------- Local


@pytest.fixture()
def local_deck(tmp_path: Path) -> Path:
    deck = tmp_path / "deck"
    (deck / "slides").mkdir(parents=True)
    (deck / "specs").mkdir()
    (deck / "deck.json").write_text(json.dumps({"template": "blank-dark", "defaultTextColor": "#FFFFFF"}), encoding="utf-8")
    (deck / "specs" / "outline.md").write_text(OUTLINE, encoding="utf-8")
    for slug, data in SLIDES.items():
        (deck / "slides" / f"{slug}.json").write_text(json.dumps(data), encoding="utf-8")
    return deck


def _local_run(deck: Path, writes: dict[str, object] | None = None, measure_slides=None) -> dict:
    code = "\n".join(
        f"write_text({rel!r}, {data!r})" if isinstance(data, str) else f"write_json({rel!r}, {data!r})"
        for rel, data in (writes or {}).items()
    ) or 'print("ok")'
    return json.loads(sandbox_tools.run_python(
        purpose="t", code=code, deck_id=str(deck), measure_slides=measure_slides))


def _compose_files(deck: Path) -> dict[str, list[Path]]:
    files: dict[str, list[Path]] = {}
    for p in sorted((deck / "compose").glob("*.json")):
        files.setdefault(p.name.rsplit("_", 1)[0], []).append(p)
    return files


_assert_local_measure_format = _assert_measure_format


def test_local_edit_with_measure(local_deck: Path, monkeypatch):
    office = fake_libreoffice.install(monkeypatch)
    out = _local_run(local_deck, {"slides/body.json": EDITED_BODY}, ["body", "bad"])

    _assert_local_measure_format(out)
    assert out["pptx"] == str(local_deck / "output.pptx")
    assert (local_deck / "output.pptx").read_bytes()[:2] == b"PK"
    assert "pptx_error" not in out and "render_error" not in out and "compose_error" not in out
    _assert_local_compose(out, local_deck)
    assert out["preview_files"] == [str(local_deck / "preview" / "body.png"), str(local_deck / "preview" / "bad.png")]
    from PIL import Image

    assert Image.open(local_deck / "preview" / "body.png").size[0] == 1280
    assert "preview" not in out
    assert not list((local_deck / "_work").glob("measure-*"))
    assert ("soffice", "svg") in office.calls


def _assert_local_compose(out: dict, deck: Path) -> None:
    # Rendered slugs are composed, except a slide whose layout fell back; with sourceHash.
    assert out["compose"] == "1 slides composed"
    files = _compose_files(deck)
    assert sorted(files) == ["body", "defs"]
    body = json.loads(files["body"][-1].read_text(encoding="utf-8"))
    assert body["regions"] == [{"name": "content", "x": 60, "y": 160, "w": 900, "h": 400}]
    assert body["sourceHash"]
    assert body["components"] and all(c["changed"] is True for c in body["components"])


def test_local_compose_replaces_older_files_of_the_written_slugs(local_deck: Path, monkeypatch):
    fake_libreoffice.install(monkeypatch)
    compose = local_deck / "compose"
    compose.mkdir()
    for name in ("body_100.json", "cover_100.json", "defs_100.json"):
        (compose / name).write_text("{}", encoding="utf-8")
    _local_run(local_deck, {"slides/body.json": EDITED_BODY})
    files = _compose_files(local_deck)
    assert [p.name for p in files["cover"]] == ["cover_100.json"]  # not re-rendered: kept
    assert len(files["body"]) == 1 and files["body"][0].name != "body_100.json"
    assert len(files["defs"]) == 1 and files["defs"][0].name != "defs_100.json"


def test_local_compose_keeps_fill_rule_of_icons(local_deck: Path, monkeypatch):
    """Adapter path: a fill-rule=evenodd graphic survives into compose/<slug>_*.json."""
    fake_libreoffice.install(monkeypatch)
    _local_run(local_deck, {"slides/body.json": EDITED_BODY})
    body = json.loads(_compose_files(local_deck)["body"][-1].read_text(encoding="utf-8"))
    graphics = [c for c in body["components"] if c["class"] == "Graphic"]
    assert graphics and all('fill-rule="evenodd"' in c["svg"] for c in graphics)


def test_local_edit_without_measure(local_deck: Path, monkeypatch):
    fake_libreoffice.install(monkeypatch)
    out = _local_run(local_deck, {"slides/body.json": EDITED_BODY})
    assert "measure" not in out
    _assert_local_unmeasured_warnings(out)
    assert out["compose"] == "1 slides composed"
    assert out["preview_files"] == [str(local_deck / "preview" / "body.png")]


def _assert_local_unmeasured_warnings(out: dict) -> None:
    # Build warnings come with measure_slides only.
    assert "warnings" not in out and "lint_diagnostics" not in out


def test_local_without_libreoffice(local_deck: Path, monkeypatch):
    fake_libreoffice.install(monkeypatch, available=False)
    out = _local_run(local_deck, {"slides/body.json": EDITED_BODY}, ["body"])
    _assert_local_no_libreoffice_measure(out)
    assert out["preview"]["status"] == "unavailable"
    assert set(out["preview"]["missing"]) == {"libreoffice", "poppler"}
    assert "compose" not in out and "preview_files" not in out
    assert (local_deck / "output.pptx").is_file()


def _assert_local_no_libreoffice_measure(out: dict) -> None:
    assert out["measure"] == json.dumps({"error": "LibreOffice SVG export failed"})


def test_local_measure_of_an_unknown_slug(local_deck: Path, monkeypatch):
    fake_libreoffice.install(monkeypatch)
    out = _local_run(local_deck, None, ["ghost"])
    _assert_local_no_match(out)


def _assert_local_no_match(out: dict) -> None:
    assert out["measure"] == json.dumps({"error": "No matching slides found for given slugs"})


def test_local_outline_warning_with_build_warnings(local_deck: Path, monkeypatch):
    fake_libreoffice.install(monkeypatch)
    out = _local_run(local_deck, {"specs/outline.md": BAD_OUTLINE}, ["body"])
    _assert_local_outline_with_build_warnings(out)


def _assert_local_outline_with_build_warnings(out: dict) -> None:
    # The outline warning stays next to the measured slide's warnings.
    assert set(out["warnings"]) == {"outline", "layoutBias", "build"}
    assert out["warnings"]["outline"].startswith("outline.md format violation")
