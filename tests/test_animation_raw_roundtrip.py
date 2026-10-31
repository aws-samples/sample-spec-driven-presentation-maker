# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Raw fallback: sidecar closure, manifest validation, and replay.

Preserving XML is the easy half. These tests cover the half that makes it
lossless: the slide JSON keeps only a reference, the sidecar keeps every
retained branch, the manifest declares the complete hashed dependency closure
(the contract remote materialisation validates in Task 6), and replay rewrites
every shape and relationship ID or fails — it never leaves a stale ``spid`` or
a dangling ``rId`` behind.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation

from sdpm.engine.builder import PPTXBuilder
from sdpm.engine.converter.pipeline import pptx_to_json
from sdpm.engine.timing.raw import (
    MANIFEST_PATH,
    RAW_MANIFEST_VERSION,
    RawManifestError,
    RawReplayError,
    apply_raw_fragment,
    load_raw_manifest,
    manifest_dependency_closure,
    remap_fragment,
    replay_raw_fragment,
    safe_bundle_path,
    validate_raw_manifest,
)
from sdpm.engine.timing.reader import (
    MediaBoundaryError,
    classify_media_boundary,
    media_only_timing,
    read_slide_motion,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "sdpm" / "templates" / "blank-dark.pptx"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"

#: An object-animation branch no sdpm version understands, so the tree is
#: preserved instead of decoded. ``{spid}`` is filled in with a real shape.
UNKNOWN_SEQ = (
    '<p:seq xmlns:p="%s" concurrent="1" nextAc="seek">'
    '<p:cTn id="20" nodeType="mainSeq"><p:childTnLst>'
    '<p:par><p:cTn id="21" futureThing="7">'
    '<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'
    "</p:cTn></p:par></p:childTnLst></p:cTn></p:seq>"
) % P


def _video_slide():
    return {
        "id": "media",
        "layout": "Blank",
        "elements": [
            {"id": "clip", "type": "video", "src": "clip.mp4", "x": 10, "y": 10,
             "width": 320, "height": 180},
            {"id": "hero", "type": "textbox", "text": "Hero", "x": 10, "y": 220,
             "width": 300, "height": 60},
        ],
    }


@pytest.fixture()
def media_dir(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 128)
    return tmp_path


def _package(base_dir, slide_def, *, animations=False, name="deck.pptx"):
    builder = PPTXBuilder(
        TEMPLATE,
        fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"},
        default_text_color="#FFFFFF",
        base_dir=base_dir,
        animations_enabled=animations,
        transitions_enabled=False,
    )
    builder.add_slide(slide_def)
    out = base_dir / name
    builder.save(out)
    return out


def _inject_unknown_sequence(path, *, nest_media=False):
    presentation = Presentation(str(path))
    slide = list(presentation.slides)[0]
    spid = slide.shapes[0].shape_id
    timing = slide._element.find("{%s}timing" % P)
    children = timing.find(
        "{%s}tnLst/{%s}par/{%s}cTn/{%s}childTnLst" % (P, P, P, P)
    )
    sequence = etree.fromstring(UNKNOWN_SEQ.format(spid=spid))
    if nest_media:
        video = children.find("{%s}video" % P)
        children.remove(video)
        sequence.find("{%s}cTn/{%s}childTnLst" % (P, P)).append(video)
    children.append(sequence)
    presentation.save(str(path))
    return path


def _read(path, slug="slide-001"):
    slide = list(Presentation(str(path)).slides)[0]
    return read_slide_motion(slide._element, slide_slug=slug, part=slide.part)


# --- the slide JSON side ---------------------------------------------------


class TestSlideJsonReference:
    def test_the_slide_keeps_a_reference_not_the_xml(self, media_dir):
        pptx_to_json(_inject_unknown_sequence(_package(media_dir, _video_slide())),
                     media_dir / "out")
        slide = json.loads((media_dir / "out" / "slides" / "slide-001.json").read_text())
        assert set(slide["_rawTiming"]) == {"sidecar", "sha256", "manifest", "reason"}
        assert "animations" not in slide
        flat = json.dumps(slide)
        # The reference names the reason in prose; the XML itself stays in the
        # sidecar, so no element markup is embedded in the slide JSON.
        assert "<p:" not in flat and "</p:" not in flat
        assert len(flat) < 4000

    def test_the_referenced_sidecar_exists_and_matches_its_digest(self, media_dir):
        pptx_to_json(_inject_unknown_sequence(_package(media_dir, _video_slide())),
                     media_dir / "out")
        slide = json.loads((media_dir / "out" / "slides" / "slide-001.json").read_text())
        reference = slide["_rawTiming"]
        sidecar = media_dir / "out" / reference["sidecar"]
        assert sidecar.is_file()
        assert b"futureThing" in sidecar.read_bytes()
        manifest = load_raw_manifest(media_dir / "out" / reference["manifest"])
        validate_raw_manifest(manifest, root=media_dir / "out")

    def test_the_raw_target_is_stamped_onto_the_element_that_recreates_it(self, media_dir):
        pptx_to_json(_inject_unknown_sequence(_package(media_dir, _video_slide())),
                     media_dir / "out")
        slide = json.loads((media_dir / "out" / "slides" / "slide-001.json").read_text())
        manifest = load_raw_manifest(media_dir / "out" / MANIFEST_PATH)
        mapped = set(manifest["sidecars"][0]["shapeMappings"].values())
        stamped = {element["id"] for element in slide["elements"] if "id" in element}
        assert mapped and mapped <= stamped, (
            "every raw spid mapping needs a JSON element carrying that logical id, "
            "otherwise replay can never resolve it"
        )


# --- the manifest ----------------------------------------------------------


class TestManifestClosure:
    def _manifest(self, media_dir):
        pptx_to_json(_inject_unknown_sequence(_package(media_dir, _video_slide())),
                     media_dir / "out")
        return load_raw_manifest(media_dir / "out" / MANIFEST_PATH), media_dir / "out"

    def test_the_closure_lists_every_file_it_declares(self, media_dir):
        manifest, root = self._manifest(media_dir)
        closure = manifest_dependency_closure(manifest)
        assert closure, "a preserved slide has a non-empty closure"
        for relative in closure:
            assert (root / relative).is_file()
        assert closure == tuple(sorted(closure)), "the closure is deterministic"

    def test_provenance_records_the_source_without_a_wall_clock_stamp(self, media_dir):
        manifest, _root = self._manifest(media_dir)
        provenance = manifest["provenance"]
        assert provenance["sourceFile"] == "deck.pptx"
        assert provenance["sidecarSchema"] == RAW_MANIFEST_VERSION
        assert set(provenance) == {
            "sourceFile", "sourceApplication", "sourceAppVersion", "sidecarSchema",
        }

    def test_a_tampered_file_fails_validation(self, media_dir):
        manifest, root = self._manifest(media_dir)
        target = root / manifest["sidecars"][0]["path"]
        target.write_bytes(target.read_bytes() + b"<!-- edited -->")
        with pytest.raises(RawManifestError, match="digest mismatch"):
            validate_raw_manifest(manifest, root=root)

    def test_a_missing_file_fails_validation(self, media_dir):
        manifest, root = self._manifest(media_dir)
        (root / manifest["sidecars"][0]["path"]).unlink()
        with pytest.raises(RawManifestError, match="missing"):
            validate_raw_manifest(manifest, root=root)

    @pytest.mark.parametrize(
        "path",
        ["../escape.xml", "/etc/passwd", "animations/../../escape.xml",
         "animations\\windows.xml", "animations//double.xml", ""],
    )
    def test_a_path_outside_the_bundle_is_rejected(self, path):
        with pytest.raises(RawManifestError):
            safe_bundle_path(path, what="test path")

    def test_a_wrong_version_is_rejected(self):
        with pytest.raises(RawManifestError, match="version"):
            validate_raw_manifest({"version": 99, "sidecars": [], "parts": [], "assets": []})

    def test_an_external_relationship_record_is_rejected(self):
        manifest = {
            "version": RAW_MANIFEST_VERSION,
            "sidecars": [{
                "slide": "slide-001", "kind": "timing", "path": "animations/a.xml",
                "sha256": "0" * 64, "shapeMappings": {}, "mediaBoundary": "notApplicable",
                "relationships": [{
                    "rId": "rId2", "targetMode": "External",
                    "relationshipType": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/audio",
                    "contentType": "audio/wav", "part": "animations/media/a.wav",
                    "sha256": "1" * 64,
                }],
            }],
            "parts": [], "assets": [],
        }
        with pytest.raises(RawManifestError, match="not Internal"):
            validate_raw_manifest(manifest)

    def test_a_relationship_whose_part_is_not_declared_is_rejected(self):
        manifest = {
            "version": RAW_MANIFEST_VERSION,
            "sidecars": [{
                "slide": "slide-001", "kind": "timing", "path": "animations/a.xml",
                "sha256": "0" * 64, "shapeMappings": {}, "mediaBoundary": "notApplicable",
                "relationships": [{
                    "rId": "rId2", "targetMode": "Internal",
                    "relationshipType": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/audio",
                    "contentType": "audio/wav", "part": "animations/media/a.wav",
                    "sha256": "1" * 64,
                }],
            }],
            "parts": [], "assets": [],
        }
        with pytest.raises(RawManifestError, match="closure is incomplete"):
            validate_raw_manifest(manifest)

    def test_a_relationship_type_outside_the_allowlist_is_rejected(self):
        manifest = {
            "version": RAW_MANIFEST_VERSION,
            "sidecars": [],
            "parts": [{
                "path": "animations/media/a.bin", "sha256": "1" * 64,
                "relationshipType": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject",
                "contentType": "application/vnd.ms-office",
            }],
            "assets": [],
        }
        with pytest.raises(RawManifestError, match="not one sdpm copies"):
            validate_raw_manifest(manifest)

    def test_a_bogus_shape_mapping_is_rejected(self):
        manifest = {
            "version": RAW_MANIFEST_VERSION,
            "sidecars": [{
                "slide": "slide-001", "kind": "timing", "path": "animations/a.xml",
                "sha256": "0" * 64, "mediaBoundary": "notApplicable", "relationships": [],
                "shapeMappings": {"not-a-spid": "hero"},
            }],
            "parts": [], "assets": [],
        }
        with pytest.raises(RawManifestError, match="not a source spid"):
            validate_raw_manifest(manifest)


# --- replay ----------------------------------------------------------------


class TestReplay:
    def _imported(self, media_dir, *, nest_media=False):
        pptx_to_json(
            _inject_unknown_sequence(_package(media_dir, _video_slide()), nest_media=nest_media),
            media_dir / "out",
        )
        slide = json.loads((media_dir / "out" / "slides" / "slide-001.json").read_text())
        return slide, media_dir / "out"

    def test_replay_rewrites_the_spid_to_the_new_builds_shape(self, media_dir):
        slide, root = self._imported(media_dir)
        node = replay_raw_fragment(
            slide["_rawTiming"], root=root, resolve_shape=lambda logical: 404,
        )
        spids = {element.get("spid") for element in node.iter("{%s}spTgt" % P)}
        assert spids == {"404"}

    def test_replay_fails_when_a_logical_target_is_gone(self, media_dir):
        slide, root = self._imported(media_dir)

        def missing(logical):
            raise KeyError(f"unknown element {logical}")

        with pytest.raises(RawReplayError, match="not on the generated slide"):
            replay_raw_fragment(slide["_rawTiming"], root=root, resolve_shape=missing)

    def test_an_unmapped_spid_is_refused_rather_than_left_stale(self, media_dir):
        slide, root = self._imported(media_dir)
        manifest = load_raw_manifest(root / MANIFEST_PATH)
        record = manifest["sidecars"][0]
        with pytest.raises(RawReplayError, match="records no logical element"):
            remap_fragment(
                (root / record["path"]).read_bytes(),
                shape_mappings={},
                relationships=[],
                resolve_shape=lambda logical: 1,
                resolve_relationship=None,
                what="test",
            )

    def test_an_spid_on_an_element_sdpm_cannot_remap_is_refused(self):
        xml = (
            '<p:timing xmlns:p="%s"><p:tnLst><p:par><p:cTn id="1">'
            '<p:futureTarget spid="5"/></p:cTn></p:par></p:tnLst></p:timing>' % P
        ).encode()
        with pytest.raises(RawReplayError, match="cannot remap"):
            remap_fragment(
                xml, shape_mappings={"5": "hero"}, relationships=[],
                resolve_shape=lambda logical: 9, resolve_relationship=None, what="test",
            )

    def test_a_tampered_sidecar_is_not_replayed(self, media_dir):
        slide, root = self._imported(media_dir)
        target = root / slide["_rawTiming"]["sidecar"]
        target.write_bytes(target.read_bytes().replace(b"futureThing", b"futureThinG"))
        with pytest.raises(RawReplayError, match="recorded digest"):
            replay_raw_fragment(slide["_rawTiming"], root=root, resolve_shape=lambda _: 1)

    def test_animations_off_replays_only_the_media_timing(self, media_dir):
        slide, root = self._imported(media_dir)
        node = replay_raw_fragment(
            slide["_rawTiming"], root=root, resolve_shape=lambda logical: 404,
            animations_enabled=False,
        )
        locals_ = [etree.QName(child).localname for child in node.iter() if isinstance(child.tag, str)]
        assert "video" in locals_, "REQ-5.4: the media timing survives animation-off"
        assert "seq" not in locals_, "the raw object-animation branch is suppressed"

    def test_animations_off_fails_when_the_boundary_is_unclassifiable(self, media_dir):
        slide, root = self._imported(media_dir, nest_media=True)
        manifest = load_raw_manifest(root / MANIFEST_PATH)
        assert manifest["sidecars"][0]["mediaBoundary"] == "unclassified"
        with pytest.raises(RawReplayError, match="cannot separate"):
            replay_raw_fragment(
                slide["_rawTiming"], root=root, resolve_shape=lambda _: 1,
                animations_enabled=False,
            )

    def test_applying_a_fragment_leaves_one_representation_in_schema_order(self, media_dir):
        slide, root = self._imported(media_dir)
        target = _package(media_dir, _video_slide(), name="target.pptx")
        presentation = Presentation(str(target))
        slide_object = list(presentation.slides)[0]
        apply_raw_fragment(
            slide_object._element, slide["_rawTiming"], root=root,
            resolve_shape=lambda logical: slide_object.shapes[0].shape_id,
        )
        order = [etree.QName(child).localname for child in slide_object._element]
        assert order[-1] == "timing"
        assert order.count("timing") == 1, "the replaced representation is gone"
        assert b"futureThing" in etree.tostring(slide_object._element), (
            "the preserved branch really landed in the package"
        )


# --- media boundary classification ----------------------------------------


class TestMediaBoundary:
    def _timing(self, xml):
        return etree.fromstring(xml)

    def test_a_clean_split_is_classified(self, media_dir):
        package = _inject_unknown_sequence(_package(media_dir, _video_slide()))
        slide = list(Presentation(str(package)).slides)[0]
        timing = slide._element.find("{%s}timing" % P)
        media, objects = classify_media_boundary(timing)
        assert len(media) == 1 and len(objects) == 1
        reduced = media_only_timing(timing)
        assert b"<p:video" in reduced or b":video" in reduced
        assert b"futureThing" not in reduced

    def test_media_nested_in_an_object_sequence_cannot_be_split(self, media_dir):
        package = _inject_unknown_sequence(
            _package(media_dir, _video_slide()), nest_media=True
        )
        slide = list(Presentation(str(package)).slides)[0]
        with pytest.raises(MediaBoundaryError, match="media nodes"):
            classify_media_boundary(slide._element.find("{%s}timing" % P))

    def test_an_unknown_node_under_the_time_root_cannot_be_split(self):
        timing = self._timing(
            '<p:timing xmlns:p="%s"><p:tnLst><p:par>'
            '<p:cTn id="1" nodeType="tmRoot"><p:childTnLst>'
            '<p:excl><p:cTn id="2"/></p:excl>'
            "</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>" % P
        )
        with pytest.raises(MediaBoundaryError, match="classify"):
            classify_media_boundary(timing)

    def test_a_timing_tree_without_media_reduces_to_nothing(self):
        timing = self._timing(
            '<p:timing xmlns:p="%s"><p:tnLst><p:par>'
            '<p:cTn id="1" nodeType="tmRoot"><p:childTnLst>'
            '<p:seq><p:cTn id="2" nodeType="mainSeq"/></p:seq>'
            "</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>" % P
        )
        assert media_only_timing(timing) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
