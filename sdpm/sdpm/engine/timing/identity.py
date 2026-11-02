# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Slide-local shape identity, Morph identity, and stable effect IDs.

The builder creates every shape, media object and placeholder first and
registers the resulting root shape node under its logical slide JSON ``id``.
The timing and transition writers then resolve a logical ID to the real
``p:cNvPr/@id`` (``spid``) that PresentationML targets require.

Three identity surfaces are kept apart on purpose:

* ``spid`` — the package-generated numeric shape ID. It is not stable across
  regeneration and is never written into slide JSON.
* logical ``id`` — the slide-local name an animation targets. It is recorded in
  a GUID-keyed ``a:ext`` under ``p:cNvPr`` so import can recover it, and it can
  also be re-derived from :func:`effect_fingerprint` when the extension is
  absent. The fingerprint's ordinal counts identical effects only
  (:func:`effect_identity`), so editing one effect never renumbers the others.
* ``morphId`` — the deck-wide Morph correspondence name. It uses Microsoft's
  documented ``!!`` Selection Pane convention proven by the Task 1 Morph spike
  (``scripts/animation_catalog/morph_probe.py``) and therefore owns
  ``p:cNvPr/@name``. Accessibility text (``@title``/``@descr``) is never
  touched.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from lxml import etree

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
SDPM_NS = "https://sdpm.dev/2026/identity"

#: GUID-keyed extension slot that carries the recoverable logical element ID.
#: PowerPoint round-trips unknown ``a:ext`` payloads keyed by a GUID URI; the
#: deterministic fingerprint below is the documented fallback when it does not.
SDPM_IDENTITY_EXT_URI = "{3D7E9B1A-6C42-4E58-9D9F-1C0A5B7E24F6}"

#: Microsoft's documented forced-Morph Selection Pane prefix.
MORPH_NAME_PREFIX = "!!"
MORPH_NAME_NAMESPACE = "sdpm-morph-"


class IdentityError(ValueError):
    """Raised when slide-local identity is duplicated or unusable."""


class TargetResolutionError(ValueError):
    """Raised when an animation target cannot be resolved to one shape."""


def morph_shape_name(morph_id: str) -> str:
    """Return the ``!!`` Selection Pane name PowerPoint matches on."""
    if not isinstance(morph_id, str) or not morph_id.strip():
        raise IdentityError("morphId must be a non-empty string")
    if morph_id.startswith(MORPH_NAME_PREFIX):
        raise IdentityError(f"morphId {morph_id!r} must not include PowerPoint's {MORPH_NAME_PREFIX} prefix")
    return f"{MORPH_NAME_PREFIX}{MORPH_NAME_NAMESPACE}{morph_id}"


def morph_id_from_shape_name(name: str | None) -> str | None:
    """Recover a ``morphId`` from a shape name, or return None."""
    prefix = f"{MORPH_NAME_PREFIX}{MORPH_NAME_NAMESPACE}"
    if isinstance(name, str) and name.startswith(prefix) and len(name) > len(prefix):
        return name[len(prefix):]
    return None


