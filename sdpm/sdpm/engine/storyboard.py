"""Render an animated slide as one still frame per click, without PowerPoint.

A still frame does not need the animation replayed — it needs each effect's
**end state**, and the catalog records that as measured data. So a storyboard
is a JSON-to-JSON transform: for click step *k*, emit a slide whose elements
are placed and shown the way they stand once step *k* has settled, then hand
it to the preview renderer that already exists.

What this catches and what it does not
======================================

It catches **authoring** mistakes, which are the ones a static preview cannot
show and a round-trip check cannot either: an element that is never revealed,
one revealed in the wrong order, an icon that arrives before the tile it sits
on, a dim applied to the wrong tile, an element hidden at the end of a build
that was supposed to stay.

It is **not** ground truth. It is a second reading of the same catalog the
writer uses, so the two agreeing does not prove PowerPoint agrees with either.
It says nothing about motion quality — easing, bounce, repeat and direction all
land on the same still frame — and nothing about how the transition between two
slides looks, beyond letting you put the last frame of one next to the first
frame of the next.

Where the state comes from
==========================

Everything below is read out of the catalog rather than written down here, so
this module cannot quietly disagree with the writer about what an effect does:

``presetClass``
    ``entr`` reveals its target, ``exit`` hides it, ``path`` moves it, ``emph``
    is modelled as no still-frame change.
``behaviors[] element == "p:animMotion"``
    its ``path`` attribute's last point, in slide-relative units, is the offset
    the target ends at.

Two deliberate understatements, both recorded per frame in ``notes`` so a
reader is told rather than misled:

* **Emphasis is modelled as changing nothing.** That is right for the pulse,
  scale and rotate family, which returns to where it started, and wrong for
  the persistent recolours (``fillColor``, ``objectColor`` and the rest), which
  do stay. Understating is the safe direction for a check: it never claims a
  change that did not happen.
* **A dim is indicated, not reproduced.** PowerPoint animates the *text*
  colour to the theme's Accent swatch and leaves the fill alone, so that is
  what happens here, with a neutral grey standing in for the template's own
  swatch. Dropping the fill's opacity instead — which this module did first —
  reads as a broken tile rather than a receded one, and that difference is
  enough to make a correct deck look wrong.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Iterator, Mapping, Sequence

#: Colour a dimmed element's text is drawn in when the author named none.
#:
#: Measured this session: ``dim`` writes ``p:animClr`` on ``ppt_c`` — the
#: **text** colour — to the theme's Accent swatch, and leaves the shape's fill
#: alone. The first version of this module indicated a dim by dropping the fill
#: to 35% opacity instead, which turned a white tile into a grey box and made a
#: correctly authored recede look like a rendering fault. The exact swatch is
#: template-dependent, so a neutral grey stands in for it and the frame's notes
#: say so.
DIM_TEXT = "#9A9AA0"

_COLOUR_TAG = re.compile(r"\{\{#[0-9A-Fa-f]{6}:")

#: Slide pixel size assumed when the deck does not say.
DEFAULT_SLIDE_SIZE = (1920, 1080)

_PATH_POINT = re.compile(r"(-?\d*\.?\d+)\s+(-?\d*\.?\d+)")


def click_steps(effects: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    """Group effects into click steps — one press of the clicker per step.

    ``onPageClick`` opens a step; ``withPrevious`` and ``afterPrevious`` join
    the step already open. An effect sequence that opens with something other
    than ``onPageClick`` still starts a step, because the first thing in a
    sequence has to wait for the sequence's own trigger.
    """
    steps: list[list[Mapping[str, Any]]] = []
    for effect in effects:
        if not isinstance(effect, Mapping):
            continue
        kind = (effect.get("start") or {}).get("type")
        if kind == "onPageClick" or not steps:
            steps.append([])
        steps[-1].append(effect)
    return steps


def _entry(index: Any, category: str, effect: str) -> Mapping[str, Any]:
    """The catalog's record for one gallery effect, or an empty mapping.

    An unknown effect name legitimately has no record, so that returns ``{}``.
    Anything else — a renamed index attribute, say — is allowed to raise:
    swallowing it once made every motion path silently stop moving while the
    storyboard still looked like it worked.
    """
    entry = index.items.get(f"animation.gallery.{category}.{effect}")
    if entry is None:
        return {}
    ooxml = getattr(entry, "ooxml", None)
    return ooxml if isinstance(ooxml, Mapping) else {}


def _path_points(path: Any, slide_size: tuple[int, int]):
    """``(first, last)`` point of a motion path as px offsets, or ``None``.

    The path is in slide-relative units with ``pathEditMode="relative"``, so a
    point times the slide size is an offset from where the element is authored.
    Both ends are needed, because three different paths all finish at offset
    zero and they are not the same thing to report:

    * ``M 0 0.035 L 0 0`` — starts displaced and settles into its authored
      place. This is how text rises into position, and the frame shows it
      correctly, so there is nothing to say.
    * ``M 0 0 C ... 0.18 0 C ... 0 0`` — goes out and comes back. The frame
      cannot show the journey, and saying nothing would read as "no motion".
    * ``M 0 0 L 0.25 0`` — travels and stays. The offset is the finding.
    """
    if not isinstance(path, str):
        return None
    points = _PATH_POINT.findall(path)
    if not points:
        return None
    scaled = [(float(x) * slide_size[0], float(y) * slide_size[1]) for x, y in points]
    return scaled[0], scaled[-1]


def _path_end(path: Any, slide_size: tuple[int, int]) -> tuple[float, float]:
    """The offset a motion path leaves its target at, in px."""
    ends = _path_points(path, slide_size)
    return ends[1] if ends else (0.0, 0.0)


def _motion_offset(ooxml: Mapping[str, Any], slide_size: tuple[int, int]) -> tuple[float, float]:
    """Where a gallery preset's motion path leaves its target."""
    for behavior in ooxml.get("behaviors") or ():
        if not isinstance(behavior, Mapping):
            continue
        if str(behavior.get("element", "")).split(":")[-1] != "animMotion":
            continue
        offset = _path_end((behavior.get("attributes") or {}).get("path"), slide_size)
        if offset != (0.0, 0.0):
            return offset
    return 0.0, 0.0


