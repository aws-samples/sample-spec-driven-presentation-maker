# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""PresentationML ``p:transition`` writer.

A transition describes how its own slide enters, so the writer only ever
touches the destination slide. It is independent from the timing writer: a
transition is removed or written without changing object or media timing
(REQ-1.4), and it is inserted before ``p:timing``/``p:extLst`` so ``p:sld``
child order stays schema-valid.

Representation
--------------
The catalog records, per effect, which of the four strategies PowerPoint uses:

* ``standard`` — a plain ``p:transition`` child such as ``p:fade``.
* ``p14`` / ``p15`` / ``p159`` — an extension element inside
  ``mc:AlternateContent/mc:Choice[@Requires]`` with an ``mc:Fallback`` branch
  that carries the recorded fallback (``p:fade`` for extension transitions,
  the same standard element otherwise).

Millisecond durations live in ``p14:dur``, which is itself an extension
attribute, so a non-default duration on an otherwise standard transition also
needs the ``p14`` Choice. ``mc:Choice/@Requires`` is a list of prefixes, so a
branch that uses two extension namespaces — ``p159:morph`` with a ``p14:dur``,
for instance — declares both (``Requires="p14 p159"``), and every token is
checked against the catalog's supported set individually. The legacy ``spd``
bucket is written in both branches exactly as the native captures show.

Parameter resolution is catalog-driven: the requested ``parameters`` are merged
over the recorded defaults for that effect and matched against the catalog
entries for the same effect. A match whose OOXML form is not established
raises :class:`CapabilityGapError` rather than guessing an extension attribute
value.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from lxml import etree

from sdpm.engine.timing.writer import (
    CapabilityEntry,
    CapabilityGapError,
    CapabilityIndex,
    MotionWriteError,
    element,
    insert_in_schema_order,
    load_capability_index,
    qn,
    refuse_unimplemented,
    remove_alternate_content,
    reparse,
    set_attrs,
    sub,
)

#: Legacy ``p:transition/@spd`` buckets in milliseconds, as recorded by the
#: catalog provenance (``legacySpeedMs``).
LEGACY_SPEED_MS = {"slow": 1000, "med": 750, "fast": 500}

#: Semantic parameter name → OOXML attribute name. Morph's GUI label is
#: "variant"; PowerPoint persists it as ``p159:morph/@option``.
PARAMETER_ALIASES = {"morph": {"variant": "option"}}

#: ``p14:dur`` is itself an extension attribute, so any ``mc:Choice`` that
#: carries a millisecond duration has to require ``p14`` as well as the
#: namespace of the transition element inside it.
DURATION_REQUIRES = "p14"

MORPH_EFFECT = "morph"


class TransitionWriteError(MotionWriteError):
    """Raised when a transition request is invalid or unsupported."""


def remove_transition(slide_element: etree._Element) -> int:
    """Remove every transition representation from the slide; return the count.

    Only an ``mc:AlternateContent`` whose branches carry nothing but
    ``p:transition`` is removed. Deleting a wrapper merely because a transition
    sits somewhere inside it would also throw away any timing or future-version
    content sharing the same wrapper, so a mixed wrapper raises instead.
    """
    return remove_alternate_content(slide_element, "transition", TransitionWriteError)


def _requested_attributes(slug: str, parameters: Mapping[str, Any]) -> dict[str, str]:
    aliases = PARAMETER_ALIASES.get(slug, {})
    attrs: dict[str, str] = {}
    for name, value in parameters.items():
        if value is None:
            continue
        attrs[aliases.get(name, name)] = "1" if value is True else ("0" if value is False else str(value))
    return attrs


def _base_entry(index: CapabilityIndex, slug: str) -> CapabilityEntry | None:
    return index.items.get(f"transition.gallery.{slug}") or index.items.get(
        f"transition.standardElement.{slug}"
    )


