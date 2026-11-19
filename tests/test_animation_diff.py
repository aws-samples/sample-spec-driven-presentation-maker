# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Hand-edit diff for motion: transitions, timelines, preserved raw fallback.

A hand-edit report is read by a person deciding what to keep, so it has to
answer "what moved?" and not "here is 40 KB of timing XML" (REQ-8.4). Two
properties carry that:

* effects are compared by **stable ID**, so reordering the same effects is a
  move rather than a wall of unrelated property changes (REQ-2.5);
* a raw fallback is summarized by digest and the targets it animates — the
  sidecar XML itself never reaches the report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdpm.engine.diff import diff_slides

P_EFFECT = {"category": "entrance", "effect": "fade", "variant": None}


def _effect(effect_id: str, element: str = "hero", **patch) -> dict:
    effect = {
        "id": effect_id,
        "target": {"element": element},
        "preset": dict(P_EFFECT),
        "start": {"type": "onPageClick", "delayMs": 0},
        "timing": {"durationMs": 500},
        "afterEffect": {"type": "none"},
        "sound": None,
    }
    effect.update(patch)
    return effect


def _transition(effect="fade", **patch) -> dict:
    transition = {
        "effect": effect,
        "parameters": {},
        "durationMs": 800,
        "advance": {"onClick": True, "afterMs": None},
        "sound": None,
    }
    transition.update(patch)
    return transition


def _slide(**patch) -> dict:
    slide = {
        "layout": "Blank",
        "elements": [
            {"id": "hero", "type": "textbox", "text": "Hero", "x": 10, "y": 10,
             "width": 300, "height": 60},
            {"id": "aside", "type": "textbox", "text": "Aside", "x": 10, "y": 120,
             "width": 300, "height": 60},
        ],
    }
    slide.update(patch)
    return slide


def _deck(slide: dict, manifest: dict | None = None) -> dict:
    deck: dict = {"slides": [slide]}
    if manifest is not None:
        deck["_rawManifest"] = manifest
    return deck


def _report(base_slide: dict, edit_slide: dict, *, base_manifest=None, edit_manifest=None) -> str:
    result = diff_slides(_deck(base_slide, base_manifest), _deck(edit_slide, edit_manifest))
    return result["report"]


# --- transitions -----------------------------------------------------------


class TestTransitionDiff:
    def test_an_added_transition_is_reported(self):
        report = _report(_slide(), _slide(transition=_transition()))
        assert "transition ADDED" in report and "fade" in report

    def test_a_removed_transition_is_reported(self):
        report = _report(_slide(transition=_transition()), _slide())
        assert "transition REMOVED" in report and "fade" in report

    def test_a_changed_effect_shows_both_values(self):
        report = _report(
            _slide(transition=_transition("fade")),
            _slide(transition=_transition("wipe")),
        )
        assert "transition.effect" in report
        assert '"fade" → "wipe"' in report

    @pytest.mark.parametrize("field,value", [
        ("durationMs", 2000),
        ("advance", {"onClick": False, "afterMs": 3000}),
        ("parameters", {"direction": "left"}),
        ("sound", {"src": "media/chime.wav", "mediaType": "audio/wav", "loop": False}),
    ])
    def test_every_transition_field_change_is_reported(self, field, value):
        report = _report(
            _slide(transition=_transition()),
            _slide(transition=_transition(**{field: value})),
        )
        assert f"transition.{field}" in report

    def test_an_unchanged_transition_is_silent(self):
        result = diff_slides(
            _deck(_slide(transition=_transition())),
            _deck(_slide(transition=_transition())),
        )
        assert result["has_diff"] is False


# --- animation timelines ---------------------------------------------------