class _Effect:
    """One effect, reduced to what a still frame needs.

    Two authoring forms reach here and both have to be handled, because a
    motion-led deck is written almost entirely in the second one:

    ``preset``
        a gallery effect, whose end state comes from the catalog.
    ``behaviors``
        PowerPoint's primitives written directly. These carry no
        ``presetClass``, so reading only the catalog made every one of them a
        no-op: a packet authored to cross the slide did not move, and nothing
        said so. Their end state comes from the list itself.
    """

    def __init__(self, effect: Mapping[str, Any], index: Any, slide_size):
        preset = effect.get("preset") or {}
        behaviors = [b for b in (effect.get("behaviors") or ()) if isinstance(b, Mapping)]
        timing = effect.get("timing") or {}
        self.id = effect.get("id")
        self.target = (effect.get("target") or {}).get("element")
        self.category = preset.get("category")
        self.effect = preset.get("effect")
        self.notes: list[str] = []
        self.recolour: str | None = None

        ooxml = _entry(index, str(self.category), str(self.effect)) if preset else {}
        self.preset_class = ooxml.get("presetClass")
        self.reveals = self.preset_class == "entr" or self.category == "entrance"
        self.conceals = self.preset_class == "exit" or self.category == "exit"
        self.transient = self.preset_class == "emph" or self.category == "emphasis"
        # A rewound or auto-reversed effect ends where it began.
        returns = bool(timing.get("rewind") or timing.get("autoReverse"))
        self.offset = (0.0, 0.0) if returns else _motion_offset(ooxml, slide_size)

        if behaviors:
            self._read_behaviors(behaviors, slide_size, returns)

        after = effect.get("afterEffect") or {}
        self.after = after.get("type")
        self.after_color = after.get("color")

    def _read_behaviors(self, behaviors, slide_size, returns) -> None:
        """Derive the end state of directly authored primitives."""
        for behavior in behaviors:
            kind = behavior.get("type")
            if kind == "motion":
                ends = _path_points(behavior.get("path"), slide_size)
                if ends is None:
                    continue
                start, end = ends
                if returns:
                    self.notes.append(
                        f"{self.id}: its path is reversed, so it ends where it began")
                elif end != (0.0, 0.0):
                    self.offset = (self.offset[0] + end[0], self.offset[1] + end[1])
                elif start != (0.0, 0.0):
                    # starts displaced and settles: the frame is already right
                    pass
                else:
                    self.notes.append(
                        f"{self.id}: its path leaves and returns, so this frame "
                        f"cannot show the journey")
            elif kind == "color":
                to = behavior.get("to")
                if isinstance(to, str):
                    self.recolour = to if to.startswith("#") else f"#{to}"
            elif kind == "set":
                if behavior.get("attrName") == "style.visibility":
                    value = str(behavior.get("to", "")).lower()
                    self.reveals = self.reveals or value == "visible"
                    self.conceals = self.conceals or value == "hidden"
            elif kind in ("scale", "rotation"):
                self.notes.append(
                    f"{self.id}: a {kind} that this frame cannot show"
                    + (" (it reverses)" if returns else "")
                )
            elif kind in ("filter", "property", "command", "none"):
                self.notes.append(f"{self.id}: a {kind} behavior, not modelled here")
            elif kind:
                self.notes.append(f"{self.id}: unknown behavior {kind!r}, not modelled")