def effect_identity(*, sequence: str, target: str, effect: Mapping[str, Any]) -> str:
    """Return the position-independent identity of one animation effect.

    Two effects belong to the same **identical-effect group** when they are the
    same normalized effect (preset or behavior types) on the same logical
    target in the same sequence. The identity deliberately excludes the array
    index, the start trigger and the timing values, so it answers only one
    question: is this effect indistinguishable from that one?
    """
    preset = effect.get("preset")
    behaviors = effect.get("behaviors")
    normalized: dict[str, Any] = {"sequence": sequence, "target": target}
    if isinstance(preset, Mapping):
        options = preset.get("options")
        normalized["preset"] = {
            "category": preset.get("category"),
            "effect": preset.get("effect"),
            # The chosen Effect Options value is part of what makes two effects
            # the same effect: Fly In from the right and Fly In from the bottom
            # are different animations on the same tile, and an id derived
            # without the option would collide for the two.
            "options": dict(sorted(options.items())) if isinstance(options, Mapping) else None,
        }
    if isinstance(behaviors, Sequence) and not isinstance(behaviors, (str, bytes)):
        normalized["behaviors"] = [
            behavior.get("type") if isinstance(behavior, Mapping) else None for behavior in behaviors
        ]
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def effect_fingerprint(
    *,
    sequence: str,
    target: str,
    effect: Mapping[str, Any],
    ordinal: int,
) -> str:
    """Return the deterministic stable ID for one animation effect.

    The fingerprint covers the sequence kind, the logical target, the
    normalized effect (:func:`effect_identity`) and the ordinal among
    identical effects, exactly as the design documents. It is used when a
    package carries no sdpm identity extension, so JSON → PPTX → JSON keeps
    comparable effect IDs.

    ``ordinal`` counts **within the identical-effect group**, not within the
    sequence: it is how many indistinguishable effects precede this one. That
    is what keeps the IDs stable under editing. Inserting a *different* effect
    earlier in the timeline leaves every following ID untouched, because no
    group it belongs to grew; adding a *duplicate* of an existing effect
    changes exactly one ID, the duplicate's own.
    """
    payload = json.dumps(
        {
            "identity": effect_identity(sequence=sequence, target=target, effect=effect),
            "ordinal": int(ordinal),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"fx-{digest}"


class EffectIdAllocator:
    """Hands out stable effect IDs, counting identical-effect ordinals.

    One allocator covers one slide. Every effect the writer places is counted,
    whether or not it carries an explicit ``id``, because the ordinal is a
    property of the timeline: the import side derives it by scanning the same
    effects in the same order.
    """

    def __init__(self) -> None:
        self._ordinals: dict[str, int] = {}

    def ordinal(self, *, sequence: str, target: str, effect: Mapping[str, Any]) -> int:
        """Return and consume this effect's ordinal within its identical group."""
        identity = effect_identity(sequence=sequence, target=target, effect=effect)
        ordinal = self._ordinals.get(identity, 0)
        self._ordinals[identity] = ordinal + 1
        return ordinal

    def allocate(self, *, sequence: str, target: str, effect: Mapping[str, Any]) -> str:
        """Return the effect's explicit ``id``, or its deterministic fallback."""
        ordinal = self.ordinal(sequence=sequence, target=target, effect=effect)
        explicit = effect.get("id")
        if isinstance(explicit, str) and explicit:
            return explicit
        return effect_fingerprint(sequence=sequence, target=target, effect=effect, ordinal=ordinal)


def _qn(prefixed: str) -> str:
    prefix, _, local = prefixed.partition(":")
    return "{%s}%s" % ({"a": A_NS, "p": P_NS, "sdpm": SDPM_NS}[prefix], local)


def _own_cNvPr(node: etree._Element) -> etree._Element | None:
    """Return the non-visual properties element owned by a root shape node."""
    for candidate in node.iter(_qn("p:cNvPr")):
        return candidate
    return None


def write_identity_extension(node: etree._Element, logical_id: str, morph_id: str | None = None) -> None:
    """Record the logical element ID in non-accessibility shape metadata.

    ``p:cNvPr/@title`` and ``@descr`` carry user accessibility text and are left
    untouched. The identity lands in a GUID-keyed ``a:extLst/a:ext`` instead,
    which is also where a future PowerPoint version is expected to preserve it.
    """
    props = _own_cNvPr(node)
    if props is None:
        raise IdentityError(f"shape node {etree.QName(node).localname!r} has no p:cNvPr to carry identity")
    ext_lst = props.find(_qn("a:extLst"))
    if ext_lst is None:
        ext_lst = etree.SubElement(props, _qn("a:extLst"))
    for existing in ext_lst.findall(_qn("a:ext")):
        if existing.get("uri") == SDPM_IDENTITY_EXT_URI:
            ext_lst.remove(existing)
    ext = etree.SubElement(ext_lst, _qn("a:ext"))
    ext.set("uri", SDPM_IDENTITY_EXT_URI)
    identity = etree.SubElement(ext, _qn("sdpm:identity"), nsmap={"sdpm": SDPM_NS})
    identity.set("element", logical_id)
    if morph_id is not None:
        identity.set("morph", morph_id)


def read_identity_extension(node: etree._Element) -> dict[str, str]:
    """Return the recorded ``{"element": ..., "morph": ...}`` identity, if any."""
    props = _own_cNvPr(node)
    if props is None:
        return {}
    for ext in props.iterfind(f"{_qn('a:extLst')}/{_qn('a:ext')}"):
        if ext.get("uri") != SDPM_IDENTITY_EXT_URI:
            continue
        identity = ext.find(_qn("sdpm:identity"))
        if identity is not None:
            return {key: value for key, value in identity.attrib.items() if isinstance(value, str)}
    return {}


@dataclass(frozen=True)
class ShapeTarget:
    """One resolved logical target: a primary shape plus any extra shapes."""

    logical_id: str
    spid: int
    extra_spids: tuple[int, ...] = ()
    kind: str = "element"
    source_path: str = ""
    morph_id: str | None = None
    removed: bool = False

    @property
    def spids(self) -> tuple[int, ...]:
        """Every shape the logical element produced, primary first."""
        return (self.spid, *self.extra_spids)


@dataclass
class ShapeIdentityRegistry:
    """Logical slide IDs → real shape IDs for one generated slide.

    ``register`` is called once per include/override-expanded element and once
    per filled placeholder, in document order. When one element builder creates
    several shapes, the **primary target rule** applies: the first root shape
    node the builder appended to ``p:spTree`` is the animation target, and the
    remaining nodes are recorded as extra shapes of the same logical element.
    """

    slide_slug: str = ""
    write_metadata: bool = True
    _targets: dict[str, ShapeTarget] = field(default_factory=dict)
    _morph_names: dict[str, str] = field(default_factory=dict)
    _nodes: dict[str, tuple[etree._Element, ...]] = field(default_factory=dict)

    # -- registration -----------------------------------------------------
    def register(
        self,
        logical_id: str | None,
        nodes: Iterable[etree._Element],
        *,
        kind: str = "element",
        source_path: str = "",
        morph_id: str | None = None,
    ) -> ShapeTarget | None:
        """Register the shapes one logical element created.

        Returns None when the element carries no logical ID (the common case
        for decks that do not animate). Raises :class:`IdentityError` on a
        duplicate logical ID or duplicate ``morphId`` within the slide.
        """
        root_nodes = tuple(nodes)
        if morph_id is not None:
            self._register_morph(morph_id, root_nodes, source_path)
        if logical_id is None:
            return None
        if logical_id in self._targets:
            previous = self._targets[logical_id]
            raise IdentityError(
                f"slide {self.slide_slug!r}: duplicate element id {logical_id!r} after include/override "
                f"expansion ({previous.source_path or 'unknown'} and {source_path or 'unknown'})"
            )
        if not root_nodes:
            target = ShapeTarget(logical_id, 0, kind=kind, source_path=source_path,
                                 morph_id=morph_id, removed=True)
            self._targets[logical_id] = target
            self._nodes[logical_id] = ()
            return target

        spids = [self._spid(node, logical_id) for node in root_nodes]
        target = ShapeTarget(
            logical_id,
            spids[0],
            tuple(spids[1:]),
            kind=kind,
            source_path=source_path,
            morph_id=morph_id,
        )
        self._targets[logical_id] = target
        self._nodes[logical_id] = root_nodes
        if self.write_metadata:
            write_identity_extension(root_nodes[0], logical_id, morph_id)
        return target

    def _register_morph(self, morph_id: str, nodes: tuple[etree._Element, ...], source_path: str) -> None:
        name = morph_shape_name(morph_id)
        if name in self._morph_names:
            raise IdentityError(
                f"slide {self.slide_slug!r}: duplicate morphId {morph_id!r} on one slide "
                f"({self._morph_names[name]} and {source_path or 'unknown'}); PowerPoint object "
                "correspondence would be ambiguous"
            )
        self._morph_names[name] = source_path or "unknown"
        if nodes and self.write_metadata:
            props = _own_cNvPr(nodes[0])
            if props is not None:
                props.set("name", name)

    def mark_removed(self, node: etree._Element) -> None:
        """Record that a registered shape was removed from the slide."""
        for logical_id, nodes in self._nodes.items():
            if any(candidate is node for candidate in nodes):
                target = self._targets[logical_id]
                self._targets[logical_id] = ShapeTarget(
                    target.logical_id, target.spid, target.extra_spids, kind=target.kind,
                    source_path=target.source_path, morph_id=target.morph_id, removed=True,
                )
                return

    # -- resolution -------------------------------------------------------
    def resolve(self, logical_id: str, *, context: str = "") -> int:
        """Return the primary ``spid`` for a logical element ID."""
        return self.target(logical_id, context=context).spid

    def target(self, logical_id: str, *, context: str = "") -> ShapeTarget:
        """Return the resolved target record for a logical element ID."""
        where = f" ({context})" if context else ""
        target = self._targets.get(logical_id)
        if target is None:
            known = ", ".join(sorted(self._targets)) or "none"
            raise TargetResolutionError(
                f"slide {self.slide_slug!r}: unknown animation target {logical_id!r}{where}; "
                f"known element ids: {known}"
            )
        if target.removed or self._detached(logical_id):
            raise TargetResolutionError(
                f"slide {self.slide_slug!r}: animation target {logical_id!r}{where} produced no shape "
                "(empty placeholder removed or element skipped)"
            )
        return target

    def _detached(self, logical_id: str) -> bool:
        """True when the registered shape is no longer in the slide tree."""
        nodes = self._nodes.get(logical_id) or ()
        return any(node.getparent() is None for node in nodes)

    def morph_names(self) -> dict[str, str]:
        """Return the slide's ``!!`` Morph names mapped to their JSON path."""
        return dict(self._morph_names)

    def ids(self) -> tuple[str, ...]:
        """Return the registered logical IDs in registration order."""
        return tuple(self._targets)

    def __contains__(self, logical_id: object) -> bool:
        return logical_id in self._targets

    def __len__(self) -> int:
        return len(self._targets)

    # -- helpers ----------------------------------------------------------
    def _spid(self, node: etree._Element, logical_id: str) -> int:
        props = _own_cNvPr(node)
        raw = props.get("id") if props is not None else None
        if raw is None or not raw.isdigit():
            raise IdentityError(
                f"slide {self.slide_slug!r}: element {logical_id!r} produced a shape without a numeric "
                "p:cNvPr/@id, so no animation target can reference it"
            )
        return int(raw)
