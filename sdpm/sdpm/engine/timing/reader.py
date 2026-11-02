# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Semantic import of ``p:timing`` and ``p:transition`` from a real package.

This is the inverse of :mod:`sdpm.engine.timing.writer` and
:mod:`sdpm.engine.timing.transition`. It turns the slide's effective timing and
transition representation into the public JSON contracts, and it refuses to
guess.

All-or-nothing classification
-----------------------------
A tree is **semantic only when every playback-affecting node, attribute,
relationship, target and extension in it is understood** (REQ-5.4). There is no
"mostly semantic plus a warning": the moment this reader meets one attribute it
cannot invert, the whole tree is handed to :mod:`sdpm.engine.timing.raw` as a
canonical raw fragment and the slide JSON keeps a small reference to it. The
recognised vocabulary is deliberately narrow and written down in one place
(:data:`SEMANTIC_VOCABULARY`), because a wide-but-lossy reader is exactly the
silent data loss the SPEC forbids.

The reader only accepts a preset whose OOXML form the capability catalog
*establishes* (``CapabilityEntry.writable``). A preset the catalog records as
capture-required would read back as semantic JSON that the writer then refuses
to generate, so PPTX → JSON → PPTX would fail on content the package actually
carried. Reading it raw instead keeps it replayable. Those presets become
semantic in Task 8, when their capture closes the catalog gap on both sides at
once.