def _elements(slide: Mapping[str, Any]) -> Iterator[tuple[int, Mapping[str, Any]]]:
    for position, element in enumerate(slide.get("elements") or []):
        if isinstance(element, Mapping):
            yield position, element


def frames(
    slide: Mapping[str, Any],
    index: Any,
    *,
    slide_size: tuple[int, int] = DEFAULT_SLIDE_SIZE,
) -> list[dict[str, Any]]:
    """Return one frame per click step, plus frame 0 and any trigger frames.

    Frame 0 is the slide as it stands before the first click: everything that
    no entrance effect reveals. That frame is where an icon with no entrance of
    its own shows up floating without its tile, which is the defect this exists
    to make visible.
    """
    animations = slide.get("animations") or {}
    main = [e for e in (animations.get("mainSequence") or []) if isinstance(e, Mapping)]
    reduced = [_Effect(e, index, slide_size) for e in main]
    steps = click_steps(main)

    ids = [e.get("id") for _, e in _elements(slide) if e.get("id")]
    revealed_by_entrance = {r.target for r in reduced if r.reveals}

    #: id -> state. Anything an entrance reveals starts off screen.
    def initial():
        return {
            element_id: {"visible": element_id not in revealed_by_entrance,
                         "dx": 0.0, "dy": 0.0, "dim": None, "fill": None,
                         # why it is off screen, once it is: an explicit exit is
                         # the author's intent, an afterEffect usually is not.
                         # Not set at frame 0 — an entrance that has simply not
                         # fired yet is the normal state, not a finding.
                         "hiddenBy": None}
            for element_id in ids
        }

    out: list[dict[str, Any]] = []
    state = initial()
    pending_hide: set[str] = set()
    out.append({
        "frame": 0,
        "label": "before the first click",
        "state": copy.deepcopy(state),
        "notes": [],
    })

    step_effects = [[_Effect(e, index, slide_size) for e in step] for step in steps]
    for number, step in enumerate(step_effects, 1):
        notes: list[str] = []
        # A hideOnNextClick from the previous step lands now.
        for element_id in pending_hide:
            if element_id in state:
                state[element_id]["visible"] = False
                state[element_id]["hiddenBy"] = "afterEffect hideOnNextClick"
                notes.append(f"{element_id}: hidden by the previous step's hideOnNextClick")
        pending_hide = set()

        for item in step:
            target = item.target
            if target not in state:
                notes.append(f"{item.id}: targets {target!r}, which is not an element on this slide")
                continue
            if item.reveals:
                state[target]["visible"] = True
                state[target]["hiddenBy"] = None
            if item.conceals:
                state[target]["visible"] = False
                # An explicit exit is the author saying "this leaves now", so it
                # is not the same finding as a tile that vanished because an
                # afterEffect hid it. A motion-led deck exits its travelling
                # parts on purpose.
                state[target]["hiddenBy"] = "exit"
            if item.offset != (0.0, 0.0):
                state[target]["dx"] += item.offset[0]
                state[target]["dy"] += item.offset[1]
            if item.recolour:
                state[target]["fill"] = item.recolour
            if item.transient:
                notes.append(
                    f"{item.id}: {item.category}.{item.effect} returns to where it started, "
                    f"so this frame cannot show it"
                )
            notes.extend(item.notes)
            if item.after == "dim":
                state[target]["dim"] = item.after_color or "theme accent"
                notes.append(
                    f"{target}: dimmed (text recoloured; PowerPoint uses the template's "
                    f"Accent swatch, which this cannot know)"
                )
            elif item.after == "hide":
                # Measured: masterRel="sameClick" on the effect's own end, so it
                # is already gone once this click has settled.
                state[target]["visible"] = False
                state[target]["hiddenBy"] = "afterEffect hide"
                notes.append(f"{target}: hidden at the end of this click by afterEffect hide")
            elif item.after == "hideOnNextClick":
                pending_hide.add(target)

        out.append({
            "frame": number,
            "label": f"after click {number}",
            "state": copy.deepcopy(state),
            "notes": notes,
        })

    # Trigger sequences are not on the clicker, so each gets one frame applied
    # on top of the settled main sequence rather than a place in the run.
    for ordinal, sequence in enumerate(animations.get("interactiveSequences") or []):
        if not isinstance(sequence, Mapping):
            continue
        notes = []
        trigger = (sequence.get("trigger") or {}).get("target")
        for item in (_Effect(e, index, slide_size)
                     for e in (sequence.get("effects") or []) if isinstance(e, Mapping)):
            if item.target not in state:
                continue
            if item.reveals:
                state[item.target]["visible"] = True
            if item.conceals:
                state[item.target]["visible"] = False
            if item.offset != (0.0, 0.0):
                state[item.target]["dx"] += item.offset[0]
                state[item.target]["dy"] += item.offset[1]
            if item.recolour:
                state[item.target]["fill"] = item.recolour
            if item.transient:
                notes.append(
                    f"{item.id}: {item.category}.{item.effect} returns to where it started, "
                    f"so this frame cannot show it"
                )
            notes.extend(item.notes)
        out.append({
            "frame": len(out),
            "label": f"after clicking {trigger!r} ({sequence.get('id') or ordinal})",
            "state": copy.deepcopy(state),
            "notes": notes,
        })

    return out


