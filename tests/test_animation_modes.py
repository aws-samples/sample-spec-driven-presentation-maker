# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Caller overrides on the public facade: ``generate(animation_mode=, transition_mode=)``.

Three things have to hold for an override to be usable (REQ-1.3, REQ-1.4):

1. the two modes are **independent** — turning object animations off must not
   touch slide transitions, and vice versa;
2. precedence is caller, then deck switch, then off, and the override is
   **render-time only**: no source JSON on disk may change;
3. an invalid value fails immediately, naming the argument and the accepted
   values, rather than surfacing later as a template or lint error.

The resulting package XML is what is asserted here, not the resolved booleans:
a mode that resolves correctly and then writes the wrong tree is still broken.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation

from sdpm.api import generate

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "sdpm" / "templates" / "blank-dark.pptx"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"

MODES = ("inherit", "on", "off")

_EFFECT = {
    "id": "show-hero",
    "target": {"element": "hero"},
    "preset": {"category": "entrance", "effect": "fade", "variant": None},
    "start": {"type": "onPageClick", "delayMs": 0},
    "timing": {"durationMs": 500},
    "afterEffect": {"type": "none"},
    "sound": None,
}
_TRANSITION = {
    "effect": "fade",
    "parameters": {},
    "durationMs": 800,
    "advance": {"onClick": True, "afterMs": None},
    "sound": None,
}


def _slide(**patch) -> dict:
    slide = {
        "layout": "Blank",
        "elements": [
            {"id": "hero", "type": "textbox", "text": "Hero", "x": 10, "y": 10,
             "width": 300, "height": 60},
        ],
        "animations": {"mainSequence": [dict(_EFFECT)]},
        "transition": dict(_TRANSITION),
    }
    slide.update(patch)
    return slide


def _deck(tmp_path: Path, *, animations=True, transitions=True, slide=None, name="deck") -> Path:
    """Write a one-slide deck workspace whose slide carries motion."""
    deck = tmp_path / name
    (deck / "slides").mkdir(parents=True)
    (deck / "specs").mkdir()
    deck_json: dict = {
        "template": "template.pptx",
        "fonts": {"fullwidth": "Meiryo", "halfwidth": "Arial"},
        "defaultTextColor": "#FFFFFF",
    }
    if animations is not None:
        deck_json["animations"] = {"enabled": animations}
    if transitions is not None:
        deck_json["transitions"] = {"enabled": transitions}
    (deck / "deck.json").write_text(json.dumps(deck_json, indent=2) + "\n")
    (deck / "template.pptx").write_bytes(TEMPLATE.read_bytes())
    (deck / "specs" / "outline.md").write_text("- [animated] Animated slide\n")
    (deck / "slides" / "animated.json").write_text(
        json.dumps(slide if slide is not None else _slide(), indent=2) + "\n"
    )
    return deck


