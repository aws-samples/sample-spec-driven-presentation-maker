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
slide**, and a target is selected through that shape's own Selection Pane row. Do not
reintroduce either function; ``tests/test_animation_gui_capture.py`` fails if their names
come back.

## What it assumes, measured rather than guessed

Every mechanic below is recorded in ``computer-use.md`` and is not re-derived here:

- A gallery press **replaces** the effect of the **selected shape** rather than adding
  one. That is what makes one slide of many shapes work: each target owns a shape, and
  each press lands on the shape whose row was selected.
- Tile indices shift as soon as a press scrolls a gallery, and galleries lazily
  materialize tiles. Nothing positional is ever cached: the tree is re-read and every
  control re-resolved **by title** immediately before each press.
- ``Effect Options`` and ``Path Animation`` open as their own AX windows, whose items
  are ``AXMenuButton``s activated with ``AXPress``.
- The ribbon exposes a read-back directly: the ``Start:`` popup's value and the
  ``Duration:`` incrementor's value. Both are recorded as evidence; neither is the gate.
- Canvas shapes have **no AX element**, but their **Selection Pane rows do**, and a row
  is how a shape is selected here. See the next section.

## There is no coordinate click here either, and that is the second deletion

Shape selection used to be a synthetic global mouse event at a point derived from the
package geometry, the live editor-pane frame and the live zoom. It never became
reliable. The operator watched a run and reported the pointer landing in the right place
while the shape stayed unselected, and the same click by hand always working. Pacing the
event — ``kCGMouseEventClickState``, a settle before the button-down, a hold, and a
0.35 s settle after the up — improved it without fixing it: the last run of that version
captured **2 of 12** attempted targets and recorded ``effectNotAdded`` with "no new
effect appeared" for the other ten, which is the signature of a click that did not
change the selection, so the gallery press replaced the *previously* selected shape's
effect.

The replacement needs no coordinates, no pointer and no timing. ``Home ▸ Arrange ▸
Selection Pane...`` opens an ``AXOutline`` in the document window carrying one ``AXRow``
per shape, in reverse z-order. A row has no ``AXPress`` — its actions are
``AXShowDefaultUI``, ``AXShowAlternateUI`` and a Rename — so it is selected by **setting
``AXSelected``**, the standard outline-row mechanism, and the row is then read back to
confirm.

A row is addressed by **index**, which is the shape's position in reverse z-order, read
offline from the package by :func:`shape_row_index`. It was addressed by name first, and
the name is still checked when the pane publishes one, but it cannot be the key: a row's
own ``title`` is ``None`` and its name is the ``value`` of a descendant ``AXStaticText``
that **only exists once the row has been scrolled into view**. One run's batches read 80
names, then 54, from the same 152 rows, and 11 targets were rejected as "no Selection
Pane row is named ..." for rows that were present and selectable throughout. What guards
the index is a count: the pane must publish exactly one row per shape on the slide, or
the selection refuses.

So ``read_canvas_geometry``, ``canvas_point``, ``read_shape_center_pt``, ``parse_zoom``,
``parse_pane_frame``, ``window_frame_to_screen``, the ``Frame`` type, ``AXNode.frame``,
``AXBackend.click``, ``EDITOR_PANE_ROLE``, ``EDITOR_PANE_TITLE_PREFIX`` and the
``--pane-frame`` / ``--pane-role`` / ``--zoom`` options are **gone**, not deprecated.
Nothing in the driver reads a frame or posts an event any more. Do not reintroduce a
coordinate click: 2 of 12 is what it was worth, and
``tests/test_animation_gui_capture.py`` fails if those names come back.

## Cost is a correctness property here, and it was measured

A run of the previous version captured **7 targets in 28 minutes** — about four minutes
each, every one correct and attributed. The Selection Pane mechanism worked; it was far
too slow to reach 76. Timed live against the real window, best of three:

    find_all_by_title(window, "Save")   one full window walk    6.4 s
    selection_outline(backend)                                 17.8 s
    walking only the outline (762 nodes)                        4.1 s
    row_names over 152 rows                                     4.3 s

The document window is **907 nodes, 762 of them the Selection Pane's rows**, and every
accessibility attribute read is an interprocess round trip, so a full walk is thousands
of them. The dominant cost was full-tree walking, not saving, and two things made it
worse than it had to be: ``document_window`` identified the ribbon-carrying window by
calling ``find_all_by_title`` on **each** of PowerPoint's four or five same-titled
windows — several full walks per call, from a function nearly every helper calls — and
every other lookup started at the window, so resolving a ribbon control traversed all
762 pane rows and resolving a row traversed the ribbon.

Four changes, in descending order of what they were worth:

1. **Lookups are scoped to a container.** ``Save`` is resolved in the window's
   ``AXToolbar``, every ribbon tab, gallery and read-back in the ribbon ``AXTabGroup``,
   and every pane row in the ``AXOutline``. A container is found by a search of the
   window's top levels that **stops at every container boundary** rather than descending
   through one, so it costs the window's structure instead of its contents. A scope that
   cannot be identified **raises** — it never widens back to the window, because a
   lookup that quietly walked everything is exactly what this removed.
2. **``document_window`` reads two levels.** The ribbon tab group is a top-level child,
   so the probe that tells the document window from its same-titled siblings is a
   depth-2 container search instead of a full walk per candidate.
3. **Containers are resolved once per stretch of work**, by :class:`Containers`, and
   dropped at **every** press, every ``AXSelected`` write and every poll of a bounded
   wait. The rule that a press is aimed by a title re-resolved immediately beforehand is
   untouched; what changed is that the re-resolution happens inside the container.
4. **One Save judges a batch of targets** rather than one. Worth the least of the four,
   because saving was never the dominant cost, and the only thing it gives up is stated
   in :func:`capture_batch` rather than implied.

## Attribution, not position, is the evidence

Because every target shares one slide, "slide N is target N" is no longer available —
and it was never worth much, since it survived no reordering and no mis-selected shape.
In its place each target is verified against the package it just saved: the slide must
have gained at least one effect, and **every** new effect's ``p:spTgt/@spid`` must be the
``p:cNvPr/@id`` of the shape the driver selected. A new effect on another shape is a
``rejected`` record naming **both** spids, not a pass; a press that added nothing is a
recorded failure. The record carries the shape name, the Selection Pane row it selected,
how the selection was made, the expected spid, the attributed spid and the new effect's
own ``p:cTn`` attributes, so merged evidence is per target even though ``--parse-oracle``
joins every record to the same slide.

This gate is unchanged by the move to the Selection Pane, deliberately: it is what
proved the click unreliable, and it is the only thing that makes a capture evidence.

This also makes the save part of the measurement rather than only crash insurance, so it
is no longer optional.

A batch of targets shares one save, and each is still attributed by **its own** ``spid``
against a real saved package: the batch adds the gate that no spid outside the batch may
have gained an effect, and a target whose own spid gained nothing is rejected on its own
with the rest of the batch still credited. What batching gives up is crash granularity
and the ability to separate two targets **inside** one batch that swapped effects;
``--batch-size 1`` gives both back at one save per target. :func:`capture_batch` says so
in full.

## It does not move the pointer

Every action the driver sends is an ``AXPress`` or a single ``AXSelected`` write, so the
**pointer is never moved and no mouse event is ever posted**. The operator's machine
stays usable, and a stray window in front of PowerPoint cannot swallow a click, because
there is no click, and a run needs neither focus nor the frontmost application, so the
operator keeps the screen while it works. The expected-document guard is enforced before
anything is sent: an ``AXPress`` goes to whichever window the title resolution found, and
a wrong document would mean pressing ribbon controls over the operator's own work.

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
      --with lxml \\
      python scripts/animation_catalog/gui_capture.py \\
        --plan plan.json --out /abs/out --document /abs/capture-deck.pptx --drive-powerpoint

Three dependencies, and that is the whole list. **Quartz is not among them**: the only
binding that needed it was the mouse event, and it went when the coordinate click did.
``lxml`` is: the package readers import it lazily inside the function, which keeps it off
the import path of ``--help``, and a run outside this repository's environment then fails
with ``ModuleNotFoundError: No module named 'lxml'`` at the first attribution unless the
invocation asks for it. Inside the repository ``uv run`` already provides it; naming it
costs nothing and makes the line correct anywhere.

``--help``, ``--emit-record-schema`` and every pure function here work without pyobjc;
the accessibility bindings are imported lazily inside the live backend so importing this
module never requires them and the unit tests run with a fake.
"""

from __future__ import annotations

import argparse
import json
import plistlib
import shutil
import sys
import time
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any,
    Callable,
    Iterator,
    Mapping,
    NamedTuple,
    Protocol,
    Sequence,
    runtime_checkable,
)

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

#: Quick Access toolbar button, pressed once per batch of targets.
SAVE_LABEL = "Save"

#: Bounds on a tree scan. Exceeding either is an error rather than a "not found", so a
#: truncated scan can never be mistaken for an absent control.
MAX_TREE_DEPTH = 40
MAX_TREE_NODES = 60_000

#: Default bound on every wait, in seconds. There is no unbounded wait anywhere.
DEFAULT_TIMEOUT = 8.0
POLL_INTERVAL = 0.2

#: How many targets are pressed before one Save judges them all. See :func:`capture_batch`
#: for what batching buys and what it gives up; ``--batch-size 1`` is the per-target save.
DEFAULT_BATCH_SIZE = 10

# --- the window's containers, which is what a lookup is scoped to -----------
# Measured live on 2026-11-01, best of three, against the real window:
#
#     find_all_by_title(window, "Save")   one full window walk    6.4 s
#     selection_outline(backend)                                 17.8 s
#     walking only the outline (762 nodes)                        4.1 s
#     row_names over 152 rows                                     4.3 s
#
# The document window is 907 nodes and 762 of them are the Selection Pane's rows, and
# every accessibility attribute read is an interprocess round trip, so a full walk is
# thousands of them. A run of that driver captured 7 targets in 28 minutes — every one
# correct and attributed, and four minutes each.
#
# The cost was never the saving. It was that every lookup walked the *whole* window:
# resolving a ribbon control traversed all 762 pane rows, resolving a pane row traversed
# the ribbon, and ``document_window`` walked each of PowerPoint's four or five
# same-titled windows looking for the one carrying the ribbon — several full walks per
# call, from a function nearly every helper calls.
#
# So a lookup now names the one container that is certain to hold what it wants, and a
# container is found by a search of the window's top levels that never descends into a
# container. A scope that is wrong raises; it never silently widens back to the window.

#: Holds ``Save``.
TOOLBAR_ROLE = "AXToolbar"

#: Holds the ribbon: the tab strip, and the active tab's command galleries beneath it.
RIBBON_ROLE = "AXTabGroup"

#: Depth bound on a container search, as a backstop to the pruning above. The containers
#: sit in the window's top few levels; a bound rather than no bound means a tree that is
#: not shaped as measured fails loudly instead of walking everything.
CONTAINER_DEPTH = 8

#: How many pages a gallery may be turned in each direction while looking for one tile.
#: The Entrance gallery is 33 effects shown 25 at a time; eight each way is room for a
#: gallery three times that and still a bound, so a tile that is genuinely absent costs a
#: bounded number of presses rather than the whole timeout spent paging.
MAX_GALLERY_PAGES = 8

#: The ribbon's own gallery pagers, as titles. A gallery shows a window of its effects —
#: the Entrance gallery published ``Appear`` through ``Whip`` while ``Grow  Turn``,
#: ``Stretch`` and ``Zoom`` sat outside it — and these two buttons are what move it.
#: ``AXScrollUpByPage`` / ``AXScrollDownByPage`` on the gallery's own ``AXScrollArea``
#: are **accepted and do nothing**: a run paged 8 each way and the tiles never appeared,
#: which is why the pagers are pressed by title instead. ``Previous`` is disabled at the
#: top, which is how the paging knows it has reached it.
GALLERY_PAGE_PREVIOUS = "Previous {gallery} gallery"
GALLERY_PAGE_NEXT = "Next {gallery} gallery"

#: Node bound on a container search. Smaller than :data:`MAX_TREE_NODES` on purpose: a
#: container search that visits thousands of nodes has stopped being a container search,
#: and finding that out is worth more than completing it.
MAX_CONTAINER_NODES = 4_000

#: Depth of the probe that tells the document window from PowerPoint's other same-titled
#: windows. The ribbon tab group is a top-level child, so two levels is enough, and that
#: is the whole point: this probe replaced a full walk of every candidate window.
RIBBON_PROBE_DEPTH = 2

#: A ribbon tab that is present whatever is selected and whatever tab is active. Used to
#: tell PowerPoint's two same-titled windows apart: only one of them carries the ribbon,
#: and it is also the tab the Selection Pane is opened from.
RIBBON_ANCHOR_TAB = "Home"

#: ``Home ▸ Arrange`` is an ``AXMenuButton``; pressing it opens a window titled
#: ``Arrange`` holding an ``AXMenuButton`` titled ``Selection Pane...``, and pressing
#: *that* opens the pane inside the document window that carries the ribbon. Walked by
#: :func:`press_path`, so each step is resolved by title against a fresh read.
SELECTION_PANE_PATH = (RIBBON_ANCHOR_TAB, "Arrange", "Selection Pane...")

#: The pane itself, and the row and label roles inside it. A row's own ``title`` is
#: ``None``: the shape's name is the ``value`` of a descendant ``AXStaticText``. The
#: outline is also the window's third container, and the large one: 762 of the live
#: window's 907 nodes are inside it.
SELECTION_PANE_ROLE = "AXOutline"
SELECTION_ROW_ROLE = "AXRow"
SELECTION_LABEL_ROLE = "AXStaticText"

#: Every container role. A container search stops at each of these: the one it wants is
#: returned without being descended into, and any other is pruned, because nothing above
#: a container is reachable only through one. This is what keeps the search proportional
#: to the window's structure rather than to its contents — it is the Selection Pane's
#: 762 rows that make a full walk expensive, and they all sit inside one container.
CONTAINER_ROLES = (TOOLBAR_ROLE, RIBBON_ROLE, SELECTION_PANE_ROLE)

#: A child title that identifies the one container of a role worth having, for the roles
#: that turn out not to be unique. The Selection Pane brings its own ``AXTabGroup`` with
#: it, so the ribbon is the tab group carrying the ribbon's own first tab.
CONTAINER_ANCHORS = {RIBBON_ROLE: RIBBON_ANCHOR_TAB}

#: Recorded per target so a merged evidence file says how each capture was driven. The
#: previous value of this field was a click point.
SELECTED_BY = "selectionPaneRow"

#: Windows that are **not** the document window. Each is a transient panel PowerPoint
#: publishes as its own ``AXWindow``: two from the Animations tab, and the ``Arrange``
#: menu the Selection Pane is opened from. Listing ``Arrange`` here keeps
#: :func:`document_window` from mistaking it for the deck while it is open.
POPUP_WINDOW_TITLES = frozenset({"Effect Options", "Path Animation", SELECTION_PANE_PATH[1]})


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
    """A shape the package does not identify: no such name, or no ``p:cNvPr/@id``.

    The name is historical — it covered screen geometry too, back when a shape's centre
    was mapped to a click point. The kind is kept as it is because capture records
    already carry it; what it means now is "the package cannot tell me which shape this
    target is".
    """

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
    """The press added an effect, but to a shape other than the one that was selected."""

    kind = "effectMisattributed"


# --- what the package says about a shape ------------------------------------
# There is deliberately no slide size, no EMU conversion and no shape centre here. The
# driver no longer computes a point on the canvas; it selects a shape by name through its
# Selection Pane row. See the module docstring for the 2-of-12 run that ended the click.
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
    """Return every named shape on one slide with its ``spid``.

    The ``spid`` is the shape's own ``p:cNvPr/@id``, which is what PowerPoint writes into
    ``p:spTgt`` when it animates that shape — so the name selects the shape in the
    Selection Pane and the ``spid`` is the identity the capture is attributed to. The two
    are **not** the same number: the generated deck's first shape is named ``Rounded
    Rectangle 1`` and carries ``id="2"``.
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
        shapes.append({"name": props.get("name"), "spid": props.get("id")})
    return shapes