Identity
--------
``morphId`` is recovered from ``p:cNvPr/@name`` (Microsoft's ``!!`` convention)
and the slide-local ``id`` from the GUID-keyed sdpm identity extension —
separately, as the design requires, because one shape can carry either, both or
neither. A shape with no recoverable sdpm identity gets a deterministic ID
derived from its source non-visual name plus a collision suffix.

Effect IDs come from the ``SDPM_EFFECT_EXT_URI`` extension when the package
still carries it, and otherwise from
:func:`sdpm.engine.timing.identity.effect_fingerprint` over the same
(sequence kind, logical target, normalized effect, ordinal among identical
effects) tuple the writer used, so the two sides agree without the extension.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from fractions import Fraction
from functools import lru_cache
from typing import Any, Iterable, Mapping, Sequence

from lxml import etree

from sdpm.engine.timing.identity import (
    EffectIdAllocator,
    morph_id_from_shape_name,
    read_identity_extension,
)
from sdpm.engine.timing.model import (
    MAX_TIMING_XML_DEPTH,
    MAX_TIMING_XML_ELEMENTS,
    TimingXmlLimitError,
    validate_xml_resource_limits,
)
from sdpm.engine.timing.transition import LEGACY_SPEED_MS
from sdpm.engine.timing.writer import (
    ANGLE_SCALE,
    ANIM_CALC_MODES,
    ANIM_EFFECT_TRANSITIONS,
    ANIM_VALUE_TYPES,
    BEHAVIOR_ELEMENTS,
    CMD_TYPES,
    MEASURED_DIM_SCHEME_COLOR,
    MOTION_ORIGINS,
    MOTION_PATH_EDIT_MODES,
    PERCENT_SCALE,
    SDPM_EFFECT_EXT_URI,
    TRANSITION_STRATEGIES,
    CapabilityIndex,
    load_capability_index,
    qn,
)

#: OOXML element -> ``behaviors[].type``, inverted from the writer's own table
#: so the two directions cannot drift. ``none`` writes no node, so it has no
#: element to come back from.
BEHAVIOR_TYPE_BY_TAG: dict[str, str] = {
    tag: name for name, tag in BEHAVIOR_ELEMENTS.items() if tag is not None
}

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
SDPM_NS = "https://sdpm.dev/2026/identity"

#: The structured error code every resource-limit rejection carries (REQ-5.3a).
IMPORT_LIMIT_CODE = "IMPORT_LIMIT_EXCEEDED"

#: The exact OOXML vocabulary this reader can invert. Anything outside it is
#: preserved as raw rather than dropped, so this table is the honest statement
#: of semantic import coverage.
SEMANTIC_VOCABULARY: dict[str, tuple[str, ...]] = {
    "timing.root": ("p:tnLst", "p:bldLst", "p:extLst"),
    "timing.rootCTn": ("id", "dur", "restart", "nodeType"),
    "sequence": ("p:seq[mainSeq]", "p:seq[interactiveSeq]", "p:video", "p:audio"),
    "effectCTn": (
        "id", "fill", "grpId", "nodeType", "presetClass", "presetID", "presetSubtype",
        "repeatCount", "repeatDur", "autoRev", "accel", "decel", "restart",
    ),
    "behavior": ("p:animEffect", "p:set", "p:cmd"),
    "buildList": ("p:bldP[@spid,@grpId,@animBg]",),
    "transition": ("spd", "advClick", "advTm", "p14:dur"),
    "transitionChild": ("the catalogued transition element plus p:sndAc",),
}

#: ``p:transition/@spd`` is the only legacy duration bucket PowerPoint writes
#: when the millisecond duration is the effect default.
_SPD_VALUES = frozenset(LEGACY_SPEED_MS)

_PRESET_CATEGORY = {"entr": "entrance", "exit": "exit", "emph": "emphasis",
                    "mediacall": "media", "path": "motionPath"}

_ID_START = re.compile(r"[A-Za-z]")
_ID_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

#: Relationship attributes that name a package relationship.
REL_ATTRS = (f"{{{R_NS}}}embed", f"{{{R_NS}}}link", f"{{{R_NS}}}id")


class MotionReadError(ValueError):
    """Raised when a timing/transition tree cannot be imported at all.

    This is *not* the "unknown content" path — unknown content becomes raw.
    It is reserved for input that is malformed or unsafe: a branch set with no
    usable branch structure, a shape reference that names no shape on the
    slide, or a relationship sdpm refuses to copy.
    """

    code = "IMPORT_MOTION_UNREADABLE"


class ImportLimitExceeded(MotionReadError):
    """Raised when timing/transition XML exceeds the bounded parser contract."""

    code = IMPORT_LIMIT_CODE


class MediaBoundaryError(MotionReadError):
    """Raised when media and object timing cannot be separated safely.

    REQ-5.4 requires animation-off output from a mixed raw tree to keep the
    media timing. When the two cannot be told apart, generation has to fail
    *before* the package is published rather than ship a deck whose video no
    longer plays.
    """

    code = "IMPORT_MEDIA_BOUNDARY_UNCLASSIFIED"


# ---------------------------------------------------------------------------
# Shape identity
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ShapeIdentity:
    """One slide shape's three identity surfaces."""

    spid: int
    element_id: str
    morph_id: str | None = None
    #: True when ``element_id`` came from the sdpm identity extension rather
    #: than from a deterministic derivation.
    recovered: bool = False
    name: str = ""


def _slug(value: str) -> str:
    cleaned = _ID_SAFE.sub("-", value.strip()).strip("-.")
    cleaned = cleaned.lower()
    if not cleaned or not _ID_START.match(cleaned):
        return ""
    return cleaned


def derive_element_id(name: str, spid: int, used: Iterable[str]) -> str:
    """Return a deterministic, collision-free slide-local ID for one shape.

    The base is the shape's source non-visual name, which is what a PowerPoint
    user sees in the Selection Pane; a shape whose name is unusable falls back
    to its source ``spid``. A collision appends ``-2``, ``-3``, … so an import
    is deterministic and collision-free within itself (REQ-2.3).
    """
    taken = set(used)
    base = _slug(name) or f"shape-{spid}"
    candidate = base
    ordinal = 2
    while candidate in taken:
        candidate = f"{base}-{ordinal}"
        ordinal += 1
    return candidate


def shape_identities(slide_element: etree._Element) -> dict[int, ShapeIdentity]:
    """Return every addressable shape on the slide, keyed by source ``spid``.

    Shapes are walked in document order, so the derived IDs and their collision
    suffixes are stable for one package.
    """
    identities: dict[int, ShapeIdentity] = {}
    used: set[str] = set()
    tree = slide_element.find(f"{{{P_NS}}}cSld/{{{P_NS}}}spTree")
    if tree is None:
        return identities
    for props in tree.iter(qn("p:cNvPr")):
        raw_id = props.get("id")
        if raw_id is None or not raw_id.isdigit():
            continue
        spid = int(raw_id)
        if spid in identities:
            continue
        name = props.get("name") or ""
        morph_id = morph_id_from_shape_name(name)
        owner = props.getparent()
        shape = owner.getparent() if owner is not None else None
        identity = read_identity_extension(shape) if shape is not None else {}
        element_id = identity.get("element")
        recovered = bool(element_id)
        if not recovered:
            element_id = derive_element_id(morph_id or name, spid, used)
        used.add(element_id)
        identities[spid] = ShapeIdentity(
            spid=spid,
            element_id=element_id,
            morph_id=identity.get("morph") or morph_id,
            recovered=recovered,
            name=name,
        )
    return identities


# ---------------------------------------------------------------------------
# Reverse capability index
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Reverse:
    """Catalog lookups in the import direction."""

    presets: Mapping[tuple[str, str, str], Any]
    transitions: Mapping[tuple[str, tuple[tuple[str, str], ...]], Any]
    requires: tuple[str, ...]
    #: ``(presetClass, presetID, presetSubtype) -> (entry, setting, value)`` for
    #: every ``Effect Options`` value whose subtype identifies it on its own.
    #: Without these a preset written with a non-default option would not resolve
    #: at all — Fly In's ``From Right`` is subtype 2 and no entry claims it — so
    #: this is what makes an option round-trip rather than merely import.
    preset_options: Mapping[tuple[str, str, str], tuple[Any, str, str]] = field(
        default_factory=dict
    )
    #: ``(presetClass, presetID, presetSubtype, payload) -> (entry, setting, value)``
    #: for the options no subtype identifies, matched on the behaviours instead.
    preset_option_payloads: Mapping[
        tuple[str, str, str, tuple[Any, ...]], tuple[Any, str, str]
    ] = field(default_factory=dict)


def _preference(entry: Any) -> tuple[int, int, str]:
    """Deterministic winner when several entries describe one OOXML form.

    A captured Transitions/Animations gallery tile beats an enum candidate that
    merely corroborates the same mapping, exactly as
    :func:`sdpm.engine.timing.transition.resolve_transition` prefers it when
    writing, so the two directions agree on which catalog key owns a form.
    """
    return (
        0 if "galleryTile" in entry.ooxml else 1,
        0 if entry.group == "guiItems" else 1,
        entry.key,
    )


@lru_cache(maxsize=4)
def reverse_index(index: CapabilityIndex) -> _Reverse:
    """Return (and cache) the OOXML → semantic lookups for one catalog."""
    presets: dict[tuple[str, str, str], Any] = {}
    preset_options: dict[tuple[str, str, str], tuple[Any, str, str]] = {}
    preset_option_payloads: dict[
        tuple[str, str, str, tuple[Any, ...]], tuple[Any, str, str]
    ] = {}
    transitions: dict[tuple[str, tuple[tuple[str, str], ...]], Any] = {}
    for entry in sorted(
        [*index.items.values(), *index.candidates.values()], key=_preference
    ):
        if not entry.writable:
            # Reading a capture-required mapping semantically would produce
            # JSON the writer refuses; raw fallback keeps it replayable.
            continue
        ooxml = entry.ooxml
        transition = entry.semantic.get("transition")
        if isinstance(transition, Mapping):
            if ooxml.get("strategy") not in TRANSITION_STRATEGIES:
                continue
            tag = ooxml.get("element")
            if not isinstance(tag, str):
                continue
            key = (tag, tuple(sorted(entry.attributes().items())))
            transitions.setdefault(key, entry)
            continue
        if ooxml.get("strategy") not in CapabilityIndex.PRESET_STRATEGIES:
            continue
        if ooxml.get("presetId") is None:
            continue
        preset = _semantic_preset(entry)
        if preset is None:
            continue
        preset_class = ooxml.get("presetClass")
        classes = preset_class if isinstance(preset_class, list) else [preset_class]
        for one in classes:
            if not isinstance(one, str):
                continue
            if _PRESET_CATEGORY.get(one) != preset.get("category"):
                continue
            token = (one, str(ooxml["presetId"]), str(ooxml.get("presetSubtype", 0)))
            presets.setdefault(token, entry)
            for setting, value, subtype in _option_subtypes(ooxml):
                presets.setdefault((one, str(ooxml["presetId"]), subtype), entry)
                preset_options.setdefault(
                    (one, str(ooxml["presetId"]), subtype), (entry, setting, value)
                )
            for setting, value, subtype, payload in _option_payloads(ooxml):
                preset_option_payloads.setdefault(
                    (one, str(ooxml["presetId"]), subtype, payload), (entry, setting, value)
                )
    requires = tuple(
        str(row.get("requires"))
        for row in index.alternate_content.get("supported", ())
        if row.get("requires")
    )
    return _Reverse(
        presets=presets,
        transitions=transitions,
        requires=requires,
        preset_options=preset_options,
        preset_option_payloads=preset_option_payloads,
    )


#: Attributes a payload signature leaves out, because the writer is allowed to
#: change them: ``id`` is allocated per document, and ``dur``/``delay`` scale
#: with the requested effect duration. Everything else is transcribed verbatim
#: from the capture, which is what makes the comparison exact rather than
#: approximate.
_VOLATILE_ATTRS = frozenset({"id", "dur", "delay"})


def _subtree_signature(node: Mapping[str, Any]) -> tuple[Any, ...]:
    """Signature of a measured ``{element, attributes, children}`` value subtree."""
    return (
        str(node.get("element", "")).split(":")[-1],
        tuple(
            sorted(
                (str(name), str(value))
                for name, value in (node.get("attributes") or {}).items()
                if name not in _VOLATILE_ATTRS
            )
        ),
        tuple(_subtree_signature(child) for child in node.get("children") or ()),
    )


def _catalog_payload(behaviors: Sequence[Mapping[str, Any]]) -> tuple[Any, ...]:
    """Signature of an effect's behaviours as the catalog records them.

    Local names only, without the namespace prefix, so this agrees with the
    signature taken from XML without the reader having to invert lxml's prefix
    map. Two value elements that differ only by namespace would collide, and
    none do: the point is to tell one measured value of one setting from
    another, and those differ in ``@by``, ``@filter``, ``@prLst`` or a keyframe.
    """
    return tuple(
        (
            str(behavior.get("element", "")).split(":")[-1],
            tuple(
                sorted(
                    (str(name), str(value))
                    for name, value in (behavior.get("attributes") or {}).items()
                    if name not in _VOLATILE_ATTRS
                )
            ),
            tuple(str(name) for name in behavior.get("attrNames") or ()),
            tuple(
                _subtree_signature((behavior.get("values") or {})[key])
                # The writer appends these in this order, so the XML side can
                # walk children in document order and agree.
                for key in ("to", "from", "by", "tavLst")
                if (behavior.get("values") or {}).get(key) is not None
            ),
        )
        for behavior in behaviors
    )


def _xml_subtree_signature(node: etree._Element) -> tuple[Any, ...]:
    return (
        _local(node),
        tuple(
            sorted(
                (str(name), str(value))
                for name, value in node.attrib.items()
                if name not in _VOLATILE_ATTRS
            )
        ),
        tuple(
            _xml_subtree_signature(child)
            for child in node
            if isinstance(child.tag, str)
        ),
    )


def _xml_payload(children: etree._Element) -> tuple[Any, ...]:
    """Signature of what was actually written, comparable with :func:`_catalog_payload`."""
    out: list[tuple[Any, ...]] = []
    for node in children:
        if not isinstance(node.tag, str):
            continue
        carrier = _child(node, "cBhvr")
        names: list[str] = []
        if carrier is not None:
            name_list = _child(carrier, "attrNameLst")
            if name_list is not None:
                names = [(child.text or "") for child in name_list if isinstance(child.tag, str)]
        out.append(
            (
                _local(node),
                tuple(
                    sorted(
                        (str(name), str(value))
                        for name, value in node.attrib.items()
                        if name not in _VOLATILE_ATTRS
                    )
                ),
                tuple(names),
                tuple(
                    _xml_subtree_signature(child)
                    for child in node
                    if isinstance(child.tag, str) and _local(child) != "cBhvr"
                ),
            )
        )
    return tuple(out)


def _option_payloads(
    ooxml: Mapping[str, Any],
) -> list[tuple[str, str, str, tuple[Any, ...]]]:
    """Return ``(setting, value, subtype, payload)`` for options only a payload identifies.

    9 of the 37 measured groups never move ``presetSubtype``: Spin's two
    directions are both 0 and differ in the sign of ``p:animRot/@by``,
    Grow/Shrink's amounts differ in ``p:animScale/p:by``, Transparency's in
    ``p:animEffect/@prLst``. The subtype cannot tell those apart, so the
    behaviours are compared instead — and because the writer transcribes them,
    the comparison is exact rather than a nearest match.

    The setting's **default** value is left out. Its payload is what a plain
    effect writes, so registering it would make an effect asked for without
    options read back with them, and every existing preset entry would stop
    round-tripping. A setting whose default could not be resolved is left out
    entirely for the same reason: without knowing which payload is the default
    there is no way to avoid labelling it.
    """
    options = ooxml.get("effectOptions")
    if not isinstance(options, Mapping):
        return []
    rows: list[tuple[str, str, str, tuple[Any, ...]]] = []
    for setting, option in options.items():
        default = option.get("default")
        if default is None:
            continue
        values = option.get("values") or {}
        subtypes = {measured.get("presetSubtype") for measured in values.values()}
        if len(values) < 2 or len(subtypes) > 1:
            # The subtype already identifies these, and that path is cheaper
            # and does not depend on the behaviours surviving unchanged.
            continue
        for value, measured in values.items():
            if value == default:
                continue
            behaviors = measured.get("behaviors") or []
            if not behaviors:
                continue
            rows.append(
                (
                    str(setting),
                    str(value),
                    str(measured.get("presetSubtype")),
                    _catalog_payload(behaviors),
                )
            )
    return rows


def _option_subtypes(ooxml: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """Return ``(setting, value, subtype)`` for options a subtype identifies alone.

    Three kinds are left out, each because inverting it from the subtype would
    be a guess rather than a reading:

    * the value whose subtype **is** the effect's default. The written bytes are
      the plain effect, so the reader emits no ``options`` and the JSON
      round-trips as the effect it asked for.
    * a subtype carried by more than one value of the effect. 9 of the 37
      measured groups never move the subtype — Spin's two directions are both
      subtype 0, differing only in the sign of ``p:animRot/@by`` — so the
      subtype cannot say which was asked for. These import as the plain effect
      and are one-way until the reader compares behaviours.
    * a subtype two different *settings* share, for the four effects offering
      two settings at once.
    """
    options = ooxml.get("effectOptions")
    if not isinstance(options, Mapping):
        return []
    default_subtype = ooxml.get("presetSubtype")
    seen: dict[str, int] = {}
    candidates: list[tuple[str, str, str]] = []
    for setting, option in options.items():
        for value, measured in (option.get("values") or {}).items():
            subtype = measured.get("presetSubtype")
            if subtype is None or subtype == default_subtype:
                continue
            seen[str(subtype)] = seen.get(str(subtype), 0) + 1
            candidates.append((str(setting), str(value), str(subtype)))
    return [entry for entry in candidates if seen[entry[2]] == 1]


def _semantic_preset(entry: Any) -> Mapping[str, Any] | None:
    from sdpm.engine.timing.writer import first_effect

    effect = first_effect(entry.semantic)
    preset = effect.get("preset") if isinstance(effect, Mapping) else None
    return preset if isinstance(preset, Mapping) else None


def supported_requires(index: CapabilityIndex | None = None) -> tuple[str, ...]:
    """Return the versioned ``mc:Choice/@Requires`` prefixes sdpm understands."""
    return reverse_index(index or load_capability_index()).requires


# ---------------------------------------------------------------------------
# AlternateContent selection
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Branch:
    """One retained ``mc:AlternateContent`` branch."""

    kind: str  # "Choice" | "Fallback"
    requires: str
    satisfied: bool
    payload: tuple[str, ...]


@dataclass(frozen=True)
class Selection:
    """The outcome of evaluating one representation of a slide feature."""

    node: etree._Element | None
    #: "direct" | "choice" | "fallback" | "none"
    source: str
    branches: tuple[Branch, ...] = ()
    container: etree._Element | None = None
    reason: str = ""


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _branch_payload(branch: etree._Element) -> tuple[str, ...]:
    return tuple(
        _local(child) for child in branch if isinstance(child.tag, str)
    )


def select_alternate_branch(
    container: etree._Element,
    local_name: str,
    *,
    supported: Sequence[str],
) -> Selection:
    """Pick the branch of one ``mc:AlternateContent`` sdpm should read.

    ``mc:Choice`` elements are evaluated **in document order**; the first whose
    every ``@Requires`` token is in the supported set wins. Otherwise
    ``mc:Fallback`` is used. When neither is usable the caller falls back to raw
    preservation, which is why every branch is reported back — the sidecar has
    to retain all of them (REQ-5.5), not just the one that was selected.
    """
    allowed = set(supported)
    branches: list[Branch] = []
    chosen: etree._Element | None = None
    chosen_kind = ""
    fallback: etree._Element | None = None
    seen_branch = False
    for child in container:
        if not isinstance(child.tag, str):
            continue
        kind = _local(child)
        if kind not in {"Choice", "Fallback"}:
            raise MotionReadError(
                f"mc:AlternateContent carries an unexpected child {kind!r}; "
                "ECMA-376 Part 3 allows only mc:Choice and mc:Fallback"
            )
        seen_branch = True
        payload = _branch_payload(child)
        if kind == "Choice":
            requires = child.get("Requires")
            if not requires or not requires.split():
                raise MotionReadError(
                    "mc:Choice without @Requires is malformed; sdpm will not guess "
                    "which namespace a branch needs"
                )
            tokens = requires.split()
            satisfied = all(token in allowed for token in tokens)
            branches.append(Branch("Choice", " ".join(tokens), satisfied, payload))
            if satisfied and chosen is None and local_name in payload:
                chosen, chosen_kind = child, "choice"
        else:
            branches.append(Branch("Fallback", "", True, payload))
            if fallback is None and local_name in payload:
                fallback = child
    if not seen_branch:
        raise MotionReadError("mc:AlternateContent has no mc:Choice or mc:Fallback branch")
    if chosen is None and fallback is not None:
        chosen, chosen_kind = fallback, "fallback"
    if chosen is None:
        return Selection(
            None,
            "none",
            tuple(branches),
            container,
            reason=(
                f"no mc:AlternateContent branch carries a readable p:{local_name}: "
                f"supported namespaces {sorted(allowed)}"
            ),
        )
    node = next(
        (child for child in chosen if isinstance(child.tag, str) and _local(child) == local_name),
        None,
    )
    return Selection(node, chosen_kind, tuple(branches), container)


def select_representation(
    slide_element: etree._Element,
    local_name: str,
    *,
    supported: Sequence[str],
) -> Selection:
    """Return the slide's one effective ``local_name`` representation.

    A direct child and an ``mc:AlternateContent`` wrapper carrying the same
    feature is the python-pptx issue 954 corruption, so two representations are
    a deterministic error rather than a silent choice.
    """
    found: list[Selection] = []
    for child in slide_element:
        if not isinstance(child.tag, str):
            continue
        kind = _local(child)
        if kind == local_name:
            found.append(Selection(child, "direct", container=child))
        elif kind == "AlternateContent":
            payload = {name for branch in child for name in _branch_payload(branch)}
            if local_name in payload:
                found.append(select_alternate_branch(child, local_name, supported=supported))
    if not found:
        return Selection(None, "none")
    if len(found) > 1:
        raise MotionReadError(
            f"slide carries {len(found)} p:{local_name} representations (direct and/or "
            "mc:AlternateContent); python-pptx issue 954 documents the package corruption "
            "this causes, so sdpm refuses to pick one"
        )
    return found[0]


# ---------------------------------------------------------------------------
# Bounded parsing
# ---------------------------------------------------------------------------
def enforce_xml_limits(
    xml_bytes: bytes,
    *,
    what: str,
    max_depth: int = MAX_TIMING_XML_DEPTH,
    max_elements: int = MAX_TIMING_XML_ELEMENTS,
) -> None:
    """Apply the depth/element/DTD contract and raise the structured code.

    The measurement is on the uncompressed XML and happens *before* any
    sidecar is created, exactly as REQ-5.3a requires.
    """
    try:
        validate_xml_resource_limits(xml_bytes, max_depth=max_depth, max_elements=max_elements)
    except TimingXmlLimitError as error:
        raise ImportLimitExceeded(f"{what}: {error}") from error


def canonical_xml(node: etree._Element) -> bytes:
    """Return one subtree as standalone, namespace-complete bytes."""
    return etree.tostring(node, encoding="utf-8")


def declared_namespaces(node: etree._Element) -> dict[str, str]:
    """Return every namespace in scope for a retained fragment."""
    collected: dict[str, str] = {}
    for element in node.iter():
        if not isinstance(element.tag, str):
            continue
        for prefix, uri in element.nsmap.items():
            collected[prefix or ""] = uri
    return dict(sorted(collected.items()))


# ---------------------------------------------------------------------------
# Relationships and assets
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RelationshipRef:
    """One package relationship a retained fragment depends on."""

    rid: str
    relationship_type: str
    target_mode: str
    target_ref: str
    content_type: str = ""
    blob: bytes = b""
    source_part: str = ""


@dataclass(frozen=True)
class AssetRef:
    """One semantic sound/media asset copied into the import bundle."""

    #: Deck-relative path the active slide JSON references.
    path: str
    blob: bytes
    content_type: str
    relationship_type: str
    source_part: str = ""


class RelationshipLookup:
    """Reads one slide part's relationships without trusting their targets.

    An external (``TargetMode="External"``) relationship is reported but never
    copied: REQ-5.5/REQ-5.7 and the security boundary both forbid following a
    link out of the package during import.
    """

    def __init__(self, part: Any | None = None) -> None:
        self._part = part

    def get(self, rid: str) -> RelationshipRef | None:
        part = self._part
        if part is None:
            return None
        try:
            relationship = part.rels[rid]
        except (KeyError, TypeError):
            return None
        if relationship.is_external:
            return RelationshipRef(
                rid=rid,
                relationship_type=str(relationship.reltype),
                target_mode="External",
                target_ref=str(relationship.target_ref),
            )
        target = relationship.target_part
        return RelationshipRef(
            rid=rid,
            relationship_type=str(relationship.reltype),
            target_mode="Internal",
            target_ref=str(relationship.target_ref),
            content_type=str(target.content_type),
            blob=bytes(target.blob),
            source_part=str(target.partname),
        )

    def collect(self, node: etree._Element) -> tuple[tuple[RelationshipRef, ...], tuple[str, ...]]:
        """Return every relationship a fragment names, plus unresolved rIds."""
        refs: dict[str, RelationshipRef] = {}
        missing: list[str] = []
        for element in node.iter():
            if not isinstance(element.tag, str):
                continue
            for attribute in REL_ATTRS:
                rid = element.get(attribute)
                if not rid or rid in refs or rid in missing:
                    continue
                resolved = self.get(rid)
                if resolved is None:
                    missing.append(rid)
                else:
                    refs[rid] = resolved
        return tuple(refs[rid] for rid in sorted(refs)), tuple(sorted(missing))


# ---------------------------------------------------------------------------
# Raw fragments
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RawFragment:
    """Everything the sidecar needs to replay one unrecognised tree."""

    kind: str  # "timing" | "transition"
    xml: bytes
    namespaces: Mapping[str, str]
    branches: tuple[Branch, ...] = ()
    #: source ``spid`` → logical element ID, for every schema-defined shape
    #: reference in the fragment (``p:spTgt/@spid`` and the build-list spids).
    shape_mappings: Mapping[str, str] = field(default_factory=dict)
    relationships: tuple[RelationshipRef, ...] = ()
    #: Media-only timing for animation-off output, when the boundary is safe.
    media_only: bytes | None = None
    media_boundary: str = "notApplicable"
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class SlideMotion:
    """What one slide's timing and transition became."""

    animations: dict[str, Any] | None = None
    transition: dict[str, Any] | None = None
    raw_timing: RawFragment | None = None
    raw_transition: RawFragment | None = None
    assets: tuple[AssetRef, ...] = ()
    #: source ``spid`` → logical element ID that the slide JSON must carry.
    element_ids: Mapping[int, str] = field(default_factory=dict)
    morph_ids: Mapping[int, str] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()

    @property
    def has_object_animation(self) -> bool:
        """True when the slide persists object animations in either form."""
        return self.animations is not None or self.raw_timing is not None

    @property
    def has_transition(self) -> bool:
        """True when the slide persists a transition in either form."""
        return self.transition is not None or self.raw_transition is not None


# ---------------------------------------------------------------------------
# Media / object boundary
# ---------------------------------------------------------------------------
#: Shape-reference attributes, by owning element. Everything else that carries
#: an ``spid`` is unknown to this reader and is refused rather than remapped
#: blind, so replay can never leave a stale spid behind.
SPID_OWNERS = frozenset({"spTgt", "bldP", "bldGraphic", "bldDgm", "bldOleChart"})

MEDIA_NODES = frozenset({"video", "audio"})


def time_root(timing: etree._Element) -> etree._Element | None:
    """Return the ``p:cTn[@nodeType="tmRoot"]`` of one timing tree."""
    for node in timing.iterfind(f"{{{P_NS}}}tnLst/{{{P_NS}}}par/{{{P_NS}}}cTn"):
        if node.get("nodeType") == "tmRoot":
            return node
    return None


def classify_media_boundary(
    timing: etree._Element,
) -> tuple[tuple[etree._Element, ...], tuple[etree._Element, ...]]:
    """Split a timing tree into ``(media nodes, object-animation nodes)``.

    The split is only safe when every child of the time root is either a media
    node or an object-animation sequence, and no media node is nested inside a
    sequence. Anything else raises :class:`MediaBoundaryError`, because
    suppressing object animations would then either take the media with it or
    leave an object animation running.
    """
    root = time_root(timing)
    if root is None:
        raise MediaBoundaryError(
            "timing tree has no p:cTn[@nodeType='tmRoot'], so its media and object "
            "branches cannot be told apart"
        )
    children = root.find(f"{{{P_NS}}}childTnLst")
    media: list[etree._Element] = []
    objects: list[etree._Element] = []
    for child in children if children is not None else ():
        if not isinstance(child.tag, str):
            continue
        name = _local(child)
        if name in MEDIA_NODES:
            media.append(child)
            continue
        if name != "seq":
            raise MediaBoundaryError(
                f"timing tree holds p:{name} directly under the time root; sdpm cannot "
                "classify it as media or object animation, so animation-off output would "
                "either drop media playback or keep an object animation"
            )
        nested = [
            _local(node)
            for node in child.iter()
            if isinstance(node.tag, str) and _local(node) in MEDIA_NODES
        ]
        if nested:
            raise MediaBoundaryError(
                f"an object-animation sequence contains media nodes {sorted(set(nested))}; "
                "suppressing the sequence would stop the media as well"
            )
        objects.append(child)
    return tuple(media), tuple(objects)


def media_only_timing(timing: etree._Element) -> bytes | None:
    """Return a media-only copy of a timing tree, or None when it has no media.

    Used for animation-off output from a mixed raw tree (REQ-5.4): the
    supported media timing is reconstructed and the raw object-animation
    branches are suppressed.
    """
    media, _objects = classify_media_boundary(timing)
    if not media:
        return None
    copy = etree.fromstring(canonical_xml(timing))
    root = time_root(copy)
    children = root.find(f"{{{P_NS}}}childTnLst") if root is not None else None
    if children is None:
        raise MediaBoundaryError("timing tree lost its time root while being copied")
    for child in list(children):
        if isinstance(child.tag, str) and _local(child) not in MEDIA_NODES:
            children.remove(child)
    for tag in ("bldLst", "extLst"):
        for node in copy.findall(f"{{{P_NS}}}{tag}"):
            copy.remove(node)
    return canonical_xml(copy)


# ---------------------------------------------------------------------------
# Semantic timing reader
# ---------------------------------------------------------------------------
class _Unsupported(Exception):
    """Internal: this subtree is not fully understood, so the tree goes raw."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _attrs(node: etree._Element) -> dict[str, str]:
    return {str(name): str(value) for name, value in node.attrib.items()}


def _require_attrs(node: etree._Element, allowed: Iterable[str], what: str) -> dict[str, str]:
    attrs = _attrs(node)
    extra = sorted(set(attrs) - set(allowed))
    if extra:
        raise _Unsupported(f"{what} carries unsupported attributes {extra}")
    return attrs


def _only_children(node: etree._Element, allowed: Iterable[str], what: str) -> list[etree._Element]:
    allowed = set(allowed)
    children = [child for child in node if isinstance(child.tag, str)]
    extra = sorted({_local(child) for child in children} - allowed)
    if extra:
        raise _Unsupported(f"{what} carries unsupported children {extra}")
    return children


def _child(node: etree._Element, name: str) -> etree._Element | None:
    return node.find(f"{{{P_NS}}}{name}")


def _cond_delay(cond: etree._Element, what: str) -> int:
    """Return one ``p:cond/@delay`` as milliseconds."""
    token = cond.get("delay")
    if token is None or not token.isdigit():
        raise _Unsupported(f"{what} delay {token!r} is not a millisecond value")
    return int(token)


def _int_attr(node: etree._Element, name: str, what: str) -> int:
    value = node.get(name)
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise _Unsupported(f"{what}/@{name} is not an integer: {value!r}") from None


class _TimingReader:
    """Reads one slide's ``p:timing`` into the public animation contract."""

    def __init__(
        self,
        *,
        index: CapabilityIndex,
        identities: Mapping[int, ShapeIdentity],
        slide_slug: str,
    ) -> None:
        self.index = index
        self.reverse = reverse_index(index)
        self.identities = identities
        self.slide_slug = slide_slug
        self.targets: set[int] = set()
        self._effect_ids = EffectIdAllocator()
        self._ext_ids: dict[str, str] = {}
        #: ``p:bldLst`` decoded ahead of the sequences, keyed the way the build
        #: list itself keys a build. It has to be decoded first: the writer
        #: allocates an effect ID from the JSON *including* its build fields, so
        #: an effect that learned its ``text`` afterwards would fingerprint
        #: differently and come back with the wrong ID.
        self._builds: dict[tuple[int, int], dict[str, Any]] = {}
        #: The build tokens an effect claimed. One build per spid + grpId, so
        #: the first effect on that pair takes it, exactly as the writer
        #: registers it from the first effect that asks.
        self._builds_used: set[tuple[int, int]] = set()
        self._preset_build: dict[tuple[int, int], bool] = {}
        #: The paragraph range the behaviour targets just named, if any.
        #: `p:pRg` sits inside `p:spTgt`, which is read per behaviour, while the
        #: JSON carries it once on the effect's target — so it is handed up
        #: here rather than threaded through every target read.
        self._paragraph_range: dict[str, int] | None = None

    # -- entry point ---------------------------------------------------
    def read(self, timing: etree._Element) -> dict[str, Any] | None:
        _require_attrs(timing, (), "p:timing")
        _only_children(timing, {"tnLst", "bldLst", "extLst"}, "p:timing")
        self._read_extension(timing)
        self._decode_build_list(timing)
        root = time_root(timing)
        if root is None:
            raise _Unsupported("p:timing has no p:cTn[@nodeType='tmRoot']")
        tn_lst = _child(timing, "tnLst")
        if tn_lst is None or len(_only_children(tn_lst, {"par"}, "p:tnLst")) != 1:
            raise _Unsupported("p:tnLst must hold exactly one p:par time root")
        _require_attrs(root, ("id", "dur", "restart", "nodeType"), "the time root p:cTn")
        if root.get("dur") != "indefinite" or root.get("restart") != "never":
            raise _Unsupported("the time root p:cTn is not PowerPoint's indefinite/never root")
        children = _child(root, "childTnLst")
        main: list[dict[str, Any]] = []
        interactive: list[dict[str, Any]] = []
        root_children = (
            _only_children(children, {"seq", "video", "audio"}, "the time root p:childTnLst")
            if children is not None
            else []
        )
        for child in root_children:
            name = _local(child)
            if name in MEDIA_NODES:
                self._read_media(child)
                continue
            sequence_ctn = _child(child, "cTn")
            node_type = (child if sequence_ctn is None else sequence_ctn).get("nodeType")
            if node_type == "mainSeq":
                if main:
                    raise _Unsupported("more than one main sequence")
                main = self._read_main(child)
            elif node_type == "interactiveSeq":
                interactive.append(self._read_interactive(child, len(interactive)))
            else:
                raise _Unsupported(f"p:seq has unsupported nodeType {node_type!r}")
        unclaimed = sorted(set(self._builds) - self._builds_used)
        if unclaimed:
            spid, grp_id = unclaimed[0]
            raise _Unsupported(
                f"p:bldLst carries a build for spid {spid} group {grp_id}, which no imported "
                "effect animates"
            )
        if not main and not interactive:
            return None
        return {"mainSequence": main, "interactiveSequences": interactive}

    # -- extension -----------------------------------------------------
    def _read_extension(self, timing: etree._Element) -> None:
        ext_lst = _child(timing, "extLst")
        if ext_lst is None:
            return
        for ext in _only_children(ext_lst, {"ext"}, "p:timing/p:extLst"):
            uri = ext.get("uri")
            if uri != SDPM_EFFECT_EXT_URI:
                raise _Unsupported(f"p:timing carries an unknown extension {uri!r}")
            effects = ext.find(f"{{{SDPM_NS}}}effects")
            if effects is None:
                raise _Unsupported("the sdpm effect extension has no sdpm:effects payload")
            for node in effects:
                effect_id, ctn = node.get("id"), node.get("cTn")
                if not effect_id or not ctn:
                    raise _Unsupported("an sdpm:effect entry is missing its id or cTn")
                self._ext_ids[ctn] = effect_id

    # -- media ---------------------------------------------------------
    def _read_media(self, node: etree._Element) -> None:
        """Accept only the media node python-pptx's ``add_movie`` writes.

        A media node is understood but not represented in slide JSON: the
        builder recreates it from the ``video``/``audio`` element. Anything
        richer — a bookmark, a trim, an explicit autoplay condition — is a
        playback-affecting setting the JSON has no field for, so it sends the
        whole tree to raw instead of being thrown away.
        """
        _require_attrs(node, (), f"p:{_local(node)}")
        media = _child(node, "cMediaNode")
        if media is None:
            raise _Unsupported(f"p:{_local(node)} has no p:cMediaNode")
        _require_attrs(media, ("vol", "mute", "numSld", "showWhenStopped"), "p:cMediaNode")
        _only_children(media, {"cTn", "tgtEl"}, "p:cMediaNode")
        ctn = _child(media, "cTn")
        if ctn is None:
            raise _Unsupported("p:cMediaNode has no p:cTn")
        _require_attrs(ctn, ("id", "fill", "display", "dur", "restart"), "p:cMediaNode/p:cTn")
        _only_children(ctn, {"stCondLst"}, "p:cMediaNode/p:cTn")
        self._read_target(media, allow_range=False)

    # -- sequences -----------------------------------------------------
    def _read_main(self, seq: etree._Element) -> list[dict[str, Any]]:
        _require_attrs(seq, ("concurrent", "nextAc"), "the main p:seq")
        _only_children(
            seq, {"cTn", "prevCondLst", "nextCondLst"}, "the main p:seq"
        )
        ctn = _child(seq, "cTn")
        if ctn is None:
            raise _Unsupported("the main p:seq has no p:cTn")
        _require_attrs(ctn, ("id", "dur", "nodeType"), "the main sequence p:cTn")
        for tag, event in (("prevCondLst", "onPrev"), ("nextCondLst", "onNext")):
            cond_lst = _child(seq, tag)
            if cond_lst is None:
                continue
            for cond in _only_children(cond_lst, {"cond"}, f"the main sequence p:{tag}"):
                if cond.get("evt") != event or cond.find(f"{{{P_NS}}}tgtEl/{{{P_NS}}}sldTgt") is None:
                    raise _Unsupported(
                        f"the main sequence p:{tag} is not PowerPoint's slide {event} condition"
                    )
        return self._read_groups(ctn, sequence="mainSequence", interactive=False)

    def _read_interactive(self, seq: etree._Element, ordinal: int) -> dict[str, Any]:
        _require_attrs(seq, ("concurrent", "nextAc"), "an interactive p:seq")
        _only_children(seq, {"cTn", "prevCondLst", "nextCondLst"}, "an interactive p:seq")
        ctn = _child(seq, "cTn")
        if ctn is None:
            raise _Unsupported("an interactive p:seq has no p:cTn")
        _require_attrs(
            ctn,
            ("id", "restart", "fill", "evtFilter", "nodeType"),
            "an interactive sequence p:cTn",
        )
        start = _child(ctn, "stCondLst")
        if start is None:
            raise _Unsupported("an interactive sequence has no p:stCondLst trigger")
        conditions = _only_children(start, {"cond"}, "an interactive sequence p:stCondLst")
        if len(conditions) != 1:
            raise _Unsupported("an interactive sequence needs exactly one start condition")
        cond = conditions[0]
        _require_attrs(cond, ("evt", "delay"), "an interactive sequence trigger p:cond")
        if cond.get("evt") != "onClick":
            raise _Unsupported(
                f"an interactive sequence triggers on {cond.get('evt')!r}, and sdpm models only "
                "onClick shape triggers"
            )
        target_el = cond.find(f"{{{P_NS}}}tgtEl")
        if target_el is None:
            raise _Unsupported("an interactive sequence trigger has no p:tgtEl")
        trigger_target = self._read_target(cond, allow_range=False)
        sequence_id = f"interactive-{ordinal}"
        effects = self._read_groups(
            ctn, sequence=f"interactive:{sequence_id}", interactive=True,
            trigger_target=trigger_target,
        )
        return {
            "id": sequence_id,
            "trigger": {
                "type": "onShapeClick",
                "target": trigger_target,
                "delayMs": _cond_delay(cond, "an interactive sequence trigger"),
            },
            "effects": effects,
        }

    def _read_groups(
        self,
        ctn: etree._Element,
        *,
        sequence: str,
        interactive: bool,
        trigger_target: str | None = None,
    ) -> list[dict[str, Any]]:
        children = _child(ctn, "childTnLst")
        effects: list[dict[str, Any]] = []
        if children is None:
            return effects
        for click_index, click in enumerate(
            _only_children(children, {"par"}, f"{sequence} p:childTnLst")
        ):
            click_ctn = _child(click, "cTn")
            if click_ctn is None:
                raise _Unsupported(f"{sequence} click group has no p:cTn")
            _require_attrs(click_ctn, ("id", "fill"), f"{sequence} click group p:cTn")
            if self._delay_token(click_ctn) != "indefinite":
                raise _Unsupported(
                    f"{sequence} click group does not wait for a click "
                    f"(delay {self._delay_token(click_ctn)!r})"
                )
            start_groups = _child(click_ctn, "childTnLst")
            if start_groups is None:
                raise _Unsupported(f"{sequence} click group has no effects")
            # Sibling start groups share a parent begin time, so sequencing
            # lives in each group's own cumulative offset. The JSON model has
            # no field for that offset — it is derived from the effects — so a
            # group delay that is not the derived value carries a pause this
            # importer would silently drop, and the tree goes raw instead.
            expected_offset = 0
            for start_index, group in enumerate(
                _only_children(start_groups, {"par"}, f"{sequence} click group")
            ):
                group_ctn = _child(group, "cTn")
                if group_ctn is None:
                    raise _Unsupported(f"{sequence} start group has no p:cTn")
                _require_attrs(group_ctn, ("id", "fill"), f"{sequence} start group p:cTn")
                offset = self._delay(group_ctn, f"{sequence} start group")
                if offset != expected_offset:
                    raise _Unsupported(
                        f"{sequence} start group {start_index} begins at {offset} ms, and the "
                        f"effects before it end at {expected_offset} ms; the extra wait is not "
                        "expressible in the JSON timeline"
                    )
                group_children = _child(group_ctn, "childTnLst")
                if group_children is None:
                    raise _Unsupported(f"{sequence} start group has no effects")
                span = 0
                for node in _only_children(
                    group_children, {"par"}, f"{sequence} start group p:childTnLst"
                ):
                    effect = self._read_effect(
                        node,
                        sequence=sequence,
                        interactive=interactive,
                        trigger_target=trigger_target,
                        opens_click_group=start_index == 0,
                        click_index=click_index,
                    )
                    effects.append(effect)
                    span = max(
                        span,
                        effect["start"]["delayMs"] + (effect["timing"].get("durationMs") or 0),
                    )
                expected_offset += span
        return effects

    # -- one effect ----------------------------------------------------
    def _read_effect(
        self,
        par: etree._Element,
        *,
        sequence: str,
        interactive: bool,
        trigger_target: str | None,
        opens_click_group: bool,
        click_index: int,
    ) -> dict[str, Any]:
        ctn = _child(par, "cTn")
        if ctn is None:
            raise _Unsupported(f"{sequence} effect has no p:cTn")
        _only_children(par, {"cTn"}, f"{sequence} effect p:par")
        attrs = _require_attrs(ctn, SEMANTIC_VOCABULARY["effectCTn"], f"{sequence} effect p:cTn")
        # `p:iterate` used to be unlisted here, so a by-word or by-character
        # text animation — the three `animation.textOptions.unit` values — sent
        # the whole slide's timing to the raw fallback on the element alone.
        # `p:iterate` used to be unlisted here, so a by-word or by-character
        # text animation sent the whole slide's timing to the raw fallback.
        # `p:subTnLst` is the after-animation value and was unlisted for the
        # same reason — it was unwritable, so nothing produced one.
        _only_children(
            ctn, {"stCondLst", "childTnLst", "iterate", "subTnLst"}, f"{sequence} effect p:cTn"
        )
        node_type = attrs.get("nodeType")
        start_type = self._start_type(node_type, interactive, click_index, opens_click_group)
        behaviors = _child(ctn, "childTnLst")
        if behaviors is None:
            raise _Unsupported(f"{sequence} effect has no p:childTnLst behaviors")
        # An effect with no presetClass/presetID is the advanced form — a list
        # of behaviour primitives PowerPoint plays without naming — so it is
        # inverted as one rather than looked up as a preset.
        behavior_list: list[dict[str, Any]] | None = None
        if attrs.get("presetClass") is None or attrs.get("presetID") is None:
            behavior_list, target, duration = self._read_behavior_list(behaviors, sequence)
            named: dict[str, Any] = {"behaviors": behavior_list}
            grp_id = int(attrs.get("grpId", 0))
            # No preset means no measured build list, so the shape animates
            # without its text, which is what `p:bldP/@animBg` would have said.
            self._preset_build[(self._spid_of(target), grp_id)] = False
        else:
            # Resolved after the behaviours are in hand, not before: an option the
            # subtype cannot identify is found by comparing them.
            entry, options = self._preset_entry(attrs, sequence, behaviors)
            preset = dict(_semantic_preset(entry) or {})
            target, duration = self._read_behaviors(behaviors, entry, preset, sequence)
            named = {"preset": self._read_preset(preset, options)}
            grp_id = int(attrs.get("grpId", 0))
            self._preset_build[(self._spid_of(target), grp_id)] = _animates_background(entry)

        # Both before the effect dict is built, because the writer allocates an
        # effect ID from the JSON *including* its text and build fields: an
        # effect that learned them afterwards would fingerprint differently and
        # come back with the wrong ID.
        build_fields = self._claim_build(
            target, grp_id, self._preset_build.get((self._spid_of(target), grp_id), False)
        )
        iterate = self._read_iterate(ctn, sequence)
        text = {**(build_fields.pop("text", None) or {}), **iterate}

        # Set while the behaviours' targets were read, so it is in hand before
        # the effect dict — and therefore before the effect ID is allocated
        # from it, which is what the writer fingerprints.
        paragraph_range = self._paragraph_range
        self._paragraph_range = None

        effect: dict[str, Any] = {
            "target": (
                {"element": target, "paragraphRange": paragraph_range}
                if paragraph_range is not None
                else {"element": target}
            ),
            **named,
            "start": {"type": start_type, "delayMs": self._delay(ctn, f"{sequence} effect")},
            "timing": self._read_timing(attrs, duration, sequence),
            **({"text": text} if text else {}),
            **build_fields,
            "afterEffect": self._read_after_effect(ctn, sequence),
            "sound": None,
        }
        if behavior_list is not None:
            # A behaviour inherits the effect's duration when it states none, so
            # restating the inherited value would hand back JSON that differs
            # from the JSON that produced the package while writing the same
            # bytes. Only a behaviour that really times differently keeps it.
            effect_duration = effect["timing"].get("durationMs")
            for behavior in behavior_list:
                if behavior.get("durationMs") == effect_duration:
                    behavior.pop("durationMs")
        if start_type == "onShapeClick" and trigger_target is not None:
            effect["start"]["target"] = trigger_target
        explicit = self._ext_ids.get(attrs.get("id", ""))
        if explicit:
            effect["id"] = explicit
        effect["id"] = self._effect_ids.allocate(
            sequence=sequence, target=target, effect=effect
        )
        return {"id": effect.pop("id"), **effect}

    @staticmethod
    def _start_type(
        node_type: str | None, interactive: bool, click_index: int, opens_click_group: bool
    ) -> str:
        if node_type == "clickEffect":
            return "onShapeClick" if interactive else "onPageClick"
        if node_type == "afterEffect":
            if opens_click_group and click_index > 0:
                raise _Unsupported(
                    "an afterEffect opens a click group, which no writer form produces"
                )
            return "afterPrevious"
        if node_type == "withEffect":
            return "withPrevious"
        raise _Unsupported(f"effect p:cTn has unsupported nodeType {node_type!r}")

    def _preset_entry(
        self,
        attrs: Mapping[str, str],
        sequence: str,
        children: etree._Element | None = None,
    ) -> tuple[Any, dict[str, str] | None]:
        """Return the catalog entry for these preset attributes, and the option they name.

        When the subtype names an ``Effect Options`` value, the entry comes back
        **overlaid with that value's measured behaviours** — the same overlay
        the writer applies. Without it :meth:`_read_behaviors` would validate
        what was written against the tile's own behaviour list and reject it:
        19 of the 95 tiles have no measured behaviours at all, so every option
        on those tiles dropped to the raw fallback rather than importing.
        """
        preset_class = attrs.get("presetClass")
        preset_id = attrs.get("presetID")
        if preset_class is None or preset_id is None:
            raise _Unsupported(
                f"{sequence} effect has no presetClass/presetID, so it is an explicit behavior "
                "list whose payload sdpm does not invert"
            )
        token = (preset_class, preset_id, attrs.get("presetSubtype", "0"))
        entry = self.reverse.presets.get(token)
        if entry is None:
            raise _Unsupported(
                f"no catalog entry establishes presetClass={preset_class!r} "
                f"presetID={preset_id!r} presetSubtype={attrs.get('presetSubtype', '0')!r}"
            )
        found = self.reverse.preset_options.get(token)
        if found is None and children is not None:
            # No subtype says which option this is, so the behaviours do. The
            # writer transcribes them, so a hit here is an exact match on the
            # measured bytes rather than a nearest guess.
            found = self.reverse.preset_option_payloads.get((*token, _xml_payload(children)))
        if found is None:
            return entry, None
        _owner, setting, value = found
        measured = (
            ((entry.ooxml.get("effectOptions") or {}).get(setting) or {}).get("values") or {}
        ).get(value)
        if not isinstance(measured, Mapping):
            return entry, None
        overlay = dict(entry.ooxml)
        overlay["presetSubtype"] = measured.get("presetSubtype")
        overlay["behaviors"] = measured.get("behaviors") or []
        overlay["behaviorChildren"] = measured.get("behaviorChildren") or []
        if measured.get("measuredDurationMs") is not None:
            overlay["measuredDurationMs"] = measured["measuredDurationMs"]
        return replace(entry, ooxml=overlay), {setting: value}

    def _read_preset(
        self, preset: Mapping[str, Any], options: Mapping[str, str] | None
    ) -> dict[str, Any]:
        """Return the semantic preset, naming the ``Effect Options`` value when one is written.

        ``options`` is **omitted** rather than set to null when the effect is at
        its default, so JSON written without options reads back without them.
        An option the subtype cannot identify is omitted too; see
        :func:`_option_subtypes` for which, and why guessing there would be
        worse than saying nothing.
        """
        read: dict[str, Any] = {
            "category": preset.get("category"),
            "effect": preset.get("effect"),
        }
        if options:
            read["options"] = dict(options)
        return read

    def _read_after_effect(self, ctn: etree._Element, sequence: str) -> dict[str, Any]:
        """Invert the effect's ``p:subTnLst`` into its ``afterEffect``.

        The absent case is the common one and is the **default**, not a gap:
        measured 2026-11-02, clearing the pane's ``After animation`` to ``Don't
        Dim`` removes the whole ``p:subTnLst``, so no node means ``none``.

        Everything else is read strictly, and a form that does not match what
        was measured raises :class:`_Unsupported` so the effect falls to raw
        replay. That is the point rather than caution: a near miss here would
        hand back an ``afterEffect`` the package does not carry, and the two
        pairs differ by one attribute each — ``masterRel`` for the hides and the
        colour child for the dims — so "close enough" is a different value.
        """
        sub_list = _child(ctn, "subTnLst")
        if sub_list is None:
            return {"type": "none"}
        children = _only_children(sub_list, {"set", "animClr"}, f"{sequence} effect p:subTnLst")
        if len(children) != 1:
            raise _Unsupported(
                f"{sequence} effect p:subTnLst carries {len(children)} children; one "
                "after-animation value writes exactly one"
            )
        node = children[0]
        behavior = _child(node, "cBhvr")
        if behavior is None or behavior.get("override") != "childStyle":
            raise _Unsupported(
                f"{sequence} effect p:subTnLst child has no p:cBhvr override=\"childStyle\""
            )
        inner = _child(behavior, "cTn")
        if inner is None:
            raise _Unsupported(f"{sequence} effect after-animation behaviour has no p:cTn")
        inner_attrs = _require_attrs(
            inner,
            ("id", "dur", "fill", "display", "masterRel", "afterEffect"),
            f"{sequence} effect after-animation p:cTn",
        )
        if inner_attrs.get("afterEffect") not in {"1", "true"}:
            raise _Unsupported(
                f"{sequence} effect p:subTnLst behaviour is not marked afterEffect"
            )
        master_rel = inner_attrs.get("masterRel")
        # An explicit None test, not `or ()`: an lxml element with no children is
        # falsey today and will be truthy in a future version, so the short form
        # would silently stop reading the list.
        name_list = _child(behavior, "attrNameLst")
        names = [
            (name.text or "").strip()
            for name in (name_list if name_list is not None else ())
            if _local(name) == "attrName"
        ]
        to = _child(node, "to")

        if _local(node) == "set":
            value = _child(to, "strVal") if to is not None else None
            if names != ["style.visibility"] or value is None or value.get("val") != "hidden":
                raise _Unsupported(
                    f"{sequence} effect p:subTnLst p:set animates {names} to "
                    f"{None if value is None else value.get('val')!r}, not style.visibility to "
                    "'hidden'"
                )
            # The one attribute that separates them. `sameClick` waits for this
            # effect to end — which is why only that form carries a start
            # condition naming the effect's own id — and `nextClick` waits for
            # the audience.
            if master_rel == "sameClick":
                return {"type": "hide"}
            if master_rel == "nextClick":
                return {"type": "hideOnNextClick"}
            raise _Unsupported(
                f"{sequence} effect after-animation masterRel {master_rel!r} is neither "
                "'sameClick' nor 'nextClick'"
            )

        if names != ["ppt_c"]:
            raise _Unsupported(
                f"{sequence} effect p:subTnLst p:animClr animates {names}, not ppt_c"
            )
        srgb = to.find(f"{{{A_NS}}}srgbClr") if to is not None else None
        scheme = to.find(f"{{{A_NS}}}schemeClr") if to is not None else None
        if srgb is not None:
            raw = srgb.get("val") or ""
            if not re.fullmatch(r"[0-9A-Fa-f]{6}", raw):
                raise _Unsupported(
                    f"{sequence} effect dim colour {raw!r} is not a six-digit sRGB hex"
                )
            return {"type": "dim", "color": f"#{raw.upper()}"}
        if scheme is not None:
            # Only the one scheme colour that was measured inverts. Mapping any
            # other to a bare `dim` would drop which colour the deck dims to,
            # and raw replay keeps it instead — the seven unmeasured swatches
            # are exactly the decks this protects.
            if scheme.get("val") == MEASURED_DIM_SCHEME_COLOR:
                return {"type": "dim"}
            raise _Unsupported(
                f"{sequence} effect dims to scheme colour {scheme.get('val')!r}; only "
                f"{MEASURED_DIM_SCHEME_COLOR!r} was measured, so inverting this one would drop "
                "which colour the deck dims to"
            )
        raise _Unsupported(f"{sequence} effect p:animClr after-animation has no p:to colour")

    def _read_timing(
        self, attrs: Mapping[str, str], duration: int | None, sequence: str
    ) -> dict[str, Any]:
        from sdpm.engine.timing.writer import PERCENT_SCALE, REPEAT_SCALE

        timing: dict[str, Any] = {}
        if duration is not None:
            timing["durationMs"] = duration
        if "repeatCount" in attrs:
            raw = attrs["repeatCount"]
            if not raw.isdigit() or int(raw) % REPEAT_SCALE:
                raise _Unsupported(
                    f"{sequence} effect repeatCount {raw!r} is not a whole repetition count"
                )
            timing["repeatCount"] = int(raw) // REPEAT_SCALE
        if "repeatDur" in attrs:
            raw = attrs["repeatDur"]
            if not raw.isdigit():
                raise _Unsupported(f"{sequence} effect repeatDur {raw!r} is not a duration")
            timing["repeatDurationMs"] = int(raw)
        if attrs.get("autoRev") in {"1", "true"}:
            timing["autoReverse"] = True
        elif "autoRev" in attrs and attrs["autoRev"] not in {"0", "false"}:
            raise _Unsupported(f"{sequence} effect autoRev {attrs['autoRev']!r} is not a boolean")
        # "Rewind when done playing" is `@fill`, and the default is `hold`:
        # measured 2026-11-02, the checkbox moved the existing fill from "hold"
        # to "remove" and touched nothing else. So `hold` reports nothing rather
        # than `rewind: False` — the writer emits no `rewind` key for a false,
        # and reporting one would hand back JSON that differs from the JSON that
        # produced the package.
        if attrs.get("fill") == "remove":
            timing["rewind"] = True
        for name, key in (("accel", "acceleration"), ("decel", "deceleration")):
            if name not in attrs:
                continue
            raw = attrs[name]
            if not raw.isdigit():
                raise _Unsupported(f"{sequence} effect {name} {raw!r} is not a percentage")
            value = int(raw) / PERCENT_SCALE
            timing[key] = round(value, 6)
        if "restart" in attrs:
            timing["restart"] = attrs["restart"]
        return timing

    # -- behaviors -----------------------------------------------------
    # -- the advanced form: an explicit behaviour list ------------------
    def _unscale(self, raw: str, scale: int, what: str, *, whole: bool) -> int | float:
        """Divide a scaled integer attribute back out.

        An angle is written as whole degrees times 60000, so one that does not
        divide exactly was not written by this writer and inverting it would
        invent a number the package never carried — the raw fallback keeps that
        replayable instead. A scale factor is a *fraction* times 100000, so 1.5
        is the ordinary case and a remainder says nothing is wrong.
        """
        try:
            value = int(raw)
        except ValueError:
            raise _Unsupported(f"{what} {raw!r} is not an integer") from None
        if whole:
            if value % scale:
                raise _Unsupported(f"{what} {raw!r} is not a whole multiple of {scale}")
            return value // scale
        divided = value / scale
        # An integral factor comes back as an int so the JSON reads as `2`
        # rather than `2.0`; both write the same bytes.
        return int(divided) if divided.is_integer() else divided

    def _read_attr_name(self, behavior: etree._Element) -> str | None:
        names = _child(behavior, "attrNameLst")
        if names is None:
            return None
        found = [child.text for child in names if isinstance(child.tag, str)]
        if len(found) != 1 or not found[0]:
            raise _Unsupported("p:attrNameLst does not carry exactly one attribute name")
        return str(found[0])

    def _behavior_payload(self, node: etree._Element, tag: str) -> Any:
        """Return the ``p:to`` payload for the three behaviours that carry one."""
        to = _child(node, "to")
        if to is None:
            raise _Unsupported(f"{tag} has no p:to payload")
        if tag == "p:animClr":
            # The colour is DrawingML, so it is not in the p: namespace the
            # rest of a timing tree lives in.
            colour = to.find(f"{{{A_NS}}}srgbClr")
            if colour is None or not colour.get("val"):
                raise _Unsupported("p:animClr/p:to carries no a:srgbClr/@val")
            return str(colour.get("val"))
        if tag == "p:animScale":
            factors: dict[str, Any] = {}
            for axis in ("x", "y"):
                raw = to.get(axis)
                if raw is None:
                    raise _Unsupported(f"p:animScale/p:to has no @{axis}")
                factors[axis] = self._unscale(
                    raw, PERCENT_SCALE, f"p:animScale/p:to/@{axis}", whole=False
                )
            return factors
        value = _child(to, "strVal")
        if value is None or value.get("val") is None:
            raise _Unsupported("p:set/p:to carries no p:strVal/@val")
        return str(value.get("val"))

    def _behavior_fields(self, node: etree._Element, tag: str) -> dict[str, Any]:
        """Invert one behaviour element's own attributes.

        The mirror of the writer's ``_behavior_attrs``. Every enumerated value
        is checked against the same vocabulary the writer validates against, so
        a package carrying something outside it falls back to raw rather than
        importing as a value sdpm would refuse to write back.
        """
        fields: dict[str, Any] = {}

        def enumerated(attr: str, allowed: frozenset[str], key: str) -> None:
            raw = node.get(attr)
            if raw is None:
                return
            if raw not in allowed:
                raise _Unsupported(f"{tag}/@{attr} {raw!r} is not one of {sorted(allowed)}")
            fields[key] = raw

        if tag == "p:animMotion":
            path = node.get("path")
            if not path:
                raise _Unsupported("p:animMotion has no @path")
            fields["path"] = path
            enumerated("pathEditMode", MOTION_PATH_EDIT_MODES, "pathEditMode")
            enumerated("origin", MOTION_ORIGINS, "origin")
            if node.get("rAng") is not None:
                fields["rotationAngle"] = self._unscale(
                    str(node.get("rAng")), ANGLE_SCALE, "p:animMotion/@rAng", whole=True
                )
            if node.get("ptsTypes") is not None:
                fields["pointTypes"] = str(node.get("ptsTypes"))
        elif tag == "p:animRot":
            for attr, key in (("by", "by"), ("from", "fromValue"), ("to", "to")):
                if node.get(attr) is not None:
                    fields[key] = self._unscale(
                        str(node.get(attr)), ANGLE_SCALE, f"p:animRot/@{attr}", whole=True
                    )
        elif tag == "p:anim":
            enumerated("calcmode", ANIM_CALC_MODES, "calcMode")
            enumerated("valueType", ANIM_VALUE_TYPES, "valueType")
            for attr, key in (("by", "by"), ("from", "fromValue"), ("to", "to")):
                if node.get(attr) is not None:
                    fields[key] = str(node.get(attr))
        elif tag == "p:animEffect":
            enumerated("transition", ANIM_EFFECT_TRANSITIONS, "transition")
            if node.get("filter") is not None:
                fields["filter"] = str(node.get("filter"))
        elif tag == "p:cmd":
            raw_type = node.get("type")
            if raw_type is not None and raw_type not in CMD_TYPES:
                raise _Unsupported(f"p:cmd/@type {raw_type!r} is not one of {sorted(CMD_TYPES)}")
            command = node.get("cmd")
            if not command:
                raise _Unsupported("p:cmd has no @cmd")
            # The writer composes `cmd` as `command(value)`, and a PowerPoint
            # command's bracket always delimits its argument — `playFrom(0.0)`,
            # against bare `pause` or `stop`. So the two parts are split back
            # out, which is what makes the documented `command` + `value` form
            # come back as it was written.
            text = str(command)
            if text.endswith(")") and "(" in text:
                name, _, argument = text[:-1].partition("(")
                fields["command"] = name
                fields["value"] = argument
            else:
                fields["command"] = text
            # `call` is the writer's default, so restating it would hand back
            # JSON that differs from the JSON that produced these bytes.
            if raw_type is not None and raw_type != "call":
                fields["commandType"] = raw_type
        return fields

    def _read_behavior_list(
        self, children: etree._Element, sequence: str
    ) -> tuple[list[dict[str, Any]], str, int | None]:
        """Invert an effect written as explicit behaviour primitives.

        An effect with no ``presetClass``/``presetID`` is the advanced form: a
        list of behaviours PowerPoint plays but does not name. It used to drop
        the whole slide's timing to the raw fallback, which round-trips the
        package but hands back no JSON anyone can read or edit. Each of the
        eight primitives is inverted here instead.

        Anything outside the writer's own vocabulary still raises, so the raw
        fallback keeps covering what cannot be written back.
        """
        behaviors: list[dict[str, Any]] = []
        targets: set[str] = set()
        duration: int | None = None
        for node in children:
            if not isinstance(node.tag, str):
                continue
            tag = f"p:{_local(node)}"
            kind = BEHAVIOR_TYPE_BY_TAG.get(tag)
            if kind is None:
                raise _Unsupported(f"{sequence} effect writes {tag}, which is not a behavior")
            common = _child(node, "cBhvr")
            if common is None:
                raise _Unsupported(f"{sequence} behavior {tag} has no p:cBhvr")
            _only_children(common, {"cTn", "tgtEl", "attrNameLst"}, f"{tag}/p:cBhvr")
            common_ctn = _child(common, "cTn")
            if common_ctn is None:
                raise _Unsupported(f"{tag}/p:cBhvr has no p:cTn")
            _require_attrs(common_ctn, ("id", "dur", "fill"), f"{tag}/p:cBhvr/p:cTn")
            targets.add(self._read_target(common, allow_range=True))

            behavior: dict[str, Any] = {"type": kind}
            behavior.update(self._behavior_fields(node, tag))
            if tag in ("p:animClr", "p:animScale", "p:set"):
                behavior["to"] = self._behavior_payload(node, tag)
            attr_name = self._read_attr_name(common)
            if attr_name is not None:
                behavior["attrName"] = attr_name
            raw = common_ctn.get("dur")
            if raw is not None:
                if not raw.isdigit():
                    raise _Unsupported(f"{tag} duration {raw!r} is not a millisecond value")
                behavior["durationMs"] = int(raw)
                duration = int(raw)
            behaviors.append(behavior)

        if not behaviors:
            raise _Unsupported(f"{sequence} effect has an empty behavior list")
        if len(targets) != 1:
            raise _Unsupported(
                f"{sequence} behaviors animate {len(targets)} targets; sdpm models one per effect"
            )
        return behaviors, targets.pop(), duration

    def _read_behaviors(
        self,
        children: etree._Element,
        entry: Any,
        preset: Mapping[str, Any],
        sequence: str,
    ) -> tuple[str, int | None]:
        found = [
            f"p:{_local(child)}" for child in children if isinstance(child.tag, str)
        ]
        measured = entry.ooxml.get("behaviors")
        if isinstance(measured, (list, tuple)) and measured:
            return self._read_measured_behaviors(children, entry, measured, found, sequence)
        expected = sorted(str(tag) for tag in entry.ooxml.get("behaviorChildren") or ())
        if sorted(found) != expected:
            raise _Unsupported(
                f"{sequence} effect writes behaviors {sorted(found)} but catalog entry "
                f"{entry.key!r} records {expected}"
            )
        category = str(preset.get("category"))
        targets: set[str] = set()
        duration: int | None = None
        for child in children:
            tag = f"p:{_local(child)}"
            behavior = _child(child, "cBhvr")
            if behavior is None:
                raise _Unsupported(f"{sequence} behavior {tag} has no p:cBhvr")
            _only_children(behavior, {"cTn", "tgtEl", "attrNameLst"}, f"{tag}/p:cBhvr")
            behavior_ctn = _child(behavior, "cTn")
            if behavior_ctn is None:
                raise _Unsupported(f"{tag}/p:cBhvr has no p:cTn")
            _require_attrs(behavior_ctn, ("id", "dur", "fill"), f"{tag}/p:cBhvr/p:cTn")
            targets.add(self._read_target(behavior, allow_range=True))
            if tag == "p:set":
                self._check_visibility_set(child, behavior, category, sequence)
                continue
            if tag == "p:animEffect":
                self._check_anim_effect(child, entry, category, sequence)
            elif tag == "p:cmd":
                self._check_command(child, entry, sequence)
            raw = behavior_ctn.get("dur")
            if raw is not None:
                if not raw.isdigit():
                    raise _Unsupported(f"{tag} duration {raw!r} is not a millisecond value")
                duration = int(raw)
        if len(targets) != 1:
            raise _Unsupported(
                f"{sequence} effect animates {len(targets)} different shapes in one effect"
            )
        return targets.pop(), duration

    def _read_measured_behaviors(
        self,
        children: etree._Element,
        entry: Any,
        measured: Sequence[Mapping[str, Any]],
        found: Sequence[str],
        sequence: str,
    ) -> tuple[str, int | None]:
        """Read back an effect whose behaviours the GUI capture measured.

        The general path above compares the written children against the
        entry's distinct ``behaviorChildren`` and then checks each one against
        the catalog's general rules. Neither works for a measured effect: **57
        of the 76 repeat an element**, so a distinct comparison rejects a
        correct effect, and an emphasis ``p:set`` animates a font attribute
        rather than the visibility the general rule insists on.

        What replaces both is a stricter statement: the written elements must be
        the measured ones, **in the measured order**. The duration is recovered
        by inverting the one thing the writer is allowed to change — the
        proportional scale — using the first behaviour whose measured duration
        is a number the writer scales.
        """
        expected = [str(behavior.get("element")) for behavior in measured]
        if list(found) != expected:
            raise _Unsupported(
                f"{sequence} effect writes behaviors {list(found)} but catalog entry "
                f"{entry.key!r} measured {expected}"
            )
        targets: set[str] = set()
        scale: Fraction | None = None
        for node, behavior in zip(children, measured):
            tag = f"p:{_local(node)}"
            carrier = _child(node, "cBhvr")
            if carrier is None:
                raise _Unsupported(f"{sequence} behavior {tag} has no p:cBhvr")
            _only_children(carrier, {"cTn", "tgtEl", "attrNameLst"}, f"{tag}/p:cBhvr")
            carrier_ctn = _child(carrier, "cTn")
            if carrier_ctn is None:
                raise _Unsupported(f"{tag}/p:cBhvr has no p:cTn")
            targets.add(self._read_target(carrier, allow_range=True))
            written = carrier_ctn.get("dur")
            source = behavior.get("durMs")
            if scale is None and written is not None and source and written.isdigit():
                # The visibility p:set is skipped as a scale source on purpose:
                # its duration is 1 ms at every effect duration, so a ratio
                # taken from it would always read back as 1 ms.
                if not (tag == "p:set" and int(source) == 1):
                    scale = Fraction(int(written), int(source))
        if len(targets) != 1:
            raise _Unsupported(
                f"{sequence} effect animates {len(targets)} different shapes in one effect"
            )
        measured_duration = entry.ooxml.get("measuredDurationMs")
        if scale is None or measured_duration is None:
            return targets.pop(), None
        return targets.pop(), int(round(int(measured_duration) * scale))

    def _check_visibility_set(
        self,
        node: etree._Element,
        behavior: etree._Element,
        category: str,
        sequence: str,
    ) -> None:
        from sdpm.engine.timing.writer import VISIBILITY_ATTR

        if category not in {"entrance", "exit"}:
            raise _Unsupported(
                f"{sequence} effect has a p:set on a {category} preset, whose attribute the "
                "catalog does not establish"
            )
        attr_lst = _child(behavior, "attrNameLst")
        names = [
            (child.text or "").strip()
            for child in (attr_lst if attr_lst is not None else ())
        ]
        if names != [VISIBILITY_ATTR]:
            raise _Unsupported(f"{sequence} effect p:set changes {names}, not {VISIBILITY_ATTR}")
        value = node.find(f"{{{P_NS}}}to/{{{P_NS}}}strVal")
        wanted = "visible" if category == "entrance" else "hidden"
        if value is None or value.get("val") != wanted:
            raise _Unsupported(
                f"{sequence} effect p:set writes {value.get('val') if value is not None else None!r}, "
                f"not the {category} visibility {wanted!r}"
            )

    def _check_anim_effect(
        self, node: etree._Element, entry: Any, category: str, sequence: str
    ) -> None:
        attrs = _require_attrs(node, ("filter", "transition"), f"{sequence} p:animEffect")
        expected_filter = entry.ooxml.get("animEffectFilter")
        if attrs.get("filter") != expected_filter:
            raise _Unsupported(
                f"{sequence} p:animEffect filter {attrs.get('filter')!r} is not the catalogued "
                f"{expected_filter!r} of {entry.key!r}"
            )
        expected = {"entrance": "in", "exit": "out"}.get(category)
        if attrs.get("transition") != expected and not (expected is None and "transition" not in attrs):
            raise _Unsupported(
                f"{sequence} p:animEffect transition {attrs.get('transition')!r} does not match "
                f"the {category} preset"
            )

    def _check_command(self, node: etree._Element, entry: Any, sequence: str) -> None:
        attrs = _require_attrs(node, ("type", "cmd"), f"{sequence} p:cmd")
        if attrs.get("cmd") != entry.ooxml.get("command") or attrs.get("type") != "call":
            raise _Unsupported(
                f"{sequence} p:cmd {attrs!r} is not the catalogued command of {entry.key!r}"
            )

    # -- targets, delays, builds ---------------------------------------
    def _read_target(self, parent: etree._Element, *, allow_range: bool) -> str:
        target = _child(parent, "tgtEl")
        if target is None:
            raise _Unsupported("a behavior or condition has no p:tgtEl")
        children = _only_children(target, {"spTgt"}, "p:tgtEl")
        if len(children) != 1:
            raise _Unsupported("p:tgtEl must name exactly one p:spTgt shape target")
        sp_tgt = children[0]
        _require_attrs(sp_tgt, ("spid",), "p:spTgt")
        spid = _int_attr(sp_tgt, "spid", "p:spTgt")
        identity = self.identities.get(spid)
        if identity is None:
            raise MotionReadError(
                f"slide {self.slide_slug!r}: p:spTgt/@spid {spid} names no shape on the slide, "
                "so neither a semantic target nor a raw remapping can be built"
            )
        nested = _only_children(sp_tgt, {"txEl"} if allow_range else set(), "p:spTgt")
        self._paragraph_range = None
        if nested:
            self._paragraph_range = self._read_paragraph_range(nested)
        self.targets.add(spid)
        return identity.element_id

    def _read_paragraph_range(self, nested: list[etree._Element]) -> dict[str, int]:
        """Invert ``p:spTgt/p:txEl/p:pRg`` into ``target.paragraphRange``.

        The reader used to refuse any text sub-target outright, which sent the
        whole slide's timing to the raw fallback. Only the paragraph range is
        inverted: ``p:txEl`` can also carry a character range or a whole-text
        reference, and those have no field in the JSON, so they keep the raw
        fallback rather than importing as a range they are not.
        """
        if len(nested) != 1:
            raise _Unsupported("p:spTgt carries more than one p:txEl")
        _only_children(nested[0], {"pRg"}, "p:txEl")
        rng = _child(nested[0], "pRg")
        if rng is None:
            raise _Unsupported(
                "p:txEl carries no p:pRg, so it names a text range sdpm has no field for"
            )
        attrs = _require_attrs(rng, ("st", "end"), "p:pRg")
        bounds: dict[str, int] = {}
        for attribute, name in (("st", "start"), ("end", "end")):
            raw = attrs.get(attribute)
            if raw is None or not raw.lstrip("-").isdigit():
                raise _Unsupported(f"p:pRg/@{attribute} {raw!r} is not a paragraph index")
            bounds[name] = int(raw)
        return bounds

    def _spid_of(self, element_id: str) -> int:
        for spid, identity in self.identities.items():
            if identity.element_id == element_id:
                return spid
        raise _Unsupported(f"no shape carries logical id {element_id!r}")

    @staticmethod
    def _delay_token(ctn: etree._Element) -> str | None:
        cond_lst = _child(ctn, "stCondLst")
        if cond_lst is None:
            return None
        conditions = [child for child in cond_lst if isinstance(child.tag, str)]
        if len(conditions) != 1 or _local(conditions[0]) != "cond":
            return None
        return conditions[0].get("delay")

    def _delay(self, ctn: etree._Element, what: str) -> int:
        token = self._delay_token(ctn)
        if token is None:
            raise _Unsupported(f"{what} has no single p:cond start delay")
        if token.isdigit():
            return int(token)
        raise _Unsupported(f"{what} start delay {token!r} is not a millisecond value")

    def _read_iterate(self, ctn: etree._Element, sequence: str) -> dict[str, Any]:
        """Invert ``p:iterate`` into ``text.unit`` and the inter-item delay.

        ``CT_TLIterateData`` is a choice of exactly one ``p:tmAbs`` or
        ``p:tmPct``. The writer emits only ``p:tmPct``, because the absolute
        form has no field in the JSON, so a package carrying ``p:tmAbs`` stays
        raw rather than importing as a percentage it is not.
        """
        from sdpm.engine.timing.writer import TIME_PERCENT_SCALE

        node = _child(ctn, "iterate")
        if node is None:
            return {}
        attrs = _require_attrs(node, ("type", "backwards"), f"{sequence} p:iterate")
        if attrs.get("backwards") is not None:
            raise _Unsupported("p:iterate/@backwards is not a value sdpm writes back")
        wanted = attrs.get("type")
        unit = None
        for value in ("byParagraph", "byWord", "byCharacter"):
            entry = self.index.entry(f"animation.textOptions.unit.{value}")
            if entry is not None and entry.ooxml.get("type") == wanted:
                unit = value
                break
        if unit is None:
            raise _Unsupported(f"p:iterate/@type {wanted!r} is not a catalogued text unit")
        children = _only_children(node, {"tmPct", "tmAbs"}, f"{sequence} p:iterate")
        if len(children) != 1:
            raise _Unsupported("p:iterate must carry exactly one interval")
        interval = children[0]
        if _local(interval) != "tmPct":
            raise _Unsupported(
                "p:iterate carries p:tmAbs, an absolute interval sdpm has no JSON field for"
            )
        raw = interval.get("val")
        if raw is None or not raw.lstrip("-").isdigit():
            raise _Unsupported(f"p:tmPct/@val {raw!r} is not a percentage")
        scaled = int(raw) / TIME_PERCENT_SCALE * 100
        percent = int(scaled) if float(scaled).is_integer() else scaled
        return {"unit": unit, "interItemDelayPercent": percent}

    def _build_value(
        self, family: str, element_name: str, child: str | None, attrs: Mapping[str, str]
    ) -> str | None:
        """Return the catalogued build value whose recorded form is ``attrs``.

        Resolved against the catalog rather than against a table repeated here,
        so a build value added to the catalog is readable without touching the
        reader. An entry records its form either as an ``attributes`` mapping
        (the ``p:bldP`` levels) or as a single ``attribute``/``value`` pair
        (``p:bldDgm`` and ``a:bldChart``), and both shapes are compared.
        """
        wanted = {str(k): str(v) for k, v in attrs.items()}
        for value in self.index.build_values(family, element=element_name, child=child):
            entry = self.index.build_entry(family, value, element=element_name, child=child)
            if entry is None:
                continue
            recorded = entry.ooxml.get("attributes")
            if isinstance(recorded, Mapping):
                form = {str(k): str(v) for k, v in recorded.items()}
            else:
                name, token = entry.ooxml.get("attribute"), entry.ooxml.get("value")
                form = {str(name): str(token)} if name and token is not None else {}
            if form == wanted:
                return value
        return None

    def _decode_build_list(self, timing: etree._Element) -> None:
        """Invert ``p:bldLst`` into per-token ``text``/``chart``/``smartArt``.

        The old reader accepted ``p:bldP`` alone, allowed only the three
        attributes a preset's own build list carries, and read nothing into the
        JSON — it validated ``@animBg`` against the preset and stopped. So a
        chart build (``p:bldGraphic``), a SmartArt build (``p:bldDgm``) and even
        a plain paragraph level (``p:bldP/@build``) each sent the whole slide's
        timing to the raw fallback on an unexpected element or attribute, and
        the builds it did accept came back as no JSON at all.

        Decoding happens here, before the sequences, and the fields are merged
        into the effect in :meth:`_read_effect`. ``@animBg`` cannot be resolved
        yet, because whether it is a JSON request or the preset's own
        catalogued form depends on the preset — so the raw flag is carried and
        settled there.
        """
        bld_lst = _child(timing, "bldLst")
        if bld_lst is None:
            return
        allowed = {
            "bldP": ("spid", "grpId", "build", "bldLvl", "rev", "animBg"),
            "bldGraphic": ("spid", "grpId"),
            "bldDgm": ("spid", "grpId", "bld"),
        }
        for build in _only_children(bld_lst, set(allowed), "p:bldLst"):
            local = _local(build)
            tag = f"p:{local}"
            attrs = _require_attrs(build, allowed[local], tag)
            spid = _int_attr(build, "spid", tag)
            if spid not in self.identities:
                raise MotionReadError(
                    f"slide {self.slide_slug!r}: {tag}/@spid {spid} names no shape on the slide"
                )
            token = (spid, int(attrs.get("grpId", 0)))
            if token in self._builds:
                raise _Unsupported(
                    f"p:bldLst carries two builds for spid {spid} group {token[1]}"
                )
            if local == "bldP":
                self._builds[token] = self._decode_paragraph_build(build, attrs, tag)
            elif local == "bldGraphic":
                self._builds[token] = {"chart": self._decode_chart_build(build, tag)}
            else:
                self._builds[token] = {"smartArt": self._decode_diagram_build(attrs, tag)}

    def _decode_paragraph_build(
        self, build: etree._Element, attrs: Mapping[str, str], tag: str
    ) -> dict[str, Any]:
        _only_children(build, (), tag)
        text: dict[str, Any] = {}
        form = {name: attrs[name] for name in ("build", "bldLvl") if name in attrs}
        if form:
            # ``bldLvl`` is what makes a build a *level*: ``build="p"`` alone is
            # the by-paragraph sequence, and the same token with a level is one
            # of the five paragraph levels. The two families record identical
            # forms for "as one object" and "all at once", so without this rule
            # one OOXML form would resolve to two different JSON fields.
            family, field = (
                ("animation.textOptions.level", "level") if "bldLvl" in form
                else ("animation.textOptions.sequence", "sequence")
            )
            value = self._build_value(family, "p:bldP", None, form)
            if value is None:
                raise _Unsupported(
                    f"{tag} carries {form}, which no catalogued text build records"
                )
            text[field] = value
        if attrs.get("rev") in {"1", "true"}:
            text["reverseOrder"] = True
        return {"text": text, "animBg": attrs.get("animBg") in {"1", "true"}}

    def _decode_chart_build(self, build: etree._Element, tag: str) -> dict[str, Any]:
        _only_children(build, {"bldSub"}, tag)
        sub_build = _child(build, "bldSub")
        if sub_build is None:
            raise _Unsupported(f"{tag} carries no p:bldSub, so its chart build is unknown")
        # a:bldChart is DrawingML, so it is not in the p: namespace the rest of
        # a timing tree lives in.
        chart = sub_build.find(f"{{{A_NS}}}bldChart")
        if chart is None:
            raise _Unsupported(f"{tag}/p:bldSub carries no a:bldChart")
        attrs = _require_attrs(chart, ("bld", "animBg"), "a:bldChart")
        if attrs.get("animBg") is not None:
            raise _Unsupported("a:bldChart/@animBg is not a value sdpm writes back")
        value = self._build_value(
            "animation.textOptions.level", "p:bldGraphic", "p:bldSub/a:bldChart",
            {"bld": attrs.get("bld", "")},
        )
        if value is None:
            raise _Unsupported(
                f"a:bldChart/@bld {attrs.get('bld')!r} is not a catalogued chart build"
            )
        return {"build": value}

    def _decode_diagram_build(self, attrs: Mapping[str, str], tag: str) -> dict[str, Any]:
        value = self._build_value(
            "animation.smartArt.build", "p:bldDgm", None, {"bld": attrs.get("bld", "")}
        )
        if value is None:
            raise _Unsupported(
                f"{tag}/@bld {attrs.get('bld')!r} is not a catalogued SmartArt build"
            )
        return {"build": value}

    def _claim_build(
        self, target: str, grp_id: int, animates_background: bool
    ) -> dict[str, Any]:
        """Return the build fields belonging to one effect, settling ``@animBg``.

        ``text.animateBackground`` is tri-state and the preset is what makes it
        readable. Absent, it means "whatever this preset's own capture records";
        set, it overrides. So ``@animBg`` only belongs in the imported JSON when
        it **disagrees** with the preset — restating agreement would add a field
        the caller never wrote, to every one of the 95 tiles whose capture
        records a build list.

        That is also why this runs here rather than in the decoder: the
        disagreement is not visible until the preset is known.
        """
        token = (self._spid_of(target), grp_id)
        decoded = self._builds.get(token)
        if decoded is None or token in self._builds_used:
            return {}
        self._builds_used.add(token)
        fields = {key: value for key, value in decoded.items() if key != "animBg"}
        if "text" in fields:
            text = dict(fields["text"])
            written = bool(decoded.get("animBg"))
            if written != animates_background:
                text["animateBackground"] = written
            fields["text"] = text
            if not text:
                del fields["text"]
        return fields


def _animates_background(entry: Any) -> bool:
    """Mirror the writer's catalog-driven ``p:bldP/@animBg`` decision."""
    recorded = str(entry.ooxml.get("buildList") or "")
    return recorded.startswith("p:bldP/") and "@animBg=1" in recorded


# ---------------------------------------------------------------------------
# Semantic transition reader
# ---------------------------------------------------------------------------
def _transition_sound(
    node: etree._Element,
    lookup: RelationshipLookup,
    *,
    slide_slug: str,
    assets: list[AssetRef],
) -> dict[str, Any] | None:
    """Read ``p:sndAc`` into the semantic sound contract, copying the asset."""
    sound_action = _child(node, "sndAc")
    if sound_action is None:
        return None
    _only_children(sound_action, {"stSnd", "endSnd"}, "p:sndAc")
    start = _child(sound_action, "stSnd")
    if start is None:
        raise _Unsupported("p:sndAc carries no p:stSnd, so no sound file can be recovered")
    _require_attrs(start, ("loop",), "p:stSnd")
    snd = _child(start, "snd")
    if snd is None:
        raise _Unsupported("p:stSnd carries no p:snd reference")
    rid = snd.get(f"{{{R_NS}}}embed")
    if not rid:
        raise _Unsupported("p:snd has no r:embed relationship, so the audio part is unknown")
    reference = lookup.get(rid)
    if reference is None:
        raise MotionReadError(
            f"slide {slide_slug!r}: transition sound relationship {rid!r} does not exist in the "
            "package, so the sound cannot be preserved"
        )
    if reference.target_mode != "Internal":
        raise MotionReadError(
            f"slide {slide_slug!r}: transition sound {rid!r} is an external relationship; sdpm "
            "does not follow links out of the package during import"
        )
    asset = AssetRef(
        path=f"media/{_asset_name(slide_slug, reference)}",
        blob=reference.blob,
        content_type=reference.content_type,
        relationship_type=reference.relationship_type,
        source_part=reference.source_part,
    )
    assets.append(asset)
    return {
        "src": asset.path,
        "mediaType": reference.content_type,
        "loop": start.get("loop") in {"1", "true"},
    }


def _asset_name(slide_slug: str, reference: RelationshipRef) -> str:
    base = (reference.source_part or reference.target_ref).rsplit("/", 1)[-1]
    safe = _ID_SAFE.sub("-", base).strip("-") or "asset"
    prefix = _slug(slide_slug) or "slide"
    return f"{prefix}-{safe}"


def read_transition(
    node: etree._Element,
    *,
    index: CapabilityIndex,
    slide_slug: str,
    lookup: RelationshipLookup,
    assets: list[AssetRef],
) -> dict[str, Any]:
    """Return the semantic transition for one ``p:transition`` element."""
    reverse = reverse_index(index)
    allowed = ("spd", "advClick", "advTm", f"{{{P14_NS}}}dur")
    attrs = _require_attrs(node, allowed, "p:transition")
    children = [child for child in node if isinstance(child.tag, str)]
    effects = [child for child in children if _local(child) != "sndAc"]
    if len(effects) != 1:
        raise _Unsupported(
            f"p:transition carries {len(effects)} effect elements; exactly one is required"
        )
    effect_node = effects[0]
    tag = _prefixed_tag(effect_node)
    key = (tag, tuple(sorted(_attrs(effect_node).items())))
    entry = reverse.transitions.get(key)
    if entry is None:
        raise _Unsupported(
            f"no catalog entry establishes transition element {tag} with attributes "
            f"{_attrs(effect_node)!r}"
        )
    semantic = entry.semantic.get("transition")
    if not isinstance(semantic, Mapping):
        raise _Unsupported(f"catalog entry {entry.key!r} records no semantic transition")

    spd = attrs.get("spd")
    if spd is not None and spd not in _SPD_VALUES:
        raise _Unsupported(f"p:transition/@spd {spd!r} is not a legacy speed bucket")
    duration = attrs.get(f"{{{P14_NS}}}dur")
    if duration is not None:
        if not duration.isdigit():
            raise _Unsupported(f"p14:dur {duration!r} is not a millisecond value")
        duration_ms: int | None = int(duration)
    elif spd is not None:
        duration_ms = LEGACY_SPEED_MS[spd]
    else:
        recorded = entry.ooxml.get("defaultDurationMs")
        duration_ms = int(recorded) if isinstance(recorded, int) else None

    advance_click = attrs.get("advClick")
    if advance_click is not None and advance_click not in {"0", "1", "true", "false"}:
        raise _Unsupported(f"p:transition/@advClick {advance_click!r} is not a boolean")
    after = attrs.get("advTm")
    if after is not None and not after.isdigit():
        raise _Unsupported(f"p:transition/@advTm {after!r} is not a millisecond value")

    transition: dict[str, Any] = {
        "effect": semantic.get("effect"),
        "parameters": _semantic_parameters(semantic),
        "durationMs": duration_ms,
        "advance": {
            "onClick": advance_click not in {"0", "false"},
            "afterMs": int(after) if after is not None else None,
        },
        "sound": _transition_sound(node, lookup, slide_slug=slide_slug, assets=assets),
    }
    return transition


def _semantic_parameters(semantic: Mapping[str, Any]) -> dict[str, Any]:
    parameters = semantic.get("parameters")
    return dict(parameters) if isinstance(parameters, Mapping) else {}


def _prefixed_tag(node: etree._Element) -> str:
    """Return ``prefix:local`` for one element, using the writer's prefixes."""
    from sdpm.engine.timing.writer import NSMAP

    qname = etree.QName(node)
    for prefix, uri in NSMAP.items():
        if uri == qname.namespace:
            return f"{prefix}:{qname.localname}"
    return f"{{{qname.namespace}}}{qname.localname}"


# ---------------------------------------------------------------------------
# Raw fragment construction
# ---------------------------------------------------------------------------
def _shape_mappings(
    node: etree._Element,
    identities: Mapping[int, ShapeIdentity],
    *,
    slide_slug: str,
) -> dict[str, str]:
    """Map every schema-defined shape reference in a fragment to a logical ID."""
    mappings: dict[str, str] = {}
    for element in node.iter():
        if not isinstance(element.tag, str):
            continue
        spid = element.get("spid")
        if spid is None:
            continue
        if _local(element) not in SPID_OWNERS:
            raise MotionReadError(
                f"slide {slide_slug!r}: p:{_local(element)} carries an spid attribute sdpm does "
                "not know how to remap; replaying it would leave a stale shape reference"
            )
        if not spid.isdigit() or int(spid) not in identities:
            raise MotionReadError(
                f"slide {slide_slug!r}: raw timing references shape {spid!r}, which is not a "
                "shape on this slide, so it can never be remapped on regeneration"
            )
        mappings[spid] = identities[int(spid)].element_id
    return mappings


def build_raw_fragment(
    selection: Selection,
    *,
    kind: str,
    identities: Mapping[int, ShapeIdentity],
    lookup: RelationshipLookup,
    slide_slug: str,
    reasons: Sequence[str],
) -> RawFragment:
    """Return the canonical raw fragment for one unrecognised representation.

    The retained XML is the whole container — the ``mc:AlternateContent`` with
    **every** Choice and Fallback branch when there is one — so a branch sdpm
    cannot read today is still there for a reader that can.
    """
    container = selection.container
    if container is None:
        raise MotionReadError(f"slide {slide_slug!r}: no {kind} content to preserve")
    xml = canonical_xml(container)
    enforce_xml_limits(xml, what=f"slide {slide_slug!r} raw {kind}")
    relationships, missing = lookup.collect(container)
    if missing:
        raise MotionReadError(
            f"slide {slide_slug!r}: raw {kind} references relationships {list(missing)} that the "
            "package does not define; sdpm will not emit a dangling rId"
        )
    external = [ref.rid for ref in relationships if ref.target_mode != "Internal"]
    if external:
        raise MotionReadError(
            f"slide {slide_slug!r}: raw {kind} depends on external relationships {external}; "
            "unsupported-preservation rather than a link sdpm cannot copy (REQ-5.7)"
        )
    media_only: bytes | None = None
    boundary = "notApplicable"
    if kind == "timing":
        timing = selection.node
        if timing is None:
            boundary = "unclassified"
        else:
            try:
                media_only = media_only_timing(timing)
                boundary = "classified"
            except MediaBoundaryError:
                boundary = "unclassified"
    return RawFragment(
        kind=kind,
        xml=xml,
        namespaces=declared_namespaces(container),
        branches=selection.branches,
        shape_mappings=_shape_mappings(container, identities, slide_slug=slide_slug),
        relationships=relationships,
        media_only=media_only,
        media_boundary=boundary,
        reasons=tuple(reasons),
    )


# ---------------------------------------------------------------------------
# Slide entry point
# ---------------------------------------------------------------------------
def read_slide_motion(
    slide_element: etree._Element,
    *,
    slide_slug: str = "",
    part: Any | None = None,
    index: CapabilityIndex | None = None,
) -> SlideMotion:
    """Import one slide's timing and transition.

    ``part`` is the python-pptx slide part, used only to resolve the package
    relationships a fragment or a semantic sound names. Parsing never touches
    the network, a process or a path outside the package.
    """
    index = index or load_capability_index()
    supported = supported_requires(index)
    identities = shape_identities(slide_element)
    lookup = RelationshipLookup(part)
    assets: list[AssetRef] = []
    reasons: list[str] = []

    timing_selection = select_representation(slide_element, "timing", supported=supported)
    transition_selection = select_representation(slide_element, "transition", supported=supported)

    animations: dict[str, Any] | None = None
    raw_timing: RawFragment | None = None
    targets: set[int] = set()
    if timing_selection.container is not None:
        if timing_selection.node is None:
            raw_timing = build_raw_fragment(
                timing_selection, kind="timing", identities=identities, lookup=lookup,
                slide_slug=slide_slug, reasons=[timing_selection.reason],
            )
            reasons.append(timing_selection.reason)
        else:
            enforce_xml_limits(
                canonical_xml(timing_selection.container),
                what=f"slide {slide_slug!r} p:timing",
            )
            reader = _TimingReader(index=index, identities=identities, slide_slug=slide_slug)
            try:
                animations = reader.read(timing_selection.node)
                targets = set(reader.targets)
            except _Unsupported as error:
                animations = None
                reasons.append(error.reason)
                raw_timing = build_raw_fragment(
                    timing_selection, kind="timing", identities=identities, lookup=lookup,
                    slide_slug=slide_slug, reasons=[error.reason],
                )

    transition: dict[str, Any] | None = None
    raw_transition: RawFragment | None = None
    if transition_selection.container is not None:
        if transition_selection.node is None:
            raw_transition = build_raw_fragment(
                transition_selection, kind="transition", identities=identities, lookup=lookup,
                slide_slug=slide_slug, reasons=[transition_selection.reason],
            )
            reasons.append(transition_selection.reason)
        else:
            enforce_xml_limits(
                canonical_xml(transition_selection.container),
                what=f"slide {slide_slug!r} p:transition",
            )
            transition_assets: list[AssetRef] = []
            try:
                transition = read_transition(
                    transition_selection.node, index=index, slide_slug=slide_slug,
                    lookup=lookup, assets=transition_assets,
                )
                assets.extend(transition_assets)
            except _Unsupported as error:
                transition = None
                reasons.append(error.reason)
                raw_transition = build_raw_fragment(
                    transition_selection, kind="transition", identities=identities,
                    lookup=lookup, slide_slug=slide_slug, reasons=[error.reason],
                )

    element_ids = {spid: identities[spid].element_id for spid in sorted(targets)}
    if raw_timing is not None:
        element_ids.update(
            {int(spid): logical for spid, logical in raw_timing.shape_mappings.items()}
        )
    if raw_transition is not None:
        element_ids.update(
            {int(spid): logical for spid, logical in raw_transition.shape_mappings.items()}
        )
    morph_ids = {
        spid: identity.morph_id
        for spid, identity in identities.items()
        if identity.morph_id
    }
    return SlideMotion(
        animations=animations,
        transition=transition,
        raw_timing=raw_timing,
        raw_transition=raw_transition,
        assets=tuple(assets),
        element_ids=element_ids,
        morph_ids=morph_ids,
        reasons=tuple(reasons),
    )


# ---------------------------------------------------------------------------
# Deck switch derivation
# ---------------------------------------------------------------------------
def resolve_import_switches(
    detected: Mapping[str, bool],
    existing: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, bool]]:
    """Return the ``animations``/``transitions`` switches an import writes.

    A **new** import writes each switch from detected content. **Hand-edit
    sync** passes the current ``deck.json`` as ``existing``: an explicit switch
    is preserved exactly as the user set it, and only a missing one is derived
    (REQ-1.2).
    """
    resolved: dict[str, dict[str, bool]] = {}
    for feature in ("animations", "transitions"):
        value = (existing or {}).get(feature)
        explicit = (
            value.get("enabled") if isinstance(value, Mapping) and isinstance(value.get("enabled"), bool) else None
        )
        resolved[feature] = {
            "enabled": bool(explicit) if explicit is not None else bool(detected.get(feature))
        }
    return resolved


# ---------------------------------------------------------------------------
# Projection into slide JSON
# ---------------------------------------------------------------------------
def apply_motion_to_slide_json(
    slide_dict: dict[str, Any],
    motion: SlideMotion,
    *,
    element_targets: Sequence[tuple[int, dict[str, Any]]] = (),
    placeholder_targets: Mapping[int, str] = {},
    raw_references: Mapping[str, Mapping[str, Any]] = {},
) -> None:
    """Write one slide's recovered motion into its JSON dict.

    ``element_targets`` pairs each extracted element dict with the source
    ``spid`` it came from, and ``placeholder_targets`` maps a source ``spid``
    to its ``placeholders`` key, so a logical ID lands on the JSON node that
    actually produces that shape again.

    A logical ``id`` is stamped only on shapes the timing or transition
    actually references, which keeps the JSON of an ordinary non-animated deck
    byte-identical to before (REQ-9.4). ``morphId`` is independent: it is
    restored wherever the source shape carried one, because Morph matching is a
    property of the shape rather than of a timeline.
    """
    by_spid: dict[int, list[dict[str, Any]]] = {}
    for spid, element in element_targets:
        by_spid.setdefault(spid, []).append(element)

    def stamp(spid: int, key: str, value: str) -> bool:
        for element in by_spid.get(spid, ()):
            element[key] = value
            return True
        placeholder_key = placeholder_targets.get(spid)
        if placeholder_key is None:
            return False
        placeholders = slide_dict.get("placeholders")
        if not isinstance(placeholders, dict) or placeholder_key not in placeholders:
            return False
        current = placeholders[placeholder_key]
        if not isinstance(current, dict):
            current = {"text": current}
            placeholders[placeholder_key] = current
        current[key] = value
        return True

    unmapped = [
        f"{logical} (source spid {spid})"
        for spid, logical in motion.element_ids.items()
        if not stamp(spid, "id", logical)
    ]
    if unmapped:
        raise MotionReadError(
            "the imported timing targets shapes that produced no slide JSON node: "
            f"{unmapped}; regeneration could not resolve them, so sdpm refuses to write "
            "animation JSON that points at nothing"
        )
    for spid, morph_id in motion.morph_ids.items():
        stamp(spid, "morphId", morph_id)

    if motion.animations is not None:
        slide_dict["animations"] = motion.animations
    if motion.transition is not None:
        slide_dict["transition"] = motion.transition
    for key, reference in raw_references.items():
        slide_dict[key] = dict(reference)
