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


def test_an_identity_on_a_group_child_is_reported_as_inert():
    """A group is flattened, but nothing registers its children's identities.

    So an `id` there did nothing at all and an effect naming it failed the build
    with "known element ids: none", which does not explain why an id the JSON
    visibly carries was not seen. Moving the child out of the group changes no
    geometry, so the diagnostic can name the fix.
    """
    slide = _slide()
    slide["elements"] = [{
        "type": "group", "x": 10, "y": 10, "width": 400, "height": 200,
        "elements": [
            {"id": "inner", "type": "shape", "shape": "rectangle",
             "x": 0, "y": 0, "width": 100, "height": 50, "fill": "#FFFFFF"},
            {"morphId": "card", "type": "shape", "shape": "rectangle",
             "x": 0, "y": 60, "width": 100, "height": 50, "fill": "#FFFFFF"},
        ],
    }]
    slide["animations"]["mainSequence"][0]["target"]["element"] = "inner"

    diagnostics = validate_slide_motion(slide)
    inert = [d for d in diagnostics if d.rule == "inert-group-child-identity"]
    assert [d.path for d in inert] == [
        "elements[0].elements[0].id", "elements[0].elements[1].morphId",
    ]
    assert "move the element out of the group" in inert[0].message
    # The id is reported, not adopted: it is still not a usable target.
    assert any(d.rule == "unknown-animation-target" for d in diagnostics)


def test_a_nested_group_child_identity_is_reported_too():
    slide = _slide()
    slide["elements"] = [{
        "type": "group", "x": 0, "y": 0, "width": 400, "height": 200,
        "elements": [{
            "type": "group", "x": 0, "y": 0, "width": 200, "height": 100,
            "elements": [{"id": "deep", "type": "shape", "shape": "rectangle",
                          "x": 0, "y": 0, "width": 50, "height": 50, "fill": "#FFFFFF"}],
        }],
    }]
    paths = [d.path for d in validate_slide_motion(slide)
             if d.rule == "inert-group-child-identity"]
    assert paths == ["elements[0].elements[0].elements[0].id"]


def test_an_unexpanded_include_suspends_the_target_rule_only():
    """The element set an include contributes is not knowable from this slide.

    The builder expands it at build time, so validating membership here reported
    a valid included target as unknown. Every other rule still applies, and the
    build still refuses a target that resolves to nothing.
    """
    slide = _slide()
    slide["elements"] = [{"type": "include", "include": "includes/cards.json"}]
    slide["animations"]["mainSequence"][0]["target"]["element"] = "lives-in-the-include"
    slide["animations"]["interactiveSequences"] = [{
        "id": "details",
        "trigger": {"type": "onShapeClick", "target": "also-in-the-include"},
        "effects": [],
    }]

    rules = {item.rule for item in validate_slide_motion(slide)}
    assert "unknown-animation-target" not in rules
    assert "unknown-trigger-target" not in rules

    # The rule is suspended, not the validation.
    slide["animations"]["mainSequence"][0]["id"] = "not a valid id"
    slide["animations"]["interactiveSequences"][0]["trigger"]["target"] = 7
    rules = {item.rule for item in validate_slide_motion(slide)}
    assert "invalid-effect-id" in rules
    assert "unknown-trigger-target" in rules, "a non-string target is still wrong"


def test_motion_is_validated_after_overrides_resolve(tmp_path):
    """An effect may target an element its slide inherits rather than declares.

    `_resolve_config` used to lint the unresolved slides, so a valid inherited
    target was reported as `unknown-animation-target` on every build.
    """
    import json

    from sdpm.api import _resolve_config

    deck = tmp_path / "deck"
    (deck / "slides").mkdir(parents=True)
    (deck / "specs").mkdir()
    (deck / "deck.json").write_text(json.dumps({
        "template": "blank-light",
        "animations": {"enabled": True},
    }))
    (deck / "slides" / "base.json").write_text(json.dumps({
        "id": "base", "layout": "Blank",
        "elements": [
            {"id": "inherited", "type": "textbox", "text": "A",
             "x": 10, "y": 10, "width": 300, "height": 60},
        ],
    }))
    (deck / "slides" / "derived.json").write_text(json.dumps({
        "id": "derived", "layout": "Blank", "override": "base",
        "animations": {
            "mainSequence": [{
                "id": "reveal", "target": {"element": "inherited"},
                "preset": {"category": "entrance", "effect": "fade"},
                "start": {"type": "onPageClick", "delayMs": 0},
                "timing": {"durationMs": 400},
            }],
            "interactiveSequences": [],
        },
    }))
    (deck / "specs" / "outline.md").write_text("- [base] base\n- [derived] derived\n")

    config = _resolve_config(str(deck), animation_mode=None, transition_mode=None)
    rules = {d["rule"] for d in config.lint_diagnostics}
    assert "unknown-animation-target" not in rules, config.lint_diagnostics

    # The save path sees one slide at a time and cannot resolve `override`, so
    # it suspends the membership rule rather than reporting a target it cannot
    # check. The two paths agree about this deck.
    from sdpm.engine.schema.lint import lint, lint_and_sanitize

    derived = json.loads((deck / "slides" / "derived.json").read_text())
    _cleaned, diagnostics = lint_and_sanitize(derived)
    assert "unknown-animation-target" not in {d["rule"] for d in diagnostics}, diagnostics
    assert "unknown-animation-target" not in {
        d["rule"] for d in lint({"slides": [derived]})
    }

    # Suspending it on the unresolved form must not let a real mistake through
    # on the build path, which lints the resolved and expanded slide.
    derived["animations"]["mainSequence"][0]["target"]["element"] = "inhreited"
    (deck / "slides" / "derived.json").write_text(json.dumps(derived, ensure_ascii=False))
    broken = _resolve_config(str(deck), animation_mode=None, transition_mode=None)
    assert "unknown-animation-target" in {d["rule"] for d in broken.lint_diagnostics}


