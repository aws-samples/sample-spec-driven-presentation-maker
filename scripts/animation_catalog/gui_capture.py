#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Scripted accessibility capture driver for the animation values only the GUI can reach.

Development-only, in the same spirit as ``powerpoint.applescript``: sdpm's runtime,
CLI, MCP servers, tests and CI never invoke it, and it refuses to send a single
accessibility action without the explicit consent argument ``--drive-powerpoint``.

## Why this exists

``add effect`` and ``make new effect`` are declared in ``PowerPoint.sdef`` but are
**not implemented** in PowerPoint for Mac 16.113.1 (see
``tests/fixtures/animations/oracle-16.113.1/animation-route-probe/``), so no animation
value can be applied through the scripting dictionary. The macOS Accessibility API is
a different mechanism and is not blocked. Driving it by hand costs four agent round
trips per value — select the slide, select the shape, read the tree, press the control —
which does not fit a session. This module is that loop as one script.

## There is no slide navigation here, and that is deliberate

The first version of this driver selected a slide per target. A live run of it on
2026-10-31 against a 76-target plan returned **76 records, 0 captured, 76 rejected**, and
every record's ``steps`` was empty: nothing ever got as far as pressing a control. Two
distinct causes, both inside slide selection:

1. **Slides 1 to 6 timed out.** ``select_slide`` pressed the navigator cell, then set
   ``kAXSelected``, then waited for ``AXSelected`` to read back true. In the live tree the
   cells expose **no actions at all** — a manual read showed
   ``cell "Slide 1 of 17 Slides"`` with no ``[AXPress]`` — and ``AXSelected`` never became
   true. The only thing that selected a slide by hand was a synthetic global click on the
   cell's own frame.
2. **Slides 7 to 76 were not addressable.** The navigator publishes only the cells
   currently scrolled into view — 6 of 76 — so position-indexing into the cell list cannot
   reach the rest.

Making that work would have needed scrollbar arithmetic, title matching and a status-bar
cross-check: three more assumptions nothing offline can check. So slide selection is
**gone**, along with the thumbnail-position lookup and the ``Has Animation`` thumbnail
check that depended on it. ``gui_capture_plan.py`` now puts every target's shape on **one
slide**, and a target is selected by clicking its own shape. Do not reintroduce either
function; ``tests/test_animation_gui_capture.py`` fails if their names come back.

## What it assumes, measured rather than guessed

Every mechanic below is recorded in ``computer-use.md`` and is not re-derived here:

- A gallery press **replaces** the effect of the **selected shape** rather than adding
  one. That is what makes one slide of many shapes work: each target owns a shape, and
  each press lands on the shape the click selected.
- Tile indices shift as soon as a press scrolls a gallery, and galleries lazily
  materialize tiles. Nothing positional is ever cached: the tree is re-read and every
  control re-resolved **by title** immediately before each press.
- ``Effect Options`` and ``Path Animation`` open as their own AX windows, whose items
  are ``AXMenuButton``s activated with ``AXPress``.
- The ribbon exposes a read-back directly: the ``Start:`` popup's value and the
  ``Duration:`` incrementor's value. Both are recorded as evidence; neither is the gate.
- Canvas shapes have **no AX element**. They are selected with a synthetic mouse event
  at a point derived from the package geometry, the live editor-pane frame and the live
  zoom — never a hardcoded coordinate.

## Attribution, not position, is the evidence

Because every target shares one slide, "slide N is target N" is no longer available —
and it was never worth much, since it survived no reordering and no mis-aimed click. In
its place each target is verified against the package it just saved: the slide's effect
count must have grown by **exactly one**, and that new effect's ``p:spTgt/@spid`` must be
the ``p:cNvPr/@id`` of the shape the driver clicked. A new effect on another shape is a
``rejected`` record naming **both** spids, not a pass; a press that added nothing is a
recorded failure. The record carries the shape name, the expected spid, the attributed
spid and the new effect's own ``p:cTn`` attributes, so merged evidence is per target even
though ``--parse-oracle`` joins every record to the same slide.

This also makes the per-target save part of the measurement rather than only crash
insurance, so it is no longer optional.

## It moves the real pointer

Selecting a shape posts a global mouse event, so the **pointer physically moves** to
the slide canvas and the click lands wherever the frontmost window is. That is the one
part of the loop with no addressable element. The driver therefore refuses to start
unless PowerPoint is frontmost and its document window is the expected capture deck, so
it cannot click into the operator's own work. Do not use the machine during a run.

## Failure is recorded, never fatal and never silent

A target whose control is absent, ambiguous, or whose verification times out becomes a
``rejected`` record and the run continues. This is the lesson from the 2026-10-31
scripting run, which lost 357 applied candidates to one bad term because the failure
propagated out before the save. Every wait is bounded and a timeout is a recorded
failure, not a hang.

## Output

``powerpoint-readback.jsonl`` in the shape ``generate.py --parse-oracle`` consumes, plus
the saved package copied to ``powerpoint-oracle.pptx`` in the same directory so the two
can be joined offline:

    uv run python scripts/animation_catalog/generate.py --parse-oracle <out-dir>

Usage::

    uv run --with pyobjc-framework-ApplicationServices --with pyobjc-framework-Cocoa \\
      --with pyobjc-framework-Quartz \\
      python scripts/animation_catalog/gui_capture.py \\
        --plan plan.json --out /abs/out --document /abs/capture-deck.pptx --drive-powerpoint

