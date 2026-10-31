#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Derive the GUI capture plan from the catalog's own remaining gaps, and build its deck.

Development-only, like everything else in this directory. This module touches no
application: it reads the two checked-in catalogue artefacts and writes JSON plus, on
request, an sdpm deck. :mod:`gui_capture` is what drives PowerPoint.

## Why the plan is derived rather than written

A hand-written target list drifts from the catalog the moment a capture promotes an
entry, and the drift is invisible — the list still looks complete. So the plan is read
out of the catalog: the entries whose ``ooxml.requiresCapture`` is true, restricted to
the key namespaces the GUI can address, with the GUI path each entry's own metadata
implies. Re-emitting after a capture run produces a shorter plan, with no edit.

## Four lists, because "not in the plan" has four different meanings

Nothing is dropped silently. Every capture-required entry lands in exactly one list:

``targets``
    GUI-addressable and resolvable by title in one press. These are what the driver runs,
    one **shape** each.
``deferredTargets``
    GUI-addressable namespace, but the metadata does not imply a pressable path — a
    motion path that must be *drawn*, a Media gallery that needs a media object, the
    After animation dropdown inside the Animation Pane's effect dialog, and the Effect
    Options direction labels, which depend on **which effect is applied** and so cannot
    be derived from a direction entry alone. The driver supports a ``prerequisite`` path
    for exactly this shape, so a deferral is about the derivation, not the driver.
``setAsideScriptingEnumerators``
    The ``MsoAnim*`` candidates. The GUI applies a value **by label**; a scripting
    enumerator is a different identity. Closing one through the GUI would assert a name
    correspondence rather than measure a value, which is the error
    ``computer-use.md`` records under "What the GUI route cannot establish".
``gapsWithoutCaptureFlag``
    GUI-addressable entries that carry an ``ooxml.gap`` and
    ``verification: powerPointReadBackRequired`` but no ``requiresCapture`` flag — the
    After animation, sound, timing and start values of ``computer-use.md`` Steps 3 to 5.
    They are listed so the selection rule's edge is visible instead of looking like
    coverage.

## The deck: one slide, many shapes

The deck used to be one slide per target. The 2026-10-31 live run proved that shape
unusable: **every** one of its 76 targets was rejected in slide selection, because the
navigator's cells expose no actions and publish only the handful currently scrolled into
view (``computer-use.md``, "Why the driver does not select slides"). So the deck is now
**one slide carrying one named shape per target**, laid out as a grid by
:func:`grid_layout`, and the driver selects a target by clicking its own shape.

That is not a workaround with weaker evidence; it is stronger evidence. A gallery press
replaces the effect **of the selected shape**, so each target's effect lands in the
slide's ``p:timing`` carrying ``p:spTgt/@spid``, and the slide's ``p:cNvPr/@id``/``@name``
map that spid back to the shape and hence to the target. "Slide N is target N" survived
nothing; an spid survives reordering and catches a mis-aimed click instead of recording
the wrong key.

The grid is derived from the target count and checked rather than eyeballed: shapes may
not overlap, a shape's centre must sit :data:`CLICK_MARGIN_PX` inside its own edges, and
it must clear every other shape by :data:`NEIGHBOUR_CLEARANCE_PX`, so a click aimed at a
centre cannot land on a neighbour. If the count does not fit one slide under those
constraints the plan splits across as few slides as it can and says so in ``deck``.

sdpm derives a shape's **name** from its geometry rather than from the element id the
deck JSON asks for — that is the trap that bit the single-shape version — so
``--generate`` reads every name back out of the package it actually wrote, matching each
target by its shape's position, and writes the ``target key -> shape name`` mapping into
the plan.

``--generate`` builds through ``sdpm.api.generate`` with **both motion switches off** so
sdpm contributes no motion of its own and every ``p:timing`` tree in the saved package
came from PowerPoint.

Usage::

    uv run python scripts/animation_catalog/gui_capture_plan.py --emit-plan \\
      --out /abs/out/plan.json --build-deck /abs/out/deck --generate /abs/out/capture-deck.pptx
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = REPO_ROOT / "sdpm" / "references" / "catalogs"
DEFAULT_CATALOG = CATALOG_DIR / "powerpoint-animation-catalog.json"
DEFAULT_MANIFEST = CATALOG_DIR / "powerpoint-gui-surface-16.113.1.json"
DEFAULT_TEMPLATE = REPO_ROOT / "sdpm" / "templates" / "blank-dark.pptx"

#: The driver this plan feeds.
DRIVER = "scripts/animation_catalog/gui_capture.py"

#: Element id prefixes the deck JSON asks for. sdpm names the *shape* itself from its
#: geometry rather than from these, so the names the driver looks up are read back out of
#: the generated package by :func:`resolve_shape_names` instead of being assumed here.
SHAPE_ELEMENT_PREFIX = "target"
LABEL_ELEMENT_PREFIX = "key"