def resolve_transition(
    index: CapabilityIndex, transition: Mapping[str, Any], *, slide_slug: str = ""
) -> tuple[CapabilityEntry, dict[str, str]]:
    """Return the catalog entry and OOXML attributes for one transition.

    The requested parameters are merged over the recorded defaults and matched
    against every catalog entry for the same effect, so an unsupported
    direction or variant fails with the supported values instead of producing
    an invalid extension attribute.
    """
    slug = transition.get("effect")
    if not isinstance(slug, str) or not slug:
        raise TransitionWriteError(f"slide {slide_slug!r}: transition.effect is required")
    variants = index.transition_variants(slug)
    if not variants:
        raise TransitionWriteError(
            f"slide {slide_slug!r}: unknown transition effect {slug!r}; supported: "
            f"{', '.join(index.transition_slugs())}"
        )
    parameters = transition.get("parameters") or {}
    if not isinstance(parameters, Mapping):
        raise TransitionWriteError(f"slide {slide_slug!r}: transition.parameters must be an object")

    base = _base_entry(index, slug)
    merged = dict(base.attributes() if base is not None else {})
    merged.update(_requested_attributes(slug, parameters))

    # Deterministic preference: a captured Transitions-gallery tile wins over a
    # standard element that merely shares the name (the "zoom" tile is
    # p14:warp, while ECMA-376 also defines an unused p:zoom).
    ordered = sorted(variants, key=lambda e: (0 if "galleryTile" in e.ooxml else 1, e.key))
    # Selecting and writing are the same attribute set for every entry but one.
    # `p14:wheelReverse` carries "reverse" in its element name, so it is
    # selected with {spokes, reverse} and written with {spokes} alone; matching
    # on `merged` and then writing `merged` would put a `reverse` attribute on
    # an element that has none.
    matches = [entry for entry in ordered if entry.selector_attributes() == merged]
    writable = [entry for entry in matches if entry.writable]
    if writable:
        chosen = writable[0]
        return chosen, (chosen.attributes() if chosen.selects_by_element_name else merged)
    if matches:
        gap = matches[0].gap or "no established OOXML form"
        raise CapabilityGapError(
            matches[0].key, gap, what=f"slide {slide_slug!r}: transition {slug!r} with {merged}"
        )
    supported = sorted(
        {
            _parameter_summary(slug, entry, base)
            for entry in variants
            if entry.writable
        }
    )
    raise TransitionWriteError(
        f"slide {slide_slug!r}: transition {slug!r} does not support parameters {dict(parameters)}; "
        f"supported parameter sets: {'; '.join(supported) or 'none'}"
    )


def _parameter_summary(slug: str, entry: CapabilityEntry, base: CapabilityEntry | None) -> str:
    aliases = {v: k for k, v in PARAMETER_ALIASES.get(slug, {}).items()}
    base_attrs = base.attributes() if base is not None else {}
    # The selector, so the "supported parameter sets" message lists what the
    # caller would have to pass rather than what lands on the element.
    attrs = {
        aliases.get(name, name): value
        for name, value in entry.selector_attributes().items()
        if base_attrs.get(name) != value or name in aliases
    }
    return str(attrs)


def _effective_duration(entry: CapabilityEntry, transition: Mapping[str, Any]) -> tuple[int | None, str | None]:
    """Return ``(p14_dur_ms, spd)`` for one transition."""
    ooxml = entry.ooxml
    speed = ooxml.get("legacySpeed")
    duration = transition.get("durationMs")
    if duration is None:
        return None, speed
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        raise TransitionWriteError(f"transition.durationMs must be a positive number, got {duration!r}")
    duration = int(round(duration))
    default = ooxml.get("defaultDurationMs")
    if duration == default and LEGACY_SPEED_MS.get(str(speed)) == duration:
        # The native capture carries only the legacy bucket for this value.
        return None, speed
    return duration, speed


def _transition_node(
    entry: CapabilityEntry,
    attrs: Mapping[str, str],
    transition: Mapping[str, Any],
    *,
    duration_ms: int | None,
    speed: str | None,
    index: CapabilityIndex,
    branch: str,
) -> etree._Element:
    node = element("p:transition")
    if speed:
        node.set("spd", str(speed))
    if duration_ms is not None and branch == "choice":
        index.require("transition.duration", what="transition duration")
        node.set(qn("p14:dur"), str(duration_ms))
    advance = transition.get("advance") or {}
    if advance.get("onClick") is False:
        index.require("transition.advance.onMouseClick", what="transition advance-on-click")
        node.set("advClick", "0")
    after = advance.get("afterMs")
    if after is not None:
        index.require("transition.advance.afterTime", what="transition advance-after-time")
        if not isinstance(after, (int, float)) or isinstance(after, bool) or after < 0:
            raise TransitionWriteError(
                f"transition.advance.afterMs must be a non-negative number, got {after!r}"
            )
        node.set("advTm", str(int(round(after))))

    strategy = entry.ooxml.get("strategy")
    if branch == "choice" or strategy == "standard":
        tag = entry.ooxml.get("element")
        if not tag:
            raise TransitionWriteError(f"catalog entry {entry.key!r} records no transition element")
        set_attrs(sub(node, tag), attrs)
    else:
        fallback = entry.ooxml.get("fallbackElement") or entry.ooxml.get("element")
        fallback_attrs = attrs if fallback == entry.ooxml.get("element") else {}
        set_attrs(sub(node, fallback), fallback_attrs)
    return node


def _supported_prefixes(index: CapabilityIndex) -> tuple[str, ...]:
    """Return the catalog's supported ``Requires`` prefixes, in catalog order."""
    return tuple(
        str(row.get("requires"))
        for row in index.alternate_content.get("supported", ())
        if row.get("requires")
    )


