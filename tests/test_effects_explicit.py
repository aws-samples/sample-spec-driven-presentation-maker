"""Effects are explicit: what the slide JSON says is what renders.

python-pptx gives every autoshape/connector a default ``<p:style>`` whose
``effectRef`` points at the template theme's effect style — an outer shadow in
the Office default theme and in the bundled blank templates. The builder must
therefore always write an explicit ``<a:effectLst>``: empty when the JSON asks
for no effect, filled when it asks for one. ``"shadow": "none"`` is an explicit
off, not an unknown preset that falls back to "md".
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pytest

from sdpm import api, tools

_SP_RE = re.compile(r"<p:(sp|cxnSp)>.*?</p:\1>", re.S)


def _build(tmp_path: Path, elements: list[dict]) -> list[str]:
    r = tools.init_deck_workspace(str(tmp_path / "deck"))
    deck = Path(r.get("output_dir", str(tmp_path / "deck")))
    api.apply_style(deck, "report", "blank-light")
    (deck / "specs" / "outline.md").write_text(
        "# T\n\n## A\n- [one] Claim\n  - body: b\n  - visual: v\n  - evidence: e\n"
    )
    (deck / "slides" / "one.json").write_text(json.dumps({"layout": "Blank", "elements": elements}))
    tools.generate_pptx(str(deck))
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
