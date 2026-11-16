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

import hashlib
import json
import shutil
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
    MEDIA_CTN_DEFAULTS,
    MEDIA_NODE_DEFAULTS,
    MEDIA_START_DELAY,
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


def _repack(source, destination, app_xml):
    """Copy a package, replacing ``docProps/app.xml`` with hostile bytes."""
    import zipfile

    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(destination, "w") as zout:
        for item in zin.infolist():
            data = app_xml if item.filename == "docProps/app.xml" else zin.read(item.filename)
            zout.writestr(item, data)
    return destination


class TestHostileSourceProperties:
    """The provenance reader must survive the input it uses defusedxml for.

    It parses `docProps/app.xml` out of a PPTX the user supplied, which is why
    it uses `defusedxml` rather than the stdlib parser. It caught `ParseError`
    only, and defusedxml signals a *refusal* with `EntitiesForbidden` /
    `ExternalReferenceForbidden` — `DefusedXmlException`, which derives from
    `ValueError`, not from `ParseError`. `pptx_to_json` calls it unguarded, so
    the one input the safe parser was chosen for failed the whole conversion.
    """

    ENTITY_APP = (
        b'<?xml version="1.0"?>\n'
        b'<!DOCTYPE Properties [<!ENTITY boom "boom">]>\n'
        b'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/'
        b'2006/extended-properties"><Application>&boom;</Application></Properties>'
    )

    def test_the_refusal_is_not_a_parse_error(self):
        """Pins the premise, so this does not quietly stop testing anything."""
        from defusedxml.common import DefusedXmlException
        from defusedxml.ElementTree import ParseError, fromstring

        with pytest.raises(DefusedXmlException) as caught:
            fromstring(self.ENTITY_APP)
        assert not isinstance(caught.value, ParseError)

    def test_an_entity_declaration_records_nulls_rather_than_failing(self, media_dir):
        from sdpm.engine.converter.pipeline import _source_provenance

        hostile = _repack(
            _package(media_dir, _video_slide(), name="clean.pptx"),
            media_dir / "hostile.pptx",
            self.ENTITY_APP,
        )
        provenance = _source_provenance(hostile)
        assert provenance["sourceFile"] == "hostile.pptx"
        assert provenance["sourceApplication"] is None
        assert provenance["sourceAppVersion"] is None

    def test_the_conversion_completes(self, media_dir):
        hostile = _repack(
            _package(media_dir, _video_slide(), name="clean.pptx"),
            media_dir / "hostile.pptx",
            self.ENTITY_APP,
        )
        pptx_to_json(hostile, media_dir / "out")
        assert (media_dir / "out" / "slides" / "slide-001.json").exists()


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


# --- regeneration: the builder replays what the import preserved ----------

#: A raw fragment that also names a package relationship, so replay has to
#: copy the part and rewrite the rId as well as the spid.
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
UNREADABLE_TRANSITION = (
    '<mc:AlternateContent xmlns:mc="%s" xmlns:p="%s">'
    '<mc:Choice Requires="p2051"><p:transition spd="fast">'
    "<p:futureEffect/></p:transition></mc:Choice></mc:AlternateContent>"
) % (MC, P)


def _inject_sound(path):
    """Attach an audio part and an unreadable timing tree that names it."""
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    from pptx.opc.package import Part
    from pptx.opc.packuri import PackURI

    presentation = Presentation(str(path))
    slide = list(presentation.slides)[0]
    rid = slide.part.relate_to(
        Part(PackURI("/ppt/media/audio1.wav"), "audio/wav", slide.part.package, WAV), RT.AUDIO,
    )
    spid = slide.shapes[-1].shape_id
    for node in slide._element.findall("{%s}timing" % P):
        slide._element.remove(node)
    slide._element.append(etree.fromstring(
        '<p:timing xmlns:p="%s" xmlns:r="%s"><p:tnLst><p:par>'
        '<p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
        '<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" nodeType="mainSeq"><p:childTnLst>'
        '<p:par><p:cTn id="3" futureThing="7">'
        '<p:tgtEl><p:spTgt spid="%d"/></p:tgtEl>'
        '<p:snd r:embed="%s" name="alarm.wav"/>'
        "</p:cTn></p:par></p:childTnLst></p:cTn></p:seq>"
        "</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>" % (P, R, spid, rid)
    ))
    presentation.save(str(path))
    return path


