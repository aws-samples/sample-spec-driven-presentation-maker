# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Semantic import: PPTX timing/transition → public slide JSON.

These tests pin the import contract that makes the feature bidirectional: the
exact normalized JSON a known tree reads back as, the identity recovery
(extension first, deterministic fingerprint second, ``morphId`` separately),
PowerPoint default normalization, and — most importantly — the all-or-nothing
rule. A tree with one attribute the reader cannot invert must become raw, never
semantic JSON with the attribute quietly missing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation

from sdpm.engine.builder import PPTXBuilder
from sdpm.engine.converter.pipeline import pptx_to_json
from sdpm.engine.timing import SDPM_EFFECT_EXT_URI, effect_fingerprint
from sdpm.engine.timing.reader import (
    MotionReadError,
    derive_element_id,
    read_slide_motion,
    resolve_import_switches,
    shape_identities,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "sdpm" / "templates" / "blank-dark.pptx"
NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}

FADE = {"category": "entrance", "effect": "fade"}


def _effect(effect_id="show-hero", element="hero", **patch):
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


def _slide(**patch):
    slide = {
        "id": "animated",
        "layout": "Blank",
        "elements": [
            {"id": "hero", "type": "textbox", "text": "Hero", "x": 10, "y": 10,
             "width": 300, "height": 60},
            {"id": "aside", "type": "shape", "shape": "rectangle", "x": 10, "y": 120,
             "width": 200, "height": 80, "fill": "#333333"},
        ],
    }
    slide.update(patch)
    return slide


def _package(tmp_path, slide_def, *, animations=True, transitions=True, name="deck.pptx"):
    builder = PPTXBuilder(
        TEMPLATE,
        fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"},
        default_text_color="#FFFFFF",
        base_dir=tmp_path,
        animations_enabled=animations,
        transitions_enabled=transitions,
    )
    builder.add_slide(slide_def)
    out = tmp_path / name
    builder.save(out)
    return out


def _read(path, slug="slide-001"):
    slide = list(Presentation(str(path)).slides)[0]
    return read_slide_motion(slide._element, slide_slug=slug, part=slide.part)


def _mutate(path, mutate):
    """Apply ``mutate(slide_element)`` to a saved package and save it again."""
    presentation = Presentation(str(path))
    mutate(list(presentation.slides)[0]._element)
    presentation.save(str(path))
    return path


# --- semantic animations ---------------------------------------------------


