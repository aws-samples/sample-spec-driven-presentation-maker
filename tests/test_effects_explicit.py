"""Effects are explicit: what the slide JSON says is what renders.

python-pptx gives every autoshape/connector a default ``<p:style>`` whose
``effectRef`` points at the template theme's effect style — an outer shadow in
the Office default theme and in the bundled blank templates. The builder must
therefore always write an explicit ``<a:effectLst>`` (empty when the JSON asks
for no effect, filled when it asks for one) and point ``effectRef`` at idx 0,
because LibreOffice ignores an empty list and would still paint the theme
shadow in previews. ``"shadow": "none"`` is an explicit
off, not an unknown preset that falls back to "md".
"""

from __future__ import annotations

import json
import re
import subprocess
import zipfile
from pathlib import Path

import pytest

from sdpm import api, tools

_SP_RE = re.compile(r"<p:(sp|cxnSp)>.*?</p:\1>", re.S)


def _build_deck(tmp_path: Path, elements: list[dict]) -> Path:
    r = tools.init_deck_workspace(str(tmp_path / "deck"))
    deck = Path(r.get("output_dir", str(tmp_path / "deck")))
    api.apply_style(deck, "report", "blank-light")
    (deck / "specs" / "outline.md").write_text(
        "# T\n\n## A\n- [one] Claim\n  - body: b\n  - visual: v\n  - evidence: e\n"
    )
    (deck / "slides" / "one.json").write_text(json.dumps({"layout": "Blank", "elements": elements}))
    tools.generate_pptx(str(deck))
    return deck


def _build(tmp_path: Path, elements: list[dict]) -> list[str]:
    deck = _build_deck(tmp_path, elements)
    xml = zipfile.ZipFile(deck / "output.pptx").read("ppt/slides/slide1.xml").decode()
    return [m.group(0) for m in _SP_RE.finditer(xml)]


def _rect(**extra) -> dict:
    return {"type": "shape", "shape": "rectangle", "x": 100, "y": 300, "width": 400, "height": 200,
            "fill": "#0066FF", **extra}


@pytest.mark.parametrize(
    "elem",
    [_rect(), _rect(shadow="none"), _rect(shadow=None), _rect(shadow=False), _rect(glow="none")],
    ids=["no-key", "none", "null", "false", "glow-none"],
)
def test_shape_without_effects_gets_empty_effect_list(tmp_path: Path, elem: dict) -> None:
    (sp,) = _build(tmp_path, [elem])
    assert "<a:effectLst/>" in sp or re.search(r"<a:effectLst\s*/>|<a:effectLst></a:effectLst>", sp)
    assert "outerShdw" not in sp and "glow" not in sp


def test_shadow_preset_is_still_applied(tmp_path: Path) -> None:
    (sp,) = _build(tmp_path, [_rect(shadow="sm")])
    assert "outerShdw" in sp


def test_bevel_only_still_pins_effect_list(tmp_path: Path) -> None:
    (sp,) = _build(tmp_path, [_rect(bevel="sm")])
    assert "effectLst" in sp and "outerShdw" not in sp


def test_connector_without_effects_gets_empty_effect_list(tmp_path: Path) -> None:
    line = {"type": "line", "x1": 100, "y1": 100, "x2": 900, "y2": 100, "color": "#333333", "width": 2}
    shapes = _build(tmp_path, [line])
    cxn = [s for s in shapes if s.startswith("<p:cxnSp>")]
    assert cxn, "line should be a connector"
    assert "effectLst" in cxn[0] and "outerShdw" not in cxn[0]


_LINE = {"type": "line", "x1": 100, "y1": 700, "x2": 900, "y2": 700, "color": "#333333", "width": 4}


@pytest.mark.parametrize("elem", [_rect(), _rect(shadow="sm"), _LINE], ids=["shape", "shape-shadow", "connector"])
def test_style_effect_ref_points_at_no_theme_effect(tmp_path: Path, elem: dict) -> None:
    """LibreOffice ignores an empty effectLst, so the effectRef itself must not
    reference the theme's (shadow) effect style."""
    (sp,) = _build(tmp_path, [elem])
    assert "<p:style>" in sp, "python-pptx default style should still carry line/fill/font refs"
    assert re.findall(r'<a:effectRef idx="(\d+)"', sp) == ["0"]


def test_libreoffice_render_has_no_theme_shadow(tmp_path: Path) -> None:
    """The rendered preview (LibreOffice SVG) shows no shadow on plain shapes
    and lines; a JSON shadow still renders. LibreOffice draws a shadow as a
    group with reduced opacity (the same signal judge._in_shadow_group uses)."""
    from sdpm.engine.preview.environment import soffice_path

    soffice = soffice_path()
    if soffice is None:
        pytest.skip("LibreOffice not installed")

    def shadow_groups(elements: list[dict], name: str) -> int:
        work = tmp_path / name
        pptx = _build_deck(work, elements) / "output.pptx"
        out = work / "svg"
        subprocess.run(
            [soffice, f"-env:UserInstallation={(tmp_path / 'lo').as_uri()}", "--headless",
             "--convert-to", "svg", "--outdir", str(out), str(pptx)],
            check=True, capture_output=True, timeout=120,
        )
        svg = (out / "output.svg").read_text()
        return len(re.findall(r'style="opacity: 0\.\d+"', svg))

    assert shadow_groups([_rect(), _LINE], "plain") == 0
    assert shadow_groups([_rect(shadow="md")], "shadow") == 1