class TestMediaPlaybackSettingsSurvive:
    """A media node is not represented in JSON, so anything extra must go raw.

    `_read_media` allowed `@vol`, `@mute`, `@numSld`, `@showWhenStopped` and the
    `p:cTn`'s `@dur` / `@restart` through and then represented none of them,
    because the builder recreates the node from the `video` element. A muted
    clip came back unmuted and a clip at half volume came back at 80%. Only the
    node the builder writes is accepted now; the rest is preserved.
    """

    def test_the_replayed_slot_comes_from_the_manifest_not_the_xml(self, media_dir):
        """The record's `kind` decides the slot, not a scan of the bytes.

        `apply_raw_fragment` used to sniff the replayed XML for a `p:transition`
        anywhere inside it. For every fragment sdpm writes the two agree, so
        this pins the precedence with one where they cannot: a sidecar recorded
        as `timing` whose XML carries a `p:transition` descendant. The old code
        put that tree in the transition slot and left the slide with no timing.
        """
        slide, root = _import(media_dir, _inject_unknown_sequence(
            _package(media_dir, _video_slide())
        ))
        reference = slide["_rawTiming"]
        sidecar = root / reference["sidecar"]
        xml = sidecar.read_bytes().replace(
            b"<p:tnLst>", b"<p:tnLst><p:transition spd=\"fast\"><p:fade/></p:transition>", 1,
        )
        sidecar.write_bytes(xml)

        # The manifest's digest covers the sidecar, so it is restated here: the
        # point under test is the slot, not the integrity check.
        manifest = load_raw_manifest(root / MANIFEST_PATH)
        record = next(r for r in manifest["sidecars"] if r["path"] == reference["sidecar"])
        assert record["kind"] == "timing"
        digest = hashlib.sha256(xml).hexdigest()
        record["sha256"] = digest
        reference = {**reference, "sha256": digest}

        # A slide that already has its own p:timing, which replaying into the
        # timing slot must replace. Sniffing the bytes sent the fragment to the
        # transition slot instead, leaving the old timing in place: the slide
        # ended up with two p:timing children, which is the corruption
        # python-pptx issue 954 describes.
        target = etree.fromstring(etree.tostring(list(Presentation(str(
            _package(media_dir, _video_slide(), name="slot.pptx")
        )).slides)[0]._element))
        assert len(target.findall("{%s}timing" % P)) == 1, "the fixture starts with one"

        apply_raw_fragment(
            target,
            reference,
            root=root,
            resolve_shape=lambda logical: 2,
            manifest=manifest,
        )
        assert len(target.findall("{%s}timing" % P)) == 1, (
            "the replayed timing replaced the slide's own, rather than landing "
            "in the transition slot beside it"
        )
        assert b"futureThing" in etree.tostring(target), "it is the replayed one"

    def test_a_record_without_a_kind_cannot_be_read_as_a_transition(self, media_dir):
        """`str(None)` is `"None"`, which fell into the caller's else branch —
        removing the transition and leaving the slide's own `p:timing` beside
        the replayed one.

        On the in-tree path `replay_raw_fragment`'s own shape validation rejects
        a kind-less record before this is reached, so the guard covers the case
        the review named: a manifest handed in by a caller that validated
        nothing. It is tested at that seam rather than through
        `apply_raw_fragment`, which cannot get there.
        """
        from sdpm.engine.timing.raw import _fragment_kind

        slide, root = _import(media_dir, _inject_unknown_sequence(
            _package(media_dir, _video_slide())
        ))
        manifest = load_raw_manifest(root / MANIFEST_PATH)
        record = next(
            r for r in manifest["sidecars"] if r["path"] == slide["_rawTiming"]["sidecar"]
        )
        assert _fragment_kind(slide["_rawTiming"], root=root, manifest=manifest) == "timing"

        del record["kind"]
        with pytest.raises(RawManifestError, match="must be 'timing' or 'transition'"):
            _fragment_kind(slide["_rawTiming"], root=root, manifest=manifest)

    def test_a_media_node_without_a_start_condition_is_preserved(self, media_dir):
        """The guard only ran when the start list was present, so a node with
        none imported semantically and was rebuilt with the builder's
        `delay="indefinite"` rather than the source's absence of one."""
        package = _package(media_dir, _video_slide(), name="nostart.pptx")
        presentation = Presentation(str(package))
        slide = list(presentation.slides)[0]
        media = next(
            node for node in slide._element.iter()
            if isinstance(node.tag, str) and etree.QName(node).localname == "cMediaNode"
        )
        ctn = media.find("{%s}cTn" % P)
        ctn.remove(ctn.find("{%s}stCondLst" % P))
        presentation.save(str(package))

        motion = _read(package)
        assert motion.animations is None, "an absent start condition is not the builder's node"
        assert motion.raw_timing is not None

    def test_a_tampered_media_only_sidecar_is_refused(self, media_dir):
        """Only the full sidecar's digest was checked here. In tree that was
        covered because the builder validates the whole closure against a root
        first, but `replay_raw_fragment` also accepts a manifest with no root —
        and then nothing verified the file it actually replayed."""
        slide, root = _import(media_dir, _inject_unknown_sequence(
            _package(media_dir, _video_slide())
        ))
        manifest = load_raw_manifest(root / MANIFEST_PATH)
        record = next(
            r for r in manifest["sidecars"] if r["path"] == slide["_rawTiming"]["sidecar"]
        )
        assert record["mediaBoundary"] == "classified"
        media_only = record.get("mediaOnlyPath")
        assert media_only, "the fixture must have a media-only variant to tamper with"
        target = root / media_only
        target.write_bytes(target.read_bytes().replace(b'dur="indefinite"', b'dur="indefinit3"'))

        # Rootless: the closure is not revalidated, so the digest carried in the
        # record is the only thing standing between this and a silent replay.
        with pytest.raises(RawReplayError, match="recorded digest"):
            replay_raw_fragment(
                slide["_rawTiming"],
                root=root,
                resolve_shape=lambda logical: 2,
                animations_enabled=False,
                manifest=manifest,
            )

    def test_the_manifest_is_written_as_bytes_so_its_newlines_are_the_same_everywhere(
        self, media_dir,
    ):
        """`write_text` translates "\\n" to `os.linesep`.

        Every file the manifest names is written with `write_bytes` and carries
        a SHA-256, and a deck is synced between a Windows workstation and Linux
        CI, so the manifest was the one file in the subtree whose bytes depended
        on the platform that wrote it.
        """
        _slide, root = _import(media_dir, _inject_sound(
            _package(media_dir, _video_slide(), name="newlines.pptx")
        ))
        data = (root / MANIFEST_PATH).read_bytes()
        assert b"\r\n" not in data, "the manifest must not pick up platform line endings"
        assert data.endswith(b"\n")

    def test_the_accepted_media_node_is_the_one_the_builder_writes(self, media_dir):
        """Pins the reader's accepted defaults against the builder's output.

        These are python-pptx's `add_movie` values. If it ever writes different
        ones, every video would import raw with no other warning, so the two
        statements are compared here rather than kept in step by hand.
        """
        package = _package(media_dir, _video_slide(), name="defaults.pptx")
        slide = list(Presentation(str(package)).slides)[0]
        nodes = [
            node for node in slide._element.iter()
            if isinstance(node.tag, str) and etree.QName(node).localname == "video"
        ]
        assert len(nodes) == 1, "the fixture must carry one video"
        media = nodes[0].find("{%s}cMediaNode" % P)
        assert dict(media.attrib) == MEDIA_NODE_DEFAULTS
        ctn = media.find("{%s}cTn" % P)
        assert {k: v for k, v in ctn.attrib.items() if k != "id"} == MEDIA_CTN_DEFAULTS
        conditions = ctn.findall("{%s}stCondLst/{%s}cond" % (P, P))
        assert [cond.get("delay") for cond in conditions] == [MEDIA_START_DELAY]

    def _with_media_attr(self, media_dir, *, on, name, **attrs):
        package = _package(media_dir, _video_slide(), name=name)
        presentation = Presentation(str(package))
        slide = list(presentation.slides)[0]
        media = next(
            node for node in slide._element.iter()
            if isinstance(node.tag, str) and etree.QName(node).localname == "cMediaNode"
        )
        target = media if on == "media" else media.find("{%s}cTn" % P)
        for key, value in attrs.items():
            target.set(key, value)
        presentation.save(str(package))
        return _read(package)

    def test_a_muted_clip_is_preserved_rather_than_imported_unmuted(self, media_dir):
        motion = self._with_media_attr(media_dir, on="media", name="muted.pptx", mute="1")
        assert motion.animations is None, "an unrepresentable setting must not import"
        assert motion.raw_timing is not None
        assert b'mute="1"' in motion.raw_timing.xml

    def test_a_lowered_volume_is_preserved(self, media_dir):
        motion = self._with_media_attr(media_dir, on="media", name="vol.pptx", vol="40000")
        assert motion.animations is None
        assert b'vol="40000"' in motion.raw_timing.xml

    def test_a_trimmed_or_restarted_clip_is_preserved(self, media_dir):
        motion = self._with_media_attr(
            media_dir, on="ctn", name="trim.pptx", dur="4000", restart="always",
        )
        assert motion.animations is None
        assert b'dur="4000"' in motion.raw_timing.xml

    def test_an_autoplay_start_condition_is_preserved(self, media_dir):
        package = _package(media_dir, _video_slide(), name="autoplay.pptx")
        presentation = Presentation(str(package))
        slide = list(presentation.slides)[0]
        for cond in slide._element.iter("{%s}cond" % P):
            if cond.get("delay") == MEDIA_START_DELAY:
                cond.set("delay", "0")
        presentation.save(str(package))

        motion = _read(package)
        assert motion.animations is None, "autoplay has no slide JSON field today"
        assert motion.raw_timing is not None
        assert b'delay="0"' in motion.raw_timing.xml