class TestSemanticAnimations:
    def test_a_known_main_sequence_reads_back_as_the_same_effect(self, tmp_path):
        source = _effect()
        motion = _read(_package(tmp_path, _slide(
            animations={"mainSequence": [source], "interactiveSequences": []}
        )))
        assert motion.animations == {
            "mainSequence": [source],
            "interactiveSequences": [],
        }
        assert motion.raw_timing is None, "a fully understood tree must not also be preserved raw"

    def test_every_written_timing_option_comes_back(self, tmp_path):
        source = _effect(timing={
            "durationMs": 700,
            "repeatCount": 3,
            "autoReverse": True,
            "acceleration": 0.25,
            "deceleration": 0.5,
            "restart": "never",
        })
        motion = _read(_package(tmp_path, _slide(
            animations={"mainSequence": [source], "interactiveSequences": []}
        )))
        assert motion.animations["mainSequence"][0]["timing"] == source["timing"]

    def test_trigger_kinds_and_order_survive(self, tmp_path):
        effects = [
            _effect("first"),
            _effect("second", element="aside", start={"type": "afterPrevious", "delayMs": 100}),
            _effect("third", start={"type": "withPrevious", "delayMs": 0}),
            _effect("fourth", element="aside", start={"type": "onPageClick", "delayMs": 50}),
        ]
        motion = _read(_package(tmp_path, _slide(
            animations={"mainSequence": effects, "interactiveSequences": []}
        )))
        read_back = motion.animations["mainSequence"]
        assert [effect["id"] for effect in read_back] == ["first", "second", "third", "fourth"]
        assert [effect["start"] for effect in read_back] == [
            {"type": "onPageClick", "delayMs": 0},
            {"type": "afterPrevious", "delayMs": 100},
            {"type": "withPrevious", "delayMs": 0},
            {"type": "onPageClick", "delayMs": 50},
        ]

    def test_an_interactive_sequence_reads_back_with_its_trigger(self, tmp_path):
        motion = _read(_package(tmp_path, _slide(animations={
            "mainSequence": [],
            "interactiveSequences": [{
                "id": "interactive-0",
                "trigger": {"type": "onShapeClick", "target": "hero", "delayMs": 0},
                "effects": [_effect("boom", element="aside",
                                    start={"type": "withPrevious", "delayMs": 0})],
            }],
        })))
        sequences = motion.animations["interactiveSequences"]
        assert len(sequences) == 1
        assert sequences[0]["trigger"] == {
            "type": "onShapeClick", "target": "hero", "delayMs": 0,
        }
        assert sequences[0]["effects"][0]["id"] == "boom"

    def _two_sequences(self):
        return {
            "mainSequence": [],
            "interactiveSequences": [
                {"id": "author-chose-this", "trigger": {"type": "onShapeClick", "target": "hero"},
                 "effects": [_effect("a", element="aside",
                                     start={"type": "withPrevious", "delayMs": 0})]},
                {"id": "and-this", "trigger": {"type": "onShapeClick", "target": "aside"},
                 "effects": [_effect("b", start={"type": "withPrevious", "delayMs": 0})]},
            ],
        }

    def test_the_interactive_sequence_keeps_the_name_its_author_gave_it(self, tmp_path):
        """PowerPoint stores no name for a trigger sequence, so sdpm persists
        the author's own label in its extension, the way it already does for
        effect IDs. Without this a sequence came back as ``interactive-0`` and
        an author's JSON stopped matching itself after a round-trip."""
        motion = _read(_package(tmp_path, _slide(animations=self._two_sequences())))
        assert [s["id"] for s in motion.animations["interactiveSequences"]] == [
            "author-chose-this", "and-this",
        ]

    def test_the_interactive_sequence_id_is_deterministic_without_a_persisted_name(self, tmp_path):
        """A package PowerPoint wrote, or one sdpm wrote before it persisted
        sequence names, carries no ``sdpm:sequences``. Those are still numbered
        by position rather than given an invented name."""
        from sdpm.engine.timing.reader import SDPM_NS

        def drop_sequence_names(slide_element):
            found = slide_element.findall(f".//{{{SDPM_NS}}}sequences")
            assert found, "the writer should have persisted sequence names to strip"
            for node in found:
                node.getparent().remove(node)

        package = _mutate(
            _package(tmp_path, _slide(animations=self._two_sequences())),
            drop_sequence_names,
        )
        motion = _read(package)
        assert [s["id"] for s in motion.animations["interactiveSequences"]] == [
            "interactive-0", "interactive-1",
        ]
        # the effect IDs inside them are unaffected: they have their own entries
        assert [e["id"] for s in motion.animations["interactiveSequences"]
                for e in s["effects"]] == ["a", "b"]


# --- identity --------------------------------------------------------------


class TestIdentityRecovery:
    def test_effect_ids_come_from_the_sdpm_extension(self, tmp_path):
        motion = _read(_package(tmp_path, _slide(animations={
            "mainSequence": [_effect("author-id")], "interactiveSequences": [],
        })))
        assert motion.animations["mainSequence"][0]["id"] == "author-id"

    def test_without_the_extension_the_deterministic_fingerprint_is_used(self, tmp_path):
        package = _package(tmp_path, _slide(animations={
            "mainSequence": [_effect("author-id"), _effect("second-id")],
            "interactiveSequences": [],
        }))

        def strip(slide_element):
            for timing in slide_element.findall("{%s}timing" % NS["p"]):
                for ext_lst in timing.findall("{%s}extLst" % NS["p"]):
                    timing.remove(ext_lst)

        motion = _read(_mutate(package, strip))
        read_back = motion.animations["mainSequence"]
        expected = [
            effect_fingerprint(
                sequence="mainSequence", target="hero", effect=effect, ordinal=ordinal,
            )
            for ordinal, effect in enumerate(read_back)
        ]
        assert [effect["id"] for effect in read_back] == expected
        assert expected[0] != expected[1], "identical effects get distinct ordinals"

    def test_morph_id_is_recovered_separately_from_the_element_id(self, tmp_path):
        slide = _slide(animations={"mainSequence": [_effect()], "interactiveSequences": []})
        slide["elements"][1]["morphId"] = "card"
        motion = _read(_package(tmp_path, slide))
        identities = shape_identities(
            list(Presentation(str(tmp_path / "deck.pptx")).slides)[0]._element
        )
        card = [identity for identity in identities.values() if identity.morph_id == "card"]
        assert len(card) == 1
        assert card[0].element_id == "aside", "the logical id is not the morphId"
        assert set(motion.morph_ids.values()) == {"card"}

    def test_a_shape_without_sdpm_metadata_gets_a_deterministic_id(self):
        used: list[str] = []
        first = derive_element_id("Rounded Rectangle 4", 7, used)
        used.append(first)
        second = derive_element_id("Rounded Rectangle 4", 9, used)
        assert first == "rounded-rectangle-4"
        assert second == "rounded-rectangle-4-2", "a collision takes a suffix, not a random id"
        assert derive_element_id("", 11, used) == "shape-11"
        assert derive_element_id("12 inches", 13, used) == "shape-13", "an id must start with a letter"


