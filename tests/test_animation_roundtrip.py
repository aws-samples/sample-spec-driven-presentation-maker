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
#: 108 presets, not 101: the 7 Complex motion paths were captured on 2026-11-02
#: and are invertible like the Basic five.
#: 148 transitions, not 147: the reversed Clock joined them when its selector
#: parameters stopped being conflated with the attributes it writes.
BIDIRECTIONAL_COVERAGE = {"transitions": 148, "presets": 108}

FADE = {"category": "entrance", "effect": "fade"}

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
                    preset={"category": "entrance", "effect": "flyIn"}),
            _effect("stress", timing={}, start={"type": "afterPrevious", "delayMs": 0},
                    preset={"category": "emphasis", "effect": "wave"}),
            _effect("join", element="aside", timing={},
                    start={"type": "withPrevious", "delayMs": 0},
                    preset={"category": "entrance", "effect": "fade"}),
            _effect("out", timing={}, start={"type": "onPageClick", "delayMs": 500},
                    preset={"category": "exit", "effect": "flyOut"}),
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


#: One case per behaviour primitive, each exercising every field that primitive
#: accepts. The eight are the whole vocabulary of the advanced form, so this is
#: coverage rather than a sample.
BEHAVIOR_CASES: dict[str, dict] = {
    "motion": {
        "type": "motion",
        "path": "M 0 0 L 0.25 0",
        "pathEditMode": "relative",
        "origin": "layout",
        "rotationAngle": 45,
        "pointTypes": "AA",
    },
    "color": {"type": "color", "to": "FF0000"},
    "scale": {"type": "scale", "to": {"x": 1.5, "y": 2}},
    "rotation": {"type": "rotation", "by": 90},
    "property": {
        "type": "property",
        "attrName": "style.opacity",
        "to": "0.5",
        "calcMode": "lin",
        "valueType": "num",
    },
    "command": {"type": "command", "command": "playFrom", "value": "0.0"},
    "filter": {"type": "filter", "filter": "fade", "transition": "in"},
    "set": {"type": "set", "attrName": "style.visibility", "to": "visible"},
}