def _required_prefixes(
    index: CapabilityIndex, entry: CapabilityEntry, *, duration: bool
) -> tuple[str, ...]:
    """Return every namespace prefix the ``mc:Choice`` branch needs.

    ``@Requires`` is a *list* of prefixes (ECMA-376 Part 3), and a branch has
    to declare every extension namespace it uses, not just the one that names
    its element. A Morph Choice that also carries a millisecond duration uses
    ``p159:morph`` and ``p14:dur``, so it requires ``p14 p159``; declaring only
    ``p159`` would leave a reader that understands p159 but not p14 facing an
    attribute it was told nothing about.
    """
    tokens = [token for token in str(entry.ooxml.get("requires") or "").split() if token]
    if duration and DURATION_REQUIRES not in tokens:
        tokens.append(DURATION_REQUIRES)
    order = _supported_prefixes(index)
    return tuple(
        sorted(dict.fromkeys(tokens), key=lambda token: (order.index(token) if token in order else len(order), token))
    )


def _require_supported_prefixes(
    index: CapabilityIndex,
    requires: Sequence[str],
    transition: Mapping[str, Any],
    *,
    slide_slug: str,
) -> None:
    """Check each ``Requires`` token against the catalog's supported set.

    The check is per token, because a branch can need more than one namespace:
    a set-membership test on the joined string would accept any combination the
    catalog never recorded support for.
    """
    supported = set(_supported_prefixes(index))
    missing = [token for token in requires if token not in supported]
    if missing:
        raise TransitionWriteError(
            f"slide {slide_slug!r}: transition {transition.get('effect')!r} needs namespaces "
            f"{list(requires)}, and the catalog's supported set {sorted(supported)} does not "
            f"contain {missing}"
        )


def build_transition(
    transition: Mapping[str, Any],
    *,
    index: CapabilityIndex | None = None,
    slide_slug: str = "",
) -> tuple[etree._Element, dict[str, Any]]:
    """Return the transition element and a report describing what was written."""
    index = index or load_capability_index()
    entry, attrs = resolve_transition(index, transition, slide_slug=slide_slug)
    if transition.get("sound") is not None:
        sound = transition["sound"]
        key = (
            "transition.sound.loopUntilNext"
            if isinstance(sound, Mapping) and sound.get("loop")
            else "transition.sound.effect"
        )
        refuse_unimplemented(
            index,
            key,
            f"slide {slide_slug!r}: transition sound",
            "a transition sound needs an audio part plus a package relationship that this writer "
            "does not create, so the semantic sound would be silently dropped",
        )
    if transition.get("effect") == MORPH_EFFECT:
        index.require("transition.morph.objectMatching", what="Morph object matching")

    duration_ms, speed = _effective_duration(entry, transition)
    requires = _required_prefixes(index, entry, duration=duration_ms is not None)
    needs_alternate = bool(requires)

    report: dict[str, Any] = {
        "effect": transition.get("effect"),
        "catalogKey": entry.key,
        "capabilityLevel": entry.level,
        "strategy": entry.ooxml.get("strategy"),
        "requires": " ".join(requires),
        "requiresTokens": list(requires),
        "attributes": dict(attrs),
        "durationMs": duration_ms,
        "spd": speed,
        "alternateContent": needs_alternate,
    }
    if not needs_alternate:
        node = _transition_node(
            entry, attrs, transition, duration_ms=None, speed=speed, index=index, branch="choice"
        )
        return node, report

    _require_supported_prefixes(index, requires, transition, slide_slug=slide_slug)
    alternate = element("mc:AlternateContent")
    choice = sub(alternate, "mc:Choice", Requires=" ".join(requires))
    choice.append(
        _transition_node(
            entry, attrs, transition, duration_ms=duration_ms, speed=speed, index=index, branch="choice"
        )
    )
    fallback = sub(alternate, "mc:Fallback")
    fallback.append(
        _transition_node(
            entry, attrs, transition, duration_ms=None, speed=speed, index=index, branch="fallback"
        )
    )
    report["fallbackElement"] = entry.ooxml.get("fallbackElement") or entry.ooxml.get("element")
    return alternate, report


def write_slide_transition(
    slide_element: etree._Element,
    transition: Mapping[str, Any] | None,
    *,
    transitions_enabled: bool = True,
    index: CapabilityIndex | None = None,
    slide_slug: str = "",
) -> dict[str, Any]:
    """Write, replace or remove one slide's transition.

    Returns a report with the resolved catalog key, namespace requirement and
    emitted attributes. Object and media timing are never touched.
    """
    if not transitions_enabled or transition is None:
        return {"transition": False, "removed": remove_transition(slide_element)}
    if not isinstance(transition, Mapping):
        raise TransitionWriteError(f"slide {slide_slug!r}: transition must be an object")
    node, report = build_transition(transition, index=index, slide_slug=slide_slug)
    report["removed"] = remove_transition(slide_element)
    insert_in_schema_order(slide_element, reparse(node), "transition")
    report["transition"] = True
    return report