# --- transitions -----------------------------------------------------------


class TestSemanticTransition:
    def test_a_standard_transition_reads_back_with_its_captured_duration(self, tmp_path):
        motion = _read(_package(tmp_path, _slide(
            transition={"effect": "wipe", "parameters": {}, "durationMs": 1000,
                        "advance": {"onClick": True, "afterMs": None}, "sound": None}
        )))
        assert motion.transition == {
            "effect": "wipe", "parameters": {}, "durationMs": 1000,
            "advance": {"onClick": True, "afterMs": None}, "sound": None,
        }

    def test_the_morph_variant_survives_the_extension_branch(self, tmp_path):
        motion = _read(_package(tmp_path, _slide(
            transition={"effect": "morph", "parameters": {"variant": "byChar"},
                        "durationMs": 800, "advance": {"onClick": True, "afterMs": None},
                        "sound": None}
        )))
        assert motion.transition["effect"] == "morph"
        assert motion.transition["parameters"] == {"variant": "byChar"}
        assert motion.transition["durationMs"] == 800

    def test_advance_settings_are_normalized_from_powerpoints_defaults(self, tmp_path):
        motion = _read(_package(tmp_path, _slide(
            transition={"effect": "fade", "parameters": {}, "durationMs": 700,
                        "advance": {"onClick": False, "afterMs": 3000}, "sound": None}
        )))
        assert motion.transition["advance"] == {"onClick": False, "afterMs": 3000}

    def test_a_duration_only_in_the_legacy_bucket_normalizes_to_milliseconds(self, tmp_path):
        """``wipe`` at its default duration persists only ``@spd="slow"``; the
        importer has to turn that back into the millisecond value rather than
        leave the JSON without a duration."""
        package = _package(tmp_path, _slide(
            transition={"effect": "wipe", "parameters": {}, "durationMs": 1000,
                        "advance": {"onClick": True, "afterMs": None}, "sound": None}
        ))
        slide = list(Presentation(str(package)).slides)[0]
        node = slide._element.find("{%s}transition" % NS["p"])
        assert node is not None and node.get("spd") == "slow"
        assert "dur" not in {etree.QName(k).localname for k in node.attrib}
        assert _read(package).transition["durationMs"] == 1000


# --- all-or-nothing classification ----------------------------------------