def _shape_by_name(package: Path, slide_index: int, shape_name: str) -> dict[str, Any]:
    """Return one named shape, or fail listing the names the slide does carry.

    A shape the driver cannot find by name is an error rather than a guess: the name is
    both what the Selection Pane row is matched on and what the attribution's expected
    ``spid`` is read from, so an approximate match would attribute one shape's effect to
    another's record.
    """
    shapes = read_slide_shapes(package, slide_index)
    found = [shape for shape in shapes if shape["name"] == shape_name]
    if len(found) > 1:
        raise GeometryError(
            f"slide {slide_index} has {len(found)} shapes named {shape_name!r}; a press could not "
            "be attributed to one of them"
        )
    if not found:
        raise GeometryError(
            f"no shape named {shape_name!r} on slide {slide_index}; shapes present: "
            f"{sorted({shape['name'] for shape in shapes})}"
        )
    return found[0]


def read_shape_spid(package: Path, slide_index: int, shape_name: str) -> str:
    """Return the named shape's ``p:cNvPr/@id``, the spid its effects will carry."""
    spid = _shape_by_name(package, slide_index, shape_name)["spid"]
    if not spid:
        raise GeometryError(f"shape {shape_name!r} on slide {slide_index} has no p:cNvPr/@id")
    return str(spid)


def shape_row_index(package: Path, slide_index: int, shape_name: str) -> tuple[int, int]:
    """Return the shape's Selection Pane row index, and how many rows to expect.

    The pane lists one row per shape in **reverse z-order** — the slide part's last
    ``p:sp`` is row 0 — so a row index is a fact about the package, read offline, rather
    than something searched for in the tree. Measured against the live pane twice: 152
    rows, 152 agreements, 0 mismatches.

    This exists because a row's **name** is not always readable. ``AXRows`` publishes
    every row, but a row that has never been scrolled into view publishes no
    ``AXStaticText`` descendant to read a name from, so the earlier by-name lookup saw 80
    readable names in one batch and 54 in the next and rejected 11 targets as "no
    Selection Pane row is named ..." for rows that were there the whole time. The count
    is returned with the index so the caller can refuse when the pane does not publish
    one row per shape, instead of selecting whatever sits at that offset.
    """
    shapes = read_slide_shapes(package, slide_index)
    found = [index for index, shape in enumerate(shapes) if shape["name"] == shape_name]
    if len(found) > 1:
        raise GeometryError(
            f"slide {slide_index} has {len(found)} shapes named {shape_name!r}; neither their "
            "rows nor their effects could be told apart"
        )
    if not found:
        raise GeometryError(
            f"no shape named {shape_name!r} on slide {slide_index}; shapes present: "
            f"{sorted({shape['name'] for shape in shapes})}"
        )
    return len(shapes) - 1 - found[0], len(shapes)


#: How many times a value press is retried when the package says it changed
#: nothing. A press inside the ``Effect Options`` window is intermittent in a
#: way the ribbon's own presses are not, and the worst case keeps rising as
#: more values are measured: ``Half Spin`` took on the second attempt,
#: ``Quarter Spin`` and ``From Right`` on the third, and ``Stretch``'s
#: ``From Top`` on the **fourth** — which was the cap at the time and so came
#: within one attempt of being recorded as a failure. Raised to 8 for that
#: reason, and overridable per run, because this is a bound on an observed
#: flake rate rather than a measured property of the application.
DEFAULT_VALUE_PRESS_ATTEMPTS = 8


def effect_signatures(package: Path, slide_index: int, spid: str) -> list[str]:
    """Return a comparable signature per effect on one shape, behaviours included.

    The ``p:cTn`` alone is not enough and that is the whole reason this exists:
    Grow/Shrink's ``Huge`` and its default carry **identical** preset
    attributes and differ only in ``p:animScale``'s ``p:by``. A gate that
    compared ``p:cTn`` would call a press that changed the amount "no change".

    Node ``id`` is excluded, because PowerPoint renumbers on save and every
    effect would then differ from itself.
    """
    from lxml import etree

    root = _read_slide_part(package, slide_index)
    live = _live_effect_nodes(root)
    signatures: list[str] = []
    for element in root.iter():
        if etree.QName(element).localname != "cTn" or element.get("presetID") is None:
            continue
        if element not in live:
            continue
        spids = {
            target.get("spid")
            for target in element.iter()
            if etree.QName(target).localname == "spTgt"
        }
        if spids != {spid}:
            continue
        parts: list[str] = [
            f"{name}={value}"
            for name, value in sorted(element.attrib.items())
            if name != "id"
        ]
        for node in element.iter():
            local = etree.QName(node).localname
            if local == "cTn" and node is element:
                continue
            parts.append(
                local
                + "("
                + ",".join(
                    f"{name}={value}"
                    for name, value in sorted(node.attrib.items())
                    if name != "id"
                )
                + ")"
                + ((node.text or "").strip())
            )
        signatures.append("|".join(parts))
    return sorted(signatures)


def _live_effect_nodes(root: Any) -> set[Any]:
    """Return the effect nodes a conforming consumer actually applies.

    ``mc:AlternateContent`` carries the same effect twice — once in the
    ``mc:Choice`` that needs an extension, once in the ``mc:Fallback`` that does
    not — and only one is ever live. Counting both made one effect read as two,
    which would be harmless if the duplication were stable. It is not: measured
    2026-11-02, clearing ``Bounce End`` removed ``p14:presetBounceEnd`` and with
    it the whole ``AlternateContent``, so **every** effect's signature list went
    from two entries to one and all seven shapes reported a change for a press
    that touched one.

    That matters for the pane-setting gate specifically. Its stray-shape failure
    asks which shapes moved, so a save that restructures the package would
    accuse six shapes nobody pressed.
    """
    from lxml import etree

    live: set[Any] = set()
    for node in root.iter():
        local = etree.QName(node).localname
        if local != "cTn" or node.get("presetID") is None:
            continue
        inside_fallback = False
        parent = node.getparent()
        while parent is not None:
            if etree.QName(parent).localname == "Fallback":
                inside_fallback = True
                break
            parent = parent.getparent()
        if not inside_fallback:
            live.add(node)
    return live


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
    target shares a slide.

    The rule is unchanged by the move from a canvas click to a Selection Pane row: **at
    least one new effect, and every new effect on the shape that was selected**. It is
    not "exactly one", because a compound value writes several
    ``p:cTn`` nodes; a run rejected a correctly applied target reporting "0 before and 3
    after, spids that appeared: ['2']". Two failures are still refused, and they mean
    different things:

    - **nothing new appeared.** A selection that did not take looks exactly like this,
      because the press then *replaced* the previously selected shape's effect — which
      is how the coordinate click was caught, 10 of 12 targets at a time. So does a
      press that applied nothing. It is also what ``--force`` produces
      against an already-captured deck, which is why ``--force`` wants a freshly
      generated one: crediting that would rest on a *previous* run's evidence.
    - **something appeared on another shape.** The value was applied, just not to this
      target, so the record names both spids rather than crediting the wrong key.
    """
    added = _spid_counts(after) - _spid_counts(before)
    if not added:
        vanished = sorted(str(spid) for spid in _spid_counts(before) - _spid_counts(after))
        raise EffectNotAdded(
            f"the slide carried {len(before)} animation effects before the press and {len(after)} "
            f"after it, and no new effect appeared; spids that vanished: {vanished or ['none']}. "
            f"The selected shape's spid is {expected_spid!r}, so either the selection did not "
            "take and the press replaced another shape's effect, or the press applied nothing "
            "at all",
            expectedSpid=expected_spid,
            effectsBefore=len(before),
            effectsAfter=len(after),
            appearedSpids=[],
            vanishedSpids=vanished,
        )
    # A gallery press can write MORE than one effect node: a compound value such as an
    # emphasis colour change arrives as several ``p:cTn`` carrying a ``presetClass``.
    # Measured: a run reported "0 before and 3 after, spids that appeared: ['2']" and
    # rejected a target whose value had in fact been applied to exactly the right shape.
    # So the gate is not "exactly one more effect" — it is "at least one new effect, and
    # every new effect belongs to the shape that was selected". That still refuses the two
    # failures worth refusing: nothing appeared, or something appeared elsewhere.
    # Compared as the values the package carries, not as strings: an effect whose
    # ``p:spTgt`` names two shapes has ``spid`` ``None``, and stringifying it first loses
    # the ability to find that effect again and so loses the spids it actually named.
    foreign = sorted((spid for spid in added if spid != expected_spid), key=str)
    if foreign:
        effect = next(
            (candidate for candidate in after if candidate["spid"] in set(foreign)), None
        )
        spid = foreign[0]
        raise EffectMisattributed(
            f"the press added an effect targeting shape spid {spid!r} (p:spTgt spids "
            f"{(effect or {}).get('spids')}), but the driver selected the shape with spid "
            f"{expected_spid!r}; the effect belongs to another shape, so this target is not captured",
            attributedSpid=spid,
            expectedSpid=expected_spid,
            spTgtSpids=(effect or {}).get("spids"),
            effectCTn=(effect or {}).get("cTn"),
        )
    # Every new effect belongs to the selected shape. When a compound value wrote several,
    # the first is returned as the representative and the count is carried so a reader
    # knows the value is not a single node.
    mine = [candidate for candidate in after if candidate["spid"] == expected_spid]
    if not mine:  # pragma: no cover - `added` containing the spid makes this impossible
        raise EffectNotAdded(f"no effect in the saved slide targets spid {expected_spid!r}")
    effect = dict(mine[0])
    effect["newEffectCount"] = added[expected_spid]
    # Every one of the shape's effects, not only the representative. A target
    # with a prerequisite leaves **two**: the tile's default and a second one
    # carrying the pressed value, which is the application's behaviour and not a
    # selection bug (re-selecting the shape to avoid it disables the control
    # outright). The driver cannot say which is which — measured: Grow/Shrink's
    # Huge and its default have *identical* ``p:cTn``, and differ only in
    # ``p:by`` — so it records both and the offline side, which holds every
    # tile's measured default already, tells them apart.
    effect["allCTns"] = [dict(candidate["cTn"]) for candidate in mine]
    return effect


def attribute_batch(
    before: Sequence[dict[str, Any]],
    after: Sequence[dict[str, Any]],
    expected_spids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Attribute one save to every target in a batch, by each target's own ``spid``.

    Returns ``spid -> effect`` for the targets that gained something. A target whose spid
    is absent from the result gained nothing and is the caller's to reject **on its own**,
    with the rest of the batch still credited.

    Raised failures are batch-level, and there is exactly one of them: an **added spid
    that belongs to no target in the batch**. That is a press the driver cannot account
    for — an effect on a shape nobody selected — and crediting the batch around it would
    be asserting that the other presses landed correctly on the strength of a package
    that says something else happened. The failure names the stray spid.

    A batch of one delegates to :func:`attribute_new_effect`, deliberately rather than
    coincidentally: ``--batch-size 1`` is then not a second code path that behaves
    similarly, it **is** the per-target gate, with the same failures, the same messages
    and the same ``detail``.

    What a batch of n cannot do is separate two targets **inside** it that swapped
    effects: if each of them gained one effect, the package cannot say whose value is
    whose. Per-target saving could, which is what ``--batch-size 1`` is for. See
    :func:`capture_batch` for why the trade is worth making.
    """
    unique = list(dict.fromkeys(expected_spids))
    if not unique:
        return {}
    if len(unique) == 1:
        return {unique[0]: attribute_new_effect(before, after, unique[0])}

    added = _spid_counts(after) - _spid_counts(before)
    expected = set(unique)
    stray = sorted((spid for spid in added if spid not in expected), key=str)
    if stray:
        foreign = [
            candidate
            for candidate in after
            if candidate["spid"] in set(stray) or (None in stray and candidate["spid"] is None)
        ]
        raise EffectMisattributed(
            f"the batch's save added effects targeting shape spids {stray}, and no target in the "
            f"batch selected any of them; the batch selected {sorted(expected)}. An effect on a "
            "shape nobody selected means a press landed somewhere this run cannot account for, so "
            "the whole batch is refused rather than credited around it",
            attributedSpid=stray[0],
            straySpids=stray,
            expectedSpids=sorted(expected),
            spTgtSpids=sorted({spid for effect in foreign for spid in effect["spids"]}),
            strayEffectCTn=[effect["cTn"] for effect in foreign],
        )

    credited: dict[str, dict[str, Any]] = {}
    for spid in unique:
        if not added[spid]:
            continue
        mine = [candidate for candidate in after if candidate["spid"] == spid]
        effect = dict(mine[0])
        effect["newEffectCount"] = added[spid]
        effect["allCTns"] = [dict(candidate["cTn"]) for candidate in mine]
        credited[spid] = effect
    return credited