class TestAnimationDiff:
    def test_an_added_effect_is_reported_with_its_target(self):
        report = _report(
            _slide(animations={"mainSequence": [_effect("one")]}),
            _slide(animations={"mainSequence": [_effect("one"), _effect("two", "aside")]}),
        )
        assert "animation ADDED mainSequence[1] two" in report
        assert "on aside" in report

    def test_a_removed_effect_is_reported(self):
        report = _report(
            _slide(animations={"mainSequence": [_effect("one"), _effect("two", "aside")]}),
            _slide(animations={"mainSequence": [_effect("one")]}),
        )
        assert "animation REMOVED mainSequence[1] two" in report

    def test_a_reorder_of_the_same_effects_is_a_move_not_a_rewrite(self):
        """The whole point of stable IDs: swapping two effects must read as two
        moves, not as every property of both effects having changed."""
        first, second = _effect("one"), _effect("two", "aside")
        report = _report(
            _slide(animations={"mainSequence": [first, second]}),
            _slide(animations={"mainSequence": [second, first]}),
        )
        assert "animation MOVED mainSequence[0] → [1] one" in report
        assert "animation MOVED mainSequence[1] → [0] two" in report
        assert "ADDED" not in report and "REMOVED" not in report
        assert "durationMs" not in report, "a move is not a property change"

    def test_a_property_change_keeps_the_effect_identity(self):
        report = _report(
            _slide(animations={"mainSequence": [_effect("one")]}),
            _slide(animations={"mainSequence": [_effect("one", timing={"durationMs": 1200})]}),
        )
        assert "animation mainSequence[0] one" in report
        assert "timing:" in report and "1200" in report
        assert "MOVED" not in report

    def test_a_retargeted_effect_reports_the_new_target(self):
        report = _report(
            _slide(animations={"mainSequence": [_effect("one", "hero")]}),
            _slide(animations={"mainSequence": [_effect("one", "aside")]}),
        )
        assert "target:" in report and "aside" in report

    def test_a_move_and_a_property_change_are_both_reported(self):
        first, second = _effect("one"), _effect("two", "aside")
        report = _report(
            _slide(animations={"mainSequence": [first, second]}),
            _slide(animations={"mainSequence": [second, _effect("one", timing={"durationMs": 50})]}),
        )
        assert "animation MOVED mainSequence[0] → [1] one" in report
        assert "animation mainSequence[1] one" in report and "50" in report

    def test_effects_without_explicit_ids_compare_by_derived_fingerprint(self):
        """An imported deck may carry effects whose ID was derived rather than
        authored; the two sides still have to line up."""
        bare = {k: v for k, v in _effect("x").items() if k != "id"}
        other = {k: v for k, v in _effect("y", "aside").items() if k != "id"}
        result = diff_slides(
            _deck(_slide(animations={"mainSequence": [bare, other]})),
            _deck(_slide(animations={"mainSequence": [bare, other]})),
        )
        assert result["has_diff"] is False

        moved = _report(
            _slide(animations={"mainSequence": [bare, other]}),
            _slide(animations={"mainSequence": [other, bare]}),
        )
        assert moved.count("animation MOVED") == 2

    def test_an_interactive_sequence_is_compared_by_its_own_id(self):
        base = _slide(animations={"mainSequence": [], "interactiveSequences": [
            {"id": "details", "trigger": {"type": "onShapeClick", "target": "hero"},
             "effects": [_effect("one"), _effect("two", "aside")]},
        ]})
        edit = _slide(animations={"mainSequence": [], "interactiveSequences": [
            {"id": "details", "trigger": {"type": "onShapeClick", "target": "aside"},
             "effects": [_effect("two", "aside")]},
        ]})
        report = _report(base, edit)
        assert "interactive[details].trigger" in report
        assert "animation REMOVED interactive[details][0] one" in report
        assert "animation MOVED interactive[details][1] → [0] two" in report

    def test_a_whole_added_sequence_is_reported_once(self):
        report = _report(
            _slide(animations={"mainSequence": []}),
            _slide(animations={"mainSequence": [], "interactiveSequences": [
                {"id": "details", "trigger": {"type": "onShapeClick", "target": "hero"},
                 "effects": [_effect("one")]},
            ]}),
        )
        assert "animation ADDED sequence interactive[details]" in report
        assert "animation ADDED interactive[details][0] one" in report

    def test_an_unchanged_timeline_is_silent(self):
        slide = _slide(animations={"mainSequence": [_effect("one"), _effect("two", "aside")]})
        assert diff_slides(_deck(slide), _deck(slide))["has_diff"] is False


# --- raw fallback ----------------------------------------------------------


def _raw_reference(digest: str) -> dict:
    return {
        "sidecar": "animations/slide-001-timing.xml",
        "sha256": digest,
        "manifest": "animations/manifest.json",
        "reason": "mainSequence click group p:cTn carries unsupported attributes",
    }


def _raw_manifest(digest: str, targets=("hero", "aside")) -> dict:
    return {
        "version": 1,
        "sidecars": [{
            "slide": "slide-001",
            "kind": "timing",
            "path": "animations/slide-001-timing.xml",
            "sha256": digest,
            "shapeMappings": {str(100 + i): name for i, name in enumerate(targets)},
            "mediaBoundary": "classified",
            "relationships": [],
        }],
        "parts": [],
        "assets": [],
    }