class TestPartialTreesGoRaw:
    def _unknown_attribute(self, slide_element):
        for timing in slide_element.findall("{%s}timing" % NS["p"]):
            for ctn in timing.iter("{%s}cTn" % NS["p"]):
                if ctn.get("nodeType") == "clickEffect":
                    # A real, playback-affecting PresentationML attribute the
                    # reader does not invert.
                    ctn.set("afterEffect", "1")
                    return

    def test_one_uninverted_attribute_sends_the_whole_tree_raw(self, tmp_path):
        package = _mutate(
            _package(tmp_path, _slide(animations={
                "mainSequence": [_effect()], "interactiveSequences": [],
            })),
            self._unknown_attribute,
        )
        motion = _read(package)
        assert motion.animations is None, "no partially semantic output"
        assert motion.raw_timing is not None
        assert any("afterEffect" in reason for reason in motion.reasons)

    def test_an_extra_wait_between_start_groups_is_preserved_rather_than_dropped(self, tmp_path):
        """Sibling start groups share a begin time, so their cumulative offset
        carries the sequencing. The JSON timeline derives that offset from the
        effects, so a group that waits longer than the effects before it would
        lose the extra pause on regeneration."""
        def delay_the_second_group(slide_element):
            groups = slide_element.xpath(
                ".//p:seq/p:cTn/p:childTnLst/p:par/p:cTn/p:childTnLst/p:par/p:cTn"
            )
            cond = groups[1].find("{%s}stCondLst/{%s}cond" % (NS["p"], NS["p"]))
            cond.set("delay", str(int(cond.get("delay")) + 2000))

        motion = _read(_mutate(
            _package(tmp_path, _slide(animations={
                "mainSequence": [
                    _effect("first"),
                    _effect("second", element="aside",
                            start={"type": "afterPrevious", "delayMs": 0}),
                ],
                "interactiveSequences": [],
            })),
            delay_the_second_group,
        ))
        assert motion.animations is None
        assert motion.raw_timing is not None
        assert "extra wait" in " ".join(motion.reasons)

    def test_an_unestablished_preset_is_preserved_rather_than_guessed(self, tmp_path):
        def retarget(slide_element):
            for ctn in slide_element.iter("{%s}cTn" % NS["p"]):
                if ctn.get("presetID") is not None:
                    ctn.set("presetID", "99999")

        motion = _read(_mutate(
            _package(tmp_path, _slide(animations={
                "mainSequence": [_effect()], "interactiveSequences": [],
            })),
            retarget,
        ))
        assert motion.animations is None
        assert motion.raw_timing is not None
        assert "99999" in " ".join(motion.reasons)

    def test_a_transition_element_the_catalog_does_not_establish_goes_raw(self, tmp_path):
        def swap(slide_element):
            for node in slide_element.findall("{%s}transition" % NS["p"]):
                for child in list(node):
                    node.remove(child)
                etree.SubElement(node, "{%s}futureEffect" % NS["p"])

        motion = _read(_mutate(
            _package(tmp_path, _slide(
                transition={"effect": "wipe", "parameters": {}, "durationMs": 1000,
                            "advance": {"onClick": True, "afterMs": None}, "sound": None}
            )),
            swap,
        ))
        assert motion.transition is None
        assert motion.raw_transition is not None

    def test_a_target_that_names_no_shape_is_an_explicit_failure(self, tmp_path):
        def retarget(slide_element):
            for sp_tgt in slide_element.iter("{%s}spTgt" % NS["p"]):
                sp_tgt.set("spid", "4242")

        package = _mutate(
            _package(tmp_path, _slide(animations={
                "mainSequence": [_effect()], "interactiveSequences": [],
            })),
            retarget,
        )
        with pytest.raises(MotionReadError, match="4242"):
            _read(package)


# --- media timing ----------------------------------------------------------


class TestMediaTiming:
    @pytest.fixture()
    def media_dir(self, tmp_path):
        (tmp_path / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 128)
        return tmp_path

    def test_media_only_timing_is_not_an_object_animation(self, media_dir):
        package = _package(media_dir, {
            "id": "media", "layout": "Blank",
            "elements": [{"id": "clip", "type": "video", "src": "clip.mp4",
                          "x": 10, "y": 10, "width": 320, "height": 180}],
        }, animations=False)
        motion = _read(package)
        assert motion.animations is None
        assert motion.raw_timing is None, "python-pptx's own media timing is understood"
        assert motion.has_object_animation is False


# --- deck switches ---------------------------------------------------------


