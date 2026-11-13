# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Remote materialization of preserved motion, and the remote mode contract.

The remote server builds in a bounded tmpdir, so everything a slide's
preserved timing depends on has to be fetched *before* the engine runs. The
hashed dependency manifest is the only complete statement of that closure:
scanning slide JSON for path-shaped strings finds the sidecar at best and
never the media parts it names (REQ-5.5). These tests pin the closure, the
refusal of a manifest that does not validate, and the mode pass-through
(REQ-1.3, REQ-9.5).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tools import generate as generate_mod

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "sdpm" / "templates" / "blank-dark.pptx"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
AUDIO_REL = f"{R}/audio"

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
SIDECAR = (
    '<p:timing xmlns:p="%s" xmlns:r="%s"><p:tnLst><p:par>'
    '<p:cTn id="1" nodeType="tmRoot"><p:childTnLst><p:seq><p:cTn id="2" futureThing="7">'
    '<p:tgtEl><p:spTgt spid="7"/></p:tgtEl><p:snd r:embed="rId9"/>'
    "</p:cTn></p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>"
) % (P, R)
SIDECAR_BYTES = SIDECAR.encode()
MEDIA_PART = "animations/media/slide-001-rId9-alarm.wav"
SIDECAR_PATH = "animations/slide-001-timing.xml"
MANIFEST_PATH = "animations/manifest.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(**patch) -> dict:
    manifest = {
        "version": 1,
        "provenance": {"sourceFile": "deck.pptx"},
        "sidecars": [{
            "slide": "slide-001",
            "kind": "timing",
            "path": SIDECAR_PATH,
            "sha256": _sha(SIDECAR_BYTES),
            "contentType": "application/xml",
            "namespaces": {"p": P},
            "branches": [],
            "shapeMappings": {"7": "hero"},
            "relationships": [{
                "rId": "rId9",
                "relationshipType": AUDIO_REL,
                "targetMode": "Internal",
                "contentType": "audio/wav",
                "part": MEDIA_PART,
                "sha256": _sha(WAV),
                "sourcePart": "/ppt/media/audio1.wav",
            }],
            "mediaBoundary": "classified",
            "mediaOnlyPath": None,
            "mediaOnlySha256": None,
            "reasons": ["unsupported attribute"],
        }],
        "parts": [{
            "path": MEDIA_PART,
            "sha256": _sha(WAV),
            "size": len(WAV),
            "contentType": "audio/wav",
            "relationshipType": AUDIO_REL,
            "sourcePart": "/ppt/media/audio1.wav",
        }],
        "assets": [],
    }
    manifest.update(patch)
    return manifest


def _slide(*, raw=True) -> dict:
    slide: dict = {
        "layout": "blank",
        "elements": [
            {"id": "hero", "type": "textbox", "text": "Hello", "x": 100, "y": 100,
             "width": 600, "height": 80, "fontSize": 32},
        ],
    }
    if raw:
        slide["_rawTiming"] = {
            "sidecar": SIDECAR_PATH,
            "sha256": _sha(SIDECAR_BYTES),
            "manifest": MANIFEST_PATH,
            "reason": "unsupported attribute",
        }
    return slide


@pytest.fixture
def storage():
    """Storage mock serving a one-slide deck plus an object store."""
    objects: dict[str, bytes] = {}
    store = MagicMock()
    store.pptx_bucket = "pptx-bucket"
    store.objects = objects
    store.get_deck.return_value = {"deckId": "d1", "name": "Test"}
    store.get_deck_json.return_value = {
        "template": "", "fonts": {"fullwidth": "", "halfwidth": ""},
        "animations": {"enabled": True},
    }
    store.get_user_template_metadata.return_value = None
    store.list_user_templates.return_value = []
    store.list_templates.return_value = []

    def list_files(prefix: str, bucket: str = ""):
        if prefix.endswith("/slides/"):
            return ["decks/d1/slides/intro.json"]
        return []

    store.list_files.side_effect = list_files

    def download(key: str):
        if key in objects:
            return objects[key]
        raise FileNotFoundError(key)

    store.download_file_from_pptx_bucket.side_effect = download
    store.download_file.side_effect = lambda key: (
        TEMPLATE.read_bytes() if key == "templates/blank-dark.pptx"
        else (_ for _ in ()).throw(FileNotFoundError(key))
    )
    return store


