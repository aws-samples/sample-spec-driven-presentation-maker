# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""PresentationML ``p:timing`` writer driven by the generated capability catalog.

The writer runs once per slide, after every shape, placeholder, note and media
object exists and after empty placeholders have been removed (REQ-6.1). It is
the only component that creates ``p:timing``; it never calls python-pptx's
``CT_Slide.get_or_add_childTnLst``, which deletes any existing timing tree.

Capability gating
-----------------
Every value the writer emits comes from
``sdpm/references/catalogs/powerpoint-animation-catalog.json``. For each
feature a slide asks for, the writer looks up the catalog entry that owns it
and refuses to write anything whose OOXML form the catalog marks as unresolved
(``ooxml.gap`` / ``ooxml.requiresCapture``). Refusal is a
:class:`CapabilityGapError` naming the catalog key and the recorded gap, so a
missing PowerPoint read-back can never become a silent approximation.

The gate covers behavior *payloads* as well as element names. The gallery
capture recorded which behavior children PowerPoint wrote for each tile, not
the coordinates, colours or formulas inside them. A preset whose children the
catalog's ``behaviorPayloads`` table does not fully establish raises
:class:`BehaviorPayloadGapError`; the writer never emits a behavior node whose
payload it had to leave out. :func:`refuse_unimplemented` keeps that refusal in
place for features that also need writer support sdpm does not have (effect
sound relationships, for example), so closing a catalog gap alone cannot turn
them into silent no-ops.

Effect structure
----------------
PowerPoint's main sequence nests three ``p:par`` levels, which this writer
reproduces::

    p:seq(mainSeq)
      p:par  click group   p:cond delay="indefinite"
        p:par  start group p:cond delay="<cumulative ms>"
          p:par  effect    p:cTn presetID/presetClass/presetSubtype + nodeType

``onPageClick`` opens a new click group, ``afterPrevious`` opens a new start
group inside the current click group, and ``withPrevious`` joins the current
start group. The first effect of a sequence always opens a click group, because
the sequence has to wait for its trigger before anything runs. The effect's
``nodeType`` records the trigger (``clickEffect`` / ``afterEffect`` /
``withEffect``) exactly as the catalog's ``animation.start.*`` entries describe.

Sibling start groups inside one click group are children of a ``p:par``, so
they all begin relative to the same parent time. Sequencing therefore lives in
the start group's own ``p:cond/@delay``, which is the **cumulative absolute
offset** from the click: each ``afterPrevious`` group starts where the previous
group ended, that is the previous group's offset plus the longest
``delay + duration`` any effect in it contributes. A ``delay="0"`` on every
group would make After Previous play at the same time as With Previous.

Durations live on the behavior ``p:cBhvr/p:cTn/@dur`` (the catalog records the
captured child duration per tile); repeat, acceleration, auto-reverse, restart
and after-effect flags live on the effect ``p:cTn``. The visibility ``p:set``
of an entrance/exit preset is a one-millisecond discrete state change with its
own ``p:cTn dur="1" fill="hold"`` and start condition: an entrance shows the
shape at the effect start, and an exit hides it in the last millisecond of the
active duration so the outgoing filter stays visible while it runs. Those
values come from the catalog's ``behaviorPayloads.resolved['p:set']``
``behaviorTiming`` rule rather than from this module.

``p:childTnLst`` is ``CT_TimeNodeList``, which requires at least one child, so
the writer builds the behavior children first and only attaches the list when
it is non-empty. An effect whose behaviors are all the explicit no-op persists
nothing and is rejected instead of producing an empty, schema-invalid list.

Build lists
-----------
``p:bldLst`` keys one build per ``spid`` + ``grpId``, so an effect contributes
at most one ``p:bldP``, ``p:bldGraphic`` or ``p:bldDgm``. Every build value is
looked up by catalog family *and* by the element the catalog records for it:
the paragraph levels and the chart builds share the
``animation.textOptions.level`` family but write different attributes in
different elements, and a value belonging to one must never reach the other.
A paragraph build is written when the slide JSON asks for text options, or
when the preset's own catalog capture records one (``ooxml.buildList``). The
media and motion-path tiles record no build list, so they get none.

Stable effect IDs
-----------------
Slide JSON effect IDs are written into ``p:timing/p:extLst/p:ext`` under a GUID
URI, and :func:`sdpm.engine.timing.identity.effect_fingerprint` is the
documented deterministic fallback for packages where that extension does not
survive a PowerPoint save (REQ-2.5).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from lxml import etree

from sdpm.engine.timing.identity import (
    EffectIdAllocator,
    ShapeIdentityRegistry,
    TargetResolutionError,
)

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
P15_NS = "http://schemas.microsoft.com/office/powerpoint/2012/main"
P159_NS = "http://schemas.microsoft.com/office/powerpoint/2015/09/main"
SDPM_NS = "https://sdpm.dev/2026/identity"

NSMAP = {"a": A_NS, "p": P_NS, "mc": MC_NS, "p14": P14_NS, "p15": P15_NS, "p159": P159_NS}

#: GUID-keyed slot that carries the slide JSON effect IDs.
SDPM_EFFECT_EXT_URI = "{8C4F5A2E-91D3-4B7A-8F1E-2A6D0B93C57D}"

#: ``p:cTn/@accel`` and ``@decel`` are ST_PositiveFixedPercentage: 100% is
#: 100000. The JSON model carries a 0..1 fraction.
PERCENT_SCALE = 100_000

#: ``p:cTn/@repeatCount`` counts in thousandths of a repetition.
REPEAT_SCALE = 1000

#: ``p:tmPct/@val`` is ST_PositivePercentage: 100% is 100000.
TIME_PERCENT_SCALE = 100_000

#: ST_Angle counts 60000ths of a degree.
ANGLE_SCALE = 60_000

#: The nine PowerPoint behavior primitives and the element each one writes.
#: ``none`` is the explicit no-op: the catalog records it as non-persisted, so
#: it contributes no OOXML node.
BEHAVIOR_ELEMENTS: dict[str, str | None] = {
    "motion": "p:animMotion",
    "color": "p:animClr",
    "scale": "p:animScale",
    "rotation": "p:animRot",
    "property": "p:anim",
    "command": "p:cmd",
    "filter": "p:animEffect",
    "set": "p:set",
    "none": None,
}

#: ``p:set`` payload for entrance/exit presets. The attribute-name vocabulary
#: (``style.visibility``) and the ``p:to/p:strVal`` payload are normative
#: ECMA-376; the catalog records the binding under ``behaviorPayloads``.
VISIBILITY_ATTR = "style.visibility"

#: ECMA-376 simple-type allowlists for the attribute values an explicit
#: ``behaviors`` list may carry. ``model.py`` is the frozen Task 2 contract and
#: only validates the behavior *type*, so the writer validates the OOXML
#: vocabulary at its own boundary: an out-of-enum value would otherwise reach
#: the package and make PowerPoint show a repair prompt.
CMD_TYPES = frozenset({"evt", "call", "verb"})  # ST_TLCommandType
MOTION_ORIGINS = frozenset({"parent", "layout"})  # ST_TLAnimateMotionBehaviorOrigin
MOTION_PATH_EDIT_MODES = frozenset({"relative", "fixed"})  # ST_TLAnimateMotionPathEditMode
ANIM_CALC_MODES = frozenset({"discrete", "lin", "fmla"})  # ST_TLAnimateBehaviorCalcMode
ANIM_VALUE_TYPES = frozenset({"str", "num", "clr"})  # ST_TLAnimateBehaviorValueType
ANIM_EFFECT_TRANSITIONS = frozenset({"in", "out", "none"})  # ST_TLAnimateEffectTransition

#: ``p:animClr/p:to/a:srgbClr/@val`` is ST_HexColorRGB.
SRGB_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")

#: The JSON keys that give each behavior element something to animate. A
#: behavior with none of them would be an empty node, so the writer rejects it
#: instead of emitting a payload-free approximation.
BEHAVIOR_REQUIRED_PAYLOAD: dict[str, tuple[tuple[str, ...], str]] = {
    "p:animMotion": (("path",), "a motion path ('path')"),
    "p:animClr": (("to",), "a target colour ('to')"),
    "p:animScale": (("to",), "target scale factors ('to': {'x': .., 'y': ..})"),
    "p:animRot": (("by", "fromValue", "to"), "an angle ('by', 'fromValue' or 'to')"),
    "p:anim": (("by", "fromValue", "to"), "a value ('by', 'fromValue' or 'to')"),
    "p:cmd": (("command",), "a command ('command')"),
    "p:animEffect": (("filter", "transition"), "a filter or transition ('filter'/'transition')"),
    "p:set": (("to",), "a target value ('to')"),
}

#: Behaviors whose ``p:cBhvr/p:attrNameLst`` PowerPoint always fills in.
BEHAVIOR_REQUIRED_ATTR_NAME = frozenset({"p:anim", "p:set"})

#: start.type → ``p:cTn/@nodeType``.
START_NODE_TYPES = {
    "onPageClick": "clickEffect",
    "withPrevious": "withEffect",
    "afterPrevious": "afterEffect",
    "onShapeClick": "clickEffect",
}

CATEGORY_PRESET_CLASS = {
    "entrance": "entr",
    "exit": "exit",
    "emphasis": "emph",
    "media": "mediacall",
    "motionPath": "path",
}

#: The OOXML strategies that map a catalog value onto a slide-transition
#: element. Every other transition entry is a control (duration, advance,
#: sound, Morph object matching) that modifies one rather than choosing one.
TRANSITION_STRATEGIES = frozenset({"standard", "p14", "p15", "p159"})

#: Build-list requests, keyed by the JSON field that asks for them. Each row is
#: ``(catalog family, p:bldLst element, catalogued child path)``.
#:
#: ``animation.textOptions.level`` holds two different controls: the paragraph
#: levels, which write ``p:bldP/@build``, and the chart builds, which write
#: ``p:bldSub/a:bldChart/@bld`` inside ``p:bldGraphic``. The element is
#: therefore part of the lookup, otherwise a paragraph value such as
#: ``byParagraphLevel2`` would resolve inside the same family and its ``build``
#: token (``p``) would be written into ``a:bldChart/@bld``, which is not an
#: ST_AnimationChartBuildType value at all.
TEXT_SEQUENCE_BUILD = ("animation.textOptions.sequence", "p:bldP", None)
TEXT_LEVEL_BUILD = ("animation.textOptions.level", "p:bldP", None)
CHART_BUILD = ("animation.textOptions.level", "p:bldGraphic", "p:bldSub/a:bldChart")
SMARTART_BUILD = ("animation.smartArt.build", "p:bldDgm", None)

#: The build-list form the gallery capture records for a preset that animates
#: the shape together with its text. Only the entrance/emphasis/exit tiles
#: carry it; media and motion-path tiles record no build list at all.
CATALOG_ANIMATE_BACKGROUND = "p:bldP/@animBg=1"


class MotionWriteError(ValueError):
    """Base class for deterministic animation/transition generation errors."""


class CapabilityGapError(MotionWriteError):
    """Raised when the catalog has no established OOXML form for a value."""

    def __init__(
        self,
        key: str,
        gap: str,
        *,
        what: str = "",
        unimplemented: bool = False,
        elements: Sequence[str] = (),
    ) -> None:
        state = "not implemented by the writer" if unimplemented else "semantic-preservation-only"
        remedy = (
            "Implement it against the captured form before enabling it"
            if unimplemented
            else "Capture it with the PowerPoint oracle (Task 8)"
        )
        super().__init__(
            f"{what or key} cannot be generated: catalog entry {key!r} is {state} "
            f"({gap}). {remedy}; sdpm refuses to approximate it."
        )
        self.key = key
        self.gap = gap
        #: The behavior elements whose payload is unresolved, when the gap is
        #: a behavior-payload gap.
        self.elements: tuple[str, ...] = tuple(elements)