class TestImportSwitches:
    def test_a_new_import_derives_both_switches_from_content(self, tmp_path):
        pptx_to_json(
            _package(tmp_path, _slide(
                animations={"mainSequence": [_effect()], "interactiveSequences": []},
                transition={"effect": "wipe", "parameters": {}, "durationMs": 1000,
                            "advance": {"onClick": True, "afterMs": None}, "sound": None},
            )),
            tmp_path / "out",
        )
        deck = json.loads((tmp_path / "out" / "deck.json").read_text())
        assert deck["animations"] == {"enabled": True}
        assert deck["transitions"] == {"enabled": True}

    def test_a_still_deck_resolves_to_off_without_gaining_switch_keys(self, tmp_path):
        """An absent switch is defined as disabled, so a deck with no motion
        imports byte-identically to how it did before the feature existed
        (REQ-9.4) while still resolving to off (REQ-1.2)."""
        from sdpm.engine.timing import resolve_enabled

        pptx_to_json(_package(tmp_path, _slide(), animations=False, transitions=False),
                     tmp_path / "out")
        deck = json.loads((tmp_path / "out" / "deck.json").read_text())
        assert "animations" not in deck and "transitions" not in deck
        assert resolve_enabled(deck, "animations") is False
        assert resolve_enabled(deck, "transitions") is False

    def test_a_deck_with_only_a_transition_still_writes_both_switches(self, tmp_path):
        pptx_to_json(
            _package(tmp_path, _slide(
                transition={"effect": "wipe", "parameters": {}, "durationMs": 1000,
                            "advance": {"onClick": True, "afterMs": None}, "sound": None},
            )),
            tmp_path / "out",
        )
        deck = json.loads((tmp_path / "out" / "deck.json").read_text())
        assert deck["transitions"] == {"enabled": True}
        assert deck["animations"] == {"enabled": False}, (
            "a deck that carries motion states both switches explicitly"
        )

    def test_an_explicit_off_switch_is_written_back_even_for_a_still_deck(self, tmp_path):
        pptx_to_json(
            _package(tmp_path, _slide(), animations=False, transitions=False),
            tmp_path / "out",
            existing_deck={"transitions": {"enabled": False}},
        )
        deck = json.loads((tmp_path / "out" / "deck.json").read_text())
        assert deck["transitions"] == {"enabled": False}
        assert "animations" not in deck

    def test_hand_edit_sync_preserves_an_explicit_switch_and_derives_a_missing_one(self, tmp_path):
        existing = {"animations": {"enabled": False}}
        pptx_to_json(
            _package(tmp_path, _slide(
                animations={"mainSequence": [_effect()], "interactiveSequences": []},
                transition={"effect": "wipe", "parameters": {}, "durationMs": 1000,
                            "advance": {"onClick": True, "afterMs": None}, "sound": None},
            )),
            tmp_path / "out",
            existing_deck=existing,
        )
        deck = json.loads((tmp_path / "out" / "deck.json").read_text())
        assert deck["animations"] == {"enabled": False}, "the user's explicit off is kept"
        assert deck["transitions"] == {"enabled": True}, "the missing switch is derived"

    @pytest.mark.parametrize(
        "existing,expected",
        [
            (None, {"animations": True, "transitions": False}),
            ({}, {"animations": True, "transitions": False}),
            ({"animations": {"enabled": True}}, {"animations": True, "transitions": False}),
            ({"transitions": {"enabled": True}}, {"animations": True, "transitions": True}),
            ({"animations": {}}, {"animations": True, "transitions": False}),
            ({"animations": {"enabled": "yes"}}, {"animations": True, "transitions": False}),
        ],
    )
    def test_switch_resolution_table(self, existing, expected):
        resolved = resolve_import_switches(
            {"animations": True, "transitions": False}, existing
        )
        assert resolved == {
            "animations": {"enabled": expected["animations"]},
            "transitions": {"enabled": expected["transitions"]},
        }


# --- compatibility ---------------------------------------------------------


def test_a_still_deck_gets_no_animation_keys_and_no_logical_ids(tmp_path):
    """REQ-9.4: importing an ordinary deck must look exactly as it did."""
    pptx_to_json(_package(tmp_path, _slide(), animations=False, transitions=False),
                 tmp_path / "out")
    slide = json.loads((tmp_path / "out" / "slides" / "slide-001.json").read_text())
    assert "animations" not in slide and "transition" not in slide
    assert "_rawTiming" not in slide and "_rawTransition" not in slide
    assert all("id" not in element for element in slide["elements"]), (
        "a logical id is only stamped on a shape an animation actually targets"
    )
    assert not (tmp_path / "out" / "animations").exists()


@pytest.mark.parametrize(
    "after",
    [
        {"type": "none"},
        {"type": "hide"},
        {"type": "hideOnNextClick"},
        {"type": "dim"},
        {"type": "dim", "color": "#808080"},
    ],
    ids=["none", "hide", "hideOnNextClick", "dim", "dimColor"],
)
def test_an_after_animation_value_comes_back_as_it_went_in(tmp_path, after):
    """Each of the five, written and read, compared as the JSON.

    The two pairs are what make this worth parametrising rather than asserting
    once: ``hide`` and ``hideOnNextClick`` differ by a single attribute, and so
    do ``dim`` and ``dimColor``, so a reader that recognised the node and not
    the distinguishing attribute would return the wrong member of the pair and
    still look like it worked.
    """
    package = _package(tmp_path, _slide(animations={
        "mainSequence": [_effect(afterEffect=after)],
        "interactiveSequences": [],
    }))
    motion = _read(package)
    assert motion.raw_timing is None, (
        "a measured after-effect must not fall to raw replay"
    )
    assert motion.animations["mainSequence"][0]["afterEffect"] == after