def _dim_text(element: dict[str, Any], dim: str) -> None:
    """Recolour an element's text to show it has receded.

    Every inline ``{{#RRGGBB:`` tag is rewritten, because that is how a tile's
    per-paragraph colour is set and leaving them alone would dim nothing.
    """
    colour = dim if isinstance(dim, str) and dim.startswith("#") else DIM_TEXT
    element["fontColor"] = colour
    for paragraph in element.get("paragraphs") or ():
        if isinstance(paragraph, dict) and isinstance(paragraph.get("text"), str):
            paragraph["text"] = _COLOUR_TAG.sub("{{%s:" % colour, paragraph["text"])
    if isinstance(element.get("text"), str):
        element["text"] = _COLOUR_TAG.sub("{{%s:" % colour, element["text"])
    if element.get("iconColor"):
        element["iconColor"] = colour


def frame_slide(slide: Mapping[str, Any], frame: Mapping[str, Any], suffix: str) -> dict[str, Any]:
    """Build the slide JSON for one frame: hidden elements out, offsets applied."""
    state = frame["state"]
    derived = {k: v for k, v in slide.items() if k not in ("animations", "transition", "elements")}
    derived["id"] = f"{slide.get('id', 'slide')}{suffix}"
    kept = []
    for _, element in _elements(slide):
        element_id = element.get("id")
        entry = state.get(element_id) if element_id else None
        if entry is not None and not entry["visible"]:
            continue
        copied = copy.deepcopy(dict(element))
        if entry is not None:
            if entry["dx"] or entry["dy"]:
                if copied.get("x") is not None:
                    copied["x"] = copied["x"] + entry["dx"]
                if copied.get("y") is not None:
                    copied["y"] = copied["y"] + entry["dy"]
            if entry["fill"] is not None and copied.get("fill") not in (None, "none"):
                copied["fill"] = entry["fill"]
            if entry["dim"] is not None:
                _dim_text(copied, entry["dim"])
        kept.append(copied)
    derived["elements"] = kept
    return derived


def storyboard(
    deck: Mapping[str, Any],
    slides: Sequence[Mapping[str, Any]],
    index: Any,
    *,
    slide_size: tuple[int, int] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(derived deck, frame slides, manifest)`` for every frame.

    One deck holds every frame so a single renderer pass produces all of them;
    the manifest maps each rendered page back to its slide and click step, and
    carries the notes for anything the still frame could not show.
    """
    size = slide_size
    if size is None:
        declared = deck.get("slideSize") or {}
        size = (
            int(declared.get("width") or DEFAULT_SLIDE_SIZE[0]),
            int(declared.get("height") or DEFAULT_SLIDE_SIZE[1]),
        )

    derived_slides: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    for slide in slides:
        slug = slide.get("id", "slide")
        slide_frames = frames(slide, index, slide_size=size)
        ids = [e.get("id") for _, e in _elements(slide) if e.get("id")]
        for frame in slide_frames:
            derived_slides.append(frame_slide(slide, frame, f"-f{frame['frame']:02d}"))
            on_screen = sorted(k for k, v in frame["state"].items() if v["visible"])
            manifest.append({
                "page": len(derived_slides),
                "slide": slug,
                "frame": frame["frame"],
                "label": frame["label"],
                "onScreen": on_screen,
                "offScreen": sorted(set(ids) - set(on_screen)),
                "notes": frame["notes"],
            })
        # A build that ends with an element off screen is usually a mistake, and
        # it is invisible in both the ordinary preview and a round-trip check.
        # An element the author explicitly exited is excluded: a motion-led deck
        # sends its travelling parts off stage on purpose, and flagging those
        # would bury the real finding under noise.
        final = slide_frames[-1]["state"]
        stranded = sorted(k for k, v in final.items()
                          if not v["visible"] and v.get("hiddenBy") != "exit")
        if stranded:
            reasons = {k: final[k].get("hiddenBy") or "never revealed" for k in stranded}
            manifest[-1]["notes"] = list(manifest[-1]["notes"]) + [
                "ends with " + ", ".join(f"{k} off screen ({v})" for k, v in reasons.items())
            ]

    derived_deck = {k: v for k, v in deck.items()
                    if k not in ("animations", "transitions")}
    derived_deck["animations"] = {"enabled": False}
    derived_deck["transitions"] = {"enabled": False}
    return derived_deck, derived_slides, manifest