def _publish(storage, *, slide=None, manifest=None, extra=None):
    """Fill the mock object store with one deck."""
    storage.objects.clear()
    storage.objects["decks/d1/specs/outline.md"] = b"- [intro] Opening slide\n"
    storage.objects["decks/d1/slides/intro.json"] = json.dumps(
        slide if slide is not None else _slide()
    ).encode()
    if manifest is not None:
        storage.objects[f"decks/d1/{MANIFEST_PATH}"] = json.dumps(manifest).encode()
        storage.objects[f"decks/d1/{SIDECAR_PATH}"] = SIDECAR_BYTES
        storage.objects[f"decks/d1/{MEDIA_PART}"] = WAV
    for key, value in (extra or {}).items():
        storage.objects[key] = value
    return storage


# --- the dependency closure ------------------------------------------------


class TestManifestClosureMaterialization:
    def test_every_declared_sidecar_and_part_lands_in_the_workspace(self, storage):
        _publish(storage, manifest=_manifest())
        tmpdir, slides, _kwargs = generate_mod._prepare_workspace("d1", "u1", storage)

        assert (tmpdir / SIDECAR_PATH).read_bytes() == SIDECAR_BYTES
        assert (tmpdir / MANIFEST_PATH).is_file()
        assert (tmpdir / MEDIA_PART).read_bytes() == WAV, (
            "the media part is named only by the manifest — a slide-JSON string "
            "scan can never find it"
        )
        assert slides[0]["_rawTiming"]["sidecar"] == SIDECAR_PATH

    def test_the_manifest_is_read_even_without_a_raw_reference(self, storage):
        """A deck may carry only semantic sound assets, which the manifest
        declares under ``assets`` with no slide reference at all."""
        asset = _manifest(sidecars=[], parts=[], assets=[{
            "path": "media/chime.wav", "sha256": _sha(WAV), "size": len(WAV),
            "contentType": "audio/wav", "relationshipType": AUDIO_REL,
            "sourcePart": "/ppt/media/audio1.wav",
        }])
        _publish(storage, slide=_slide(raw=False), extra={
            f"decks/d1/{MANIFEST_PATH}": json.dumps(asset).encode(),
            "decks/d1/media/chime.wav": WAV,
        })
        tmpdir, _slides, _kwargs = generate_mod._prepare_workspace("d1", "u1", storage)
        assert (tmpdir / "media" / "chime.wav").read_bytes() == WAV

    def test_a_deck_without_preserved_motion_needs_no_manifest(self, storage):
        _publish(storage, slide=_slide(raw=False))
        tmpdir, slides, _kwargs = generate_mod._prepare_workspace("d1", "u1", storage)
        assert not (tmpdir / MANIFEST_PATH).exists()
        assert slides and "_rawTiming" not in slides[0]

    def test_a_referenced_manifest_missing_from_storage_fails(self, storage):
        _publish(storage)  # slide references the manifest; nothing published
        with pytest.raises(ValueError, match="not in storage"):
            generate_mod._prepare_workspace("d1", "u1", storage)

    def test_a_manifest_naming_a_path_outside_the_workspace_fails(self, storage):
        escaping = _manifest()
        escaping["parts"][0]["path"] = "../../etc/passwd"
        _publish(storage, manifest=escaping)
        with pytest.raises(ValueError, match="relative to the bundle root|invalid"):
            generate_mod._prepare_workspace("d1", "u1", storage)

    def test_a_relationship_type_outside_the_allowlist_fails(self, storage):
        hostile = _manifest()
        ole = f"{R}/oleObject"
        hostile["parts"][0]["relationshipType"] = ole
        hostile["sidecars"][0]["relationships"][0]["relationshipType"] = ole
        _publish(storage, manifest=hostile)
        with pytest.raises(ValueError, match="invalid"):
            generate_mod._prepare_workspace("d1", "u1", storage)

    def test_an_external_relationship_fails(self, storage):
        external = _manifest()
        external["sidecars"][0]["relationships"][0]["targetMode"] = "External"
        _publish(storage, manifest=external)
        with pytest.raises(ValueError, match="invalid"):
            generate_mod._prepare_workspace("d1", "u1", storage)

    def test_an_undeclared_part_fails(self, storage):
        undeclared = _manifest()
        undeclared["parts"] = []
        _publish(storage, manifest=undeclared)
        with pytest.raises(ValueError, match="invalid"):
            generate_mod._prepare_workspace("d1", "u1", storage)

    def test_a_digest_mismatch_after_materialization_fails(self, storage):
        _publish(storage, manifest=_manifest())
        storage.objects[f"decks/d1/{MEDIA_PART}"] = WAV + b"tampered"
        with pytest.raises(ValueError, match="did not materialize intact"):
            generate_mod._prepare_workspace("d1", "u1", storage)

    def test_a_manifest_reference_pointing_somewhere_else_is_refused(self, storage):
        slide = _slide()
        slide["_rawTiming"]["manifest"] = "animations/other.json"
        _publish(storage, slide=slide, manifest=_manifest())
        with pytest.raises(ValueError, match="must end with"):
            generate_mod._prepare_workspace("d1", "u1", storage)


