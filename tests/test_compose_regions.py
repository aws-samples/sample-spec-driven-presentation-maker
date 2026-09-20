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