``--help``, ``--emit-record-schema`` and every pure function here work without pyobjc;
the accessibility bindings are imported lazily inside the live backend so importing this
module never requires them and the unit tests run with a fake.
"""

from __future__ import annotations

import argparse
import json
import plistlib
import re
import shutil
import sys
import time
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol, Sequence, runtime_checkable

#: The consent argument. Deliberately **not** the scripting oracle's own token: the two
#: drivers gate different mechanisms, and ``tests/test_animation_catalog.py`` pins the
#: exact set of files allowed to mention the oracle's, so this module must not name it.
DRIVE_TOKEN = "--drive-powerpoint"

#: PowerPoint's bundle identifier, as reported by ``NSRunningApplication``.
BUNDLE_ID = "com.microsoft.Powerpoint"

#: Named in every record's ``application`` line so a merged evidence file says which
#: driver produced it.
DRIVER_NAME = "sdpm accessibility GUI capture driver"

#: Read offline from the application bundle. Reading a plist is not an Apple Event.
POWERPOINT_APP = Path("/Applications/Microsoft PowerPoint.app")

#: ``generate.py --parse-oracle`` joins these two by slide index.
READBACK_NAME = "powerpoint-readback.jsonl"
PACKAGE_NAME = "powerpoint-oracle.pptx"

#: ``merge_oracle_readback`` keys a record ``f"{enum}.{enumerator}"``. A GUI capture has
#: no scripting enumerator, so it declares this pseudo-enumeration and carries the
#: catalog key as the enumerator. That keeps GUI keys disjoint from the scripting
#: candidate keys instead of colliding with them.
RECORD_ENUM = "guiCapture"
RECORD_KIND = "guiCapture"
RESOLVED_BY = "accessibilityPress"

#: The ``p:cTn`` attribute that marks a timing node as an animation **effect** rather than
#: one of the container nodes above it or a behaviour node below it. Counting these, and
#: reading the ``p:spTgt/@spid`` under each, is how a press is attributed to a shape.
EFFECT_MARKER_ATTRIBUTE = "presetClass"

#: Ribbon controls read back after a press.
START_LABEL = "Start:"
DURATION_LABEL = "Duration:"

#: Quick Access toolbar button, pressed after every target so a crash costs one target.
SAVE_LABEL = "Save"

#: 914400 EMU per inch, 72 points per inch.
EMU_PER_POINT = 12700

#: Bounds on a tree scan. Exceeding either is an error rather than a "not found", so a
#: truncated scan can never be mistaken for an absent control.
MAX_TREE_DEPTH = 40
MAX_TREE_NODES = 60_000

#: Default bound on every wait, in seconds. There is no unbounded wait anywhere.
DEFAULT_TIMEOUT = 8.0
POLL_INTERVAL = 0.2

#: The editor pane's role and the status-bar zoom button's title form, both resolved from
#: the live tree. ``computer-use.md``'s coordinate table is a fallback for a control with
#: no element, not a source of these.
EDITOR_PANE_ROLE = "AXSplitGroup"

#: The slide editor area names itself, and its own frame is what the canvas mapping
#: needs. Resolving it by title rather than by role-and-size is what keeps the mapping
#: right when the ribbon collapses and the pane grows.
EDITOR_PANE_TITLE_PREFIX = "Slide Editor Pane"
ZOOM_TITLE_PATTERN = re.compile(r"^\s*\d+(?:\.\d+)?\s*%\s*$")


# --- failures ---------------------------------------------------------------
class DriverRefusal(RuntimeError):
    """The preconditions for touching PowerPoint are not met. Nothing was sent."""


class TargetFailure(RuntimeError):
    """One target failed. Recorded as ``rejected`` and the run continues.

    ``detail`` is for the figures a reader would otherwise have to parse back out of the
    message. An attribution failure names the spid it found and the spid it wanted, so a
    merged evidence file can be queried for "which targets landed on another shape"
    without reading prose.
    """

    kind = "targetFailure"

    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.detail = detail

    def as_error(self) -> dict[str, Any]:
        error = {"kind": self.kind, "message": str(self)}
        return {**error, "detail": self.detail} if self.detail else error


class ControlNotFound(TargetFailure):
    kind = "controlNotFound"


class AmbiguousControl(TargetFailure):
    kind = "ambiguousControl"


class DriverTimeout(TargetFailure):
    kind = "timeout"


class GeometryError(TargetFailure):
    kind = "geometryError"


class TreeTooLarge(TargetFailure):
    kind = "treeTooLarge"


class PackageEvidenceError(TargetFailure):
    """The saved package could not be read where the per-target evidence lives."""

    kind = "packageEvidence"


class EffectNotAdded(TargetFailure):
    """The press did not add exactly one animation effect to the slide."""

    kind = "effectNotAdded"


class EffectMisattributed(TargetFailure):
    """The press added an effect, but to a shape other than the one that was clicked."""

    kind = "effectMisattributed"


# --- geometry ---------------------------------------------------------------
@dataclass(frozen=True)
class Frame:
    """A rectangle in points. Screen frames use the top-left origin AX reports."""

    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)

    def offset(self, dx: float, dy: float) -> Frame:
        return Frame(self.x + dx, self.y + dy, self.width, self.height)


def emu_to_points(value: int | str) -> float:
    """Convert an OOXML EMU measurement to points."""
    return int(value) / EMU_PER_POINT


def read_slide_size_pt(package: Path) -> tuple[float, float]:
    """Return the deck's slide size in points, read from ``ppt/presentation.xml``."""
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    with zipfile.ZipFile(package) as archive:
        root = etree.fromstring(archive.read("ppt/presentation.xml"), parser=parser)
    size = next((el for el in root.iter() if etree.QName(el).localname == "sldSz"), None)
    if size is None:
        raise GeometryError(f"{package.name} has no p:sldSz in ppt/presentation.xml")
    return emu_to_points(size.get("cx")), emu_to_points(size.get("cy"))


def _read_slide_part(package: Path, slide_index: int) -> Any:
    """Parse one slide part, or fail naming the part that is not there."""
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    part = f"ppt/slides/slide{slide_index}.xml"
    with zipfile.ZipFile(package) as archive:
        try:
            blob = archive.read(part)
        except KeyError as exc:
            raise PackageEvidenceError(f"{package.name} has no {part}") from exc
    return etree.fromstring(blob, parser=parser)


def read_slide_shapes(package: Path, slide_index: int) -> list[dict[str, Any]]:
    """Return every named shape on one slide, with its ``spid`` and its centre in points.

    The ``spid`` is the shape's own ``p:cNvPr/@id``, which is what PowerPoint writes into
    ``p:spTgt`` when it animates that shape — so this one read supplies both the point to
    click and the identity the capture is attributed to. The two are **not** the same
    number: the generated deck's first shape is named ``Rounded Rectangle 1`` and carries
    ``id="2"``.
    """
    from lxml import etree

    root = _read_slide_part(package, slide_index)
    shapes: list[dict[str, Any]] = []
    for shape in root.iter():
        if etree.QName(shape).localname not in {"sp", "pic", "graphicFrame", "grpSp"}:
            continue
        props = next(
            (
                el
                for el in shape.iter()
                if etree.QName(el).localname == "cNvPr" and el.get("name")
            ),
            None,
        )
        if props is None:
            continue
        off = next((el for el in shape.iter() if etree.QName(el).localname == "off"), None)
        ext = next((el for el in shape.iter() if etree.QName(el).localname == "ext"), None)
        entry: dict[str, Any] = {"name": props.get("name"), "spid": props.get("id"), "center": None}
        if off is not None and ext is not None:
            x, y = emu_to_points(off.get("x")), emu_to_points(off.get("y"))
            cx, cy = emu_to_points(ext.get("cx")), emu_to_points(ext.get("cy"))
            entry["center"] = (x + cx / 2.0, y + cy / 2.0)
        shapes.append(entry)
    return shapes


def _shape_by_name(package: Path, slide_index: int, shape_name: str) -> dict[str, Any]:
    """Return one named shape, or fail listing the names the slide does carry.

    A shape the driver cannot find by name is an error rather than an estimate, because
    clicking an estimated point would select the wrong thing and the record would name
    the right one.
    """
    shapes = read_slide_shapes(package, slide_index)
    found = [shape for shape in shapes if shape["name"] == shape_name]
    if len(found) > 1:
        raise GeometryError(
            f"slide {slide_index} has {len(found)} shapes named {shape_name!r}; a click could not "
            "be attributed to one of them"
        )
    if not found:
        raise GeometryError(
            f"no shape named {shape_name!r} on slide {slide_index}; shapes present: "
            f"{sorted({shape['name'] for shape in shapes})}"
        )
    return found[0]


def read_shape_center_pt(package: Path, slide_index: int, shape_name: str) -> tuple[float, float]:
    """Return the named shape's centre on one slide, in points from the slide's top-left."""
    shape = _shape_by_name(package, slide_index, shape_name)
    if shape["center"] is None:
        raise GeometryError(f"shape {shape_name!r} on slide {slide_index} has no a:off/a:ext")
    return shape["center"]


def read_shape_spid(package: Path, slide_index: int, shape_name: str) -> str:
    """Return the named shape's ``p:cNvPr/@id``, the spid its effects will carry."""
    spid = _shape_by_name(package, slide_index, shape_name)["spid"]
    if not spid:
        raise GeometryError(f"shape {shape_name!r} on slide {slide_index} has no p:cNvPr/@id")
    return str(spid)


