# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Raw timing/transition sidecars, their dependency manifest, and replay.

When :mod:`sdpm.engine.timing.reader` cannot understand every playback-affecting
part of a slide's timing or transition, the whole tree is preserved here instead
of being partially decoded. Three things have to be true for that to be
lossless rather than merely stored:

1. **Completeness.** The sidecar keeps the original XML of the *container* —
   every retained ``mc:Choice`` and ``mc:Fallback`` branch, not just the branch
   this version of sdpm would have selected — plus the namespace declarations
   that were in scope.
2. **Remappability.** Shape references (``p:spTgt/@spid`` and the build-list
   spids) are recorded as source-spid → logical-element-ID pairs, and every
   package relationship the fragment names is recorded with its copied part.
   On regeneration both are rewritten to the newly generated IDs; a shape or
   relationship that cannot be resolved is an explicit failure, never a stale
   ``spid`` or a dangling ``rId`` (REQ-5.5, REQ-5.7, REQ-6.4).
3. **Closure.** ``animations/manifest.json`` lists every sidecar and every
   copied part with its relationship type, content type, relative path and
   SHA-256. Local import retains that closure inside the immutable bundle;
   remote materialisation validates the manifest and fetches every listed part
   before generation. :func:`validate_raw_manifest` and
   :func:`manifest_dependency_closure` are the API that second caller uses —
   the remote wiring itself is Task 6.

Everything here is path-checked. A manifest entry has to be a relative path
that normalises *beneath* the bundle root, and an external
(``TargetMode="External"``) relationship is rejected outright rather than
fetched during generation.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from lxml import etree

from sdpm.engine.timing.reader import (
    REL_ATTRS,
    SPID_OWNERS,
    AssetRef,
    RawFragment,
    enforce_xml_limits,
)

#: Bumped whenever the sidecar/manifest layout changes incompatibly.
RAW_MANIFEST_VERSION = 1

#: Everything a raw import writes lives under this one deck-relative directory,
#: so the dependency closure is a single subtree the bundle can retain whole.
RAW_DIR = "animations"
MANIFEST_PATH = f"{RAW_DIR}/manifest.json"
MEDIA_DIR = f"{RAW_DIR}/media"

#: Deck-relative directory for *semantic* sound/media assets. Slide JSON
#: references these paths directly (``media/slide-001-audio1.wav``), which is
#: what lets activation rebase them like any other imported asset.
ASSET_DIR = "media"

#: Package relationship types sdpm will copy for a raw fragment. Anything else
#: is an unsupported-preservation error rather than a part copied on trust.
ALLOWED_RELATIONSHIP_TYPES = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/audio",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/video",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
        "http://schemas.microsoft.com/office/2007/relationships/media",
    }
)

#: Content-type families a copied part may belong to.
ALLOWED_CONTENT_FAMILIES = frozenset({"audio", "video", "image"})

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LOGICAL_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")


class RawManifestError(ValueError):
    """Raised when a sidecar dependency manifest is invalid or incomplete."""

    code = "RAW_MANIFEST_INVALID"


class RawReplayError(ValueError):
    """Raised when raw content cannot be replayed without data loss."""

    code = "RAW_REPLAY_UNMAPPABLE"