def attribute_modified_batch(
    before: Mapping[str, Sequence[str]],
    after: Mapping[str, Sequence[str]],
    expected_spids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Attribute a save that **changed** effects rather than adding any.

    Every gate here so far asks whether a shape *gained* an effect, which is the
    right question for a gallery tile. A pane setting is the other kind of
    press: Smooth Start, an after-animation value, Bounce End — each edits the
    effect already on the shape, so the count does not move and
    :func:`attribute_batch` would call a landed press "no change".

    The evidence is therefore the effect's own signature, which already carries
    its attributes **and** its behaviour payloads — the same string
    :func:`effect_signatures` built so that Grow/Shrink's ``Huge`` could be told
    from its default. ``before``/``after`` map spid to that shape's signatures.

    Returns ``spid -> {before, after}`` for the targets whose signatures moved. A
    target whose signatures are unchanged is absent and is the caller's to
    reject on its own, with the rest of the batch still credited.

    One batch-level failure, and it is the one that matters for this surface: a
    **shape outside the batch whose signatures moved**. The Animation Pane's
    `Delete` button sits beside the controls being pressed, and a ref landing on
    it removes effects rather than editing them — that is exactly a change on a
    shape nobody selected, so the batch is refused and the stray spid named
    rather than the other presses credited around it.
    """
    unique = list(dict.fromkeys(expected_spids))
    if not unique:
        return {}
    expected = set(unique)
    moved = {
        spid
        for spid in set(before) | set(after)
        if list(before.get(spid, ())) != list(after.get(spid, ()))
    }
    stray = sorted(moved - expected, key=str)
    if stray:
        raise EffectMisattributed(
            f"the batch's save changed the effects on shape spids {stray}, and no target in the "
            f"batch selected any of them; the batch selected {sorted(expected)}. A pane setting "
            "edits the effect on the selected shape, so a change elsewhere means a press landed "
            "somewhere this run cannot account for — the Animation Pane's Delete button sits "
            "beside these controls — and the whole batch is refused rather than credited around it",
            attributedSpid=stray[0],
            straySpids=stray,
            expectedSpids=sorted(expected),
            strayBefore={spid: list(before.get(spid, ())) for spid in stray},
            strayAfter={spid: list(after.get(spid, ())) for spid in stray},
        )
    return {
        spid: {
            "spid": spid,
            "signaturesBefore": list(before.get(spid, ())),
            "signaturesAfter": list(after.get(spid, ())),
        }
        for spid in unique
        if spid in moved
    }


def not_changed_in_batch(
    before: Mapping[str, Sequence[str]],
    after: Mapping[str, Sequence[str]],
    spid: str,
) -> TargetFailure:
    """Return the failure for a pane-setting target whose effect did not move."""
    return EffectNotAdded(
        f"the save left shape spid {spid}'s effect signatures unchanged, so the pane setting did "
        "not reach the effect; a press that lands on a disabled control, or on a control belonging "
        "to a different effect, looks exactly like this",
        attributedSpid=spid,
        signaturesBefore=list(before.get(spid, ())),
        signaturesAfter=list(after.get(spid, ())),
    )


def not_added_in_batch(
    before: Sequence[dict[str, Any]],
    after: Sequence[dict[str, Any]],
    expected_spid: str,
) -> EffectNotAdded:
    """The failure for one target of a batch whose own spid gained nothing.

    Worded as :func:`attribute_new_effect` words it, because it means the same thing: the
    press applied nothing, or it applied to a shape this target did not select. The
    counts are the batch's, which is what a reader has to know to interpret them — the
    slide went from n to n+k for k targets, and this target's own spid contributed none
    of it.
    """
    appeared = sorted(
        str(spid) for spid in (_spid_counts(after) - _spid_counts(before)) if spid is not None
    )
    vanished = sorted(str(spid) for spid in (_spid_counts(before) - _spid_counts(after)))
    return EffectNotAdded(
        f"the slide carried {len(before)} animation effects before this batch and {len(after)} "
        f"after its save, and no new effect appeared on spid {expected_spid!r}, which is the "
        f"shape this target selected; spids that did gain an effect: {appeared or ['none']}, "
        f"spids that vanished: {vanished or ['none']}. Either the press applied nothing or it "
        "applied to a shape this target did not select",
        expectedSpid=expected_spid,
        effectsBefore=len(before),
        effectsAfter=len(after),
        appearedSpids=appeared,
        vanishedSpids=vanished,
    )


# --- the accessibility layer, injectable ------------------------------------
@runtime_checkable
class AXNode(Protocol):
    """One accessibility element. The live and fake implementations share this shape.

    There is no ``frame`` reader: nothing here needs a rectangle any more, and the one
    thing that did — the canvas click — is gone. There is no general attribute setter
    either. ``set_selected`` is the only write, because an outline row is selected by
    setting ``AXSelected`` and that is the only attribute this driver ever writes.
    """

    @property
    def role(self) -> str: ...
    @property
    def title(self) -> str | None: ...
    @property
    def value(self) -> str | None: ...
    @property
    def enabled(self) -> bool: ...
    @property
    def selected(self) -> bool: ...
    @property
    def index(self) -> int | None: ...
    @property
    def children(self) -> Sequence[AXNode]: ...
    def press(self) -> None: ...
    def set_selected(self, selected: bool) -> None: ...
    def set_focused(self, focused: bool) -> None: ...


class AXBackend(Protocol):
    """Everything the driver needs from the host. Tests supply a fake for all of it.

    No ``click``: the driver posts no mouse events at all. See the module docstring.
    """

    def trusted(self) -> bool: ...
    def frontmost_bundle_id(self) -> str | None: ...
    def windows(self) -> list[AXNode]: ...
    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...

    # --- the keyboard, and the two reads that make it safe to use -----------
    #
    # One surface needs a key event: the Animation Pane's effect list, which no
    # accessibility write can select a row in. See `select_pane_effect`.
    #
    # `post_key` delivers to **the process owning the document window**, never to
    # whatever is frontmost. That is the whole reason it is safe: three decks
    # share one PowerPoint process on the measuring host, and other applications
    # are the operator's own work. A key that can only reach a named process
    # cannot be typed into either.
    #
    # The two reads are preconditions, not conveniences. A process receives a key
    # at its focused window and its focused element, so without them a press is
    # aimed at whatever happened to be in front.
    def focused_window_title(self) -> str | None: ...
    def focused_element_role(self) -> str | None: ...
    def post_key(self, keycode: int) -> None: ...


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
    """Return every element in ``root`` whose title matches ``title`` exactly.

    ``root`` is a **container**, not the window. Passing the window costs a full walk —
    6.4 s and several thousand interprocess reads live — which is what made the previous
    driver four minutes per target. See :func:`find_containers`.
    """
    allowed = set(roles) if roles else None
    return [
        node
        for node in walk(root)
        if node.title == title and (allowed is None or node.role in allowed)
    ]


def find_containers(
    window: AXNode,
    role: str,
    *,
    title: str | None = None,
    reject_title: str | None = None,
    max_depth: int = CONTAINER_DEPTH,
    max_nodes: int = MAX_CONTAINER_NODES,
) -> list[AXNode]:
    """Return the window's containers of one role, without ever looking inside one.

    ``title`` narrows by the container's own name, which the Animation Pane needs
    and the ribbon and toolbar do not: the pane is an ``AXGroup``, and a window
    holds many of those, so role alone is ambiguous rather than selective. The
    pane carries the title ``Animations``, so naming it keeps the rule this
    search exists for — start at the smallest container **certain** to hold the
    thing — instead of relaxing to a walk.

    This is the search that replaced walking the window. It descends from the window's
    own children, stops at every node whose role is in :data:`CONTAINER_ROLES` — keeping
    the one it wants, pruning the rest — and is bounded in depth and node count as a
    backstop. The cost is therefore the window's structure, a few dozen nodes, rather
    than its contents: the Selection Pane's 762 rows are behind a container boundary and
    are never crossed to find the ribbon or the toolbar.

    Exceeding a bound raises, exactly as :func:`walk` does, so a window that is not
    shaped as measured fails loudly rather than being reported as missing a container.
    """
    found: list[AXNode] = []
    stack: list[tuple[AXNode, int]] = [(child, 1) for child in reversed(list(window.children))]
    seen = 1
    while stack:
        node, depth = stack.pop()
        seen += 1
        if seen > max_nodes:
            raise TreeTooLarge(
                f"the search for a {role} in the window visited more than {max_nodes} nodes; the "
                "window is not shaped as measured and a container search has become a tree walk"
            )
        node_role = node.role
        if node_role == role:
            node_title = node.title
            wanted = title is None or node_title == title
            if wanted and (reject_title is None or node_title != reject_title):
                found.append(node)
                continue
            # A same-role container with a different name is not the one being
            # asked for, and its contents are still behind a boundary — so it is
            # pruned like any other container rather than descended into.
            continue
        if node_role in CONTAINER_ROLES or depth >= max_depth:
            continue
        stack.extend((child, depth + 1) for child in reversed(list(node.children)))
    return found


def window_container(
    window: AXNode,
    role: str,
    *,
    what: str,
    absent: str | None = None,
    title: str | None = None,
    reject_title: str | None = None,
) -> AXNode:
    """Resolve the one container of a role, or fail saying which it is.

    Absent and ambiguous are kept exactly as :func:`_resolve_in` keeps them, and for the
    same reason: a scope that cannot be identified must raise rather than widen to the
    window, because a lookup that quietly walked everything is the cost this whole
    mechanism exists to remove and it would come back unnoticed.
    """
    found = find_containers(window, role, title=title, reject_title=reject_title)
    if not found:
        raise ControlNotFound(
            absent
            or (
                f"the document window holds no {role}, so {what} cannot be looked up; the roles "
                f"directly under the window are {sorted({child.role for child in window.children})}"
            )
        )
    if len(found) > 1:
        # Opening the Selection Pane adds a SECOND AXTabGroup to the window — measured
        # as `Tab bar, 1 tabs`, holding 'Selection Pane' and 'Close Selection Pane' —
        # so the role alone stopped identifying the ribbon and every target failed with
        # ambiguousControl. A role that can appear twice names a child title that only
        # the one we want carries; the ribbon's is its first tab.
        anchor = CONTAINER_ANCHORS.get(role)
        if anchor is not None:
            anchored = [
                node
                for node in found
                if any((child.title or "") == anchor for child in node.children)
            ]
            if len(anchored) == 1:
                return anchored[0]
        raise AmbiguousControl(
            f"the document window holds {len(found)} {role} elements and "
            + (
                f"{'none' if not anchor else 'more than one'} of them has a child titled "
                f"{anchor!r}"
                if anchor is not None
                else "no child title distinguishes them"
            )
            + f"; refusing to guess which one is {what}"
        )
    return found[0]


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

    Every poll starts by dropping whatever the caller's :class:`Containers` holds. A
    wait exists because the tree is expected to change, so reusing a previous poll's
    window or container would make the poll ask the same question of the same read and
    spin to the deadline. Within one poll the elements are still shared, which is where
    the saving is: a predicate that tries several titles resolves its container once.
    """
    view = held(backend)
    deadline = backend.now() + timeout
    while True:
        view.stale()
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
    document window is identified by being none of them. PowerPoint then publishes four
    or five windows carrying the **same document title** and only one of them carries the
    ribbon; taking the first non-popup picked them inconsistently, and one run reached
    Save on its first target and then failed every later one with "no element titled
    'Animations'".

    How that one is identified is the change that matters most for cost. It used to be
    ``find_all_by_title(window, "Home")`` **per candidate window** — several 6.4 s full
    walks on every call, from a function nearly every helper calls. The ribbon tab group
    is a top-level child, so the probe is now two levels deep and reads a few dozen
    attributes per candidate instead of a few thousand.

    The result is still not cached here: ``computer-use.md`` records that a popup is
    invisible to the read that opened it and that element identity does not survive
    between reads. :class:`Containers` is what holds it, for one stretch of work at a
    time, and drops it at every action.
    """
    windows = backend.windows()
    if not windows:
        raise ControlNotFound("PowerPoint reports no windows")
    candidates = [window for window in windows if (window.title or "") not in POPUP_WINDOW_TITLES]
    if not candidates:
        raise ControlNotFound("every PowerPoint window is a popup; no document window")
    # Direct children first, and only then two levels. The tab group was measured as a
    # top-level child, so the first pass almost always answers and costs one ``children``
    # read plus one ``role`` read per child; the second exists so a window one level
    # deeper than measured is still found rather than silently losing the ribbon.
    for depth in (1, RIBBON_PROBE_DEPTH):
        with_ribbon = [
            window
            for window in candidates
            if find_containers(window, RIBBON_ROLE, max_depth=depth)
        ]
        if with_ribbon:
            return with_ribbon[0]
    return candidates[0]


def find_window(backend: AXBackend, title: str) -> AXNode | None:
    """Return the window titled ``title`` from a fresh read, or None."""
    return next((window for window in backend.windows() if window.title == title), None)


class Containers:
    """The document window and its containers, held for one stretch of work.

    An element reference is usable for the read that produced it, and the lookups that
    make up one step of a target's work — a reachability probe, the polls of a bounded
    wait, a row resolution — all start from the same two or three elements. Resolving
    them once and sharing them is what stops ``document_window`` and the container search
    from being repeated a dozen times per target.

    What it must not do is outlive an action. A press can scroll a gallery and renumber
    its tiles, and PowerPoint rebuilds its elements between reads, so every press, every
    ``AXSelected`` write and every poll of :func:`wait_until` calls :meth:`stale` and the
    next lookup reads again. **The rule that a press is aimed by a title re-resolved
    immediately beforehand is therefore intact**: a press's own resolution always follows
    an invalidation. What got cheaper is where that re-resolution looks — inside the
    container rather than across the window.

    It satisfies :class:`AXBackend` by delegation, so every function here still takes a
    backend and a caller holding one of these passes it straight through. :func:`held`
    is how a function gets the caller's instance when there is one and its own when
    there is not.
    """

    __slots__ = ("_backend", "_window", "_containers", "_named")

    def __init__(self, backend: AXBackend) -> None:
        self._backend = backend
        self._window: AXNode | None = None
        self._containers: dict[str, AXNode] = {}
        self._named: dict[str, AXNode] = {}

    # --- the backend protocol, delegated ---------------------------------
    def trusted(self) -> bool:
        return self._backend.trusted()

    def frontmost_bundle_id(self) -> str | None:
        return self._backend.frontmost_bundle_id()

    def windows(self) -> list[AXNode]:
        return self._backend.windows()

    def now(self) -> float:
        return self._backend.now()

    def sleep(self, seconds: float) -> None:
        self._backend.sleep(seconds)

    # Delegated and deliberately **not** held. These two are the preconditions for
    # sending a key, so a cached answer would be the one thing worse than no answer:
    # it would report focus as it was before the operator clicked elsewhere.
    def focused_window_title(self) -> str | None:
        return self._backend.focused_window_title()

    def focused_element_role(self) -> str | None:
        return self._backend.focused_element_role()

    def post_key(self, keycode: int) -> None:
        self._backend.post_key(keycode)

    # --- what it holds ----------------------------------------------------
    def stale(self) -> None:
        """Drop everything held. Called after every action and before every poll."""
        self._window = None
        self._containers.clear()
        self._named.clear()

    def window(self) -> AXNode:
        if self._window is None:
            self._window = document_window(self._backend)
        return self._window

    def named_window(self, title: str) -> AXNode:
        held_window = self._named.get(title)
        if held_window is None:
            found = find_window(self._backend, title)
            if found is None:
                raise ControlNotFound(f"no window titled {title!r}")
            self._named[title] = held_window = found
        return held_window

    def container(
        self,
        role: str,
        *,
        what: str,
        absent: str | None = None,
        title: str | None = None,
        reject_title: str | None = None,
    ) -> AXNode:
        # Keyed by role **and** the title filters: the Animation Pane shares
        # ``AXGroup`` with other containers and its effect list shares
        # ``AXOutline`` with the Selection Pane, so holding one under the bare
        # role would hand the wrong node back to a later lookup.
        token = (role, title, reject_title)
        found = self._containers.get(token)
        if found is None:
            # Only a success is held. A container that is absent must be looked for again
            # on the next call, because "absent" is how an unopened Selection Pane reads
            # and the whole point of opening it is that the answer changes.
            found = window_container(
                self.window(),
                role,
                what=what,
                absent=absent,
                title=title,
                reject_title=reject_title,
            )
            self._containers[token] = found
        return found


def held(backend: AXBackend) -> Containers:
    """Return the caller's :class:`Containers` if it has one, or a fresh one.

    A function called with a raw backend gets its own, so nothing is shared further than
    the caller meant; a function called with the caller's shares it, which is how one
    target's work resolves the window and its containers once rather than per lookup.
    """
    return backend if isinstance(backend, Containers) else Containers(backend)


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
    """Where to look: a window, the container inside it, then titles.

    A scope is re-resolved from a fresh read before every press, because PowerPoint
    rebuilds its accessibility elements between reads and a press can scroll a gallery
    and renumber everything in it. Holding the scope as a role and titles rather than as
    elements is what makes "never cache a positional index" structural rather than a
    rule to remember.

    ``container_role`` is the part that made the driver fast enough to finish. Without
    it a lookup starts at the window, and resolving a ribbon tile then traverses all 762
    Selection Pane rows while resolving a row traverses the ribbon. With it a lookup
    starts at the smallest container that is **certain** to hold the thing, and a
    container that is absent or ambiguous raises rather than widening back to the window.
    """

    window_title: str | None = None
    container_role: str | None = None
    descend: tuple[str, ...] = ()
    #: The container's own name, when its role is not selective on its own. The
    #: Animation Pane is an ``AXGroup`` and a window holds many, so the pane is
    #: reached by naming it rather than by relaxing the container rule.
    container_title: str | None = None

    def inside(self, title: str) -> Scope:
        return Scope(
            self.window_title, self.container_role, self.descend + (title,), self.container_title
        )

    def in_window(self, title: str) -> Scope:
        # A popup — ``Effect Options``, ``Path Animation``, ``Arrange`` — is a window of a
        # handful of menu buttons, so it has no container to narrow to and needs none.
        return Scope(title, None, ())

    def describe(self) -> str:
        container = self.container_role
        if container and self.container_title:
            container = f"{container}[{self.container_title}]"
        parts = [self.window_title or "document window", container, *self.descend]
        return " > ".join(part for part in parts if part)


#: The ribbon: every tab, and every gallery and labelled read-back on the active tab.
RIBBON_SCOPE = Scope(container_role=RIBBON_ROLE)

#: The Quick Access toolbar, which holds exactly one control this driver wants.
TOOLBAR_SCOPE = Scope(container_role=TOOLBAR_ROLE)

#: The Animation Pane's settings view, where the per-effect options live. Read
#: 2026-11-02: PowerPoint for Mac 16.113.1 has **no** "Effect Options" dialog
#: with Effect / Timing tabs. Those settings sit inline in the pane as
#: collapsible sections under a scroll area, so the route is the pane itself and
#: not a window — see ``computer-use.md``, "The per-effect settings surface".
#:
#: The pane's own tab is called ``Animations``, not "Animation Pane", and the
#: ribbon control that opens it is a **switch**.
ANIMATION_PANE_TAB = "Animations"
ANIMATION_PANE_SWITCH = "Animation Pane"

#: The Selection Pane's own tab, which shares the one side-pane tab bar. Named
#: because the state that matters is both panes open with one behind the other,
#: and a message that can say which pane is in front is the difference between
#: "not found" and "select the other tab". Measured 2026-11-02 alongside
#: ``Close Selection Pane``, an ``AXButton`` the bar carries per tab.
SELECTION_PANE_TAB = "Selection Pane"

#: The four sections the 2026-11-02 read returned, each answering ``AXPress``.
#: Which sections exist depends on the selection, so a section this driver asks
#: for and does not find is a failure rather than a reason to look elsewhere.
PANE_SECTIONS = ("Effect Options", "Timing", "Text Animations", "Triggers")

#: The pane is an ``AXGroup`` titled ``Animations``, read 2026-11-02. It is
#: named as a container for the same reason the ribbon and the Selection Pane
#: are: a lookup that starts at the document window traverses every Selection
#: Pane row on the way, and this surface is pressed once per target.
#: A pane popup and the items it attaches when pressed. Measured 2026-11-02:
#: the menu arrives as the popup's **own child**, not as a new window, which is
#: how the ribbon's popups behave and the reason this needed its own primitive.
#: Both roles, because the ``After animation`` menu mixes them: its four named
#: choices are ``AXMenuItem`` while its eight scheme colours are ``AXButton``
#: inside a colour-swatch group. Looking for menu items alone found the four and
#: timed out on the eight.
POPUP_ROLE = "AXPopUpButton"
MENU_ITEM_ROLES = ("AXMenuItem", "AXButton")

#: The Animation Pane's effect list, which shares ``AXOutline`` with the
#: Selection Pane. Named here so the Selection Pane can be identified by
#: excluding it; see :func:`selection_outline`.
ANIMATION_LIST_TITLE = "Animation list"

#: Where an effect row's identity lives. A Selection Pane row is named by a
#: descendant ``AXStaticText``; an effect row is not, and a search for one comes
#: back empty — which is how these rows came to be called nameless. The name is
#: the ``AXCell`` child's own title, and it describes the whole effect:
#: ``'Animation order: 7, Starts: On Click, Path effect, Curvy Left, 007.'``
#: Measured 2026-11-02.
PANE_CELL_ROLE = "AXCell"

#: macOS virtual keycodes for the two keys this driver sends, and the only two.
#: They move the Animation Pane's effect selection, which no accessibility write
#: can do — see :func:`select_pane_effect`. Named rather than inlined so that a
#: grep for what this driver can type returns a list of length two.
KEY_ARROW_DOWN = 125
KEY_ARROW_UP = 126

#: Both panes share one tab bar once the Selection Pane is open, so the
#: Animation Pane is revealed by selecting its tab rather than by the ribbon
#: switch, which would close it.
PANE_TAB_ROLE = "AXRadioButton"

ANIMATION_PANE_ROLE = "AXGroup"

#: The side pane's tab bar, which is how the side pane is identified at all.
#:
#: It shares ``AXTabGroup`` with the ribbon and is told apart by its title:
#: measured 2026-11-02, the ribbon's is ``ribbon`` and the side pane's is
#: ``Tab bar, N tabs`` — the same second ``AXTabGroup``
#: :func:`window_container` already disambiguates the ribbon against.
#:
#: This prefix is load-bearing rather than decorative. **Three** live elements
#: are titled ``Animations``: the ribbon's own tab, the side pane's group, and
#: the pane's tab. Searching the window for an ``AXRadioButton`` titled
#: ``Animations`` finds the *ribbon tab*, whose ``AXValue`` is ``"1"`` whenever
#: that tab is active — which is the state this driver deliberately puts the
#: ribbon in — so such a search reports the Animation Pane open while the side
#: pane is showing something else entirely. Measured 2026-11-02: it cost a run,
#: reporting ``alreadyOpen`` and then failing on the pane's absent contents.
#: Every pane lookup therefore starts from this tab bar, which only the side
#: pane has.
SIDE_PANE_TAB_BAR_ROLE = RIBBON_ROLE
SIDE_PANE_TAB_BAR_PREFIX = "Tab bar"

#: How deep the side pane's tab bar sits below its group, and its tabs below the
#: bar. Measured 2026-11-02: ``AXGroup`` ▸ ``AXTabGroup`` ▸ ``AXRadioButton``,
#: so both are small. Bounded so that a window shaped differently fails here
#: rather than turning a pane lookup into a full tree walk.
SIDE_PANE_TAB_BAR_DEPTH = 4
SIDE_PANE_TAB_DEPTH = 3

#: What each container is called in a failure message, so "no AXTabGroup" reads as a
#: statement about PowerPoint rather than about a role name.
CONTAINER_NAMES = {
    TOOLBAR_ROLE: "the Quick Access toolbar",
    RIBBON_ROLE: "the ribbon",
    SELECTION_PANE_ROLE: "the Selection Pane",
}


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
    """Resolve a scope, reusing whatever the caller's :class:`Containers` already holds.

    The window and the container come from the caller's holder, which every action and
    every poll invalidates; the titles beneath them are walked afresh each time. So a
    press is still aimed by a title resolved immediately beforehand, and what it no
    longer costs is a walk of the window to get to the container.
    """
    view = held(backend)
    if scope.window_title is None:
        node = view.window()
        if scope.container_role:
            node = view.container(
                scope.container_role,
                what=CONTAINER_NAMES.get(scope.container_role, scope.container_role),
                title=scope.container_title,
            )
    else:
        node = view.named_window(scope.window_title)
        if scope.container_role:
            node = window_container(
                node,
                scope.container_role,
                what=CONTAINER_NAMES.get(scope.container_role, scope.container_role),
                title=scope.container_title,
            )
    for title in scope.descend:
        node = _resolve_in(node, title)
    return node


def _reachable_any(scope_node: AXNode, titles: Sequence[str]) -> bool:
    """Is any of ``titles`` findable anywhere inside this scope?"""
    return any(find_all_by_title(scope_node, title) for title in titles)


def title_variants(title: str, alternatives: Sequence[str] = ()) -> tuple[str, ...]:
    """Every spelling of a control's title worth trying, in order, without duplicates.

    The plan's title first, then the alternatives it carries, then **the same titles with
    every ``&`` removed**. That last one is not a guess at a synonym: the accessibility
    layer drops the ampersand from a tile's own title and leaves the spaces around it, so
    ``Grow & Turn`` is published as ``Grow  Turn`` with two spaces and ``Shrink & Turn``
    as ``Shrink  Turn``. Two targets were reported absent for exactly that, from a
    gallery that holds them, and ``str.replace("&", "")`` reproduces the live title
    character for character.

    It is a derived **alternative**, never a replacement: the exact title is tried first,
    so a gallery that does publish the ampersand is matched on it.
    """
    stated = (title, *alternatives)
    dropped = tuple(spelling.replace("&", "") for spelling in stated if "&" in spelling)
    return tuple(dict.fromkeys(stated + dropped))


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
      does not contain the next step is pressed **unless a window of its title is already
      open**, and the driver then waits, bounded, for that window — this is how
      ``Effect Options``, ``Path Animation`` and a gallery's expanded palette work;
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

    # Rebound so the closures below share the caller's holder rather than each resolving
    # the window again. ``held`` returns the caller's own when it has one.
    backend = view = held(backend)
    steps: list[StepOutcome] = []
    # Every step of a ribbon path — the tab, the gallery, the tile — is inside the ribbon
    # tab group, so the walk never leaves it and never reaches the Selection Pane's rows.
    scope = RIBBON_SCOPE
    final_titles = title_variants(path[-1], alternatives)

    # Pressing a ribbon tab that is ALREADY active collapses the ribbon, which takes
    # every control on it out of the tree. Measured: a run against a deck whose
    # Animations tab was already selected pressed it anyway, the ribbon folded, and all
    # 76 targets failed waiting for a gallery that had stopped existing. So the tab is
    # pressed only when its own controls are not already reachable, which is the same
    # evidence the wait below uses and needs no extra attribute.
    # Reachability is checked BEFORE the tab is resolved, not after. Measured: three
    # live elements are titled 'Animations' (an AXRadioButton and two AXGroups), so
    # resolving the tab raises AmbiguousControl — and resolving it first would fail every
    # target even when the tab is already active and nothing needs pressing.
    if _reachable_any(resolve_scope(backend, scope), [path[1]]):
        steps.append(StepOutcome(path[0], "tabAlreadyActive", None))
    else:
        tab_node = _resolve_in(resolve_scope(backend, scope), path[0])
        tab_node.press()
        view.stale()
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
            # Pressed only when its window is not already open. This is the third time
            # the same trap has cost a run: pressing an active ribbon tab collapses the
            # ribbon, pressing `Selection Pane...` while the pane is open closes the
            # pane, and pressing a gallery whose palette window is already open closes
            # that — which is how the last target failed, as `timed out waiting for the
            # 'Exit Effects' window to open` right after something else had opened it. So
            # the window's presence is read rather than assumed, as it is in both other
            # places.
            window = find_window(backend, title)
            if window is None:
                node.press()
                view.stale()
                window = wait_until(
                    backend,
                    lambda title=title: find_window(backend, title),
                    timeout=timeout,
                    what=f"the {title!r} window to open",
                )
                steps.append(StepOutcome(title, "openedWindow", node.role))
            else:
                steps.append(StepOutcome(title, "windowAlreadyOpen", node.role))
            scope = scope.in_window(window.title or title)
            continue
        scope = scope.inside(title)
        steps.append(StepOutcome(title, "scopedPendingTiles", node.role))

    tried = ", ".join(repr(title) for title in final_titles)

    #: Pages scrolled while looking for the final step, in each direction. A gallery is
    #: an ``AXScrollArea`` publishing only the tiles on its current page: the Entrance
    #: gallery published 25 and neither ``Grow & Turn`` nor ``Stretch`` was among them,
    #: while an earlier run had captured ``Zoom``, which was not among them either. So a
    #: missing tile is paged for before it is reported missing — **up** first, because
    #: the previous target left the gallery wherever it was and only the top is a known
    #: starting point, then **down** through the whole list.
    paged = {"up": 0, "down": 0}

    def page_gallery() -> None:
        """Turn the gallery one page, or do nothing once both directions are spent.

        The pagers are the ribbon's own buttons, resolved by title in the ribbon rather
        than inside the gallery, because that is where they sit. A pager that is absent
        or disabled spends its direction: ``Previous`` is disabled at the top of the
        list, so going up stops there rather than pressing a dead control eight times.
        """
        gallery = scope.descend[-1] if scope.descend else None
        if gallery is None:
            return
        for direction, template in (
            ("up", GALLERY_PAGE_PREVIOUS),
            ("down", GALLERY_PAGE_NEXT),
        ):
            if paged[direction] >= MAX_GALLERY_PAGES:
                continue
            try:
                pager = _resolve_in(
                    resolve_scope(backend, RIBBON_SCOPE), template.format(gallery=gallery)
                )
            except TargetFailure:
                paged[direction] = MAX_GALLERY_PAGES
                continue
            if not pager.enabled:
                paged[direction] = MAX_GALLERY_PAGES
                continue
            pager.press()
            view.stale()
            paged[direction] += 1
            return

    def present() -> str | None:
        scope_node = resolve_scope(backend, scope)
        for candidate in final_titles:
            try:
                _resolve_in(scope_node, candidate)
            except ControlNotFound:
                continue
            return candidate
        page_gallery()
        return None

    try:
        matched = wait_until(backend, present, timeout=timeout, what=f"one of {tried} in {scope.describe()}")
    except DriverTimeout as exc:
        raise ControlNotFound(
            f"none of {tried} appeared in {scope.describe()} within {timeout:g}s; the tree was "
            "re-read on every poll, so a lazily materialized tile had its chance, and the "
            f"gallery was paged {paged['up']} up then {paged['down']} down"
        ) from exc
    if paged["up"] or paged["down"]:
        steps.append(
            StepOutcome(
                scope.descend[-1] if scope.descend else path[1],
                f"pagedGallery({paged['up']} up, {paged['down']} down)",
                None,
            )
        )

    # Re-resolved from one more fresh read: a press aimed by anything older can land on a
    # tile that scrolled, which applies the wrong value and records the right one. The
    # wait above invalidated the holder on its last poll, so this really is a fresh
    # resolution — it is just a resolution inside the ribbon rather than across the
    # window, which is the only thing that changed when the driver got fast.
    view.stale()
    node = _resolve_in(resolve_scope(backend, scope), matched)
    if not node.enabled:
        raise ControlNotFound(f"{matched!r} is present but disabled in {scope.describe()}")
    node.press()
    view.stale()
    steps.append(StepOutcome(matched, "pressed", node.role))
    return PathResult(matched, steps)


# --- read-back --------------------------------------------------------------
def read_labelled_value(scope_node: AXNode, label: str) -> str | None:
    """Return the value of the control titled ``label`` inside ``scope_node``, or None.

    ``scope_node`` is the ribbon, not the window: both labels are ribbon controls, and a
    read-back is not worth a walk of the Selection Pane.

    The read-back is recorded evidence, not an acceptance gate, so an absent or
    ambiguous control is reported as ``null`` rather than failing the target. The
    acceptance gate is :func:`attribute_new_effect`, which reads the saved package.
    """
    found = find_all_by_title(scope_node, label)
    if len(found) == 1:
        return found[0].value
    valued = [node for node in found if node.value not in (None, "")]
    return valued[0].value if len(valued) == 1 else None


def ribbon_readback(backend: AXBackend) -> dict[str, str | None]:
    """Return the ``Start:`` and ``Duration:`` values the ribbon shows right now.

    Taken while the target's own shape is still the selected one. Under batching that
    means it is read immediately after the press rather than after the batch's save: the
    ribbon shows the **selected** shape's values, and the next target in the batch moves
    the selection, so a read-back deferred to the save would record the last target's
    values against every key in the batch.
    """
    ribbon = resolve_scope(backend, RIBBON_SCOPE)
    return {
        "start": read_labelled_value(ribbon, START_LABEL),
        "duration": read_labelled_value(ribbon, DURATION_LABEL),
    }


# --- the Selection Pane, which is how a shape is selected -------------------
# There is deliberately no slide selection and no thumbnail lookup here, and no canvas
# click either. See the module docstring: the live 2026-10-31 run rejected all 76 targets
# inside slide selection, and the click that replaced it captured 2 of 12.


def selection_outline(backend: AXBackend) -> AXNode:
    """Return the Selection Pane's outline from a fresh read, or fail if it is closed.

    :class:`ControlNotFound` rather than a bool, so :func:`wait_until` can poll this
    directly and so a closed pane reads the same as any other absent control.

    This used to walk the whole document window looking for an ``AXOutline``, and it was
    the single most expensive call in the driver at **17.8 s** — most of which was not
    the outline at all but ``document_window`` walking each same-titled candidate window
    to find the ribbon. It is now a container search that stops at the outline rather
    than descending into its 762 rows.
    """
    # The Animation Pane publishes an ``AXOutline`` of its own — its effect
    # list, titled ``Animation list`` — so the role stopped identifying the
    # Selection Pane the moment the Animation Pane was open. Measured
    # 2026-11-02: this resolved to a nine-row effect list and ``select_shape``
    # then timed out waiting for row 13 of 14 in a pane publishing eight rows.
    #
    # The Selection Pane's own outline is **untitled**, so it is identified by
    # excluding the one that is named rather than by naming it. That is the
    # weaker of the two and it is deliberate: a title this driver asserts and
    # PowerPoint changes would make the pane unreachable, while excluding a
    # known impostor degrades to "ambiguous" and raises.
    return held(backend).container(
        SELECTION_PANE_ROLE,
        reject_title=ANIMATION_LIST_TITLE,
        what=CONTAINER_NAMES[SELECTION_PANE_ROLE],
        absent=(
            f"the document window holds no {SELECTION_PANE_ROLE} other than the Animation "
            f"Pane's {ANIMATION_LIST_TITLE!r}; the Selection Pane is not open"
        ),
    )


def row_names(row: AXNode) -> list[str]:
    """Return the shape names a Selection Pane row carries.

    A row's own ``title`` is ``None``; the name is the ``value`` of a descendant
    ``AXStaticText``. Every such value is returned rather than only the first, because
    nothing offline can promise a row holds exactly one label, and matching against all
    of them cannot invent a name the pane does not show.
    """
    return [
        str(node.value)
        for node in walk(row)
        if node.role == SELECTION_LABEL_ROLE and node.value not in (None, "")
    ]


class PaneRow(NamedTuple):
    """One Selection Pane row: the element, the index it reports, and any name it shows.

    ``index`` is the row's own ``AXIndex`` when it publishes one, and its offset in the
    read when it does not. Which it was is not recorded, deliberately: the only consumer
    is :func:`select_shape`, and what protects it from the difference is that a row with
    a name must match the name expected at that index.
    """

    node: AXNode
    index: int
    names: list[str]


def selection_rows(backend: AXBackend) -> list[PaneRow]:
    """Return the pane's rows with their indices and names, from a fresh read.

    Pane order is **reverse z-order**: the live pane's row 0 was ``TextBox 152`` and row
    1 ``Rounded Rectangle 151``. :func:`select_shape` depends on that order, because it
    addresses a row by index; the order was verified against the package twice, 152 rows
    and 0 mismatches each time.

    Rows come from the outline's ``AXRows``, which publishes more of them than
    ``AXChildren`` does — that difference is why 26 targets once failed, the driver
    reporting "the pane shows 62 names", then 47, for rows that existed. An outline that
    publishes no ``AXRows`` falls back to the bounded walk, which also picks up a row
    nested one level deeper — a grouped shape's disclosure row — rather than reporting it
    missing.

    **``AXRows`` is not all of them either**, and two earlier readings of this were
    wrong. Probed on an idle pane it answered 152 rows, every one carrying a readable
    name, and both this docstring and the notes concluded no scrolling was needed. Under
    load the same pane published **43, 54, 61, 63, 74, 88 and 91** rows on consecutive
    reads — the pane rebuilds as the application works, and a read can catch it
    part-built. So neither the number of rows in a read nor a row's offset within it says
    anything, and what identifies a row is its **own ``AXIndex``**, which every row
    publishes.

    A row's **names list can also be empty**: only a row that has been scrolled into
    view publishes an ``AXStaticText`` to read a name from. The names here are therefore
    a *validation* signal — checked when present, absent without complaint when not — and
    never the way a row is found.

    One pass, not one pass per row. Walking the outline measured 4.1 s and calling
    :func:`row_names` on each of 152 rows another 4.3 s, because the second pass visits
    every row's subtree a second time. Here a row's labels are collected as the single
    walk reaches them, which halves the only remaining large read in the driver. A nested
    row becomes its own entry and owns the labels beneath it, so a grouped shape's
    disclosure row is still addressable by its own name.
    """
    outline = selection_outline(backend)
    rows: list[PaneRow] = []
    names_by_row: dict[int, list[str]] = {}
    published = getattr(outline, "rows", None)
    roots = list(published) if published else list(outline.children)
    stack: list[tuple[AXNode, int, int]] = [(child, 1, -1) for child in reversed(roots)]
    seen = 1
    while stack:
        node, depth, owner = stack.pop()
        seen += 1
        if seen > MAX_TREE_NODES:
            raise TreeTooLarge(f"tree scan exceeded {MAX_TREE_NODES} nodes")
        role = node.role
        if role == SELECTION_ROW_ROLE:
            owner = len(rows)
            names_by_row[owner] = []
            published_index = node.index
            rows.append(
                PaneRow(node, owner if published_index is None else published_index, names_by_row[owner])
            )
        elif role == SELECTION_LABEL_ROLE and owner >= 0:
            value = node.value
            if value not in (None, ""):
                names_by_row[owner].append(str(value))
        if depth >= MAX_TREE_DEPTH:
            continue
        stack.extend((child, depth + 1, owner) for child in reversed(list(node.children)))
    return rows


def open_selection_pane(backend: AXBackend, *, timeout: float) -> str:
    """Make sure the Selection Pane is open, and say what that took. Once per run.

    Pressing ``Selection Pane...`` while the pane is already open **closes** it — the
    same "pressing an active thing toggles it" trap that collapsed the ribbon and took
    every gallery out of the tree. So the pane's own presence is the test, read from the
    tree rather than remembered: if the outline is there, nothing is pressed.

    Opening it walks ``Home ▸ Arrange ▸ Selection Pane...`` through
    :func:`press_path`, so each step is resolved by title against a fresh read and the
    ``Arrange`` window is awaited rather than assumed.
    """
    view = held(backend)
    try:
        selection_outline(view)
        return "alreadyOpen"
    except ControlNotFound:
        pass
    press_path(view, SELECTION_PANE_PATH, timeout=timeout)
    wait_until(
        view,
        lambda: _rows_present(view),
        timeout=timeout,
        what=f"the Selection Pane's {SELECTION_PANE_ROLE} to appear in the document window",
    )
    return "pressed"


def _rows_present(backend: AXBackend) -> bool:
    """Is the pane open with at least one row? Used as a bounded wait's predicate."""
    return bool(selection_rows(backend))


class RowSelection(NamedTuple):
    """Which Selection Pane row was selected, and the name it published if it did.

    ``name`` is ``None`` when the row published no label — an unscrolled row — which is
    not a failure. ``index`` is what identifies the row either way, so a record always
    says which row was selected even when the pane would not say what it is called.
    """

    index: int
    name: str | None


def select_shape(
    backend: AXBackend,
    shape_name: str,
    *,
    row_index: int,
    row_count: int,
    timeout: float,
) -> RowSelection:
    """Select one shape through its Selection Pane row, addressed by index.

    The shape itself has no accessibility element, but its row does, and that removes
    every moving part the click had: no coordinates, no pointer, no zoom, no editor-pane
    frame, no window focus and no settling. A row exposes no ``AXPress`` — its actions
    are ``AXShowDefaultUI``, ``AXShowAlternateUI`` and a Rename — so selection is a
    **write of ``AXSelected``**, which is the standard outline-row mechanism, and the
    row is read back to confirm it took.

    ## Why an index, when this used to be a name

    A name is the better key right up to the point where the pane will not publish one.
    Only a row that has been scrolled into view carries the ``AXStaticText`` its name is
    read from, and the counts move between reads: one run's batches saw 80 readable
    names, then 54. By-name lookup therefore rejected 11 targets with "no Selection Pane
    row is named ..." for rows that were present and selectable the whole time. Scrolling
    the pane to materialize a name would be work done only to recover a key the package
    already has.

    So the row is addressed by ``row_index`` from :func:`shape_row_index` — the shape's
    position in reverse z-order — and the name is used the other way round, as a check.

    ## Which index, though: the row's own, not its offset

    The first version of this took ``rows[row_index]`` and required the pane to publish
    exactly ``row_count`` rows first. That refused 7 targets, because the pane published
    43, 54, 61, 63, 74, 88 and 91 rows on consecutive reads of the same 152-shape slide:
    it rebuilds while the application works, and a read catches it part-built. The
    refusal was right — an offset into a partial read is not the row asked for — but
    waiting for a whole one is not a mechanism either.

    Every row publishes its **own ``AXIndex``**, measured as 0, 1, 76 and 151 for the
    rows at those offsets. So a row is found by matching that, and a partial read is
    perfectly usable as long as it happens to contain the row wanted. ``row_count`` is
    now only used to describe the slide in a failure message.

    Three gates, in the order they fire:

    * A read with no row at ``row_index`` is "not yet": the lookup is **retried against
      fresh reads** until ``timeout``, because the pane does fill in. Only then is it a
      :class:`DriverTimeout` saying how many rows were published and which indices.
    * Two rows reporting one index is an :class:`AmbiguousControl`, never a choice.
    * A row that publishes names none of which is ``shape_name`` is a
      :class:`ControlNotFound` naming both. That is the check that makes the index safe:
      if ``AXIndex`` were ever relative to a partial read rather than absolute, or the
      pane were in some order other than reverse z-order, this is what catches it before
      a press lands on another shape. Under load the pane published a name for every row
      it published, so this gate is live exactly when it is needed.
    """

    #: What the most recent read saw, so a timeout can describe it without reading the
    #: pane again. One extra outline read per target is the single most expensive thing
    #: this driver does, and a failure message is not worth one.
    last_read: dict[str, Any] = {"rows": 0, "indices": "none"}

    def resolve_row() -> PaneRow | None:
        rows = selection_rows(backend)
        indices = sorted(row.index for row in rows)
        last_read["rows"] = len(rows)
        last_read["indices"] = f"{indices[0]}..{indices[-1]}" if indices else "none"
        matching = [row for row in rows if row.index == row_index]
        if len(matching) > 1:
            raise AmbiguousControl(
                f"{len(matching)} Selection Pane rows report index {row_index}; refusing to "
                f"choose which one is {shape_name!r}"
            )
        if not matching:
            return None
        row = matching[0]
        if row.names and shape_name not in row.names:
            raise ControlNotFound(
                f"Selection Pane row {row_index} publishes {row.names} rather than "
                f"{shape_name!r}; the pane is not in the reverse z-order this index was "
                "derived from"
            )
        return row

    def describe() -> str:
        return (
            f"row {row_index} of {row_count} (expected to be {shape_name!r}); the last read "
            f"published {last_read['rows']} rows, indices {last_read['indices']}"
        )

    def selected_now() -> bool:
        found = resolve_row()
        return found is not None and found.node.selected

    view = held(backend)
    try:
        row = wait_until(
            view,
            resolve_row,
            timeout=timeout,
            # Nothing is swallowed: a row that is not published yet is a None return
            # rather than an exception, so the only things that can be raised here are a
            # name that contradicts the index and two rows claiming one index. Polling
            # cannot make either come true, and swallowing them would turn a pane in the
            # wrong order into a timeout 10 seconds later instead of a refusal now.
            swallow=(),
            what=f"{shape_name!r}'s Selection Pane row to be published",
        )
    except DriverTimeout as exc:
        raise ControlNotFound(
            f"the Selection Pane never published {describe()}"
        ) from exc
    row.node.set_selected(True)
    view.stale()
    wait_until(
        view,
        selected_now,
        timeout=timeout,
        swallow=(),
        what=f"the Selection Pane's {describe()} to read back as selected",
    )
    return RowSelection(row_index, shape_name if shape_name in row.names else None)


def close_window(backend: AXBackend, title: str, *, timeout: float) -> str:
    """Close one of PowerPoint's popup windows by pressing its ribbon opener again.

    The opener **toggles**, which is the trap that has cost three runs: pressing
    it while the window is open closes it. Here that is the intent, so the
    window's presence is read first and nothing is pressed when it is already
    shut — the same discipline, used the other way round.

    Returns what it did, so a record says whether a window had been held over.
    """
    view = held(backend)
    if find_window(view, title) is None:
        return "alreadyClosed"
    opener = _resolve_in(resolve_scope(view, RIBBON_SCOPE), title)
    if not opener.enabled:
        raise ControlNotFound(
            f"the {title!r} window is open but its ribbon control is disabled, so it cannot "
            "be closed from here"
        )
    opener.press()
    view.stale()
    wait_until(
        view,
        lambda: find_window(view, title) is None,
        timeout=timeout,
        swallow=(),
        what=f"the {title!r} window to close",
    )
    return "closed"


def _tab_bar_in(node: AXNode) -> AXNode | None:
    """The side pane's tab bar inside ``node``, or None if it holds none.

    Named by prefix rather than by role alone because the ribbon carries the
    same role; see :data:`SIDE_PANE_TAB_BAR_PREFIX` for what that cost.
    """
    for child in walk(node, max_depth=SIDE_PANE_TAB_BAR_DEPTH):
        if child.role != SIDE_PANE_TAB_BAR_ROLE:
            continue
        if (child.title or "").startswith(SIDE_PANE_TAB_BAR_PREFIX):
            return child
    return None


def side_pane_group(backend: AXBackend) -> AXNode | None:
    """The group of whichever side pane is open, or None when none is.

    Identified by holding a side-pane tab bar, which is the only thing about it
    that does not move: its own title is **whichever tab is active** — measured
    2026-11-02, ``Animations`` with the Animation Pane showing and ``Selection
    Pane`` with the Selection Pane showing — so the group cannot be addressed by
    the name of the pane being looked for.

    The outermost such group is returned, which is what the pre-order descent
    gives: measured 2026-11-02 the tab bar is a direct child of the outer group,
    and the inner groups beneath its scroll area hold no tab bar at all.

    Descends the way :func:`find_containers` does — pruning at every container
    role — rather than walking the window, for the reason that search exists: a
    window walk crosses the Selection Pane's rows, 762 of them on the deck that
    motivated the container boundary, to find a group three levels down.
    """
    view = held(backend)
    window = view.window()
    stack: list[tuple[AXNode, int]] = [(child, 1) for child in reversed(list(window.children))]
    seen = 1
    while stack:
        node, depth = stack.pop()
        seen += 1
        if seen > MAX_CONTAINER_NODES:
            raise TreeTooLarge(
                f"the search for the side pane visited more than {MAX_CONTAINER_NODES} nodes; "
                "the window is not shaped as measured and a container search has become a walk"
            )
        role = node.role
        if role == ANIMATION_PANE_ROLE and _tab_bar_in(node) is not None:
            return node
        if role in CONTAINER_ROLES or depth >= CONTAINER_DEPTH:
            continue
        stack.extend((child, depth + 1) for child in reversed(list(node.children)))
    return None


def _pane_tab(backend: AXBackend, title: str) -> AXNode | None:
    """One side-pane tab by name, or None when the side pane does not offer it.

    None covers two states the caller has to tell apart by other means: no side
    pane at all, and a side pane whose bar does not list this tab. Measured
    2026-11-02 with only the Selection Pane open, the bar read ``Tab bar, 1
    tabs`` and held no ``Animations`` tab — so an absent tab means the pane is
    closed, not merely behind another.
    """
    group = side_pane_group(backend)
    if group is None:
        return None
    bar = _tab_bar_in(group)
    if bar is None:  # pragma: no cover - the group was selected by holding one
        return None
    for node in walk(bar, max_depth=SIDE_PANE_TAB_DEPTH):
        if node.role == PANE_TAB_ROLE and node.title == title:
            return node
    return None


def open_animation_pane(backend: AXBackend, *, timeout: float) -> str:
    """Make the Animation Pane visible, and return how it got there.

    The ribbon control is a **switch**, not a button, so pressing it when the
    pane is already open closes it. The pane's own tab is checked for first and
    the switch is only touched when the tab is absent.

    The tab is looked for **inside the side pane's tab bar**, never across the
    window: the ribbon publishes a radio button titled ``Animations`` too, and
    its value is ``"1"`` whenever that ribbon tab is active. See
    :data:`SIDE_PANE_TAB_BAR_PREFIX`.
    """
    view = held(backend)

    def pane_tab() -> AXNode | None:
        view.stale()
        return _pane_tab(view, ANIMATION_PANE_TAB)

    def pane_open() -> bool:
        tab = pane_tab()
        # ``AXValue`` on the tab is "1" when its own pane is the one showing.
        return tab is not None and tab.value == "1"

    if pane_open():
        return "alreadyOpen"

    # Two different states need two different answers, and pressing the ribbon
    # switch is only right for one of them. With the Selection Pane open, both
    # panes share a tab bar and the Animation Pane is merely *behind* its tab:
    # the switch would close it rather than reveal it. Measured 2026-11-02, this
    # cost two runs — `select_shape` succeeded and the pane then timed out.
    tab = pane_tab()
    if tab is not None:
        tab.press()
        view.stale()
        if pane_open():
            return "tabSelected"

    # `ensure_tab` takes a whole GUI path — the tab plus the control it is being
    # activated for — so the switch is named here rather than the tab alone.
    #
    # It is handed this view rather than the raw backend, and the view is invalidated
    # afterwards, because `ensure_tab` **presses a ribbon tab**: a view that kept its
    # container across that press resolves the switch inside the ribbon as it was
    # before, where the Animations tab's controls do not exist. That is the module's
    # own rule — a press is followed by an invalidation — applied to a press made by
    # a function this one calls rather than by this one.
    ensure_tab(view, ("Animations", ANIMATION_PANE_SWITCH), timeout=timeout)
    view.stale()
    _resolve_in(resolve_scope(view, RIBBON_SCOPE), ANIMATION_PANE_SWITCH).press()
    view.stale()
    wait_until(backend, pane_open, timeout=timeout, what="the Animation Pane to open")
    return "switched"


def animation_pane(backend: AXBackend) -> AXNode:
    """Return the side-pane group that is currently showing the Animation Pane.

    Not a :class:`Scope`, and that is the finding rather than a shortcut: the
    group's own title is whichever tab is active, so no fixed title identifies
    it. See :func:`side_pane_group` for what does.

    The three states are kept apart, because they need three different answers
    from the caller: no side pane (open one), a side pane that does not list an
    ``Animations`` tab (press the ribbon switch), and one that lists it behind
    the Selection Pane (select the tab). Collapsing them into "not found" is what
    sent a run into the switch while the pane was already open.
    """
    view = held(backend)
    view.stale()
    group = side_pane_group(view)
    if group is None:
        raise ControlNotFound(
            "the document window holds no side pane — no group carries a tab bar titled "
            f"{SIDE_PANE_TAB_BAR_PREFIX!r} — so the Animation Pane is not open; "
            "call open_animation_pane first"
        )
    bar = _tab_bar_in(group)
    tab = _pane_tab(view, ANIMATION_PANE_TAB)
    if tab is None:
        raise ControlNotFound(
            f"the side pane is open but its tab bar lists no {ANIMATION_PANE_TAB!r} tab "
            f"(it reads {None if bar is None else bar.title!r}), so the Animation Pane is closed "
            "rather than merely behind another pane; call open_animation_pane first"
        )
    if tab.value != "1":
        raise ControlNotFound(
            f"the {ANIMATION_PANE_TAB!r} tab exists but is not the selected one, so the pane's "
            "settings are behind another pane; call open_animation_pane first"
        )
    return group


def pane_effect_rows(backend: AXBackend) -> list[dict[str, Any]]:
    """Describe every row of the Animation Pane's effect list.

    An effect **is** identifiable, which the first version of this denied. The
    name is not a descendant ``AXStaticText`` the way a Selection Pane row's is —
    that is why a search for one came back empty — it is the row's ``AXCell``
    child's own title, and it is richer than a name::

        row 0  None                                                        (the ANIMATIONS header)
        row 1  'Animation order: 1, Starts: On Click, Path effect, Bounce Left, 001.'
        ...
        row 7  'Animation order: 7, Starts: On Click, Path effect, Curvy Left, 007.'

    So a measurement can record *which* effect it measured rather than asserting
    a row number, and a fixture can name it. Measured 2026-11-02.
    """
    view = held(backend)
    view.stale()
    pane = animation_pane(view)
    outline: AXNode | None = None
    for node in walk(pane):
        if node.role == SELECTION_PANE_ROLE:
            outline = node
            break
    if outline is None:
        raise ControlNotFound(
            f"the Animation Pane publishes no {SELECTION_PANE_ROLE}, so it has no effect list"
        )
    described: list[dict[str, Any]] = []
    for index, row in enumerate(
        child for child in outline.children if child.role == SELECTION_ROW_ROLE
    ):
        cell = next((child for child in row.children if child.role == PANE_CELL_ROLE), None)
        described.append(
            {
                "rowIndex": index,
                "index": row.index,
                "selected": row.selected,
                "describedAs": None if cell is None else cell.title,
            }
        )
    return described


def _effect_list(backend: AXBackend) -> AXNode:
    """The Animation Pane's effect list element itself."""
    view = held(backend)
    for node in walk(animation_pane(view)):
        if node.role == SELECTION_PANE_ROLE:
            return node
    raise ControlNotFound(
        f"the Animation Pane publishes no {SELECTION_PANE_ROLE}, so it has no effect list"
    )


def _refuse_unless_keys_reach_the_effect_list(backend: AXBackend) -> None:
    """Raise unless an arrow key would land in the effect list being driven.

    Both halves are required and neither is a formality:

    * The process delivers a key to its **focused window**. The measuring host had
      three decks open in one PowerPoint process, so "send a key to PowerPoint"
      says nothing about which deck receives it. ``AXFocusedWindow`` is not
      settable on this application, so this can only require the right one.
    * A window delivers a key to its **focused element**. Without this the arrow
      would move the slide, scroll the canvas or type into a text box.

    Checked immediately before every press rather than once per target: the
    operator can click into another window between two presses, and the whole
    reason this is acceptable at all is that a key cannot go anywhere it was not
    just confirmed to be going.
    """
    view = held(backend)
    wanted = view.window().title
    focused = view.focused_window_title()
    if focused != wanted:
        raise TargetFailure(
            f"PowerPoint's focused window is {focused!r}, not the deck being measured "
            f"({wanted!r}), so an arrow key would move something in another document; "
            "bring the capture deck to the front",
            focusedWindow=focused,
            wantedWindow=wanted,
        )
    role = view.focused_element_role()
    if role != SELECTION_PANE_ROLE:
        raise TargetFailure(
            f"the focused element is a {role}, not the {SELECTION_PANE_ROLE} holding the "
            "effect list, so an arrow key would move something other than the effect "
            "selection",
            focusedRole=role,
        )


def select_pane_effect(
    backend: AXBackend, *, described_as: str, timeout: float
) -> dict[str, Any]:
    """Select one effect in the Animation Pane's list, by what the effect **is**.

    ``described_as`` matches against the row's own description — e.g. ``"Curvy
    Left"`` against ``'Animation order: 7, Starts: On Click, Path effect, Curvy
    Left, 007.'`` — so a measurement names the effect it measured instead of
    asserting a row number that depends on pane ordering.

    **This is the one place the driver sends a key event**, and only because every
    alternative was measured and none works: ``AXSelected`` on the row and
    ``AXSelectedRows`` on the outline both report settable, return 0 and never read
    back; ``AXPress`` is not published; the row's two actions do nothing; selecting
    the shape selects no effect; and ``agent-desktop``'s ``click`` answers
    "Selection was delivered but its effect could not be verified". What does work
    is ``AXFocused`` on the list plus an arrow key — measured 2026-11-02, two Down
    presses moved the selection to rows 1 and 2 and the four settings sections and
    six popups appeared with it.

    Three properties keep that from being the mouse event this driver removed:

    * The key is posted **to PowerPoint's process**, so it cannot reach another
      application or be typed into the operator's work.
    * It needs no coordinate and no pointer, so nothing is aimed by position —
      which is what corrupted evidence on 2026-10-31.
    * Every press is preceded by :func:`_refuse_unless_keys_reach_the_effect_list`
      and followed by a read of the selection, so a press that went somewhere else
      fails here rather than being recorded as a measurement.

    It walks the selection one row at a time instead of computing a press count,
    because the read-back after each press is what makes the walk honest: a list
    that stops moving fails as "stuck" rather than silently swallowing presses.
    """
    view = held(backend)

    def rows() -> list[dict[str, Any]]:
        return pane_effect_rows(view)

    def target_in(found: list[dict[str, Any]]) -> dict[str, Any]:
        matching = [
            row
            for row in found
            if row["describedAs"] and described_as in row["describedAs"]
        ]
        if not matching:
            raise ControlNotFound(
                f"no effect in the Animation Pane is described as {described_as!r}",
                describedAs=described_as,
                rows=[row["describedAs"] for row in found],
            )
        if len(matching) > 1:
            raise AmbiguousControl(
                f"{len(matching)} effects in the Animation Pane match {described_as!r}; "
                "refusing to choose",
                matched=[row["describedAs"] for row in matching],
            )
        return matching[0]

    found = rows()
    target = target_in(found)
    if target["selected"]:
        return {
            "describedAs": target["describedAs"],
            "rowIndex": target["rowIndex"],
            "how": "alreadySelected",
            "presses": 0,
        }

    # Focus is what the key follows, so it is established once and then re-checked
    # before each press rather than trusted for the whole walk.
    _effect_list(view).set_focused(True)
    view.stale()

    presses = 0
    # One press per row is enough to cross the list from either end; the bound
    # exists so a list that answers presses without moving terminates.
    limit = len(found) + 1
    while presses < limit:
        _refuse_unless_keys_reach_the_effect_list(view)
        found = rows()
        target = target_in(found)
        if target["selected"]:
            return {
                "describedAs": target["describedAs"],
                "rowIndex": target["rowIndex"],
                "how": "arrowKeys",
                "presses": presses,
            }
        selected = [row for row in found if row["selected"]]
        if len(selected) > 1:
            raise AmbiguousControl(
                f"the effect list has {len(selected)} rows selected, so an arrow key would "
                "move an ambiguous selection",
                selected=[row["describedAs"] for row in selected],
            )
        # With nothing selected the first Down takes the top row, so down is also
        # the right first move from empty.
        at = selected[0]["rowIndex"] if selected else -1
        before = at
        view.post_key(KEY_ARROW_DOWN if at < target["rowIndex"] else KEY_ARROW_UP)
        presses += 1
        view.stale()
        # PowerPoint answers a key asynchronously, so the move is waited for rather
        # than assumed — and "did not move" is a failure, not a slow success.
        def moved(before: int = before) -> bool:
            view.stale()
            current = [row for row in pane_effect_rows(view) if row["selected"]]
            return bool(current) and current[0]["rowIndex"] != before
        wait_until(
            view,
            moved,
            timeout=timeout,
            what=(
                f"the effect list's selection to move off row {before} after an arrow key "
                f"(press {presses})"
            ),
        )

    raise TargetFailure(
        f"the effect list's selection did not reach {described_as!r} in {limit} arrow keys",
        describedAs=described_as,
        presses=presses,
    )


def selected_pane_effect(backend: AXBackend) -> dict[str, Any]:
    """Return the effect the Animation Pane has selected, or refuse saying nothing is.

    **This reads; it does not select.** Selecting an effect row cannot be done
    through the accessibility API on PowerPoint for Mac 16.113.1, and that was
    established by exhausting the alternatives rather than assumed — measured
    2026-11-02:

    ===========================================  ==========================================
    ``AXSelected`` on the row                    reported settable, write returns 0, never
                                                 reads back, on every row including the header
    ``AXSelectedRows`` on the outline            reported settable, write returns 0, never
                                                 reads back
    ``AXPress`` on the row                       not published (AX error -25206)
    ``AXShowDefaultUI`` / ``AXShowAlternateUI``  the row's only two actions; both return 0
                                                 and change nothing
    the row's ``AXCell``                         no actions at all
    selecting the shape                          selects the shape and no effect: rows stay
                                                 unselected and no section appears
    ``AXFocused`` on the outline                 **does** take and read back, and still
                                                 selects no row
    ===========================================  ==========================================

    ``agent-desktop`` reaches the same wall from the other side and says so:
    ``click`` on the row answers ``ACTION_FAILED`` — "Selection was delivered but
    its effect could not be verified".

    An earlier version of this function wrote ``AXSelected`` and waited for it to
    read back, which can only ever time out. The two after-animation values
    measured on 2026-11-02 were measured with an effect that something *outside*
    the driver had selected, which is why they looked like it worked.

    What does work is focusing the list and sending an arrow key, which
    :func:`select_pane_effect` does. This function stays because it is the
    cheaper question — "is an effect selected, and which one?" — and because the
    settings sections exist only while one is, so it is the precondition every
    pane setting is read against.

    The selection is not load-bearing for correctness, which is worth stating:
    :func:`attribute_modified_batch` compares the package either side of the save,
    so a measurement taken against the wrong effect is caught as a stray shape
    rather than recorded as fact.
    """
    rows = pane_effect_rows(backend)
    selected = [row for row in rows if row["selected"]]
    if not selected:
        raise ControlNotFound(
            "the Animation Pane has no effect selected, so it publishes none of its "
            f"settings sections {list(PANE_SECTIONS)}; nothing in the accessibility API "
            "selects one on this build (see selected_pane_effect) so an effect has to be "
            "selected by hand before this runs",
            rowCount=len(rows),
            describedAs=[row["describedAs"] for row in rows],
        )
    if len(selected) > 1:
        raise AmbiguousControl(
            f"the Animation Pane has {len(selected)} effects selected, so a pane setting would "
            "apply to more than the effect being measured",
            describedAs=[row["describedAs"] for row in selected],
        )
    return selected[0]


def expand_pane_section(backend: AXBackend, section: str, *, timeout: float) -> str:
    """Expand one Animation Pane settings section, and return how it got there.

    A section is a disclosure whose value is ``"1"`` when open, so an already
    open section is left alone: pressing it would close it and the control
    underneath would then be unreachable rather than merely slow.
    """
    if section not in PANE_SECTIONS:
        raise ControlNotFound(
            f"{section!r} is not one of this build's Animation Pane sections {list(PANE_SECTIONS)}",
            section=section,
        )
    view = held(backend)

    def opened() -> bool:
        view.stale()
        return _resolve_in(animation_pane(view), section).value == "1"

    if opened():
        return "alreadyExpanded"
    _resolve_in(animation_pane(view), section).press()
    view.stale()
    wait_until(backend, opened, timeout=timeout, what=f"the {section!r} section to expand")
    return "expanded"


def set_pane_checkbox(
    backend: AXBackend, label: str, *, to: bool, timeout: float
) -> dict[str, Any]:
    """Set one Animation Pane checkbox, and report what it was and became.

    The state is **read back** rather than assumed, because PowerPoint answers a
    landed toggle with a timeout often enough that the press's own result cannot
    be trusted: measured 2026-11-02, ``agent-desktop`` reported ``TIMEOUT``
    (``ax_error -25204``) with the postcondition already satisfied.

    A checkbox already in the asked-for state is left alone and reported as
    such, so the caller can reject it rather than record a save that proves
    nothing: pressing it would move it away from the value being measured.
    """
    view = held(backend)

    def state() -> bool:
        view.stale()
        return _resolve_in(animation_pane(view), label).value == "1"

    was = state()
    if was is to:
        return {"label": label, "was": was, "became": was, "pressed": False}
    _resolve_in(animation_pane(view), label).press()
    view.stale()
    wait_until(
        backend,
        lambda: state() is to,
        timeout=timeout,
        what=f"{label!r} to read back as {'checked' if to else 'cleared'}",
    )
    return {"label": label, "was": was, "became": to, "pressed": True}


def set_pane_choice(
    backend: AXBackend,
    *,
    from_value: str,
    to_value: str,
    reads_back_as: str | None = None,
    timeout: float,
) -> dict[str, Any]:
    """Pick one item from an Animation Pane popup, and report what it was and became.

    The popup is found by **the value it currently shows**, because that is its
    accessibility title: the pane's six popups are titled ``Anchored to
    Object``, ``Don't Dim``, ``[No Sound]``, ``On Click``, ``2 seconds
    (Medium)`` and ``(none)``, while their labels are separate static text with
    no ``AXTitleUIElement`` link to them. Resolving by role would be ambiguous
    six ways and resolving by position is the thing this driver does not do.

    So ``from_value`` is both the address and a precondition: a popup that is
    not showing it fails the target rather than measuring from a state the
    record would then describe wrongly.

    Pressing it attaches an ``AXMenu`` **as the popup's own child** — measured
    2026-11-02; no new window appears, unlike the ribbon's popups — and the item
    is pressed inside that menu.
    """
    view = held(backend)

    def popup(expected: str) -> AXNode:
        view.stale()
        node = _resolve_in(animation_pane(view), expected)
        if node.role != POPUP_ROLE:
            raise ControlNotFound(
                f"{expected!r} in the Animation Pane is a {node.role}, not a {POPUP_ROLE}",
                expected=expected,
                role=node.role,
            )
        return node

    opener = popup(from_value)
    opener.press()
    view.stale()

    def menu_item() -> AXNode | None:
        # The pane is walked for the item rather than the popup re-resolved by
        # title: once the menu is attached, ``Don't Dim`` names both the popup
        # **and** one of its own items, so resolving that title is ambiguous in
        # exactly the state this has to work in.
        view.stale()
        for node in walk(animation_pane(view)):
            if node.role in MENU_ITEM_ROLES and node.title == to_value:
                return node
        return None

    wait_until(
        backend,
        lambda: menu_item() is not None,
        timeout=timeout,
        what=f"{to_value!r} to appear in the {from_value!r} popup",
    )
    found = menu_item()
    if found is None:  # pragma: no cover - wait_until already raised
        raise ControlNotFound(f"no menu item titled {to_value!r}")
    found.press()
    view.stale()
    # A named choice leaves the popup showing its own name, so that is the
    # default read-back. A colour swatch does not — its title is the swatch's
    # name, not what the popup becomes — so the caller states the expected
    # read-back for those rather than the check being skipped: a press whose
    # effect cannot be confirmed in the UI is the failure mode that produced
    # wrong records on 2026-10-31.
    expected = reads_back_as or to_value
    wait_until(
        backend,
        lambda: _popup_shows(view, expected),
        timeout=timeout,
        what=f"the popup to read back as {expected!r}",
    )
    return {"from": from_value, "to": to_value, "readsBackAs": expected, "pressed": True}


def _popup_shows(view: Containers, value: str) -> bool:
    """True when a popup in the scope now reads ``value``."""
    view.stale()
    try:
        node = _resolve_in(animation_pane(view), value)
    except TargetFailure:
        return False
    return node.role == POPUP_ROLE


def press_save(backend: AXBackend, document: Path, *, timeout: float) -> None:
    """Press Save in the Quick Access toolbar and wait, bounded, for the file to change.

    Saving is the measurement: :func:`attribute_new_effect` and :func:`attribute_batch`
    read the file this writes, so there is no option to skip it. The document must
    already exist on disk so Save overwrites in place and PowerPoint does not open a
    Save As sheet, which this driver would not answer.

    It is pressed once per **batch** rather than once per target. ``Save`` lives in the
    window's toolbar and is resolved there: the lookup that found it used to walk the
    window, which cost 6.4 s to reach a button sitting two levels from the root.
    """
    # Rebound so everything below shares the caller's holder rather than resolving the
    # window again. ``held`` returns the caller's own when it has one.
    backend = view = held(backend)
    before = (document.stat().st_mtime_ns, document.stat().st_size) if document.exists() else None
    _resolve_in(resolve_scope(view, TOOLBAR_SCOPE), SAVE_LABEL).press()
    view.stale()
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
    """Refuse to start unless PowerPoint's document window is the expected capture deck.

    An ``AXPress`` goes to whatever window the title resolution found, and the wrong
    document would mean pressing ribbon controls, opening the Selection Pane and
    pressing ``Save`` on the operator's own deck. **That** is what this guard is for, and
    the document check is what enforces it. Nothing is sent before this passes.

    It does **not** require PowerPoint to be frontmost, and that is a deliberate change
    rather than a relaxation of the guard. Every action here is an accessibility
    ``AXPress`` or attribute write addressed to a specific element, so it reaches an
    occluded window and takes no focus — which is why the driver posts no mouse events
    in the first place. Requiring frontmost bought nothing the document check does not
    already cover, and it cost something real: a run of this length could not be started
    without taking the operator's screen, and a stray app coming forward mid-run would
    have aborted it. The document window is still resolved by title from a fresh read,
    so a second deck opening in front changes nothing about which window is driven.
    """
    if not backend.trusted():
        raise DriverRefusal(
            "this process does not hold the Accessibility grant; add the terminal running it "
            "to System Settings > Privacy & Security > Accessibility"
        )
    title = normalise_document_title(held(backend).window().title)
    if title != normalise_document_title(expected_document):
        raise DriverRefusal(
            f"PowerPoint's document window is {title!r}, not the expected capture deck "
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
    selection_row: str | None = None,
    selection_row_index: int | None = None,
    prerequisite: dict[str, Any] | None = None,
    value_press: dict[str, Any] | None = None,
    effect: dict[str, Any] | None = None,
    effect_count: tuple[int, int] | None = None,
    batch_index: int | None = None,
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
    ``shapeName`` and ``shapeSpid`` say which shape was aimed at, ``selectionRowIndex``,
    ``selectionRow`` and ``selectedBy`` say how it was selected, ``attributedSpid`` and
    ``effectCTn`` say which effect the package gained and what it says, and
    ``effectCount`` says the slide went from n to n+1. A merged view is read per target by
    matching ``attributedSpid`` against the slide's ``p:spTgt/@spid``.

    ``selectedBy`` replaced a ``clickPoint``, and the difference is the point: a merged
    evidence file now says each capture was driven by a Selection Pane row rather than by
    a coordinate, so a record from this driver cannot be confused with one from the click
    version that captured 2 of 12. It is keyed on ``selectionRowIndex`` rather than on
    ``selectionRow``, because the row that was selected is always known while the name it
    published is not: an unscrolled row publishes no label, so ``selectionRow`` is null
    on a perfectly good capture and only ``selectionRowIndex`` says a row was selected at
    all.

    ``batchIndex`` says which Save judged this record, and ``effectCount`` is that
    batch's before/after count for the slide rather than this target's own — with ten
    targets per save the slide goes from n to n+10 and no single record owns the step.
    What this record owns is ``newEffectCount``: how many ``p:cTn`` nodes appeared on
    **its** ``shapeSpid``, which is the figure the attribution gate actually tested.
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
        "selectionRow": selection_row,
        "selectionRowIndex": selection_row_index,
        "selectedBy": SELECTED_BY if selection_row_index is not None else None,
        # Which press made the target's control exist. A value behind an effect
        # is meaningless without it: `From Bottom` is a direction *of Fly In*,
        # and a record that did not say so could be read as a global setting.
        "prerequisite": prerequisite,
        # How many times the value press had to be made, and whether the package
        # changed. A press inside the Effect Options window is intermittent, and
        # a record that did not say so could not be told from a value that
        # happens to equal the effect's default.
        "valuePress": value_press,
        "applied": applied,
        "matchedTitle": matched_title,
        "ribbonReadBack": readback or {"start": None, "duration": None},
        "attributedSpid": effect.get("spid") if effect else None,
        "effectCTn": effect.get("cTn") if effect else None,
        # All of the shape's effects when the press left more than one, which a
        # target with a prerequisite always does. ``effectCTn`` above is the
        # representative; this is what lets the offline side pick the one
        # carrying the pressed value rather than the tile's default.
        "effectCTns": effect.get("allCTns") if effect else None,
        "newEffectCount": effect.get("newEffectCount") if effect else None,
        "effectCount": {
            "before": effect_count[0] if effect_count else None,
            "after": effect_count[1] if effect_count else None,
        },
        "batchIndex": batch_index,
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
    side may assume one. A target with no name has no Selection Pane row to match and
    nothing to attribute an effect to, so this refuses the whole run rather than
    producing a record per target that says the same thing.
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
    #: Targets pressed before one Save judges them all. ``1`` saves per target, which is
    #: the strongest attribution available and the slowest; see :func:`capture_batch`.
    batch_size: int = DEFAULT_BATCH_SIZE
    #: How many times a target carrying ``verifyChange`` re-presses its value while
    #: the package says nothing changed. Costs two saves per attempt, so it only
    #: applies to those targets.
    value_press_attempts: int = DEFAULT_VALUE_PRESS_ATTEMPTS

    @property
    def expected_title(self) -> str:
        return self.expect_document or self.document.stem

    @property
    def readback_path(self) -> Path:
        return self.out_dir / READBACK_NAME

    @property
    def package_path(self) -> Path:
        return self.out_dir / PACKAGE_NAME


def ensure_tab(backend: AXBackend, path: Sequence[str], *, timeout: float) -> str:
    """Make the ribbon tab named by ``path`` active, and return what it took.

    Pressing a tab that is already active **collapses the ribbon**, so the tab is pressed
    only when its own controls are not already reachable. Reachability is checked before
    the tab is resolved, because three live elements are titled 'Animations' — an
    ``AXRadioButton`` and two ``AXGroup``s — so resolving it raises
    :class:`AmbiguousControl` even when nothing needs pressing.
    """
    if len(path) < 2:
        raise ControlNotFound(f"a GUI path needs a ribbon tab and a control, got {list(path)}")
    view = held(backend)
    scope = RIBBON_SCOPE
    if _reachable_any(resolve_scope(view, scope), [path[1]]):
        return "alreadyActive"
    _resolve_in(resolve_scope(view, scope), path[0]).press()
    view.stale()
    wait_until(
        view,
        lambda: _reachable_any(resolve_scope(view, scope), [path[1]]),
        timeout=timeout,
        what=f"{path[1]!r} after selecting the {path[0]!r} tab",
    )
    return "pressed"


def press_target(
    backend: AXBackend,
    target: dict[str, Any],
    settings: CaptureSettings,
    shape_name: str,
    carried: dict[str, Any],
) -> None:
    """Drive one target up to and including its press. No save and no attribution.

    Fills ``carried`` as it goes, so a failure part-way leaves the record carrying what
    had been measured by then — the shape's spid, the row it selected — rather than
    nothing.

    Raises :class:`TargetFailure`. The save and the verification belong to the batch,
    because one save judges the whole batch.
    """
    timeout = settings.timeout
    carried["shape_spid"] = read_shape_spid(settings.document, target["slideIndex"], shape_name)
    # The shape is selected through its Selection Pane row, which does not depend on
    # which ribbon tab is active — but the tab still comes first. Opening the pane
    # leaves the ribbon on Home, and a gallery on an inactive tab is not in the tree
    # at all, so making the target's own tab active here keeps the press that follows
    # looking at a materialized gallery rather than waiting for one that cannot
    # appear. Measured against an earlier version: a freshly opened deck starts on
    # Home and all 76 targets timed out on 'Emphasis Effects'.
    ensure_tab(backend, target["guiPath"], timeout=timeout)
    row_index, row_count = shape_row_index(settings.document, target["slideIndex"], shape_name)
    selection = select_shape(
        backend, shape_name, row_index=row_index, row_count=row_count, timeout=timeout
    )
    carried["selection_row_index"] = selection.index
    carried["selection_row"] = selection.name

    # A target whose control only exists once an effect is applied names the
    # press that applies one. Measured: ``Effect Options`` and ``Trigger`` read
    # `enabled=False` until a gallery tile has been pressed, exactly as
    # ``Duration:`` did, so a direction cannot be reached without this.
    #
    # The attribution gate is unaffected, and that is why this is safe to add:
    # the prerequisite applies the effect and the target's own press *modifies*
    # that same effect, so the shape still gains exactly one ``p:cTn`` and the
    # record is still credited by its own ``spid``. A prerequisite that landed
    # on another shape would be caught by the stray-spid gate like any press.
    prerequisite = target.get("prerequisite")
    if prerequisite:
        ensure_tab(backend, prerequisite, timeout=timeout)
        before = press_path(
            backend,
            prerequisite,
            timeout=timeout,
            alternatives=tuple(target.get("prerequisiteAlternatives", ())),
        )
        carried["prerequisite"] = {
            "guiPath": list(prerequisite),
            "matchedTitle": before.matched_title,
            "steps": before.as_dicts(),
        }
        # Close the window the target's own path will open, when the target asks
        # for it. Measured: three Spin amounts and one Fly In direction wrote the
        # effect's **default** instead of the value pressed — `Half Spin` and
        # `Quarter Spin` both landed on `by="21600000"`, which is `Full Spin`,
        # and `From Right` came out byte-identical to `From Bottom`. The press
        # reaches the control and the application does not act on it, which is
        # the signature of a window held over from the previous target: reusing
        # it is what :func:`press_path`'s ``windowAlreadyOpen`` branch does, and
        # it exists to avoid the opposite trap of pressing an open window's
        # control shut. Opt-in per target rather than always, so the 76 motion
        # paths and transitions that this path already captured keep the exact
        # sequence they were measured with.
        if target.get("reopenWindow"):
            closed = close_window(backend, target["guiPath"][1], timeout=timeout)
            carried["prerequisite"]["reopenedWindow"] = closed
        # **Do not re-select the shape here.** It was tried, to stop the value
        # press adding a second effect instead of editing the first, and it
        # breaks the route outright: selecting the shape in the Selection Pane
        # deselects its *effect*, so ``Effect Options`` goes disabled again and
        # the next step times out waiting for a window that cannot open. The
        # two states are exclusive — shape selected, or effect selected — and
        # the tile press is what leaves the effect selected.
        #
        # So the value press adding an effect is the application's behaviour and
        # not a selection bug: a tile press writes the tile's default, and a
        # press inside the window writes a **second** effect carrying the value.
        # Measured: 2 effects on the shape (``by`` 150000 and 400000) against 1
        # for a tile-only control run. :func:`attribute_batch` is what has to
        # account for that, by telling the default apart from the value.
        ensure_tab(backend, target["guiPath"], timeout=timeout)
    if prerequisite and target.get("verifyChange"):
        # The value press is verified against the package rather than trusted,
        # and retried when it changed nothing. Without this the driver cannot
        # tell a press that did not take from a value that **equals** the
        # default — which is exactly how ``Full Spin`` and ``From Bottom`` read
        # correct while ``Quarter Spin`` and ``From Right`` read wrong. Costs
        # one extra save per target: the prerequisite's effect has to be on disk
        # to be the thing compared against.
        press_save(backend, settings.document, timeout=timeout)
        before = effect_signatures(settings.document, target["slideIndex"], carried["shape_spid"])
        attempts: list[dict[str, Any]] = []
        for attempt in range(1, settings.value_press_attempts + 1):
            result = press_path(
                backend,
                target["guiPath"],
                timeout=timeout,
                alternatives=tuple(target.get("titleAlternatives", ())),
            )
            press_save(backend, settings.document, timeout=timeout)
            after = effect_signatures(
                settings.document, target["slideIndex"], carried["shape_spid"]
            )
            changed = after != before
            attempts.append({"attempt": attempt, "changed": changed, "effects": len(after)})
            if changed:
                break
        carried["value_press"] = {
            "attempts": attempts,
            "changed": attempts[-1]["changed"],
            "defaultSignatures": len(before),
        }
        if not attempts[-1]["changed"]:
            raise EffectNotAdded(
                f"the value press left the shape's effects byte-identical to what the "
                f"prerequisite wrote, after {len(attempts)} attempt(s); the press reaches the "
                "control and the application does not act on it, so this value is not "
                "measured. Raise --value-press-attempts if a higher flake rate is plausible",
                expectedSpid=carried["shape_spid"],
                attempts=len(attempts),
                effectsBefore=len(before),
                effectsAfter=len(after),
            )
    else:
        result = press_path(
            backend,
            target["guiPath"],
            timeout=timeout,
            alternatives=tuple(target.get("titleAlternatives", ())),
        )
    carried["matched_title"] = result.matched_title
    carried["steps"] = result.as_dicts()
    # Read here, not after the batch's save: the ribbon shows the SELECTED shape's values
    # and the next target in the batch moves the selection.
    carried["readback"] = ribbon_readback(backend)


def capture_batch(
    backend: AXBackend,
    batch: Sequence[dict[str, Any]],
    settings: CaptureSettings,
    shape_names: dict[str, str],
    *,
    batch_index: int,
) -> list[dict[str, Any]]:
    """Press a batch of targets, save once, then attribute each by its own ``spid``.

    Returns one record per target in the batch, in batch order, successful or not.

    ## Why a batch

    Saving was never the expensive part — the full-tree walking was — but a save is still
    a save, and 76 of them are 76 more than one per ten targets. The order is the same as
    it was per target and for the same reason: press, then save, then verify, because the
    verification **is** a read of the saved package. A save that does not land therefore
    rejects every target that was pressed into it rather than being a footnote on a
    passing record — without the save there is no evidence either way.

    ## What the evidence still is

    Unchanged in kind, per target: the target's own ``spid`` must have gained at least one
    effect in a package PowerPoint actually wrote, and that effect's own ``p:cTn`` is
    recorded against this key. The batch adds one gate of its own — **no spid outside the
    batch may have gained anything** — because an effect on a shape nobody selected means
    a press landed somewhere the run cannot account for, and that fails the batch naming
    the stray spid.

    A target whose own spid gained nothing is rejected **individually**, and the rest of
    the batch is still credited. One bad target does not cost nine good ones.

    ## What a batch gives up, stated rather than implied

    **Crash granularity.** A crash costs the presses since the last save rather than one.
    They are not lost work in the accounting sense — a target with no record is
    uncaptured, so a resumed run re-presses them — but they are lost time.

    **Telling two targets inside one batch apart when they swap effects.** If target A's
    press animated B's shape and B's animated A's, both spids gained one effect and no
    spid outside the batch gained anything, so the package cannot say whose value is
    whose. A save per target can, and ``--batch-size 1`` still does. This is a real
    reduction and it is not covered by the stray-spid gate; what bounds it is that the
    mechanism which used to cause it — a selection that did not take, so the press
    replaced the previously selected shape's effect — is caught **before** any press by
    :func:`select_shape`'s read-back of ``AXSelected``, and that a press landing on a
    shape outside the batch is caught by the stray-spid gate.
    """
    if not batch:
        return []
    slide_index = batch[0]["slideIndex"]
    records: dict[str, dict[str, Any]] = {}
    pressed: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def reject(target: dict[str, Any], carried: dict[str, Any], exc: TargetFailure, **extra: Any) -> None:
        records[target["key"]] = capture_record(
            target, rejected=True, error=exc.as_error(), **extra, **carried
        )

    try:
        before = read_slide_effects(settings.document, slide_index)
    except TargetFailure as exc:
        # The batch cannot be judged at all, so every target in it is rejected before a
        # single press rather than pressed into evidence that cannot be read.
        for target in batch:
            reject(target, {"batch_index": batch_index}, exc)
        return [records[target["key"]] for target in batch]

    for target in batch:
        carried: dict[str, Any] = {
            "batch_index": batch_index,
            "shape_name": shape_names[target["key"]],
        }
        try:
            press_target(backend, target, settings, shape_names[target["key"]], carried)
        except TargetFailure as exc:
            reject(target, carried, exc)
            continue
        pressed.append((target, carried))

    if pressed:
        try:
            press_save(backend, settings.document, timeout=settings.timeout)
        except TargetFailure as exc:
            for target, carried in pressed:
                reject(target, carried, exc, save_error=exc.as_error())
            return [records[target["key"]] for target in batch]
        for _target, carried in pressed:
            carried["saved"] = True

        try:
            after = read_slide_effects(settings.document, slide_index)
        except TargetFailure as exc:
            for target, carried in pressed:
                reject(target, carried, exc)
            return [records[target["key"]] for target in batch]

        counts = (len(before), len(after))
        try:
            credited = attribute_batch(
                before, after, [carried["shape_spid"] for _target, carried in pressed]
            )
        except TargetFailure as exc:
            for target, carried in pressed:
                reject(target, carried, exc, effect_count=counts)
            return [records[target["key"]] for target in batch]

        for target, carried in pressed:
            effect = credited.get(carried["shape_spid"])
            if effect is None:
                reject(
                    target,
                    carried,
                    not_added_in_batch(before, after, carried["shape_spid"]),
                    effect_count=counts,
                )
                continue
            records[target["key"]] = capture_record(
                target,
                applied=" > ".join(target["guiPath"]),
                effect=effect,
                effect_count=counts,
                **carried,
            )

    return [records[target["key"]] for target in batch]


def plan_batches(
    todo: Sequence[dict[str, Any]], size: int
) -> list[list[dict[str, Any]]]:
    """Split the targets to run into batches, never mixing two slides in one.

    One save judges one batch and the judgement reads one slide's effects, so a batch
    spanning two slides could not be attributed. The plan puts all 76 targets on one
    slide; a split plan simply produces more, smaller batches.
    """
    if size < 1:
        raise DriverRefusal(f"a batch must hold at least one target, got {size}")
    batches: list[list[dict[str, Any]]] = []
    for target in todo:
        if (
            not batches
            or len(batches[-1]) >= size
            or batches[-1][0]["slideIndex"] != target["slideIndex"]
        ):
            batches.append([])
        batches[-1].append(target)
    return batches


def report_to_stderr(message: str) -> None:
    """Write one progress line where it cannot contaminate the summary on stdout."""
    print(message, file=sys.stderr, flush=True)


def run_capture(
    plan: dict[str, Any],
    settings: CaptureSettings,
    backend: AXBackend,
    *,
    version: str | None = None,
    progress: Callable[[str], None] = report_to_stderr,
) -> dict[str, Any]:
    """Run a whole plan. Returns the summary; writes the read-back incrementally.

    A line per batch goes to ``progress`` — stderr by default, so stdout stays pure JSON.
    A 76-target run takes long enough that an operator with no output would be looking at
    something indistinguishable from a hang.
    """
    targets = list(plan.get("targets", []))
    shape_names = plan_shape_names(plan)
    settings.out_dir.mkdir(parents=True, exist_ok=True)
    existing = read_records(settings.readback_path)
    todo, skipped = split_plan(targets, existing, force=settings.force)
    batches = plan_batches(todo, settings.batch_size)

    title = assert_ready(backend, settings.expected_title)
    try:
        # Once per run, not per target: pressing ``Selection Pane...`` again would close
        # the pane. A pane that cannot be opened is the whole run's precondition rather
        # than one target's, so it refuses with an actionable message instead of
        # producing 76 identical records.
        selection_pane = open_selection_pane(backend, timeout=settings.timeout)
    except TargetFailure as exc:
        raise DriverRefusal(f"cannot open the Selection Pane: {exc}") from exc

    keep = retained_records(existing, todo)
    with settings.readback_path.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(application_record(version), ensure_ascii=False) + "\n")
        for record in keep:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        stream.flush()

        written: list[dict[str, Any]] = []
        started = backend.now()
        for index, batch in enumerate(batches, start=1):
            # One Containers per batch, dropped at every action inside it: the window and
            # its containers are resolved once for a stretch of work rather than once per
            # lookup, which is what removed several full window walks per target.
            for record in capture_batch(
                held(backend), batch, settings, shape_names, batch_index=index
            ):
                written.append(record)
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            progress(
                f"batch {index}/{len(batches)}: {len(batch)} targets attempted, "
                f"{len(written)}/{len(todo)} done, "
                f"{sum(1 for record in written if not record['rejected'])} captured, "
                f"{backend.now() - started:.0f}s elapsed"
            )

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
        "batchSize": settings.batch_size,
        "batches": len(batches),
        "attributed": sum(1 for record in written if record["attributed"]),
        "saveFailures": sum(1 for record in written if record["saveError"]),
        "retainedRecords": len(keep),
        "shapeSelection": {"mechanism": SELECTED_BY, "selectionPane": selection_pane},
        "failures": [
            {
                "key": record["catalogKey"],
                "slideIndex": record["slideIndex"],
                "batchIndex": record["batchIndex"],
                "shapeName": record["shapeName"],
                "shapeSpid": record["shapeSpid"],
                "selectionRow": record["selectionRow"],
                "selectionRowIndex": record["selectionRowIndex"],
                "attributedSpid": record["attributedSpid"],
                "error": record["error"],
            }
            for record in failures
        ],
    }


