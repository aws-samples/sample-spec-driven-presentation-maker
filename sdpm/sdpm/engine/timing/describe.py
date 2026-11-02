# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Say what a gallery animation actually does, derived from what was measured.

A caller choosing an effect has a problem the catalog does not solve: the names
are PowerPoint's, and a name does not say what moves. ``Boomerang`` and
``Whip`` both move and resize; ``Teeter`` rotates; ``Stretch`` resizes without
moving. Finding that out by trying each one costs a deck per guess.

Everything needed to answer it is already in the catalog, because the capture
measured each effect's behaviours. This reads them back out. Nothing here is
inferred — if a value is not in the catalog, it is not in the output.

## Two layers, because they have different costs

**Choosing** needs one fact per effect: what it changes. :func:`axis_table`
groups all of them onto 14 rows, about 230 tokens, which is cheap enough to
keep in the authoring guide.

**Verifying** needs the whole thing, and :func:`expression` is one line per
effect — 136 characters at the median. All 209 of them together come to about
9,000 tokens, which is why they are fetched per effect rather than shipped as a
block. The ``describe_effects`` tool is that fetch.

An expression reads as a sum of behaviours::

    entrance.flyIn[direction=fromRight]
      = set(style.visibility: -> visible)@1
        anim(ppt_x: 1+#ppt_w/2 -> #ppt_x)@500
        anim(ppt_y: #ppt_y -> #ppt_y)@500

``@`` is the duration in milliseconds and ``+`` a delay. ``#ppt_w`` is the
shape's own width in PowerPoint's animation variables, so ``1+#ppt_w/2`` is
half a shape-width beyond the right edge of a slide one unit wide — which is
what "from the right" means, and is not something a caller would guess.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

#: ``animated attribute -> what a reader would call it``. The keys are the
#: ``p:attrName`` values the capture recorded, so this maps measurement onto
#: vocabulary rather than inventing a taxonomy.
AXIS_BY_ATTRIBUTE: tuple[tuple[tuple[str, ...], str], ...] = (
    (("ppt_x", "ppt_y"), "moves"),
    (("ppt_w", "ppt_h"), "resizes"),
    (("r",), "rotates"),
    (("style.color", "fillcolor", "stroke.color", "style.fontColor"), "recolours"),
    (("style.opacity",), "fades"),
    (("style.visibility",), "appears/disappears"),
    (
        ("style.fontWeight", "style.fontStyle", "style.textDecorationUnderline"),
        "restyles text",
    ),
)

#: Behaviour elements that mean something on their own, whatever they animate.
AXIS_BY_ELEMENT: tuple[tuple[str, str], ...] = (
    ("animMotion", "follows a path"),
    ("animScale", "resizes"),
)

#: What a ``p:animEffect`` is doing, which depends on what it carries rather
#: than on the element name. Blinds is ``filter="blinds(horizontal)"`` and
#: reveals the shape through a pattern; Transparency is ``filter="image"`` with
#: ``prLst="opacity: 0.5"`` and changes a property. Both are ``p:animEffect``,
#: and calling them the same thing would describe neither.
AXIS_FALLBACK = "wipes/dissolves"


def _local(element: Any) -> str:
    return str(element or "").split(":")[-1]


def axes(behaviors: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return what an effect changes, in a reader's words, from its behaviours.

    ``appears/disappears`` is dropped when anything else is present: every
    entrance and exit effect carries the visibility toggle, so reporting it
    would put one label on all 71 of them and describe none.
    """
    names = {str(n) for b in behaviors for n in (b.get("attrNames") or ())}
    elements = {_local(b.get("element")) for b in behaviors}
    found: list[str] = []
    for keys, label in AXIS_BY_ATTRIBUTE:
        if names & set(keys) and label not in found:
            found.append(label)
    for element, label in AXIS_BY_ELEMENT:
        if element in elements and label not in found:
            found.append(label)
    # A filter that names a pattern and carries no property list reveals the
    # shape through that pattern. `fade` is 28 of the 48 measured ones, so it
    # gets its own word: calling Float In a wipe would be wrong about the
    # majority of effects that use a filter at all.
    for behavior in behaviors:
        attributes = behavior.get("attributes") or {}
        if _local(behavior.get("element")) != "animEffect":
            continue
        if not attributes.get("filter") or attributes.get("prLst"):
            continue
        label = "fades" if str(attributes["filter"]).startswith("fade") else AXIS_FALLBACK
        if label not in found:
            found.append(label)
    if len(found) > 1 and "appears/disappears" in found:
        found.remove("appears/disappears")
    return found or [AXIS_FALLBACK]


def _values(node: Mapping[str, Any]) -> list[str]:
    """Collect the literal values a measured value subtree carries."""
    out: list[str] = []
    attributes = node.get("attributes") or {}
    if "val" in attributes:
        out.append(str(attributes["val"]))
    for name in ("x", "y"):
        if name in attributes:
            out.append(f"{name}={attributes[name]}")
    for child in node.get("children") or ():
        out.extend(_values(child))
    return out


def behaviour_expression(behavior: Mapping[str, Any]) -> str:
    """One behaviour as ``kind(what: from -> to)@duration+delay``."""
    kind = _local(behavior.get("element"))
    attributes = behavior.get("attributes") or {}
    values = behavior.get("values") or {}
    names = ",".join(str(n) for n in (behavior.get("attrNames") or ()))

    if "tavLst" in values:
        frames = []
        for frame in values["tavLst"].get("children") or ():
            found = _values(frame)
            frames.append(found[0] if found else "?")
        body = " -> ".join(frames)
    elif "by" in values:
        body = "by " + ",".join(_values(values["by"]))
    elif "to" in values:
        body = "-> " + ",".join(_values(values["to"]))
    elif "by" in attributes:
        body = f"by {attributes['by']}"
    elif "prLst" in attributes:
        body = str(attributes["prLst"])
    elif "path" in attributes:
        body = f"path {attributes['path']}"
    else:
        body = str(attributes.get("filter") or "")

    label = names or str(attributes.get("filter") or "")
    head = kind + "(" + label + (f": {body}" if body else "") + ")"
    duration = behavior.get("durMs")
    delay = behavior.get("delayMs")
    if duration is not None:
        head += f"@{duration}"
    if delay:
        head += f"+{delay}"
    return head


def expression(behaviors: Iterable[Mapping[str, Any]]) -> str:
    """The whole effect as a sum of its measured behaviours, in document order."""
    return " ".join(behaviour_expression(b) for b in behaviors)


def _entry_rows(index: Any) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for key in sorted(index.items):
        entry = index.items[key]
        if not key.startswith("animation.gallery."):
            continue
        if not (entry.ooxml.get("behaviors") or []):
            continue
        rows.append((key, dict(entry.ooxml)))
    return rows


def axis_table(index: Any) -> list[tuple[str, list[str]]]:
    """Return ``(what it changes, effects)`` rows — the cheap layer.

    Grouped rather than listed per effect, because a caller picking an effect is
    choosing a *kind* of motion first. 14 rows for 83 effects.
    """
    rows = [
        (key.removeprefix("animation.gallery.").partition("."), " + ".join(axes(ooxml["behaviors"])))
        for key, ooxml in _entry_rows(index)
    ]
    # A name is qualified only when it lands in **different** rows. `bounce` is
    # an entrance effect that moves and resizes and a motion path that follows a
    # curve, so leaving it bare would send a reader to the wrong one. `blinds`
    # exists as both entrance and exit and does the same thing either way, so
    # qualifying it would say nothing and cost a third of the table.
    labels_by_effect: dict[str, set[str]] = {}
    for (_category, _dot, effect), label in rows:
        labels_by_effect.setdefault(effect, set()).add(label)

    grouped: dict[str, list[str]] = {}
    for (category, _dot, effect), label in rows:
        name = f"{category}.{effect}" if len(labels_by_effect[effect]) > 1 else effect
        grouped.setdefault(label, [])
        if name not in grouped[label]:
            grouped[label].append(name)
    return sorted(
        ((label, sorted(names)) for label, names in grouped.items()),
        key=lambda row: (-len(row[1]), row[0]),
    )


def describe(index: Any, *, category: str | None = None, effect: str | None = None):
    """Return the measured description of each matching gallery effect.

    An effect's options are described too, each as its own expression, because
    the option is where the interesting difference usually is: Fly In's eight
    directions differ only in two keyframes.
    """
    out: list[dict[str, Any]] = []
    for key, ooxml in _entry_rows(index):
        tail = key.removeprefix("animation.gallery.")
        entry_category, _, entry_effect = tail.partition(".")
        if category and entry_category != category:
            continue
        if effect and entry_effect != effect:
            continue
        described: dict[str, Any] = {
            "category": entry_category,
            "effect": entry_effect,
            "changes": axes(ooxml["behaviors"]),
            "expression": expression(ooxml["behaviors"]),
            "durationMs": ooxml.get("measuredDurationMs"),
        }
        options = ooxml.get("effectOptions") or {}
        if options:
            described["options"] = {
                setting: {
                    "default": option.get("default"),
                    "values": {
                        value: expression(measured.get("behaviors") or [])
                        for value, measured in sorted((option.get("values") or {}).items())
                    },
                }
                for setting, option in sorted(options.items())
            }
            combinations = ooxml.get("effectOptionCombinations")
            if combinations:
                described["optionsNote"] = combinations.get("gap")
        out.append(described)
    return out


def describe_transition(index: Any, slug: str) -> dict[str, Any]:
    """Return the parameter sets one transition accepts, and what each writes.

    The counterpart of :func:`describe` for the Transitions tab, and it exists
    because `transition.parameters` is the one part of the motion contract whose
    vocabulary cannot be guessed. The keys are the **OOXML attribute names**,
    not the friendly names the animation side uses: Push takes ``{"dir": "d"}``
    and not ``{"direction": "fromBottom"}``, and Split takes ``{"orient":
    "vert"}``. Writing a plausible-looking key is refused — correctly, but after
    a round trip through the writer that this answers without one.

    The sets are derived from the same catalog entries and the same
    ``selector_attributes`` the writer matches against, so this cannot drift
    from what will actually be accepted.
    """
    from sdpm.engine.timing.transition import PARAMETER_ALIASES, _base_entry

    variants = index.transition_variants(slug)
    if not variants:
        return {
            "transitions": [],
            "hint": (
                f"unknown transition effect {slug!r}; accepted: "
                f"{', '.join(index.transition_slugs())}"
            ),
        }

    base = _base_entry(index, slug)
    base_attributes = base.attributes() if base is not None else {}
    # `parameters` keys are the attribute names except where an alias exists, so
    # the reported key is the one a caller actually writes.
    aliases = {raw: friendly for friendly, raw in PARAMETER_ALIASES.get(slug, {}).items()}

    # Several catalog variants reduce to the same choosable set once the
    # effect's own defaults are removed — the element differs, the request does
    # not — so the list is deduplicated. Order is kept so the answer is stable.
    #
    # There is no per-variant `writable` flag here, and that is a measurement
    # rather than an omission: all 53 transitions are writable in every variant,
    # so a flag reporting it would never vary and would only add noise to an
    # answer whose entire purpose is to be cheaper than reading the guide.
    seen: set[tuple[tuple[str, Any], ...]] = set()
    parameter_sets: list[dict[str, Any]] = []
    for entry in sorted(variants, key=lambda item: item.key):
        if not entry.writable:
            continue
        # Only what the caller has to state: an attribute already carried by the
        # effect's own default is not a parameter they choose.
        chosen = {
            aliases.get(name, name): value
            for name, value in sorted(entry.selector_attributes().items())
            if base_attributes.get(name) != value
        }
        fingerprint = tuple(sorted(chosen.items()))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        parameter_sets.append(chosen)

    return {
        "transitions": [
            {
                "effect": slug,
                # Omitting `parameters` gets this, so it answers "what happens
                # if I state nothing" without a second call.
                "defaultAttributes": dict(sorted(base_attributes.items())),
                "parameterSets": parameter_sets,
                "note": (
                    "parameter keys are OOXML attribute names, not the friendly names "
                    "animation options use"
                ),
            }
        ]
    }