def _inject_transition_sound(path):
    """Attach a catalogued transition that also plays an embedded sound.

    The effect itself is readable; only ``p:sndAc`` is not writable, which is
    what sends the whole transition raw.
    """
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    from pptx.opc.package import Part
    from pptx.opc.packuri import PackURI

    presentation = Presentation(str(path))
    slide = list(presentation.slides)[0]
    rid = slide.part.relate_to(
        Part(PackURI("/ppt/media/audio1.wav"), "audio/wav", slide.part.package, WAV), RT.AUDIO,
    )
    for node in slide._element.findall("{%s}transition" % P):
        slide._element.remove(node)
    slide._element.insert(
        len(slide._element) - len(slide._element.findall("{%s}timing" % P)),
        etree.fromstring(
            '<p:transition xmlns:p="%s" xmlns:r="%s" spd="fast"><p:fade/>'
            '<p:sndAc><p:stSnd loop="0"><p:snd r:embed="%s" name="alarm.wav"/>'
            "</p:stSnd></p:sndAc></p:transition>" % (P, R, rid)
        ),
    )
    presentation.save(str(path))
    return path


def _inject_unreadable_transition(path):
    presentation = Presentation(str(path))
    slide = list(presentation.slides)[0]
    for node in slide._element.findall("{%s}transition" % P):
        slide._element.remove(node)
    slide._element.insert(
        len(slide._element) - len(slide._element.findall("{%s}timing" % P)),
        etree.fromstring(UNREADABLE_TRANSITION),
    )
    presentation.save(str(path))
    return path