# --- the remote mode contract ----------------------------------------------


class TestRemoteModes:
    @pytest.fixture
    def recorded(self, monkeypatch):
        """Replace the engine facade with a recorder that writes a package."""
        import sdpm.api

        calls: list[dict] = []

        def fake_generate(json_path, output_path=None, only_slugs=None,
                          animation_mode="inherit", transition_mode="inherit"):
            calls.append({"animation_mode": animation_mode, "transition_mode": transition_mode})
            Path(output_path).write_bytes(TEMPLATE.read_bytes())
            return {"slide_count": 1, "slides": ["page01 - Hello"], "warnings": []}

        monkeypatch.setattr(sdpm.api, "generate", fake_generate)
        import server_utils
        monkeypatch.setattr(server_utils, "schedule_webp_background", MagicMock())
        return calls

    @pytest.mark.parametrize("animation_mode", ["inherit", "on", "off"])
    @pytest.mark.parametrize("transition_mode", ["inherit", "on", "off"])
    def test_both_modes_reach_the_shared_engine(
        self, storage, recorded, animation_mode, transition_mode,
    ):
        _publish(storage, slide=_slide(raw=False))
        result = generate_mod.generate_pptx(
            deck_id="d1", user_id="u1", storage=storage,
            animation_mode=animation_mode, transition_mode=transition_mode,
        )
        assert result["status"] == "completed"
        assert recorded == [{"animation_mode": animation_mode, "transition_mode": transition_mode}]

    def test_the_default_is_inherit_on_both(self, storage, recorded):
        _publish(storage, slide=_slide(raw=False))
        generate_mod.generate_pptx(deck_id="d1", user_id="u1", storage=storage)
        assert recorded == [{"animation_mode": "inherit", "transition_mode": "inherit"}]

    @pytest.mark.parametrize("argument", ["animation_mode", "transition_mode"])
    def test_an_invalid_mode_fails_before_the_deck_is_downloaded(self, storage, argument):
        _publish(storage, slide=_slide(raw=False))
        with pytest.raises(ValueError) as error:
            generate_mod.generate_pptx(
                deck_id="d1", user_id="u1", storage=storage, **{argument: "sideways"},
            )
        assert argument in str(error.value)
        for accepted in ("inherit", "on", "off"):
            assert accepted in str(error.value)
        storage.download_file_from_pptx_bucket.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