def read_slide_effects(package: Path, slide_index: int) -> list[dict[str, Any]]:
    """Return one entry per animation effect on a slide, each with the spid it targets.

    An effect is a ``p:cTn`` carrying :data:`EFFECT_MARKER_ATTRIBUTE` — the preset node
    PowerPoint writes per applied effect — and its target is the ``p:spTgt/@spid`` beneath
    it. A node whose subtree names more than one spid gets ``spid: None`` and keeps the
    whole list, because an effect that targets two shapes attributes to neither.

    Only the spids are compared across reads. PowerPoint is free to renumber the timing
    tree's ``id`` attributes when it adds an effect, so an identity built from them would
    make every earlier effect look new.
    """
    from lxml import etree

    root = _read_slide_part(package, slide_index)
    effects: list[dict[str, Any]] = []
    for node in root.iter():
        if etree.QName(node).localname != "cTn" or node.get(EFFECT_MARKER_ATTRIBUTE) is None:
            continue
        spids = sorted(
            {
                el.get("spid")
                for el in node.iter()
                if etree.QName(el).localname == "spTgt" and el.get("spid")
            }
        )
        effects.append(
            {
                "spid": spids[0] if len(spids) == 1 else None,
                "spids": spids,
                "cTn": dict(node.attrib),
            }
        )
    effects.sort(key=lambda effect: (effect["spid"] or "", json.dumps(effect["cTn"], sort_keys=True)))
    return effects


def _spid_counts(effects: Sequence[dict[str, Any]]) -> Counter[str | None]:
    return Counter(effect["spid"] for effect in effects)


def attribute_new_effect(
    before: Sequence[dict[str, Any]],
    after: Sequence[dict[str, Any]],
    expected_spid: str,
) -> dict[str, Any]:
    """Return the effect the press added, or fail saying what the package shows instead.

    This is the per-target acceptance gate, and it replaced a thumbnail label that only
    ever said *the slide* has an animation — which is not per-target evidence once every
    target shares a slide. Two distinct failures, because they mean different things:

    - the effect count did not grow by exactly one. A click that landed on a shape which
      already carries an effect looks exactly like this, since a gallery press *replaces*
      that shape's effect, and so does a press that applied nothing at all. It is also
      what ``--force`` produces against a deck that has already been captured once, which
      is why ``--force`` wants a freshly generated deck: a re-press on an animated shape
      cannot produce the new effect this gate requires, and reporting it as a pass would
      be crediting a target on the strength of a *previous* run's evidence;
    - exactly one effect appeared but on another shape. The value was applied, just not
      to this target, so the record names both spids and is rejected rather than
      crediting the wrong key.
    """
    if len(after) != len(before) + 1:
        appeared = sorted(str(spid) for spid in _spid_counts(after) - _spid_counts(before))
        vanished = sorted(str(spid) for spid in _spid_counts(before) - _spid_counts(after))
        raise EffectNotAdded(
            f"the slide carried {len(before)} animation effects before the press and {len(after)} "
            f"after it, so the press did not add exactly one; spids that appeared: "
            f"{appeared or ['none']}, spids that vanished: {vanished or ['none']}. The clicked "
            f"shape's spid is {expected_spid!r}",
            expectedSpid=expected_spid,
            effectsBefore=len(before),
            effectsAfter=len(after),
            appearedSpids=appeared,
            vanishedSpids=vanished,
        )
    added = _spid_counts(after) - _spid_counts(before)
    if sum(added.values()) != 1:
        raise EffectNotAdded(
            f"the slide gained one effect but {sum(added.values())} spids changed, so no single new "
            f"effect can be attributed; the clicked shape's spid is {expected_spid!r}",
            expectedSpid=expected_spid,
            effectsBefore=len(before),
            effectsAfter=len(after),
            appearedSpids=sorted(str(spid) for spid in added),
        )
    spid = next(iter(added.elements()))
    effect = next((candidate for candidate in after if candidate["spid"] == spid), None)
    if spid != expected_spid:
        raise EffectMisattributed(
            f"the press added an effect targeting shape spid {spid!r} (p:spTgt spids "
            f"{(effect or {}).get('spids')}), but the click was aimed at the shape with spid "
            f"{expected_spid!r}; the effect belongs to another shape, so this target is not captured",
            attributedSpid=spid,
            expectedSpid=expected_spid,
            spTgtSpids=(effect or {}).get("spids"),
            effectCTn=(effect or {}).get("cTn"),
        )
    if effect is None:  # pragma: no cover - the count arithmetic above makes this impossible
        raise EffectNotAdded(f"no effect in the saved slide targets spid {expected_spid!r}")
    return effect