class BehaviorPayloadGapError(CapabilityGapError):
    """Raised when a catalog preset's behavior payload was never captured.

    The gallery capture recorded *which* behavior children PowerPoint wrote,
    not the values inside them. Emitting the node without its payload would be
    a silent approximation, so the writer refuses and names every unresolved
    child at once instead of stopping at the first one.
    """

    def __init__(self, key: str, gaps: Sequence[tuple[str, str]], *, what: str = "") -> None:
        super().__init__(
            key,
            "; ".join(f"{name}: {reason}" for name, reason in gaps),
            what=what,
            elements=[name for name, _ in gaps],
        )


class TimingWriteError(MotionWriteError):
    """Raised when a timing request is invalid or unresolvable."""


# ---------------------------------------------------------------------------
# Capability index
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CapabilityEntry:
    """One catalog entry, pre-indexed for O(1) lookup."""

    key: str
    status: str
    level: str
    ooxml: Mapping[str, Any]
    semantic: Mapping[str, Any]
    group: str

    @property
    def gap(self) -> str | None:
        """Return the recorded gap when the OOXML form is not established."""
        if self.status != "accepted":
            return None
        if self.ooxml.get("requiresCapture"):
            return str(self.ooxml.get("gap") or "requiresCapture")
        if "gap" in self.ooxml:
            return str(self.ooxml["gap"])
        return None

    @property
    def writable(self) -> bool:
        """True when the catalog establishes an OOXML form for this entry."""
        return self.status == "accepted" and self.gap is None

    @property
    def unresolved_payloads(self) -> tuple[str, ...]:
        """Return the behavior children whose payload the capture lacks."""
        values = self.ooxml.get("unresolvedPayloads")
        if isinstance(values, (list, tuple)):
            return tuple(str(value) for value in values)
        return ()

    def attributes(self) -> dict[str, str]:
        """Return the recorded OOXML attributes as strings.

        Control entries record ``attributes`` as a list of attribute *names*
        (``["p14:dur"]``); only element mappings record name → value pairs.
        """
        attributes = self.ooxml.get("attributes")
        if not isinstance(attributes, Mapping):
            return {}
        return {str(k): str(v) for k, v in attributes.items()}


class CapabilityIndex:
    """Indexed view over the 1.2 MB capability catalog.

    The catalog is parsed once per process (see :func:`load_capability_index`)
    and reduced to dictionaries, so generating a deck never rescans the
    document and no lookup touches the filesystem after construction.
    """

    def __init__(self, catalog: Mapping[str, Any]) -> None:
        self.baseline = dict(catalog.get("baseline") or {})
        self.alternate_content = dict(catalog.get("alternateContent") or {})
        self.behavior_payloads = dict(catalog.get("behaviorPayloads") or {})
        self.items: dict[str, CapabilityEntry] = {}
        self.candidates: dict[str, CapabilityEntry] = {}
        self._transitions: dict[str, list[CapabilityEntry]] = {}
        self._presets: dict[tuple[str, str], CapabilityEntry] = {}
        self._builds: dict[tuple[str, str, str | None], dict[str, CapabilityEntry]] = {}

        for group, bucket in (("guiItems", self.items), ("candidates", self.candidates)):
            for raw in catalog.get(group) or ():
                entry = CapabilityEntry(
                    key=str(raw.get("key")),
                    status=str(raw.get("status")),
                    level=str(raw.get("capabilityLevel") or ""),
                    ooxml=raw.get("ooxml") or {},
                    semantic=raw.get("semanticJson") or {},
                    group=group,
                )
                bucket[entry.key] = entry
                self._index_semantics(entry)
                self._index_build(entry)

    #: Strategies that map a value onto an animation preset.
    PRESET_STRATEGIES = frozenset({"preset", "animMotion", "behaviorPrimitives"})

    def _index_semantics(self, entry: CapabilityEntry) -> None:
        if entry.status != "accepted":
            return
        strategy = entry.ooxml.get("strategy")
        transition = entry.semantic.get("transition")
        if isinstance(transition, Mapping):
            slug = transition.get("effect")
            if isinstance(slug, str) and strategy in TRANSITION_STRATEGIES:
                self._transitions.setdefault(slug, []).append(entry)
            return
        effect = first_effect(entry.semantic)
        if effect is None:
            return
        preset = effect.get("preset")
        if not isinstance(preset, Mapping):
            return
        if strategy not in self.PRESET_STRATEGIES:
            return
        category, name = preset.get("category"), preset.get("effect")
        if isinstance(category, str) and isinstance(name, str):
            existing = self._presets.get((category, name))
            # A gallery item records the captured template; prefer it over an
            # enum candidate that only corroborates the same preset.
            if existing is None or (not existing.writable and entry.writable):
                self._presets[(category, name)] = entry

    # -- lookups ----------------------------------------------------------
    def _index_build(self, entry: CapabilityEntry) -> None:
        """Index one ``p:bldLst`` value under its family, element and child.

        The element and child are part of the key so a request can only reach
        the values the catalog records for *that* build element: the chart
        builds and the paragraph levels share the ``animation.textOptions.level``
        family but write different attributes in different elements.
        """
        if entry.status != "accepted" or entry.ooxml.get("strategy") != "build":
            return
        family, _, value = entry.key.rpartition(".")
        if not family or not value:
            return
        element_name = entry.ooxml.get("element")
        child = entry.ooxml.get("child")
        token = (
            family,
            str(element_name) if element_name is not None else "",
            str(child) if child is not None else None,
        )
        self._builds.setdefault(token, {})[value] = entry

    def build_entry(
        self, family: str, value: str, *, element: str, child: str | None = None
    ) -> CapabilityEntry | None:
        """Return the catalogued build entry for one requested value."""
        return self._builds.get((family, element, child), {}).get(value)

    def build_values(self, family: str, *, element: str, child: str | None = None) -> tuple[str, ...]:
        """Return every value the catalog records for one build element."""
        return tuple(sorted(self._builds.get((family, element, child), {})))

    def entry(self, key: str) -> CapabilityEntry | None:
        """Return a catalog entry by key (GUI items first, then candidates)."""
        return self.items.get(key) or self.candidates.get(key)

    def require(self, key: str, *, what: str = "") -> CapabilityEntry:
        """Return a writable entry, or raise the deterministic refusal."""
        entry = self.entry(key)
        if entry is None:
            raise TimingWriteError(f"{what or key}: no catalog entry {key!r} exists")
        if entry.status in {"rejected", "outOfScope"}:
            raise TimingWriteError(
                f"{what or key}: catalog entry {key!r} is {entry.status} and cannot be generated"
            )
        gap = entry.gap
        if gap is not None:
            raise CapabilityGapError(key, gap, what=what, elements=entry.unresolved_payloads)
        return entry

    def preset(self, category: str, effect: str) -> CapabilityEntry:
        """Return the writable catalog entry for one animation preset."""
        entry = self.items.get(f"animation.gallery.{category}.{effect}") or self._presets.get(
            (category, effect)
        )
        if entry is None:
            raise TimingWriteError(
                f"unknown {category} animation effect {effect!r}; "
                f"supported: {', '.join(self.preset_names(category)) or 'none'}"
            )
        gap = entry.gap
        if gap is not None:
            raise CapabilityGapError(
                entry.key, gap, what=f"{category} effect {effect!r}",
                elements=entry.unresolved_payloads,
            )
        return entry

    def preset_names(self, category: str) -> tuple[str, ...]:
        """Return the catalog's effect names for one animation category."""
        names = {name for (cat, name) in self._presets if cat == category}
        prefix = f"animation.gallery.{category}."
        names |= {key[len(prefix):] for key in self.items if key.startswith(prefix)}
        return tuple(sorted(names))

    def transition_variants(self, slug: str) -> tuple[CapabilityEntry, ...]:
        """Return every catalog entry that writes one transition effect."""
        return tuple(self._transitions.get(slug, ()))

    def transition_slugs(self) -> tuple[str, ...]:
        """Return every transition effect name the catalog accepts."""
        return tuple(sorted(self._transitions))

    # There is no ``direction_names``. It returned the 45 ``MsoAnimDirection``
    # scripting names that ``preset.variant`` validated against, and the
    # effect-option capture showed that vocabulary to be the wrong one: of the
    # 36 direction labels the galleries actually offer, only 12 had a name in
    # it, while 33 of its 45 names are not reachable from any tile. Directions
    # are per effect — Fly In's ``From Right`` and Stretch's ``From Right`` are
    # different measurements — so they live in each entry's
    # ``ooxml.effectOptions`` and are validated there. See ``effect_options``.


def default_catalog_path() -> Path:
    """Return the packaged capability catalog path."""
    from sdpm.config import REFERENCES_DIR

    return REFERENCES_DIR / "catalogs" / "powerpoint-animation-catalog.json"


@lru_cache(maxsize=4)
def _load_index(path: str) -> CapabilityIndex:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return CapabilityIndex(data)


def load_capability_index(path: str | Path | None = None) -> CapabilityIndex:
    """Return the process-wide capability index for the catalog at ``path``.

    The parse is cached, so repeated slide generation never re-reads or
    re-walks the 1.2 MB catalog document.
    """
    return _load_index(str(path or default_catalog_path()))


def capability_cache_info():
    """Return the index cache statistics (used by the index tests)."""
    return _load_index.cache_info()


def refuse_unimplemented(index: CapabilityIndex, key: str, what: str, reason: str) -> None:
    """Raise :class:`CapabilityGapError` for a value sdpm cannot write at all.

    Catalog gaps close one value at a time in Task 8. A feature that also needs
    writer support sdpm does not have — effect and transition sounds need an
    audio part plus a package relationship — must keep failing after its
    catalog gap closes, otherwise the next catalog regeneration would silently
    turn it into a dropped setting. The refusal is therefore unconditional and
    quotes the catalog's recorded gap when there is one.
    """
    entry = index.entry(key)
    gap = (entry.gap if entry is not None else None) or reason
    raise CapabilityGapError(key, gap, what=what, unimplemented=entry is None or entry.gap is None)


def preset_payload_gaps(
    entry: CapabilityEntry, category: str, payloads: Mapping[str, Any]
) -> tuple[tuple[str, str], ...]:
    """Return ``(element, reason)`` for every behavior child a preset cannot write.

    The catalog's ``behaviorPayloads`` table is the single source of truth for
    which behavior payloads are established. ``p:set`` is resolved only for the
    entrance/exit visibility change, ``p:animEffect`` only when the entry
    carries a captured filter string, and ``p:cmd`` only when it carries a
    captured command; everything listed under ``unresolved`` is a gap by
    definition. An empty result means the writer can reproduce the whole
    preset.
    """
    children = tuple(str(child) for child in entry.ooxml.get("behaviorChildren") or ())
    if not children:
        return (("-", "the capture records no behavior children for this preset"),)
    resolved = payloads.get("resolved") or {}
    unresolved = payloads.get("unresolved") or {}
    gaps: list[tuple[str, str]] = []
    for tag in children:
        if tag not in resolved:
            gaps.append(
                (
                    tag,
                    str(
                        unresolved.get(tag)
                        or f"the catalog's behaviorPayloads table records no payload for {tag}"
                    ),
                )
            )
        elif tag == "p:set" and category not in {"entrance", "exit"}:
            gaps.append(
                (
                    tag,
                    f"only the entrance/exit visibility set is established; the attribute a "
                    f"{category} preset sets is not captured",
                )
            )
        elif tag == "p:animEffect" and not entry.ooxml.get("animEffectFilter"):
            gaps.append((tag, "no captured filter string for this preset"))
        elif tag == "p:cmd" and not entry.ooxml.get("command"):
            gaps.append((tag, "no captured command string for this preset"))
    return tuple(gaps)


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------
def qn(prefixed: str) -> str:
    """Return the Clark-notation name for a prefixed PresentationML tag."""
    prefix, _, local = prefixed.partition(":")
    return "{%s}%s" % (NSMAP[prefix], local)