#: The geometry preset of the clickable shape, which is how it is told apart in the
#: package from the label text boxes (python-pptx gives those ``prst="rect"``).
SHAPE_PRESET = "roundRect"

#: sdpm's deck coordinates are in a fixed 1920x1080 "px" basis that it maps onto whatever
#: the template's slide size is, so a 960x540 pt slide makes one px half a point. The
#: grid is computed in this basis because that is what the deck JSON carries; the
#: separation constraints below are therefore px and worth halving before comparing them
#: to anything in points.
DECK_BASIS_PX = (1920.0, 1080.0)

#: Empty border kept around the whole grid, in deck px.
SLIDE_MARGIN_PX = 48.0

#: Empty space kept inside each grid cell: horizontally between neighbouring shapes, and
#: vertically between a shape and the row below it. The label sits in the vertical gap.
CELL_GAP_X_PX = 28.0
CELL_GAP_Y_PX = 20.0
#: Tall enough for the two lines :func:`label_text` splits a key into. The longest key
#: today is 46 characters, which does not fit a 100 pt wide box on one line at any size a
#: person would read, so the label is two lines rather than one overflowing into its
#: neighbour.
#: One line, not two. The label is for a human glancing at the deck; the authoritative
#: key lives in the plan and the attribution is by ``spid``, so the label does not need
#: to carry the whole key. Height bought back here goes straight into the shape, and
#: height was the limiting axis: a 100x22 pt shape was the measured cause of clicks
#: landing on empty canvas, which left the previous shape selected so the next press
#: overwrote ITS effect — 71 presses produced five effects.
LABEL_HEIGHT_PX = 16.0

#: Half the minimum side of a shape: the distance from the point the driver clicks to the
#: nearest edge of the shape it is aiming at. 20 px is 10 pt, which is 9.2 screen points
#: at the 92% zoom the 2026-10-31 session measured.
CLICK_MARGIN_PX = 20.0

#: The distance a click point must keep from **every other** shape on its slide. This is
#: the constraint that makes a mis-aimed click miss rather than silently select the
#: neighbour, which would apply the right effect to the wrong target.
NEIGHBOUR_CLEARANCE_PX = 20.0

#: Preferred cell width-to-height ratio. Squarer cells than the 2.2 first chosen: a
#: click's accuracy is bounded by the shape's **smaller** side, and at 2.2 that side was
#: 22 pt. The grid picks the column count whose cell aspect comes closest to this.
CELL_ASPECT = 1.5

#: Font sizes, in points, for the ordinal inside a shape and the key below it.
SHAPE_FONT_PT = 11
LABEL_FONT_PT = 6

#: How far, in points, a shape's centre in the generated package may sit from the centre
#: the grid asked for before :func:`resolve_shape_names` refuses to match the two. Any
#: two shapes are at least ``CELL_GAP_X_PX`` apart, so this cannot match a neighbour.
MATCH_TOLERANCE_PT = 1.0

#: 914400 EMU per inch, 72 points per inch.
EMU_PER_POINT = 12700

#: Key namespaces the GUI can address at all. A capture-required entry outside these is
#: a scripting enumerator and goes to the set-aside list.
GUI_NAMESPACES = (
    "animation.gallery.",
    "animation.effectOptions.",
    "animation.afterAnimation.",
    "animation.timing.",
    "animation.sound.",
    "animation.start.",
)

#: Ribbon control per gallery category. ``computer-use.md`` records these as separate
#: named galleries on this build, each enumerating its own tiles.
GALLERY_CONTROL = {
    "entrance": "Entrance Effects",
    "emphasis": "Emphasis Effects",
    "exit": "Exit Effects",
}

#: The ribbon menu button whose own window lists the motion-path presets. Measured: the
#: pilot capture of ``animation.gallery.motionPath.lines`` went through exactly this
#: path, and its evidence is checked in under ``tests/fixtures/animations/gui-only/``.
PATH_ANIMATION_CONTROL = "Path Animation"
ANIMATIONS_TAB = "Animations"

#: Labels PowerPoint does not spell the way the catalog key does. Kept explicit and
#: short: every other title is derived mechanically from the key, and a title that turns
#: out to be wrong is a *recorded failure* in the driver rather than a wrong value, so
#: this table does not have to be exhaustive to be safe.
TITLE_OVERRIDES = {
    "growShrink": ("Grow/Shrink", ("Grow Shrink",)),
    "growTurn": ("Grow & Turn", ("Grow Turn",)),
    "shrinkTurn": ("Shrink & Turn", ("Shrink Turn",)),
    "custom": ("Custom Path", ()),
}