def parse_zoom(title: str | None) -> float:
    """Return the zoom factor from the status bar button's title, e.g. ``92%`` -> 0.92."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", title or "")
    if not match:
        raise GeometryError(f"no zoom percentage in status-bar title {title!r}")
    return float(match.group(1)) / 100.0


def canvas_point(
    slide_size_pt: tuple[float, float],
    shape_center_pt: tuple[float, float],
    pane: Frame,
    zoom: float,
) -> tuple[float, float]:
    """Return the screen point of a shape's centre on the slide canvas.

    ``pane`` is the editor pane's frame in **screen** coordinates and ``zoom`` the live
    zoom factor. The slide is taken to be centred in the pane, which is what the
    2026-10-31 measurement showed: a 960x540 pt slide at 92% in a 1258x540 pane at
    screen (254, 177) puts a shape centred at (140, 190) pt on screen (570.2, 373.4).

    Deriving the point is the whole point: the shape has no AX element, so a wrong
    constant would select nothing and the press would apply to no shape at all.
    """
    if zoom <= 0:
        raise GeometryError(f"zoom must be positive, got {zoom!r}")
    slide_w, slide_h = slide_size_pt
    shown_w, shown_h = slide_w * zoom, slide_h * zoom
    origin_x = pane.x + (pane.width - shown_w) / 2.0
    origin_y = pane.y + (pane.height - shown_h) / 2.0
    return (origin_x + shape_center_pt[0] * zoom, origin_y + shape_center_pt[1] * zoom)


def parse_pane_frame(text: str | None) -> Frame | None:
    """Parse an operator-supplied ``x,y,w,h`` editor pane frame in screen points."""
    if not text:
        return None
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 4:
        raise ValueError(f"--pane-frame needs four comma-separated numbers, got {text!r}")
    try:
        x, y, width, height = (float(part) for part in parts)
    except ValueError as exc:
        raise ValueError(f"--pane-frame is not numeric: {text!r}") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"--pane-frame needs a positive width and height, got {text!r}")
    return Frame(x, y, width, height)


def window_frame_to_screen(frame: Frame, window_origin: tuple[float, float]) -> Frame:
    """Convert a window-relative frame to screen coordinates.

    ``computer-use.md`` records the ribbon's frames window-relative, so this is how a
    figure from that table is turned into something clickable.
    """
    return frame.offset(window_origin[0], window_origin[1])


# --- the accessibility layer, injectable ------------------------------------
@runtime_checkable
class AXNode(Protocol):
    """One accessibility element. The live and fake implementations share this shape."""

    @property
    def role(self) -> str: ...
    @property
    def title(self) -> str | None: ...
    @property
    def value(self) -> str | None: ...
    @property
    def enabled(self) -> bool: ...
    @property
    def frame(self) -> Frame | None: ...
    @property
    def children(self) -> Sequence[AXNode]: ...
    def press(self) -> None: ...


class AXBackend(Protocol):
    """Everything the driver needs from the host. Tests supply a fake for all of it."""

    def trusted(self) -> bool: ...
    def frontmost_bundle_id(self) -> str | None: ...
    def windows(self) -> list[AXNode]: ...
    def click(self, x: float, y: float) -> None: ...
    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


def walk(root: AXNode, *, max_depth: int = MAX_TREE_DEPTH, max_nodes: int = MAX_TREE_NODES) -> Iterator[AXNode]:
    """Depth-first walk of an element subtree, bounded in both depth and node count.

    Exceeding either bound raises rather than returning what it has, so a truncated scan
    cannot be read as "the control is not there".
    """
    stack: list[tuple[AXNode, int]] = [(root, 0)]
    seen = 0
    while stack:
        node, depth = stack.pop()
        seen += 1
        if seen > max_nodes:
            raise TreeTooLarge(f"tree scan exceeded {max_nodes} nodes")
        yield node
        if depth >= max_depth:
            continue
        stack.extend((child, depth + 1) for child in reversed(list(node.children)))


def find_all_by_title(root: AXNode, title: str, roles: Sequence[str] | None = None) -> list[AXNode]:
    """Return every element in ``root`` whose title matches ``title`` exactly."""
    allowed = set(roles) if roles else None
    return [
        node
        for node in walk(root)
        if node.title == title and (allowed is None or node.role in allowed)
    ]


def wait_until(
    backend: AXBackend,
    predicate: Callable[[], Any],
    *,
    timeout: float,
    what: str,
    poll: float = POLL_INTERVAL,
    swallow: tuple[type[BaseException], ...] = (ControlNotFound,),
) -> Any:
    """Poll ``predicate`` until it returns something truthy. Always bounded.

    A timeout is a :class:`DriverTimeout`, which the caller records as a failed target.
    There is no code path here that waits forever, and none that blocks on the GUI.

    Only ``swallow`` is treated as "not yet" — by default a control that is simply not
    there. An :class:`AmbiguousControl` or a :class:`TreeTooLarge` propagates at once,
    because polling cannot make either of them true and reporting them as a timeout
    would hide what actually went wrong.
    """
    deadline = backend.now() + timeout
    while True:
        try:
            result = predicate()
        except swallow:
            result = None
        if result:
            return result
        if backend.now() >= deadline:
            raise DriverTimeout(f"timed out after {timeout:g}s waiting for {what}")
        backend.sleep(poll)


def document_window(backend: AXBackend) -> AXNode:
    """Return PowerPoint's document window from a fresh read.

    Popups (``Effect Options``, ``Path Animation``) are their own windows, so the
    document window is identified by being none of them, and the result is never cached:
    ``computer-use.md`` records that a popup is invisible to the read that opened it and
    that element identity does not survive between reads.
    """
    windows = backend.windows()
    if not windows:
        raise ControlNotFound("PowerPoint reports no windows")
    popups = {"Effect Options", "Path Animation"}
    for window in windows:
        if (window.title or "") not in popups:
            return window
    raise ControlNotFound("every PowerPoint window is a popup; no document window")


def find_window(backend: AXBackend, title: str) -> AXNode | None:
    """Return the window titled ``title`` from a fresh read, or None."""
    return next((window for window in backend.windows() if window.title == title), None)


# --- path resolution --------------------------------------------------------
@dataclass
class StepOutcome:
    """What one step of a GUI path did. Carried into the record for traceability."""

    title: str
    outcome: str
    role: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "outcome": self.outcome, "role": self.role}


@dataclass
class PathResult:
    matched_title: str
    steps: list[StepOutcome]

    def as_dicts(self) -> list[dict[str, Any]]:
        return [step.as_dict() for step in self.steps]


@dataclass(frozen=True)
class Scope:
    """Where to look, as titles rather than elements.

    A scope is re-resolved from a fresh read before every press, because PowerPoint
    rebuilds its accessibility elements between reads and a press can scroll a gallery
    and renumber everything in it. Holding the scope as titles is what makes
    "never cache a positional index" structural rather than a rule to remember.
    """

    window_title: str | None = None
    descend: tuple[str, ...] = ()

    def inside(self, title: str) -> Scope:
        return Scope(self.window_title, self.descend + (title,))

    def in_window(self, title: str) -> Scope:
        return Scope(title, ())

    def describe(self) -> str:
        parts = [self.window_title or "document window", *self.descend]
        return " > ".join(parts)


#: When a title matches more than one element, these roles break the tie, in order. A
#: ribbon tab and a gallery tile have known roles, so this is a deterministic
#: disambiguation rather than a choice between candidates.
ROLE_PREFERENCE = ("AXRadioButton", "AXMenuButton", "AXButton", "AXCheckBox", "AXPopUpButton")


def _resolve_in(scope_node: AXNode, title: str) -> AXNode:
    """Resolve one title inside an already-resolved scope, disambiguating by role.

    Absent is :class:`ControlNotFound`; still ambiguous after the role preference is
    applied is :class:`AmbiguousControl`. Choosing between two same-titled controls would
    be a guess, and a press aimed by a guess applies the wrong value while the record
    names the right one — the exact failure mode that corrupted evidence on 2026-10-31.
    """
    found = find_all_by_title(scope_node, title)
    if not found:
        raise ControlNotFound(f"no element titled {title!r}")
    if len(found) == 1:
        return found[0]
    for role in ROLE_PREFERENCE:
        matching = [node for node in found if node.role == role]
        if len(matching) == 1:
            return matching[0]
    roles = sorted({node.role for node in found})
    raise AmbiguousControl(f"{len(found)} elements titled {title!r} with roles {roles}; refusing to choose")


def resolve_scope(backend: AXBackend, scope: Scope) -> AXNode:
    """Resolve a scope against a fresh read of the tree."""
    if scope.window_title is None:
        node = document_window(backend)
    else:
        window = find_window(backend, scope.window_title)
        if window is None:
            raise ControlNotFound(f"no window titled {scope.window_title!r}")
        node = window
    for title in scope.descend:
        node = _resolve_in(node, title)
    return node


def _reachable_any(scope_node: AXNode, titles: Sequence[str]) -> bool:
    """Is any of ``titles`` findable anywhere inside this scope?"""
    return any(find_all_by_title(scope_node, title) for title in titles)


#: Roles whose element opens its own window when pressed — the ``Effect Options`` and
#: ``Path Animation`` openers. Anything else holding a step is a container to scope into.
PRESS_TO_OPEN_ROLES = ("AXMenuButton", "AXButton", "AXPopUpButton")


def press_path(
    backend: AXBackend,
    path: Sequence[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    alternatives: Sequence[str] = (),
) -> PathResult:
    """Walk a GUI path by title and press its final step. Returns what each step did.

    ``path`` is ``[ribbon tab, control, *inner]`` — for example
    ``["Animations", "Entrance Effects", "Fly In"]`` or
    ``["Animations", "Path Animation", "Lines"]``. Each step is resolved **by title**
    against a fresh read:

    - the first step is the ribbon tab and is pressed;
    - an intermediate step whose subtree already contains the next step is a container
      (a visible gallery), so it is scoped into rather than pressed;
    - an intermediate step that is a pressable opener (:data:`PRESS_TO_OPEN_ROLES`) and
      does not contain the next step is pressed, and the driver then waits, bounded, for
      a window of that title — this is how ``Effect Options`` and ``Path Animation`` work;
    - any other intermediate step is scoped into and the next step is awaited inside it,
      because a gallery **lazily materializes its tiles** and a first read is not the
      whole gallery;
    - an intermediate step that is absent **while the next step is already reachable** is
      recorded as ``groupAbsent`` and skipped. That covers a purely visual grouping level
      such as ``Basic`` in ``Path Animation``, and it never affects the value-bearing
      step, which must still match a title exactly;
    - the final step is awaited, re-reading the tree on every poll, then **re-resolved
      from a fresh read and pressed**. Absent for the whole timeout is a failure naming
      every title it tried; ambiguous fails at once rather than being polled.
    """
    if len(path) < 2:
        raise ControlNotFound(f"a GUI path needs a ribbon tab and a control, got {list(path)}")

    steps: list[StepOutcome] = []
    scope = Scope()
    final_titles = (path[-1], *alternatives)

    # Pressing a ribbon tab that is ALREADY active collapses the ribbon, which takes
    # every control on it out of the tree. Measured: a run against a deck whose
    # Animations tab was already selected pressed it anyway, the ribbon folded, and all
    # 76 targets failed waiting for a gallery that had stopped existing. So the tab is
    # pressed only when its own controls are not already reachable, which is the same
    # evidence the wait below uses and needs no extra attribute.
    tab_node = _resolve_in(resolve_scope(backend, scope), path[0])
    if _reachable_any(resolve_scope(backend, scope), [path[1]]):
        steps.append(StepOutcome(path[0], "tabAlreadyActive", tab_node.role))
    else:
        tab_node.press()
        steps.append(StepOutcome(path[0], "pressedTab", tab_node.role))
        wait_until(
            backend,
            lambda: _reachable_any(resolve_scope(backend, scope), [path[1]]),
            timeout=timeout,
            what=f"{path[1]!r} after selecting the {path[0]!r} tab",
        )

    for index in range(1, len(path) - 1):
        title = path[index]
        following = final_titles if index == len(path) - 2 else (path[index + 1],)
        scope_node = resolve_scope(backend, scope)
        try:
            node = _resolve_in(scope_node, title)
        except ControlNotFound:
            if not _reachable_any(scope_node, following):
                raise
            steps.append(StepOutcome(title, "groupAbsent", None))
            continue
        if _reachable_any(node, following):
            scope = scope.inside(title)
            steps.append(StepOutcome(title, "scoped", node.role))
            continue
        if node.role in PRESS_TO_OPEN_ROLES:
            node.press()
            window = wait_until(
                backend,
                lambda title=title: find_window(backend, title),
                timeout=timeout,
                what=f"the {title!r} window to open",
            )
            scope = scope.in_window(window.title or title)
            steps.append(StepOutcome(title, "openedWindow", node.role))
            continue
        scope = scope.inside(title)
        steps.append(StepOutcome(title, "scopedPendingTiles", node.role))

    tried = ", ".join(repr(title) for title in final_titles)

    def present() -> str | None:
        scope_node = resolve_scope(backend, scope)
        for candidate in final_titles:
            try:
                _resolve_in(scope_node, candidate)
            except ControlNotFound:
                continue
            return candidate
        return None

    try:
        matched = wait_until(backend, present, timeout=timeout, what=f"one of {tried} in {scope.describe()}")
    except DriverTimeout as exc:
        raise ControlNotFound(
            f"none of {tried} appeared in {scope.describe()} within {timeout:g}s; the tree was "
            "re-read on every poll, so a lazily materialized tile had its chance"
        ) from exc

    # Re-resolved from one more fresh read: a press aimed by anything older can land on a
    # tile that scrolled, which applies the wrong value and records the right one.
    node = _resolve_in(resolve_scope(backend, scope), matched)
    if not node.enabled:
        raise ControlNotFound(f"{matched!r} is present but disabled in {scope.describe()}")
    node.press()
    steps.append(StepOutcome(matched, "pressed", node.role))
    return PathResult(matched, steps)


# --- read-back --------------------------------------------------------------
def read_labelled_value(window: AXNode, label: str) -> str | None:
    """Return the value of the ribbon control titled ``label``, or None.

    The read-back is recorded evidence, not an acceptance gate, so an absent or
    ambiguous control is reported as ``null`` rather than failing the target. The
    acceptance gate is :func:`attribute_new_effect`, which reads the saved package.
    """
    found = find_all_by_title(window, label)
    if len(found) == 1:
        return found[0].value
    valued = [node for node in found if node.value not in (None, "")]
    return valued[0].value if len(valued) == 1 else None


def ribbon_readback(backend: AXBackend) -> dict[str, str | None]:
    """Return the ``Start:`` and ``Duration:`` values the ribbon shows right now."""
    window = document_window(backend)
    return {
        "start": read_labelled_value(window, START_LABEL),
        "duration": read_labelled_value(window, DURATION_LABEL),
    }


# --- driving ----------------------------------------------------------------
# There is deliberately no slide selection and no thumbnail lookup here. See the module
# docstring: the live 2026-10-31 run rejected all 76 targets inside them, because the
# navigator's cells expose no actions and only the handful scrolled into view is published
# at all. Every target now lives on one slide and is reached by clicking its own shape.


def select_shape(
    backend: AXBackend,
    geometry: CanvasGeometry,
    package: Path,
    slide_index: int,
    shape_name: str,
    gate_title: str,
    *,
    timeout: float,
) -> tuple[float, float]:
    """Click one named shape and confirm something is selected. Returns the point clicked.

    The shape has **no accessibility element**, so the point is derived from the
    package's own geometry for *this* shape plus the live editor-pane frame and zoom, and
    posting it physically moves the pointer.

    Confirmation is weak by nature and weaker than it used to be: the gallery named by
    the target's path is disabled until *some* shape is selected, so its becoming enabled
    says a shape is selected — and after the first target of a run, one already is. It
    is kept because it still catches a click that lands on empty canvas, which deselects.
    What establishes that the click landed on the *right* shape is
    :func:`attribute_new_effect`, after the press and the save.
    """
    point = geometry.point_for(package, slide_index, shape_name)

    def gate_enabled() -> bool:
        return _resolve_in(document_window(backend), gate_title).enabled

    backend.click(*point)
    wait_until(
        backend,
        gate_enabled,
        timeout=timeout,
        what=(
            f"{gate_title!r} to become enabled after clicking {shape_name!r} at "
            f"{point[0]:.0f},{point[1]:.0f}"
        ),
    )
    return point


def press_save(backend: AXBackend, document: Path, *, timeout: float) -> None:
    """Press Save in the Quick Access toolbar and wait, bounded, for the file to change.

    Incremental saving is what makes a crash cost one target rather than the run, and it
    is now also the measurement: :func:`attribute_new_effect` reads the file this writes,
    so there is no option to skip it. The document must already exist on disk so Save
    overwrites in place and PowerPoint does not open a Save As sheet, which this driver
    would not answer.
    """
    before = (document.stat().st_mtime_ns, document.stat().st_size) if document.exists() else None
    _resolve_in(document_window(backend), SAVE_LABEL).press()
    wait_until(
        backend,
        lambda: document.exists() and (document.stat().st_mtime_ns, document.stat().st_size) != before,
        timeout=timeout,
        what=f"{document.name} to be written by Save",
    )


def read_application_version(app: Path = POWERPOINT_APP) -> str | None:
    """Read PowerPoint's version from its bundle. A plist read is not an Apple Event."""
    info = app / "Contents" / "Info.plist"
    if not info.exists():
        return None
    try:
        data = plistlib.loads(info.read_bytes())
    except (plistlib.InvalidFileException, ValueError):
        return None
    version = data.get("CFBundleShortVersionString") or data.get("CFBundleVersion")
    return str(version) if version else None