def _include_deck(tmp_path, slugs, *, target, broken_slug):
    """A deck whose slides each carry an `include`, one with a bad target."""
    import json

    deck = tmp_path / "deck"
    (deck / "slides").mkdir(parents=True)
    (deck / "specs").mkdir()
    (deck / "includes").mkdir()
    (deck / "deck.json").write_text(json.dumps({
        "template": "blank-light",
        "animations": {"enabled": True},
    }))
    (deck / "includes" / "panel.json").write_text(json.dumps([
        {"id": "panel", "type": "shape", "shape": "rectangle",
         "x": 400, "y": 300, "width": 200, "height": 100, "fill": "#333333"},
    ]))
    for slug in slugs:
        (deck / "slides" / f"{slug}.json").write_text(json.dumps({
            "id": slug, "layout": "Blank",
            "elements": [
                {"id": "hero", "type": "textbox", "text": slug,
                 "x": 10, "y": 10, "width": 300, "height": 60},
                {"type": "include", "src": "includes/panel.json"},
            ],
            "animations": {
                "mainSequence": [{
                    "id": "reveal",
                    "target": {"element": target if slug == broken_slug else "panel"},
                    "preset": {"category": "entrance", "effect": "fade"},
                    "start": {"type": "onPageClick", "delayMs": 0},
                    "timing": {"durationMs": 400},
                }],
                "interactiveSequences": [],
            },
        }, ensure_ascii=False))
    (deck / "specs" / "outline.md").write_text("".join(f"- [{s}] {s}\n" for s in slugs))
    return deck


def test_an_include_does_not_hide_a_misspelled_target_on_the_build_path(tmp_path):
    """The membership rule is suspended for the linter, not for the build.

    `validate_slide_motion` cannot read an include, so it suspends the rule
    rather than reporting an included target as unknown. The build resolves the
    include, so it has no reason to inherit that suspension — and while it did,
    a misspelled target on a slide with *any* include got no diagnostic at all.
    """
    from sdpm.api import _resolve_config

    # The valid case first, so the suspension is doing its job.
    good = _resolve_config(
        str(_include_deck(tmp_path / "good", ["only"], target="panel", broken_slug="only")),
        animation_mode=None, transition_mode=None,
    )
    assert "unknown-animation-target" not in {d["rule"] for d in good.lint_diagnostics}, (
        "the include really does provide `panel`"
    )

    bad = _resolve_config(
        str(_include_deck(tmp_path / "bad", ["only"], target="pannel", broken_slug="only")),
        animation_mode=None, transition_mode=None,
    )
    assert "unknown-animation-target" in {d["rule"] for d in bad.lint_diagnostics}, (
        f"a misspelled target is still a mistake: {bad.lint_diagnostics}"
    )


def test_only_slugs_numbers_a_diagnostic_by_its_deck_position(tmp_path):
    """A partial build must not renumber the slides it kept.

    On the legacy `presentation.json` path the filter runs inside
    `_resolve_config`, after `lint` has already numbered the whole deck. Motion
    is linted on the filtered list, so it numbered from zero — and both sets
    land in one diagnostics list whose `slide` is a bare integer, where a
    finding about the third slide read as one about the first. (A deck
    directory filters at assembly, so there both start from the same list.)
    """
    import json

    from sdpm.api import _resolve_config

    slugs = ["title", "intro", "details", "closing"]
    slides = []
    for slug in slugs:
        slides.append({
            "id": slug, "layout": "Blank",
            "elements": [{"id": "hero", "type": "textbox", "text": slug,
                          "x": 10, "y": 10, "width": 300, "height": 60}],
            "animations": {
                "mainSequence": [{
                    "id": "reveal",
                    "target": {"element": "heor" if slug == "details" else "hero"},
                    "preset": {"category": "entrance", "effect": "fade"},
                    "start": {"type": "onPageClick", "delayMs": 0},
                    "timing": {"durationMs": 400},
                }],
                "interactiveSequences": [],
            },
        })
    presentation = tmp_path / "presentation.json"
    presentation.write_text(json.dumps({
        "template": "blank-light",
        "animations": {"enabled": True},
        "slides": slides,
    }, ensure_ascii=False))

    def targets(config):
        return [d["slide"] for d in config.lint_diagnostics
                if d["rule"] == "unknown-animation-target"]

    whole = _resolve_config(str(presentation), animation_mode=None, transition_mode=None)
    assert targets(whole) == [slugs.index("details")], whole.lint_diagnostics

    partial = _resolve_config(
        str(presentation), only_slugs={"details"},
        animation_mode=None, transition_mode=None,
    )
    assert targets(partial) == [slugs.index("details")], (
        "the kept slide keeps the number it has in the deck: "
        f"{partial.lint_diagnostics}"
    )


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