def element(tag: str, **attrs: Any) -> etree._Element:
    """Create a namespaced element with the full PresentationML nsmap."""
    node = etree.Element(qn(tag), nsmap=NSMAP)
    set_attrs(node, attrs)
    return node


def sub(parent: etree._Element, tag: str, **attrs: Any) -> etree._Element:
    """Create a namespaced child element, skipping None attributes."""
    node = etree.SubElement(parent, qn(tag))
    set_attrs(node, attrs)
    return node


def set_attrs(node: etree._Element, attrs: Mapping[str, Any]) -> etree._Element:
    """Set attributes, skipping None and expanding ``prefix:name`` keys."""
    for name, value in attrs.items():
        if value is None:
            continue
        node.set(qn(name) if ":" in name else name, str(value))
    return node


def first_effect(semantic: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return the first animation effect in a semantic fragment, if any."""
    animations = semantic.get("animations")
    if not isinstance(animations, Mapping):
        return None
    main = animations.get("mainSequence") or []
    if isinstance(main, Sequence) and main and isinstance(main[0], Mapping):
        return main[0]
    for sequence in animations.get("interactiveSequences") or ():
        if isinstance(sequence, Mapping):
            effects = sequence.get("effects") or []
            if effects and isinstance(effects[0], Mapping):
                return effects[0]
    return None


def _subtree_element(node: Mapping[str, Any]) -> etree._Element:
    """Rebuild a measured ``{element, attributes, children}`` subtree verbatim.

    The capture records a behaviour's value as a subtree rather than a scalar
    because it is not always one — ``p:to`` holds a ``p:strVal`` for a
    visibility, an ``a:schemeClr`` for a colour and nothing but ``@x``/``@y``
    for a scale, and a ``p:anim`` has a ``p:tavLst`` of keyframes instead. This
    writes whichever of those was measured, without a reader per shape.
    """
    built = element(str(node["element"]))
    set_attrs(built, {str(k): v for k, v in (node.get("attributes") or {}).items()})
    for child in node.get("children") or ():
        built.append(_subtree_element(child))
    return built


def _is_visibility_set(behavior: Mapping[str, Any]) -> bool:
    """Is this the discrete visibility toggle the duration rule exempts?

    Matched on both the element and the attribute it names, not on the element
    alone: an emphasis ``p:set`` animates a font attribute — Underline sets
    ``style.textDecorationUnderline`` — and those are ordinary behaviours that
    scale. Only ``style.visibility`` measured as exempt.
    """
    if str(behavior.get("element")) != "p:set":
        return False
    return VISIBILITY_ATTR in [str(name) for name in behavior.get("attrNames") or ()]


def _scaled(value: int, scale: Fraction) -> int:
    """Scale a measured millisecond value, rounding halves up.

    The rounding is where this writer's output can differ from PowerPoint's, and
    the difference is bounded and measured rather than assumed. At a fractional
    ratio every product that was not an exact half matched PowerPoint exactly;
    the six that were split both ways — 580 → 652 down and 1324 → 1490 up at the
    same ratio — which is PowerPoint's internal float precision and not a rule
    that can be restated in integers. So a scaled value may be 1 ms from what
    PowerPoint writes, and only on a half. At an effect's measured duration the
    scale is one and the output is the measured integer.
    """
    if scale == 1:
        return value
    exact = Fraction(value) * scale
    return int(exact + Fraction(1, 2))


def _int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TimingWriteError(f"{name} must be a number, got {value!r}")
    return int(round(value))


def _object(value: Any, path: str) -> Mapping[str, Any]:
    """Return a JSON object field as a mapping, or raise a path-aware error.

    ``None`` and an absent field mean "not requested" and become an empty
    mapping. Anything else — a list, a string, a number — is a malformed slide
    JSON field, and the caller must see the JSON path rather than the
    ``AttributeError`` or ``ValueError`` that indexing it would raise.
    """
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TimingWriteError(
            f"{path} must be an object, got {type(value).__name__} {value!r}"
        )
    return value


def media_timing_nodes(slide_element: etree._Element) -> list[etree._Element]:
    """Return copies of every media node already present in the slide timing.

    python-pptx's ``add_movie`` writes ``p:video`` straight into ``p:timing``.
    The writer harvests those nodes (and any ``p:audio``) before replacing the
    tree, so video playback controls survive object-animation generation and
    animation-off builds (REQ-1.4, REQ-6.3).
    """
    nodes: list[etree._Element] = []
    for timing in timing_elements(slide_element):
        for tag in ("p:video", "p:audio"):
            for node in timing.iter(qn(tag)):
                nodes.append(etree.fromstring(etree.tostring(node)))
    return nodes


def timing_elements(slide_element: etree._Element) -> list[etree._Element]:
    """Return every effective timing representation on the slide."""
    found: list[etree._Element] = []
    for child in slide_element:
        local = etree.QName(child).localname
        if local == "timing":
            found.append(child)
        elif local == "AlternateContent":
            found.extend(child.iter(qn("p:timing")))
    return found


def alternate_content_payload(node: etree._Element) -> set[str]:
    """Return the local names an ``mc:AlternateContent`` carries in its branches."""
    return {
        etree.QName(child).localname
        for branch in node
        if etree.QName(branch).localname in {"Choice", "Fallback"}
        for child in branch
        if isinstance(child.tag, str)
    }


def remove_alternate_content(
    slide_element: etree._Element, local_name: str, error: type[MotionWriteError]
) -> int:
    """Remove the slide's ``local_name`` children; return how many went away.

    ``mc:AlternateContent`` is only removed when **every** branch child is a
    ``local_name`` element. Deleting a wrapper because it happens to contain
    one somewhere would throw away the other content in the same wrapper, so a
    mixed wrapper raises instead: the caller cannot replace one representation
    without losing the other, and REQ-6.4 wants that to be a deterministic
    error rather than data loss.
    """
    removed = 0
    for child in list(slide_element):
        local = etree.QName(child).localname
        if local == local_name:
            slide_element.remove(child)
            removed += 1
            continue
        if local != "AlternateContent":
            continue
        payload = alternate_content_payload(child)
        if local_name not in payload:
            continue
        if payload != {local_name}:
            raise error(
                f"mc:AlternateContent wraps {sorted(payload)} in one branch set; sdpm will not "
                f"delete the other content to replace p:{local_name}. Split the wrapper so each "
                "representation has its own mc:AlternateContent."
            )
        slide_element.remove(child)
        removed += 1
    return removed


def remove_timing(slide_element: etree._Element) -> int:
    """Remove every timing representation from the slide; return the count.

    python-pptx issue 954 corrupts a package when a direct ``p:timing`` sits
    beside timing wrapped in ``mc:AlternateContent``; the writer therefore
    always collapses the slide to exactly one representation.
    """
    return remove_alternate_content(slide_element, "timing", TimingWriteError)


_SUCCESSORS = {"transition": ("transition", "timing", "extLst"), "timing": ("timing", "extLst")}


def insert_in_schema_order(slide_element: etree._Element, node: etree._Element, tag: str) -> None:
    """Insert ``node`` respecting ``p:sld`` child order.

    ``p:sld`` is ``cSld, clrMapOvr, transition, timing, extLst``; a transition
    goes before timing and extLst, and timing goes before extLst.
    """
    successors = set(_SUCCESSORS[tag])
    index = len(slide_element)
    for position, child in enumerate(slide_element):
        local = etree.QName(child).localname
        if local in successors:
            index = position
            break
        if local == "AlternateContent" and any(
            etree.QName(found).localname in successors for found in child.iter()
        ):
            index = position
            break
    slide_element.insert(index, node)


def reparse(node: etree._Element) -> etree._Element:
    """Round-trip a built subtree through python-pptx's oxml parser."""
    from pptx.oxml import parse_xml

    return parse_xml(etree.tostring(node))


# ---------------------------------------------------------------------------
# Timing writer
# ---------------------------------------------------------------------------
@dataclass
class _BuildEntry:
    kind: str
    spid: int
    grp_id: int
    attrs: dict[str, str] = field(default_factory=dict)
    child: tuple[str, dict[str, str]] | None = None


class TimingWriter:
    """Build one slide's ``p:timing`` tree from semantic slide JSON."""

    def __init__(
        self,
        registry: ShapeIdentityRegistry,
        *,
        index: CapabilityIndex | None = None,
        slide_slug: str = "",
    ) -> None:
        self.registry = registry
        self._index = index
        self.slide_slug = slide_slug or registry.slide_slug
        self.effect_ids: list[tuple[str, int]] = []
        self.max_ctn_id = 0
        self._next_id = 1
        self._effect_ids = EffectIdAllocator()
        self._builds: list[_BuildEntry] = []
        self._build_seen: set[tuple[str, int, int]] = set()
        self._group_ids: dict[int, int] = {}

    @property
    def index(self) -> CapabilityIndex:
        """Return the capability index, parsing the catalog on first use.

        An ordinary deck has no animations, so :meth:`build` returns before it
        needs a single catalog value. Loading the 1.2 MB document in
        ``__init__`` would charge every non-animated slide for a feature it
        does not use, so the parse is deferred to the first lookup.
        """
        if self._index is None:
            self._index = load_capability_index()
        return self._index

    @property
    def catalog_loaded(self) -> bool:
        """True once a catalog lookup forced the index to be parsed."""
        return self._index is not None

    # -- public ------------------------------------------------------------
    def build(
        self,
        animations: Mapping[str, Any] | None,
        media_nodes: Sequence[etree._Element] = (),
    ) -> etree._Element | None:
        """Return a complete ``p:timing`` element, or None when it would be empty."""
        main = list((animations or {}).get("mainSequence") or [])
        interactive = list((animations or {}).get("interactiveSequences") or [])
        if not main and not interactive and not media_nodes:
            return None

        timing = element("p:timing")
        tn_lst = sub(timing, "p:tnLst")
        root_par = sub(tn_lst, "p:par")
        root_ctn = sub(
            root_par, "p:cTn", id=self._id(), dur="indefinite", restart="never", nodeType="tmRoot"
        )
        root_children = sub(root_ctn, "p:childTnLst")

        if main:
            self._main_sequence(root_children, main)
        for ordinal, sequence in enumerate(interactive):
            self._interactive_sequence(root_children, sequence, ordinal)
        for node in media_nodes:
            root_children.append(node)
            for ctn in node.iter(qn("p:cTn")):
                ctn.set("id", str(self._id()))

        if self._builds:
            timing.append(self._build_list())
        if self.effect_ids:
            timing.append(self._effect_id_extension())
        self.max_ctn_id = self._next_id - 1
        return timing

    # -- sequences ---------------------------------------------------------
    def _main_sequence(self, parent: etree._Element, effects: Sequence[Mapping[str, Any]]) -> None:
        self.index.require("animation.sequence.main", what="main animation sequence")
        seq = sub(parent, "p:seq", concurrent="1", nextAc="seek")
        ctn = sub(seq, "p:cTn", id=self._id(), dur="indefinite", nodeType="mainSeq")
        children = sub(ctn, "p:childTnLst")
        self._effect_groups(children, effects, sequence="mainSequence")
        self._main_cond_lists(seq)

    def _interactive_sequence(
        self, parent: etree._Element, sequence: Mapping[str, Any], ordinal: int
    ) -> None:
        self.index.require("animation.sequence.interactive", what="interactive animation sequence")
        if not isinstance(sequence, Mapping):
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: interactive sequence {ordinal} must be an object"
            )
        sequence_id = sequence.get("id") or f"interactive-{ordinal}"
        path = f"animations.interactiveSequences[{ordinal}]"
        trigger = _object(
            sequence.get("trigger"), f"slide {self.slide_slug!r}: {path}.trigger"
        )
        if trigger.get("type") != "onShapeClick":
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: interactive sequence {sequence_id!r} needs an onShapeClick "
                f"trigger, got {trigger.get('type')!r}"
            )
        self.index.require(
            "animation.timing.triggerTarget", what=f"sequence {sequence_id!r} trigger target"
        )
        trigger_target = trigger.get("target")
        spid = self._resolve(trigger_target, f"interactive sequence {sequence_id!r} trigger")
        delay = _int(trigger.get("delayMs") or 0, f"interactive sequence {sequence_id!r} delayMs")

        seq = sub(parent, "p:seq", concurrent="1", nextAc="seek")
        ctn = sub(
            seq,
            "p:cTn",
            id=self._id(),
            restart="whenNotActive",
            fill="hold",
            # A trigger sequence must not let the click bubble up to the main
            # sequence, otherwise clicking the trigger shape also advances the
            # click-driven timeline.
            evtFilter="cancelBubble",
            nodeType="interactiveSeq",
        )
        self._trigger_cond(sub(ctn, "p:stCondLst"), spid, delay)
        end_sync = sub(ctn, "p:endSync", evt="end", delay=0)
        sub(end_sync, "p:rtn", val="all")
        children = sub(ctn, "p:childTnLst")
        self._effect_groups(
            children,
            sequence.get("effects") or [],
            sequence=f"interactive:{sequence_id}",
            trigger_target=trigger_target if isinstance(trigger_target, str) else None,
        )
        # An interactive sequence re-arms on the same shape click; it has no
        # slide-level previous/next condition, because it is not part of the
        # click-driven main timeline.
        self._trigger_cond(sub(seq, "p:nextCondLst"), spid, delay)

    @staticmethod
    def _trigger_cond(cond_lst: etree._Element, spid: int, delay: int) -> etree._Element:
        """Write the shape-click condition an interactive sequence starts on."""
        cond = sub(cond_lst, "p:cond", evt="onClick", delay=delay)
        tgt = sub(cond, "p:tgtEl")
        sub(tgt, "p:spTgt", spid=spid)
        return cond

    def _main_cond_lists(self, seq: etree._Element) -> None:
        """Write the main sequence's slide-level previous/next conditions."""
        for tag, event in (("p:prevCondLst", "onPrev"), ("p:nextCondLst", "onNext")):
            cond_lst = sub(seq, tag)
            cond = sub(cond_lst, "p:cond", evt=event, delay=0)
            tgt = sub(cond, "p:tgtEl")
            sub(tgt, "p:sldTgt")

    def _effect_groups(
        self,
        parent: etree._Element,
        effects: Sequence[Mapping[str, Any]],
        *,
        sequence: str,
        trigger_target: str | None = None,
    ) -> None:
        """Nest one sequence's effects into click groups and start groups.

        Start groups are siblings of a ``p:par``, so they share a parent begin
        time: ``afterPrevious`` is only sequential because its group carries
        the cumulative offset of everything that already ran in the same click
        group. ``group_span`` is the longest ``delay + duration`` contributed by
        the current group, which is what ``withPrevious`` effects extend.
        """
        interactive = sequence.startswith("interactive:")
        click_children: etree._Element | None = None
        start_children: etree._Element | None = None
        group_start = 0
        group_span = 0
        for ordinal, effect in enumerate(effects):
            if not isinstance(effect, Mapping):
                raise TimingWriteError(
                    f"slide {self.slide_slug!r}: {sequence}[{ordinal}] must be an object"
                )
            label = f"{sequence}[{ordinal}]"
            start = _object(effect.get("start"), f"slide {self.slide_slug!r}: {label}.start")
            kind = start.get("type") or "onPageClick"
            if kind == "none":
                # msoAnimTriggerNone is an effect with no start condition at
                # all. The writer always emits one, so the value is refused
                # explicitly instead of failing on a nodeType lookup.
                refuse_unimplemented(
                    self.index,
                    "animation.start.none",
                    f"slide {self.slide_slug!r}: {label} start 'none'",
                    "an effect with no trigger persists as the absence of a start condition; this "
                    "writer always emits a p:stCondLst, so it cannot represent msoAnimTriggerNone",
                )
            if kind not in START_NODE_TYPES:
                raise TimingWriteError(
                    f"slide {self.slide_slug!r}: {label} has unknown start type {kind!r}; "
                    f"supported: {', '.join(sorted(START_NODE_TYPES))}, none"
                )
            self.index.require(f"animation.start.{kind}", what=f"{label} start {kind!r}")
            if kind == "onShapeClick" and not interactive:
                raise TimingWriteError(
                    f"slide {self.slide_slug!r}: {label} uses onShapeClick; PowerPoint stores a "
                    "shape-click trigger as an interactive sequence, so move it to "
                    "animations.interactiveSequences"
                )
            if kind == "onShapeClick":
                self._require_sequence_trigger(start, trigger_target, label)

            if click_children is None or kind in {"onPageClick", "onShapeClick"}:
                click_children = self._click_group(parent)
                start_children = self._start_group(click_children, 0)
                group_start, group_span = 0, 0
            elif kind == "afterPrevious":
                group_start += group_span
                start_children = self._start_group(click_children, group_start)
                group_span = 0
            span = self._effect(
                start_children,
                effect,
                sequence=sequence,
                ordinal=ordinal,
                node_type=START_NODE_TYPES[kind],
            )
            group_span = max(group_span, span)

    def _require_sequence_trigger(
        self, start: Mapping[str, Any], trigger_target: str | None, label: str
    ) -> None:
        """Require a per-effect shape-click target to be the sequence's own.

        PowerPoint stores one ``p:seq`` per trigger shape: the click condition
        lives on the interactive sequence, and the effects inside it carry no
        target of their own. A second shape in ``start.target`` therefore has
        nowhere to go. Dropping it silently would play the effect on the wrong
        click, so the writer requires the two to agree and tells the author to
        open a second sequence instead.
        """
        target = start.get("target")
        if target is None or target == trigger_target:
            return
        raise TimingWriteError(
            f"slide {self.slide_slug!r}: {label}.start.target {target!r} is not the trigger target "
            f"{trigger_target!r} of its interactive sequence; PowerPoint stores one shape-click "
            "trigger per sequence, so give the effect its own interactive sequence with that "
            "trigger instead of a per-effect target"
        )

    def _click_group(self, parent: etree._Element) -> etree._Element:
        par = sub(parent, "p:par")
        ctn = sub(par, "p:cTn", id=self._id(), fill="hold")
        st_cond = sub(ctn, "p:stCondLst")
        sub(st_cond, "p:cond", delay="indefinite")
        return sub(ctn, "p:childTnLst")

    def _start_group(self, parent: etree._Element, delay: int) -> etree._Element:
        par = sub(parent, "p:par")
        ctn = sub(par, "p:cTn", id=self._id(), fill="hold")
        st_cond = sub(ctn, "p:stCondLst")
        sub(st_cond, "p:cond", delay=delay)
        return sub(ctn, "p:childTnLst")

    # -- one effect --------------------------------------------------------
    def _effect(
        self,
        parent: etree._Element,
        effect: Mapping[str, Any],
        *,
        sequence: str,
        ordinal: int,
        node_type: str,
    ) -> int:
        """Write one effect and return the ``delay + duration`` it occupies."""
        label = f"{sequence}[{ordinal}]"
        target = _object(effect.get("target"), f"slide {self.slide_slug!r}: {label}.target")
        element_id = target.get("element")
        spid = self._resolve(element_id, f"{label} target")
        self.index.require("animation.target.shape", what=f"{label} shape target")
        grp_id = self._grp_id(spid)

        preset = effect.get("preset")
        behaviors = effect.get("behaviors")
        if (preset is None) == (behaviors is None):
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {label} needs exactly one of preset or behaviors"
            )

        timing = _object(effect.get("timing"), f"slide {self.slide_slug!r}: {label}.timing")
        self._refuse_unwritten_timing(timing, label)
        after = _object(effect.get("afterEffect"), f"slide {self.slide_slug!r}: {label}.afterEffect")
        self._refuse_unwritten_after_effect(after, label)
        if effect.get("sound") is not None:
            refuse_unimplemented(
                self.index,
                "animation.sound.effect",
                f"slide {self.slide_slug!r}: {label} effect sound",
                "an effect sound needs an audio part plus a package relationship that this writer "
                "does not create, so the semantic sound would be silently dropped",
            )
        start = _object(effect.get("start"), f"slide {self.slide_slug!r}: {label}.start")
        if start.get("bookmark") is not None:
            refuse_unimplemented(
                self.index,
                "animation.media.bookmarkTrigger",
                f"slide {self.slide_slug!r}: {label}.start.bookmark",
                "a bookmark trigger needs a p14:bmkTgt start condition this writer does not emit, "
                "so the semantic bookmark would be silently dropped",
            )

        entry = self._preset_entry(preset, label) if preset is not None else None
        duration = timing.get("durationMs")
        if duration is None and entry is not None:
            # ``measuredDurationMs`` first: for an entry the GUI capture
            # measured it is the duration PowerPoint itself applied, and it is
            # what the measured behaviour timings belong to.
            #
            # This fallback is load-bearing beyond the behaviours. The value
            # returned from here is how far the effect advances the timeline, so
            # an ``afterPrevious`` group's delay is the sum of what came before
            # it. Without it a slide of "click, then after the previous" wrote a
            # second start group at delay 0 while its first effect ran for
            # 500 ms, and the reader rightly refused the result as a timeline it
            # could not express.
            duration = entry.ooxml.get("measuredDurationMs")
            if duration is None:
                duration = entry.ooxml.get("observedChildDurationMs")
        if duration is not None:
            duration = _int(duration, f"{label}.timing.durationMs")
        delay = _int(start.get("delayMs") or 0, f"{label}.start.delayMs")

        text = _object(effect.get("text"), f"slide {self.slide_slug!r}: {label}.text")
        chart = _object(effect.get("chart"), f"slide {self.slide_slug!r}: {label}.chart")
        smart_art = _object(effect.get("smartArt"), f"slide {self.slide_slug!r}: {label}.smartArt")
        self._validate_build_request(text, chart, smart_art, label)

        par = sub(parent, "p:par")
        ctn_id = self._id()
        attrs: dict[str, Any] = {"id": ctn_id, "fill": "hold", "grpId": grp_id, "nodeType": node_type}
        if entry is not None:
            attrs.update(self._preset_attrs(entry, preset or {}, label))
        attrs.update(self._timing_attrs(timing, label))
        ctn = sub(par, "p:cTn", **attrs)
        st_cond = sub(ctn, "p:stCondLst")
        sub(st_cond, "p:cond", delay=delay)

        self._iterate(ctn, text, label)
        # p:childTnLst is CT_TimeNodeList and needs at least one child, so the
        # behaviors are built detached and only attached when non-empty.
        children = element("p:childTnLst")
        if entry is not None:
            self._preset_behaviors(children, entry, preset or {}, spid, duration, target, label)
        else:
            self._custom_behaviors(children, behaviors or (), spid, duration, target, label)
        if len(children) == 0:
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {label} produced no animation behavior, so its "
                "p:childTnLst would be empty and PowerPoint would reject the package"
            )
        ctn.append(children)

        self._register_builds(spid, grp_id, text, chart, smart_art, entry, label)
        effect_id = self._effect_ids.allocate(
            sequence=sequence, target=str(element_id), effect=effect
        )
        self.effect_ids.append((str(effect_id), ctn_id))
        return delay + (duration or 0)

    def _refuse_unwritten_timing(self, timing: Mapping[str, Any], label: str) -> None:
        """Refuse the timing options this writer has no OOXML form for.

        Rewind, smooth start/end and bounce end are recorded by the catalog but
        the writer emits nothing for them, so the refusal has to be
        unconditional (:func:`refuse_unimplemented`). A plain
        :meth:`CapabilityIndex.require` would start *passing* the moment Task 8
        closes the catalog gap, and the option would then be dropped in silence
        instead of being written.
        """
        for name, key, reason in (
            (
                "rewind",
                "animation.timing.rewind",
                "the p:cTn fill/autoRev combination PowerPoint writes for Rewind when done playing "
                "is not implemented here",
            ),
            (
                "smoothStart",
                "animation.timing.smoothStart",
                "Smooth start is a motion-path acceleration this writer does not emit",
            ),
            (
                "smoothEnd",
                "animation.timing.smoothEnd",
                "Smooth end is a motion-path deceleration this writer does not emit",
            ),
            (
                "bounceEnd",
                "animation.timing.bounceEnd",
                "Bounce end needs the extra synthesised behaviours PowerPoint appends, which this "
                "writer does not build",
            ),
        ):
            if timing.get(name):
                refuse_unimplemented(
                    self.index, key, f"slide {self.slide_slug!r}: {label}.timing.{name}", reason
                )

    def _refuse_unwritten_after_effect(self, after: Mapping[str, Any], label: str) -> None:
        """Refuse every after-animation value except the explicit ``none``.

        ``none`` is the absence of an after-effect and needs no markup. Dim,
        hide, hide-on-next-click and the dim colour all need nodes the capture
        does not contain and the writer does not emit, so they stay refused
        even after their catalog gap closes; Task 8 implements them against the
        captured form.
        """
        kind = after.get("type")
        if kind not in (None, "none"):
            refuse_unimplemented(
                self.index,
                f"animation.afterAnimation.{kind}",
                f"slide {self.slide_slug!r}: {label}.afterEffect.type {kind!r}",
                "the after-animation node PowerPoint writes for this value is not implemented here, "
                "so the requested after-effect would be silently dropped",
            )
        if after.get("color") is not None:
            refuse_unimplemented(
                self.index,
                "animation.afterAnimation.dimColor",
                f"slide {self.slide_slug!r}: {label}.afterEffect.color",
                "the dim colour needs the p:animClr node PowerPoint appends after the effect, which "
                "this writer does not build",
            )

    def _timing_attrs(self, timing: Mapping[str, Any], label: str) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        repeat = timing.get("repeatCount")
        if repeat is not None and _int(repeat, f"{label}.timing.repeatCount") != 1:
            self.index.require("animation.timing.repeatCount", what=f"{label} timing.repeatCount")
            attrs["repeatCount"] = _int(repeat, "repeatCount") * REPEAT_SCALE
        if timing.get("repeatDurationMs") is not None:
            self.index.require(
                "animation.timing.repeatDurationMs", what=f"{label} timing.repeatDurationMs"
            )
            attrs["repeatDur"] = _int(timing["repeatDurationMs"], "repeatDurationMs")
        if timing.get("autoReverse"):
            self.index.require("animation.timing.autoReverse", what=f"{label} timing.autoReverse")
            attrs["autoRev"] = "1"
        for name, attribute, key in (
            ("acceleration", "accel", "animation.timing.acceleration"),
            ("deceleration", "decel", "animation.timing.deceleration"),
        ):
            value = timing.get(name)
            if value:
                self.index.require(key, what=f"{label} timing.{name}")
                attrs[attribute] = int(round(float(value) * PERCENT_SCALE))
        restart = timing.get("restart")
        if restart is not None:
            self.index.require(
                f"animation.timing.restart.{restart}", what=f"{label} timing.restart {restart!r}"
            )
            attrs["restart"] = restart
        return attrs

    def _preset_entry(self, preset: Mapping[str, Any], label: str) -> CapabilityEntry:
        if not isinstance(preset, Mapping):
            raise TimingWriteError(f"slide {self.slide_slug!r}: {label}.preset must be an object")
        category = preset.get("category")
        name = preset.get("effect")
        if not isinstance(category, str) or not isinstance(name, str):
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {label}.preset needs a category and an effect"
            )
        if preset.get("variant") is not None:
            # Only a non-null one fails. ``variant`` named one of the 45
            # ``MsoAnimDirection`` enumerators and was refused for every value,
            # so the catalog's own examples all spelled it ``null`` and any
            # document written against them carries that. A null asked for
            # nothing, and failing it would break those documents to tell them
            # about a field they are not using. A **non-null** one is a real
            # request for a direction, and ignoring it would silently write the
            # tile's default instead — so that is the one that has to stop.
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {label}.preset.variant {preset['variant']!r} is no "
                f"longer a field; write {label}.preset.options instead, which names the setting "
                "as well as the value and is validated against what this effect offers, as in "
                '{"options": {"direction": "fromRight"}}'
            )
        try:
            entry = self.index.preset(category, name)
        except TimingWriteError as error:
            raise TimingWriteError(f"slide {self.slide_slug!r}: {label}: {error}") from error
        options = preset.get("options")
        if options is None:
            return entry
        return self._with_effect_options(entry, options, label)

    def _with_effect_options(
        self, entry: CapabilityEntry, options: Any, label: str
    ) -> CapabilityEntry:
        """Return the entry as if the requested ``Effect Options`` value were applied.

        The chosen value's measured ``presetSubtype`` and behaviours are laid
        over the entry's own, so :meth:`_preset_attrs` and
        :meth:`_preset_behaviors` need to know nothing about options: they read
        the same fields they always did. That is the whole reason the overlay
        is built here rather than threaded through them.

        Both fields are replaced, never one. 9 of the 37 measured groups do not
        move ``presetSubtype`` at all — Spin's ``Clockwise`` and
        ``Counterclockwise`` are both subtype 0 and differ only in the sign of
        ``p:animRot/@by`` — so an overlay that carried only the subtype would
        write one direction for both. And no group moves the subtype alone, so
        the behaviours always differ too.
        """
        if not isinstance(options, Mapping):
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {label}.preset.options must be an object mapping a "
                'setting to a value, as in {"direction": "fromRight"}'
            )
        if not options:
            return entry
        available = entry.ooxml.get("effectOptions")
        if not isinstance(available, Mapping) or not available:
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {label}.preset {entry.key!r} offers no effect "
                f"options, so {sorted(options)} cannot be set; 33 of the 95 gallery effects "
                "carry a setting and the rest expose only the text-unit sequence"
            )
        unknown = sorted(name for name in options if name not in available)
        if unknown:
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {label}.preset.options {unknown} is not a setting of "
                f"{entry.key!r}; it offers {sorted(available)}"
            )
        if len(options) > 1:
            # Each value was measured with the effect's *other* setting left at
            # its default, so the combinations were never applied. Composing
            # two measurements — taking Spin's sign from one and its magnitude
            # from the other — would emit a value PowerPoint was never observed
            # to write, which is the inference this whole capture exists to
            # remove.
            gap = (entry.ooxml.get("effectOptionCombinations") or {}).get("gap")
            raise CapabilityGapError(
                entry.key,
                gap or "the combinations of this effect's settings are not measured",
                what=(
                    f"slide {self.slide_slug!r}: {label}.preset.options {sorted(options)} "
                    "together"
                ),
                unimplemented=False,
            )
        (setting, wanted), = options.items()
        option = available[setting]
        values = option.get("values") or {}
        if not isinstance(wanted, str) or wanted not in values:
            self._refuse_retired_direction(wanted, str(setting), label)
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {label}.preset.options.{setting} {wanted!r} is not a "
                f"measured value of {entry.key!r}'s {option.get('setting', setting)!r}; "
                f"it offers {sorted(values)}"
            )
        measured = values[wanted]
        return self._overlay(entry, measured)

    def _refuse_retired_direction(self, wanted: Any, setting: str, label: str) -> None:
        """Quote the catalog when the asked-for value is a retired scripting name.

        ``preset.variant`` validated against the 45 ``MsoAnimDirection``
        enumerators, and someone migrating to ``options`` will reach for the
        same names. 33 of them are not offered by any gallery tile and the rest
        do not spell the labels that are, so the plain "not a measured value"
        error would leave them guessing why a name that used to be accepted is
        gone. The catalog records the reason on the enumerator's own entry, so
        the refusal quotes it rather than restating it here.
        """
        if setting != "direction" or not isinstance(wanted, str):
            return
        entry = self.index.entry(f"animation.effectOptions.direction.{wanted}")
        if entry is None or entry.gap is None:
            return
        raise CapabilityGapError(
            entry.key,
            entry.gap,
            what=f"slide {self.slide_slug!r}: {label}.preset.options.{setting} {wanted!r}",
            unimplemented=False,
        )

    def _overlay(self, entry: CapabilityEntry, measured: Mapping[str, Any]) -> CapabilityEntry:
        overlay = dict(entry.ooxml)
        overlay["presetSubtype"] = measured.get("presetSubtype")
        overlay["behaviors"] = measured.get("behaviors") or []
        overlay["behaviorChildren"] = measured.get("behaviorChildren") or []
        if measured.get("measuredDurationMs") is not None:
            # The option's own duration basis, not the effect's. 19 of the 95
            # tiles fell outside the gallery capture's plan and have no measured
            # duration, so without this an option on one of them could not be
            # written at any duration but the one it was captured at.
            # ``durationScaling`` is not touched: :meth:`_duration_scale` only
            # consults it when there is no measured duration to scale from, and
            # setting one here is exactly what removes that case.
            overlay["measuredDurationMs"] = measured["measuredDurationMs"]
        if measured.get("iterate"):
            overlay["iterate"] = measured["iterate"]
        return replace(entry, ooxml=overlay)

    def _preset_attrs(
        self, entry: CapabilityEntry, preset: Mapping[str, Any], label: str
    ) -> dict[str, Any]:
        ooxml = entry.ooxml
        preset_class = ooxml.get("presetClass")
        if isinstance(preset_class, list):
            wanted = CATEGORY_PRESET_CLASS.get(str(preset.get("category")))
            if wanted not in preset_class:
                raise TimingWriteError(
                    f"slide {self.slide_slug!r}: {label} category {preset.get('category')!r} does not "
                    f"match catalog preset classes {preset_class}"
                )
            preset_class = wanted
        attrs: dict[str, Any] = {}
        if preset_class:
            attrs["presetClass"] = preset_class
        if ooxml.get("presetId") is not None:
            attrs["presetID"] = ooxml["presetId"]
        if ooxml.get("presetSubtype") is not None:
            attrs["presetSubtype"] = ooxml["presetSubtype"]
        return attrs

    # -- behaviors ---------------------------------------------------------
    def _visibility_timing(self) -> Mapping[str, Any]:
        """Return the catalog's ``p:set`` visibility timing rule."""
        resolved = self.index.behavior_payloads.get("resolved") or {}
        rule = (resolved.get("p:set") or {}).get("behaviorTiming")
        if not isinstance(rule, Mapping):
            raise TimingWriteError(
                "the catalog records no behaviorPayloads.resolved['p:set'].behaviorTiming rule, so "
                "the entrance/exit visibility change has no established timing"
            )
        return rule

    def _preset_behaviors(
        self,
        parent: etree._Element,
        entry: CapabilityEntry,
        preset: Mapping[str, Any],
        spid: int,
        duration: int | None,
        target: Mapping[str, Any],
        label: str,
    ) -> None:
        category = str(preset.get("category"))
        measured = entry.ooxml.get("behaviors")
        if isinstance(measured, (list, tuple)) and measured:
            self._measured_behaviors(parent, entry, measured, spid, duration, target, label)
            return
        gaps = preset_payload_gaps(entry, category, self.index.behavior_payloads)
        if gaps:
            raise BehaviorPayloadGapError(
                entry.key, gaps, what=f"slide {self.slide_slug!r}: {label} {category} preset"
            )
        for tag in entry.ooxml.get("behaviorChildren") or ():
            self._preset_behavior(parent, str(tag), entry, category, spid, duration, target, label)

    def _measured_behaviors(
        self,
        parent: etree._Element,
        entry: CapabilityEntry,
        measured: Sequence[Mapping[str, Any]],
        spid: int,
        duration: int | None,
        target: Mapping[str, Any],
        label: str,
    ) -> None:
        """Write the behaviours PowerPoint wrote for this effect, as it wrote them.

        This is the path for an entry the GUI capture measured, and it replaces
        inference with transcription. The synthesised path below it builds one
        behaviour per distinct element name and fills each payload from the
        general ``BEHAVIOR_PAYLOADS`` rules; that could not express **57 of the
        76 measured effects**, which repeat an element — entrance Bounce has
        eight ``p:animScale`` differing only in duration and delay — and for the
        rest it would be writing a plausible value rather than the measured one.

        Only the timings move, and only by the measured rule: every animated
        behaviour's duration and delay scale in proportion to the effect
        duration, while the visibility ``p:set`` keeps ``dur="1"`` and has its
        delay recomputed rather than scaled. Nothing else is touched, because
        nothing else changed when the duration did — not ``@path``, not ``@by``,
        not ``@filter``, not the count or the order.
        """
        scale = self._duration_scale(entry, duration, label)
        for behavior in measured:
            tag = str(behavior.get("element"))
            node = sub(parent, tag)
            set_attrs(node, {str(k): v for k, v in (behavior.get("attributes") or {}).items()})
            carrier = sub(node, "p:cBhvr")
            set_attrs(carrier, {str(k): v for k, v in (behavior.get("carrier") or {}).items()})
            timing: dict[str, Any] = {"id": self._id()}
            timing.update({str(k): v for k, v in (behavior.get("timingAttributes") or {}).items()})
            dur_ms, delay_ms = self._measured_timing(behavior, scale, duration)
            if dur_ms is not None:
                timing["dur"] = dur_ms
            ctn = sub(carrier, "p:cTn", **timing)
            if delay_ms is not None:
                st_cond = sub(ctn, "p:stCondLst")
                sub(st_cond, "p:cond", delay=delay_ms)
            self._target(carrier, spid, target)
            names = [str(name) for name in behavior.get("attrNames") or ()]
            if names:
                attr_lst = sub(carrier, "p:attrNameLst")
                for name in names:
                    sub(attr_lst, "p:attrName").text = name
            for key in ("to", "from", "by", "tavLst"):
                payload = (behavior.get("values") or {}).get(key)
                if payload is not None:
                    node.append(_subtree_element(payload))

    def _duration_scale(
        self, entry: CapabilityEntry, duration: int | None, label: str
    ) -> Fraction:
        """Return the factor the measured timings scale by. One when they do not.

        ``measuredDurationMs`` is the duration the measured integers belong to.
        An effect the ribbon reports as ``Auto`` has none — its behaviours carry
        ``dur="indefinite"`` — so there is nothing to scale against, and asking
        for a different duration is refused rather than silently ignored.
        """
        measured = entry.ooxml.get("measuredDurationMs")
        if duration is None or measured is None or int(duration) == int(measured):
            if duration is not None and measured is None:
                scaling = entry.ooxml.get("durationScaling") or {}
                if scaling.get("rule") == "notScalable":
                    raise TimingWriteError(
                        f"slide {self.slide_slug!r}: {label} preset {entry.key!r} has no scalable "
                        f"duration ({scaling.get('reason')}), so timing.durationMs "
                        f"{duration} cannot be honoured; omit it to write the measured form"
                    )
            return Fraction(1)
        if int(measured) <= 0:
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {label} preset {entry.key!r} records "
                f"measuredDurationMs {measured!r}, which cannot be scaled from"
            )
        return Fraction(int(duration), int(measured))

    def _measured_timing(
        self, behavior: Mapping[str, Any], scale: Fraction, duration: int | None
    ) -> tuple[int | None, int | None]:
        """Return one behaviour's duration and delay at the requested duration.

        The visibility ``p:set`` is the measured exception and it is exempt in
        both fields. Its duration stayed at 1 ms while every animated behaviour
        doubled, and its delay is **recomputed** from the effect duration rather
        than scaled: Fly Out hides the shape at 499 ms of a 500 ms effect and at
        **999** of a 1000 ms one, where scaling 499 would have given 998.
        """
        dur_ms = behavior.get("durMs")
        delay_ms = behavior.get("delayMs")
        if _is_visibility_set(behavior):
            if delay_ms is not None and int(delay_ms) > 0 and duration is not None:
                delay_ms = max(int(duration) - 1, 0)
            return (None if dur_ms is None else int(dur_ms),
                    None if delay_ms is None else int(delay_ms))
        return (
            None if dur_ms is None else _scaled(int(dur_ms), scale),
            None if delay_ms is None else _scaled(int(delay_ms), scale),
        )

    def _preset_behavior(
        self,
        parent: etree._Element,
        tag: str,
        entry: CapabilityEntry,
        category: str,
        spid: int,
        duration: int | None,
        target: Mapping[str, Any],
        label: str,
    ) -> None:
        """Write one captured behavior child of a gallery preset.

        Only payloads :func:`preset_payload_gaps` already cleared reach this
        method, so every branch has a catalog-established value to write.
        """
        if tag == "p:set":
            rule = self._visibility_timing()
            instantaneous = tuple(entry.ooxml.get("behaviorChildren") or ()) == ("p:set",)
            if category == "entrance" or instantaneous:
                # The captured exit offset exists so the outgoing filter stays
                # visible for the whole effect and the state change finishes
                # with it. A preset whose only behaviour child is the
                # visibility p:set — Disappear — persists no accompanying
                # animation, so there is no active duration to offset from and
                # the state change sits at the effect start, exactly as an
                # entrance Appear does. Inferred from the captured rule's own
                # rationale rather than measured; Task 8 read-back confirms it.
                delay = _int(rule.get("entranceDelayMs", 0), "entranceDelayMs")
            else:
                if duration is None:
                    raise TimingWriteError(
                        f"slide {self.slide_slug!r}: {label} exit preset {entry.key!r} needs an "
                        "explicit timing.durationMs: the captured form hides the shape "
                        f"{abs(_int(rule.get('exitDelayOffsetMs', -1), 'exitDelayOffsetMs'))} ms "
                        "before the end of the active duration, and this entry records no "
                        "observedChildDurationMs to derive it from"
                    )
                delay = max(duration + _int(rule.get("exitDelayOffsetMs", -1), "exitDelayOffsetMs"), 0)
            node = sub(parent, "p:set")
            self._behavior_common(
                node,
                spid,
                rule.get("durMs"),
                target,
                attr_name=VISIBILITY_ATTR,
                fill=rule.get("fill"),
                start_delay=delay,
            )
            to = sub(node, "p:to")
            sub(to, "p:strVal", val="visible" if category == "entrance" else "hidden")
            return
        if tag == "p:animEffect":
            attrs: dict[str, Any] = {"filter": entry.ooxml["animEffectFilter"]}
            if category == "entrance":
                attrs["transition"] = "in"
            elif category == "exit":
                attrs["transition"] = "out"
            node = sub(parent, "p:animEffect", **attrs)
            self._behavior_common(node, spid, duration, target)
            return
        if tag == "p:cmd":
            node = sub(parent, "p:cmd", type="call", cmd=entry.ooxml["command"])
            self._behavior_common(node, spid, duration, target)
            return
        raise TimingWriteError(
            f"slide {self.slide_slug!r}: {label} preset {entry.key!r} records behavior child {tag!r}, "
            "which the writer has no established payload for"
        )

    def _custom_behaviors(
        self,
        parent: etree._Element,
        behaviors: Iterable[Mapping[str, Any]],
        spid: int,
        duration: int | None,
        target: Mapping[str, Any],
        label: str,
    ) -> None:
        wrote = False
        for ordinal, behavior in enumerate(behaviors):
            if not isinstance(behavior, Mapping):
                raise TimingWriteError(
                    f"slide {self.slide_slug!r}: {label}.behaviors[{ordinal}] must be an object"
                )
            kind = behavior.get("type")
            if kind not in BEHAVIOR_ELEMENTS:
                raise TimingWriteError(
                    f"slide {self.slide_slug!r}: {label}.behaviors[{ordinal}] type {kind!r} is not one "
                    f"of {', '.join(sorted(BEHAVIOR_ELEMENTS))}"
                )
            entry = self.index.entry(f"animation.behavior.{kind}")
            if entry is not None and entry.status == "accepted":
                self.index.require(
                    f"animation.behavior.{kind}", what=f"{label}.behaviors[{ordinal}] {kind!r}"
                )
            tag = BEHAVIOR_ELEMENTS[kind]
            if tag is None:
                continue  # explicit no-op: the catalog records no OOXML node
            if kind == "command" and (behavior.get("command") or behavior.get("value") is not None):
                self.index.require(
                    "animation.media.playFromBookmark",
                    what=f"{label}.behaviors[{ordinal}] command payload",
                )
            self._custom_behavior(parent, tag, behavior, spid, duration, target, label, ordinal)
            wrote = True
        if not wrote:
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {label}.behaviors contains only the explicit no-op, which "
                "PowerPoint does not persist. p:childTnLst (CT_TimeNodeList) must not be empty, so "
                "give the effect at least one persisted behavior or drop the effect"
            )

    def _enum(self, value: Any, allowed: frozenset[str], where: str, attribute: str) -> str:
        """Return ``value`` when the ECMA-376 enumeration allows it."""
        text = str(value)
        if text not in allowed:
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {where}.{attribute} {value!r} is not an OOXML value; "
                f"allowed: {', '.join(sorted(allowed))}"
            )
        return text

    def _text(self, value: Any, where: str, attribute: str) -> str:
        """Return a required non-empty string attribute value."""
        if not isinstance(value, str) or not value.strip():
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {where}.{attribute} must be a non-empty string, "
                f"got {value!r}"
            )
        return value

    def _behavior_attrs(self, tag: str, behavior: Mapping[str, Any], where: str) -> dict[str, Any]:
        """Return the validated OOXML attributes for one explicit behavior.

        ``model.py`` is the frozen Task 2 contract and checks only the behavior
        type, so every enumerated attribute value is validated here, at the
        boundary that writes the package. An invalid value is a path-aware
        :class:`TimingWriteError`, never an out-of-enum attribute PowerPoint
        would ask the user to repair.
        """
        attrs: dict[str, Any] = {}
        if tag == "p:animMotion":
            attrs["path"] = self._text(behavior.get("path"), where, "path")
            if behavior.get("pathEditMode") is not None:
                attrs["pathEditMode"] = self._enum(
                    behavior["pathEditMode"], MOTION_PATH_EDIT_MODES, where, "pathEditMode"
                )
            if behavior.get("origin") is not None:
                attrs["origin"] = self._enum(behavior["origin"], MOTION_ORIGINS, where, "origin")
            if behavior.get("rotationAngle") is not None:
                # p:animMotion/@rAng is ST_Angle, counted in 60000ths of a
                # degree like every other DrawingML angle.
                attrs["rAng"] = _int(
                    behavior["rotationAngle"], f"{where}.rotationAngle"
                ) * ANGLE_SCALE
            if behavior.get("pointTypes") is not None:
                attrs["ptsTypes"] = self._text(behavior["pointTypes"], where, "pointTypes")
        elif tag == "p:animRot":
            for name, key in (("by", "by"), ("from", "fromValue"), ("to", "to")):
                if behavior.get(key) is not None:
                    attrs[name] = _int(behavior[key], f"{where}.{key}") * ANGLE_SCALE
        elif tag == "p:anim":
            if behavior.get("calcMode") is not None:
                attrs["calcmode"] = self._enum(
                    behavior["calcMode"], ANIM_CALC_MODES, where, "calcMode"
                )
            if behavior.get("valueType") is not None:
                attrs["valueType"] = self._enum(
                    behavior["valueType"], ANIM_VALUE_TYPES, where, "valueType"
                )
            for name, key in (("by", "by"), ("from", "fromValue"), ("to", "to")):
                if behavior.get(key) is not None:
                    attrs[name] = str(behavior[key])
        elif tag == "p:animEffect":
            if behavior.get("transition") is not None:
                attrs["transition"] = self._enum(
                    behavior["transition"], ANIM_EFFECT_TRANSITIONS, where, "transition"
                )
            if behavior.get("filter") is not None:
                attrs["filter"] = self._text(behavior["filter"], where, "filter")
        elif tag == "p:cmd":
            attrs["type"] = self._enum(
                behavior.get("commandType", "call"), CMD_TYPES, where, "commandType"
            )
            command = self._text(behavior.get("command"), where, "command")
            value = behavior.get("value")
            attrs["cmd"] = (
                f"{command}({value})" if value is not None and "(" not in command else command
            )
        return attrs

    def _require_payload(self, tag: str, behavior: Mapping[str, Any], where: str) -> None:
        """Reject a behavior with nothing to animate."""
        keys, described = BEHAVIOR_REQUIRED_PAYLOAD.get(tag, ((), ""))
        if keys and not any(behavior.get(key) is not None for key in keys):
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {where} of type {behavior.get('type')!r} needs "
                f"{described}; sdpm writes only explicit payloads"
            )
        if tag in BEHAVIOR_REQUIRED_ATTR_NAME:
            self._text(behavior.get("attrName"), where, "attrName")

    def _custom_behavior(
        self,
        parent: etree._Element,
        tag: str,
        behavior: Mapping[str, Any],
        spid: int,
        duration: int | None,
        target: Mapping[str, Any],
        label: str,
        ordinal: int,
    ) -> None:
        where = f"{label}.behaviors[{ordinal}]"
        self._require_payload(tag, behavior, where)
        attrs = self._behavior_attrs(tag, behavior, where)

        node = sub(parent, tag, **attrs)
        self._behavior_common(
            node,
            spid,
            behavior.get("durationMs", duration),
            target,
            attr_name=behavior.get("attrName"),
        )
        payload = behavior.get("to")
        if tag == "p:animClr":
            colour = self._text(payload, where, "to")
            if not SRGB_RE.fullmatch(colour):
                raise TimingWriteError(
                    f"slide {self.slide_slug!r}: {where}.to {payload!r} is not a six-digit sRGB "
                    "hex colour"
                )
            to = sub(node, "p:to")
            sub(to, "a:srgbClr", val=colour.lstrip("#").upper())
        elif tag == "p:animScale":
            if not isinstance(payload, Mapping):
                raise TimingWriteError(
                    f"slide {self.slide_slug!r}: {where}.to must be an object with x and y scale "
                    f"factors, got {payload!r}"
                )
            to = sub(node, "p:to")
            set_attrs(
                to,
                {
                    "x": _int(float(payload.get("x", 1)) * PERCENT_SCALE, f"{where}.to.x"),
                    "y": _int(float(payload.get("y", 1)) * PERCENT_SCALE, f"{where}.to.y"),
                },
            )
        elif tag == "p:set":
            to = sub(node, "p:to")
            sub(to, "p:strVal", val=self._text(payload, where, "to"))

    def _behavior_common(
        self,
        parent: etree._Element,
        spid: int,
        duration: Any,
        target: Mapping[str, Any],
        *,
        attr_name: str | None = None,
        fill: str | None = None,
        start_delay: int | None = None,
    ) -> etree._Element:
        """Write a behavior's ``p:cBhvr`` (timing, target, attribute name).

        ``p:cBhvr`` is ``cTn, tgtEl, attrNameLst`` and the behavior's own
        ``p:cTn`` starts with ``p:stCondLst``, so both are built in that order.
        """
        behavior = sub(parent, "p:cBhvr")
        attrs: dict[str, Any] = {"id": self._id()}
        if duration is not None:
            attrs["dur"] = _int(duration, "durationMs")
        if fill is not None:
            attrs["fill"] = fill
        ctn = sub(behavior, "p:cTn", **attrs)
        if start_delay is not None:
            st_cond = sub(ctn, "p:stCondLst")
            sub(st_cond, "p:cond", delay=start_delay)
        self._target(behavior, spid, target)
        if attr_name:
            attr_lst = sub(behavior, "p:attrNameLst")
            node = sub(attr_lst, "p:attrName")
            node.text = attr_name
        return behavior

    def _target(self, parent: etree._Element, spid: int, target: Mapping[str, Any]) -> None:
        tgt = sub(parent, "p:tgtEl")
        sp_tgt = sub(tgt, "p:spTgt", spid=spid)
        paragraph_range = target.get("paragraphRange")
        if paragraph_range is None:
            return
        self.index.require("animation.target.paragraphRange", what="paragraph-range target")
        if not isinstance(paragraph_range, Mapping):
            raise TimingWriteError("target.paragraphRange must be an object with start and end")
        start = _int(paragraph_range.get("start", 0), "paragraphRange.start")
        end = _int(paragraph_range.get("end", start), "paragraphRange.end")
        tx_el = sub(sp_tgt, "p:txEl")
        sub(tx_el, "p:pRg", st=start, end=end)

    # -- build lists -------------------------------------------------------
    @staticmethod
    def _graphic_builds(chart: Mapping[str, Any], smart_art: Mapping[str, Any]) -> tuple[str, ...]:
        """Return the graphical build kinds this effect asks for."""
        kinds = []
        if chart.get("build") is not None:
            kinds.append("chart")
        if smart_art.get("build") is not None:
            kinds.append("smartArt")
        return tuple(kinds)

    def _validate_build_request(
        self,
        text: Mapping[str, Any],
        chart: Mapping[str, Any],
        smart_art: Mapping[str, Any],
        label: str,
    ) -> None:
        """Reject build requests that would need two builds for one shape.

        ``p:bldLst`` keys a build by ``spid`` plus ``grpId``, so one shape and
        group has exactly one build. A paragraph build (``p:bldP``) and a
        chart/diagram build (``p:bldGraphic``/``p:bldDgm``) for the same pair
        contradict each other, and PowerPoint would read only one of them.
        """
        graphic = self._graphic_builds(chart, smart_art)
        if len(graphic) > 1:
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {label} asks for both a chart and a SmartArt build on "
                "one shape; PowerPoint stores one build per shape and group"
            )
        if graphic and text:
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {label} asks for a {graphic[0]} build and paragraph text "
                "options on one shape; PowerPoint stores one build per shape and group, so split "
                "them into two effects"
            )

    def _build_entry(
        self,
        family: tuple[str, str, str | None],
        value: Any,
        *,
        path: str,
        what: str,
    ) -> CapabilityEntry:
        """Return the catalogued build entry for one requested build value.

        The lookup is keyed by the catalog family **and** by the ``p:bldLst``
        element the value belongs to, so only values the catalog records for
        that element are reachable. Without the element in the key, a paragraph
        level and a chart build would be interchangeable — they share the
        ``animation.textOptions.level`` family — and a request for a chart
        build could write a ``p:bldP`` token such as ``build="p"`` into
        ``a:bldChart/@bld``.
        """
        name, element_name, child = family
        allowed = self.index.build_values(name, element=element_name, child=child)
        if not isinstance(value, str) or value not in allowed:
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {path} {value!r} is not a catalogued "
                f"{element_name} build value; allowed: {', '.join(allowed) or 'none'}"
            )
        entry = self.index.require(f"{name}.{value}", what=what)
        recorded = (entry.ooxml.get("element"), entry.ooxml.get("child"))
        if recorded != (element_name, child):
            # Defence in depth: ``require`` resolves the key again, including
            # the candidate bucket, so the element the catalog records for the
            # entry it returns is re-checked before anything is written.
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {path} {value!r} resolves to catalog entry "
                f"{entry.key!r}, which records {recorded[0]!r} (child {recorded[1]!r}) rather than "
                f"{element_name!r} (child {child!r}); sdpm will not write one build element's value "
                "into another"
            )
        return entry

    def _build_token(self, entry: CapabilityEntry, attribute: str, path: str) -> str:
        """Return the catalogued build token for a graphical build element.

        ``p:bldDgm`` and ``a:bldChart`` carry the build type in one attribute,
        and an empty token is not a valid ST_AnimationBuildType value. A blank
        or differently named recorded attribute is therefore a refusal, not an
        empty attribute PowerPoint would ask the user to repair.
        """
        recorded = entry.ooxml.get("attribute")
        value = entry.ooxml.get("value")
        if recorded != attribute or not isinstance(value, str) or not value.strip():
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {path} resolves to catalog entry {entry.key!r}, which "
                f"records no {attribute!r} build token (attribute={recorded!r}, value={value!r}); "
                "sdpm writes only catalogued build values"
            )
        return value

    def _register_builds(
        self,
        spid: int,
        grp_id: int,
        text: Mapping[str, Any],
        chart: Mapping[str, Any],
        smart_art: Mapping[str, Any],
        entry: CapabilityEntry | None,
        label: str,
    ) -> None:
        if chart.get("build") is not None:
            chart_entry = self._build_entry(
                CHART_BUILD,
                chart["build"],
                path=f"{label}.chart.build",
                what=f"{label} chart build",
            )
            token = self._build_token(chart_entry, "bld", f"{label}.chart.build")
            self._add_build(
                "p:bldGraphic", spid, grp_id, {}, child=("a:bldChart", {"bld": token})
            )
            return
        if smart_art.get("build") is not None:
            diagram_entry = self._build_entry(
                SMARTART_BUILD,
                smart_art["build"],
                path=f"{label}.smartArt.build",
                what=f"{label} SmartArt build",
            )
            token = self._build_token(diagram_entry, "bld", f"{label}.smartArt.build")
            self._add_build("p:bldDgm", spid, grp_id, {"bld": token})
            return

        attrs: dict[str, str] = {}
        if text:
            sequence_entry = level_entry = None
            sequence = text.get("sequence")
            if sequence is not None:
                sequence_entry = self._build_entry(
                    TEXT_SEQUENCE_BUILD,
                    sequence,
                    path=f"{label}.text.sequence",
                    what=f"{label} text sequence",
                )
            level = text.get("level")
            if level is not None:
                level_entry = self._build_entry(
                    TEXT_LEVEL_BUILD,
                    level,
                    path=f"{label}.text.level",
                    what=f"{label} text level {level!r}",
                )
            if sequence_entry is not None and level_entry is not None:
                self._require_agreeing_text_build(
                    sequence_entry, level_entry, str(sequence), str(level), label
                )
            for resolved in (sequence_entry, level_entry):
                if resolved is not None:
                    attrs.update(resolved.attributes())
            unit = text.get("unit")
            if unit is not None:
                self.index.require(
                    f"animation.textOptions.unit.{unit}", what=f"{label} text unit {unit!r}"
                )
            if text.get("reverseOrder"):
                self.index.require(
                    "animation.textOptions.reverseOrder", what=f"{label} text reverse order"
                )
                attrs["rev"] = "1"
            if text.get("interItemDelayPercent") is not None:
                self.index.require(
                    "animation.textOptions.interItemDelayPercent", what=f"{label} inter-item delay"
                )
        if self._animates_background(text, entry):
            self.index.require(
                "animation.textOptions.animateAttachedShape", what=f"{label} animate attached shape"
            )
            attrs["animBg"] = "1"
        if text or attrs:
            self._add_build("p:bldP", spid, grp_id, attrs)

    def _require_agreeing_text_build(
        self,
        sequence_entry: CapabilityEntry,
        level_entry: CapabilityEntry,
        sequence: str,
        level: str,
        label: str,
    ) -> None:
        """Reject a text sequence and level that cannot share one ``p:bldP``.

        One shape and group has one ``p:bldP``, and ``@build`` has one value.
        "As one object" records no ``@build`` at all while a by-paragraph level
        records ``build="p"``, so merging the two would keep whichever the
        writer happened to apply last and drop the other request. A level that
        only *refines* its sequence (``byParagraph`` plus
        ``byParagraphLevel2``, which adds ``@bldLvl``) agrees and is kept.
        """
        sequence_build = sequence_entry.attributes().get("build")
        level_build = level_entry.attributes().get("build")
        if sequence_build == level_build:
            return
        raise TimingWriteError(
            f"slide {self.slide_slug!r}: {label}.text.sequence {sequence!r} and {label}.text.level "
            f"{level!r} contradict each other: one writes p:bldP/@build "
            f"{sequence_build or 'absent'} and the other {level_build or 'absent'}, and a shape has "
            "one paragraph build. Drop one of them or pick a level that belongs to the sequence"
        )

    @staticmethod
    def _animates_background(
        text: Mapping[str, Any], entry: CapabilityEntry | None
    ) -> bool:
        """Decide whether this effect writes ``p:bldP/@animBg="1"``.

        An explicit ``text.animateBackground`` is the author's answer. Without
        one, the only evidence is the catalog's own ``buildList`` record for the
        preset, which the capture holds for the entrance, emphasis and exit
        gallery tiles. Media and motion-path tiles record no build list, and an
        explicit ``behaviors`` list has no catalog entry at all, so neither gets
        an invented paragraph build attached to a shape PowerPoint never
        attached one to.
        """
        requested = text.get("animateBackground")
        if requested is not None:
            return bool(requested)
        if entry is None:
            return False
        recorded = str(entry.ooxml.get("buildList") or "")
        return recorded.startswith("p:bldP/") and "@animBg=1" in recorded

    def _add_build(
        self,
        kind: str,
        spid: int,
        grp_id: int,
        attrs: Mapping[str, str],
        child: tuple[str, dict[str, str]] | None = None,
    ) -> None:
        token = (kind, spid, grp_id)
        if token in self._build_seen:
            return
        self._build_seen.add(token)
        self._builds.append(_BuildEntry(kind, spid, grp_id, dict(attrs), child))

    def _build_list(self) -> etree._Element:
        self.index.require("animation.target.buildList", what="build list")
        bld_lst = element("p:bldLst")
        for entry in self._builds:
            node = sub(bld_lst, entry.kind, spid=entry.spid, grpId=entry.grp_id)
            set_attrs(node, entry.attrs)
            if entry.child is None:
                continue
            tag, attrs = entry.child
            parent = sub(node, "p:bldSub") if entry.kind == "p:bldGraphic" else node
            set_attrs(sub(parent, tag), attrs)
        return bld_lst

    def _iterate(self, ctn: etree._Element, text: Mapping[str, Any], label: str) -> None:
        """Write ``p:iterate`` for a by-word / by-character text animation.

        ``CT_TLIterateData`` is a choice of exactly one ``p:tmAbs`` or
        ``p:tmPct``, so an interval is mandatory. The interval PowerPoint
        writes when the GUI is left at its default is not in the capture, so an
        explicit ``text.interItemDelayPercent`` is required rather than guessed;
        a by-paragraph animation needs no ``p:iterate`` at all.
        """
        unit = text.get("unit")
        percent = text.get("interItemDelayPercent")
        if unit in (None, "byParagraph") and percent is None:
            return
        entry = self.index.require(
            f"animation.textOptions.unit.{unit or 'byParagraph'}", what=f"{label} text unit"
        )
        iterate_type = entry.ooxml.get("type")
        if percent is None:
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {label}.text.interItemDelayPercent is required for text "
                f"unit {unit!r}: p:iterate carries exactly one of p:tmPct or p:tmAbs "
                "(ECMA-376 CT_TLIterateData) and the catalog records no default interval"
            )
        node = sub(ctn, "p:iterate", **({"type": iterate_type} if iterate_type else {}))
        sub(node, "p:tmPct", val=int(round(float(percent) / 100 * TIME_PERCENT_SCALE)))

    # -- effect-ID extension ----------------------------------------------
    def _effect_id_extension(self) -> etree._Element:
        ext_lst = element("p:extLst")
        ext = sub(ext_lst, "p:ext", uri=SDPM_EFFECT_EXT_URI)
        effects = etree.SubElement(ext, "{%s}effects" % SDPM_NS, nsmap={"sdpm": SDPM_NS})
        for effect_id, ctn_id in self.effect_ids:
            node = etree.SubElement(effects, "{%s}effect" % SDPM_NS)
            node.set("id", effect_id)
            node.set("cTn", str(ctn_id))
        return ext_lst

    # -- helpers ----------------------------------------------------------
    def _resolve(self, element_id: Any, context: str) -> int:
        if not isinstance(element_id, str) or not element_id:
            raise TimingWriteError(
                f"slide {self.slide_slug!r}: {context} is missing a target element id"
            )
        try:
            return self.registry.resolve(element_id, context=context)
        except TargetResolutionError as error:
            raise TimingWriteError(str(error)) from error

    def _grp_id(self, spid: int) -> int:
        current = self._group_ids.get(spid, -1) + 1
        self._group_ids[spid] = current
        return current

    def _id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value


