# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""AlternateContent branch selection and relationship-bearing motion.

Two separate contracts meet here:

* ``mc:AlternateContent`` selection (REQ-5.3, REQ-5.4a) — Choice branches are
  evaluated in document order against the **versioned** supported-namespace set
  the catalog publishes, then Fallback, then raw preservation of every branch.
* Relationship handling (REQ-3.9, REQ-5.7) — a sound or media reference is
  either copied with its part and remapped, or the import fails. A dangling
  ``rId`` and an external link followed during import are both forbidden.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.package import Part
from pptx.opc.packuri import PackURI

from sdpm.engine.builder import PPTXBuilder
from sdpm.engine.converter.pipeline import pptx_to_json
from sdpm.engine.timing.raw import (
    ALLOWED_RELATIONSHIP_TYPES,
    RawReplayError,
    load_raw_manifest,
    remap_fragment,
    validate_raw_manifest,
)
from sdpm.engine.timing.reader import (
    MotionReadError,
    read_slide_motion,
    select_alternate_branch,
    select_representation,
    supported_requires,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "sdpm" / "templates" / "blank-dark.pptx"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 24


def _slide(**patch):
    slide = {
        "id": "animated",
        "layout": "Blank",
        "elements": [
            {"id": "hero", "type": "textbox", "text": "Hero", "x": 10, "y": 10,
             "width": 300, "height": 60},
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


def _mutate(path, mutate):
    presentation = Presentation(str(path))
    slide = list(presentation.slides)[0]
    mutate(slide)
    presentation.save(str(path))
    return path


def _read(path, slug="slide-001"):
    slide = list(Presentation(str(path)).slides)[0]
    return read_slide_motion(slide._element, slide_slug=slug, part=slide.part)


def _add_audio(slide, *, external=False):
    if external:
        return slide.part.relate_to("https://example.invalid/alarm.wav", RT.AUDIO, is_external=True)
    part = Part(PackURI("/ppt/media/audio1.wav"), "audio/wav", slide.part.package, WAV)
    return slide.part.relate_to(part, RT.AUDIO)


def _alternate(xml):
    return etree.fromstring(xml)


# --- branch selection ------------------------------------------------------


class TestAlternateContentSelection:
    def test_the_supported_set_is_the_versioned_catalog_set(self):
        assert supported_requires() == ("p14", "p15", "p159")

    def test_the_first_satisfied_choice_in_document_order_wins(self):
        node = _alternate(
            f'<mc:AlternateContent xmlns:mc="{MC}" xmlns:p="{P}">'
            '<mc:Choice Requires="p15"><p:transition spd="fast"/></mc:Choice>'
            '<mc:Choice Requires="p14"><p:transition spd="slow"/></mc:Choice>'
            '<mc:Fallback><p:transition spd="med"/></mc:Fallback>'
            "</mc:AlternateContent>"
        )
        selection = select_alternate_branch(node, "transition", supported=("p14", "p15"))
        assert selection.source == "choice"
        assert selection.node.get("spd") == "fast"
        assert [branch.requires for branch in selection.branches] == ["p15", "p14", ""]

    def test_an_unsupported_choice_falls_through_to_the_next_one(self):
        node = _alternate(
            f'<mc:AlternateContent xmlns:mc="{MC}" xmlns:p="{P}">'
            '<mc:Choice Requires="p99"><p:transition spd="fast"/></mc:Choice>'
            '<mc:Choice Requires="p14"><p:transition spd="slow"/></mc:Choice>'
            "</mc:AlternateContent>"
        )
        selection = select_alternate_branch(node, "transition", supported=("p14",))
        assert selection.node.get("spd") == "slow"
        assert [branch.satisfied for branch in selection.branches] == [False, True]

    def test_a_multi_token_choice_needs_every_token_supported(self):
        node = _alternate(
            f'<mc:AlternateContent xmlns:mc="{MC}" xmlns:p="{P}">'
            '<mc:Choice Requires="p14 p99"><p:transition spd="fast"/></mc:Choice>'
            '<mc:Fallback><p:transition spd="med"/></mc:Fallback>'
            "</mc:AlternateContent>"
        )
        selection = select_alternate_branch(node, "transition", supported=("p14", "p15", "p159"))
        assert selection.source == "fallback"
        assert selection.node.get("spd") == "med"

    def test_without_a_usable_branch_every_branch_is_reported_for_raw_retention(self):
        node = _alternate(
            f'<mc:AlternateContent xmlns:mc="{MC}" xmlns:p="{P}">'
            '<mc:Choice Requires="p99"><p:transition spd="fast"/></mc:Choice>'
            "</mc:AlternateContent>"
        )
        selection = select_alternate_branch(node, "transition", supported=("p14",))
        assert selection.node is None and selection.source == "none"
        assert selection.container is node
        assert [branch.kind for branch in selection.branches] == ["Choice"]
        assert "p14" in selection.reason

    def test_a_choice_without_requires_is_a_deterministic_error(self):
        node = _alternate(
            f'<mc:AlternateContent xmlns:mc="{MC}" xmlns:p="{P}">'
            "<mc:Choice><p:transition/></mc:Choice></mc:AlternateContent>"
        )
        with pytest.raises(MotionReadError, match="without @Requires"):
            select_alternate_branch(node, "transition", supported=("p14",))

    def test_an_unexpected_branch_element_is_a_deterministic_error(self):
        node = _alternate(
            f'<mc:AlternateContent xmlns:mc="{MC}" xmlns:p="{P}">'
            "<p:transition/></mc:AlternateContent>"
        )
        with pytest.raises(MotionReadError, match="unexpected child"):
            select_alternate_branch(node, "transition", supported=("p14",))

    def test_two_representations_of_one_feature_are_refused(self, tmp_path):
        """A direct child beside an AlternateContent wrapper is python-pptx
        issue 954; picking one silently is how a package gets corrupted."""
        def add_second(slide):
            slide._element.append(etree.fromstring(
                f'<mc:AlternateContent xmlns:mc="{MC}" xmlns:p="{P}">'
                '<mc:Choice Requires="p14"><p:transition spd="fast"><p:fade/></p:transition>'
                "</mc:Choice></mc:AlternateContent>"
            ))

        package = _mutate(_package(tmp_path, _slide(
            transition={"effect": "wipe", "parameters": {}, "durationMs": 1000,
                        "advance": {"onClick": True, "afterMs": None}, "sound": None},
        )), add_second)
        slide = list(Presentation(str(package)).slides)[0]
        with pytest.raises(MotionReadError, match="representations"):
            select_representation(slide._element, "transition", supported=("p14",))

    def test_an_unreadable_branch_set_is_preserved_whole(self, tmp_path):
        def replace(slide):
            for node in slide._element.findall("{%s}transition" % P):
                slide._element.remove(node)
            slide._element.append(etree.fromstring(
                f'<mc:AlternateContent xmlns:mc="{MC}" xmlns:p="{P}">'
                '<mc:Choice Requires="p2051"><p:transition spd="fast">'
                '<p:futureEffect/></p:transition></mc:Choice>'
                "</mc:AlternateContent>"
            ))

        motion = _read(_mutate(_package(tmp_path, _slide(
            transition={"effect": "wipe", "parameters": {}, "durationMs": 1000,
                        "advance": {"onClick": True, "afterMs": None}, "sound": None},
        )), replace))
        assert motion.transition is None
        fragment = motion.raw_transition
        assert fragment is not None
        assert b"p2051" in fragment.xml and b"futureEffect" in fragment.xml
        assert [branch.kind for branch in fragment.branches] == ["Choice"]
        assert "mc" in fragment.namespaces


# --- semantic sound --------------------------------------------------------


class TestSemanticSoundAsset:
    def _with_sound(self, tmp_path, loop=False):
        def attach(slide):
            rid = _add_audio(slide)
            node = slide._element.find("{%s}transition" % P)
            sound = etree.SubElement(node, "{%s}sndAc" % P)
            start = etree.SubElement(sound, "{%s}stSnd" % P)
            if loop:
                start.set("loop", "1")
            snd = etree.SubElement(start, "{%s}snd" % P)
            snd.set("{%s}embed" % R, rid)
            snd.set("name", "alarm.wav")

        return _mutate(_package(tmp_path, _slide(
            transition={"effect": "wipe", "parameters": {}, "durationMs": 1000,
                        "advance": {"onClick": True, "afterMs": None}, "sound": None},
        )), attach)

    def test_a_transition_sound_becomes_a_bundle_relative_asset_reference(self, tmp_path):
        motion = _read(self._with_sound(tmp_path))
        assert motion.transition is not None, "a sound does not make the transition unreadable"
        assert motion.transition["sound"] == {
            "src": "media/slide-001-audio1.wav",
            "mediaType": "audio/wav",
            "loop": False,
        }
        assert len(motion.assets) == 1
        asset = motion.assets[0]
        assert asset.blob == WAV
        assert asset.relationship_type in ALLOWED_RELATIONSHIP_TYPES, (
            "generation has to be able to recreate the relationship from this record"
        )

    def test_loop_until_next_sound_survives(self, tmp_path):
        motion = _read(self._with_sound(tmp_path, loop=True))
        assert motion.transition["sound"]["loop"] is True

    def test_the_asset_lands_in_the_deck_and_the_manifest(self, tmp_path):
        pptx_to_json(self._with_sound(tmp_path), tmp_path / "out")
        slide = json.loads((tmp_path / "out" / "slides" / "slide-001.json").read_text())
        src = slide["transition"]["sound"]["src"]
        assert (tmp_path / "out" / src).read_bytes() == WAV
        manifest = load_raw_manifest(tmp_path / "out" / "animations" / "manifest.json")
        validate_raw_manifest(manifest, root=tmp_path / "out")
        assert [asset["path"] for asset in manifest["assets"]] == [src]

    def test_an_external_sound_relationship_is_refused(self, tmp_path):
        def attach(slide):
            rid = _add_audio(slide, external=True)
            node = slide._element.find("{%s}transition" % P)
            sound = etree.SubElement(node, "{%s}sndAc" % P)
            start = etree.SubElement(sound, "{%s}stSnd" % P)
            snd = etree.SubElement(start, "{%s}snd" % P)
            snd.set("{%s}embed" % R, rid)

        package = _mutate(_package(tmp_path, _slide(
            transition={"effect": "wipe", "parameters": {}, "durationMs": 1000,
                        "advance": {"onClick": True, "afterMs": None}, "sound": None},
        )), attach)
        with pytest.raises(MotionReadError, match="external relationship"):
            _read(package)

    def test_a_sound_naming_a_missing_relationship_is_refused(self, tmp_path):
        def attach(slide):
            node = slide._element.find("{%s}transition" % P)
            sound = etree.SubElement(node, "{%s}sndAc" % P)
            start = etree.SubElement(sound, "{%s}stSnd" % P)
            snd = etree.SubElement(start, "{%s}snd" % P)
            snd.set("{%s}embed" % R, "rId999")

        package = _mutate(_package(tmp_path, _slide(
            transition={"effect": "wipe", "parameters": {}, "durationMs": 1000,
                        "advance": {"onClick": True, "afterMs": None}, "sound": None},
        )), attach)
        with pytest.raises(MotionReadError, match="does not exist in the package"):
            _read(package)


# --- relationship-bearing raw timing --------------------------------------


def _raw_timing_with_sound(tmp_path):
    """A slide whose timing sdpm cannot decode and which names an audio part."""
    def attach(slide):
        rid = _add_audio(slide)
        for node in slide._element.findall("{%s}timing" % P):
            slide._element.remove(node)
        spid = slide.shapes[0].shape_id
        slide._element.append(etree.fromstring(
            f'<p:timing xmlns:p="{P}" xmlns:r="{R}"><p:tnLst><p:par>'
            '<p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
            '<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" nodeType="mainSeq">'
            '<p:childTnLst><p:par><p:cTn id="3" futureThing="7">'
            f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'
            f'<p:snd r:embed="{rid}" name="alarm.wav"/>'
            "</p:cTn></p:par></p:childTnLst>"
            "</p:cTn></p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>"
        ))

    return _mutate(_package(tmp_path, _slide(), animations=False), attach)


class TestRawRelationshipPreservation:
    def test_the_relationship_part_is_copied_and_recorded(self, tmp_path):
        motion = _read(_raw_timing_with_sound(tmp_path))
        fragment = motion.raw_timing
        assert fragment is not None
        assert len(fragment.relationships) == 1
        reference = fragment.relationships[0]
        assert reference.relationship_type == RT.AUDIO
        assert reference.target_mode == "Internal"
        assert reference.blob == WAV

    def test_the_bundle_holds_the_part_with_its_hash(self, tmp_path):
        pptx_to_json(_raw_timing_with_sound(tmp_path), tmp_path / "out")
        manifest = load_raw_manifest(tmp_path / "out" / "animations" / "manifest.json")
        closure = validate_raw_manifest(manifest, root=tmp_path / "out")
        parts = [part for part in closure if part.kind == "part"]
        assert len(parts) == 1
        assert parts[0].relationship_type == RT.AUDIO
        assert (tmp_path / "out" / parts[0].path).read_bytes() == WAV

    def test_replay_recreates_the_relationship_and_rewrites_the_rid(self, tmp_path):
        pptx_to_json(_raw_timing_with_sound(tmp_path), tmp_path / "out")
        manifest = load_raw_manifest(tmp_path / "out" / "animations" / "manifest.json")
        record = manifest["sidecars"][0]
        xml = (tmp_path / "out" / record["path"]).read_bytes()
        asked: list[tuple[str, str, str]] = []

        def resolve_relationship(part, relationship_type, content_type):
            asked.append((part, relationship_type, content_type))
            return "rId77"

        node = remap_fragment(
            xml,
            shape_mappings=record["shapeMappings"],
            relationships=record["relationships"],
            resolve_shape=lambda logical: 99,
            resolve_relationship=resolve_relationship,
            what="test",
        )
        assert node.find(".//{%s}snd" % P).get("{%s}embed" % R) == "rId77"
        assert node.find(".//{%s}spTgt" % P).get("spid") == "99"
        assert asked and asked[0][1] == RT.AUDIO
        assert asked[0][0].startswith("animations/media/")

    def test_replay_without_a_resolver_refuses_rather_than_dangling(self, tmp_path):
        pptx_to_json(_raw_timing_with_sound(tmp_path), tmp_path / "out")
        manifest = load_raw_manifest(tmp_path / "out" / "animations" / "manifest.json")
        record = manifest["sidecars"][0]
        with pytest.raises(RawReplayError, match="no relationship resolver"):
            remap_fragment(
                (tmp_path / "out" / record["path"]).read_bytes(),
                shape_mappings=record["shapeMappings"],
                relationships=record["relationships"],
                resolve_shape=lambda logical: 99,
                resolve_relationship=None,
                what="test",
            )

    def test_an_unrecorded_relationship_cannot_be_replayed(self, tmp_path):
        pptx_to_json(_raw_timing_with_sound(tmp_path), tmp_path / "out")
        manifest = load_raw_manifest(tmp_path / "out" / "animations" / "manifest.json")
        record = manifest["sidecars"][0]
        with pytest.raises(RawReplayError, match="dangling rId"):
            remap_fragment(
                (tmp_path / "out" / record["path"]).read_bytes(),
                shape_mappings=record["shapeMappings"],
                relationships=[],
                resolve_shape=lambda logical: 99,
                resolve_relationship=lambda *_: "rId1",
                what="test",
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