class TestRawFallbackSummary:
    def test_a_changed_sidecar_is_summarized_by_digest_and_targets(self):
        report = _report(
            _slide(_rawTiming=_raw_reference("a" * 64)),
            _slide(_rawTiming=_raw_reference("b" * 64)),
            base_manifest=_raw_manifest("a" * 64),
            edit_manifest=_raw_manifest("b" * 64),
        )
        assert "raw timing CHANGED" in report
        assert "a" * 12 in report and "b" * 12 in report
        assert "targets: aside, hero" in report
        assert "<p:" not in report and "p:cTn id=" not in report, "no XML in the report"
        assert len(report) < 600

    def test_an_identical_sidecar_is_silent(self):
        reference = _raw_reference("c" * 64)
        slide = _slide(_rawTiming=reference)
        manifest = _raw_manifest("c" * 64)
        result = diff_slides(_deck(slide, manifest), _deck(slide, manifest))
        assert result["has_diff"] is False

    def test_raw_fallback_appearing_or_disappearing_is_reported(self):
        added = _report(
            _slide(),
            _slide(_rawTiming=_raw_reference("d" * 64)),
            edit_manifest=_raw_manifest("d" * 64),
        )
        assert "raw timing ADDED" in added and "d" * 12 in added

        removed = _report(
            _slide(_rawTransition=_raw_reference("e" * 64)),
            _slide(),
            base_manifest=_raw_manifest("e" * 64),
        )
        assert "raw transition REMOVED" in removed

    def test_the_summary_survives_a_missing_manifest(self):
        """A source-JSON baseline has no converted manifest; the digest alone
        still has to be reportable."""
        report = _report(
            _slide(_rawTiming=_raw_reference("f" * 64)),
            _slide(_rawTiming=_raw_reference("0" * 64)),
        )
        assert "raw timing CHANGED" in report
        assert "targets:" not in report


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """One animated deck, built once: the real generate → convert → diff path."""
    from sdpm.api import generate

    root = tmp_path_factory.mktemp("animated")
    template = Path(__file__).resolve().parent.parent / "sdpm" / "templates" / "blank-dark.pptx"
    deck = root / "deck"
    (deck / "slides").mkdir(parents=True)
    (deck / "specs").mkdir()
    (deck / "deck.json").write_text(json.dumps({
        "template": "template.pptx",
        "fonts": {"fullwidth": "Meiryo", "halfwidth": "Arial"},
        "defaultTextColor": "#FFFFFF",
        "animations": {"enabled": True},
        "transitions": {"enabled": True},
    }))
    (deck / "template.pptx").write_bytes(template.read_bytes())
    (deck / "specs" / "outline.md").write_text("- [animated] Animated slide\n")
    (deck / "slides" / "animated.json").write_text(json.dumps(_slide(
        animations={"mainSequence": [
            _effect("show-hero", "hero"),
            _effect("show-aside", "aside", start={"type": "afterPrevious", "delayMs": 0}),
        ]},
        transition=_transition(),
    )))
    pptx = root / "built.pptx"
    generate(deck, output_path=pptx)
    return deck, pptx


class TestEndToEndHandEditDiff:
    """The real ``diff_pptx`` path over an animated deck.

    Two things can only be shown here: that a lossless roundtrip of a deck
    with motion produces **no** diff (a motion comparison that reports noise
    is worse than none), and that a reorder is still a move once the effects
    have been through the converter rather than typed by hand.
    """

    def test_an_untouched_animated_deck_reports_no_diff(self, built):
        from sdpm.api import diff_report

        deck, pptx = built
        result = diff_report(deck, pptx)
        assert result["has_diff"] is False, result["report"]

    def test_a_reorder_of_converted_effects_reads_as_two_moves(self, built):
        from sdpm.api import load_slides_json_or_pptx

        _deck_dir, pptx = built
        baseline = load_slides_json_or_pptx(str(pptx))
        sequence = baseline["slides"][0]["animations"]["mainSequence"]
        assert len(sequence) == 2, "the fixture's timeline survived the roundtrip"

        edited = json.loads(json.dumps(baseline))
        edited["slides"][0]["animations"]["mainSequence"] = list(reversed(sequence))
        report = diff_slides(baseline, edited)["report"]
        assert report.count("animation MOVED") == 2, report
        assert "ADDED" not in report and "REMOVED" not in report


class TestLoaderAttachesTheManifest:
    def test_the_roundtrip_loader_reads_the_sidecar_manifest(self, tmp_path: Path):
        from sdpm.api import _load_deck_as_roundtrip

        deck = tmp_path / "rt"
        (deck / "slides").mkdir(parents=True)
        (deck / "animations").mkdir()
        (deck / "deck.json").write_text(json.dumps({"animations": {"enabled": True}}))
        (deck / "slides" / "slide-001.json").write_text(
            json.dumps(_slide(_rawTiming=_raw_reference("a" * 64)))
        )
        (deck / "animations" / "manifest.json").write_text(json.dumps(_raw_manifest("a" * 64)))

        data = _load_deck_as_roundtrip(deck)
        assert data["_rawManifest"]["sidecars"][0]["shapeMappings"] == {"100": "hero", "101": "aside"}

    def test_a_deck_without_preserved_motion_has_no_manifest_key(self, tmp_path: Path):
        from sdpm.api import _load_deck_as_roundtrip

        deck = tmp_path / "plain"
        (deck / "slides").mkdir(parents=True)
        (deck / "deck.json").write_text("{}")
        (deck / "slides" / "slide-001.json").write_text(json.dumps(_slide()))
        assert "_rawManifest" not in _load_deck_as_roundtrip(deck)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
