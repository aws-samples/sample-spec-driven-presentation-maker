# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Normalized round-trip equality: JSON → PPTX → JSON.

Two layers:

* **Deck level** — a real ``generate`` into a real package, converted back with
  the real importer, compared field by field. This is what catches a writer and
  a reader that each look right on their own but disagree.
* **Catalog level** — every transition form and every animation preset the
  catalog establishes in *both* directions is written and read back in one
  loop, so the coverage number is counted rather than asserted by sampling.
  The counts below are the honest state of bidirectional support: they are
  bounded by Task 4's writer gaps (262 capture-required mappings) and will grow
  when Task 8 closes them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from sdpm.api import generate
from sdpm.engine.converter.pipeline import pptx_to_json
from sdpm.engine.timing import ShapeIdentityRegistry
from sdpm.engine.timing.reader import read_slide_motion, reverse_index
from sdpm.engine.timing.transition import build_transition
from sdpm.engine.timing.writer import (
    CATALOG_TARGET_ID,
    TimingWriter,
    load_capability_index,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"

#: Counted bidirectional coverage of the checked-in catalog. A form counts only
#: when the writer can emit it *and* the reader can turn the emitted XML back
#: into the same semantic JSON.
#: Reversible forms in the catalog. The transition count rose from 93 to 147
#: when the scripting-oracle capture under
#: ``tests/fixtures/animations/oracle-16.113.1`` closed the last transition
#: gaps: an entry with no established element form has no inverse mapping
#: either, so closing the gap makes it reversible in both directions.
#: Presets went from 25 to 101 when the 2026-11-01 GUI capture measured the
#: behaviour payloads of every GUI-addressable animation value. The 76 it
#: covered are the difference: 24 emphasis tiles and 5 motion-path groups that
#: had no writable form at all, plus 47 entrance and exit tiles that were
#: refused for their payloads.
BIDIRECTIONAL_COVERAGE = {"transitions": 147, "presets": 101}

FADE = {"category": "entrance", "effect": "fade", "variant": None}

SLIDE_XML = (
    '<p:sld xmlns:p="%s" xmlns:a="%s"><p:cSld><p:spTree>'
    '<p:sp><p:nvSpPr><p:cNvPr id="2" name="catalog target"/><p:cNvSpPr/><p:nvPr/>'
    "</p:nvSpPr></p:sp></p:spTree></p:cSld></p:sld>" % (P, A)
)


def _effect(effect_id="fx", element="hero", **patch):
    effect = {
        "id": effect_id,
        "target": {"element": element},
        "preset": dict(FADE),
        "start": {"type": "onPageClick", "delayMs": 0},
        "timing": {"durationMs": 500},
        "afterEffect": {"type": "none"},
        "sound": None,
    }
    effect.update(patch)
    return effect


ANIMATED_SLIDE = {
    "layout": "Blank",
    "elements": [
        {"id": "hero", "type": "textbox", "text": "Hero", "x": 10, "y": 10,
         "width": 300, "height": 60},
        {"id": "aside", "morphId": "card", "type": "shape", "shape": "rectangle",
         "x": 10, "y": 120, "width": 200, "height": 80, "fill": "#333333"},
    ],
    "animations": {
        "mainSequence": [
            _effect("show-hero"),
            _effect("show-aside", element="aside",
                    start={"type": "afterPrevious", "delayMs": 250},
                    timing={"durationMs": 700, "repeatCount": 2, "autoReverse": True,
                            "acceleration": 0.2, "restart": "never"}),
            _effect("with-hero", start={"type": "withPrevious", "delayMs": 0}),
        ],
        "interactiveSequences": [{
            "id": "interactive-0",
            "trigger": {"type": "onShapeClick", "target": "hero", "delayMs": 0},
            "effects": [_effect("boom", element="aside",
                                start={"type": "withPrevious", "delayMs": 0},
                                timing={"durationMs": 300})],
        }],
    },
    "transition": {
        "effect": "morph", "parameters": {"variant": "byObject"}, "durationMs": 800,
        "advance": {"onClick": True, "afterMs": None}, "sound": None,
    },
}


def _deck(tmp_path, slide, *, name="deck", switches=True):
    deck = tmp_path / name
    (deck / "slides").mkdir(parents=True)
    (deck / "specs").mkdir()
    meta = {
        "template": "blank-dark.pptx",
        "fonts": {"fullwidth": "Meiryo", "halfwidth": "Arial"},
        "defaultTextColor": "#FFFFFF",
    }
    if switches:
        meta["animations"] = {"enabled": True}
        meta["transitions"] = {"enabled": True}
    (deck / "deck.json").write_text(json.dumps(meta))
    (deck / "specs" / "outline.md").write_text("- [s1] round trip\n")
    (deck / "slides" / "s1.json").write_text(json.dumps(slide, ensure_ascii=False))
    return deck


def _round_trip(tmp_path, slide, *, name="deck", switches=True):
    """generate → pptx_to_json → the extracted slide dict."""
    deck = _deck(tmp_path, slide, name=name, switches=switches)
    package = tmp_path / f"{name}.pptx"
    assert generate(deck, output_path=package)["slide_count"] == 1
    pptx_to_json(package, tmp_path / f"{name}-out")
    return json.loads(
        (tmp_path / f"{name}-out" / "slides" / "slide-001.json").read_text()
    )


# --- deck level ------------------------------------------------------------


class TestDeckRoundTrip:
    def test_the_whole_timeline_comes_back_unchanged(self, tmp_path):
        extracted = _round_trip(tmp_path, ANIMATED_SLIDE)
        assert extracted["animations"] == ANIMATED_SLIDE["animations"]
        assert "_rawTiming" not in extracted

    def test_the_transition_comes_back_unchanged(self, tmp_path):
        extracted = _round_trip(tmp_path, ANIMATED_SLIDE)
        assert extracted["transition"] == ANIMATED_SLIDE["transition"]
        assert "_rawTransition" not in extracted

    def test_identity_survives_the_round_trip(self, tmp_path):
        extracted = _round_trip(tmp_path, ANIMATED_SLIDE)
        identities = {
            element.get("id"): element.get("morphId")
            for element in extracted["elements"]
        }
        assert identities == {"hero": None, "aside": "card"}

    def test_the_second_pass_is_idempotent(self, tmp_path):
        once = _round_trip(tmp_path, ANIMATED_SLIDE, name="first")
        twice = _round_trip(
            tmp_path,
            {key: value for key, value in once.items() if not key.startswith("_")},
            name="second",
        )
        assert twice["animations"] == once["animations"]
        assert twice["transition"] == once["transition"]

    def test_effect_order_is_array_order(self, tmp_path):
        reordered = json.loads(json.dumps(ANIMATED_SLIDE))
        main = reordered["animations"]["mainSequence"]
        main[0], main[1] = main[1], main[0]
        # Swapping a click-triggered effect to the front keeps it a click
        # effect, so the sequence is legal; only the order changed.
        main[0]["start"] = {"type": "onPageClick", "delayMs": 0}
        extracted = _round_trip(tmp_path, reordered)
        assert [effect["id"] for effect in extracted["animations"]["mainSequence"]] == [
            "show-aside", "show-hero", "with-hero",
        ]

    def test_transitions_off_emits_and_imports_no_transition(self, tmp_path):
        deck = _deck(tmp_path, ANIMATED_SLIDE, name="off")
        package = tmp_path / "off.pptx"
        generate(deck, output_path=package, transition_mode="off")
        pptx_to_json(package, tmp_path / "off-out")
        extracted = json.loads(
            (tmp_path / "off-out" / "slides" / "slide-001.json").read_text()
        )
        assert "transition" not in extracted and "_rawTransition" not in extracted
        assert extracted["animations"] == ANIMATED_SLIDE["animations"], (
            "REQ-1.4: turning transitions off leaves object timing alone"
        )
        deck_meta = json.loads((tmp_path / "off-out" / "deck.json").read_text())
        assert deck_meta["transitions"] == {"enabled": False}
        assert deck_meta["animations"] == {"enabled": True}

    def test_animations_off_emits_and_imports_no_timeline(self, tmp_path):
        deck = _deck(tmp_path, ANIMATED_SLIDE, name="noanim")
        package = tmp_path / "noanim.pptx"
        generate(deck, output_path=package, animation_mode="off")
        pptx_to_json(package, tmp_path / "noanim-out")
        extracted = json.loads(
            (tmp_path / "noanim-out" / "slides" / "slide-001.json").read_text()
        )
        assert "animations" not in extracted and "_rawTiming" not in extracted
        assert extracted["transition"] == ANIMATED_SLIDE["transition"]


# --- catalog level ---------------------------------------------------------


def _catalog_slide():
    """Return a one-shape slide plus the registry the writers target."""
    slide = etree.fromstring(SLIDE_XML)
    shape = slide.find(f"{{{P}}}cSld/{{{P}}}spTree/{{{P}}}sp")
    registry = ShapeIdentityRegistry("catalog")
    registry.register(CATALOG_TARGET_ID, [shape], source_path="catalog")
    return slide, registry


class TestCatalogBidirectionalCoverage:
    def test_every_reversible_transition_form_round_trips(self):
        index = load_capability_index()
        # CapabilityEntry holds dicts, so it is unhashable: dedupe by key.
        entries = sorted(
            {entry.key: entry for entry in reverse_index(index).transitions.values()}.values(),
            key=lambda entry: entry.key,
        )
        mismatches = []
        for entry in entries:
            expected = entry.semantic["transition"]
            node, _report = build_transition(expected, index=index, slide_slug="catalog")
            slide, _registry = _catalog_slide()
            slide.append(node)
            motion = read_slide_motion(slide, slide_slug="catalog", index=index)
            if motion.transition != expected:
                mismatches.append((entry.key, expected, motion.transition, motion.reasons))
        assert not mismatches, (
            f"{len(mismatches)} catalog transition forms do not round-trip: "
            f"{mismatches[:3]}"
        )
        assert len(entries) == BIDIRECTIONAL_COVERAGE["transitions"]

    def test_every_reversible_animation_preset_round_trips(self):
        index = load_capability_index()
        entries = sorted(
            {entry.key: entry for entry in reverse_index(index).presets.values()}.values(),
            key=lambda entry: entry.key,
        )
        mismatches = []
        for entry in entries:
            expected = entry.semantic["animations"]
            slide, registry = _catalog_slide()
            timing = TimingWriter(registry, index=index, slide_slug="catalog").build(
                expected
            )
            slide.append(timing)
            motion = read_slide_motion(slide, slide_slug="catalog", index=index)
            read_back = (motion.animations or {}).get("mainSequence") or [{}]
            if read_back[0].get("preset") != expected["mainSequence"][0]["preset"]:
                mismatches.append((entry.key, read_back[0].get("preset"), motion.reasons))
        assert not mismatches, (
            f"{len(mismatches)} catalog presets do not round-trip: {mismatches[:3]}"
        )
        assert len(entries) == BIDIRECTIONAL_COVERAGE["presets"]

    def test_the_reader_refuses_presets_the_writer_cannot_emit(self):
        """A capture-required mapping must not read back semantically.

        Importing it as JSON the writer then refuses would make
        PPTX → JSON → PPTX fail on content the package really carried, so it is
        preserved raw until Task 8 captures it on both sides.
        """
        index = load_capability_index()
        reversible = {entry.key for entry in reverse_index(index).presets.values()}
        assert reversible, "sanity: some presets are reversible"
        assert all(index.entry(key).writable for key in reversible)
        refused = {
            entry.key
            for entry in index.items.values()
            if entry.key.startswith("animation.gallery.") and not entry.writable
        }
        assert refused, "sanity: the catalog still has capture-required gallery tiles"
        assert not (reversible & refused)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# --- sequencing without an authored duration --------------------------------
SEQUENCED_SLIDE = {
    "layout": "Blank",
    "elements": [
        {"id": "hero", "type": "textbox", "text": "Hero", "x": 10, "y": 10,
         "width": 300, "height": 60},
        {"id": "aside", "type": "shape", "shape": "rectangle", "x": 10, "y": 120,
         "width": 200, "height": 80, "fill": "#333333"},
        {"id": "btn", "type": "shape", "shape": "rectangle", "x": 10, "y": 220,
         "width": 120, "height": 40, "fill": "#444444"},
    ],
    "animations": {
        "mainSequence": [
            # One shape animated three times across two click groups, with a
            # sibling joining the second group, and NO durationMs anywhere.
            _effect("in", timing={},
                    preset={"category": "entrance", "effect": "flyIn", "variant": None}),
            _effect("stress", timing={}, start={"type": "afterPrevious", "delayMs": 0},
                    preset={"category": "emphasis", "effect": "wave", "variant": None}),
            _effect("join", element="aside", timing={},
                    start={"type": "withPrevious", "delayMs": 0},
                    preset={"category": "entrance", "effect": "fade", "variant": None}),
            _effect("out", timing={}, start={"type": "onPageClick", "delayMs": 500},
                    preset={"category": "exit", "effect": "flyOut", "variant": None}),
        ],
        "interactiveSequences": [{
            "id": "interactive-0",
            "trigger": {"type": "onShapeClick", "target": "btn", "delayMs": 0},
            "effects": [_effect("spin", element="aside", timing={},
                                preset={"category": "emphasis", "effect": "spin",
                                        "variant": None})],
        }],
    },
}


class TestSequencingWithoutAnAuthoredDuration:
    """An omitted ``durationMs`` must not flatten the timeline.

    The value the writer falls back to is not only the behaviours' duration: it
    is how far the effect advances the timeline, so an ``afterPrevious`` group's
    delay is the sum of what came before it. Promoting the GUI capture removed
    ``observedChildDurationMs`` from every measured entry, and for a slide that
    named no duration that left the second start group at delay 0 while the
    first effect ran 500 ms — which the reader refused as a timeline it could
    not express, falling back to raw. ``measuredDurationMs`` is the fallback now.
    """

    def test_the_timeline_round_trips_with_no_duration_authored(self, tmp_path):
        slide = _round_trip(tmp_path, dict(SEQUENCED_SLIDE), name="sequenced")
        animations = slide.get("animations")
        assert animations, "the slide fell back to raw instead of semantic JSON"
        assert "rawTiming" not in slide, "the reader could not express the timeline"
        starts = [
            (effect["target"]["element"], effect["preset"]["effect"],
             effect["start"]["type"], effect["start"]["delayMs"])
            for effect in animations["mainSequence"]
        ]
        assert starts == [
            ("hero", "flyIn", "onPageClick", 0),
            ("hero", "wave", "afterPrevious", 0),
            ("aside", "fade", "withPrevious", 0),
            ("hero", "flyOut", "onPageClick", 500),
        ]
        # Each effect reads back the duration PowerPoint measured for it.
        assert [e["timing"]["durationMs"] for e in animations["mainSequence"]] == [500] * 4
        sequences = animations["interactiveSequences"]
        assert [s["trigger"]["target"] for s in sequences] == ["btn"]
        assert [e["preset"]["effect"] for e in sequences[0]["effects"]] == ["spin"]

    def test_one_shape_animated_three_times_gets_three_group_ids(self, tmp_path):
        """PowerPoint numbers each effect on a shape, and so does the writer."""
        import zipfile

        deck = _deck(tmp_path, dict(SEQUENCED_SLIDE), name="grouped")
        package = tmp_path / "grouped.pptx"
        generate(deck, output_path=package)
        with zipfile.ZipFile(package) as archive:
            root = etree.fromstring(archive.read("ppt/slides/slide1.xml"))
        effects = [
            node for node in root.iter()
            if etree.QName(node).localname == "cTn" and node.get("presetID")
        ]
        by_group: dict[str, list[str]] = {}
        for node in effects:
            by_group.setdefault(node.get("grpId"), []).append(node.get("nodeType"))
        # hero carries three effects, so its three group ids are 0, 1 and 2.
        assert {"0", "1", "2"} <= set(by_group), sorted(by_group)
        assert len(effects) == 5, "four main-sequence effects plus the triggered one"