def _behavior_slide(effect: dict) -> tuple[etree._Element, etree._Element]:
    """Write one effect onto a catalog slide; return the slide and its timing."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts" / "animation_catalog"))
    import accept as acceptance

    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    slide, registry, _spids = acceptance.catalog_slide()
    node = TimingWriter(registry, index=index, slide_slug="behaviors").build(
        {
            "mainSequence": [dict(effect, id="e1", target={"element": CATALOG_TARGET_ID})],
            "interactiveSequences": [],
        }
    )
    slide.append(node)
    return slide, node


@pytest.mark.parametrize("name", sorted(BEHAVIOR_CASES))
def test_every_behavior_primitive_round_trips_byte_for_byte(name):
    """The advanced form comes back as JSON, not as a raw sidecar.

    An effect with no ``presetClass``/``presetID`` is a list of behaviour
    primitives PowerPoint plays without naming. It used to drop the whole
    slide's timing to the raw fallback: replayable, so nothing was lost from
    the *package*, but the JSON handed back held an opaque reference that no
    one could read or edit. An imported deck's hand-made animations were
    therefore carry-only.

    Equality of the re-emitted XML is the assertion, not equality of the JSON.
    Reading something that merely *looks* right is the failure mode worth
    catching, and only the bytes settle it.
    """
    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    effect = {
        "behaviors": [dict(BEHAVIOR_CASES[name], durationMs=700)],
        "start": {"type": "onPageClick", "delayMs": 0},
        "timing": {"durationMs": 700},
    }
    slide, written = _behavior_slide(effect)
    first = etree.tostring(written)

    motion = read_slide_motion(slide, slide_slug="behaviors", index=index)
    assert motion.animations is not None, f"{name} fell back to raw: {motion.reasons}"
    assert motion.raw_timing is None, name
    imported = motion.animations["mainSequence"][0]
    assert imported["behaviors"][0]["type"] == name

    _slide, rewritten = _behavior_slide({k: v for k, v in imported.items() if k != "id"})
    assert etree.tostring(rewritten) == first, (
        f"{name} did not survive the round trip\n"
        f"  wrote: {first.decode()}\n"
        f"  again: {etree.tostring(rewritten).decode()}"
    )


def test_a_behavior_duration_is_reported_once_on_import():
    """A behaviour's duration is the effect's, and import says it once.

    The effect's own ``p:cTn`` carries **no** ``dur`` for a behaviour list —
    only the behaviour's does. So a behaviour that states no duration inherits
    the effect's, and one that states a different duration simply *is* the
    effect's duration: there is nowhere in the package for an effect-level
    value a behaviour does not use, and the writer does not invent one.

    Import therefore reports it on the effect and omits it from the behaviour,
    for both spellings. The JSON normalises; the bytes do not move, which the
    byte-equality test above is what proves.
    """
    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )

    def imported(effect):
        slide, written = _behavior_slide(effect)
        motion = read_slide_motion(slide, slide_slug="behaviors", index=index)
        assert motion.animations is not None
        return motion.animations["mainSequence"][0], etree.tostring(written)

    # Inherited: the behaviour omits it, and import must not restate it — that
    # restatement would read as a round-trip failure for the 16 catalog entries
    # whose examples omit it.
    effect, inherited_xml = imported(
        {
            "behaviors": [{"type": "rotation", "by": 360}],
            "start": {"type": "onPageClick", "delayMs": 0},
            "timing": {"durationMs": 500},
        }
    )
    assert "durationMs" not in effect["behaviors"][0], effect["behaviors"][0]
    assert effect["timing"]["durationMs"] == 500

    # Stated on the behaviour: the same place, because that is the only place
    # the package has. The effect-level 500 was never persisted.
    effect, overridden_xml = imported(
        {
            "behaviors": [{"type": "rotation", "by": 360, "durationMs": 250}],
            "start": {"type": "onPageClick", "delayMs": 0},
            "timing": {"durationMs": 500},
        }
    )
    assert "durationMs" not in effect["behaviors"][0], effect["behaviors"][0]
    assert effect["timing"]["durationMs"] == 250
    assert b'dur="250"' in overridden_xml and b'dur="500"' not in overridden_xml
    assert b'dur="500"' in inherited_xml


def test_a_behavior_outside_the_writers_vocabulary_still_falls_back_to_raw():
    """Inverting the eight primitives must not widen what import accepts.

    The raw fallback is what keeps a package replayable when sdpm cannot write
    the content back. An out-of-enum attribute value is exactly that case: the
    writer would refuse it, so importing it as a value would produce JSON that
    fails on the way out.
    """
    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    slide, written = _behavior_slide(
        {
            "behaviors": [{"type": "filter", "filter": "fade", "transition": "in"}],
            "start": {"type": "onPageClick", "delayMs": 0},
            "timing": {"durationMs": 700},
        }
    )
    # Corrupt the enumerated attribute in place, the way a hand edit or another
    # producer would.
    for node in written.iter():
        if etree.QName(node).localname == "animEffect":
            node.set("transition", "sideways")
    motion = read_slide_motion(slide, slide_slug="behaviors", index=index)
    assert motion.animations is None
    assert motion.raw_timing is not None
    assert any("sideways" in reason for reason in motion.reasons), motion.reasons


#: One case per build family, with the OOXML each must produce.
BUILD_CASES = {
    "paragraph level": (
        {"text": {"level": "byParagraphLevel2"}},
        b'<p:bldP spid="2" grpId="0" build="p" bldLvl="2"',
    ),
    "paragraph sequence": (
        {"text": {"sequence": "byParagraph"}},
        b'<p:bldP spid="2" grpId="0" build="p"',
    ),
    "reverse order": (
        {"text": {"sequence": "byParagraph", "reverseOrder": True}},
        b'rev="1"',
    ),
    "chart build": (
        {"chart": {"build": "chartBySeriesElement"}},
        b'<a:bldChart bld="seriesEl"/>',
    ),
    "smartArt build": (
        {"smartArt": {"build": "byLevelOneByOne"}},
        b'<p:bldDgm spid="2" grpId="0" bld="lvlOne"/>',
    ),
    "text unit": (
        {"text": {"unit": "byWord", "interItemDelayPercent": 10}},
        b'<p:iterate type="wd"',
    ),
}


@pytest.mark.parametrize("name", sorted(BUILD_CASES))
def test_every_build_family_round_trips(name):
    """``p:bldLst`` and ``p:iterate`` come back as JSON, not as a raw sidecar.

    The reader used to accept ``p:bldP`` alone, allow only the three attributes
    a preset's own build list carries, and read nothing into the JSON. So a
    chart build, a SmartArt build, a paragraph level and a by-word text unit
    each sent the whole slide's timing to the raw fallback — on the element or
    the attribute, before any value was even looked at.

    The expected OOXML is asserted as well as the JSON, because a reader that
    agrees with a *wrong* writer would pass a JSON-only comparison.
    """
    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    fields, expected_xml = BUILD_CASES[name]
    effect = {
        "preset": {"category": "entrance", "effect": "fade"},
        "start": {"type": "onPageClick", "delayMs": 0},
        "timing": {"durationMs": 500},
        **fields,
    }
    slide, written = _behavior_slide(effect)
    first = etree.tostring(written)
    assert expected_xml in first, f"{name}: {first.decode()}"

    motion = read_slide_motion(slide, slide_slug="behaviors", index=index)
    assert motion.animations is not None, f"{name} fell back to raw: {motion.reasons}"
    imported = motion.animations["mainSequence"][0]
    for field, value in fields.items():
        assert imported.get(field) == value, f"{name}: {field} came back {imported.get(field)!r}"

    _slide, rewritten = _behavior_slide({k: v for k, v in imported.items() if k != "id"})
    assert etree.tostring(rewritten) == first, name


def test_a_build_list_value_outside_the_catalog_falls_back_to_raw():
    """Inverting the build families must not widen what import accepts.

    A build token the catalog does not record would import as a value the
    writer then refuses, so the round-trip would break on content the file
    carried. The raw fallback is what keeps that replayable.
    """
    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    slide, written = _behavior_slide(
        {
            "preset": {"category": "entrance", "effect": "fade"},
            "start": {"type": "onPageClick", "delayMs": 0},
            "timing": {"durationMs": 500},
            "smartArt": {"build": "byLevelOneByOne"},
        }
    )
    for node in written.iter():
        if etree.QName(node).localname == "bldDgm":
            node.set("bld", "lvlSeventeen")
    motion = read_slide_motion(slide, slide_slug="behaviors", index=index)
    assert motion.animations is None
    assert motion.raw_timing is not None
    assert any("lvlSeventeen" in reason for reason in motion.reasons), motion.reasons


def test_a_presets_own_animate_background_is_not_restated_on_import():
    """``text.animateBackground`` is tri-state, and the preset makes it readable.

    Absent, it means "whatever this preset's capture records"; set, it
    overrides. So it belongs in the imported JSON only when it **disagrees**
    with the preset — restating agreement would add a field the caller never
    wrote to every one of the 95 tiles whose capture records a build list.

    The cost of that rule is exact and worth naming: an explicit
    ``animateBackground: true`` on a preset that already animates its
    background writes the same bytes as writing nothing, so it cannot be
    recovered. That is one of the eight irreducible build entries.
    """
    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )

    def imported(fields):
        slide, _written = _behavior_slide(
            {
                "preset": {"category": "entrance", "effect": "fade"},
                "start": {"type": "onPageClick", "delayMs": 0},
                "timing": {"durationMs": 500},
                **fields,
            }
        )
        motion = read_slide_motion(slide, slide_slug="behaviors", index=index)
        assert motion.animations is not None, motion.reasons
        return motion.animations["mainSequence"][0]

    # Fade's own capture records p:bldP/@animBg=1, so agreement says nothing.
    assert "text" not in imported({})
    assert "text" not in imported({"text": {"animateBackground": True}})
    # Disagreement is the author's answer and survives.
    assert imported({"text": {"animateBackground": False}})["text"] == {
        "animateBackground": False
    }