#: Why a GUI-addressable entry is not driver-runnable. Prefix match, longest first.
DEFERRALS: tuple[tuple[str, str], ...] = (
    (
        "animation.gallery.motionPath.custom",
        "a custom motion path is drawn on the canvas; no titled control applies one",
    ),
    (
        "animation.gallery.media.",
        "the Media gallery is present only while a media object is selected, and the capture "
        "deck carries a shape; capturing these needs a deck with audio or video on the slide",
    ),
    (
        "animation.effectOptions.direction.",
        "the Effect Options direction labels depend on which effect is currently applied "
        "(Fly In offers From Bottom, Wheel offers 1 Spoke), and no catalog metadata binds a "
        "direction entry to an effect, so the path cannot be derived from the entry alone",
    ),
    (
        "animation.afterAnimation.",
        "After animation is a dropdown in the Animation Pane's effect dialog, which needs a "
        "prerequisite effect and a dialog tab the entry's metadata does not name",
    ),
    (
        "animation.timing.",
        "a timing option lives in the effect dialog behind a prerequisite effect, which the "
        "entry's metadata does not name",
    ),
    (
        "animation.sound.",
        "the Sound dropdown lives in the effect dialog behind a prerequisite effect, and the "
        "capture must also record the media part and relationship, not just the XML",
    ),
    (
        "animation.start.",
        "the Start popup needs a prerequisite effect before it has any value to set",
    ),
)

SET_ASIDE_REASON = (
    "a scripting enumerator is applied by code and the GUI applies by label, so closing this "
    "through the GUI would state a name correspondence rather than measure a value"
)


# --- reading the checked-in artefacts ---------------------------------------
def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_manifest_linkage(catalog: dict[str, Any], manifest: dict[str, Any]) -> str:
    """Fail unless the catalog pins the manifest it is being read beside.

    The catalog's ``baseline.guiManifest`` carries ``<file>@<manifestVersion>``. Emitting
    a plan from a mismatched pair would describe a GUI surface that is not the one the
    gaps were computed against.
    """
    pinned = str(catalog.get("baseline", {}).get("guiManifest", ""))
    version = str(manifest.get("manifestVersion", ""))
    if not pinned.endswith(f"@{version}"):
        raise ValueError(f"catalog pins guiManifest {pinned!r}, manifest is version {version!r}")
    return version


def requires_capture(entry: dict[str, Any]) -> bool:
    return bool((entry.get("ooxml") or {}).get("requiresCapture"))


def ooxml_gap(entry: dict[str, Any]) -> str | None:
    gap = (entry.get("ooxml") or {}).get("gap")
    return str(gap) if gap else None


def is_gui_addressable(key: str) -> bool:
    return key.startswith(GUI_NAMESPACES)


# --- deriving one target ----------------------------------------------------
def gui_title(value: str) -> tuple[str, tuple[str, ...], str]:
    """Return ``(title, alternatives, source)`` for a catalog key's last segment.

    Mechanical where it can be — ``flyIn`` -> ``Fly In``, ``complementaryColor2`` ->
    ``Complementary Color 2`` — and from :data:`TITLE_OVERRIDES` where PowerPoint spells
    the label differently. The derivation is never trusted blind: the driver matches the
    live title exactly and records a failure naming what it looked for, so a wrong label
    costs one record instead of producing a mislabelled capture.
    """
    if value in TITLE_OVERRIDES:
        title, alternatives = TITLE_OVERRIDES[value]
        return title, alternatives, "labelTable"
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)", " ", value)
    title = " ".join(word[:1].upper() + word[1:] for word in spaced.split())
    return title, (), "catalogKey"


def deferral_reason(key: str) -> str | None:
    """Return why this GUI-addressable key is not driver-runnable, or None."""
    for prefix, reason in DEFERRALS:
        if key == prefix or key.startswith(prefix):
            return reason
    return None


def gui_path(key: str) -> list[str] | None:
    """Return the ribbon path a gallery key implies, or None when it implies none."""
    parts = key.split(".")
    if len(parts) != 4 or parts[:2] != ["animation", "gallery"]:
        return None
    category, value = parts[2], parts[3]
    title, _alternatives, _source = gui_title(value)
    if category in GALLERY_CONTROL:
        return [ANIMATIONS_TAB, GALLERY_CONTROL[category], title]
    if category == "motionPath":
        return [ANIMATIONS_TAB, PATH_ANIMATION_CONTROL, title]
    return None


def derive_entry(key: str, entry: dict[str, Any], item: dict[str, Any] | None) -> dict[str, Any]:
    """Classify one capture-required GUI entry into a target or a deferral."""
    common = {
        "key": key,
        "control": (item or {}).get("control"),
        "surface": (item or {}).get("surface"),
        "gap": ooxml_gap(entry),
    }
    reason = deferral_reason(key)
    if reason is not None:
        return {**common, "bucket": "deferred", "reason": reason}
    path = gui_path(key)
    if path is None:
        return {
            **common,
            "bucket": "deferred",
            "reason": "no ribbon path follows from this key's own metadata",
        }
    title, alternatives, source = gui_title(key.split(".")[-1])
    return {
        **common,
        "bucket": "target",
        "guiPath": path,
        "title": title,
        "titleAlternatives": list(alternatives),
        "titleSource": source,
    }