def write_slide_timing(
    slide_element: etree._Element,
    slide_def: Mapping[str, Any],
    registry: ShapeIdentityRegistry,
    *,
    animations_enabled: bool = True,
    index: CapabilityIndex | None = None,
) -> dict[str, Any]:
    """Replace the slide's timing with one merged, schema-ordered tree.

    Media timing python-pptx already generated is harvested and merged into the
    new root, so object animations and video coexist without the duplicate
    ``p:timing``/``mc:AlternateContent`` representation of python-pptx issue
    954. When ``animations_enabled`` is false, object-animation branches are
    skipped and only media timing is rebuilt.

    Anything the catalog cannot establish raises before the slide is modified,
    so the report describes only content that was actually written; there is no
    partially approximated timing tree and no warning-only degradation.
    """
    animations = slide_def.get("animations") if animations_enabled else None
    if animations is not None and not isinstance(animations, Mapping):
        raise TimingWriteError(f"slide {slide_def.get('id', '')!r}: animations must be an object")
    media_nodes = media_timing_nodes(slide_element)
    writer = TimingWriter(registry, index=index, slide_slug=str(slide_def.get("id") or ""))
    timing = writer.build(animations, media_nodes)
    removed = remove_timing(slide_element)
    report: dict[str, Any] = {
        "timing": timing is not None,
        "effects": len(writer.effect_ids),
        "mediaNodes": len(media_nodes),
        "removedRepresentations": removed,
        "effectIds": [effect_id for effect_id, _ in writer.effect_ids],
        "maxCTnId": writer.max_ctn_id,
        "catalogLoaded": writer.catalog_loaded,
    }
    if timing is not None:
        insert_in_schema_order(slide_element, reparse(timing), "timing")
    return report


