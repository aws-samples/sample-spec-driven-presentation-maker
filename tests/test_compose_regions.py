# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Adapter integration tests for live-preview regions in compose output."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LOCAL = str(_ROOT / "servers" / "local")
if _LOCAL not in sys.path:
    sys.path.insert(0, _LOCAL)

import compose  # noqa: E402
import sandbox_tools  # noqa: E402


def test_local_compose_output_includes_regions(tmp_path: Path, monkeypatch):
    (tmp_path / "slides").mkdir()
    (tmp_path / "specs").mkdir()
    (tmp_path / "includes").mkdir()
    (tmp_path / "deck.json").write_text('{"template": "blank-dark"}', encoding="utf-8")
    (tmp_path / "specs" / "outline.md").write_text("- [title] Hello\n", encoding="utf-8")
    (tmp_path / "slides" / "title.json").write_text(
        json.dumps(
            {
                "elements": [
                    {"_comment": "region: body", "x": 100, "y": 120, "w": 900, "h": 700},
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_generate(json_path=None, output_path=None, **kwargs):
        Path(output_path).write_bytes(b"pptx")
        return {"output_path": str(output_path), "warnings": [], "errors": {}}

    import sdpm.api
    import sdpm.engine.preview
    import sdpm.engine.preview.judge
    import sdpm.engine.preview.measure

    monkeypatch.setattr(sdpm.api, "generate", fake_generate)
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/soffice" if name == "soffice" else None)
    monkeypatch.setattr(compose, "count_slides", lambda path: 2)
    monkeypatch.setattr(compose, "extract_optimized_defs", lambda path: {"version": 1, "defs": ""})
    monkeypatch.setattr(
        compose,
        "split_slide_components",
        lambda path, slide_num: {
            "version": 1,
            "viewBox": "0 0 1920 1080",
            "bgFill": "#000",
            "bgSvg": None,
            "components": [],
        },
    )
    monkeypatch.setattr(sdpm.engine.preview.measure, "measure_from_svg", lambda *args, **kwargs: [])
    monkeypatch.setattr(sdpm.engine.preview.measure, "format_measure_report", lambda *args, **kwargs: "ok")
    monkeypatch.setattr(sdpm.engine.preview.judge, "judge_from_svg", lambda *args, **kwargs: [])
    monkeypatch.setattr(sdpm.engine.preview, "export_pdf", lambda *args, **kwargs: False)

    original_run = subprocess.run

    def fake_run(command, *args, **kwargs):
        if command and command[0] == "/fake/soffice":
            outdir = Path(command[command.index("--outdir") + 1])
            (outdir / "measure.svg").write_text("<svg />", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(sandbox_tools.subprocess, "run", fake_run)

    result = json.loads(
        sandbox_tools.run_python(
            purpose="verify title",
            code='print("ok")',
            deck_id=str(tmp_path),
            measure_slides=["title"],
        )
    )

    compose_files = list((tmp_path / "compose").glob("title_*.json"))
    assert result["compose"] == "1 slides composed"
    assert len(compose_files) == 1
    payload = json.loads(compose_files[0].read_text(encoding="utf-8"))
    assert payload["regions"] == [
        {"name": "body", "x": 100, "y": 120, "w": 900, "h": 700},
    ]


def _detected_render_rig(tmp_path: Path, monkeypatch, slides: dict[str, dict]) -> list[set]:
    """Deck with the given slides + fakes for the render pipeline.

    Returns the list of ``only_slugs`` sets passed to partial builds.
    """
    (tmp_path / "slides").mkdir()
    (tmp_path / "specs").mkdir()
    (tmp_path / "deck.json").write_text('{"template": "blank-dark"}', encoding="utf-8")
    (tmp_path / "specs" / "outline.md").write_text(
        "".join(f"- [{s}] {s}\n" for s in slides), encoding="utf-8"
    )
    for slug, data in slides.items():
        (tmp_path / "slides" / f"{slug}.json").write_text(json.dumps(data), encoding="utf-8")

    partial_builds: list[set] = []

    def fake_generate(json_path=None, output_path=None, only_slugs=None, **kwargs):
        if only_slugs is not None:
            partial_builds.append(set(only_slugs))
        Path(output_path).write_bytes(b"pptx")
        return {"output_path": str(output_path), "warnings": [], "errors": {}}

    import sdpm.api
    import sdpm.engine.preview

    monkeypatch.setattr(sdpm.api, "generate", fake_generate)
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/soffice" if name == "soffice" else None)
    # SVG holds one page per slide in the last partial build (+1: count_slides convention)
    monkeypatch.setattr(compose, "count_slides", lambda path: len(partial_builds[-1]) + 1)
    monkeypatch.setattr(compose, "extract_optimized_defs", lambda path: {"version": 1, "defs": ""})
    monkeypatch.setattr(
        compose,
        "split_slide_components",
        lambda path, slide_num: {"version": 1, "viewBox": "0 0 1920 1080", "bgFill": "#000",
                                 "bgSvg": None, "components": []},
    )
    monkeypatch.setattr(sdpm.engine.preview, "export_pdf", lambda *args, **kwargs: False)

    original_run = subprocess.run

    def fake_run(command, *args, **kwargs):
        if command and command[0] == "/fake/soffice":
            outdir = Path(command[command.index("--outdir") + 1])
            (outdir / "iso.svg").write_text("<svg />", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(sandbox_tools.subprocess, "run", fake_run)
    return partial_builds


def _composed(tmp_path: Path) -> set[str]:
    return {
        p.name.rsplit("_", 1)[0]
        for p in (tmp_path / "compose").glob("*.json")
        if not p.name.startswith("defs_")
    }


def test_local_edit_without_measure_still_rerenders_changed_slides(tmp_path: Path, monkeypatch):
    """The preview-staleness bug: a slide written but not listed in
    measure_slides must still get fresh compose data."""
    partial_builds = _detected_render_rig(
        tmp_path, monkeypatch,
        {"cover": {"elements": []}, "problem": {"elements": []}, "end": {"elements": []}},
    )

    result = json.loads(
        sandbox_tools.run_python(
            purpose="edit two slides, measure one",
            code=(
                'write_json("slides/cover.json", {"elements": [{"type": "textbox", "text": "c"}]})\n'
                'write_json("slides/problem.json", {"elements": [{"type": "textbox", "text": "p"}]})'
            ),
            deck_id=str(tmp_path),
            measure_slides=["problem"],
        )
    )

    assert partial_builds == [{"cover", "problem"}]
    assert _composed(tmp_path) == {"cover", "problem"}
    assert result["compose"] == "2 slides composed"


def test_local_edit_with_no_measure_at_all_rerenders_without_measuring(tmp_path: Path, monkeypatch):
    partial_builds = _detected_render_rig(tmp_path, monkeypatch, {"a": {"elements": []}, "b": {"elements": []}})

    result = json.loads(
        sandbox_tools.run_python(
            purpose="edit a",
            code='write_json("slides/a.json", {"elements": [{"type": "textbox", "text": "a"}]})',
            deck_id=str(tmp_path),
        )
    )

    assert partial_builds == [{"a"}]
    assert _composed(tmp_path) == {"a"}
    assert "measure" not in result
    # A missing preview renderer is not reported on automatic re-renders
    assert "preview" not in result


def test_local_override_child_renders_with_its_base(tmp_path: Path, monkeypatch):
    """Editing demo-2 builds demo-1 too (inheritance), but composes only demo-2;
    editing demo-1 re-renders demo-2, which inherits from it."""
    slides = {"demo-1": {"elements": []}, "demo-2": {"override": "demo-1", "elements": []}}
    partial_builds = _detected_render_rig(tmp_path, monkeypatch, slides)

    sandbox_tools.run_python(
        purpose="edit child",
        code='write_json("slides/demo-2.json", {"override": "demo-1", "elements": [{"type": "textbox"}]})',
        deck_id=str(tmp_path),
    )
    assert partial_builds[-1] == {"demo-1", "demo-2"}
    assert _composed(tmp_path) == {"demo-2"}

    sandbox_tools.run_python(
        purpose="edit base",
        code='write_json("slides/demo-1.json", {"elements": [{"type": "textbox", "text": "b"}]})',
        deck_id=str(tmp_path),
    )
    assert partial_builds[-1] == {"demo-1", "demo-2"}
    assert _composed(tmp_path) == {"demo-1", "demo-2"}


def test_local_read_only_run_renders_nothing(tmp_path: Path, monkeypatch):
    partial_builds = _detected_render_rig(tmp_path, monkeypatch, {"a": {"elements": []}})

    sandbox_tools.run_python(purpose="read", code='print(read_json("slides/a.json"))', deck_id=str(tmp_path))

    assert partial_builds == []
    assert not (tmp_path / "compose").exists()