# --- the live backend, imported lazily --------------------------------------
class LiveAXNode:
    """One live accessibility element. Every attribute is read on access, never cached."""

    __slots__ = ("_element", "_ax")

    def __init__(self, element: Any, ax: Any) -> None:
        self._element = element
        self._ax = ax

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
    def selected(self) -> bool:
        return bool(self._attribute(self._ax.kAXSelectedAttribute))

    @property
    def index(self) -> int | None:
        """``AXIndex``: the row's own position in its outline, as it reports it.

        This is what makes a row identifiable when the pane publishes only some of them.
        Measured on the Selection Pane's rows: ``AXIndex`` 0, 1, 76 and 151 for the
        published rows at those offsets, so a row's self-reported index and its offset
        agree when every row is published — and the self-reported one is still readable
        when they are not. ``None`` for an element that publishes no ``AXIndex``.
        """
        value = self._attribute("AXIndex")
        return None if value is None else int(value)

    @property
    def children(self) -> Sequence[AXNode]:
        kids = self._attribute(self._ax.kAXChildrenAttribute) or []
        return [LiveAXNode(child, self._ax) for child in kids]

    @property
    def rows(self) -> Sequence[AXNode] | None:
        """Return the element's ``AXRows``, or None when it publishes none.

        An outline publishes more of its rows here than ``AXChildren`` does. Measured on
        an idle Selection Pane: ``AXRows`` 152, ``AXVisibleRows`` 24, ``AXChildren`` 153
        — and walking children had the driver report "the pane shows 62 names", then 47,
        which is how 26 targets failed to find a row that existed.

        It is **not** a promise of all of them. During a run the same pane published 43,
        54, 61, 63, 74, 88 and 91 rows on consecutive reads of a 152-shape slide, which
        is why a row is found by its own ``AXIndex`` rather than by its offset here.
        """
        rows = self._attribute("AXRows")
        if rows is None:
            return None
        return [LiveAXNode(row, self._ax) for row in rows]

    def press(self) -> None:
        error = self._ax.AXUIElementPerformAction(self._element, self._ax.kAXPressAction)
        if error:
            raise TargetFailure(f"AXPress on {self.title!r} ({self.role}) failed with AX error {error}")

    def set_focused(self, focused: bool) -> None:
        """Write ``AXFocused``. The second and last attribute this driver sets.

        It exists for one element: the Animation Pane's effect list, which has to
        hold keyboard focus before an arrow key can move its selection. Measured
        2026-11-02, this is the **only** write that surface accepts — ``AXSelected``
        on a row and ``AXSelectedRows`` on the outline both report settable, return
        0 and never read back, while this one takes and the application's
        ``AXFocusedUIElement`` becomes the list.
        """
        error = self._ax.AXUIElementSetAttributeValue(
            self._element, self._ax.kAXFocusedAttribute, bool(focused)
        )
        if error:
            raise TargetFailure(
                f"setting AXFocused on a {self.role} failed with AX error {error}"
            )

    def set_selected(self, selected: bool) -> None:
        """Write ``AXSelected``. One of the two attributes this driver ever sets.

        A Selection Pane row has no ``AXPress`` — its actions are ``AXShowDefaultUI``,
        ``AXShowAlternateUI`` and a Rename — so setting this attribute is how an outline
        row is selected. It is deliberately **not** a general "set any attribute" method:
        a narrow one cannot be reached for when something else looks like it might work,
        which is how the 2026-10-31 run came to set ``kAXSelected`` on navigator cells
        that never read it back.

        There is still no slide selection here. That attribute never took on the
        navigator's cells; it does take on an outline's rows, which is a different
        element with a different mechanism, and this method's read-back is what says so
        per target rather than assuming it.
        """
        error = self._ax.AXUIElementSetAttributeValue(
            self._element, self._ax.kAXSelectedAttribute, bool(selected)
        )
        if error:
            raise TargetFailure(
                f"setting AXSelected on a {self.role} failed with AX error {error}; the row "
                f"carries {[child.value for child in self.children if child.value]}"
            )