def test_an_unqualified_dim_does_not_come_back_carrying_a_colour(tmp_path):
    """Because it writes one, and reporting it would change the document.

    An unqualified ``dim`` writes ``a:schemeClr val="accent2"`` — the one swatch
    that was measured. Reading that back as ``{"type": "dim", "color": ...}``
    would hand back JSON that differs from the JSON that produced the package
    while writing the same bytes, which is the failure the round-trip gate
    exists to catch.
    """
    package = _package(tmp_path, _slide(animations={
        "mainSequence": [_effect(afterEffect={"type": "dim"})],
        "interactiveSequences": [],
    }))
    assert "accent2" in _slide_xml(package)
    motion = _read(package)
    assert motion.animations["mainSequence"][0]["afterEffect"] == {"type": "dim"}


def test_a_dim_to_an_unmeasured_scheme_colour_is_kept_raw_rather_than_flattened(tmp_path):
    """The seven swatches nobody measured are the decks this protects.

    Only ``accent2`` inverts, because it is the only swatch whose mapping was
    measured. Mapping any other scheme colour to a bare ``dim`` would silently
    drop which colour the deck dims to — so the effect falls to raw replay,
    which keeps it.
    """
    package = _package(tmp_path, _slide(animations={
        "mainSequence": [_effect(afterEffect={"type": "dim"})],
        "interactiveSequences": [],
    }))

    def repoint(slide):
        for node in slide.iter():
            if node.tag.endswith("}schemeClr") and node.get("val") == "accent2":
                node.set("val", "accent4")

    _mutate(package, repoint)
    motion = _read(package)
    assert motion.animations is None, "it did not invert"
    assert motion.raw_timing is not None, (
        "an unmeasured scheme colour is preserved raw, not flattened to a bare dim"
    )
    assert b"accent4" in motion.raw_timing.xml


def test_bounce_end_round_trips_out_of_the_alternate_content_choice(tmp_path):
    """The wrapper has to be read back through, not merely written.

    The reader picks the `mc:Choice` branch because it implements `p14`, and the
    percentage comes back as the `0`–`1` fraction that produced it. The matching
    `p:animMotion/@p14:bounceEnd` is deliberately **not** reported as a second
    field: it is the same setting seen on the behaviour, and a JSON carrying it
    twice would not be the JSON that produced the package.
    """
    source = {"durationMs": 500, "bounceEnd": 0.5}
    package = _package(tmp_path, _slide(animations={
        "mainSequence": [
            _effect(
                preset={"category": "motionPath", "effect": "lines"},
                timing=dict(source),
            )
        ],
        "interactiveSequences": [],
    }))
    assert "AlternateContent" in _slide_xml(package), "the wrapper reached the package"

    motion = _read(package)
    assert motion.raw_timing is None, "the wrapper must be understood, not preserved raw"
    effect = motion.animations["mainSequence"][0]
    assert effect["timing"] == source
    assert "bounce" not in json.dumps(effect.get("behaviors") or [])


def test_rewind_round_trips_through_the_fill_attribute(tmp_path):
    """And its default does not come back as an explicit false.

    ``@fill`` is ``hold`` unless Rewind is on, so a reader that reported
    ``rewind: False`` for the default would add a key the input did not carry.
    """
    for timing, expected in (
        ({"durationMs": 500}, {"durationMs": 500}),
        ({"durationMs": 500, "rewind": True}, {"durationMs": 500, "rewind": True}),
    ):
        package = _package(
            tmp_path,
            _slide(animations={
                "mainSequence": [_effect(timing=timing)],
                "interactiveSequences": [],
            }),
            name=f"rewind-{'on' if timing.get('rewind') else 'off'}.pptx",
        )
        motion = _read(package)
        assert motion.raw_timing is None
        assert motion.animations["mainSequence"][0]["timing"] == expected


def _slide_xml(path):
    from lxml import etree

    slide = list(Presentation(str(path)).slides)[0]
    return etree.tostring(slide._element).decode()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
