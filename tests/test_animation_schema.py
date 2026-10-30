# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Animation/transition JSON contract and feature-switch tests."""

from __future__ import annotations

import json

import pytest

from sdpm.api import _resolve_config
from sdpm.engine.schema.lint import lint, lint_and_sanitize
from sdpm.engine.timing import (
    BEHAVIOR_TYPES,
    normalize_mode,
    resolve_enabled,
    validate_deck_switches,
    validate_slide_motion,
)


def _element(element_id: str = "hero", morph_id: str | None = None) -> dict:
    value = {
        "id": element_id,
        "type": "textbox",
        "text": "Hero",
        "x": 10,
        "y": 10,
        "width": 300,
        "height": 50,
    }
    if morph_id is not None:
        value["morphId"] = morph_id
    return value


def _effect(effect_id: str = "show-hero") -> dict:
    return {
        "id": effect_id,
        "target": {"element": "hero"},
        "preset": {"category": "entrance", "effect": "fade"},
        "start": {"type": "onPageClick", "delayMs": 0},
        "timing": {"durationMs": 500},
        "afterEffect": {"type": "none"},
        "sound": None,
    }


def _slide() -> dict:
    return {
        "elements": [_element()],
        "transition": {
            "effect": "morph",
            "parameters": {"variant": "byObject"},
            "durationMs": 800,
            "advance": {"onClick": True, "afterMs": None},
        },
        "animations": {"mainSequence": [_effect()], "interactiveSequences": []},
    }


@pytest.mark.parametrize("mode", [None, "inherit", "on", "off"])
def test_modes_are_explicit(mode):
    assert normalize_mode(mode, "animation_mode") == ("inherit" if mode is None else mode)


def test_invalid_mode_names_argument_and_values():
    with pytest.raises(ValueError, match=r"animation_mode.*inherit.*off.*on"):
        normalize_mode("yes", "animation_mode")


def test_override_precedence_and_missing_default():
    deck = {"animations": {"enabled": True}}
    assert resolve_enabled(deck, "animations", "inherit") is True
    assert resolve_enabled(deck, "animations", "off") is False
    assert resolve_enabled({}, "animations", "inherit") is False


def test_deck_switches_are_independent_and_boolean():
    assert validate_deck_switches({"animations": {"enabled": True}, "transitions": {"enabled": False}}) == []
    diagnostics = validate_deck_switches({"animations": True, "transitions": {"enabled": "yes"}})
    assert {item.rule for item in diagnostics} == {"invalid-feature-config", "invalid-enabled"}


def test_valid_timeline_and_morph_transition():
    assert validate_slide_motion(_slide()) == []
    assert lint({"slides": [_slide()]}) == []


def test_all_nine_behavior_primitives_are_accepted():
    assert BEHAVIOR_TYPES == {
        "motion", "color", "scale", "rotation", "property", "command", "filter", "set", "none",
    }
    for behavior_type in BEHAVIOR_TYPES:
        slide = {"elements": [_element()], "animations": {"mainSequence": [{
            **_effect(),
            "preset": None,
            "behaviors": [{"type": behavior_type}],
        }]}}
        del slide["animations"]["mainSequence"][0]["preset"]
        assert validate_slide_motion(slide) == []


def test_duplicate_element_effect_and_morph_ids_are_rejected():
    slide = _slide()
    slide["elements"].append(_element("hero", "same"))
    slide["elements"][0]["morphId"] = "same"
    slide["animations"]["mainSequence"].append(_effect())
    rules = {item.rule for item in validate_slide_motion(slide)}
    assert {"duplicate-element-id", "duplicate-morph-id", "duplicate-effect-id"} <= rules


def test_unknown_targets_and_trigger_targets_are_rejected():
    slide = _slide()
    slide["animations"]["mainSequence"][0]["target"]["element"] = "missing"
    slide["animations"]["interactiveSequences"] = [{
        "id": "details",
        "trigger": {"type": "onShapeClick", "target": "missing"},
        "effects": [],
    }]
    rules = {item.rule for item in validate_slide_motion(slide)}
    assert {"unknown-animation-target", "unknown-trigger-target"} <= rules


def test_raw_and_semantic_representations_are_mutually_exclusive():
    slide = _slide()
    slide["_rawTiming"] = {"src": "attachments/imports/key/timing.json"}
    slide["_rawTransition"] = {"src": "attachments/imports/key/transition.json"}
    rules = {item.rule for item in validate_slide_motion(slide)}
    assert {"animation-source-conflict", "transition-source-conflict"} <= rules


def test_sound_requires_safe_workspace_relative_audio_asset():
    slide = _slide()
    slide["animations"]["mainSequence"][0]["sound"] = {
        "src": "audio/cue.wav",
        "mediaType": "audio/wav",
        "loop": False,
    }
    assert validate_slide_motion(slide) == []
    slide["animations"]["mainSequence"][0]["sound"]["src"] = "../secret.wav"
    slide["animations"]["mainSequence"][0]["sound"]["mediaType"] = "video/mp4"
    rules = {item.rule for item in validate_slide_motion(slide)}
    assert {"invalid-sound-src", "invalid-sound-media-type"} <= rules


@pytest.mark.parametrize("variant", ["byObject", "byWord", "byChar"])
def test_all_morph_variants_are_accepted(variant):
    slide = _slide()
    slide["transition"]["parameters"]["variant"] = variant
    assert validate_slide_motion(slide) == []


def test_invalid_morph_variant_is_rejected():
    slide = _slide()
    slide["transition"]["parameters"]["variant"] = "byName"
    assert {item.rule for item in validate_slide_motion(slide)} == {"invalid-morph-variant"}


def test_lint_and_sanitize_keeps_motion_contract():
    slide = _slide()
    cleaned, diagnostics = lint_and_sanitize(slide)
    assert diagnostics == []
    assert cleaned["animations"] == slide["animations"]
    assert cleaned["transition"] == slide["transition"]


def test_resolve_config_applies_modes_without_mutating_deck(tmp_path):
    deck = tmp_path / "deck"
    (deck / "slides").mkdir(parents=True)
    (deck / "specs").mkdir()
    deck_json = {
        "template": "blank-dark.pptx",
        "fonts": {"fullwidth": "Meiryo", "halfwidth": "Arial"},
        "defaultTextColor": "#FFFFFF",
        "animations": {"enabled": True},
        "transitions": {"enabled": False},
    }
    original = json.dumps(deck_json, sort_keys=True)
    (deck / "deck.json").write_text(json.dumps(deck_json))
    (deck / "specs" / "outline.md").write_text("- [intro] Intro\n")
    (deck / "slides" / "intro.json").write_text(json.dumps({"layout": "Blank", "elements": []}))

    config = _resolve_config(deck, animation_mode="off", transition_mode="on")

    assert config.animations_enabled is False
    assert config.transitions_enabled is True
    assert json.dumps(json.loads((deck / "deck.json").read_text()), sort_keys=True) == original