class LiveAXBackend:
    """The real host. pyobjc is imported here so importing this module never needs it.

    It posts **no mouse events**. It posts exactly one kind of event — an arrow key,
    to PowerPoint's own process — for the one surface where no accessibility write
    works at all: see :meth:`post_key` and :func:`select_pane_effect`. So Quartz is
    imported again, inside that method, and the documented invocation carries
    ``--with pyobjc-framework-Quartz``.
    """

    def __init__(self) -> None:
        import ApplicationServices as ax
        from AppKit import NSWorkspace

        self._ax = ax
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
        return [LiveAXNode(window, self._ax) for window in (windows or [])]

    # There is deliberately no ``click``. It posted a global mouse event at a derived
    # canvas point, with a click state, a move settle, a button hold and a 0.35 s settle
    # after the up, and its last live run captured 2 of 12 attempted targets: the pointer
    # landed in the right place and the shape stayed unselected. Shape selection is a
    # Selection Pane row now, so this backend posts no **mouse** events at all.

    def focused_window_title(self) -> str | None:
        """The title of the window a key sent to this process would reach.

        Read rather than set: ``AXFocusedWindow`` reports ``settable=False`` on this
        application, so the driver can require the right deck and cannot redirect to
        it. Requiring is enough — and is the point: the measuring host had three
        decks open in one process (``cx-deck``, ``spin2-deck``, ``eo-deck``), so a
        key aimed at "PowerPoint" is aimed at whichever of them has focus.
        """
        element = self._application()
        error, window = self._ax.AXUIElementCopyAttributeValue(element, "AXFocusedWindow", None)
        if error or window is None:
            return None
        return LiveAXNode(window, self._ax).title

    def focused_element_role(self) -> str | None:
        """The role of the element a key sent to this process would reach.

        The second half of the precondition. A window's focused element is where its
        key events land, so this is what says the arrow key will move the effect
        list's selection rather than the slide, the canvas or a text box.
        """
        element = self._application()
        error, focused = self._ax.AXUIElementCopyAttributeValue(
            element, "AXFocusedUIElement", None
        )
        if error or focused is None:
            return None
        return LiveAXNode(focused, self._ax).role

    def post_key(self, keycode: int) -> None:
        """Post one key, down then up, **to PowerPoint's process**.

        ``CGEventPostToPid`` rather than ``CGEventPost``: a posted-to-pid event is
        delivered to the named process and reaches nothing else, so it cannot be
        typed into the operator's own work and cannot reach another application. It
        moves no cursor and takes no focus, which is why this is not the mouse event
        that was removed — that one needed a screen coordinate and a pointer, and
        this one needs neither.

        Quartz is imported here, and only here, for the same reason pyobjc is
        imported in this class at all: importing this module must not need it. The
        documented invocation therefore carries
        ``--with pyobjc-framework-Quartz`` again.
        """
        import Quartz

        for pressed in (True, False):
            event = Quartz.CGEventCreateKeyboardEvent(None, keycode, pressed)
            if event is None:  # pragma: no cover - the binding would have to fail
                raise TargetFailure(f"could not create a key event for keycode {keycode}")
            Quartz.CGEventPostToPid(self._pid, event)

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
            "It selects each shape by its Selection Pane row and presses ribbon controls by "
            "title, so it never moves the pointer and posts no mouse events; it refuses to "
            "start unless PowerPoint has the expected capture deck as its document window. "
            "It does not require PowerPoint to be frontmost: see assert_ready."
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
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=(
            "targets pressed before one Save judges them all (default "
            f"{DEFAULT_BATCH_SIZE}). Each target is still attributed by its own spid against "
            "the saved package; 1 saves per target, which additionally separates two targets "
            "that swapped effects, at one save each"
        ),
    )
    parser.add_argument(
        "--value-press-attempts",
        type=int,
        default=DEFAULT_VALUE_PRESS_ATTEMPTS,
        help=(
            "how many times a target carrying verifyChange re-presses its value while the "
            f"package says nothing changed (default {DEFAULT_VALUE_PRESS_ATTEMPTS}). Two "
            "saves per attempt, so it costs nothing on targets without the flag"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "re-capture targets that already have a record; regenerate the deck first, because a "
            "re-press replaces the shape's existing effect and the attribution needs a new one"
        ),
    )
    # There is no --pane-frame, --pane-role or --zoom. They existed to correct a canvas
    # click's coordinate mapping, and there is no coordinate and no click any more.
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
            "controls and selects shapes in the frontmost application's Selection Pane.",
            file=sys.stderr,
        )
        return 2

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    try:
        plan_shape_names(plan)
    except DriverRefusal as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    if args.batch_size < 1:
        print(f"FAIL: --batch-size must be at least 1, got {args.batch_size}", file=sys.stderr)
        return 2
    settings = CaptureSettings(
        out_dir=args.out,
        document=args.document,
        expect_document=args.expect_document,
        timeout=args.timeout,
        force=args.force,
        batch_size=args.batch_size,
        value_press_attempts=args.value_press_attempts,
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
            "--with lxml",
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