def normalise_document_title(title: str | None) -> str:
    """Strip what PowerPoint decorates a document window title with."""
    text = (title or "").strip()
    for suffix in (".pptx", ".ppt"):
        if text.lower().endswith(suffix):
            text = text[: -len(suffix)]
    return text.strip()


def assert_ready(backend: AXBackend, expected_document: str) -> str:
    """Refuse to start unless the frontmost document is the expected capture deck.

    The driver clicks with a global mouse event, so a wrong frontmost window means
    clicking into the operator's own work. Nothing is pressed before this passes.
    """
    if not backend.trusted():
        raise DriverRefusal(
            "this process does not hold the Accessibility grant; add the terminal running it "
            "to System Settings > Privacy & Security > Accessibility"
        )
    frontmost = backend.frontmost_bundle_id()
    if frontmost != BUNDLE_ID:
        raise DriverRefusal(f"PowerPoint must be frontmost; the frontmost application is {frontmost!r}")
    title = normalise_document_title(document_window(backend).title)
    if title != normalise_document_title(expected_document):
        raise DriverRefusal(
            f"the frontmost document is {title!r}, not the expected capture deck "
            f"{normalise_document_title(expected_document)!r}; refusing to drive it"
        )
    return title


# --- records ----------------------------------------------------------------
def application_record(version: str | None) -> dict[str, Any]:
    """The read-back file's first line: which application and which driver produced it."""
    return {
        "record": "application",
        "application": "Microsoft PowerPoint",
        "version": version,
        "driver": DRIVER_NAME,
        "mechanism": "macOS Accessibility API",
        "usesAppleEvents": False,
        "usesVisualBasic": False,
    }


