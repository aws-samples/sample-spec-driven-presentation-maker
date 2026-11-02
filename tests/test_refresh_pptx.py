# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""sdpm.api.refresh_pptx — the run_python post-processing of PPTX decks, shared by
both servers. LibreOffice and poppler are faked (tests/fake_libreoffice.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import fake_libreoffice
import sdpm.api
from sdpm.api import refresh_pptx

SLIDES = {
    "cover": {"layout": "Title Slide", "title": "Hello", "elements": []},
    "body": {
        "layout": "Title Only",
        "title": "Body",
        "elements": [
            {"_comment": "region: content", "x": 60, "y": 160, "width": 900, "height": 400},
            {"type": "textbox", "text": "First block", "x": 60, "y": 160, "width": 500, "height": 80},
            {"type": "include", "src": "includes/missing.json"},
        ],
    },
    "bad": {"layout": "No Such Layout", "title": "Bad",
            "elements": [{"type": "textbox", "text": "Bad layout", "x": 100, "y": 400, "width": 600, "height": 80}]},
}


def _deck(tmp_path: Path, slides: dict[str, dict] = SLIDES) -> Path:
    deck = tmp_path / "deck"
    (deck / "slides").mkdir(parents=True)
    (deck / "specs").mkdir()
    (deck / "deck.json").write_text(json.dumps({"template": "blank-dark", "defaultTextColor": "#FFFFFF"}))
    (deck / "specs" / "outline.md").write_text("".join(f"- [{s}] {s}\n" for s in slides))
    for slug, data in slides.items():
        (deck / "slides" / f"{slug}.json").write_text(json.dumps(data))
    return deck


@pytest.fixture()
def office(monkeypatch):
    return fake_libreoffice.install(monkeypatch)


@pytest.fixture()
def partial_builds(monkeypatch) -> list[set]:
    builds: list[set] = []
    real = sdpm.api.generate

    def spy(*args, **kwargs):
        if kwargs.get("only_slugs") is not None:
            builds.append(set(kwargs["only_slugs"]))
        return real(*args, **kwargs)

    monkeypatch.setattr(sdpm.api, "generate", spy)
    return builds


def test_nothing_to_do_builds_nothing(tmp_path, office):
    deck = _deck(tmp_path)
    with refresh_pptx(deck, ["specs/brief.md"]) as r:
        assert r.plan == {"build": False, "artifact": False, "verify": False}
        assert r.result == {} and r.pptx_path is None and r.render_slugs == []
    assert not (deck / "output.pptx").exists() and office.calls == []


def test_change_renders_the_affected_slide_without_measuring(tmp_path, office, partial_builds):
    deck = _deck(tmp_path)
    with refresh_pptx(deck, ["slides/body.json"]) as r:
        assert r.pptx_path == deck / "output.pptx" and r.pptx_path.read_bytes()[:2] == b"PK"
        assert r.render_slugs == ["body"] and r.compose_slugs == ["body"]
        assert r.result == {}  # no measure_slides: no measure, warnings or errors
    assert partial_builds == [{"body"}]


def test_override_child_renders_with_its_base(tmp_path, office, partial_builds):
    slides = {"demo-1": {"layout": "Blank", "elements": []},
              "demo-2": {"layout": "Blank", "override": "demo-1", "elements": []}}
    with refresh_pptx(_deck(tmp_path, slides), ["slides/demo-2.json"]) as r:
        assert r.render_slugs == ["demo-2"]
        assert r.compose(None).slides.keys() == {"demo-2"}
    assert partial_builds == [{"demo-1", "demo-2"}]


def test_measure_reports_for_the_measured_slugs_only(tmp_path, office):
    with refresh_pptx(_deck(tmp_path), [], ["body", "bad"]) as r:
        assert r.plan == {"build": True, "artifact": False, "verify": True}
        assert r.render_slugs == ["body", "bad"]
        assert r.compose_slugs == ["body"]  # a fallback-layout slide is not composed
        res = r.result
    assert res["measure"].startswith("📐 Text measurement") and "Slide body:" in res["measure"]
    assert "Slide cover:" not in res["measure"]
    assert [b["slide"] for b in res["warnings"]["layoutBias"]] == [2, 3]  # full-deck pages
    assert all("page02(body)" in w for w in res["warnings"]["build"])
    assert res["errors"] == {"bad": {"invalidLayout": "No Such Layout", "available": res["errors"]["bad"]["available"]}}
    assert "Blank" in res["errors"]["bad"]["available"]
    assert "preview" not in res


def test_measuring_one_slide_drops_the_other_slides_warnings(tmp_path, office):
    with refresh_pptx(_deck(tmp_path), [], ["cover"]) as r:
        assert "warnings" not in r.result and "errors" not in r.result


def test_unknown_slug(tmp_path, office):
    with refresh_pptx(_deck(tmp_path), [], ["ghost"]) as r:
        assert r.result == {"measure": json.dumps({"error": "No matching slides found for given slugs"})}
        assert r.render_slugs == []


def test_without_libreoffice(tmp_path, monkeypatch):
    fake_libreoffice.install(monkeypatch, available=False)
    with refresh_pptx(_deck(tmp_path), ["slides/body.json"], ["body"]) as r:
        assert r.pptx_path is not None
        assert r.result["measure"] == json.dumps({"error": "LibreOffice SVG export failed"})
        assert r.result["preview"]["status"] == "unavailable"
        assert r.compose(None).defs is None
        assert r.previews().rendered is False


def test_full_build_failure_still_renders_the_edited_slide(tmp_path, office):
    slides = {**SLIDES, "cover": {"layout": "Blank", "elements": [{"type": "image", "src": "assets:none/missing"}]}}
    with refresh_pptx(_deck(tmp_path, slides), ["slides/body.json"], ["body"]) as r:
        assert "Missing assets" in r.result["pptx_error"] and r.pptx_path is None
        assert r.render_slugs == ["body"] and r.render_error is None
        assert r.result["measure"].startswith("📐 Text measurement")
        assert r.compose(None).slides.keys() == {"body"}


def test_compose_marks_changes_against_the_previous_payload(tmp_path, office):
    deck = _deck(tmp_path)
    with refresh_pptx(deck, ["slides/body.json"]) as r:
        first = r.compose(None)
    body = first.slides["body"]
    assert first.defs["version"] == 1 and first.shortfall is None and first.error is None
    assert body["regions"] == [{"name": "content", "x": 60, "y": 160, "w": 900, "h": 400}]
    assert body["sourceHash"] and all(c["changed"] for c in body["components"])
    assert any('fill-rule="evenodd"' in c["svg"] for c in body["components"])

    with refresh_pptx(deck, ["slides/body.json"]) as r:  # same JSON: nothing changed
        assert not any(c["changed"] for c in r.compose({"body": body}).slides["body"]["components"])
    stale = {**body, "sourceHash": "old", "components": [{**c, "text": "other"} for c in body["components"]]}
    with refresh_pptx(deck, ["slides/body.json"]) as r:
        changed = [c["changed"] for c in r.compose({"body": stale}).slides["body"]["components"]]
    assert changed == [bool(c["text"]) for c in body["components"]]


def test_compose_also_joins_only_a_render(tmp_path, office):
    deck = _deck(tmp_path)
    with refresh_pptx(deck, [], ["body"], compose_also=["cover", "bad", "ghost"]) as r:
        assert r.render_slugs == ["body"] and r.compose_slugs == ["cover", "body"]
    with refresh_pptx(deck, [], ["ghost"], compose_also=["cover"]) as r:
        assert r.compose_slugs == []


def test_compose_reports_a_short_svg(tmp_path, office, monkeypatch):
    import sdpm.engine.preview.compose as compose_mod

    monkeypatch.setattr(compose_mod, "count_slides", lambda tree: 2)
    with refresh_pptx(_deck(tmp_path), ["specs/outline.md"]) as r:
        out = r.compose(None)
    assert out.shortfall.startswith("LibreOffice exported only 1 slide(s) to SVG but 3 were rendered")
    assert out.slides.keys() == {"cover"}


def test_previews_and_close(tmp_path, office):
    from PIL import Image

    with refresh_pptx(_deck(tmp_path), ["specs/outline.md"]) as r:
        wide = r.previews()
        assert wide.rendered and list(wide.files) == ["cover", "body", "bad"] and wide.missing == []
        assert Image.open(wide.files["body"]).size[0] == 1280
        assert Image.open(r.previews(scale_to=None, dpi=200).files["body"]).size[0] == 40
        work = wide.files["body"].parents[1]
        assert work.parent == r.deck_dir / "_work"
    assert not work.exists()
    r.close()  # idempotent


def test_merge_into_keeps_adapter_warnings_and_errors():
    r = sdpm.api.PptxRefresh(Path("."), {"build": True, "artifact": True, "verify": True})
    r.result = {"warnings": {"build": ["page01 x"]}, "errors": {"a": {"invalidLayout": "X"}}, "measure": "m"}
    result = {"warnings": {"outline": "o"}, "errors": {"lintDiagnostics": [1]}}
    r.merge_into(result)
    assert result == {"warnings": {"outline": "o", "build": ["page01 x"]},
                      "errors": {"lintDiagnostics": [1], "a": {"invalidLayout": "X"}}, "measure": "m"}


def test_generate_include_checks_returns_checks_instead_of_bias_lines(tmp_path):
    deck = _deck(tmp_path)
    plain = sdpm.api.generate(deck, output_path=tmp_path / "a.pptx")
    checked = sdpm.api.generate(deck, output_path=tmp_path / "b.pptx", include_checks=True)
    assert "checks" not in plain and any("offset:" in w for w in plain["warnings"])
    assert not any("offset:" in w for w in checked["warnings"])
    assert [b["slide"] for b in checked["checks"]["layout_bias"]] == [2, 3]
    [invalid] = checked["checks"]["invalid_layouts"]
    assert invalid["slug"] == "bad" and "Blank" in invalid["available"]
    assert checked["invalid_layouts"] == plain["invalid_layouts"]