def sha256_hex(data: bytes) -> str:
    """Return the lowercase SHA-256 hex digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def safe_bundle_path(value: object, *, what: str) -> str:
    """Return a validated bundle-relative POSIX path.

    Absolute paths, Windows separators, ``..`` segments and empty segments are
    all rejected, so a manifest can never name a file outside the
    import/output root (REQ-5.3, security boundary).
    """
    if not isinstance(value, str) or not value.strip():
        raise RawManifestError(f"{what} must be a non-empty relative path")
    if "\\" in value:
        raise RawManifestError(f"{what} {value!r} must use forward slashes")
    if value.startswith("/") or PurePosixPath(value).is_absolute():
        raise RawManifestError(f"{what} {value!r} must be relative to the bundle root")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise RawManifestError(f"{what} {value!r} must not contain '.', '..' or empty segments")
    normalised = posixpath.normpath(value)
    if normalised != value:
        raise RawManifestError(f"{what} {value!r} is not normalised ({normalised!r})")
    return value


def resolve_within(root: Path, relative: str, *, what: str) -> Path:
    """Return ``root/relative`` after proving it stays beneath ``root``."""
    safe_bundle_path(relative, what=what)
    root_resolved = Path(root).resolve()
    candidate = (root_resolved / relative).resolve()
    if root_resolved not in candidate.parents:
        raise RawManifestError(f"{what} {relative!r} escapes the bundle root {root_resolved}")
    return candidate


def check_relationship(relationship_type: object, content_type: object, *, what: str) -> None:
    """Validate one copied relationship against both allowlists."""
    if relationship_type not in ALLOWED_RELATIONSHIP_TYPES:
        raise RawManifestError(
            f"{what} relationship type {relationship_type!r} is not one sdpm copies; allowed: "
            f"{sorted(ALLOWED_RELATIONSHIP_TYPES)}"
        )
    family = str(content_type).split("/", 1)[0].lower()
    if family not in ALLOWED_CONTENT_FAMILIES:
        raise RawManifestError(
            f"{what} content type {content_type!r} is not in the allowed families "
            f"{sorted(ALLOWED_CONTENT_FAMILIES)}"
        )


# ---------------------------------------------------------------------------
# Sidecar writing
# ---------------------------------------------------------------------------
def _part_name(slide_slug: str, rid: str, reference: Any) -> str:
    base = (reference.source_part or reference.target_ref).rsplit("/", 1)[-1]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-") or "part"
    return f"{MEDIA_DIR}/{slide_slug}-{rid}-{safe}"


@dataclass
class RawSidecarWriter:
    """Writes raw sidecars, copied parts and the dependency manifest.

    One writer covers one converted deck. ``root`` is the deck directory the
    converter is filling in, so every recorded path is deck-relative and the
    whole ``animations/`` subtree can be moved into the immutable bundle as a
    unit.
    """

    root: Path
    provenance: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.provenance = dict(self.provenance or {})
        self._sidecars: list[dict[str, Any]] = []
        self._parts: dict[str, dict[str, Any]] = {}
        self._assets: dict[str, dict[str, Any]] = {}

    # -- writing ------------------------------------------------------
    def _write(self, relative: str, data: bytes) -> str:
        target = resolve_within(self.root, relative, what="sidecar path")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return sha256_hex(data)

    def add_fragment(self, slide_slug: str, fragment: RawFragment) -> dict[str, Any]:
        """Persist one raw fragment and return the small slide-JSON reference."""
        path = f"{RAW_DIR}/{slide_slug}-{fragment.kind}.xml"
        digest = self._write(path, fragment.xml)
        media_path: str | None = None
        media_digest: str | None = None
        if fragment.media_only is not None:
            media_path = f"{RAW_DIR}/{slide_slug}-{fragment.kind}-media.xml"
            media_digest = self._write(media_path, fragment.media_only)

        relationships: list[dict[str, Any]] = []
        for reference in fragment.relationships:
            what = f"slide {slide_slug!r} raw {fragment.kind} relationship {reference.rid}"
            check_relationship(reference.relationship_type, reference.content_type, what=what)
            part_path = _part_name(slide_slug, reference.rid, reference)
            part_digest = self._write(part_path, reference.blob)
            self._parts[part_path] = {
                "path": part_path,
                "sha256": part_digest,
                "size": len(reference.blob),
                "contentType": reference.content_type,
                "relationshipType": reference.relationship_type,
                "sourcePart": reference.source_part,
            }
            relationships.append(
                {
                    "rId": reference.rid,
                    "relationshipType": reference.relationship_type,
                    "targetMode": reference.target_mode,
                    "contentType": reference.content_type,
                    "part": part_path,
                    "sha256": part_digest,
                    "sourcePart": reference.source_part,
                }
            )

        record: dict[str, Any] = {
            "slide": slide_slug,
            "kind": fragment.kind,
            "path": path,
            "sha256": digest,
            "contentType": "application/xml",
            "namespaces": dict(fragment.namespaces),
            "branches": [
                {
                    "kind": branch.kind,
                    "requires": branch.requires,
                    "satisfied": branch.satisfied,
                    "payload": list(branch.payload),
                }
                for branch in fragment.branches
            ],
            "shapeMappings": dict(fragment.shape_mappings),
            "relationships": relationships,
            "mediaBoundary": fragment.media_boundary,
            "mediaOnlyPath": media_path,
            "mediaOnlySha256": media_digest,
            "reasons": list(fragment.reasons),
        }
        self._sidecars.append(record)
        return {
            "sidecar": path,
            "sha256": digest,
            "manifest": MANIFEST_PATH,
            "reason": fragment.reasons[0] if fragment.reasons else "",
        }

    def add_asset(self, asset: AssetRef) -> str:
        """Copy one semantic sound/media asset and return its deck path."""
        what = f"semantic asset {asset.path!r}"
        check_relationship(asset.relationship_type, asset.content_type, what=what)
        digest = self._write(asset.path, asset.blob)
        self._assets[asset.path] = {
            "path": asset.path,
            "sha256": digest,
            "size": len(asset.blob),
            "contentType": asset.content_type,
            "relationshipType": asset.relationship_type,
            "sourcePart": asset.source_part,
        }
        return asset.path

    @property
    def empty(self) -> bool:
        """True when nothing raw or asset-bearing was imported."""
        return not (self._sidecars or self._parts or self._assets)

    def manifest(self) -> dict[str, Any]:
        """Return the hashed dependency manifest for everything written."""
        return {
            "version": RAW_MANIFEST_VERSION,
            "provenance": dict(self.provenance),
            "sidecars": list(self._sidecars),
            "parts": [self._parts[key] for key in sorted(self._parts)],
            "assets": [self._assets[key] for key in sorted(self._assets)],
        }

    def write_manifest(self) -> dict[str, Any] | None:
        """Write ``animations/manifest.json`` unless nothing was preserved."""
        if self.empty:
            return None
        manifest = self.manifest()
        payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
        target = resolve_within(self.root, MANIFEST_PATH, what="manifest path")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
        return manifest


# ---------------------------------------------------------------------------
# Manifest validation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RawPart:
    """One file in the sidecar dependency closure."""

    path: str
    sha256: str
    content_type: str
    kind: str  # "sidecar" | "mediaOnly" | "part" | "asset"
    relationship_type: str = ""


def _require_digest(value: object, *, what: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise RawManifestError(f"{what} must carry a lowercase SHA-256 hex digest, got {value!r}")
    return value


def load_raw_manifest(path: str | Path) -> dict[str, Any]:
    """Load one ``animations/manifest.json`` without validating its closure."""
    manifest_path = Path(path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RawManifestError(f"cannot load raw manifest {manifest_path}: {error}") from error
    if not isinstance(data, Mapping):
        raise RawManifestError("raw manifest root must be an object")
    return dict(data)


def validate_raw_manifest(
    manifest: Mapping[str, Any],
    *,
    root: str | Path | None = None,
    verify_hashes: bool = True,
) -> tuple[RawPart, ...]:
    """Validate a sidecar manifest and return its complete dependency closure.

    With ``root`` the files themselves are checked: every declared path has to
    exist beneath the root and match its recorded digest, which is what lets
    the remote side prove it materialised the whole closure before generation
    instead of scanning slide JSON strings for references.
    """
    if manifest.get("version") != RAW_MANIFEST_VERSION:
        raise RawManifestError(
            f"raw manifest version must be {RAW_MANIFEST_VERSION}, got {manifest.get('version')!r}"
        )
    for key in ("sidecars", "parts", "assets"):
        if not isinstance(manifest.get(key, []), list):
            raise RawManifestError(f"raw manifest {key} must be an array")
    if not isinstance(manifest.get("provenance", {}), Mapping):
        raise RawManifestError("raw manifest provenance must be an object")

    closure: list[RawPart] = []
    seen: set[str] = set()

    def add(path: str, digest: str, content_type: str, kind: str, rel_type: str = "") -> None:
        if path in seen:
            raise RawManifestError(f"raw manifest lists {path!r} twice")
        seen.add(path)
        closure.append(RawPart(path, digest, content_type, kind, rel_type))

    declared_parts: dict[str, str] = {}
    for index, part in enumerate(manifest.get("parts") or []):
        what = f"raw manifest parts[{index}]"
        if not isinstance(part, Mapping):
            raise RawManifestError(f"{what} must be an object")
        path = safe_bundle_path(part.get("path"), what=f"{what}.path")
        digest = _require_digest(part.get("sha256"), what=f"{what}.sha256")
        check_relationship(part.get("relationshipType"), part.get("contentType"), what=what)
        declared_parts[path] = digest
        add(path, digest, str(part.get("contentType")), "part", str(part.get("relationshipType")))

    for index, asset in enumerate(manifest.get("assets") or []):
        what = f"raw manifest assets[{index}]"
        if not isinstance(asset, Mapping):
            raise RawManifestError(f"{what} must be an object")
        path = safe_bundle_path(asset.get("path"), what=f"{what}.path")
        digest = _require_digest(asset.get("sha256"), what=f"{what}.sha256")
        check_relationship(asset.get("relationshipType"), asset.get("contentType"), what=what)
        add(path, digest, str(asset.get("contentType")), "asset", str(asset.get("relationshipType")))

    for index, record in enumerate(manifest.get("sidecars") or []):
        what = f"raw manifest sidecars[{index}]"
        if not isinstance(record, Mapping):
            raise RawManifestError(f"{what} must be an object")
        if record.get("kind") not in {"timing", "transition"}:
            raise RawManifestError(f"{what}.kind must be 'timing' or 'transition'")
        path = safe_bundle_path(record.get("path"), what=f"{what}.path")
        digest = _require_digest(record.get("sha256"), what=f"{what}.sha256")
        add(path, digest, "application/xml", "sidecar")
        media_path = record.get("mediaOnlyPath")
        if media_path is not None:
            add(
                safe_bundle_path(media_path, what=f"{what}.mediaOnlyPath"),
                _require_digest(record.get("mediaOnlySha256"), what=f"{what}.mediaOnlySha256"),
                "application/xml",
                "mediaOnly",
            )
        if record.get("mediaBoundary") not in {"classified", "unclassified", "notApplicable"}:
            raise RawManifestError(f"{what}.mediaBoundary {record.get('mediaBoundary')!r} is unknown")
        mappings = record.get("shapeMappings")
        if not isinstance(mappings, Mapping):
            raise RawManifestError(f"{what}.shapeMappings must be an object")
        for spid, logical in mappings.items():
            if not str(spid).isdigit():
                raise RawManifestError(f"{what}.shapeMappings key {spid!r} is not a source spid")
            if not isinstance(logical, str) or not _LOGICAL_ID_RE.fullmatch(logical):
                raise RawManifestError(
                    f"{what}.shapeMappings[{spid!r}] {logical!r} is not a logical element id"
                )
        relationships = record.get("relationships")
        if not isinstance(relationships, list):
            raise RawManifestError(f"{what}.relationships must be an array")
        for position, relationship in enumerate(relationships):
            where = f"{what}.relationships[{position}]"
            if not isinstance(relationship, Mapping):
                raise RawManifestError(f"{where} must be an object")
            if relationship.get("targetMode") != "Internal":
                raise RawManifestError(
                    f"{where} targetMode {relationship.get('targetMode')!r} is not Internal; sdpm "
                    "rejects external relationships for raw replay"
                )
            check_relationship(
                relationship.get("relationshipType"), relationship.get("contentType"), what=where
            )
            part_path = safe_bundle_path(relationship.get("part"), what=f"{where}.part")
            part_digest = _require_digest(relationship.get("sha256"), what=f"{where}.sha256")
            if declared_parts.get(part_path) != part_digest:
                raise RawManifestError(
                    f"{where} names part {part_path!r}, which the manifest's parts list does not "
                    "declare with the same digest; the dependency closure is incomplete"
                )

    if root is not None:
        for part in closure:
            target = resolve_within(Path(root), part.path, what="raw manifest path")
            if not target.is_file():
                raise RawManifestError(f"raw manifest declares {part.path!r}, which is missing")
            if verify_hashes:
                actual = sha256_hex(target.read_bytes())
                if actual != part.sha256:
                    raise RawManifestError(
                        f"raw manifest digest mismatch for {part.path!r}: expected {part.sha256}, "
                        f"found {actual}"
                    )
    return tuple(closure)


def manifest_dependency_closure(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    """Return every bundle-relative path a manifest declares, sorted.

    Remote materialisation fetches exactly this list (plus the manifest itself,
    which it already had to read) before calling the shared engine.
    """
    return tuple(sorted(part.path for part in validate_raw_manifest(manifest)))


def sidecar_record(manifest: Mapping[str, Any], sidecar_path: str) -> Mapping[str, Any]:
    """Return the manifest record that owns one sidecar path."""
    for record in manifest.get("sidecars") or []:
        if isinstance(record, Mapping) and record.get("path") == sidecar_path:
            return record
    raise RawManifestError(
        f"the raw manifest has no sidecar record for {sidecar_path!r}, so its shape and "
        "relationship mappings are unknown"
    )


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
ShapeResolver = Callable[[str], int]
RelationshipResolver = Callable[[str, str, str], str]


def remap_fragment(
    xml_bytes: bytes,
    *,
    shape_mappings: Mapping[str, str],
    relationships: Sequence[Mapping[str, Any]],
    resolve_shape: ShapeResolver,
    resolve_relationship: RelationshipResolver | None,
    what: str,
) -> etree._Element:
    """Return the fragment with every shape and relationship ID rewritten.

    ``resolve_shape`` maps a logical element ID to the ``spid`` the current
    build gave it; ``resolve_relationship`` is handed
    ``(bundle part path, relationship type, content type)`` and returns the new
    ``rId`` after creating the part. Either one failing is a
    :class:`RawReplayError` before anything is inserted — a half-remapped
    fragment is never written into a package.
    """
    enforce_xml_limits(xml_bytes, what=what)
    node = etree.fromstring(xml_bytes)

    for element in node.iter():
        if not isinstance(element.tag, str):
            continue
        spid = element.get("spid")
        if spid is None:
            continue
        local = etree.QName(element).localname
        if local not in SPID_OWNERS:
            raise RawReplayError(
                f"{what}: p:{local} carries an spid sdpm cannot remap, so replaying it would "
                "leave a stale shape reference"
            )
        logical = shape_mappings.get(spid)
        if logical is None:
            raise RawReplayError(
                f"{what}: the sidecar records no logical element for source spid {spid!r}, so the "
                "target cannot be remapped"
            )
        try:
            element.set("spid", str(resolve_shape(logical)))
        except Exception as error:  # noqa: BLE001 - surfaced as a replay failure
            raise RawReplayError(
                f"{what}: raw target {logical!r} (source spid {spid}) is not on the generated "
                f"slide: {error}"
            ) from error

    by_rid = {
        str(relationship.get("rId")): relationship
        for relationship in relationships
        if isinstance(relationship, Mapping)
    }
    rewritten: dict[str, str] = {}
    for element in node.iter():
        if not isinstance(element.tag, str):
            continue
        for attribute in REL_ATTRS:
            rid = element.get(attribute)
            if not rid:
                continue
            if rid not in rewritten:
                relationship = by_rid.get(rid)
                if relationship is None:
                    raise RawReplayError(
                        f"{what}: the sidecar records no copied part for relationship {rid!r}, so "
                        "replaying it would emit a dangling rId"
                    )
                if resolve_relationship is None:
                    raise RawReplayError(
                        f"{what}: relationship {rid!r} needs a package part, and no relationship "
                        "resolver was supplied"
                    )
                try:
                    rewritten[rid] = resolve_relationship(
                        str(relationship.get("part")),
                        str(relationship.get("relationshipType")),
                        str(relationship.get("contentType")),
                    )
                except Exception as error:  # noqa: BLE001 - surfaced as a replay failure
                    raise RawReplayError(
                        f"{what}: relationship {rid!r} could not be recreated: {error}"
                    ) from error
            element.set(attribute, rewritten[rid])
    return node


def replay_raw_fragment(
    reference: Mapping[str, Any],
    *,
    root: str | Path,
    resolve_shape: ShapeResolver,
    resolve_relationship: RelationshipResolver | None = None,
    animations_enabled: bool = True,
    manifest: Mapping[str, Any] | None = None,
) -> etree._Element | None:
    """Rebuild one preserved fragment for the slide currently being generated.

    With ``animations_enabled`` false the media-only tree recorded at import is
    replayed instead of the object-animation branches (REQ-5.4). When the
    media/object boundary could not be classified, that is a
    :class:`RawReplayError` rather than a package whose video stopped playing,
    and it happens before any output is published.

    Returns None when animations are off and the fragment carried no media.
    """
    root_path = Path(root)
    sidecar = safe_bundle_path(reference.get("sidecar"), what="raw reference sidecar")
    if manifest is None:
        manifest = load_raw_manifest(resolve_within(root_path, MANIFEST_PATH, what="manifest path"))
    validate_raw_manifest(manifest)
    record = sidecar_record(manifest, sidecar)
    kind = str(record.get("kind"))

    path = sidecar
    if not animations_enabled and kind == "timing":
        if record.get("mediaBoundary") != "classified":
            raise RawReplayError(
                f"slide {record.get('slide')!r}: raw timing mixes media and object animation in a "
                "way sdpm cannot separate, so animations-off output would change media playback; "
                "generation stops before publishing the package"
            )
        media_path = record.get("mediaOnlyPath")
        if media_path is None:
            return None
        path = safe_bundle_path(media_path, what="raw reference mediaOnlyPath")

    target = resolve_within(root_path, path, what="raw sidecar path")
    data = target.read_bytes()
    expected = reference.get("sha256") or record.get("sha256")
    if path == sidecar and expected and sha256_hex(data) != expected:
        raise RawReplayError(
            f"raw sidecar {path!r} does not match its recorded digest; the immutable bundle "
            "content changed under sdpm"
        )
    return remap_fragment(
        data,
        shape_mappings=record.get("shapeMappings") or {},
        relationships=record.get("relationships") or [],
        resolve_shape=resolve_shape,
        resolve_relationship=resolve_relationship,
        what=f"raw {kind} of slide {record.get('slide')!r}",
    )


def apply_raw_fragment(
    slide_element: etree._Element,
    reference: Mapping[str, Any],
    *,
    root: str | Path,
    resolve_shape: ShapeResolver,
    resolve_relationship: RelationshipResolver | None = None,
    animations_enabled: bool = True,
    manifest: Mapping[str, Any] | None = None,
) -> etree._Element | None:
    """Replay a preserved fragment into one slide, in ``p:sld`` child order.

    The slide's existing representation of the same feature is removed first,
    so the result is the single effective representation python-pptx issue 954
    requires.
    """
    from sdpm.engine.timing.transition import remove_transition
    from sdpm.engine.timing.writer import insert_in_schema_order, remove_timing, reparse

    node = replay_raw_fragment(
        reference,
        root=root,
        resolve_shape=resolve_shape,
        resolve_relationship=resolve_relationship,
        animations_enabled=animations_enabled,
        manifest=manifest,
    )
    if node is None:
        remove_timing(slide_element)
        return None
    tag = "transition" if _carries(node, "transition") else "timing"
    if tag == "timing":
        remove_timing(slide_element)
    else:
        remove_transition(slide_element)
    insert_in_schema_order(slide_element, reparse(node), tag)
    return node


def _carries(node: etree._Element, local_name: str) -> bool:
    if etree.QName(node).localname == local_name:
        return True
    return any(
        etree.QName(child).localname == local_name
        for child in node.iter()
        if isinstance(child.tag, str)
    )