def capture_record(
    target: dict[str, Any],
    *,
    applied: str | None = None,
    matched_title: str | None = None,
    readback: dict[str, str | None] | None = None,
    steps: Sequence[dict[str, Any]] = (),
    shape_name: str | None = None,
    shape_spid: str | None = None,
    click_point: tuple[float, float] | None = None,
    effect: dict[str, Any] | None = None,
    effect_count: tuple[int, int] | None = None,
    saved: bool = False,
    rejected: bool = False,
    error: dict[str, Any] | None = None,
    save_error: dict[str, Any] | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """One record per target, in the shape ``generate.py --parse-oracle`` consumes.

    ``--parse-oracle`` joins on ``enum``/``enumerator``/``slideIndex``, so a GUI capture
    declares the pseudo-enumeration :data:`RECORD_ENUM` and carries the catalog key as
    the enumerator. ``code`` is null by construction: a GUI control has no four-char
    scripting code, and inventing one would assert a name correspondence the capture
    does not measure.

    Every target now shares one slide, so that join puts the **whole slide's** OOXML
    beside every record. The per-target evidence therefore lives in the record itself:
    ``shapeName`` and ``shapeSpid`` say which shape was aimed at, ``attributedSpid`` and
    ``effectCTn`` say which effect the package gained and what it says, and
    ``effectCount`` says the slide went from n to n+1. A merged view is read per target by
    matching ``attributedSpid`` against the slide's ``p:spTgt/@spid``.
    """
    key = target["key"]
    attributed = bool(effect and shape_spid and effect.get("spid") == shape_spid)
    return {
        "record": RECORD_KIND,
        "enum": RECORD_ENUM,
        "enumerator": key,
        "code": None,
        "catalogKey": key,
        "slideIndex": target["slideIndex"],
        "guiPath": list(target["guiPath"]),
        "shapeName": shape_name,
        "shapeSpid": shape_spid,
        "clickPoint": [round(click_point[0], 1), round(click_point[1], 1)] if click_point else None,
        "applied": applied,
        "matchedTitle": matched_title,
        "ribbonReadBack": readback or {"start": None, "duration": None},
        "attributedSpid": effect.get("spid") if effect else None,
        "effectCTn": effect.get("cTn") if effect else None,
        "effectCount": {
            "before": effect_count[0] if effect_count else None,
            "after": effect_count[1] if effect_count else None,
        },
        "attributed": attributed,
        "pathResolution": list(steps),
        "saved": saved,
        "saveError": save_error,
        "rejected": rejected,
        "resolvedBy": RESOLVED_BY if not rejected else None,
        "error": error,
        "capturedAt": captured_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def read_records(path: Path) -> list[dict[str, Any]]:
    """Read an existing read-back file, keeping unparsable lines visible."""
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            records.append({"record": "unparsed", "line": number, "error": str(exc)})
    return records


def captured_keys(records: Sequence[dict[str, Any]]) -> set[str]:
    """Return the catalog keys already captured successfully.

    A rejected record is **not** captured, so a failed target is retried on the next run.
    That is the difference between resuming and skipping.
    """
    return {
        record["catalogKey"]
        for record in records
        if record.get("record") == RECORD_KIND and record.get("catalogKey") and not record.get("rejected")
    }


def split_plan(
    targets: Sequence[dict[str, Any]], records: Sequence[dict[str, Any]], *, force: bool
) -> tuple[list[dict[str, Any]], list[str]]:
    """Split a plan into what to run now and what is already captured."""
    if force:
        return list(targets), []
    done = captured_keys(records)
    todo = [target for target in targets if target["key"] not in done]
    skipped = [target["key"] for target in targets if target["key"] in done]
    return todo, skipped


def plan_shape_names(plan: dict[str, Any]) -> dict[str, str]:
    """Return the plan's ``target key -> shape name`` mapping, refusing an incomplete one.

    The names are settled by ``gui_capture_plan.py --generate``, which reads them back out
    of the package sdpm wrote; sdpm derives a shape's name from its geometry, so neither
    side may assume one. A target with no name has nothing to click and nothing to
    attribute an effect to, so this refuses the whole run rather than producing a record
    per target that says the same thing.
    """
    mapping = {str(key): str(name) for key, name in (plan.get("shapeNames") or {}).items() if name}
    missing: list[str] = []
    conflicting: list[str] = []
    for target in plan.get("targets", []):
        key, name = target["key"], target.get("shapeName")
        if name:
            if key in mapping and mapping[key] != name:
                conflicting.append(key)
            mapping[key] = str(name)
        elif key not in mapping:
            missing.append(key)
    if conflicting:
        raise DriverRefusal(
            f"the plan's shapeNames mapping disagrees with the targets' own shapeName for "
            f"{sorted(conflicting)}; regenerate the plan rather than guessing which is current"
        )
    if missing:
        raise DriverRefusal(
            f"{len(missing)} targets carry no shapeName and the plan's shapeNames mapping does not "
            f"name them either, starting with {sorted(missing)[:3]}; shape names are settled by "
            "gui_capture_plan.py --generate, which reads them out of the generated package"
        )
    return mapping


def retained_records(records: Sequence[dict[str, Any]], rerunning: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the prior records to keep: everything not about a target being re-run.

    Rewriting rather than appending keeps exactly one record per key, so the file stays a
    statement about the current state of the deck instead of a history to reconcile.
    """
    retrying = {target["key"] for target in rerunning}
    return [
        record
        for record in records
        if record.get("record") == RECORD_KIND and record.get("catalogKey") not in retrying
    ]


# --- the run ----------------------------------------------------------------
@dataclass
class CaptureSettings:
    """Everything the run needs that is not the plan or the backend."""

    out_dir: Path
    document: Path
    expect_document: str | None = None
    timeout: float = DEFAULT_TIMEOUT
    force: bool = False
    pane_role: str = EDITOR_PANE_ROLE
    pane: Frame | None = None
    zoom: float | None = None

    @property
    def expected_title(self) -> str:
        return self.expect_document or self.document.stem

    @property
    def readback_path(self) -> Path:
        return self.out_dir / READBACK_NAME

    @property
    def package_path(self) -> Path:
        return self.out_dir / PACKAGE_NAME


@dataclass
class CanvasGeometry:
    """How the driver turns a package and the live window into a clickable point."""

    slide_size_pt: tuple[float, float]
    pane: Frame
    zoom: float
    source: dict[str, Any] = field(default_factory=dict)

    def point_for(self, package: Path, slide_index: int, shape_name: str) -> tuple[float, float]:
        centre = read_shape_center_pt(package, slide_index, shape_name)
        return canvas_point(self.slide_size_pt, centre, self.pane, self.zoom)


def read_canvas_geometry(
    backend: AXBackend,
    package: Path,
    *,
    pane_role: str = EDITOR_PANE_ROLE,
    pane: Frame | None = None,
    zoom: float | None = None,
) -> CanvasGeometry:
    """Derive the canvas mapping from the package and the live window, not from constants.

    The slide size comes from ``ppt/presentation.xml``, the editor pane's frame from the
    accessibility tree, and the zoom from the status bar button's own title. The
    2026-10-31 session got this 90 px wrong by estimating it, which is why none of it is
    a literal here.

    ``pane`` and ``zoom`` let an operator supply a measured value when this build does not
    expose one; both are recorded in the summary as an override so a capture driven from
    an override is distinguishable from a derived one. A *wrong* pane fails loudly rather
    than quietly: the click lands off the shape, the gallery stays disabled, and
    :func:`select_shape` records a timeout instead of pressing anything.
    """
    source: dict[str, Any] = {"paneRole": pane_role}
    window = document_window(backend)
    if pane is None:
        # Identified by the editor area's OWN title, not by being the biggest pane of a
        # role. Measured: picking the largest AXSplitGroup returns the outer split that
        # also holds the navigator and the notes, which is 254 px too wide and 188 px too
        # tall, so every click landed off its shape and all 76 targets timed out. The
        # editor area is the only element whose title starts with this phrase, and its
        # frame follows the ribbon being expanded or collapsed, which a constant cannot.
        # The editor area names itself, but its OWN frame lags a ribbon expand or
        # collapse — measured once as y=89 h=594 while its parent scroll area already
        # reported the settled y=144 h=540. So the pane is the smallest framed container
        # whose subtree holds that titled element: identified by the title, measured by
        # the container that has re-laid out.
        holders = [
            node
            for node in walk(window)
            if node.frame is not None
            and node.frame.width > 0
            and node.frame.height > 0
            and any(
                (inner.title or "").startswith(EDITOR_PANE_TITLE_PREFIX)
                for inner in walk(node)
                if inner is not node
            )
        ]
        if not holders:
            raise GeometryError(
                f"no framed container holds an element titled {EDITOR_PANE_TITLE_PREFIX!r}*; "
                "pass --pane-frame with a measured x,y,w,h"
            )
        smallest = min(holders, key=lambda node: node.frame.width * node.frame.height)  # type: ignore[union-attr]
        assert smallest.frame is not None
        pane, source["paneSource"] = smallest.frame, "editorPaneContainer"
        source["paneRole"] = smallest.role
    else:
        source["paneSource"] = "operatorOverride"
    if zoom is None:
        titles = [node.title for node in walk(window) if node.title and ZOOM_TITLE_PATTERN.match(node.title)]
        if not titles:
            raise GeometryError("no status-bar zoom percentage in the document window; pass --zoom")
        if len({title.strip() for title in titles}) > 1:
            raise GeometryError(f"ambiguous zoom percentages in the window: {sorted(set(titles))}")
        zoom, source["zoomSource"], source["zoomTitle"] = parse_zoom(titles[0]), "statusBar", titles[0].strip()
    else:
        source["zoomSource"] = "operatorOverride"
    return CanvasGeometry(
        slide_size_pt=read_slide_size_pt(package),
        pane=pane,
        zoom=zoom,
        source=source,
    )


def capture_target(
    backend: AXBackend,
    target: dict[str, Any],
    settings: CaptureSettings,
    geometry: CanvasGeometry,
    shape_name: str,
) -> dict[str, Any]:
    """Drive one target end to end and return its record, successful or not.

    The order matters and is not the order it used to be. The press is followed by the
    save, and only then by verification, because the verification **is** a read of the
    saved package: the slide must have gained exactly one effect and that effect must
    target the clicked shape. A save failure is therefore a rejected record rather than a
    footnote on a passing one — without the save there is no evidence either way.
    """
    timeout = settings.timeout
    slide_index = target["slideIndex"]
    carried: dict[str, Any] = {"shape_name": shape_name}
    try:
        carried["shape_spid"] = spid = read_shape_spid(settings.document, slide_index, shape_name)
        before = read_slide_effects(settings.document, slide_index)
        carried["click_point"] = select_shape(
            backend,
            geometry,
            settings.document,
            slide_index,
            shape_name,
            target["guiPath"][1],
            timeout=timeout,
        )
        result = press_path(
            backend,
            target["guiPath"],
            timeout=timeout,
            alternatives=tuple(target.get("titleAlternatives", ())),
        )
        carried["matched_title"] = result.matched_title
        carried["steps"] = result.as_dicts()
    except TargetFailure as exc:
        return capture_record(target, rejected=True, error=exc.as_error(), **carried)

    try:
        press_save(backend, settings.document, timeout=timeout)
    except TargetFailure as exc:
        return capture_record(
            target, rejected=True, error=exc.as_error(), save_error=exc.as_error(), **carried
        )
    carried["saved"] = True

    try:
        after = read_slide_effects(settings.document, slide_index)
        carried["effect_count"] = (len(before), len(after))
        carried["effect"] = attribute_new_effect(before, after, spid)
    except TargetFailure as exc:
        return capture_record(target, rejected=True, error=exc.as_error(), **carried)

    return capture_record(
        target,
        applied=" > ".join(target["guiPath"]),
        readback=ribbon_readback(backend),
        **carried,
    )


def run_capture(
    plan: dict[str, Any],
    settings: CaptureSettings,
    backend: AXBackend,
    *,
    version: str | None = None,
) -> dict[str, Any]:
    """Run a whole plan. Returns the summary; writes the read-back incrementally."""
    targets = list(plan.get("targets", []))
    shape_names = plan_shape_names(plan)
    settings.out_dir.mkdir(parents=True, exist_ok=True)
    existing = read_records(settings.readback_path)
    todo, skipped = split_plan(targets, existing, force=settings.force)

    title = assert_ready(backend, settings.expected_title)
    try:
        geometry = read_canvas_geometry(
            backend,
            settings.document,
            pane_role=settings.pane_role,
            pane=settings.pane,
            zoom=settings.zoom,
        )
    except TargetFailure as exc:
        # Geometry is the whole run's precondition, not one target's, so a failure here
        # is a refusal with an actionable message rather than 76 identical records.
        raise DriverRefusal(f"cannot derive the canvas mapping: {exc}") from exc

    keep = retained_records(existing, todo)
    with settings.readback_path.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(application_record(version), ensure_ascii=False) + "\n")
        for record in keep:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        stream.flush()

        written: list[dict[str, Any]] = []
        for target in todo:
            record = capture_target(backend, target, settings, geometry, shape_names[target["key"]])
            written.append(record)
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()

    if settings.document.exists():
        shutil.copy2(settings.document, settings.package_path)

    failures = [record for record in written if record["rejected"]]
    return {
        "document": title,
        "readback": str(settings.readback_path),
        "package": str(settings.package_path) if settings.package_path.exists() else None,
        "planned": len(targets),
        "slides": sorted({target["slideIndex"] for target in targets}),
        "skippedAlreadyCaptured": len(skipped),
        "attempted": len(written),
        "captured": len(written) - len(failures),
        "failed": len(failures),
        "attributed": sum(1 for record in written if record["attributed"]),
        "saveFailures": sum(1 for record in written if record["saveError"]),
        "retainedRecords": len(keep),
        "canvas": {
            "slideSizePt": list(geometry.slide_size_pt),
            "paneFrame": [geometry.pane.x, geometry.pane.y, geometry.pane.width, geometry.pane.height],
            "zoom": geometry.zoom,
            **geometry.source,
        },
        "failures": [
            {
                "key": record["catalogKey"],
                "slideIndex": record["slideIndex"],
                "shapeName": record["shapeName"],
                "shapeSpid": record["shapeSpid"],
                "attributedSpid": record["attributedSpid"],
                "error": record["error"],
            }
            for record in failures
        ],
    }


# --- the live backend, imported lazily --------------------------------------
class LiveAXNode:
    """One live accessibility element. Every attribute is read on access, never cached."""

    __slots__ = ("_element", "_ax", "_quartz")

    def __init__(self, element: Any, ax: Any, quartz: Any) -> None:
        self._element = element
        self._ax = ax
        self._quartz = quartz

    def _attribute(self, name: str) -> Any:
        error, value = self._ax.AXUIElementCopyAttributeValue(self._element, name, None)
        return None if error else value

    @property
    def role(self) -> str:
        return str(self._attribute(self._ax.kAXRoleAttribute) or "")

    @property
    def title(self) -> str | None:
        value = self._attribute(self._ax.kAXTitleAttribute)
        if value in (None, ""):
            value = self._attribute(self._ax.kAXDescriptionAttribute)
        return None if value in (None, "") else str(value)

    @property
    def value(self) -> str | None:
        value = self._attribute(self._ax.kAXValueAttribute)
        return None if value is None else str(value)

    @property
    def enabled(self) -> bool:
        value = self._attribute(self._ax.kAXEnabledAttribute)
        return True if value is None else bool(value)

    @property
    def frame(self) -> Frame | None:
        position = self._attribute(self._ax.kAXPositionAttribute)
        size = self._attribute(self._ax.kAXSizeAttribute)
        if position is None or size is None:
            return None
        ok_point, point = self._ax.AXValueGetValue(position, self._ax.kAXValueCGPointType, None)
        ok_size, extent = self._ax.AXValueGetValue(size, self._ax.kAXValueCGSizeType, None)
        if not ok_point or not ok_size:
            return None
        return Frame(float(point.x), float(point.y), float(extent.width), float(extent.height))

    @property
    def children(self) -> Sequence[AXNode]:
        kids = self._attribute(self._ax.kAXChildrenAttribute) or []
        return [LiveAXNode(child, self._ax, self._quartz) for child in kids]

    def press(self) -> None:
        error = self._ax.AXUIElementPerformAction(self._element, self._ax.kAXPressAction)
        if error:
            raise TargetFailure(f"AXPress on {self.title!r} ({self.role}) failed with AX error {error}")

    # There is deliberately no ``select``. The 2026-10-31 run proved ``kAXSelected`` never
    # reads back true on this build's navigator cells, and nothing else here selects by
    # attribute: a shape is selected by a click and verified from the saved package.


class LiveAXBackend:
    """The real host. pyobjc is imported here so importing this module never needs it."""

    def __init__(self) -> None:
        import ApplicationServices as ax
        import Quartz
        from AppKit import NSWorkspace

        self._ax = ax
        self._quartz = Quartz
        self._workspace = NSWorkspace
        self._pid: int | None = None

    def _application(self) -> Any:
        if self._pid is None:
            for app in self._workspace.sharedWorkspace().runningApplications():
                if app.bundleIdentifier() == BUNDLE_ID:
                    self._pid = int(app.processIdentifier())
                    break
        if self._pid is None:
            raise DriverRefusal("PowerPoint is not running")
        return self._ax.AXUIElementCreateApplication(self._pid)

    def trusted(self) -> bool:
        return bool(self._ax.AXIsProcessTrusted())

    def frontmost_bundle_id(self) -> str | None:
        app = self._workspace.sharedWorkspace().frontmostApplication()
        return str(app.bundleIdentifier()) if app else None

    def windows(self) -> list[AXNode]:
        element = self._application()
        error, windows = self._ax.AXUIElementCopyAttributeValue(element, self._ax.kAXWindowsAttribute, None)
        if error:
            raise ControlNotFound(f"reading PowerPoint's windows failed with AX error {error}")
        return [LiveAXNode(window, self._ax, self._quartz) for window in (windows or [])]

    def click(self, x: float, y: float) -> None:
        """Post a global mouse click. This **moves the operator's pointer**."""
        quartz = self._quartz
        point = quartz.CGPointMake(x, y)
        for event_type in (
            quartz.kCGEventMouseMoved,
            quartz.kCGEventLeftMouseDown,
            quartz.kCGEventLeftMouseUp,
        ):
            event = quartz.CGEventCreateMouseEvent(None, event_type, point, quartz.kCGMouseButtonLeft)
            quartz.CGEventPost(quartz.kCGHIDEventTap, event)
            time.sleep(0.03)

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


# --- CLI --------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gui_capture.py",
        description=(
            "Development-only accessibility capture driver for PowerPoint animation values. "
            "It MOVES THE REAL POINTER to click the slide canvas and refuses to start unless "
            "PowerPoint is frontmost showing the expected capture deck."
        ),
        epilog=(
            f"Sends nothing without {DRIVE_TOKEN}. sdpm's runtime, CLI, MCP servers and tests "
            "never invoke this module."
        ),
    )
    parser.add_argument("--plan", type=Path, help="plan JSON from gui_capture_plan.py")
    parser.add_argument("--out", type=Path, help="output directory for the read-back and the package")
    parser.add_argument("--document", type=Path, help="the already-saved capture deck PowerPoint has open")
    parser.add_argument("--expect-document", help="window title to require; defaults to the document's stem")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="bound on every wait, in seconds")
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "re-capture targets that already have a record; regenerate the deck first, because a "
            "re-press replaces the shape's existing effect and the attribution needs a new one"
        ),
    )
    parser.add_argument("--pane-role", default=EDITOR_PANE_ROLE, help="AX role of the slide editor pane")
    parser.add_argument("--pane-frame", help="measured editor pane frame in screen points as x,y,w,h")
    parser.add_argument("--zoom", type=float, help="measured zoom factor, e.g. 0.92, when the status bar hides it")
    parser.add_argument(
        "--emit-record-schema",
        action="store_true",
        help="print the read-back record shape and exit, without touching PowerPoint",
    )
    parser.add_argument(
        DRIVE_TOKEN,
        dest="consent",
        action="store_true",
        help="required consent: drive the running PowerPoint through the accessibility API",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.emit_record_schema:
        example = capture_record(
            {"key": "animation.gallery.entrance.flyIn", "slideIndex": 1,
             "guiPath": ["Animations", "Entrance Effects", "Fly In"]},
            captured_at="1970-01-01T00:00:00Z",
        )
        print(json.dumps({"application": application_record(None), "capture": example}, indent=2))
        return 0

    missing = [name for name in ("plan", "out", "document") if getattr(args, name) is None]
    if missing:
        print(f"FAIL: --{', --'.join(missing)} required", file=sys.stderr)
        return 2
    if not args.consent:
        print(
            f"FAIL: refusing to drive PowerPoint without {DRIVE_TOKEN}. This driver presses ribbon "
            "controls and moves the real pointer in the frontmost application.",
            file=sys.stderr,
        )
        return 2

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    try:
        pane = parse_pane_frame(args.pane_frame)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    try:
        plan_shape_names(plan)
    except DriverRefusal as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    settings = CaptureSettings(
        out_dir=args.out,
        document=args.document,
        expect_document=args.expect_document,
        timeout=args.timeout,
        force=args.force,
        pane_role=args.pane_role,
        pane=pane,
        zoom=args.zoom,
    )
    if not settings.document.exists():
        print(f"FAIL: no capture deck at {settings.document}", file=sys.stderr)
        return 1

    try:
        backend: AXBackend = LiveAXBackend()
    except ImportError as exc:
        print(
            f"FAIL: the accessibility bindings are unavailable ({exc}). Run with: uv run "
            "--with pyobjc-framework-ApplicationServices --with pyobjc-framework-Cocoa "
            "--with pyobjc-framework-Quartz",
            file=sys.stderr,
        )
        return 1

    try:
        summary = run_capture(plan, settings, backend, version=read_application_version())
    except DriverRefusal as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