# ---------------------------------------------------------------------------
# Catalog coverage accounting
# ---------------------------------------------------------------------------
#: Every semantic fragment in the catalog animates this logical element id.
CATALOG_TARGET_ID = "catalogTarget"


@dataclass(frozen=True)
class CoverageRecord:
    """What the writers did with one accepted catalog entry."""

    key: str
    group: str
    kind: str
    strategy: str
    level: str
    outcome: str
    has_gap: bool
    gap_key: str = ""
    elements: tuple[str, ...] = ()
    message: str = ""
    #: The catalog marks this entry as outside sdpm's input vocabulary, so no
    #: JSON can ask for it and no capture closes it. Carried here so coverage
    #: accounting can report it apart from the gaps a capture does close: mixed
    #: in, the capture-required total could never reach zero and would stop
    #: measuring progress. The 45 ``MsoAnimDirection`` enumerators are these.
    no_sdpm_input: bool = False
    #: The effect is real but **this** PowerPoint build cannot apply it, so no
    #: capture taken here can record its form. Separate from
    #: ``no_sdpm_input``, because the remedy differs: a capture on a platform
    #: that offers the effect would close this, whereas a direction name can
    #: never identify a ``presetSubtype`` anywhere.
    platform_unavailable: bool = False

    @property
    def generated(self) -> bool:
        """True when the entry produced OOXML."""
        return self.outcome == "generated"

    @property
    def refused(self) -> bool:
        """True when the entry raised a deterministic capability refusal."""
        return self.outcome == "refused"