# --- the shape grid ---------------------------------------------------------
@dataclass(frozen=True)
class Rect:
    """A rectangle in deck px, with the top-left origin the deck JSON uses."""

    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)

    def overlaps(self, other: Rect) -> bool:
        return (
            self.x < other.x + other.width
            and other.x < self.x + self.width
            and self.y < other.y + other.height
            and other.y < self.y + self.height
        )

    def distance_to(self, point: tuple[float, float]) -> float:
        """Shortest distance from ``point`` to this rectangle; 0 when it is inside."""
        dx = max(self.x - point[0], 0.0, point[0] - (self.x + self.width))
        dy = max(self.y - point[1], 0.0, point[1] - (self.y + self.height))
        return math.hypot(dx, dy)

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class Cell:
    """One target's place on the deck: the shape to click and the label under it."""

    slide_index: int
    cell_index: int
    shape: Rect
    label: Rect


@dataclass(frozen=True)
class Grid:
    """The whole layout, derived from the target count and checked before it is used."""

    count: int
    columns: int
    rows: int
    slides: int
    per_slide: int
    cell: tuple[float, float]
    shape: tuple[float, float]
    cells: tuple[Cell, ...]

    @property
    def split(self) -> bool:
        return self.slides > 1

    def as_dict(self) -> dict[str, Any]:
        note = (
            f"{self.count} targets fit one slide as a {self.columns}x{self.rows} grid"
            if not self.split
            else (
                f"{self.count} targets do not fit one slide with a {CLICK_MARGIN_PX:g}px click "
                f"margin and {NEIGHBOUR_CLEARANCE_PX:g}px neighbour clearance, so they are split "
                f"across {self.slides} slides of at most {self.per_slide} as a "
                f"{self.columns}x{self.rows} grid"
            )
        )
        return {
            "slides": self.slides,
            "targetsPerSlide": self.per_slide,
            "columns": self.columns,
            "rows": self.rows,
            "basisPx": list(DECK_BASIS_PX),
            "cellPx": list(self.cell),
            "shapePx": list(self.shape),
            "clickMarginPx": CLICK_MARGIN_PX,
            "neighbourClearancePx": NEIGHBOUR_CLEARANCE_PX,
            "split": self.split,
            "note": note,
        }


def _usable(basis: tuple[float, float]) -> tuple[float, float]:
    return (basis[0] - 2 * SLIDE_MARGIN_PX, basis[1] - 2 * SLIDE_MARGIN_PX)


def _candidate_grids(per_slide: int, basis: tuple[float, float]) -> list[tuple[float, int, int]]:
    """Return every column count that fits ``per_slide`` cells, best aspect ratio first.

    A candidate only counts when the shape it implies is at least twice
    :data:`CLICK_MARGIN_PX` on both sides, which is the whole point of deriving the grid:
    a cell too small to be clicked in the middle is not a layout, it is a trap.
    """
    usable_w, usable_h = _usable(basis)
    candidates: list[tuple[float, int, int]] = []
    for columns in range(1, per_slide + 1):
        rows = math.ceil(per_slide / columns)
        cell_w, cell_h = usable_w / columns, usable_h / rows
        shape_w = cell_w - CELL_GAP_X_PX
        shape_h = cell_h - CELL_GAP_Y_PX - LABEL_HEIGHT_PX
        if shape_w < 2 * CLICK_MARGIN_PX or shape_h < 2 * CLICK_MARGIN_PX:
            continue
        candidates.append((abs(cell_w / cell_h - CELL_ASPECT), columns, rows))
    return sorted(candidates)