def _sources(deck: Path) -> dict[str, str]:
    """SHA-256 of every source file a build must leave untouched."""
    return {
        str(path.relative_to(deck)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(deck.rglob("*"))
        if path.is_file() and path.suffix in {".json", ".md"}
    }


def _slide_xml(pptx: Path) -> etree._Element:
    slide = list(Presentation(str(pptx)).slides)[0]
    return etree.fromstring(etree.tostring(slide._element))


def _has_object_animation(root: etree._Element) -> bool:
    """True when the slide carries an object-animation sequence."""
    return len(root.findall(".//{%s}seq" % P)) > 0


def _has_transition(root: etree._Element) -> bool:
    return len(root.findall(".//{%s}transition" % P)) > 0


def _locals(root: etree._Element) -> list[str]:
    return [etree.QName(node).localname for node in root.iter() if isinstance(node.tag, str)]


# --- invalid values --------------------------------------------------------


class TestInvalidMode:
    @pytest.mark.parametrize("argument", ["animation_mode", "transition_mode"])
    @pytest.mark.parametrize("value", ["sideways", "ON", "", "true", "enabled", "1"])
    def test_an_unknown_value_names_the_argument_and_the_accepted_values(
        self, tmp_path: Path, argument: str, value: str,
    ):
        deck = _deck(tmp_path)
        with pytest.raises(ValueError) as error:
            generate(deck, output_path=tmp_path / "out.pptx", **{argument: value})
        message = str(error.value)
        assert argument in message
        for accepted in MODES:
            assert accepted in message
        assert not (tmp_path / "out.pptx").exists(), "nothing is written for an invalid mode"

    def test_the_value_is_checked_before_any_build_work(self, tmp_path: Path):
        """An invalid mode beats a missing deck: it is a caller error, so it
        must not wait for template resolution, lint or icon validation."""
        with pytest.raises(ValueError, match="transition_mode"):
            generate(tmp_path / "no-such-deck", animation_mode="on", transition_mode="nope")

    def test_a_non_string_value_is_refused(self, tmp_path: Path):
        deck = _deck(tmp_path)
        with pytest.raises(ValueError, match="animation_mode"):
            generate(deck, output_path=tmp_path / "out.pptx", animation_mode=True)


# --- the Cartesian product of both modes ----------------------------------


class TestModeMatrix:
    @pytest.mark.parametrize("deck_animations,deck_transitions", [
        (True, True), (False, False), (True, False), (False, True), (None, None),
    ])
    @pytest.mark.parametrize("animation_mode", MODES)
    @pytest.mark.parametrize("transition_mode", MODES)
    def test_every_combination_writes_exactly_what_it_resolves_to(
        self, tmp_path: Path, deck_animations, deck_transitions,
        animation_mode: str, transition_mode: str,
    ):
        deck = _deck(tmp_path, animations=deck_animations, transitions=deck_transitions)
        before = _sources(deck)
        out = tmp_path / f"{animation_mode}-{transition_mode}.pptx"
        generate(deck, output_path=out,
                 animation_mode=animation_mode, transition_mode=transition_mode)

        def expected(mode: str, deck_switch) -> bool:
            if mode != "inherit":
                return mode == "on"
            return bool(deck_switch)  # absent switch resolves to off

        root = _slide_xml(out)
        assert _has_object_animation(root) is expected(animation_mode, deck_animations)
        assert _has_transition(root) is expected(transition_mode, deck_transitions)
        assert _sources(deck) == before, "an override must not rewrite source JSON"

    def test_the_two_modes_do_not_interfere(self, tmp_path: Path):
        deck = _deck(tmp_path)
        animations_off = tmp_path / "a-off.pptx"
        transitions_off = tmp_path / "t-off.pptx"
        generate(deck, output_path=animations_off, animation_mode="off")
        generate(deck, output_path=transitions_off, transition_mode="off")

        a_root, t_root = _slide_xml(animations_off), _slide_xml(transitions_off)
        assert not _has_object_animation(a_root) and _has_transition(a_root)
        assert _has_object_animation(t_root) and not _has_transition(t_root)

    def test_the_caller_value_overrides_the_deck_in_both_directions(self, tmp_path: Path):
        off_deck = _deck(tmp_path, animations=False, transitions=False, name="off")
        on_deck = _deck(tmp_path, animations=True, transitions=True, name="on")
        forced_on = tmp_path / "forced-on.pptx"
        forced_off = tmp_path / "forced-off.pptx"
        generate(off_deck, output_path=forced_on, animation_mode="on", transition_mode="on")
        generate(on_deck, output_path=forced_off, animation_mode="off", transition_mode="off")

        on_root, off_root = _slide_xml(forced_on), _slide_xml(forced_off)
        assert _has_object_animation(on_root) and _has_transition(on_root)
        assert not _has_object_animation(off_root) and not _has_transition(off_root)

    def test_an_absent_deck_switch_still_builds_as_disabled(self, tmp_path: Path):
        """REQ-1.2/REQ-9.4: a deck written before this feature existed builds
        exactly as it did, with no motion and no error."""
        deck = _deck(tmp_path, animations=None, transitions=None)
        out = tmp_path / "legacy.pptx"
        generate(deck, output_path=out)
        root = _slide_xml(out)
        assert not _has_object_animation(root) and not _has_transition(root)


# --- animation-off keeps media playable ------------------------------------


class TestAnimationOffKeepsMedia:
    def test_media_timing_survives_animations_off(self, tmp_path: Path):
        deck = _deck(tmp_path, slide=_slide(elements=[
            {"id": "hero", "type": "textbox", "text": "Hero", "x": 10, "y": 10,
             "width": 300, "height": 60},
            {"id": "clip", "type": "video", "src": "clip.mp4", "x": 10, "y": 120,
             "width": 320, "height": 180},
        ]))
        (deck / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 128)

        out = tmp_path / "media-off.pptx"
        generate(deck, output_path=out, animation_mode="off")
        root = _slide_xml(out)
        assert not _has_object_animation(root), "object animation is suppressed"
        assert "video" in _locals(root), "REQ-1.4: media timing is not collateral damage"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