def catalog_target_registry() -> ShapeIdentityRegistry:
    """Return a registry resolving the catalog's single semantic target.

    The catalog's fragments all animate ``catalogTarget``, so accounting needs
    one detached shape rather than a generated deck. No identity metadata is
    written: the shape exists only to give every fragment an ``spid``.
    """
    tree = etree.fromstring(
        '<p:spTree xmlns:p="%s" xmlns:a="%s"><p:sp><p:nvSpPr>'
        '<p:cNvPr id="2" name="catalog target"/><p:cNvSpPr/><p:nvPr/>'
        "</p:nvSpPr></p:sp></p:spTree>" % (P_NS, A_NS)
    )
    registry = ShapeIdentityRegistry("catalog", write_metadata=False)
    registry.register(CATALOG_TARGET_ID, [tree[0]], source_path="catalog")
    return registry


def catalog_coverage(
    index: CapabilityIndex | None = None, *, catalog: Mapping[str, Any] | None = None
) -> tuple[CoverageRecord, ...]:
    """Write every accepted catalog entry once and record what happened.

    This is the project's single definition of writer coverage. Animation,
    transition and gallery-payload accounting all read these records instead of
    re-deriving the numbers with slightly different filters, so "how many
    mappings are still capture-required" has exactly one answer.

    Each accepted entry's recorded ``semanticJson`` is written with the real
    writer. The outcome is ``generated`` when it produces OOXML and ``refused``
    when it raises :class:`CapabilityGapError`; any other
    :class:`MotionWriteError` is a writer defect and is recorded as ``error``
    rather than quietly counted as either.
    """
    from sdpm.engine.timing.transition import build_transition

    index = index or load_capability_index()
    if catalog is None:
        catalog = json.loads(default_catalog_path().read_text(encoding="utf-8"))
    records: list[CoverageRecord] = []
    for group in ("guiItems", "candidates"):
        for raw in catalog.get(group) or ():
            if raw.get("status") != "accepted":
                continue
            ooxml = raw.get("ooxml") or {}
            semantic = raw.get("semanticJson") or {}
            transition = semantic.get("transition")
            kind = "transition" if isinstance(transition, Mapping) else "animation"
            outcome, gap_key, elements, message = "generated", "", (), ""
            try:
                if kind == "transition":
                    build_transition(transition, index=index, slide_slug="catalog")
                else:
                    TimingWriter(
                        catalog_target_registry(), index=index, slide_slug="catalog"
                    ).build(semantic.get("animations"))
            except CapabilityGapError as error:
                outcome, gap_key, elements = "refused", error.key, error.elements
                message = str(error)
            except MotionWriteError as error:
                outcome, message = "error", str(error)
            records.append(
                CoverageRecord(
                    key=str(raw.get("key")),
                    group=group,
                    kind=kind,
                    strategy=str(ooxml.get("strategy") or ""),
                    level=str(raw.get("capabilityLevel") or ""),
                    outcome=outcome,
                    has_gap=bool(ooxml.get("requiresCapture")) or "gap" in ooxml,
                    gap_key=gap_key,
                    elements=elements,
                    message=message,
                    no_sdpm_input=bool(raw.get("noSdpmInput")),
                    platform_unavailable=bool(raw.get("platformUnavailable")),
                )
            )
    return tuple(records)


def coverage_summary(records: Sequence[CoverageRecord]) -> dict[str, Any]:
    """Return the headline counts for a :func:`catalog_coverage` run."""

    def tally(outcome: str) -> dict[str, int]:
        selected = [record for record in records if record.outcome == outcome]
        return {
            "total": len(selected),
            "guiItems": sum(1 for record in selected if record.group == "guiItems"),
            "candidates": sum(1 for record in selected if record.group == "candidates"),
            "animation": sum(1 for record in selected if record.kind == "animation"),
            "transition": sum(1 for record in selected if record.kind == "transition"),
        }

    return {
        "total": len(records),
        "generated": tally("generated"),
        "refused": tally("refused"),
        "errors": [record.key for record in records if record.outcome == "error"],
        "generatedDespiteGap": [
            record.key for record in records if record.generated and record.has_gap
        ],
        "refusedWithoutGap": [
            record.key for record in records if record.refused and not record.has_gap
        ],
    }