def _import(media_dir, package):
    """Convert a package and return (slide JSON, deck root)."""
    pptx_to_json(package, media_dir / "out")
    slide = json.loads((media_dir / "out" / "slides" / "slide-001.json").read_text())
    return slide, media_dir / "out"


def _regenerate(root, slide_def, *, animations=True, transitions=False, name="regen.pptx"):
    """Rebuild one imported slide from the deck root that holds its sidecars."""
    builder = PPTXBuilder(
        TEMPLATE,
        fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"},
        default_text_color="#FFFFFF",
        base_dir=root,
        animations_enabled=animations,
        transitions_enabled=transitions,
    )
    builder.add_slide(slide_def)
    out = root / name
    builder.save(out)
    return out, builder


def _slide_root(path):
    slide = list(Presentation(str(path)).slides)[0]
    return etree.fromstring(etree.tostring(slide._element))


def _spids(root, tag="spTgt"):
    return {node.get("spid") for node in root.findall(".//{%s}%s" % (P, tag))}


class TestGenerationReplaysPreservedMotion:
    def test_an_imported_raw_slide_regenerates_with_its_motion(self, media_dir):
        slide, root = _import(media_dir, _inject_unknown_sequence(
            _package(media_dir, _video_slide())
        ))
        out, builder = _regenerate(root, slide)

        regenerated = _slide_root(out)
        assert b"futureThing" in etree.tostring(regenerated), (
            "REQ-5.5: a slide whose motion imported raw must regenerate with it, "
            "not silently without it"
        )
        assert len(regenerated.findall("{%s}timing" % P)) == 1, "one representation"
        assert builder.timing_reports[-1]["raw"] is True
        assert builder.timing_reports[-1]["timing"] is True

    def test_the_spid_is_remapped_to_this_builds_shape(self, media_dir):
        slide, root = _import(media_dir, _inject_unknown_sequence(
            _package(media_dir, _video_slide())
        ))
        manifest = load_raw_manifest(root / MANIFEST_PATH)
        source_spid, logical = next(iter(manifest["sidecars"][0]["shapeMappings"].items()))

        # An extra element in front shifts every generated shape id, so a
        # replayed spid that is still the source one would be a stale target.
        slide["elements"].insert(0, {
            "type": "shape", "shape": "rect", "x": 0, "y": 0, "width": 40, "height": 40,
        })
        out, builder = _regenerate(root, slide)

        registry = next(iter(builder.identity_registries.values()))
        expected = str(registry.resolve(logical))
        assert expected in _spids(_slide_root(out))
        assert expected != source_spid, "the fixture must actually shift the ids"
        assert source_spid not in _spids(_slide_root(out))

    def test_the_relationship_part_is_recopied_and_the_rid_remapped(self, media_dir):
        slide, root = _import(media_dir, _inject_sound(
            _package(media_dir, _video_slide(), name="sound.pptx")
        ))
        out, _builder = _regenerate(root, slide)

        regenerated = list(Presentation(str(out)).slides)[0]
        sounds = regenerated._element.findall(".//{%s}snd" % P)
        assert len(sounds) == 1
        rid = sounds[0].get("{%s}embed" % R)
        relationship = regenerated.part.rels[rid]
        assert relationship.reltype.endswith("/audio")
        assert relationship.target_part.blob == WAV, "the manifest-declared part was copied"

    def test_a_transition_sound_imports_and_regenerates_with_its_audio(self, media_dir):
        """A transition sound must not import into a deck that cannot be built.

        The writer creates neither the audio part nor its relationship, so
        ``build_transition`` refuses a semantic ``transition.sound``. Reading one
        into the semantic contract therefore produced a deck that imported
        cleanly and failed every later generate. The transition goes raw instead,
        which carries the audio part and replays it.
        """
        slide, root = _import(media_dir, _inject_transition_sound(
            _package(media_dir, _video_slide(), name="tsound.pptx")
        ))
        assert slide.get("transition") is None, "a sound must not import semantically"
        assert "sndAc" in slide["_rawTransition"]["reason"] or "sound" in (
            slide["_rawTransition"]["reason"]
        )

        out, builder = _regenerate(root, slide, transitions=True, name="tsound-regen.pptx")

        regenerated = list(Presentation(str(out)).slides)[0]
        transitions = regenerated._element.findall("{%s}transition" % P)
        assert len(transitions) == 1, "one transition, replayed from the raw fragment"
        sounds = regenerated._element.findall(".//{%s}snd" % P)
        assert len(sounds) == 1, "the sound survived the round trip"
        relationship = regenerated.part.rels[sounds[0].get("{%s}embed" % R)]
        assert relationship.reltype.endswith("/audio")
        assert relationship.target_part.blob == WAV
        assert builder.transition_reports[-1]["raw"] is True

    def test_a_bundle_relative_reference_replays_binary_parts_without_copying(self, tmp_path):
        """Activation redirects `manifest` into the bundle instead of copying.

        `run_python`, which activates an import, writes text only, so an audio or
        video part a preserved fragment depends on can never reach the active
        deck by copying — the closure validates whole, so such a deck could not
        be built locally at all. The build derives the closure root from the
        reference's `manifest` path, so pointing that one field at the read-only
        bundle resolves the sidecars and every binary part where they already
        are. This is the behaviour `import-pptx.md` Step 4-1 tells an agent to
        rely on.
        """
        work = tmp_path / "work"
        work.mkdir()
        (work / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 128)
        slide, imported = _import(work, _inject_sound(
            _package(work, _video_slide(), name="sound.pptx")
        ))
        assert load_raw_manifest(imported / MANIFEST_PATH)["parts"], (
            "the fixture must depend on a binary part for this to mean anything"
        )

        deck = tmp_path / "deck"
        bundle = deck / "attachments" / "imports" / "imp1" / "deck"
        bundle.parent.mkdir(parents=True)
        shutil.copytree(imported, bundle)
        (deck / "clip.mp4").write_bytes((work / "clip.mp4").read_bytes())
        # The active deck root holds no animations/ subtree of its own.
        assert not (deck / "animations").exists()

        slide["_rawTiming"]["manifest"] = "attachments/imports/imp1/deck/animations/manifest.json"
        out, _builder = _regenerate(deck, slide, name="bundle-relative.pptx")

        regenerated = list(Presentation(str(out)).slides)[0]
        sounds = regenerated._element.findall(".//{%s}snd" % P)
        assert len(sounds) == 1, "the preserved fragment replayed from the bundle"
        relationship = regenerated.part.rels[sounds[0].get("{%s}embed" % R)]
        assert relationship.target_part.blob == WAV, "the bundle's part was copied into the build"

    def test_a_missing_target_fails_before_the_package_is_written(self, media_dir):
        slide, root = _import(media_dir, _inject_unknown_sequence(
            _package(media_dir, _video_slide())
        ))
        manifest = load_raw_manifest(root / MANIFEST_PATH)
        logical = set(manifest["sidecars"][0]["shapeMappings"].values())
        slide["elements"] = [
            element for element in slide["elements"] if element.get("id") not in logical
        ]
        with pytest.raises(RawReplayError, match="not on the generated slide"):
            _regenerate(root, slide, name="never.pptx")
        assert not (root / "never.pptx").exists()

    def test_a_missing_relationship_part_fails_before_the_package_is_written(self, media_dir):
        slide, root = _import(media_dir, _inject_sound(
            _package(media_dir, _video_slide(), name="sound.pptx")
        ))
        manifest = load_raw_manifest(root / MANIFEST_PATH)
        (root / manifest["parts"][0]["path"]).unlink()
        with pytest.raises(RawManifestError, match="missing"):
            _regenerate(root, slide, name="never.pptx")
        assert not (root / "never.pptx").exists()

    def test_a_tampered_sidecar_fails_before_the_package_is_written(self, media_dir):
        slide, root = _import(media_dir, _inject_unknown_sequence(
            _package(media_dir, _video_slide())
        ))
        sidecar = root / slide["_rawTiming"]["sidecar"]
        sidecar.write_bytes(sidecar.read_bytes().replace(b"futureThing", b"futureThinG"))
        with pytest.raises(RawManifestError, match="digest mismatch"):
            _regenerate(root, slide, name="never.pptx")
        assert not (root / "never.pptx").exists()

    def test_animations_off_regenerates_the_media_timing_only(self, media_dir):
        slide, root = _import(media_dir, _inject_unknown_sequence(
            _package(media_dir, _video_slide())
        ))
        out, builder = _regenerate(root, slide, animations=False, name="off.pptx")

        regenerated = _slide_root(out)
        xml = etree.tostring(regenerated)
        assert b"futureThing" not in xml, "the object-animation branch is suppressed"
        locals_ = [etree.QName(node).localname for node in regenerated.iter()
                   if isinstance(node.tag, str)]
        assert "video" in locals_, "REQ-1.4: media playback timing survives"
        assert builder.timing_reports[-1]["animationsEnabled"] is False

    def test_animations_off_fails_when_the_boundary_is_unclassifiable(self, media_dir):
        slide, root = _import(media_dir, _inject_unknown_sequence(
            _package(media_dir, _video_slide()), nest_media=True,
        ))
        with pytest.raises(RawReplayError, match="cannot separate"):
            _regenerate(root, slide, animations=False, name="never.pptx")
        assert not (root / "never.pptx").exists()

    def test_a_raw_transition_is_replayed_only_when_transitions_are_enabled(self, media_dir):
        slide, root = _import(media_dir, _inject_unreadable_transition(
            _package(media_dir, _video_slide(), name="trans.pptx")
        ))
        assert "_rawTransition" in slide

        on, _builder = _regenerate(root, slide, transitions=True, name="trans-on.pptx")
        assert b"futureEffect" in etree.tostring(_slide_root(on))

        order = [etree.QName(child).localname for child in _slide_root(on)]
        assert order.index("AlternateContent") < order.index("timing"), (
            "p:sld child order: a transition precedes timing"
        )

        off, builder = _regenerate(root, slide, transitions=False, name="trans-off.pptx")
        off_root = _slide_root(off)
        assert b"futureEffect" not in etree.tostring(off_root)
        assert not off_root.findall("{%s}transition" % P)
        assert builder.transition_reports[-1] == {"transition": False, "raw": True, "removed": 0}

    def test_a_slide_carrying_both_representations_is_refused(self, media_dir):
        """REQ-5.6: raw and semantic are mutually exclusive. Preferring one
        would drop the other without saying so, so the build stops."""
        slide, root = _import(media_dir, _inject_unknown_sequence(
            _package(media_dir, _video_slide())
        ))
        conflicted = dict(slide)
        conflicted["animations"] = {"mainSequence": []}
        with pytest.raises(Exception, match="REQ-5.6"):
            _regenerate(root, conflicted, name="never.pptx")

        conflicted = dict(slide)
        conflicted.pop("animations", None)
        conflicted["_rawTransition"] = slide["_rawTiming"]
        conflicted["transition"] = {"effect": "fade", "parameters": {}}
        with pytest.raises(Exception, match="REQ-5.6"):
            _regenerate(root, conflicted, transitions=True, name="never.pptx")
        assert not (root / "never.pptx").exists()

    def test_the_facade_replays_raw_motion_and_honours_the_override(self, media_dir):
        """End to end through sdpm.api.generate: the deck-level switch the
        import derived turns the replay on, and the caller override turns it
        off without touching the deck."""
        from sdpm.api import generate

        slide, root = _import(media_dir, _inject_unknown_sequence(
            _package(media_dir, _video_slide())
        ))
        (root / "template.pptx").write_bytes(TEMPLATE.read_bytes())
        deck = json.loads((root / "deck.json").read_text())
        assert deck["animations"] == {"enabled": True}, "the import derived the switch"
        deck["template"] = "template.pptx"
        (root / "deck.json").write_text(json.dumps(deck))
        (root / "specs").mkdir(exist_ok=True)
        (root / "specs" / "outline.md").write_text("- [slide-001] imported\n")

        inherited = root / "inherited.pptx"
        generate(root, output_path=inherited)
        assert b"futureThing" in etree.tostring(_slide_root(inherited))

        suppressed = root / "suppressed.pptx"
        generate(root, output_path=suppressed, animation_mode="off")
        assert b"futureThing" not in etree.tostring(_slide_root(suppressed))


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