def max_targets_per_slide(*, basis: tuple[float, float] = DECK_BASIS_PX) -> int:
    """How many clickable shapes one slide can carry under the separation constraints.

    A cell has to be at least ``2 * CLICK_MARGIN_PX`` wide once its horizontal gap is
    removed, and that much tall once its vertical gap and its label are, so the capacity
    is just how many such cells fit the usable area. Stated here rather than found by
    search so "as few slides as possible" is arithmetic a reader can check.
    """
    usable_w, usable_h = _usable(basis)
    columns = int(usable_w // (2 * CLICK_MARGIN_PX + CELL_GAP_X_PX))
    rows = int(usable_h // (2 * CLICK_MARGIN_PX + CELL_GAP_Y_PX + LABEL_HEIGHT_PX))
    return columns * rows


def grid_layout(count: int, *, basis: tuple[float, float] = DECK_BASIS_PX) -> Grid:
    """Lay ``count`` clickable shapes out over as few slides as the constraints allow.

    One slide is preferred and is what the catalog's current 76 targets get. The returned
    grid is **checked, not asserted by eye**: no two shapes on a slide overlap, every
    shape's centre is :data:`CLICK_MARGIN_PX` inside its own edges, every centre clears
    every other shape by :data:`NEIGHBOUR_CLEARANCE_PX`, and nothing leaves the slide. A
    violation raises, because a grid that silently puts two click points within a few
    points of each other would apply the right effect to the wrong target.
    """
    if count < 1:
        raise ValueError(f"a grid needs at least one target, got {count}")
    # The closed form above says where to start; the loop is the guarantee, so a wrong
    # capacity would cost a slide rather than produce an unclickable grid.
    per_slide = min(count, max_targets_per_slide(basis=basis))
    while per_slide > 1 and not _candidate_grids(per_slide, basis):
        per_slide -= 1
    if not _candidate_grids(per_slide, basis):
        raise ValueError(
            f"not even one shape fits a {basis[0]:g}x{basis[1]:g} px slide with a "
            f"{CLICK_MARGIN_PX:g}px click margin; the constraints are unsatisfiable"
        )
    slides = math.ceil(count / per_slide)
    per_slide = math.ceil(count / slides)
    _aspect, columns, rows = _candidate_grids(per_slide, basis)[0]

    usable_w, usable_h = _usable(basis)
    cell_w, cell_h = usable_w / columns, usable_h / rows
    shape_w = round(cell_w - CELL_GAP_X_PX)
    shape_h = round(cell_h - CELL_GAP_Y_PX - LABEL_HEIGHT_PX)

    cells: list[Cell] = []
    for ordinal in range(count):
        slide_index, position = divmod(ordinal, per_slide)
        row, column = divmod(position, columns)
        cell_x = SLIDE_MARGIN_PX + column * cell_w
        cell_y = SLIDE_MARGIN_PX + row * cell_h
        shape = Rect(
            round(cell_x + CELL_GAP_X_PX / 2),
            round(cell_y + CELL_GAP_Y_PX / 2),
            shape_w,
            shape_h,
        )
        label = Rect(shape.x, shape.y + shape.height, shape_w, round(LABEL_HEIGHT_PX))
        cells.append(Cell(slide_index + 1, position + 1, shape, label))

    grid = Grid(count, columns, rows, slides, per_slide, (cell_w, cell_h), (shape_w, shape_h), tuple(cells))
    _check_grid(grid, basis)
    return grid


def _check_grid(grid: Grid, basis: tuple[float, float]) -> None:
    """Refuse a grid that a click could not address unambiguously."""
    slide = Rect(0, 0, basis[0], basis[1])
    for cell in grid.cells:
        centre = cell.shape.center
        inset = min(
            centre[0] - cell.shape.x,
            cell.shape.x + cell.shape.width - centre[0],
            centre[1] - cell.shape.y,
            cell.shape.y + cell.shape.height - centre[1],
        )
        if inset < CLICK_MARGIN_PX:
            raise ValueError(
                f"shape {cell.cell_index} on slide {cell.slide_index} puts its centre {inset:g}px "
                f"from its own edge, under the {CLICK_MARGIN_PX:g}px click margin"
            )
        for rect in (cell.shape, cell.label):
            if rect.x < 0 or rect.y < 0 or rect.x + rect.width > slide.width or rect.y + rect.height > slide.height:
                raise ValueError(
                    f"shape {cell.cell_index} on slide {cell.slide_index} leaves the "
                    f"{basis[0]:g}x{basis[1]:g} px slide: {rect.as_dict()}"
                )
    by_slide: dict[int, list[Cell]] = {}
    for cell in grid.cells:
        by_slide.setdefault(cell.slide_index, []).append(cell)
    for slide_index, cells in by_slide.items():
        for first in range(len(cells)):
            for second in range(first + 1, len(cells)):
                one, other = cells[first], cells[second]
                if one.shape.overlaps(other.shape):
                    raise ValueError(
                        f"shapes {one.cell_index} and {other.cell_index} overlap on slide {slide_index}"
                    )
                for a, b in ((one, other), (other, one)):
                    clearance = b.shape.distance_to(a.shape.center)
                    if clearance < NEIGHBOUR_CLEARANCE_PX:
                        raise ValueError(
                            f"the click point of shape {a.cell_index} on slide {slide_index} is "
                            f"{clearance:g}px from shape {b.cell_index}, under the "
                            f"{NEIGHBOUR_CLEARANCE_PX:g}px neighbour clearance"
                        )


# --- the plan ---------------------------------------------------------------
def assign_cells(targets: Sequence[dict[str, Any]]) -> Grid:
    """Lay the targets out and write each one's slide, cell and shape rectangle into it.

    ``shapeName`` is left null here on purpose: it is settled by ``--generate``, which
    reads the name back out of the package sdpm wrote, because sdpm derives a shape's name
    from its geometry rather than from the element id the deck JSON asked for.
    """
    grid = grid_layout(len(targets))
    for ordinal, (target, cell) in enumerate(zip(targets, grid.cells), start=1):
        target["targetIndex"] = ordinal
        target["slideIndex"] = cell.slide_index
        target["cellIndex"] = cell.cell_index
        target["shapeRectPx"] = cell.shape.as_dict()
        target["shapeName"] = target.get("shapeName")
    return grid


def build_plan(catalog: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Derive the whole plan from the catalog's remaining gaps."""
    manifest_version = assert_manifest_linkage(catalog, manifest)
    items = {item["key"]: item for item in manifest.get("items", [])}

    targets: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    set_aside: list[dict[str, Any]] = []
    unflagged: list[dict[str, Any]] = []

    for entry in sorted(catalog.get("guiItems", []), key=lambda e: e["key"]):
        key = entry["key"]
        if not is_gui_addressable(key):
            continue
        if requires_capture(entry):
            derived = derive_entry(key, entry, items.get(key))
            (targets if derived.pop("bucket") == "target" else deferred).append(derived)
        elif ooxml_gap(entry) and entry.get("verification") == "powerPointReadBackRequired":
            unflagged.append(
                {
                    "key": key,
                    "control": items.get(key, {}).get("control"),
                    "gap": ooxml_gap(entry),
                    "verification": entry.get("verification"),
                    "note": "carries a gap but not requiresCapture, so the selection rule excludes it",
                }
            )

    for entry in sorted(catalog.get("candidates", []), key=lambda e: e["key"]):
        if not requires_capture(entry):
            continue
        set_aside.append(
            {
                "key": entry["key"],
                "enum": entry.get("enum"),
                "enumerator": entry.get("enumerator"),
                "code": entry.get("code"),
                "guiKey": entry.get("guiKey"),
                "gap": ooxml_gap(entry),
                "reason": SET_ASIDE_REASON,
            }
        )

    grid = assign_cells(targets) if targets else None

    return {
        "plan": "sdpm animation GUI capture",
        "driver": DRIVER,
        # Target key -> shape name, filled in by --generate alongside each target's own
        # ``shapeName``. The driver refuses to run a target without one.
        "shapeNames": {},
        "deck": grid.as_dict() if grid is not None else {"slides": 0, "note": "no targets"},
        "generatedFrom": {
            "catalog": DEFAULT_CATALOG.relative_to(REPO_ROOT).as_posix(),
            "manifest": DEFAULT_MANIFEST.relative_to(REPO_ROOT).as_posix(),
            "manifestVersion": manifest_version,
            "applicationVersion": catalog.get("baseline", {}).get("version"),
            "selection": (
                "guiItems with ooxml.requiresCapture true whose key is in "
                + ", ".join(f"{prefix}*" for prefix in GUI_NAMESPACES)
            ),
        },
        "counts": {
            "targets": len(targets),
            "deferredTargets": len(deferred),
            "setAsideScriptingEnumerators": len(set_aside),
            "gapsWithoutCaptureFlag": len(unflagged),
        },
        "targets": targets,
        "deferredTargets": deferred,
        "setAsideScriptingEnumerators": set_aside,
        "gapsWithoutCaptureFlag": unflagged,
    }


# --- the capture deck -------------------------------------------------------
def label_text(key: str) -> str:
    """Return the label under a shape: the key's last segment, on one line.

    Deliberately **not** the whole key. The label orients a human looking at the deck;
    the authoritative key is in the plan and the attribution is by ``spid``, so a label
    that costs the shape half its height is a bad trade — height was the axis that made
    clicks miss. The segment is unique within a category, and the ordinal inside the
    shape ties a label back to its plan entry when two categories share a name.
    """
    return key.rpartition(".")[2] or key


def slide_elements(targets: Sequence[dict[str, Any]], grid: Grid, slide_index: int) -> list[dict[str, Any]]:
    """Return one slide's elements: per target, a shape to click and its key beneath it.

    The shape's name — read back out of the package, not asked for here — is what the
    driver looks up to compute its click point and its ``spid``. The visible key is what
    lets a human read the deck and check a saved slide against the target it was for
    rather than against a position in a list.
    """
    cells = {cell.cell_index: cell for cell in grid.cells if cell.slide_index == slide_index}
    elements: list[dict[str, Any]] = []
    for target in targets:
        if target["slideIndex"] != slide_index:
            continue
        cell = cells[target["cellIndex"]]
        ordinal = target["targetIndex"]
        elements.append(
            {
                "id": f"{SHAPE_ELEMENT_PREFIX}{ordinal:03d}",
                "type": "shape",
                "shape": "rounded_rectangle",
                "text": f"{ordinal:03d}",
                "x": cell.shape.x,
                "y": cell.shape.y,
                "width": cell.shape.width,
                "height": cell.shape.height,
                "fontSize": SHAPE_FONT_PT,
            }
        )
        elements.append(
            {
                "id": f"{LABEL_ELEMENT_PREFIX}{ordinal:03d}",
                "type": "textbox",
                "text": label_text(target["key"]),
                "x": cell.label.x,
                "y": cell.label.y,
                "width": cell.label.width,
                "height": cell.label.height,
                "fontSize": LABEL_FONT_PT,
            }
        )
    return elements


def build_capture_deck(plan: dict[str, Any], deck_dir: Path, *, template: Path = DEFAULT_TEMPLATE) -> Path:
    """Write the sdpm deck source for a plan: one slide of shapes, in plan order."""
    targets = plan.get("targets", [])
    if not targets:
        raise ValueError("the plan has no targets, so there is no deck to build")
    grid = grid_layout(len(targets))
    (deck_dir / "slides").mkdir(parents=True, exist_ok=True)
    (deck_dir / "specs").mkdir(parents=True, exist_ok=True)
    (deck_dir / "deck.json").write_text(
        json.dumps(
            {
                "template": "template.pptx",
                "fonts": {"fullwidth": "Meiryo", "halfwidth": "Arial"},
                "defaultTextColor": "#FFFFFF",
                # The effects under test are the ones PowerPoint will add, so sdpm must
                # contribute none of its own. ``generate_capture_deck`` passes the same
                # thing again as a caller override, so neither alone can switch it on.
                "animations": {"enabled": False},
                "transitions": {"enabled": False},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (deck_dir / "template.pptx").write_bytes(template.read_bytes())

    outline = []
    for slide_index in range(1, grid.slides + 1):
        slug = f"s{slide_index:03d}"
        on_slide = [target for target in targets if target["slideIndex"] == slide_index]
        outline.append(f"- [{slug}] slide {slide_index}: {len(on_slide)} capture targets")
        (deck_dir / "slides" / f"{slug}.json").write_text(
            json.dumps(
                {"layout": "Blank", "elements": slide_elements(targets, grid, slide_index)},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    (deck_dir / "specs" / "outline.md").write_text("\n".join(outline) + "\n", encoding="utf-8")
    return deck_dir


def generate_capture_deck(deck_dir: Path, output: Path) -> dict[str, Any]:
    """Build the deck through sdpm with both motion switches off.

    ``animation_mode`` and ``transition_mode`` are independent of each other and override
    the deck switches, so both are passed explicitly as well as being off in
    ``deck.json``: sdpm must contribute no motion of its own, or a ``p:timing`` tree in
    the saved package would not be evidence about a captured value.
    """
    from sdpm.api import generate

    return generate(deck_dir, output, animation_mode="off", transition_mode="off")


def _emu_to_points(value: int | str) -> float:
    return int(value) / EMU_PER_POINT


def read_package_shapes(package: Path, *, preset: str = SHAPE_PRESET) -> dict[int, list[dict[str, Any]]]:
    """Return, per 1-based slide, every ``preset`` shape the package carries.

    Each entry is the shape's own ``p:cNvPr`` name and id plus its centre in points. This
    is the read-back the whole design rests on: sdpm names a shape from its geometry, so
    the name in the file is the only name the driver can click, and the ``id`` is the
    ``spid`` PowerPoint will write into ``p:spTgt`` when it animates that shape.
    """
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    slide_part = re.compile(r"ppt/slides/slide(\d+)\.xml")
    found: dict[int, list[dict[str, Any]]] = {}
    with zipfile.ZipFile(package) as archive:
        parts = sorted(
            (int(match.group(1)), match.group(0))
            for match in map(slide_part.fullmatch, archive.namelist())
            if match
        )
        if not parts:
            raise ValueError(f"{package} has no slide parts")
        for index, part in parts:
            root = etree.fromstring(archive.read(part), parser=parser)
            shapes: list[dict[str, Any]] = []
            for shape in root.iter():
                if etree.QName(shape).localname != "sp":
                    continue
                if not any(
                    etree.QName(el).localname == "prstGeom" and el.get("prst") == preset
                    for el in shape.iter()
                ):
                    continue
                props = next(
                    (el for el in shape.iter() if etree.QName(el).localname == "cNvPr" and el.get("name")),
                    None,
                )
                off = next((el for el in shape.iter() if etree.QName(el).localname == "off"), None)
                ext = next((el for el in shape.iter() if etree.QName(el).localname == "ext"), None)
                if props is None or off is None or ext is None:
                    continue
                x, y = _emu_to_points(off.get("x")), _emu_to_points(off.get("y"))
                cx, cy = _emu_to_points(ext.get("cx")), _emu_to_points(ext.get("cy"))
                shapes.append(
                    {
                        "name": props.get("name"),
                        "id": props.get("id"),
                        "centerPt": (x + cx / 2.0, y + cy / 2.0),
                    }
                )
            found[index] = shapes
    return found


def read_slide_size_pt(package: Path) -> tuple[float, float]:
    """Return the deck's slide size in points, from ``ppt/presentation.xml``."""
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    with zipfile.ZipFile(package) as archive:
        root = etree.fromstring(archive.read("ppt/presentation.xml"), parser=parser)
    size = next((el for el in root.iter() if etree.QName(el).localname == "sldSz"), None)
    if size is None:
        raise ValueError(f"{package.name} has no p:sldSz in ppt/presentation.xml")
    return _emu_to_points(size.get("cx")), _emu_to_points(size.get("cy"))


def resolve_shape_names(package: Path, plan: dict[str, Any], *, preset: str = SHAPE_PRESET) -> dict[str, str]:
    """Read every target's shape name out of the package, matched by its own position.

    Each target is matched to the ``preset`` shape whose centre is within
    :data:`MATCH_TOLERANCE_PT` of the centre the grid asked for, converted from the deck's
    px basis using the slide size the package itself declares. Requiring exactly one
    match, and a name used by exactly one target, is what makes a click attributable: two
    candidates would mean the driver could compute a point for one shape and record the
    other target's key.
    """
    targets = plan.get("targets", [])
    if not targets:
        raise ValueError("the plan has no targets, so there are no shape names to resolve")
    slide_w_pt, _slide_h_pt = read_slide_size_pt(package)
    scale = slide_w_pt / DECK_BASIS_PX[0]
    shapes = read_package_shapes(package, preset=preset)

    names: dict[str, str] = {}
    for target in targets:
        slide_index = target["slideIndex"]
        rect = target["shapeRectPx"]
        wanted = (
            (rect["x"] + rect["width"] / 2.0) * scale,
            (rect["y"] + rect["height"] / 2.0) * scale,
        )
        on_slide = shapes.get(slide_index, [])
        matches = [
            shape
            for shape in on_slide
            if math.dist(shape["centerPt"], wanted) <= MATCH_TOLERANCE_PT
        ]
        if len(matches) != 1:
            raise ValueError(
                f"{target['key']} expects exactly one {preset} shape centred near "
                f"({wanted[0]:.1f}, {wanted[1]:.1f}) pt on slide {slide_index}; the package has "
                f"{len(matches)} within {MATCH_TOLERANCE_PT:g} pt of it, out of {len(on_slide)} on "
                f"that slide"
            )
        names[target["key"]] = matches[0]["name"]

    duplicates = sorted({name for name in names.values() if list(names.values()).count(name) > 1})
    if duplicates:
        raise ValueError(f"the package names more than one target's shape the same: {duplicates}")
    expected = sum(len(shapes.get(index, [])) for index in {target["slideIndex"] for target in targets})
    if expected != len(targets):
        raise ValueError(
            f"the package carries {expected} {preset} shapes on the target slides but the plan has "
            f"{len(targets)} targets; an unmatched shape could be clicked instead of a target"
        )
    return names


def apply_shape_names(plan: dict[str, Any], names: dict[str, str]) -> None:
    """Write the resolved names into the plan, on each target and as the mapping."""
    plan["shapeNames"] = {key: names[key] for key in sorted(names)}
    for target in plan.get("targets", []):
        target["shapeName"] = names[target["key"]]


# --- CLI --------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gui_capture_plan.py",
        description=(
            "Derive the GUI capture plan from the animation catalog's remaining gaps and, "
            "optionally, build the capture deck it implies. Touches no application."
        ),
    )
    parser.add_argument("--emit-plan", action="store_true", help="write or print the derived plan")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out", type=Path, help="write the plan here instead of stdout")
    parser.add_argument("--build-deck", type=Path, metavar="DIR", help="write the sdpm deck source here")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--generate", type=Path, metavar="PPTX", help="build the deck through sdpm.api.generate")
    parser.add_argument("--summary", action="store_true", help="print only the counts")
    return parser


def _distinct_warnings(warnings: Iterable[str]) -> list[str]:
    return sorted({re.sub(r"^page\d+ ", "", text) for text in warnings})


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not any((args.emit_plan, args.build_deck, args.generate, args.summary)):
        build_parser().error("pass --emit-plan, --summary, --build-deck or --generate")

    try:
        plan = build_plan(load_json(args.catalog), load_json(args.manifest))
    except (OSError, ValueError, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    report: dict[str, Any] = {"counts": plan["counts"], "deck": plan["deck"]}
    if args.build_deck:
        build_capture_deck(plan, args.build_deck, template=args.template)
        report["deckSource"] = str(args.build_deck)
    if args.generate:
        if not args.build_deck:
            print("FAIL: --generate needs --build-deck", file=sys.stderr)
            return 1
        result = generate_capture_deck(args.build_deck, args.generate)
        # Read the shape names back out of the package before the plan is written, so the
        # plan the driver reads names the shapes the file actually carries.
        apply_shape_names(plan, resolve_shape_names(Path(result["output_path"]), plan))
        report["package"] = result["output_path"]
        report["slideCount"] = result["slide_count"]
        report["shapeNames"] = len(plan["shapeNames"])
        report["firstShapeName"] = plan["targets"][0]["shapeName"] if plan["targets"] else None
        warnings = result.get("warnings") or []
        if warnings:
            # A capture deck is deliberately dense — 76 small shapes with a small key
            # under each — so the layout warnings repeat per cell. Reported as a count
            # plus the distinct kinds, which is the part worth reading.
            report["warningCount"] = len(warnings)
            report["distinctWarnings"] = _distinct_warnings(warnings)
    # Written last: --generate is what settles the shape names.
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        report["plan"] = str(args.out)

    if args.emit_plan and not args.out and not args.summary:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
