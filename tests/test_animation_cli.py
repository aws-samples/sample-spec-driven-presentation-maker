# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""CLI animation/transition overrides, exercised as a real subprocess.

REQ-9.5 asks for the CLI surface itself, not an in-process call to the same
function: argument wiring, the exit status, the message a user actually sees
and the package the command leaves behind. Importing ``cmd_generate`` would
prove none of that, so every case here spawns ``pptx_builder.py``.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "sdpm" / "scripts" / "pptx_builder.py"
TEMPLATE = REPO_ROOT / "sdpm" / "templates" / "blank-dark.pptx"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
MODES = ("inherit", "on", "off")


def _deck(tmp_path: Path, *, animations=True, transitions=True) -> Path:
    deck = tmp_path / "deck"
    (deck / "slides").mkdir(parents=True)
    (deck / "specs").mkdir()
    (deck / "deck.json").write_text(json.dumps({
        "template": "template.pptx",
        "fonts": {"fullwidth": "Meiryo", "halfwidth": "Arial"},
        "defaultTextColor": "#FFFFFF",
        "animations": {"enabled": animations},
        "transitions": {"enabled": transitions},
    }, indent=2) + "\n")
    (deck / "template.pptx").write_bytes(TEMPLATE.read_bytes())
    (deck / "specs" / "outline.md").write_text("- [animated] Animated slide\n")
    (deck / "slides" / "animated.json").write_text(json.dumps({
        "layout": "Blank",
        "elements": [
            {"id": "hero", "type": "textbox", "text": "Hero", "x": 10, "y": 10,
             "width": 300, "height": 60},
        ],
        "animations": {
            "mainSequence": [{
                "id": "show-hero",
                "target": {"element": "hero"},
                "preset": {"category": "entrance", "effect": "fade", "variant": None},
                "start": {"type": "onPageClick", "delayMs": 0},
                "timing": {"durationMs": 500},
                "afterEffect": {"type": "none"},
                "sound": None,
            }],
        },
        "transition": {
            "effect": "fade", "parameters": {}, "durationMs": 800,
            "advance": {"onClick": True, "afterMs": None}, "sound": None,
        },
    }, indent=2) + "\n")
    return deck


def _run(deck: Path, out: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), "generate_pptx", str(deck), "-o", str(out), *extra],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )


def _sources(deck: Path) -> dict[str, str]:
    return {
        str(path.relative_to(deck)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(deck.rglob("*"))
        if path.is_file() and path.suffix in {".json", ".md"}
    }


def _motion(pptx: Path) -> tuple[bool, bool]:
    """Return (has object animation, has transition) for the built package."""
    slide = list(Presentation(str(pptx)).slides)[0]
    root = etree.fromstring(etree.tostring(slide._element))
    return (
        len(root.findall(".//{%s}seq" % P)) > 0,
        len(root.findall(".//{%s}transition" % P)) > 0,
    )


# --- every mode combination ------------------------------------------------


@pytest.mark.parametrize("animation_mode", MODES)
@pytest.mark.parametrize("transition_mode", MODES)
def test_the_cli_builds_each_mode_combination(tmp_path: Path, animation_mode, transition_mode):
    """Deck has both switches on, so `off` is the only thing that can change
    the package — which is exactly what makes the override observable."""
    deck = _deck(tmp_path)
    before = _sources(deck)
    out = tmp_path / f"{animation_mode}-{transition_mode}.pptx"
    result = _run(deck, out, "--animation-mode", animation_mode,
                  "--transition-mode", transition_mode)

    assert result.returncode == 0, result.stderr
    assert "Generated:" in result.stdout
    animations, transitions = _motion(out)
    assert animations is (animation_mode != "off")
    assert transitions is (transition_mode != "off")
    assert _sources(deck) == before, "the CLI override must not rewrite the deck"


def test_the_cli_turns_a_disabled_deck_on(tmp_path: Path):
    deck = _deck(tmp_path, animations=False, transitions=False)
    out = tmp_path / "forced-on.pptx"
    assert _run(deck, out, "--animation-mode", "on", "--transition-mode", "on").returncode == 0
    assert _motion(out) == (True, True)


def test_without_overrides_the_deck_switches_decide(tmp_path: Path):
    deck = _deck(tmp_path, animations=False, transitions=True)
    out = tmp_path / "inherited.pptx"
    assert _run(deck, out).returncode == 0
    assert _motion(out) == (False, True)


# --- invalid values --------------------------------------------------------


@pytest.mark.parametrize("flag,argument", [
    ("--animation-mode", "animation_mode"),
    ("--transition-mode", "transition_mode"),
])
def test_an_invalid_mode_fails_with_the_accepted_values(tmp_path: Path, flag, argument):
    deck = _deck(tmp_path)
    out = tmp_path / "never.pptx"
    result = _run(deck, out, flag, "sideways")

    assert result.returncode != 0
    message = result.stdout + result.stderr
    assert argument in message
    for accepted in MODES:
        assert accepted in message
    assert not out.exists(), "no package is written for an invalid mode"


def test_a_missing_mode_value_is_an_argparse_error(tmp_path: Path):
    deck = _deck(tmp_path)
    result = _run(deck, tmp_path / "never.pptx", "--animation-mode")
    assert result.returncode != 0
    assert "--animation-mode" in result.stderr


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
