# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The GUI capture driver and its plan, verified without PowerPoint and without pyobjc.

The driver's job is to replace a four-call-per-value agent round trip with one script, so
what matters is that everything *except* the accessibility API is settled offline: the
plan is derived from the catalog's own gaps rather than typed out, the grid of clickable
shapes is checked rather than eyeballed, the click point is computed from the package and
the live frames rather than hardcoded, every press is attributed to the shape it was
aimed at, a failed target is recorded and the run continues, a resumed run neither
repeats nor loses work, and the record shape is the one ``generate.py --parse-oracle``
already consumes.

The accessibility layer is injected, so every test here runs against a fake PowerPoint
that re-renders its tree on each read — which is also how the "re-resolve by title before
every press" rule gets exercised rather than assumed. The fake is hostile on purpose in
five ways that each cost the driver a live run if it got them wrong:

- it has **no slide navigator at all**, so a reintroduced ``select_slide`` could not work
  against it;
- it has **no clickable canvas and no frames**, so a reintroduced coordinate click would
  have nothing to aim at — which is the point: the click version's last live run
  captured 2 of 12 attempted targets;
- its **Selection Pane rows are built from the package's own shape names**, in reverse
  z-order, one row per shape *and* one per label, and a gallery press applies its effect
  to **whichever row is selected** — so a driver that selected the wrong row, or none,
  would move the effect onto another shape rather than being quietly forgiven;
- only the controls of the **active ribbon tab** are in its tree, so opening the
  Selection Pane from Home really does take the ribbon off Animations;
- its Save **writes a real ``p:timing`` tree into the package** and renumbers every
  timing ``id`` while doing it, because nothing offline can promise PowerPoint does not.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import re
import zipfile
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Any, Callable

import pytest
from lxml import etree

from scripts.animation_catalog import gui_capture as driver
from scripts.animation_catalog import gui_capture_plan as planner
from scripts.animation_catalog.generate import (
    ORACLE_RUN_TOKEN,
    analyse_oracle_output,
    merge_oracle_readback,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER_SOURCE = REPO_ROOT / "scripts" / "animation_catalog" / "gui_capture.py"

#: The slide size the generated capture deck carries, in points. The driver no longer
#: reads it — nothing maps a shape to a screen point any more — so this is a pin on the
#: planner's reader and on the deck, not on the driver.
MEASURED_SLIDE_PT = (960.0, 540.0)

#: The names the live Selection Pane's first three rows carried on 2026-11-01, in pane
#: order. Reverse z-order, and a label's row sits between two shapes' rows — so a target
#: shape's row index is NOT its target number, and the index has to come from the
#: package's own shape order rather than from counting targets.
MEASURED_PANE_HEAD = ("TextBox 152", "Rounded Rectangle 151", "TextBox 150")

#: The target count the checked-in catalog derives today, and the grid it fits on one
#: slide. Both are asserted against the plan rather than trusted.
#: What the planner derives when every gallery gap is reopened. It is 92 rather
#: than the 76 captured on 2026-11-01 because 23 more tiles now carry measured
#: behaviours — 16 lifted from their own default effect option, and the 7 Complex
#: motion paths captured on 2026-11-02. Superseded comment line follows.
#: behaviours: they were outside that plan, and the effect-option capture
#: reached them through their own default option, whose behaviours are the
#: tile's. The live plan derives **0** — every gallery gap is closed.
EXPECTED_TARGETS = 99
#: 10 columns by 8 rows, not the 8x10 first chosen. A click's accuracy is bounded by the
#: shape's SHORT side, which was 22 pt at a 2.2 cell aspect with a two-line label. A live
#: run then put 71 presses onto five shapes, because a click that lands on empty canvas
#: leaves the previous shape selected and the next press overwrites ITS effect. Squarer
#: cells and a one-line label take the short side to 43.5 pt.
#: Two slides, because one cannot hold 99 shapes that are both clickable and
#: wide enough for the longest key on one line. The second slide is the
#: constraints being honoured, not a layout failure.
EXPECTED_SLIDES = 2
EXPECTED_GRID = (8, 7)
EXPECTED_SHAPE_PX = (200, 105)


# --- a package the fake can apply effects to --------------------------------
#: A preset per gallery tile, so two targets' effects are told apart by their own
#: ``p:cTn`` attributes rather than only by which shape they sit on.
TILE_PRESETS = {
    "Fly In": ("2", "entr"),
    "Fade": ("10", "entr"),
    "Grow & Turn": ("31", "entr"),
    "Grow Turn": ("31", "entr"),
    "Lines": ("0", "path"),
    "Arcs": ("1", "path"),
    "Turns": ("2", "path"),
}
DEFAULT_PRESET = ("1", "entr")

_TIMING_FRAME = (
    "<p:timing><p:tnLst><p:par>"
    '<p:cTn id="{root}" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
    '<p:seq concurrent="1" nextAc="seek"><p:cTn id="{seq}" dur="indefinite" nodeType="mainSeq">'
    "<p:childTnLst>{effects}</p:childTnLst>"
    "</p:cTn></p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>"
)
_EFFECT_FRAME = (
    '<p:par><p:cTn id="{click}" fill="hold">'
    '<p:stCondLst><p:cond delay="indefinite"/></p:stCondLst><p:childTnLst>'
    '<p:par><p:cTn id="{inner}" fill="hold">'
    '<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
    '<p:par><p:cTn id="{effect}" presetID="{preset_id}" presetClass="{preset_class}" '
    'presetSubtype="0" fill="hold" nodeType="clickEffect"><p:childTnLst>'
    '<p:set><p:cBhvr><p:cTn id="{behaviour}" dur="500" fill="hold"/>'
    '<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'
    "<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>"
    '<p:to><p:strVal val="visible"/></p:to></p:set>'
    "</p:childTnLst></p:cTn></p:par>"
    "</p:childTnLst></p:cTn></p:par>"
    "</p:childTnLst></p:cTn></p:par>"
)


def timing_xml(effects: dict[str, tuple[str, str]]) -> str:
    """Render a ``p:timing`` tree carrying one click effect per animated shape.

    The ids restart from a base that depends on how many effects there are, so **every**
    effect's ``p:cTn/@id`` changes on every save. The driver must therefore compare reads
    by ``p:spTgt/@spid`` alone; an identity built from ids would see every earlier effect
    as new and reject every target after the first.
    """
    if not effects:
        return ""
    ids = count(len(effects) * 10 + 1)
    root, seq = next(ids), next(ids)
    rendered = []
    for spid, (preset_id, preset_class) in sorted(effects.items(), key=lambda item: int(item[0])):
        rendered.append(
            _EFFECT_FRAME.format(
                click=next(ids),
                inner=next(ids),
                effect=next(ids),
                behaviour=next(ids),
                preset_id=preset_id,
                preset_class=preset_class,
                spid=spid,
            )
        )
    return _TIMING_FRAME.format(root=root, seq=seq, effects="".join(rendered))


def write_effects(package: Path, slide_index: int, effects: dict[str, tuple[str, str]]) -> None:
    """Replace one slide's ``p:timing`` with the effects given, rewriting the package."""
    part = f"ppt/slides/slide{slide_index}.xml"
    with zipfile.ZipFile(package) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    replaced = False
    for index, (info, blob) in enumerate(entries):
        if info.filename != part:
            continue
        text = re.sub(r"<p:timing>.*?</p:timing>", "", blob.decode("utf-8"), flags=re.S)
        entries[index] = (info, text.replace("</p:sld>", timing_xml(effects) + "</p:sld>").encode("utf-8"))
        replaced = True
    if not replaced:
        raise AssertionError(f"{package} has no {part} to write effects into")
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as out:
        for info, blob in entries:
            out.writestr(info, blob)


#: A shape with a name, an id and nothing else worth reading. Used to inflate a slide to
#: the size the live one had, so the pane's row count and the package's shape count stay
#: equal — which they must, because that equality is what makes a row index trustworthy.
FILLER_SHAPE = (
    '<p:sp><p:nvSpPr><p:cNvPr id="{spid}" name="{name}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
    '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="914400" cy="914400"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
    "<p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>"
)


def add_filler_shapes(package: Path, slide_index: int, count: int) -> list[str]:
    """Append ``count`` named shapes to a slide, and return their names in z-order.

    The pane used to be inflated on the fake's side alone, by publishing rows for shapes
    the package did not contain. That cannot be done any more, and the reason is the
    point: :func:`gui_capture.select_shape` refuses when the pane's row count and the
    slide's shape count disagree, so a pane inflated past its package is exactly the
    thing the driver now rejects. Inflating the **slide** keeps the fake representative.
    """
    part = f"ppt/slides/slide{slide_index}.xml"
    with zipfile.ZipFile(package) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    names = [f"Filler {index}" for index in range(count)]
    added = "".join(
        FILLER_SHAPE.format(spid=9_000 + index, name=name) for index, name in enumerate(names)
    )
    replaced = False
    for index, (info, blob) in enumerate(entries):
        if info.filename != part:
            continue
        text = blob.decode("utf-8")
        if "</p:spTree>" not in text:
            raise AssertionError(f"{part} has no p:spTree to append to")
        entries[index] = (info, text.replace("</p:spTree>", added + "</p:spTree>").encode("utf-8"))
        replaced = True
    if not replaced:
        raise AssertionError(f"{package} has no {part} to add shapes to")
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as out:
        for info, blob in entries:
            out.writestr(info, blob)
    return names


def shape_names_in_z_order(package: Path, slide_index: int) -> list[tuple[str, str]]:
    """Return ``(name, spid)`` for every shape on a slide, in document order.

    Document order is z-order, back to front, which is the order the Selection Pane
    reverses. Read here with its own XML pass rather than through the driver, so the
    fake's row names are not the driver's own idea of what the slide holds — and it keeps
    the **labels** as well as the target shapes, because the live pane carries a row for
    each (153 rows for 76 targets).
    """
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    with zipfile.ZipFile(package) as archive:
        root = etree.fromstring(archive.read(f"ppt/slides/slide{slide_index}.xml"), parser=parser)
    found: list[tuple[str, str]] = []
    for shape in root.iter():
        if etree.QName(shape).localname != "sp":
            continue
        props = next((el for el in shape.iter() if etree.QName(el).localname == "cNvPr"), None)
        if props is None or not props.get("name"):
            continue
        found.append((props.get("name"), props.get("id")))
    return found


# --- the fake accessibility host --------------------------------------------
@dataclass
class ReadCounter:
    """Counts every accessibility attribute the driver reads.

    This is the only thing offline that can tell a scoped lookup from a full-window walk,
    and cost is a correctness property for this driver: a version whose every lookup
    walked the window captured **7 targets in 28 minutes**, every one correct and
    attributed, and could not have reached 76. Live, one attribute read is one
    interprocess round trip — a full walk of the 907-node document window measured
    6.4 s — so a read count is a time estimate with the host's variance taken out.
    """

    reads: int = 0

    def read(self) -> None:
        self.reads += 1


class FakeNode:
    """One element of a fake accessibility tree, matching :class:`driver.AXNode`.

    Every attribute is a counted property rather than a field, because an attribute read
    is what the driver pays for and a dataclass field is free. A node given no counter
    gets its own, so a node built directly by a test costs nothing to the fake's total.

    There is no ``frame``: the driver reads no rectangles any more, so a fake that
    published them would let a coordinate mapping come back unnoticed.
    """

    def __init__(
        self,
        role: str,
        title: str | None = None,
        value: str | None = None,
        enabled: bool = True,
        selected: bool = False,
        children: list[FakeNode] | None = None,
        rows: list[FakeNode] | None = None,
        index: int | None = None,
        on_press: Callable[[], None] | None = None,
        on_set_selected: Callable[[bool], None] | None = None,
        press_error: str | None = None,
        select_error: str | None = None,
        counter: ReadCounter | None = None,
    ) -> None:
        self._role = role
        self._title = title
        self._value = value
        self._enabled = enabled
        self._selected = selected
        self._children = children if children is not None else []
        self._rows = rows
        self._index = index
        self.on_press = on_press
        self.on_set_selected = on_set_selected
        self.press_error = press_error
        self.select_error = select_error
        self.counter = counter if counter is not None else ReadCounter()

    @property
    def rows(self) -> list[FakeNode] | None:
        """``AXRows``, which an outline publishes more of than ``AXChildren``. None else.

        The asymmetry with ``children`` is the point: live, ``AXRows`` was 152 and
        ``AXVisibleRows`` 24, and reading children instead is what had the driver report
        "the pane shows 62 names" and fail 26 targets looking for rows that existed. It
        is not all of them either — see ``published_row_count``.
        """
        self.counter.read()
        return self._rows

    @property
    def index(self) -> int | None:
        """``AXIndex``: the row's own position in its outline, as it reports it.

        This is what identifies a row when the pane publishes only some of them, and
        every live row published one: 0, 1, 76 and 151 at those offsets. ``None`` for an
        element that does not publish it, which is everything but a row.
        """
        self.counter.read()
        return self._index

    @property
    def role(self) -> str:
        self.counter.read()
        return self._role

    @property
    def title(self) -> str | None:
        self.counter.read()
        return self._title

    @property
    def value(self) -> str | None:
        self.counter.read()
        return self._value

    @property
    def enabled(self) -> bool:
        self.counter.read()
        return self._enabled

    @property
    def selected(self) -> bool:
        self.counter.read()
        return self._selected

    @property
    def children(self) -> list[FakeNode]:
        self.counter.read()
        return self._children

    def press(self) -> None:
        if self.press_error:
            raise driver.TargetFailure(self.press_error)
        if self.on_press is not None:
            self.on_press()

    def set_selected(self, selected: bool) -> None:
        if self.select_error:
            raise driver.TargetFailure(self.select_error)
        if self.on_set_selected is not None:
            self.on_set_selected(selected)


#: Tiles the Entrance gallery holds, as **pages**. The live gallery is an
#: ``AXScrollArea`` publishing only its current page: 25 tiles, with ``Grow & Turn``,
#: ``Stretch`` and ``Zoom`` on another page — which is why three targets failed as "none
#: of 'Grow & Turn', 'Grow Turn' appeared" against a gallery that holds it.
ENTRANCE_PAGES = (("Fly In", "Fade"), ("Grow & Turn",))
ENTRANCE_TILES = tuple(title for page in ENTRANCE_PAGES for title in page)
PATH_PRESETS = ("Lines", "Arcs", "Turns")


class FakePowerPoint:
    """A PowerPoint stand-in that rebuilds its tree on every read.

    Nothing here is a cached element: each ``windows()`` call returns new nodes, which is
    how the real application behaves (``computer-use.md``: element identity does not
    survive a read, and a press can scroll a gallery and renumber it).

    It has **no slide navigator**, because the live 2026-10-31 run established that the
    navigator is not drivable: its cells publish no actions and only the few scrolled into
    view exist at all. It also has **no canvas and no frames**, because shape selection is
    a Selection Pane row now and a coordinate click has nothing left to aim at.

    The Selection Pane is modelled the way it was measured: an ``AXOutline`` of one
    ``AXRow`` per shape in **reverse z-order**, each row's name carried as a descendant
    ``AXStaticText``'s ``value`` rather than as the row's title, and ``AXSelected``
    settable with no ``AXPress``. A gallery press applies its effect to **whichever row
    is selected**, so a driver that selected the wrong row would put the effect on the
    wrong shape and the attribution gate would say so.

    Only the active ribbon tab's controls are in the tree: ``Arrange`` exists on Home,
    the galleries exist on Animations. That makes the ribbon switch the Selection Pane
    costs real rather than free.

    It is hostile about **cost** too, in the two ways the live application is:

    - it publishes ``Save`` under an ``AXToolbar`` and the whole ribbon under one
      ``AXTabGroup``, with the active tab's commands in a scroll area inside it, so a
      lookup that walked the window instead of the container would be visible in the read
      count rather than merely slower;
    - it publishes four more windows carrying the **same document title**, none of them
      holding the ribbon and each holding a subtree big enough to be worth not walking,
      because ``document_window`` identifying the right one by walking each candidate is
      half of what made a live run four minutes per target.
    """

    def __init__(
        self,
        document: Path,
        *,
        slide_index: int = 1,
        tile_pages: tuple[tuple[str, ...], ...] = ENTRANCE_PAGES,
        page: int = 0,
        duplicate_tile: str | None = None,
        applies_effect: bool = True,
        selection_sticks: bool = True,
        missing_rows: tuple[str, ...] = (),
        duplicate_row: str | None = None,
        visible_row_count: int | None = None,
        named_row_count: int | None = None,
        published_row_count: int | None = None,
        partial_reads: int | None = None,
        selection_pane_open: bool = False,
        active_tab: str = driver.RIBBON_ANCHOR_TAB,
        decoy_windows: int = 4,
    ) -> None:
        self.document = document
        self.slide_index = slide_index
        #: The gallery's tiles, as pages. Only the current page is published.
        self.tile_pages = tile_pages
        #: Which page the gallery is showing. A press leaves it wherever it was, so the
        #: next target starts from here — which is why the driver pages **up** first.
        self.page = page
        #: Every page the driver asked for, in order, as ``"up"`` / ``"down"``.
        self.scrolls: list[str] = []
        self.duplicate_tile = duplicate_tile
        self.applies_effect = applies_effect
        #: When false, writing ``AXSelected`` is accepted and does nothing — the shape
        #: the driver asked for never reads back selected. This is the Selection Pane's
        #: analogue of the click that left the shape unselected.
        self.selection_sticks = selection_sticks
        #: Rows the pane does not publish, by shape name. Removing one **renumbers**
        #: every row below it, exactly as the live outline's ``AXIndex`` would.
        self.missing_rows = set(missing_rows)
        #: A name the pane publishes one extra row for, at the end of pane order.
        self.duplicate_row = duplicate_row
        #: An index two published rows both claim as their own ``AXIndex``. The live pane
        #: never did this; the driver refuses rather than picking, because selecting one
        #: row of two would apply the value to a shape of two.
        self.duplicate_index: int | None = None
        #: ``selected row -> shape the press actually animates``. The pane reports the
        #: row the driver selected, and PowerPoint applies the effect elsewhere. With a
        #: read-back-confirmed row selection this is the ONLY way the wrong shape can
        #: still receive a press, and the attribution gate is what has to catch it.
        self.applies_to_instead: dict[str, str] = {}
        #: Shapes whose press applies no effect at all, by shape name. One target of a
        #: batch gaining nothing while its siblings gain is what has to reject that one
        #: and credit the rest.
        self.applies_nothing_for: set[str] = set()
        # How many rows ``AXChildren`` publishes. ``None`` means all of them, which is
        # what the live pane happened to publish when it was probed. It is not what it
        # always publishes: across one run the driver saw 62 names, then 47, of 152, as
        # the pane scrolled — and that is how 26 targets failed looking for rows that
        # existed. A test sets this low to pin that ``AXRows`` is what makes the lookup
        # whole; leaving it at None keeps a full walk's cost representative of the live
        # 907-node window.
        self.visible_row_count = visible_row_count
        #: How many rows, in pane order, publish a readable **name**. ``None`` means all
        #: of them. Live, a row that has never been scrolled into view publishes no
        #: ``AXStaticText`` at all: one run's batches read 80 names, then 54, from the
        #: same 152 rows, and the by-name lookup rejected 11 targets for rows that were
        #: present and selectable throughout. A row with no name is still a row and is
        #: still selectable here, which is what makes addressing one by index work.
        self.named_row_count = named_row_count
        #: How many rows ``AXRows`` itself publishes, as a prefix. ``None`` means all of
        #: them. This is the state that refused 7 targets: the pane published 43, 54, 61,
        #: 63, 74, 88 and 91 rows of 152 on consecutive reads during one run, so neither
        #: the count nor an offset into it says anything and a row is found by its own
        #: ``AXIndex``.
        self.published_row_count = published_row_count
        #: How many reads keep ``published_row_count`` before the pane publishes all its
        #: rows. ``None`` means forever. A small number models a pane that fills in,
        #: which is what the driver retries for.
        self.partial_reads = partial_reads
        self.selection_pane_open = selection_pane_open
        self.active_tab = active_tab
        #: How many same-titled windows PowerPoint publishes that are NOT the document.
        self.decoy_windows = decoy_windows
        self.trusted_flag = True
        self.frontmost = driver.BUNDLE_ID
        self.document_title = document.stem
        #: spid -> (presetID, presetClass), replaced per shape exactly as a gallery press
        #: replaces the selected shape's effect.
        self.effects: dict[str, tuple[str, str]] = {}
        self.selected_name: str | None = None
        self.open_popup: str | None = None
        self.arrange_open = False
        self.presses: list[tuple[str, str | None]] = []
        self.selections: list[str] = []
        self.selection_pane_presses = 0
        self.reads = 0
        self.saves = 0
        self.slept = 0.0
        self._now = 100.0
        self.counter = ReadCounter()
        #: ``(name, spid)`` in z-order, back to front, labels included. Read from the
        #: package, so the pane publishes exactly one row per shape the slide carries —
        #: as the live pane did, and as the driver's row count check requires. A pane
        #: with more rows than the slide has shapes is built by adding shapes to the
        #: slide (:func:`add_filler_shapes`), never by inventing rows here.
        self._shapes = shape_names_in_z_order(document, slide_index)
        self._spids = dict(self._shapes)

    # --- behaviour --------------------------------------------------------
    @property
    def shape_selected(self) -> bool:
        return self.selected_name is not None

    @property
    def selected_spid(self) -> str | None:
        """The spid of whichever shape's row is selected, or None."""
        return self._spids.get(self.selected_name) if self.selected_name else None

    def select(self, name: str) -> None:
        """Select a shape by name, as setting its row's ``AXSelected`` does."""
        self.selected_name = name

    def _row_names(self) -> list[str]:
        """The names the pane publishes, in pane order: reverse z-order."""
        names = [name for name, _spid in reversed(self._shapes) if name not in self.missing_rows]
        if self.duplicate_row:
            names.append(self.duplicate_row)
        return names

    def _set_row_selected(self, name: str, selected: bool) -> None:
        self.selections.append(name)
        if not self.selection_sticks:
            return
        self.selected_name = name if selected else None

    def _press_tile(self, title: str) -> None:
        self.presses.append((title, self.selected_spid))
        if not self.applies_effect or self.selected_name is None:
            return
        if self.selected_name in self.applies_nothing_for:
            return
        animated = self.applies_to_instead.get(self.selected_name, self.selected_name)
        self.effects[self._spids[animated]] = TILE_PRESETS.get(title, DEFAULT_PRESET)

    def _save(self) -> None:
        self.saves += 1
        write_effects(self.document, self.slide_index, self.effects)
        # Guarantees the (mtime, size) pair the driver waits on changes even when the
        # effects did not, so a save is never mistaken for a hang.
        stamp = self.document.stat().st_mtime + 5
        os.utime(self.document, (stamp, stamp))

    # --- the tree ---------------------------------------------------------
    def _node(self, **fields: Any) -> FakeNode:
        """Build a node that counts its attribute reads into this fake's counter."""
        return FakeNode(counter=self.counter, **fields)

    def _gallery(self) -> FakeNode:
        """The Entrance gallery: a scroll area publishing only its current page.

        ``tile_pages`` is what makes a tile unreachable by reading alone, which is the
        live behaviour: the gallery published 25 tiles and the three targets that failed
        last were effects on another page. Paging is an action on this element, so it
        costs no pointer and no coordinates.
        """
        pages = [list(page) for page in self.tile_pages]
        if self.duplicate_tile:
            pages[self.page][:] = [*pages[self.page], self.duplicate_tile]
        return self._node(
            role="AXScrollArea",
            title="Entrance Effects",
            enabled=self.shape_selected,
            children=[
                self._node(
                    role="AXRadioButton",
                    # The accessibility layer drops the ampersand and leaves the spaces
                    # around it: 'Grow & Turn' is published as 'Grow  Turn'. Two targets
                    # were reported absent for that, from a gallery that holds them.
                    title=title.replace("&", ""),
                    enabled=self.shape_selected,
                    on_press=lambda title=title: self._press_tile(title),
                )
                for title in pages[self.page]
            ],
        )

    def _pagers(self) -> list[FakeNode]:
        """The ribbon's own ``Previous``/``Next`` gallery buttons.

        These are what move a gallery. The gallery's own ``AXScrollUpByPage`` /
        ``AXScrollDownByPage`` are accepted and do nothing — measured: a run paged 8 each
        way and no tile appeared — so the fake does not offer them at all, and a driver
        that went back to them would find nothing to scroll.
        """
        return [
            self._node(
                role="AXButton",
                title=driver.GALLERY_PAGE_PREVIOUS.format(gallery="Entrance Effects"),
                enabled=self.page > 0,
                on_press=lambda: self._page_gallery(down=False),
            ),
            self._node(
                role="AXButton",
                title=driver.GALLERY_PAGE_NEXT.format(gallery="Entrance Effects"),
                enabled=self.page < len(self.tile_pages) - 1,
                on_press=lambda: self._page_gallery(down=True),
            ),
        ]

    def _page_gallery(self, *, down: bool) -> None:
        """Turn the gallery one page, as pressing a pager does."""
        self.scrolls.append("down" if down else "up")
        target = self.page + (1 if down else -1)
        if 0 <= target < len(self.tile_pages):
            self.page = target

    def _path_animation_button(self) -> FakeNode:
        return self._node(
            role="AXMenuButton",
            title=planner.PATH_ANIMATION_CONTROL,
            enabled=self.shape_selected,
            on_press=lambda: setattr(self, "open_popup", planner.PATH_ANIMATION_CONTROL),
        )

    def _toolbar(self) -> FakeNode:
        """The Quick Access toolbar, which is where ``Save`` lives.

        Live, ``Save`` is under the window's ``AXToolbar``, and the driver resolves it
        there rather than walking the window. Publishing it anywhere else here would let
        a full-window walk come back without the read budget noticing.
        """
        return self._node(
            role=driver.TOOLBAR_ROLE,
            children=[self._node(role="AXButton", title=driver.SAVE_LABEL, on_press=self._save)],
        )

    def _ribbon(self) -> FakeNode:
        """The ribbon: the tab strip, and the active tab's commands inside it.

        One ``AXTabGroup`` holding both, with the commands a level deeper in a scroll
        area, which is what the driver scopes every tab, gallery, tile and labelled
        read-back to. Pressing a tab makes it the active one.
        """
        children = [
            self._node(
                role="AXRadioButton",
                title=title,
                on_press=lambda title=title: setattr(self, "active_tab", title),
            )
            for title in (driver.RIBBON_ANCHOR_TAB, "Transitions", planner.ANIMATIONS_TAB)
        ]
        commands: list[FakeNode] = []
        if self.active_tab == driver.RIBBON_ANCHOR_TAB:
            commands.append(self._arrange_button())
        if self.active_tab == planner.ANIMATIONS_TAB:
            animated = self.selected_spid in self.effects
            commands += [
                self._gallery(),
                *self._pagers(),
                self._path_animation_button(),
                self._node(
                    role="AXPopUpButton",
                    title=driver.START_LABEL,
                    value="On Click" if animated else None,
                ),
                self._node(
                    role="AXIncrementor",
                    title=driver.DURATION_LABEL,
                    value="05.00" if animated else None,
                ),
            ]
        children.append(self._node(role="AXScrollArea", children=commands))
        return self._node(role=driver.RIBBON_ROLE, children=children)

    def _arrange_button(self) -> FakeNode:
        """``Home ▸ Arrange``, which opens the ``Arrange`` window when pressed."""
        return self._node(
            role="AXMenuButton",
            title=driver.SELECTION_PANE_PATH[1],
            on_press=lambda: setattr(self, "arrange_open", True),
        )

    def _arrange_window(self) -> FakeNode:
        return self._node(
            role="AXWindow",
            title=driver.SELECTION_PANE_PATH[1],
            children=[
                self._node(
                    role="AXMenuButton",
                    title=driver.SELECTION_PANE_PATH[2],
                    on_press=self._press_selection_pane_item,
                )
            ],
        )

    def _press_selection_pane_item(self) -> None:
        """Toggle the pane, exactly as pressing an already-active control does."""
        self.selection_pane_presses += 1
        self.selection_pane_open = not self.selection_pane_open
        self.arrange_open = False

    def _selection_pane(self) -> FakeNode:
        """The pane: one row per shape in reverse z-order, named by a descendant label.

        A row carries **no title and no ``AXPress``** — only ``AXSelected`` — which is
        what the live pane exposed, and is why the driver selects a row by writing the
        attribute rather than pressing it.

        Two independent things vary here, because they varied live:

        * ``visible_row_count`` — how many rows ``AXChildren`` publishes. ``AXRows``
          always publishes all of them.
        * ``named_row_count`` — how many rows publish a **name** at all. An unscrolled
          row has no ``AXStaticText`` beneath it, so it is a row the driver can select
          and cannot identify.
        """
        names = self._row_names()
        labels: list[str | None] = [
            name if self.named_row_count is None or index < self.named_row_count else None
            for index, name in enumerate(names)
        ]

        def row(position: int, name: str, label: str | None) -> FakeNode:
            # Selection is keyed on the row's own shape, named or not: a row with no
            # readable label still selects its shape, which is the whole reason a row can
            # be addressed by index. The index is the row's own ``AXIndex``, so it stays
            # correct in a read that publishes only some of the rows.
            return self._node(
                role=driver.SELECTION_ROW_ROLE,
                index=position,
                selected=name == self.selected_name,
                on_set_selected=(
                    lambda selected, name=name: self._set_row_selected(name, selected)
                ),
                children=(
                    []
                    if label is None
                    else [self._node(role=driver.SELECTION_LABEL_ROLE, value=label)]
                ),
            )

        # ``AXChildren`` publishes only the rows scrolled into view; ``AXRows`` publishes
        # all of them. Measured live: 152 rows, 24 visible. Reading children is what had
        # the driver report "the pane shows 62 names", then 47, and fail 26 targets
        # looking for a row that was there the whole time. The fake reproduces the
        # asymmetry so that regression cannot come back unnoticed.
        rows = [
            (self.duplicate_index if self.duplicate_index is not None and position == 0 else position, pair)
            for position, pair in enumerate(zip(names, labels))
        ]
        published = rows[: self._publication_limit()]
        visible = (
            published if self.visible_row_count is None else published[: self.visible_row_count]
        )
        return self._node(
            role=driver.SELECTION_PANE_ROLE,
            children=[row(position, name, label) for position, (name, label) in visible],
            rows=[row(position, name, label) for position, (name, label) in published],
        )

    def _publication_limit(self) -> int | None:
        """How many rows ``AXRows`` publishes on this read, or None for all of them.

        The live pane publishes a **prefix** that changes between reads: 43, 54, 61, 63,
        74, 88 then 91 rows of 152 on consecutive reads during one run, because it
        rebuilds while the application works. ``partial_reads`` spends that state after a
        given number of reads, so a test can have the pane fill in — which is what the
        driver's retry is for — rather than only model a pane that never does.
        """
        if self.published_row_count is None:
            return None
        if self.partial_reads is None:
            return self.published_row_count
        if self.partial_reads <= 0:
            return None
        self.partial_reads -= 1
        return self.published_row_count

    def _document_window(self) -> FakeNode:
        children = [self._toolbar(), self._ribbon()]
        if self.selection_pane_open:
            children.append(self._selection_pane())
        return self._node(role="AXWindow", title=self.document_title, children=children)

    def _decoy_window(self, index: int) -> FakeNode:
        """A window with the document's title, no ribbon, and a subtree worth skipping.

        PowerPoint publishes four or five of these. ``document_window`` used to tell them
        apart by walking each one looking for a ribbon tab, so each decoy here holds
        enough nodes that doing it again would show up in the read budget.
        """
        return self._node(
            role="AXWindow",
            title=self.document_title,
            children=[
                self._node(
                    role="AXGroup",
                    title=f"decoy {index} group {outer}",
                    children=[
                        self._node(role="AXStaticText", value=f"decoy {index}.{outer}.{inner}")
                        for inner in range(8)
                    ],
                )
                for outer in range(4)
            ],
        )

    def _popup_window(self) -> FakeNode:
        return self._node(
            role="AXWindow",
            title=planner.PATH_ANIMATION_CONTROL,
            children=[
                self._node(
                    role="AXMenuButton",
                    title=title,
                    on_press=lambda title=title: self._press_tile(title),
                )
                for title in PATH_PRESETS
            ],
        )

    # --- the backend protocol ---------------------------------------------
    def trusted(self) -> bool:
        return self.trusted_flag

    def frontmost_bundle_id(self) -> str | None:
        return self.frontmost

    @property
    def attribute_reads(self) -> int:
        """How many accessibility attributes have been read since this fake was built."""
        return self.counter.reads

    def windows(self) -> list[Any]:
        self.reads += 1
        # The decoys come FIRST, so a driver that took the first window with the right
        # title rather than the one carrying the ribbon would fail outright.
        windows = [self._decoy_window(index) for index in range(self.decoy_windows)]
        windows.append(self._document_window())
        if self.open_popup:
            windows.append(self._popup_window())
        if self.arrange_open:
            windows.append(self._arrange_window())
        return windows

    def now(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self.slept += seconds
        self._now += seconds


# --- fixtures ---------------------------------------------------------------
@pytest.fixture(scope="module")
def real_plan() -> dict[str, Any]:
    """The plan derived from the checked-in catalog and manifest.

    **Empty today**, and that is the point of the whole exercise: the plan is
    the catalog's own open gaps, and the 2026-11-01 capture closed every
    GUI-addressable animation gap there was. A test that needs targets uses
    :func:`reopened_plan` instead.
    """
    return planner.build_plan(
        planner.load_json(planner.DEFAULT_CATALOG), planner.load_json(planner.DEFAULT_MANIFEST)
    )


def reopen_gallery_gaps(catalog: dict[str, Any]) -> dict[str, Any]:
    """Return the catalog with the gallery payload gaps put back, in place.

    The planner and the deck builder are the machinery for the **next** gap, and
    with none open they would go uncovered — a derivation that produced nothing
    would pass every assertion about what it produces. So the tests that check
    the machinery run it against the state the catalog was in before the
    capture: every gallery tile capture-required for its behaviour payloads.

    This reconstructs that state rather than pinning a copy of the old catalog,
    so it keeps following the real entries: a tile added to the gallery tables
    appears here too.
    """
    for entry in catalog["guiItems"]:
        ooxml = entry.get("ooxml")
        if not isinstance(ooxml, dict) or not entry["key"].startswith("animation.gallery."):
            continue
        if entry["key"].startswith("animation.gallery.media."):
            continue
        children = ooxml.pop("behaviors", None)
        if children is None:
            continue
        ooxml["requiresCapture"] = True
        ooxml["unresolvedPayloads"] = sorted({child["element"] for child in children})
        ooxml["gap"] = "reopened by the test suite to exercise the plan derivation"
    return catalog


@pytest.fixture(scope="module")
def reopened_plan() -> dict[str, Any]:
    """The plan the checked-in catalog derived before its gaps were closed."""
    return planner.build_plan(
        reopen_gallery_gaps(planner.load_json(planner.DEFAULT_CATALOG)),
        planner.load_json(planner.DEFAULT_MANIFEST),
    )


@pytest.fixture(scope="module")
def small_plan() -> dict[str, Any]:
    """A three-target plan: two ribbon tiles and one motion path through a popup."""
    targets = [
        {
            "key": "animation.gallery.entrance.flyIn",
            "guiPath": [planner.ANIMATIONS_TAB, "Entrance Effects", "Fly In"],
            "titleAlternatives": [],
        },
        {
            "key": "animation.gallery.entrance.growTurn",
            "guiPath": [planner.ANIMATIONS_TAB, "Entrance Effects", "Grow & Turn"],
            "titleAlternatives": ["Grow Turn"],
        },
        {
            "key": "animation.gallery.motionPath.lines",
            "guiPath": [planner.ANIMATIONS_TAB, planner.PATH_ANIMATION_CONTROL, "Basic", "Lines"],
            "titleAlternatives": [],
        },
    ]
    grid = planner.assign_cells(targets)
    return {"plan": "test", "shapeNames": {}, "deck": grid.as_dict(), "targets": targets}


@pytest.fixture(scope="module")
def built_deck(small_plan, tmp_path_factory) -> dict[str, Any]:
    """Build the capture deck from the small plan, once, through sdpm."""
    root = tmp_path_factory.mktemp("capture")
    deck = root / "deck"
    planner.build_capture_deck(small_plan, deck)
    result = planner.generate_capture_deck(deck, root / "capture-deck.pptx")
    package = Path(result["output_path"])
    return {
        "deck": deck,
        "package": package,
        "result": result,
        "names": planner.resolve_shape_names(package, small_plan),
    }


@pytest.fixture
def session(small_plan, built_deck, tmp_path):
    """A runnable session: the built package, a fake PowerPoint, and settings."""
    document = tmp_path / f"{built_deck['package'].stem}.pptx"
    document.write_bytes(built_deck["package"].read_bytes())
    plan = copy.deepcopy(small_plan)
    planner.apply_shape_names(plan, built_deck["names"])
    fake = FakePowerPoint(document)
    settings = driver.CaptureSettings(out_dir=tmp_path / "out", document=document, timeout=2.0)
    spids = {
        target["key"]: driver.read_shape_spid(document, target["slideIndex"], target["shapeName"])
        for target in plan["targets"]
    }
    return {"plan": plan, "fake": fake, "settings": settings, "names": built_deck["names"], "spids": spids}


# --- plan derivation --------------------------------------------------------
class TestPlanDerivation:
    """The target list is read out of the catalog's gaps, not typed into a file."""

    def test_the_plan_is_empty_because_every_gui_gap_is_closed(self, real_plan):
        """Nothing left to capture. This test used to assert the opposite.

        The plan is the catalog's open gaps, so an empty plan is the statement
        that the GUI-addressable animation surface is measured — all 76 of it.
        What remains is 51 deferred entries, which are not reachable from the
        ribbon at all, and 185 scripting enumerators set aside for a decision.
        """
        assert real_plan["counts"]["targets"] == 0
        assert real_plan["counts"]["deferredTargets"] > 0
        assert real_plan["targets"] == []

    def test_the_plan_has_targets_and_names_what_it_was_derived_from(self, reopened_plan):
        real_plan = reopened_plan
        assert real_plan["counts"]["targets"] > 0
        source = real_plan["generatedFrom"]
        assert source["catalog"].endswith("powerpoint-animation-catalog.json")
        assert source["manifestVersion"]
        assert "requiresCapture" in source["selection"]
        assert real_plan["driver"] == planner.DRIVER

    def test_every_capture_required_gui_entry_lands_in_exactly_one_list(self, real_plan):
        catalog = planner.load_json(planner.DEFAULT_CATALOG)
        expected = {
            entry["key"]
            for entry in catalog["guiItems"]
            if planner.requires_capture(entry) and planner.is_gui_addressable(entry["key"])
        }
        targets = {target["key"] for target in real_plan["targets"]}
        deferred = {entry["key"] for entry in real_plan["deferredTargets"]}
        assert targets | deferred == expected, "a capture-required GUI entry is in neither list"
        assert not targets & deferred, "an entry is in both lists"
        assert len(targets) + len(deferred) == len(expected)

    def test_every_capture_required_candidate_is_set_aside_with_a_reason(self, real_plan):
        catalog = planner.load_json(planner.DEFAULT_CATALOG)
        expected = {entry["key"] for entry in catalog["candidates"] if planner.requires_capture(entry)}
        set_aside = {entry["key"] for entry in real_plan["setAsideScriptingEnumerators"]}
        assert set_aside == expected
        assert all(entry["enum"].startswith("MsoAnim") for entry in real_plan["setAsideScriptingEnumerators"])
        assert all(entry["reason"] for entry in real_plan["setAsideScriptingEnumerators"])

    def test_the_counts_match_the_lists(self, real_plan):
        for name, count_ in real_plan["counts"].items():
            assert len(real_plan[name]) == count_, name

    def test_a_gallery_target_names_the_tab_the_gallery_and_the_tile(self, reopened_plan):
        by_key = {target["key"]: target for target in reopened_plan["targets"]}
        target = by_key["animation.gallery.entrance.flyIn"]
        assert target["guiPath"] == [planner.ANIMATIONS_TAB, "Entrance Effects", "Fly In"]
        assert by_key["animation.gallery.exit.flyOut"]["guiPath"][1] == "Exit Effects"
        assert by_key["animation.gallery.emphasis.pulse"]["guiPath"][1] == "Emphasis Effects"

    def test_a_motion_path_goes_through_the_path_animation_window(self, reopened_plan):
        by_key = {target["key"]: target for target in reopened_plan["targets"]}
        assert by_key["animation.gallery.motionPath.lines"]["guiPath"] == [
            planner.ANIMATIONS_TAB,
            planner.PATH_ANIMATION_CONTROL,
            "Lines",
        ]

    def test_an_irregular_label_comes_from_the_table_and_keeps_the_derived_form(self, reopened_plan):
        by_key = {target["key"]: target for target in reopened_plan["targets"]}
        grow = by_key["animation.gallery.emphasis.growShrink"]
        assert grow["title"] == "Grow/Shrink"
        assert grow["titleSource"] == "labelTable"
        assert "Grow Shrink" in grow["titleAlternatives"]
        plain = by_key["animation.gallery.entrance.flyIn"]
        assert (plain["title"], plain["titleSource"]) == ("Fly In", "catalogKey")

    def test_titles_are_derived_from_the_key_not_from_a_list(self):
        assert planner.gui_title("flyIn")[0] == "Fly In"
        assert planner.gui_title("complementaryColor2")[0] == "Complementary Color 2"
        assert planner.gui_title("basicSwivel")[0] == "Basic Swivel"
        assert planner.gui_title("blink") == ("Blink", (), "catalogKey")

    def test_directions_are_deferred_with_a_stated_reason_rather_than_dropped(self, real_plan):
        directions = [
            entry for entry in real_plan["deferredTargets"]
            if entry["key"].startswith("animation.effectOptions.direction.")
        ]
        assert len(directions) == 45
        assert all("depend on which effect" in entry["reason"] for entry in directions)

    def test_the_other_deferrals_each_say_why(self, real_plan):
        reasons = {entry["key"]: entry["reason"] for entry in real_plan["deferredTargets"]}
        # `animation.gallery.motionPath.custom` used to be deferred here. It is
        # no longer a target at all: the Custom group is a selection surface
        # for the four Draw tools, so the catalog records it nonPersisted and a
        # capture has nothing to aim at.
        assert "animation.gallery.motionPath.custom" not in reasons
        assert "media object" in reasons["animation.gallery.media.mediaStop"]
        assert "effect dialog" in reasons["animation.afterAnimation.dim"]
        assert all(reasons.values())

    def test_gaps_without_the_capture_flag_are_listed_rather_than_implied_closed(self, real_plan):
        keys = {entry["key"] for entry in real_plan["gapsWithoutCaptureFlag"]}
        # computer-use.md Steps 3 to 5 are exactly these, and none carries requiresCapture.
        assert "animation.timing.rewind" in keys
        assert "animation.sound.effect" in keys
        # `animation.start.none` was listed here until the catalog stopped
        # treating an absent start condition as a value awaiting measurement.
        assert "animation.start.none" not in keys
        assert all(entry["gap"] for entry in real_plan["gapsWithoutCaptureFlag"])

    def test_no_target_is_outside_the_gui_namespaces(self, real_plan):
        assert all(planner.is_gui_addressable(target["key"]) for target in real_plan["targets"])

    def test_a_stale_catalog_manifest_pair_refuses_to_emit(self):
        catalog = planner.load_json(planner.DEFAULT_CATALOG)
        manifest = planner.load_json(planner.DEFAULT_MANIFEST)
        manifest["manifestVersion"] = "9999-01-01.1"
        with pytest.raises(ValueError, match="catalog pins guiManifest"):
            planner.build_plan(catalog, manifest)

    def test_the_plan_shrinks_when_a_gap_closes(self):
        catalog = reopen_gallery_gaps(planner.load_json(planner.DEFAULT_CATALOG))
        manifest = planner.load_json(planner.DEFAULT_MANIFEST)
        before = planner.build_plan(catalog, manifest)["counts"]["targets"]
        for entry in catalog["guiItems"]:
            if entry["key"] == "animation.gallery.entrance.flyIn":
                entry["ooxml"]["requiresCapture"] = False
        after = planner.build_plan(catalog, manifest)
        assert after["counts"]["targets"] == before - 1
        assert "animation.gallery.entrance.flyIn" not in {t["key"] for t in after["targets"]}


# --- the shape grid ---------------------------------------------------------
class TestShapeGrid:
    """Shapes over as few slides as the constraints allow, checked rather than eyeballed."""

    def test_the_catalog_is_laid_out_over_as_few_slides_as_the_constraints_allow(
        self, reopened_plan
    ):
        """Two slides, and the second one is the constraints working rather than failing.

        This asserted one slide while the catalog had 76 targets. It has 99 once
        every gallery gap is reopened, and one slide cannot hold that many shapes
        that are both clickable — 80 px on the short side — and wide enough for
        `complementaryColor2` on one line, which needs 114 px. Shrinking either
        is what a capture pays for later, so the grid splits instead.
        """
        assert reopened_plan["counts"]["targets"] == EXPECTED_TARGETS
        deck = reopened_plan["deck"]
        assert deck["slides"] == EXPECTED_SLIDES
        assert (deck["columns"], deck["rows"]) == EXPECTED_GRID
        assert tuple(deck["shapePx"]) == EXPECTED_SHAPE_PX
        # The short side is what bounds a click. 87 px is 43.5 pt, double the 22 pt that
        # made a live run land 71 presses on five shapes.
        assert min(deck["shapePx"]) / 2 >= 40, "the short side is back under 40 pt"
        assert deck["shapePx"][0] >= planner.label_width_px("complementaryColor2"), (
            "the widest label no longer fits its box on one line"
        )
        slides = {target["slideIndex"] for target in reopened_plan["targets"]}
        assert slides == set(range(1, EXPECTED_SLIDES + 1))

    def test_every_target_gets_its_own_cell_in_plan_order(self, reopened_plan):
        targets = reopened_plan["targets"]
        cells = [(t["slideIndex"], t["cellIndex"]) for t in targets]
        assert len(set(cells)) == len(cells)
        assert [t["targetIndex"] for t in targets] == list(range(1, len(targets) + 1))
        # Cell numbering restarts on each slide, so plan order is checked per slide
        # rather than across the whole run.
        by_slide: dict[int, list[int]] = {}
        for slide, cell in cells:
            by_slide.setdefault(slide, []).append(cell)
        for slide, numbers in sorted(by_slide.items()):
            assert numbers == list(range(1, len(numbers) + 1)), slide

    def test_no_two_shapes_overlap_and_no_shape_leaves_the_slide(self, reopened_plan):
        by_slide: dict[int, list[planner.Rect]] = {}
        for target in reopened_plan["targets"]:
            by_slide.setdefault(target["slideIndex"], []).append(
                planner.Rect(**target["shapeRectPx"])
            )
        # Per slide: two shapes at the same position on *different* slides are not
        # an overlap, and comparing across slides reported one.
        for slide, rects in sorted(by_slide.items()):
            for first in range(len(rects)):
                for second in range(first + 1, len(rects)):
                    assert not rects[first].overlaps(rects[second]), (slide, first, second)
            for rect in rects:
                assert rect.x >= 0 and rect.y >= 0
                assert rect.x + rect.width <= planner.DECK_BASIS_PX[0]
                assert rect.y + rect.height <= planner.DECK_BASIS_PX[1]

    def test_a_click_at_a_centre_clears_its_own_edges_and_every_neighbour(self, real_plan):
        rects = [planner.Rect(**target["shapeRectPx"]) for target in real_plan["targets"]]
        for index, rect in enumerate(rects):
            centre = rect.center
            inset = min(
                centre[0] - rect.x,
                rect.x + rect.width - centre[0],
                centre[1] - rect.y,
                rect.y + rect.height - centre[1],
            )
            assert inset >= planner.CLICK_MARGIN_PX, index
            for other_index, other in enumerate(rects):
                if other_index == index:
                    continue
                assert other.distance_to(centre) >= planner.NEIGHBOUR_CLEARANCE_PX, (index, other_index)

    def test_one_slide_holds_far_more_than_the_catalog_needs(self):
        capacity = planner.max_targets_per_slide()
        assert capacity > EXPECTED_TARGETS
        assert planner.grid_layout(capacity).slides == 1
        assert planner.grid_layout(capacity).split is False

    def test_a_count_that_cannot_fit_one_slide_splits_into_as_few_as_possible(self):
        """The grid never silently shrinks a shape below a clickable size."""
        capacity = planner.max_targets_per_slide()
        for extra, slides in ((1, 2), (capacity, 2), (capacity + 1, 3)):
            grid = planner.grid_layout(capacity + extra)
            assert grid.slides == slides, (capacity + extra, grid.slides)
            assert grid.split is True
            assert f"split across {slides} slides" in grid.as_dict()["note"]
            per_slide = [
                len([cell for cell in grid.cells if cell.slide_index == index])
                for index in range(1, slides + 1)
            ]
            assert sum(per_slide) == capacity + extra
            assert max(per_slide) <= min(grid.per_slide, capacity)

    def test_a_split_grid_still_satisfies_every_separation_constraint(self):
        grid = planner.grid_layout(planner.max_targets_per_slide() + 1)
        # grid_layout checks this itself and raises; re-checking here means a relaxed
        # check inside the planner cannot pass unnoticed.
        for cell in grid.cells:
            for other in grid.cells:
                if other is cell or other.slide_index != cell.slide_index:
                    continue
                assert not cell.shape.overlaps(other.shape)
                assert other.shape.distance_to(cell.shape.center) >= planner.NEIGHBOUR_CLEARANCE_PX

    def test_a_grid_whose_cells_would_be_unclickable_is_refused_not_shrunk(self, monkeypatch):
        monkeypatch.setattr(planner, "CLICK_MARGIN_PX", 10_000.0)
        with pytest.raises(ValueError, match="unsatisfiable"):
            planner.grid_layout(4)

    def test_an_empty_grid_is_refused(self):
        with pytest.raises(ValueError, match="at least one target"):
            planner.grid_layout(0)

    def test_the_grid_reports_the_basis_it_was_computed_in(self, reopened_plan):
        deck = reopened_plan["deck"]
        assert deck["basisPx"] == list(planner.DECK_BASIS_PX)
        assert deck["clickMarginPx"] == planner.CLICK_MARGIN_PX
        assert deck["neighbourClearancePx"] == planner.NEIGHBOUR_CLEARANCE_PX


# --- the record shape -------------------------------------------------------
class TestRecordShape:
    """The read-back is the shape ``generate.py --parse-oracle`` already consumes."""

    def test_the_first_line_names_the_application_and_the_driver(self):
        record = driver.application_record("16.113.1")
        assert record["record"] == "application"
        assert record["version"] == "16.113.1"
        assert record["driver"] == driver.DRIVER_NAME
        assert record["usesAppleEvents"] is False
        assert record["usesVisualBasic"] is False

    def test_a_capture_record_carries_the_key_shape_spid_effect_and_readback(self):
        target = {
            "key": "animation.gallery.entrance.flyIn",
            "slideIndex": 1,
            "guiPath": ["Animations", "Entrance Effects", "Fly In"],
        }
        record = driver.capture_record(
            target,
            applied="Animations > Entrance Effects > Fly In",
            matched_title="Fly In",
            readback={"start": "On Click", "duration": "05.00"},
            shape_name="Rounded Rectangle 1",
            shape_spid="2",
            selection_row="Rounded Rectangle 1",
            selection_row_index=150,
            effect={"spid": "2", "spids": ["2"], "cTn": {"presetID": "2", "presetClass": "entr"}},
            effect_count=(0, 1),
            steps=[{"title": "Fly In", "outcome": "pressed", "role": "AXRadioButton"}],
            saved=True,
        )
        assert record["catalogKey"] == target["key"]
        assert record["slideIndex"] == 1
        assert record["shapeName"] == "Rounded Rectangle 1"
        assert record["shapeSpid"] == "2"
        assert record["attributedSpid"] == "2"
        assert record["attributed"] is True
        assert record["effectCTn"] == {"presetID": "2", "presetClass": "entr"}
        assert record["effectCount"] == {"before": 0, "after": 1}
        # How the shape was selected, not where a pointer went. A record with no row
        # claims no mechanism, so a merged file cannot read a failed target as driven —
        # and the row INDEX is what carries that, because the name is null whenever the
        # pane did not publish one.
        assert record["selectionRow"] == "Rounded Rectangle 1"
        assert record["selectionRowIndex"] == 150
        assert record["selectedBy"] == driver.SELECTED_BY == "selectionPaneRow"
        assert "clickPoint" not in record
        assert record["ribbonReadBack"] == {"start": "On Click", "duration": "05.00"}
        assert record["rejected"] is False
        assert record["error"] is None
        assert record["resolvedBy"] == driver.RESOLVED_BY
        assert record["saved"] is True

    def test_an_effect_on_another_shape_is_never_recorded_as_attributed(self):
        record = driver.capture_record(
            {"key": "a", "slideIndex": 1, "guiPath": ["Animations", "g", "t"]},
            shape_spid="2",
            effect={"spid": "4", "spids": ["4"], "cTn": {"presetClass": "entr"}},
            effect_count=(0, 1),
        )
        assert record["shapeSpid"] == "2"
        assert record["attributedSpid"] == "4"
        assert record["attributed"] is False

    def test_a_rejected_record_keeps_its_error_and_claims_no_resolver(self):
        record = driver.capture_record(
            {"key": "animation.gallery.entrance.whip", "slideIndex": 1, "guiPath": ["Animations", "g", "Whip"]},
            rejected=True,
            error=driver.ControlNotFound("no element titled 'Whip'").as_error(),
        )
        assert record["rejected"] is True
        assert record["resolvedBy"] is None
        assert record["error"] == {"kind": "controlNotFound", "message": "no element titled 'Whip'"}
        assert record["attributed"] is False
        assert record["attributedSpid"] is None
        assert record["selectionRow"] is None
        assert record["selectedBy"] is None

    def test_a_gui_record_has_no_scripting_code_it_did_not_measure(self):
        record = driver.capture_record(
            {"key": "animation.gallery.entrance.flyIn", "slideIndex": 1, "guiPath": ["a", "b", "c"]}
        )
        assert record["code"] is None
        assert record["enum"] == driver.RECORD_ENUM
        assert record["enumerator"] == record["catalogKey"]

    def test_parse_oracle_joins_every_record_to_the_one_slide_so_records_self_attribute(self):
        """One slide means the join is per slide; the record is what is per target."""
        records = [
            driver.application_record("16.113.1"),
            driver.capture_record(
                {"key": "animation.gallery.entrance.flyIn", "slideIndex": 1,
                 "guiPath": ["Animations", "Entrance Effects", "Fly In"]},
                applied="Animations > Entrance Effects > Fly In",
                shape_name="Rounded Rectangle 1",
                shape_spid="2",
                effect={"spid": "2", "spids": ["2"], "cTn": {"presetID": "2", "presetClass": "entr"}},
                effect_count=(0, 1),
            ),
            driver.capture_record(
                {"key": "animation.gallery.entrance.fade", "slideIndex": 1,
                 "guiPath": ["Animations", "Entrance Effects", "Fade"]},
                applied="Animations > Entrance Effects > Fade",
                shape_name="Rounded Rectangle 3",
                shape_spid="4",
                effect={"spid": "4", "spids": ["4"], "cTn": {"presetID": "10", "presetClass": "entr"}},
                effect_count=(1, 2),
            ),
            driver.capture_record(
                {"key": "animation.gallery.entrance.whip", "slideIndex": 1,
                 "guiPath": ["Animations", "Entrance Effects", "Whip"]},
                rejected=True,
                error=driver.ControlNotFound("absent").as_error(),
            ),
        ]
        package = {
            "package": driver.PACKAGE_NAME,
            "slideCount": 1,
            "slides": {
                "1": {
                    "part": "ppt/slides/slide1.xml",
                    "transition": [],
                    "timing": [
                        {"element": "p:cTn", "attributes": {"presetID": "2"}, "spid": "2"},
                        {"element": "p:cTn", "attributes": {"presetID": "10"}, "spid": "4"},
                    ],
                }
            },
        }
        merged = merge_oracle_readback(records, package)
        assert merged["candidateRecords"] == 3
        # Every candidate carries the same slide-level OOXML, which is exactly why the
        # record has to say which effect in it is its own.
        assert all(candidate["slideIndex"] == 1 for candidate in merged["candidates"])
        assert len({len(candidate["ooxml"]["timing"]) for candidate in merged["candidates"]}) == 1
        by_key = {
            record["catalogKey"]: record
            for record in records
            if record.get("record") == driver.RECORD_KIND
        }
        assert by_key["animation.gallery.entrance.flyIn"]["attributedSpid"] == "2"
        assert by_key["animation.gallery.entrance.fade"]["attributedSpid"] == "4"
        assert by_key["animation.gallery.entrance.flyIn"]["effectCTn"]["presetID"] == "2"
        assert by_key["animation.gallery.entrance.fade"]["effectCTn"]["presetID"] == "10"
        # The failed target is named as unresolved rather than vanishing from the join.
        assert f"{driver.RECORD_ENUM}.animation.gallery.entrance.whip" in {
            candidate["key"] for candidate in merged["candidates"]
        }


# --- reading the package's own evidence -------------------------------------
class TestEffectAttribution:
    """Per-target evidence is read out of the saved package, by spid."""

    def test_a_generated_deck_carries_no_effects(self, built_deck):
        assert driver.read_slide_effects(built_deck["package"], 1) == []

    def test_an_effect_is_read_back_with_its_spid_and_its_own_ctn(self, built_deck, tmp_path):
        package = tmp_path / "one.pptx"
        package.write_bytes(built_deck["package"].read_bytes())
        write_effects(package, 1, {"4": ("31", "entr")})
        effects = driver.read_slide_effects(package, 1)
        assert len(effects) == 1
        assert effects[0]["spid"] == "4"
        assert effects[0]["cTn"]["presetID"] == "31"
        assert effects[0]["cTn"]["presetClass"] == "entr"
        assert effects[0]["cTn"]["nodeType"] == "clickEffect"

    def test_only_the_preset_nodes_count_as_effects(self, built_deck, tmp_path):
        """The timing tree's container and behaviour nodes are ``p:cTn`` too."""
        package = tmp_path / "two.pptx"
        package.write_bytes(built_deck["package"].read_bytes())
        write_effects(package, 1, {"2": ("2", "entr"), "4": ("10", "entr")})
        with zipfile.ZipFile(package) as archive:
            blob = archive.read("ppt/slides/slide1.xml").decode("utf-8")
        assert blob.count("<p:cTn ") == 10, "the fixture should carry more cTn nodes than effects"
        assert len(driver.read_slide_effects(package, 1)) == 2

    def test_a_missing_slide_part_is_a_named_failure(self, built_deck):
        with pytest.raises(driver.PackageEvidenceError, match="slide9"):
            driver.read_slide_effects(built_deck["package"], 9)

    def test_a_shape_carries_a_name_and_a_different_spid(self, built_deck, small_plan):
        name = built_deck["names"][small_plan["targets"][0]["key"]]
        spid = driver.read_shape_spid(built_deck["package"], 1, name)
        assert name == "Rounded Rectangle 1"
        assert spid == "2"

    def test_a_shape_the_package_does_not_have_names_the_ones_it_does(self, built_deck):
        with pytest.raises(driver.GeometryError, match="shapes present"):
            driver.read_shape_spid(built_deck["package"], 1, "no-such-shape")

    def test_one_new_effect_on_the_clicked_shape_is_attributed(self):
        before = [{"spid": "2", "spids": ["2"], "cTn": {"presetID": "2"}}]
        after = before + [{"spid": "4", "spids": ["4"], "cTn": {"presetID": "10"}}]
        effect = driver.attribute_new_effect(before, after, "4")
        assert effect["spid"] == "4"
        assert effect["cTn"]["presetID"] == "10"

    def test_a_new_effect_on_another_shape_names_both_spids(self):
        before: list[dict[str, Any]] = []
        after = [{"spid": "6", "spids": ["6"], "cTn": {"presetID": "2"}}]
        with pytest.raises(driver.EffectMisattributed) as raised:
            driver.attribute_new_effect(before, after, "2")
        message = str(raised.value)
        assert "'6'" in message and "'2'" in message

    def test_a_press_that_added_nothing_is_a_distinct_failure(self):
        before = [{"spid": "2", "spids": ["2"], "cTn": {"presetID": "2"}}]
        with pytest.raises(driver.EffectNotAdded) as raised:
            driver.attribute_new_effect(before, before, "4")
        detail = raised.value.as_error()["detail"]
        assert (detail["effectsBefore"], detail["effectsAfter"]) == (1, 1)
        assert detail["expectedSpid"] == "4"
        assert detail["appearedSpids"] == []

    def test_a_simple_failure_carries_no_detail_it_did_not_measure(self):
        assert driver.ControlNotFound("absent").as_error() == {
            "kind": "controlNotFound",
            "message": "absent",
        }

    def test_a_replaced_effect_does_not_pass_as_an_added_one(self):
        """A click on an already-animated shape replaces, so the count does not grow."""
        before = [{"spid": "2", "spids": ["2"], "cTn": {"presetID": "2"}}]
        after = [{"spid": "2", "spids": ["2"], "cTn": {"presetID": "10"}}]
        with pytest.raises(driver.EffectNotAdded):
            driver.attribute_new_effect(before, after, "4")

    def test_attribution_ignores_renumbered_timing_ids(self):
        before = [{"spid": "2", "spids": ["2"], "cTn": {"id": "5", "presetID": "2"}}]
        after = [
            {"spid": "2", "spids": ["2"], "cTn": {"id": "11", "presetID": "2"}},
            {"spid": "4", "spids": ["4"], "cTn": {"id": "15", "presetID": "10"}},
        ]
        assert driver.attribute_new_effect(before, after, "4")["spid"] == "4"

    def test_an_effect_targeting_two_shapes_attributes_to_neither(self):
        """An effect whose p:spTgt names two shapes belongs to neither target.

        ``spid`` is ``None`` for such an effect, which is not the clicked shape, so it
        counts as foreign and the record names what the package actually held.
        """
        after = [{"spid": None, "spids": ["2", "4"], "cTn": {"presetID": "2"}}]
        with pytest.raises(driver.EffectMisattributed, match=r"\['2', '4'\]"):
            driver.attribute_new_effect([], after, "2")

    def test_a_compound_value_writing_several_nodes_still_attributes(self):
        """A compound value writes more than one p:cTn, and that is not a failure.

        Measured: a run reported "0 before and 3 after, spids that appeared: ['2']" and
        rejected a target whose value had been applied to exactly the right shape. The
        count is carried so a reader knows the value is not a single node.
        """
        after = [
            {"spid": "2", "spids": ["2"], "cTn": {"presetID": "18", "presetClass": "emph"}},
            {"spid": "2", "spids": ["2"], "cTn": {"presetID": "18", "presetClass": "emph"}},
            {"spid": "2", "spids": ["2"], "cTn": {"presetID": "18", "presetClass": "emph"}},
        ]
        effect = driver.attribute_new_effect([], after, "2")
        assert effect["spid"] == "2"
        assert effect["newEffectCount"] == 3

    def test_a_compound_value_with_one_node_on_another_shape_is_still_refused(self):
        """Relaxing the count must not let a stray effect through."""
        after = [
            {"spid": "2", "spids": ["2"], "cTn": {"presetID": "18"}},
            {"spid": "2", "spids": ["2"], "cTn": {"presetID": "18"}},
            {"spid": "9", "spids": ["9"], "cTn": {"presetID": "18"}},
        ]
        with pytest.raises(driver.EffectMisattributed, match="'9'"):
            driver.attribute_new_effect([], after, "2")


# --- resume -----------------------------------------------------------------
class TestResume:
    """An output directory with records is resumed, not redone and not skipped blindly."""

    def _record(self, key: str, *, rejected: bool = False) -> dict[str, Any]:
        return driver.capture_record(
            {"key": key, "slideIndex": 1, "guiPath": ["Animations", "Entrance Effects", "X"]},
            rejected=rejected,
            error={"kind": "controlNotFound", "message": "absent"} if rejected else None,
        )

    def test_captured_keys_ignores_rejected_records(self):
        records = [self._record("a"), self._record("b", rejected=True)]
        assert driver.captured_keys(records) == {"a"}

    def test_a_captured_target_is_skipped_and_a_failed_one_is_retried(self):
        targets = [{"key": "a"}, {"key": "b"}, {"key": "c"}]
        records = [self._record("a"), self._record("b", rejected=True)]
        todo, skipped = driver.split_plan(targets, records, force=False)
        assert [target["key"] for target in todo] == ["b", "c"]
        assert skipped == ["a"]

    def test_force_reruns_everything(self):
        targets = [{"key": "a"}, {"key": "b"}]
        todo, skipped = driver.split_plan(targets, [self._record("a")], force=True)
        assert [target["key"] for target in todo] == ["a", "b"]
        assert skipped == []

    def test_retained_records_drop_only_the_targets_being_rerun(self):
        records = [self._record("a"), self._record("b"), {"record": "application"}]
        kept = driver.retained_records(records, [{"key": "b"}])
        assert [record["catalogKey"] for record in kept] == ["a"]

    def test_reading_a_readback_file_keeps_an_unparsable_line_visible(self, tmp_path):
        path = tmp_path / driver.READBACK_NAME
        path.write_text('{"record":"application"}\nnot json\n', encoding="utf-8")
        records = driver.read_records(path)
        assert records[0]["record"] == "application"
        assert records[1]["record"] == "unparsed" and records[1]["line"] == 2

    def test_a_second_run_leaves_exactly_one_record_per_key(self, session):
        first = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert first["captured"] == 3
        second = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert second["attempted"] == 0
        assert second["skippedAlreadyCaptured"] == 3
        records = [
            record
            for record in driver.read_records(session["settings"].readback_path)
            if record.get("record") == driver.RECORD_KIND
        ]
        keys = [record["catalogKey"] for record in records]
        assert len(keys) == len(set(keys)) == 3

    def test_force_against_an_already_captured_deck_rejects_rather_than_crediting(self, session):
        """A re-press replaces the shape's effect, so the attribution gate cannot pass.

        This is the cost of making the evidence per target: ``--force`` wants a freshly
        generated deck. Crediting the target anyway would be reporting the *previous*
        run's effect as this run's.
        """
        first = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert first["captured"] == 3
        session["settings"].force = True
        forced = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert forced["attempted"] == 3
        assert forced["captured"] == 0
        assert {failure["error"]["kind"] for failure in forced["failures"]} == {"effectNotAdded"}
        records = [
            record
            for record in driver.read_records(session["settings"].readback_path)
            if record.get("record") == driver.RECORD_KIND
        ]
        assert len(records) == 3, "one record per key, rewritten rather than appended"

    def test_a_resumed_run_rewrites_the_header_and_keeps_the_prior_records(self, session):
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        lines = session["settings"].readback_path.read_text(encoding="utf-8").strip().splitlines()
        assert json.loads(lines[0])["record"] == "application"
        assert summary["retainedRecords"] == 3


# --- failure recording ------------------------------------------------------
class TestFailureRecording:
    """One bad target costs one record. This is the lesson of the 2026-10-31 runs."""

    def test_a_missing_control_is_recorded_and_the_run_continues(self, session):
        session["plan"]["targets"][1]["guiPath"][-1] = "No Such Tile"
        session["plan"]["targets"][1]["titleAlternatives"] = []
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert summary["attempted"] == 3
        assert summary["captured"] == 2
        assert summary["failed"] == 1
        assert summary["failures"][0]["error"]["kind"] == "controlNotFound"
        # The target after the failure still ran, on its own shape.
        lines_spid = session["spids"]["animation.gallery.motionPath.lines"]
        assert ("Lines", lines_spid) in session["fake"].presses

    def test_every_attempted_target_has_a_record_even_when_it_failed(self, session):
        session["plan"]["targets"][0]["guiPath"][-1] = "No Such Tile"
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        records = [
            record
            for record in driver.read_records(session["settings"].readback_path)
            if record.get("record") == driver.RECORD_KIND
        ]
        assert len(records) == 3
        assert sum(record["rejected"] for record in records) == 1

    def test_an_ambiguous_control_is_refused_rather_than_guessed(self, session):
        session["fake"].duplicate_tile = "Fly In"
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        failures = {failure["key"]: failure["error"] for failure in summary["failures"]}
        assert failures["animation.gallery.entrance.flyIn"]["kind"] == "ambiguousControl"
        assert not any(title == "Fly In" for title, _spid in session["fake"].presses)

    def test_a_press_that_applies_nothing_is_recorded_not_credited(self, session):
        """The gallery press lands but PowerPoint attaches no effect."""
        session["fake"].applies_effect = False
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert summary["failed"] == 3
        assert summary["captured"] == 0
        assert {failure["error"]["kind"] for failure in summary["failures"]} == {"effectNotAdded"}
        # The gate is "at least one new effect", not "exactly one" — a compound value
        # writes several p:cTn nodes — so what it reports here is that none appeared.
        assert "no new effect appeared" in summary["failures"][0]["error"]["message"]
        # The presses did happen; what failed is the evidence, and it says so.
        assert len(session["fake"].presses) == 3

    def test_an_effect_that_lands_on_another_shape_is_rejected_naming_both_spids(self, session):
        """A press whose effect belongs to another shape is refused, naming both spids.

        The Selection Pane cannot put the effect on a neighbour by a few points of aim —
        which is the whole reason it replaced the click — and a row that did not take is
        caught by the read-back before anything is pressed. So what is injected here is
        the one case left: the pane reports the right row and PowerPoint animates another
        shape. The gate has to catch that, because it is the only thing standing between
        a wrong press and a correctly-labelled catalog entry.

        Driven at ``--batch-size 1``, and that is a statement about batching rather than
        a convenience. What is injected here is a **rotation**: every target's effect
        lands on the next target's shape. With one save per target the gate sees one
        press put an effect on a shape this target did not select and refuses it. With
        one save per batch every spid in the batch gained exactly one effect and none
        outside it gained anything, so the package cannot say whose value is whose — a
        rotation confined to a batch is the one thing batching cannot separate, which is
        why the per-target save is still reachable and why
        ``test_a_stray_spid_fails_the_whole_batch_naming_it`` covers the case that leaves
        the batch, where the gate still bites.
        """
        fake = session["fake"]
        targets = session["plan"]["targets"]
        session["settings"].batch_size = 1
        names = [target["shapeName"] for target in targets]
        fake.applies_to_instead = {name: names[(index + 1) % len(names)] for index, name in enumerate(names)}
        summary = driver.run_capture(session["plan"], session["settings"], fake, version="16.113.1")
        assert summary["captured"] == 0
        assert summary["attributed"] == 0
        failure = next(f for f in summary["failures"] if f["key"] == targets[0]["key"])
        assert failure["error"]["kind"] == "effectMisattributed"
        own = session["spids"][targets[0]["key"]]
        neighbour = session["spids"][targets[1]["key"]]
        assert own != neighbour
        assert f"{neighbour!r}" in failure["error"]["message"]
        assert f"{own!r}" in failure["error"]["message"]
        assert failure["shapeSpid"] == own
        # Named as data as well as prose, so the evidence can be queried.
        assert failure["error"]["detail"]["attributedSpid"] == neighbour
        assert failure["error"]["detail"]["expectedSpid"] == own
        # Nothing was attributed to this target, so the record claims nothing.
        assert failure["attributedSpid"] is None
        records = [
            record
            for record in driver.read_records(session["settings"].readback_path)
            if record.get("record") == driver.RECORD_KIND
        ]
        assert all(record["attributed"] is False for record in records)

    def test_a_selection_that_does_not_take_is_a_bounded_timeout_before_any_press(self, session):
        """The write is accepted and the row never reads back selected.

        This is the Selection Pane's version of the failure that killed the click: the
        action appears to succeed and the shape is not selected. The read-back is what
        turns it into a recorded timeout **before** a press, rather than a press that
        replaces some other shape's effect — which is how the click version lost ten of
        twelve targets to ``effectNotAdded``.
        """
        session["fake"].selection_sticks = False
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert summary["failed"] == 3
        assert {failure["error"]["kind"] for failure in summary["failures"]} == {"timeout"}
        assert session["fake"].presses == []
        assert session["fake"].selections, "the driver did try to select each row"

    def test_a_renumbered_pane_fails_rather_than_pressing_the_wrong_shape(self, session):
        """A pane missing one row renumbers the rest, and the name check catches it.

        This is the failure the name is still kept for. A row index comes from the
        slide's shape order, so a pane short one row has every row below it renumbered:
        the row at a target's index is then a **different shape**. Selecting it and
        pressing would apply the value to that shape under this target's key, which no
        later gate can undo — so the row's own published name is compared against the
        name expected at that index, and a mismatch is a refusal.

        What is asserted is the property, not a count: no press ever lands on a shape
        other than the one its target names, and every captured record is attributed.
        """
        fake = session["fake"]
        targets = session["plan"]["targets"]
        fake.missing_rows = {targets[1]["shapeName"]}
        summary = driver.run_capture(session["plan"], session["settings"], fake, version="16.113.1")
        assert summary["failed"] >= 1, "a renumbered pane cannot serve every target"
        for failure in summary["failures"]:
            assert failure["error"]["kind"] == "controlNotFound"
            message = failure["error"]["message"]
            # Either the row at that index publishes another shape's name, or — for a
            # target near the end of the pane — the index is now past the last row.
            assert "rather than" in message or "never published" in message
        records = [
            record
            for record in driver.read_records(session["settings"].readback_path)
            if record.get("record") == driver.RECORD_KIND and not record["rejected"]
        ]
        assert len(records) == summary["captured"]
        for record in records:
            assert record["attributed"], "a captured record is attributed or it is not a capture"
        intended = {
            (target["guiPath"][-1], session["spids"][target["key"]]) for target in targets
        }
        assert set(fake.presses) <= intended, "a press landed on a shape its target did not name"

    def test_two_rows_claiming_one_index_are_refused_rather_than_chosen_between(self, session):
        """Ambiguity is a refusal, as it was when rows were addressed by name."""
        fake = session["fake"]
        name = session["plan"]["targets"][0]["shapeName"]
        row_index, row_count = driver.shape_row_index(session["settings"].document, 1, name)
        fake.duplicate_index = row_index
        fake.selection_pane_open = True
        with pytest.raises(driver.AmbiguousControl, match=f"index {row_index}"):
            driver.select_shape(fake, name, row_index=row_index, row_count=row_count, timeout=2.0)
        assert fake.selections == [], "no row was selected"
        assert fake.slept == 0.0, "ambiguity failed at once rather than being polled"

    def test_an_extra_row_beyond_the_slides_shapes_does_not_stop_a_capture(self, session):
        """A row the slide has no shape for is harmless, because an index identifies.

        The by-name version refused the whole target here, since two rows carried one
        name. A row is now found by the index it reports, so a stray row at the end of
        the pane changes nothing — and that is worth pinning, because it is the ordinary
        case of a pane that is not exactly the slide's shape list.
        """
        fake = session["fake"]
        fake.duplicate_row = session["plan"]["targets"][0]["shapeName"]
        summary = driver.run_capture(session["plan"], session["settings"], fake, version="16.113.1")
        assert (summary["captured"], summary["failed"]) == (len(session["plan"]["targets"]), 0)

    def test_a_press_that_the_application_refuses_is_recorded(self, session, monkeypatch):
        original = FakePowerPoint._gallery

        def refusing(self):
            node = original(self)
            for child in node.children:
                child.press_error = "AXPress on 'Fly In' failed with AX error -25205"
            return node

        monkeypatch.setattr(FakePowerPoint, "_gallery", refusing)
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert summary["failed"] == 2
        assert all("AX error" in failure["error"]["message"] for failure in summary["failures"])

    def test_a_save_that_never_lands_is_rejected_because_it_is_the_evidence(self, session, monkeypatch):
        monkeypatch.setattr(FakePowerPoint, "_save", lambda self: setattr(self, "saves", self.saves + 1))
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert summary["failed"] == 3
        assert summary["saveFailures"] == 3
        records = [
            record
            for record in driver.read_records(session["settings"].readback_path)
            if record.get("record") == driver.RECORD_KIND
        ]
        assert all(record["saveError"] and record["rejected"] for record in records)
        assert all(record["attributedSpid"] is None for record in records)

    def test_wait_until_is_bounded_and_reports_what_it_waited_for(self, session):
        fake = session["fake"]
        with pytest.raises(driver.DriverTimeout, match="the gallery"):
            driver.wait_until(fake, lambda: None, timeout=1.0, what="the gallery")
        assert fake.slept >= 1.0

    def test_the_only_unbounded_loop_in_the_driver_is_the_bounded_wait(self):
        """No `while True` anywhere but inside ``wait_until``, which has a deadline."""
        tree = ast.parse(DRIVER_SOURCE.read_text(encoding="utf-8"))
        owners = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.While) and isinstance(inner.test, ast.Constant) and inner.test.value:
                    owners.append(node.name)
        assert owners == ["wait_until"], f"unbounded loops in {owners}"

    def test_a_tree_scan_that_overruns_is_an_error_not_a_miss(self):
        deep = FakeNode(role="AXGroup", title="deep")
        node = deep
        for _ in range(10):
            child = FakeNode(role="AXGroup")
            node.children.append(child)
            node = child
        with pytest.raises(driver.TreeTooLarge):
            list(driver.walk(deep, max_nodes=3))


# --- slide navigation is gone ----------------------------------------------
class TestSlideNavigationIsGone:
    """The 2026-10-31 live run rejected 76 of 76 targets inside slide selection."""

    def test_the_driver_defines_no_slide_selection_or_thumbnail_lookup(self):
        tree = ast.parse(DRIVER_SOURCE.read_text(encoding="utf-8"))
        defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        forbidden = {"select_slide", "slide_thumbnail", "thumbnail_cells", "thumbnail_label", "has_animation"}
        assert not defined & forbidden, f"slide navigation is back: {sorted(defined & forbidden)}"

    def test_the_driver_selects_no_slide_and_reads_no_thumbnail_state(self):
        source = DRIVER_SOURCE.read_text(encoding="utf-8")
        assert "HAS_ANIMATION" not in source
        assert not hasattr(driver, "HAS_ANIMATION")
        assert not hasattr(driver, "select_slide")

    def test_the_only_attribute_the_driver_writes_is_a_rows_selection(self):
        """``kAXSelectedAttribute`` is back, on outline rows, and nowhere else.

        It never read back true on the navigator's cells, which is why slide selection is
        gone; it does take on a Selection Pane row, which is a different element with a
        different mechanism. The narrow method is the guard: there is no "set any
        attribute" escape hatch to reach for the next time something looks selectable.
        """
        tree = ast.parse(DRIVER_SOURCE.read_text(encoding="utf-8"))
        owners = {
            function.name
            for function in ast.walk(tree)
            if isinstance(function, ast.FunctionDef)
            for node in ast.walk(function)
            if isinstance(node, ast.Attribute) and node.attr == "kAXSelectedAttribute"
        }
        assert owners == {"selected", "set_selected"}, owners
        setters = {
            function.name
            for function in ast.walk(tree)
            if isinstance(function, ast.FunctionDef)
            for node in ast.walk(function)
            if isinstance(node, ast.Attribute) and node.attr == "AXUIElementSetAttributeValue"
        }
        assert setters == {"set_selected"}, setters
        assert not hasattr(driver.LiveAXNode, "set_attribute")

    def test_the_module_docstring_records_both_live_failures(self):
        doc = driver.__doc__ or ""
        assert "76 records, 0 captured, 76 rejected" in doc
        assert "no actions at all" in doc, "the unselectable navigator cells are not recorded"
        assert "scrolled into view" in doc, "the 6-visible-cells limit is not recorded"
        assert "Do not reintroduce" in doc


# --- the canvas click is gone too ------------------------------------------
class TestTheCanvasClickIsGone:
    """The click captured 2 of 12. Nothing here may grow a coordinate back."""

    #: Every name the click path owned. The module docstring names them as deleted, so
    #: this is what makes that claim true rather than a note.
    CLICK_PATH_NAMES = (
        "read_canvas_geometry",
        "canvas_point",
        "read_shape_center_pt",
        "parse_zoom",
        "parse_pane_frame",
        "window_frame_to_screen",
        "read_slide_size_pt",
        "emu_to_points",
        "CanvasGeometry",
        "Frame",
    )

    def test_the_driver_defines_none_of_the_click_paths_names(self):
        tree = ast.parse(DRIVER_SOURCE.read_text(encoding="utf-8"))
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        back = sorted(set(self.CLICK_PATH_NAMES) & defined)
        assert not back, f"the coordinate click path is back: {back}"
        assert not [name for name in self.CLICK_PATH_NAMES if hasattr(driver, name)]

    def test_the_driver_posts_no_mouse_events_and_needs_no_frames(self):
        """Checked against the names the code *uses*, not against the prose.

        The docstrings say what was deleted and why, which means they name
        ``CGEventPost``; a text search would read that as the code being back.
        """
        tree = ast.parse(DRIVER_SOURCE.read_text(encoding="utf-8"))
        used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)} | {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        forbidden = {
            name
            for name in used
            if name.startswith(("CGEvent", "kCGMouse", "kCGEvent"))
            or name in {"kAXPositionAttribute", "kAXSizeAttribute", "AXValueGetValue"}
        }
        assert not forbidden, f"the driver uses mouse or geometry bindings again: {sorted(forbidden)}"
        assert not hasattr(driver.AXBackend, "click")
        assert not hasattr(driver.LiveAXBackend, "click")
        # The protocols themselves, so a reintroduced click would have to re-declare the
        # host contract rather than quietly use a reader that was left lying around.
        assert not hasattr(driver.AXNode, "frame")
        assert not hasattr(driver.LiveAXNode, "frame")
        assert sorted(driver.AXNode.__protocol_attrs__) == [
            "children",
            "enabled",
            "index",
            "press",
            "role",
            "selected",
            "set_selected",
            "title",
            "value",
        ]

    def test_the_module_docstring_records_what_the_click_was_worth(self):
        doc = driver.__doc__ or ""
        assert "2 of 12" in doc, "the figure that ended the click is not recorded"
        assert "Do not reintroduce a\ncoordinate click" in doc
        for name in ("read_canvas_geometry", "canvas_point", "parse_zoom", "--pane-frame"):
            assert name in doc, f"the docstring does not say {name} is gone"

    def test_the_cli_offers_no_coordinate_overrides(self):
        help_text = driver.build_parser().format_help()
        for gone in ("--pane-frame", "--pane-role", "--zoom"):
            assert gone not in help_text, f"{gone} is back"
        assert "never moves the pointer" in help_text
        settings = driver.CaptureSettings(out_dir=Path("."), document=Path("."))
        for gone in ("pane", "pane_role", "zoom"):
            assert not hasattr(settings, gone), gone

    def test_the_fake_powerpoint_has_no_navigator_to_fall_back_on(self, session):
        """No navigator cells — and the outline that *is* there is the Selection Pane.

        This assertion used to be "no ``AXRow``, ``AXCell`` or ``AXOutline`` anywhere",
        which was a fair statement of the tree while nothing was selected by attribute.
        The Selection Pane is an ``AXOutline`` of ``AXRow``s, so the check is now the
        narrower thing it was always for: no navigator, which means no cells and no
        element titled like a thumbnail.
        """
        fake = session["fake"]
        fake.selection_pane_open = True
        window = driver.document_window(fake)
        nodes = list(driver.walk(window))
        assert not any(node.role == "AXCell" for node in nodes)
        assert not any(re.match(r"Slide \d+ of \d+ Slides", node.title or "") for node in nodes)
        outlines = [node for node in nodes if node.role == driver.SELECTION_PANE_ROLE]
        assert len(outlines) == 1, "the only outline in the tree is the Selection Pane"
        assert all(row.role == driver.SELECTION_ROW_ROLE for row in outlines[0].children)


# --- the Selection Pane -----------------------------------------------------
class TestSelectionPane:
    """A shape is selected by name, through its Selection Pane row."""

    def test_the_pane_is_opened_once_per_run_and_not_once_per_target(self, session):
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert summary["attempted"] == 3
        assert session["fake"].selection_pane_presses == 1
        assert session["fake"].selection_pane_open is True
        assert summary["shapeSelection"] == {
            "mechanism": driver.SELECTED_BY,
            "selectionPane": "pressed",
        }

    def test_an_already_open_pane_is_not_pressed_again(self, session):
        """Pressing an active control toggles it, and that trap has been paid for once.

        Pressing an already-selected ribbon tab collapsed the ribbon and failed all 76
        targets of a live run. Pressing ``Selection Pane...`` with the pane open closes
        it, which would take every row out of the tree, so the pane's presence is read
        rather than remembered.
        """
        session["fake"].selection_pane_open = True
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert session["fake"].selection_pane_presses == 0
        assert session["fake"].selection_pane_open is True
        assert summary["shapeSelection"]["selectionPane"] == "alreadyOpen"
        assert summary["captured"] == 3

    def test_pressing_the_item_twice_would_close_the_pane_so_the_fake_says_so(self, session):
        """The fake really does toggle, so "open once" is a property, not a convention."""
        fake = session["fake"]
        driver.open_selection_pane(fake, timeout=2.0)
        assert fake.selection_pane_open is True
        fake._press_selection_pane_item()
        assert fake.selection_pane_open is False
        with pytest.raises(driver.ControlNotFound, match="not open"):
            driver.selection_outline(fake)

    def test_the_pane_is_opened_through_home_arrange_by_title(self, session):
        """The path is walked, not assumed: Home, then the Arrange window, then the item."""
        fake = session["fake"]
        assert driver.SELECTION_PANE_PATH == ("Home", "Arrange", "Selection Pane...")
        fake.active_tab = planner.ANIMATIONS_TAB
        assert driver.open_selection_pane(fake, timeout=2.0) == "pressed"
        assert fake.active_tab == "Home", "Arrange lives on Home, so the tab is pressed"
        assert fake.arrange_open is False, "the Arrange window closes behind the press"
        assert driver.open_selection_pane(fake, timeout=2.0) == "alreadyOpen"

    def test_a_pane_that_never_opens_refuses_the_whole_run_rather_than_every_target(self, session):
        """No pane means no way to select a shape, so it is a refusal, not 76 records."""
        monkey = session["fake"]
        monkey._press_selection_pane_item = lambda: None
        with pytest.raises(driver.DriverRefusal, match="Selection Pane"):
            driver.run_capture(session["plan"], session["settings"], monkey)
        assert monkey.presses == []

    def test_a_row_is_named_by_a_descendant_static_text_not_by_its_title(self, session):
        fake = session["fake"]
        fake.selection_pane_open = True
        rows = driver.selection_rows(fake)
        assert rows, "the pane publishes rows"
        for row in rows:
            assert row.node.title is None, "a live row carries no title"
            assert row.names, "and its name is a descendant static text's value"
        assert driver.row_names(rows[0].node) == [rows[0].names[0]]

    def test_the_rows_are_in_reverse_z_order_and_carry_the_labels_too(self, session, built_deck):
        """Reverse z-order, one row per shape and one per label — as measured.

        The live pane held 153 rows for a 76-target deck: 76 shapes, 76 labels and one
        more. The order is what :func:`gui_capture.shape_row_index` derives an index
        from, and it was verified against the live pane twice at 152 rows with 0
        mismatches; here it is verified against the package the fake was built from.
        """
        fake = session["fake"]
        fake.selection_pane_open = True
        names = [name for row in driver.selection_rows(fake) for name in row.names]
        z_order = [name for name, _spid in shape_names_in_z_order(session["settings"].document, 1)]
        assert names == list(reversed(z_order))
        targets = {target["shapeName"] for target in session["plan"]["targets"]}
        assert targets < set(names), "the pane names more than the target shapes"
        assert len(names) == 2 * len(targets), "one row per shape and one per label"
        # The live pane's head alternated label, shape, label. The fake's does too, so
        # "every other row is a target" is not a shortcut an index could be derived from.
        kinds = [name.split()[0] for name in names[: len(MEASURED_PANE_HEAD)]]
        assert kinds == [name.split()[0] for name in MEASURED_PANE_HEAD]

    def test_a_row_index_is_read_from_the_package_and_matches_the_pane(self, session):
        """Every shape's derived index addresses the row the pane publishes for it.

        This is the agreement the whole mechanism rests on, and it is checked for all 152
        rows live and for every row here rather than for the targets alone.
        """
        fake = session["fake"]
        fake.selection_pane_open = True
        document = session["settings"].document
        rows = driver.selection_rows(fake)
        by_index = {row.index: row for row in rows}
        for name, _spid in shape_names_in_z_order(document, 1):
            row_index, row_count = driver.shape_row_index(document, 1, name)
            assert row_count == len(rows)
            assert by_index[row_index].names == [name]

    def test_selecting_by_index_is_what_makes_the_right_shape_get_the_effect(self, session):
        """Each press lands on the shape whose row was selected, and only that one."""
        fake = session["fake"]
        driver.open_selection_pane(fake, timeout=2.0)
        target = session["plan"]["targets"][1]
        name = target["shapeName"]
        row_index, row_count = driver.shape_row_index(session["settings"].document, 1, name)
        selection = driver.select_shape(
            fake, name, row_index=row_index, row_count=row_count, timeout=2.0
        )
        assert selection == driver.RowSelection(row_index, name)
        assert fake.selected_name == name
        assert fake.selected_spid == session["spids"][target["key"]]
        driver.ensure_tab(fake, [planner.ANIMATIONS_TAB, "Entrance Effects"], timeout=2.0)
        driver.press_path(fake, [planner.ANIMATIONS_TAB, "Entrance Effects", "Fade"], timeout=2.0)
        assert fake.effects == {fake.selected_spid: TILE_PRESETS["Fade"]}

    def test_a_row_that_publishes_no_name_is_still_selected_by_index(self, session):
        """The failure index addressing exists for: a row with nothing to match on.

        Live, a row that has never been scrolled into view publishes no
        ``AXStaticText``, so there is no name to look it up by — and one run's batches
        read 80 names, then 54, from the same 152 rows, rejecting 11 targets that were
        selectable the whole time. Here **no** row publishes a name and the whole plan
        still captures; the records say so by carrying a row index and a null row name.
        """
        session["fake"].named_row_count = 0
        summary = driver.run_capture(
            session["plan"], session["settings"], session["fake"], version="16.113.1"
        )
        assert (summary["captured"], summary["failed"]) == (len(session["plan"]["targets"]), 0)
        records = [
            record
            for record in driver.read_records(session["settings"].readback_path)
            if record.get("record") == driver.RECORD_KIND
        ]
        for record in records:
            assert record["selectionRow"] is None, "the pane published no name to record"
            assert record["selectionRowIndex"] is not None
            assert record["selectedBy"] == driver.SELECTED_BY
            assert record["attributed"], "and the effect still landed on the right spid"

    def test_a_row_is_resolved_from_a_fresh_read_every_time(self, session):
        """Rows are rebuilt between reads, so a held element would be stale.

        Counted rather than asserted structurally: selecting one shape costs more reads
        than one, because the row is resolved once to write the attribute and again to
        confirm it. A driver holding the row across those two would read fewer.
        """
        fake = session["fake"]
        driver.open_selection_pane(fake, timeout=2.0)
        name = session["plan"]["targets"][0]["shapeName"]
        row_index, row_count = driver.shape_row_index(session["settings"].document, 1, name)
        before = fake.reads
        driver.select_shape(fake, name, row_index=row_index, row_count=row_count, timeout=2.0)
        assert fake.reads - before >= 2

    def test_a_part_built_pane_is_retried_rather_than_refused(self, session):
        """``AXRows`` publishes a prefix that grows, so an absent row is "not yet".

        Measured live: the same 152-shape pane published 43, 54, 61, 63, 74, 88 and 91
        rows on consecutive reads while the application worked. An index-addressed lookup
        that refused the first read it did not find the row in rejected 7 targets for
        rows that appeared moments later.
        """
        fake = session["fake"]
        fake.selection_pane_open = True
        name = session["plan"]["targets"][0]["shapeName"]
        row_index, row_count = driver.shape_row_index(session["settings"].document, 1, name)
        fake.published_row_count = row_index  # one short of the row wanted
        fake.partial_reads = 2
        selection = driver.select_shape(
            fake, name, row_index=row_index, row_count=row_count, timeout=2.0
        )
        assert selection == driver.RowSelection(row_index, name)
        assert fake.slept > 0.0, "it waited rather than finding the row first time"

    def test_a_row_that_is_never_published_is_a_bounded_failure_naming_the_read(self, session):
        """The retry is bounded, and what it reports is the read rather than a guess."""
        fake = session["fake"]
        fake.selection_pane_open = True
        name = session["plan"]["targets"][0]["shapeName"]
        row_index, row_count = driver.shape_row_index(session["settings"].document, 1, name)
        fake.published_row_count = row_index
        with pytest.raises(driver.ControlNotFound) as raised:
            driver.select_shape(fake, name, row_index=row_index, row_count=row_count, timeout=2.0)
        message = str(raised.value)
        assert f"row {row_index} of {row_count}" in message
        assert f"published {row_index} rows" in message
        assert f"indices 0..{row_index - 1}" in message
        assert fake.selections == [], "nothing was selected"

    def test_a_row_whose_name_contradicts_its_index_fails_loudly(self, session):
        """The name is a check on the order, which is the one thing it is still good for.

        A pane in some other order than reverse z-order would otherwise be discovered
        only in the attribution, one target late, with a value already applied.
        """
        fake = session["fake"]
        fake.selection_pane_open = True
        name = session["plan"]["targets"][0]["shapeName"]
        row_index, row_count = driver.shape_row_index(session["settings"].document, 1, name)
        fake._shapes = list(reversed(fake._shapes))
        with pytest.raises(driver.ControlNotFound, match="reverse z-order"):
            driver.select_shape(fake, name, row_index=row_index, row_count=row_count, timeout=2.0)
        assert fake.selections == []

    def test_a_long_pane_reports_its_shape_rather_than_every_name_it_holds(self, session):
        """A failure says how many rows and which indices, not 153 names.

        The by-name version listed the names the pane did show, truncated to twelve,
        because a name was the key and the operator needed to see what was there
        instead. An index needs the read's **shape**: how many rows and what range of
        indices. That is three numbers rather than a list, and it says the one thing the
        operator can act on — whether the row is missing or the pane is part-built.
        """
        fake = session["fake"]
        fake._shapes = [(f"Shape {index}", str(index + 2)) for index in range(40)]
        fake._spids = dict(fake._shapes)
        fake.selection_pane_open = True
        with pytest.raises(driver.ControlNotFound) as raised:
            driver.select_shape(fake, "Shape 0", row_index=140, row_count=152, timeout=2.0)
        message = str(raised.value)
        assert "row 140 of 152" in message
        assert "published 40 rows" in message and "indices 0..39" in message
        assert re.findall(r"'Shape \d+'", message) == ["'Shape 0'"], (
            "the only name in the message is the one that was expected, not the pane's"
        )

    def test_a_closed_pane_is_a_named_failure_rather_than_an_empty_row_list(self, session):
        with pytest.raises(driver.ControlNotFound, match="Selection Pane is not open"):
            driver.selection_outline(session["fake"])

    def test_the_summary_says_how_every_shape_was_selected(self, session):
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert "canvas" not in summary, "there is no canvas mapping to report"
        assert summary["shapeSelection"]["mechanism"] == "selectionPaneRow"
        records = [
            record
            for record in driver.read_records(session["settings"].readback_path)
            if record.get("record") == driver.RECORD_KIND
        ]
        document = session["settings"].document
        for record in records:
            assert record["selectionRow"] == record["shapeName"]
            assert record["selectedBy"] == driver.SELECTED_BY
            expected, _count = driver.shape_row_index(document, 1, record["shapeName"])
            assert record["selectionRowIndex"] == expected


# --- consent and refusal ----------------------------------------------------
class TestConsentAndRefusal:
    """It cannot be started by accident, and it cannot type into the operator's work."""

    def test_without_the_consent_argument_nothing_is_driven(self, tmp_path, capsys):
        plan = tmp_path / "plan.json"
        plan.write_text("{}", encoding="utf-8")
        document = tmp_path / "deck.pptx"
        document.write_bytes(b"x")
        code = driver.main(["--plan", str(plan), "--out", str(tmp_path), "--document", str(document)])
        assert code == 2
        assert driver.DRIVE_TOKEN in capsys.readouterr().err

    def test_the_consent_argument_is_not_the_scripting_oracles(self):
        """Two mechanisms, two tokens, and neither file may name the other's.

        The oracle's token is imported rather than retyped, both because duplicating it
        would be drift waiting to happen and because ``test_animation_catalog.py`` pins
        the exact set of files allowed to contain it — a set this module is not in.
        """
        assert driver.DRIVE_TOKEN == "--drive-powerpoint"
        assert driver.DRIVE_TOKEN != ORACLE_RUN_TOKEN
        assert ORACLE_RUN_TOKEN not in DRIVER_SOURCE.read_text(encoding="utf-8")

    def test_only_this_driver_its_docs_and_this_test_mention_the_token(self):
        allowed = {
            "scripts/animation_catalog/gui_capture.py",
            "scripts/animation_catalog/gui_capture_plan.py",
            # The discovery passes drive PowerPoint too — they apply a tile and
            # open a window — so they gate on the same token rather than on one
            # of their own. A second token would be a second thing to remember.
            "scripts/animation_catalog/discover_effect_options.py",
            "scripts/animation_catalog/discover_platform_inventory.py",
            "scripts/animation_catalog/README.md",
            "scripts/animation_catalog/computer-use.md",
            "tests/fixtures/animations/gui-only/effect-options-2026-11-01/README.md",
            "tests/test_animation_gui_capture.py",
        }
        suffixes = {".py", ".md", ".yml", ".yaml", ".sh", ".json", ".applescript", ".toml"}
        roots = ["scripts", "sdpm", "servers", "agent", "api", "shared", "tests", ".github"]
        users = set()
        for root in roots:
            for path in (REPO_ROOT / root).rglob("*"):
                if not path.is_file() or "__pycache__" in path.parts or path.suffix not in suffixes:
                    continue
                if driver.DRIVE_TOKEN in path.read_text(encoding="utf-8", errors="ignore"):
                    users.add(path.relative_to(REPO_ROOT).as_posix())
        assert users <= allowed, f"unexpected callers of {driver.DRIVE_TOKEN}: {users - allowed}"

    def test_it_refuses_without_the_accessibility_grant(self, session):
        session["fake"].trusted_flag = False
        with pytest.raises(driver.DriverRefusal, match="Accessibility"):
            driver.run_capture(session["plan"], session["settings"], session["fake"])
        assert session["fake"].presses == []

    def test_it_runs_while_another_application_is_frontmost(self, session):
        """A run does not need the operator's screen, and this test inverted.

        It used to require PowerPoint to be frontmost and assert the refusal.
        Every action here is an accessibility press or attribute write addressed
        to a named element, so it reaches an occluded window and takes no focus
        — which is why the driver posts no mouse events at all. Requiring
        frontmost bought nothing the document check does not already cover, and
        it cost two things that matter for a long run: it could not be started
        without taking the screen, and any app coming forward mid-run aborted it.

        What still guards the operator's own work is the **document** check
        below: the deck being driven has to be the capture deck.
        """
        session["fake"].frontmost = "com.apple.Terminal"
        summary = driver.run_capture(
            session["plan"], session["settings"], session["fake"], version="16.113.1"
        )
        assert summary["captured"] == len(session["plan"]["targets"])
        assert session["fake"].presses, "it drove PowerPoint from the background"

    def test_it_refuses_a_document_that_is_not_the_capture_deck(self, session):
        session["fake"].document_title = "Q3 Business Review"
        with pytest.raises(driver.DriverRefusal, match="not the expected capture deck"):
            driver.run_capture(session["plan"], session["settings"], session["fake"])
        assert (session["fake"].selections, session["fake"].presses) == ([], [])

    def test_the_expected_title_tolerates_the_extension_but_not_a_different_deck(self):
        assert driver.normalise_document_title("capture-deck.pptx") == "capture-deck"
        assert driver.normalise_document_title(" capture-deck ") == "capture-deck"
        assert driver.normalise_document_title("other") != "capture-deck"

    def test_the_record_schema_prints_without_touching_anything(self, capsys):
        assert driver.main(["--emit-record-schema"]) == 0
        printed = json.loads(capsys.readouterr().out)
        assert printed["application"]["driver"] == driver.DRIVER_NAME
        assert printed["capture"]["catalogKey"]
        assert "attributedSpid" in printed["capture"]

    def test_a_target_without_a_shape_name_refuses_the_run_rather_than_assuming_one(self, session):
        session["plan"]["shapeNames"] = {}
        session["plan"]["targets"][1]["shapeName"] = None
        with pytest.raises(driver.DriverRefusal, match="no shapeName"):
            driver.run_capture(session["plan"], session["settings"], session["fake"])
        assert (session["fake"].selections, session["fake"].presses) == ([], [])

    def test_the_cli_refuses_a_plan_whose_shape_names_are_unsettled(self, tmp_path, capsys):
        plan = tmp_path / "plan.json"
        plan.write_text(
            json.dumps({"shapeNames": {}, "targets": [{"key": "a", "slideIndex": 1, "guiPath": ["x", "y"]}]}),
            encoding="utf-8",
        )
        document = tmp_path / "deck.pptx"
        document.write_bytes(b"x")
        code = driver.main(
            ["--plan", str(plan), "--out", str(tmp_path), "--document", str(document), driver.DRIVE_TOKEN]
        )
        assert code == 2
        assert "shapeName" in capsys.readouterr().err

    def test_a_plan_whose_two_shape_name_sources_disagree_refuses(self, session):
        key = session["plan"]["targets"][0]["key"]
        session["plan"]["shapeNames"][key] = "Rounded Rectangle 999"
        with pytest.raises(driver.DriverRefusal, match="disagrees"):
            driver.run_capture(session["plan"], session["settings"], session["fake"])

    def test_there_is_no_way_to_run_without_the_per_target_save(self):
        """The save is the measurement now, so the switch that skipped it is gone."""
        help_text = driver.build_parser().format_help()
        assert "--no-save" not in help_text
        assert not hasattr(driver.CaptureSettings(out_dir=Path("."), document=Path(".")), "save_each")


# --- no accessibility dependency in CI --------------------------------------
class TestNoAccessibilityDependency:
    """Importing the module must never need pyobjc, so these tests run anywhere."""

    def test_the_accessibility_bindings_are_imported_inside_the_live_backend(self):
        tree = ast.parse(DRIVER_SOURCE.read_text(encoding="utf-8"))
        wanted = {"ApplicationServices", "Quartz", "AppKit"}
        module_level = {
            alias.name.split(".")[0]
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (node.names if isinstance(node, ast.Import) else node.names)
        } | {
            node.module.split(".")[0]
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not (module_level & wanted), f"pyobjc imported at module level: {module_level & wanted}"
        owners = {
            function.name
            for function in ast.walk(tree)
            if isinstance(function, ast.FunctionDef)
            for inner in ast.walk(function)
            if isinstance(inner, (ast.Import, ast.ImportFrom))
            and {
                *(alias.name.split(".")[0] for alias in inner.names),
                *([inner.module.split(".")[0]] if isinstance(inner, ast.ImportFrom) and inner.module else []),
            }
            & wanted
        }
        assert owners == {"__init__"}, f"pyobjc imported outside the live backend: {owners}"

    def test_pyobjc_is_not_a_declared_dependency_of_the_repo(self):
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert "pyobjc" not in text

    def test_the_fake_satisfies_the_node_protocol_the_driver_declares(self):
        node = FakeNode(role="AXButton", title="Save")
        assert isinstance(node, driver.AXNode)


# --- the deck ---------------------------------------------------------------
class TestCaptureDeck:
    """One slide, one named shape per target, and no motion contributed by sdpm."""

    def test_the_deck_has_one_slide_carrying_every_target(self, small_plan, built_deck):
        slides = sorted((built_deck["deck"] / "slides").glob("*.json"))
        assert len(slides) == 1
        assert built_deck["result"]["slide_count"] == 1
        elements = json.loads(slides[0].read_text(encoding="utf-8"))["elements"]
        shapes = [element for element in elements if element["type"] == "shape"]
        assert len(shapes) == len(small_plan["targets"])

    def test_every_target_key_is_visible_text_beside_its_own_shape(self, small_plan, built_deck):
        elements = json.loads(
            (built_deck["deck"] / "slides" / "s001.json").read_text(encoding="utf-8")
        )["elements"]
        # The label is the key's last segment on one line. The whole key used to be
        # wrapped onto two, and those two lines cost the shape half its height — the axis
        # that made clicks land on empty canvas. The authoritative key is in the plan and
        # the attribution is by spid, so the label only has to orient a reader.
        texts = {element["text"]: element for element in elements}
        for target in small_plan["targets"]:
            segment = target["key"].rpartition(".")[2]
            assert segment in texts, "a human cannot tell which shape is which target"
            label = texts[segment]
            rect = planner.Rect(**target["shapeRectPx"])
            # Directly under its own shape, same width, so the pairing is unambiguous.
            assert (label["x"], label["y"]) == (rect.x, rect.y + rect.height)
            assert label["width"] == rect.width

    def test_a_label_is_one_line_that_fits_its_box(self, reopened_plan):
        """Every label is a single line inside its box, for every target in the catalog.

        One line is the point: two lines needed 34 px of cell height, which left the
        shape 22 pt tall on its short axis, and a live run then landed 71 presses on five
        shapes. The key itself is not lost — it is in the plan, and the shape's ordinal
        ties the label back to it.
        """
        width_pt = reopened_plan["deck"]["shapePx"][0] / 2
        for target in reopened_plan["targets"]:
            label = planner.label_text(target["key"])
            assert "\n" not in label
            assert target["key"].endswith(label)
            # Arial's lowercase averages well under 0.5 em, so 0.5 is the pessimistic
            # bound; a line that fits under it fits.
            assert len(label) * planner.LABEL_FONT_PT * 0.5 <= width_pt, label
        assert planner.label_text("nodots") == "nodots"

    def test_each_shape_carries_its_ordinal_so_the_deck_can_be_read_against_the_plan(
        self, small_plan, built_deck
    ):
        elements = json.loads(
            (built_deck["deck"] / "slides" / "s001.json").read_text(encoding="utf-8")
        )["elements"]
        shapes = [element for element in elements if element["type"] == "shape"]
        assert [shape["text"] for shape in shapes] == [
            f"{target['targetIndex']:03d}" for target in small_plan["targets"]
        ]
        assert all(shape["id"].startswith(planner.SHAPE_ELEMENT_PREFIX) for shape in shapes)

    def test_both_motion_switches_are_off_in_the_deck_source(self, built_deck):
        deck = json.loads((built_deck["deck"] / "deck.json").read_text(encoding="utf-8"))
        assert deck["animations"] == {"enabled": False}
        assert deck["transitions"] == {"enabled": False}

    def test_generate_is_called_through_sdpm_with_both_modes_off(self, monkeypatch, tmp_path):
        import sdpm.api

        seen: dict[str, Any] = {}

        def fake_generate(json_path, output_path=None, **kwargs):
            seen.update({"json_path": json_path, "output_path": output_path, **kwargs})
            return {"output_path": str(output_path), "slide_count": 0}

        monkeypatch.setattr(sdpm.api, "generate", fake_generate)
        planner.generate_capture_deck(tmp_path / "deck", tmp_path / "out.pptx")
        assert seen["animation_mode"] == "off"
        assert seen["transition_mode"] == "off"

    def test_the_generated_package_carries_no_timing_and_no_transition(self, built_deck):
        with zipfile.ZipFile(built_deck["package"]) as archive:
            for name in archive.namelist():
                blob = archive.read(name)
                assert b"<p:timing" not in blob, name
                assert b"<p:transition" not in blob, name

    def test_the_shape_names_are_read_back_from_the_package_not_assumed(self, small_plan, built_deck):
        names = built_deck["names"]
        assert set(names) == {target["key"] for target in small_plan["targets"]}
        assert len(set(names.values())) == len(names), "two targets cannot share a shape"
        # sdpm derives the name from the geometry, so it is not the element id asked for.
        assert all(not name.startswith(planner.SHAPE_ELEMENT_PREFIX) for name in names.values())

    def test_applying_the_names_fills_both_the_mapping_and_each_target(self, small_plan, built_deck):
        plan = copy.deepcopy(small_plan)
        planner.apply_shape_names(plan, built_deck["names"])
        assert plan["shapeNames"] == built_deck["names"]
        assert all(target["shapeName"] == built_deck["names"][target["key"]] for target in plan["targets"])

    def test_an_empty_plan_has_no_deck(self, tmp_path):
        with pytest.raises(ValueError, match="no targets"):
            planner.build_capture_deck({"targets": []}, tmp_path / "deck")

    def test_a_shape_that_moved_is_refused_rather_than_matched_to_a_neighbour(
        self, small_plan, built_deck
    ):
        plan = copy.deepcopy(small_plan)
        plan["targets"][0]["shapeRectPx"]["x"] += 4
        with pytest.raises(ValueError, match="expects exactly one"):
            planner.resolve_shape_names(built_deck["package"], plan)

    def test_an_extra_candidate_shape_is_refused_rather_than_ignored(self, small_plan, tmp_path):
        plan = copy.deepcopy(small_plan)
        deck = tmp_path / "deck"
        planner.build_capture_deck(plan, deck)
        slide = deck / "slides" / "s001.json"
        data = json.loads(slide.read_text(encoding="utf-8"))
        extra = dict(data["elements"][0])
        extra["id"] = "intruder"
        extra["y"] = planner.DECK_BASIS_PX[1] - 100
        data["elements"].append(extra)
        slide.write_text(json.dumps(data), encoding="utf-8")
        result = planner.generate_capture_deck(deck, tmp_path / "extra.pptx")
        with pytest.raises(ValueError, match="an unmatched shape could be clicked"):
            planner.resolve_shape_names(Path(result["output_path"]), plan)


# --- the loop, against the fake ---------------------------------------------
class TestDrivingOneSlideManyShapes:
    """The whole loop: one slide, one shape per target, re-read before every press."""

    def test_a_whole_plan_runs_and_writes_one_attributed_record_per_target(self, session):
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert (summary["planned"], summary["attempted"], summary["captured"], summary["failed"]) == (3, 3, 3, 0)
        assert summary["attributed"] == 3
        assert summary["slides"] == [1]
        records = driver.read_records(session["settings"].readback_path)
        assert records[0]["record"] == "application"
        assert [record["catalogKey"] for record in records[1:]] == [
            target["key"] for target in session["plan"]["targets"]
        ]
        assert all(record["attributed"] for record in records[1:])
        assert all(record["ribbonReadBack"]["start"] == "On Click" for record in records[1:])
        assert all(record["ribbonReadBack"]["duration"] == "05.00" for record in records[1:])

    def test_each_record_is_attributed_to_its_own_shape_and_its_own_effect(self, session):
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        records = [
            record
            for record in driver.read_records(session["settings"].readback_path)
            if record.get("record") == driver.RECORD_KIND
        ]
        for record in records:
            expected = session["spids"][record["catalogKey"]]
            assert record["shapeSpid"] == expected
            assert record["attributedSpid"] == expected
            assert record["shapeName"] == session["names"][record["catalogKey"]]
        assert len({record["attributedSpid"] for record in records}) == 3
        # Each target's effect is distinguishable by its own cTn, not only by its shape.
        assert {record["effectCTn"]["presetID"] for record in records} == {"2", "31", "0"}
        # One save judged all three, so ``effectCount`` is the BATCH's step — the slide
        # went from 0 to 3 — and no single record owns it. What each record owns is
        # ``newEffectCount``: how many p:cTn nodes appeared on its OWN spid, which is the
        # figure the gate tested. Asserting the batch count here rather than a per-target
        # one is the honest reading of a batched run, not a relaxation: the per-target
        # number is still asserted, it just moved to the field that means it.
        assert [record["effectCount"] for record in records] == [{"before": 0, "after": 3}] * 3
        assert [record["newEffectCount"] for record in records] == [1, 1, 1]
        assert [record["batchIndex"] for record in records] == [1, 1, 1]

    def test_at_batch_size_one_the_counts_are_per_target_again(self, session):
        """``--batch-size 1`` restores the per-target before/after count exactly."""
        session["settings"].batch_size = 1
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        records = [
            record
            for record in driver.read_records(session["settings"].readback_path)
            if record.get("record") == driver.RECORD_KIND
        ]
        assert [record["effectCount"] for record in records] == [
            {"before": 0, "after": 1},
            {"before": 1, "after": 2},
            {"before": 2, "after": 3},
        ]
        assert [record["batchIndex"] for record in records] == [1, 2, 3]
        assert all(record["attributed"] for record in records)

    def test_each_press_lands_on_the_shape_the_target_names(self, session):
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert session["fake"].presses == [
            ("Fly In", session["spids"]["animation.gallery.entrance.flyIn"]),
            ("Grow & Turn", session["spids"]["animation.gallery.entrance.growTurn"]),
            ("Lines", session["spids"]["animation.gallery.motionPath.lines"]),
        ]

    def test_the_saved_package_ends_up_with_one_effect_per_target(self, session):
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        effects = driver.read_slide_effects(session["settings"].document, 1)
        assert len(effects) == 3
        assert {effect["spid"] for effect in effects} == set(session["spids"].values())

    def test_the_tree_is_re_read_more_often_than_it_is_pressed(self, session):
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert session["fake"].reads > len(session["fake"].presses) * 2

    def test_an_opener_whose_window_is_already_open_is_not_pressed_again(self, session):
        """Pressing it again **closes** the window, which is how one target failed.

        The third appearance of one trap: pressing an active ribbon tab collapses the
        ribbon, pressing ``Selection Pane...`` while the pane is open closes the pane,
        and pressing a gallery whose palette window is open closes that — reported as
        ``timed out waiting for the 'Path Animation' window to open`` right after
        something else had opened it. So the window's presence is read, not assumed.
        """
        fake = session["fake"]
        fake.select(session["plan"]["targets"][0]["shapeName"])
        fake.open_popup = planner.PATH_ANIMATION_CONTROL
        result = driver.press_path(
            fake,
            [planner.ANIMATIONS_TAB, planner.PATH_ANIMATION_CONTROL, "Lines"],
            timeout=2.0,
        )
        assert result.matched_title == "Lines"
        outcomes = {step["title"]: step["outcome"] for step in result.as_dicts()}
        assert outcomes[planner.PATH_ANIMATION_CONTROL] == "windowAlreadyOpen"
        assert planner.PATH_ANIMATION_CONTROL not in [title for title, _spid in fake.presses]

    def test_the_motion_path_press_happens_in_the_popup_window(self, session):
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert session["fake"].open_popup == planner.PATH_ANIMATION_CONTROL
        result = driver.press_path(
            session["fake"],
            [planner.ANIMATIONS_TAB, planner.PATH_ANIMATION_CONTROL, "Arcs"],
            timeout=2.0,
        )
        assert result.matched_title == "Arcs"
        outcomes = {step.title: step.outcome for step in result.steps}
        # The run before this left the popup open, so the opener is not pressed again —
        # pressing it would close the window the tile lives in. Either outcome puts the
        # scope in that window, which is what this test is about.
        assert outcomes[planner.PATH_ANIMATION_CONTROL] == "windowAlreadyOpen"
        assert outcomes["Arcs"] == "pressed"

    def test_an_absent_grouping_level_is_recorded_rather_than_fatal(self, session):
        session["fake"].select(session["plan"]["targets"][0]["shapeName"])
        result = driver.press_path(
            session["fake"],
            [planner.ANIMATIONS_TAB, planner.PATH_ANIMATION_CONTROL, "Basic", "Lines"],
            timeout=2.0,
        )
        outcomes = {step.title: step.outcome for step in result.steps}
        assert outcomes["Basic"] == "groupAbsent"
        assert outcomes["Lines"] == "pressed"

    def test_a_visible_gallery_is_scoped_into_rather_than_pressed(self, session):
        session["fake"].select(session["plan"]["targets"][0]["shapeName"])
        result = driver.press_path(
            session["fake"], [planner.ANIMATIONS_TAB, "Entrance Effects", "Fly In"], timeout=2.0
        )
        outcomes = {step.title: step.outcome for step in result.steps}
        assert outcomes["Entrance Effects"] == "scoped"
        assert session["fake"].presses == [("Fly In", "2")]

    def test_a_tile_on_another_page_is_paged_to_rather_than_reported_missing(self, session):
        """A gallery publishes one page of tiles, so a missing tile is paged for.

        Measured live: the Entrance gallery published 25 tiles and the last three
        failures were effects on another page — "none of 'Grow & Turn', 'Grow Turn'
        appeared" against a gallery that holds it. The pagers are ribbon buttons, so this
        costs no pointer and no coordinates.
        """
        fake = session["fake"]
        fake.select(session["plan"]["targets"][0]["shapeName"])
        assert "Grow & Turn" not in fake.tile_pages[fake.page], "the tile starts off-page"
        result = driver.press_path(
            fake, [planner.ANIMATIONS_TAB, "Entrance Effects", "Grow & Turn"], timeout=2.0
        )
        assert result.matched_title == "Grow  Turn", "the live title drops the ampersand"
        assert fake.presses[-1][0] == "Grow & Turn"
        assert "down" in fake.scrolls, "it never paged the gallery"
        paged = [step for step in result.as_dicts() if step["outcome"].startswith("pagedGallery")]
        assert len(paged) == 1, "the record does not say the gallery was paged"

    def test_the_gallery_is_paged_up_before_down_because_a_press_leaves_it_anywhere(
        self, session
    ):
        """The top is the only known starting point, so it goes there first.

        A press leaves the gallery on whatever page it was on, so the next target starts
        from there and a tile **above** it would never be found by paging down. Here the
        tile is on the first page and the gallery starts on the second.
        """
        fake = session["fake"]
        fake.select(session["plan"]["targets"][0]["shapeName"])
        fake.page = len(fake.tile_pages) - 1
        result = driver.press_path(
            fake, [planner.ANIMATIONS_TAB, "Entrance Effects", "Fly In"], timeout=2.0
        )
        assert result.matched_title == "Fly In"
        assert fake.scrolls[0] == "up", "it paged down first, which cannot reach a tile above"

    def test_a_tile_that_is_on_no_page_is_a_bounded_failure_naming_the_paging(self, session):
        """Paging is bounded in both directions and says what it tried."""
        fake = session["fake"]
        fake.select(session["plan"]["targets"][0]["shapeName"])
        with pytest.raises(driver.ControlNotFound) as raised:
            driver.press_path(
                fake, [planner.ANIMATIONS_TAB, "Entrance Effects", "No Such Tile"], timeout=2.0
            )
        assert "paged" in str(raised.value)
        assert len(fake.scrolls) <= 2 * driver.MAX_GALLERY_PAGES
        assert driver.MAX_GALLERY_PAGES == 8

    def test_an_ampersand_is_dropped_from_the_live_title_and_tried_that_way(self):
        """``Grow & Turn`` is published as ``Grow  Turn``, with the spaces kept.

        Measured on the live gallery, which lists ``Grow  Turn`` and ``Shrink  Turn``.
        Two targets were reported absent for this and nothing else. The exact title is
        still tried first, so a gallery that does publish the ampersand is matched on it.
        """
        assert driver.title_variants("Grow & Turn") == ("Grow & Turn", "Grow  Turn")
        assert driver.title_variants("Shrink & Turn", ("Shrink Turn",)) == (
            "Shrink & Turn",
            "Shrink Turn",
            "Shrink  Turn",
        )
        assert driver.title_variants("Fly In") == ("Fly In",), "no variant where none is needed"
        assert driver.title_variants("Grow & Turn", ("Grow  Turn",)) == (
            "Grow & Turn",
            "Grow  Turn",
        ), "a variant that is already an alternative is not repeated"

    def test_an_alternative_title_is_tried_and_recorded(self, session):
        session["fake"].select(session["plan"]["targets"][0]["shapeName"])
        session["fake"].tile_pages = (("Grow Turn",),)
        result = driver.press_path(
            session["fake"],
            [planner.ANIMATIONS_TAB, "Entrance Effects", "Grow & Turn"],
            timeout=2.0,
            alternatives=("Grow Turn",),
        )
        assert result.matched_title == "Grow Turn"
        assert session["fake"].presses == [("Grow Turn", "2")]

    def test_the_shape_is_selected_by_its_own_selection_pane_row(self, session):
        """One row selection per target, by name, and no mouse event anywhere.

        The fake has no ``click`` to call and the backend protocol no longer declares
        one, so this is a property of the shape of the thing as much as of the run.
        """
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert session["fake"].selections == [
            target["shapeName"] for target in session["plan"]["targets"]
        ]
        assert len(session["fake"].selections) == summary["attempted"] == 3
        assert not hasattr(session["fake"], "click")
        assert not hasattr(driver.AXBackend, "click")

    def test_save_is_pressed_once_per_batch_and_once_per_target_at_batch_size_one(self, session):
        """One save per batch, and ``--batch-size 1`` is still one per target.

        This assertion used to be ``saves == 3`` for three targets, and it changed
        because the behaviour did: the three targets are one batch now, so one Save
        judges them. The figure that replaced it is not weaker — it is the same count
        against the batches rather than the targets, and the per-target form is asserted
        beside it so the old behaviour is still reachable and still checked.
        """
        summary = driver.run_capture(
            session["plan"], session["settings"], session["fake"], version="16.113.1"
        )
        assert (summary["batchSize"], summary["batches"]) == (driver.DEFAULT_BATCH_SIZE, 1)
        assert session["fake"].saves == 1

        # A fresh output directory and a deck back to no effects, so the per-target half
        # is three captures and three saves rather than three rejections that happen to
        # have saved on the way.
        write_effects(session["settings"].document, 1, {})
        session["fake"].effects = {}
        session["fake"].saves = 0
        session["settings"].out_dir = session["settings"].out_dir.parent / "per-target"
        session["settings"].batch_size = 1
        per_target = driver.run_capture(
            session["plan"], session["settings"], session["fake"], version="16.113.1"
        )
        assert (per_target["batchSize"], per_target["batches"]) == (1, 3)
        assert per_target["captured"] == 3
        assert session["fake"].saves == 3

    def test_the_package_is_copied_where_parse_oracle_expects_it(self, session):
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        package = session["settings"].out_dir / driver.PACKAGE_NAME
        assert package.exists()
        assert summary["package"] == str(package)
        assert package.read_bytes() == session["settings"].document.read_bytes()

    def test_the_output_directory_is_what_parse_oracle_reads(self, session, capsys):
        """End to end: a run's output directory is analysable by the committed generator.

        This is the join that matters. ``--parse-oracle`` reads the saved package part by
        part and the read-back line by line, with no PowerPoint and no network, so if the
        driver's two outputs do not line up here they would not line up for a maintainer.
        """
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert analyse_oracle_output(session["settings"].out_dir) == 0
        merged = json.loads(capsys.readouterr().out)
        assert merged["package"] == driver.PACKAGE_NAME
        assert merged["slideCount"] == 1
        assert merged["candidateRecords"] == 3
        keys = [candidate["key"] for candidate in merged["candidates"]]
        assert keys == [f"{driver.RECORD_ENUM}.{target['key']}" for target in session["plan"]["targets"]]
        # Every candidate now carries OOXML, because the fake really did write effects —
        # and they all carry the *same* slide, which is what the record's own
        # attributedSpid exists to disambiguate.
        assert merged["unresolvedCandidates"] == []
        assert all(candidate["ooxml"]["timing"] for candidate in merged["candidates"])

    def test_the_ribbon_tab_is_made_active_before_the_gallery_is_pressed(self, session):
        """Opening the pane leaves the ribbon on Home, and a press needs Animations.

        Only the active tab's controls are in the fake's tree, as in the live one, so a
        run that forgot this would wait for a gallery that cannot appear — which is
        exactly what a live run did, timing out all 76 targets on 'Emphasis Effects'.
        """
        fake = session["fake"]
        assert fake.active_tab == driver.RIBBON_ANCHOR_TAB, "a fresh deck starts on Home"
        summary = driver.run_capture(session["plan"], session["settings"], fake, version="16.113.1")
        assert summary["captured"] == 3
        assert fake.active_tab == planner.ANIMATIONS_TAB


# --- batching ---------------------------------------------------------------
class TestBatching:
    """One Save judges many targets, and each is still attributed by its own ``spid``.

    The point of these is the boundary. A batch must not let one bad target cost the
    good ones, must not credit a target whose own shape gained nothing, and must refuse
    the whole batch when an effect appears on a shape nobody in it selected — which is
    the signature of a press landing somewhere the run cannot account for.
    """

    def test_one_save_judges_the_whole_batch_and_each_target_by_its_own_spid(self, session):
        summary = driver.run_capture(
            session["plan"], session["settings"], session["fake"], version="16.113.1"
        )
        assert (summary["batches"], session["fake"].saves) == (1, 1)
        assert summary["captured"] == summary["attributed"] == 3
        records = [
            record
            for record in driver.read_records(session["settings"].readback_path)
            if record.get("record") == driver.RECORD_KIND
        ]
        # Three records, one Save, and three different spids — the evidence is per target
        # even though the package was read once.
        assert len({record["attributedSpid"] for record in records}) == 3
        for record in records:
            assert record["attributedSpid"] == record["shapeSpid"] == session["spids"][record["catalogKey"]]
            assert record["batchIndex"] == 1
            assert record["saved"] is True

    def test_a_target_that_gains_nothing_is_rejected_and_its_batch_mates_are_credited(
        self, session
    ):
        """One bad target costs one record, not the batch. This is the instruction.

        The press lands and PowerPoint attaches nothing to that shape, so its spid gains
        nothing while its two batch mates gain one effect each. Rejecting the batch would
        throw away two correct captures; crediting the empty one would invent evidence.
        """
        fake, targets = session["fake"], session["plan"]["targets"]
        fake.applies_nothing_for = {targets[1]["shapeName"]}
        summary = driver.run_capture(
            session["plan"], session["settings"], fake, version="16.113.1"
        )
        assert (summary["batches"], fake.saves) == (1, 1)
        assert (summary["captured"], summary["failed"]) == (2, 1)
        failure = next(f for f in summary["failures"] if f["key"] == targets[1]["key"])
        assert failure["error"]["kind"] == "effectNotAdded"
        assert "no new effect appeared" in failure["error"]["message"]
        detail = failure["error"]["detail"]
        assert detail["expectedSpid"] == session["spids"][targets[1]["key"]]
        # It says which spids DID gain, so a reader can see it was not a dead batch.
        assert sorted(detail["appearedSpids"]) == sorted(
            session["spids"][target["key"]] for target in (targets[0], targets[2])
        )
        # And the other two are credited, each to its own shape.
        records = {
            record["catalogKey"]: record
            for record in driver.read_records(session["settings"].readback_path)
            if record.get("record") == driver.RECORD_KIND
        }
        for target in (targets[0], targets[2]):
            assert records[target["key"]]["attributed"] is True
            assert records[target["key"]]["attributedSpid"] == session["spids"][target["key"]]
            assert records[target["key"]]["newEffectCount"] == 1
        assert records[targets[1]["key"]]["attributed"] is False
        # Pressed, though: what failed is the evidence, and the record does not pretend
        # the press never happened.
        assert len(fake.presses) == 3

    def test_a_stray_spid_fails_the_whole_batch_naming_it(self, session):
        """An effect on a shape nobody in the batch selected refuses the batch.

        This is the realistic shape of a mis-selection under batching: a press lands on
        the previously selected shape instead of this one, and with a batch that shape is
        often **outside** the batch — here one of the deck's own label text boxes. Then
        the package shows an effect on a spid no target asked for, and the batch cannot be
        credited around it: one of its presses demonstrably went somewhere else, and the
        package cannot say which of the remaining credits is really that press's.
        """
        fake, targets = session["fake"], session["plan"]["targets"]
        target_names = {target["shapeName"] for target in targets}
        outsider = next(
            name
            for name, _spid in shape_names_in_z_order(session["settings"].document, 1)
            if name not in target_names
        )
        outsider_spid = fake._spids[outsider]
        assert outsider_spid not in set(session["spids"].values())
        fake.applies_to_instead = {targets[0]["shapeName"]: outsider}

        summary = driver.run_capture(
            session["plan"], session["settings"], fake, version="16.113.1"
        )
        assert (summary["captured"], summary["attributed"]) == (0, 0)
        assert summary["failed"] == 3, "the batch failed, not one target of it"
        for failure in summary["failures"]:
            assert failure["error"]["kind"] == "effectMisattributed"
            assert outsider_spid in failure["error"]["message"]
            detail = failure["error"]["detail"]
            assert detail["straySpids"] == [outsider_spid]
            assert detail["expectedSpids"] == sorted(session["spids"].values())
            assert failure["attributedSpid"] is None
        # Named as data as well as prose, so the evidence can be queried for it.
        assert all(record["attributed"] is False for record in [
            record
            for record in driver.read_records(session["settings"].readback_path)
            if record.get("record") == driver.RECORD_KIND
        ])

    def test_an_effect_on_two_shapes_is_a_stray_rather_than_a_credit(self):
        """An effect whose ``p:spTgt`` names two shapes belongs to no target in a batch."""
        after = [{"spid": None, "spids": ["2", "4"], "cTn": {"presetID": "2"}}]
        with pytest.raises(driver.EffectMisattributed, match=r"\['2', '4'\]"):
            driver.attribute_batch([], after, ["2", "4"])

    def test_a_batch_of_one_is_the_per_target_gate_itself_not_a_lookalike(self):
        """``--batch-size 1`` delegates, so its failures are identical rather than similar.

        Asserted against :func:`attribute_new_effect` directly, because "behaves exactly
        as before" has to mean the same exception type, the same message and the same
        ``detail`` — not a batch-level failure that happens to name one target.
        """
        before = [{"spid": "2", "spids": ["2"], "cTn": {"presetID": "2"}}]
        after = before + [{"spid": "4", "spids": ["4"], "cTn": {"presetID": "10"}}]
        assert driver.attribute_batch(before, after, ["4"]) == {
            "4": driver.attribute_new_effect(before, after, "4")
        }

        with pytest.raises(driver.EffectMisattributed) as batched:
            driver.attribute_batch(before, after, ["6"])
        with pytest.raises(driver.EffectMisattributed) as single:
            driver.attribute_new_effect(before, after, "6")
        assert str(batched.value) == str(single.value)
        assert batched.value.as_error() == single.value.as_error()

        with pytest.raises(driver.EffectNotAdded) as batched_none:
            driver.attribute_batch(before, before, ["4"])
        with pytest.raises(driver.EffectNotAdded) as single_none:
            driver.attribute_new_effect(before, before, "4")
        assert batched_none.value.as_error() == single_none.value.as_error()

    def test_the_batches_are_the_size_asked_for_and_never_mix_two_slides(self):
        targets = [{"key": str(index), "slideIndex": 1} for index in range(25)]
        sizes = [len(batch) for batch in driver.plan_batches(targets, 10)]
        assert sizes == [10, 10, 5]
        assert driver.plan_batches(targets, 1) == [[target] for target in targets]
        assert driver.plan_batches([], 10) == []
        # One Save judges one batch and the judgement reads one slide, so a split plan
        # produces more, smaller batches rather than a batch it could not attribute.
        split = [{"key": "a", "slideIndex": 1}, {"key": "b", "slideIndex": 2}]
        assert [len(batch) for batch in driver.plan_batches(split, 10)] == [1, 1]
        assert {batch[0]["slideIndex"] for batch in driver.plan_batches(split, 10)} == {1, 2}

    def test_a_batch_that_cannot_hold_a_target_is_refused(self):
        with pytest.raises(driver.DriverRefusal, match="at least one target"):
            driver.plan_batches([{"key": "a", "slideIndex": 1}], 0)

    def test_the_cli_refuses_a_batch_size_below_one(self, tmp_path, capsys):
        plan = tmp_path / "plan.json"
        plan.write_text(json.dumps({"shapeNames": {}, "targets": []}), encoding="utf-8")
        document = tmp_path / "deck.pptx"
        document.write_bytes(b"x")
        code = driver.main(
            [
                "--plan", str(plan), "--out", str(tmp_path), "--document", str(document),
                "--batch-size", "0", driver.DRIVE_TOKEN,
            ]
        )
        assert code == 2
        assert "--batch-size must be at least 1" in capsys.readouterr().err

    def test_a_save_that_never_lands_rejects_every_target_pressed_into_it(self, session, monkeypatch):
        """The save is the evidence, so a batch without one credits nothing.

        The difference batching makes is the count: one failed Save now rejects every
        target of the batch rather than one. They are retried on the next run, because an
        uncaptured target has no record.
        """
        monkeypatch.setattr(FakePowerPoint, "_save", lambda self: setattr(self, "saves", self.saves + 1))
        summary = driver.run_capture(
            session["plan"], session["settings"], session["fake"], version="16.113.1"
        )
        assert (summary["batches"], session["fake"].saves) == (1, 1)
        assert summary["failed"] == summary["saveFailures"] == 3
        assert summary["captured"] == 0

    def test_a_resumed_run_restarts_at_the_first_uncaptured_target(self, session):
        """A partially completed run picks up the targets with no record, in plan order.

        Driven at ``--batch-size 2`` so the first run's batches do not line up with the
        second's: the rejected target is the second half of batch 1, and the resumed run
        has to find it rather than restart a batch boundary.
        """
        fake, targets = session["fake"], session["plan"]["targets"]
        session["settings"].batch_size = 2
        fake.applies_nothing_for = {targets[1]["shapeName"]}
        first = driver.run_capture(session["plan"], session["settings"], fake, version="16.113.1")
        assert (first["batches"], first["captured"], first["failed"]) == (2, 2, 1)

        fake.applies_nothing_for = set()
        fake.presses.clear()
        resumed = driver.run_capture(session["plan"], session["settings"], fake, version="16.113.1")
        assert resumed["skippedAlreadyCaptured"] == 2
        assert resumed["attempted"] == resumed["captured"] == 1
        assert resumed["batches"] == 1
        # Exactly the uncaptured target was pressed, on its own shape.
        assert fake.presses == [
            (targets[1]["guiPath"][-1], session["spids"][targets[1]["key"]])
        ]
        records = [
            record
            for record in driver.read_records(session["settings"].readback_path)
            if record.get("record") == driver.RECORD_KIND
        ]
        assert len(records) == 3, "one record per key, rewritten rather than appended"
        assert all(record["attributed"] for record in records)

    def test_a_progress_line_per_batch_goes_to_stderr_and_stdout_stays_clean(self, session, capsys):
        """A 76-target run must not be indistinguishable from a hang.

        stderr, not stdout: the summary on stdout is parsed as JSON.
        """
        session["settings"].batch_size = 2
        summary = driver.run_capture(
            session["plan"], session["settings"], session["fake"], version="16.113.1"
        )
        captured = capsys.readouterr()
        assert captured.out == "", "stdout must stay pure JSON for the summary"
        lines = captured.err.strip().splitlines()
        assert len(lines) == summary["batches"] == 2
        assert lines[0].startswith("batch 1/2:")
        assert "2 targets attempted" in lines[0]
        assert "2/3 done" in lines[0] and "2 captured" in lines[0]
        assert "elapsed" in lines[0]
        assert lines[1].startswith("batch 2/2:")
        assert "3/3 done" in lines[1]

    def test_progress_is_injectable_so_a_caller_can_route_it(self, session):
        seen: list[str] = []
        driver.run_capture(
            session["plan"], session["settings"], session["fake"], progress=seen.append
        )
        assert len(seen) == 1 and seen[0].startswith("batch 1/1:")


# --- cost, which is a correctness property here -----------------------------
#: Attribute reads one target may cost, measured against :func:`big_pane_session` and
#: pinned with headroom. The driver this replaced captured **7 targets in 28 minutes** —
#: four minutes each, every one correct — because every lookup walked the whole 907-node
#: document window, and live one attribute read is one interprocess round trip. Measured
#: on this fake: 2,218 reads per target now against 19,826 before, 8.9x. The budget is
#: 3,000, which is ~35% of headroom over what it costs and ~15% of what a full-window
#: walk per lookup costs, so a lookup that quietly widened back to the window would
#: break this and nothing else.
#:
#: Update it only when a read legitimately moved, and say which and why. Raising it to
#: make a change fit is how the thing this guards against comes back.
READ_BUDGET_PER_TARGET = 3_000

#: How many full window walks one target may cost. The scale-free form of the same
#: statement: every lookup used to cost one of these, and a target makes about ten
#: lookups. This one adapts if the fake's tree changes size; the absolute budget above is
#: the pin that notices if it does.
WINDOW_WALKS_PER_TARGET = 5


@pytest.fixture
def big_pane_session(small_plan, built_deck, tmp_path):
    """A session whose Selection Pane carries 156 rows, as the live one carried 153.

    The proportions are what make a read count mean anything: the live document window
    was 907 nodes and **762 of them were the pane's rows**, so a fake with six rows would
    let a lookup walk the window for almost nothing and the budget would not bite.

    The rows come from 150 filler shapes added to the **slide**, not from rows invented in
    the pane, so the pane still publishes one row per shape — which is what the driver
    requires before it will trust a row index.
    """
    document = tmp_path / f"{built_deck['package'].stem}.pptx"
    document.write_bytes(built_deck["package"].read_bytes())
    add_filler_shapes(document, 1, 150)
    plan = copy.deepcopy(small_plan)
    planner.apply_shape_names(plan, built_deck["names"])
    fake = FakePowerPoint(document)
    settings = driver.CaptureSettings(out_dir=tmp_path / "out", document=document, timeout=2.0)
    return {"plan": plan, "fake": fake, "settings": settings}


def full_window_walk_reads(document: Path) -> int:
    """What one ``find_all_by_title`` over the whole document window costs, in reads.

    This is what **every** lookup cost before the containers: resolving a ribbon tile
    traversed all the pane's rows, and resolving a row traversed the ribbon. Takes the
    document as given, so a caller passes the inflated one from
    :func:`big_pane_session` and the comparison is against the same window.
    """
    fake = FakePowerPoint(document, selection_pane_open=True)
    before = fake.attribute_reads
    driver.find_all_by_title(driver.document_window(fake), driver.SAVE_LABEL)
    return fake.attribute_reads - before


class TestRowsComeFromAXRows:
    """The pane is read through ``AXRows``, which publishes all of them.

    ``AXChildren`` publishes only what is scrolled into view. Measured live: ``AXRows``
    152, ``AXVisibleRows`` 24, every one of the 152 carrying a readable name. Reading
    children instead is how one run reported "the pane shows 62 names", then 47, and
    failed 26 targets looking for a row that existed the whole time — so no scrolling is
    needed, only the right attribute.
    """

    def test_a_row_scrolled_out_of_view_is_still_found(self, session):
        fake = session["fake"]
        fake.selection_pane_open = True
        fake.visible_row_count = 1
        rows = driver.selection_rows(fake)
        names = [name for row in rows for name in row.names]
        assert len(rows) == len(fake._shapes)
        for target in session["plan"]["targets"]:
            assert target["shapeName"] in names

    def test_the_whole_plan_captures_with_almost_nothing_visible(self, session):
        session["fake"].visible_row_count = 1
        summary = driver.run_capture(
            session["plan"], session["settings"], session["fake"], version="16.113.1"
        )
        assert summary["captured"] == len(session["plan"]["targets"])
        assert summary["failed"] == 0

    def test_an_outline_publishing_no_rows_falls_back_to_its_children(self, session, monkeypatch):
        """Not every outline answers ``AXRows``; the bounded walk is still the floor."""
        original = FakePowerPoint._selection_pane

        def without_rows(self):
            node = original(self)
            node._rows = None
            node._children = [row for row in (original(self)).rows or []]
            return node

        monkeypatch.setattr(FakePowerPoint, "_selection_pane", without_rows)
        session["fake"].selection_pane_open = True
        rows = driver.selection_rows(session["fake"])
        assert len(rows) == len(session["fake"]._shapes)


class TestLookupCost:
    """Counted, because the only thing wrong with the previous driver was its cost.

    Nothing else here can catch a lookup that walks the window: it returns the right
    element, every assertion about behaviour passes, and the run takes four minutes a
    target instead of fifteen seconds. So the reads are counted and budgeted.
    """

    def test_capturing_a_batch_stays_inside_the_read_budget(self, big_pane_session):
        fake, settings = big_pane_session["fake"], big_pane_session["settings"]
        targets = big_pane_session["plan"]["targets"]
        start = fake.attribute_reads
        summary = driver.run_capture(
            big_pane_session["plan"], settings, fake, version="16.113.1", progress=lambda _m: None
        )
        assert summary["captured"] == len(targets), "the budget means nothing if it failed"
        reads = fake.attribute_reads - start
        per_target = reads / len(targets)
        assert per_target <= READ_BUDGET_PER_TARGET, (
            f"{per_target:.0f} attribute reads per target, budget {READ_BUDGET_PER_TARGET}; a "
            "lookup has gone back to walking the window"
        )

    def test_a_target_costs_less_than_a_handful_of_full_window_walks(self, big_pane_session):
        """The budget restated against what a single unscoped lookup costs.

        A full-window walk per lookup is not a hypothetical: it is what this driver did,
        and it is why a live run could not reach 76 targets. One walk of this fake's
        window costs what is measured here, a target makes about ten lookups, and the
        whole target now costs fewer than five walks.
        """
        fake, settings = big_pane_session["fake"], big_pane_session["settings"]
        targets = big_pane_session["plan"]["targets"]
        walk = full_window_walk_reads(settings.document)
        assert walk > 300, "the fake's window is too small for this comparison to mean anything"
        start = fake.attribute_reads
        driver.run_capture(
            big_pane_session["plan"], settings, fake, version="16.113.1", progress=lambda _m: None
        )
        per_target = (fake.attribute_reads - start) / len(targets)
        assert per_target <= WINDOW_WALKS_PER_TARGET * walk
        # And the budget really is below what per-lookup walking would cost, so the
        # absolute pin above is not generous enough to pass a regression.
        assert READ_BUDGET_PER_TARGET < 10 * walk

    def test_the_pane_is_what_the_cost_is_bounded_by_and_the_ribbon_is_not(
        self, big_pane_session
    ):
        """Where the reads go, so a future change knows what is worth attacking.

        Selecting one shape resolves its row twice — once to write ``AXSelected`` and
        once to read it back — and each resolution reads the whole outline, because the
        row count has to be checked against the slide before an index can be used. That
        is the floor. Pressing a ribbon control is now an order of magnitude cheaper than
        that, which is the inversion the containers bought: it used to be the same price,
        because both walked the window.
        """
        fake = big_pane_session["fake"]
        document = big_pane_session["settings"].document
        name = big_pane_session["plan"]["targets"][0]["shapeName"]
        driver.open_selection_pane(fake, timeout=2.0)
        row_index, row_count = driver.shape_row_index(document, 1, name)

        start = fake.attribute_reads
        driver.select_shape(fake, name, row_index=row_index, row_count=row_count, timeout=2.0)
        selecting = fake.attribute_reads - start

        driver.ensure_tab(fake, [planner.ANIMATIONS_TAB, "Entrance Effects"], timeout=2.0)
        start = fake.attribute_reads
        driver.press_path(
            fake, [planner.ANIMATIONS_TAB, "Entrance Effects", "Fly In"], timeout=2.0
        )
        pressing = fake.attribute_reads - start

        assert selecting > 5 * pressing, (
            f"selecting a row cost {selecting} reads and pressing a tile {pressing}; the ribbon "
            "press is no longer the cheap one, so something has gone back to walking the window"
        )

    def test_the_document_window_is_identified_without_walking_any_candidate(self, session):
        """PowerPoint publishes five same-titled windows and only one has the ribbon.

        Identifying it used to be ``find_all_by_title(window, "Home")`` per candidate —
        several full walks, from a function nearly every helper calls. It is now a probe
        of each candidate's direct children, so it costs about as much as reading their
        children lists and no more.
        """
        fake = session["fake"]
        assert fake.decoy_windows == 4, "the fake must publish the siblings the real one does"
        start = fake.attribute_reads
        window = driver.document_window(fake)
        cost = fake.attribute_reads - start
        assert window.title == fake.document_title
        assert driver.find_containers(window, driver.RIBBON_ROLE), "it picked the one with the ribbon"
        # Five windows, a title and a children list each, plus a role per direct child.
        assert cost < 60, f"identifying the document window cost {cost} reads"

    def test_a_container_search_never_descends_into_another_container(self, session):
        """The pruning rule, stated against the tree rather than against a read count.

        A search for the toolbar must not enter the outline, because the outline is where
        762 of the live window's 907 nodes are. With the pane open, finding the toolbar
        must therefore cost no more than finding it with the pane shut.
        """
        fake = session["fake"]
        fake.selection_pane_open = False
        start = fake.attribute_reads
        driver.find_containers(driver.document_window(fake), driver.TOOLBAR_ROLE)
        shut = fake.attribute_reads - start

        fake.selection_pane_open = True
        fake._shapes = [(f"Shape {index}", str(index + 2)) for index in range(200)]
        fake._spids = dict(fake._shapes)
        start = fake.attribute_reads
        found = driver.find_containers(driver.document_window(fake), driver.TOOLBAR_ROLE)
        wide_open = fake.attribute_reads - start

        assert len(found) == 1
        assert wide_open <= shut + 2, (
            f"finding the toolbar cost {shut} reads with the pane shut and {wide_open} with 200 "
            "rows open, so the search is descending into the Selection Pane"
        )

    def test_a_container_search_that_becomes_a_tree_walk_is_an_error(self, session):
        """A window not shaped as measured fails loudly rather than walking everything.

        Searched against one of the fake's decoy windows, because the document window is
        two containers under a root and the pruning means a search of it visits three
        nodes however large the pane is — which is the property, not a way to dodge the
        bound. A window with a deep subtree and no container in it is what overruns.
        """
        decoy = session["fake"]._decoy_window(0)
        assert len(driver.find_containers(decoy, driver.RIBBON_ROLE)) == 0
        with pytest.raises(driver.TreeTooLarge, match="container search has become a tree walk"):
            driver.find_containers(decoy, "AXNoSuchRole", max_nodes=5)


class TestScopesRaiseRatherThanWiden:
    """A scope that cannot be identified must fail, not fall back to the window.

    This is the rule that keeps the cost gone. A lookup that widened to the window when
    its container was missing would still find the control, still pass every behavioural
    test, and put the four-minutes-a-target cost back where nobody would look for it.
    """

    def test_save_outside_the_toolbar_is_not_found_by_widening_to_the_window(self, session):
        fake = session["fake"]
        # Save still exists, directly under the window, exactly where the old lookup
        # would have found it.
        monkeypatched = FakeNode(
            role="AXWindow",
            title=fake.document_title,
            children=[
                FakeNode(role="AXButton", title=driver.SAVE_LABEL),
                fake._ribbon(),
            ],
        )
        with pytest.raises(driver.ControlNotFound, match=driver.TOOLBAR_ROLE):
            driver.window_container(
                monkeypatched, driver.TOOLBAR_ROLE, what=driver.CONTAINER_NAMES[driver.TOOLBAR_ROLE]
            )

    def test_an_absent_container_names_what_the_window_does_hold(self, session):
        window = driver.document_window(session["fake"])
        with pytest.raises(driver.ControlNotFound) as raised:
            driver.window_container(window, "AXSplitGroup", what="the split view")
        message = str(raised.value)
        assert "the split view" in message
        assert driver.TOOLBAR_ROLE in message and driver.RIBBON_ROLE in message

    def test_two_containers_of_one_role_are_refused_rather_than_chosen_between(self, session):
        fake = session["fake"]
        doubled = FakeNode(
            role="AXWindow",
            title=fake.document_title,
            children=[fake._toolbar(), fake._toolbar(), fake._ribbon()],
        )
        with pytest.raises(driver.AmbiguousControl, match="refusing to guess"):
            driver.window_container(
                doubled, driver.TOOLBAR_ROLE, what=driver.CONTAINER_NAMES[driver.TOOLBAR_ROLE]
            )

    def test_every_lookup_the_driver_makes_names_a_container(self):
        """No scope in the driver starts at the bare window.

        ``Scope()`` with no container is still constructible, because a popup window has
        no container to narrow to and needs none — but nothing may use it against the
        *document* window, which is the expensive case.
        """
        source = DRIVER_SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        bare = [
            function.name
            for function in ast.walk(tree)
            if isinstance(function, ast.FunctionDef)
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Scope"
            and not node.args
            and not node.keywords
        ]
        assert bare == [], f"these resolve against the whole document window: {bare}"
        # And the window itself is only ever reached through the holder or by the two
        # functions whose job is to find it.
        callers = {
            function.name
            for function in ast.walk(tree)
            if isinstance(function, ast.FunctionDef)
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "document_window"
        }
        assert callers == {"window"}, f"document_window is called outside the holder: {callers}"


# --- the docs that describe it ---------------------------------------------
@pytest.fixture(scope="module")
def readme() -> str:
    return (REPO_ROOT / "scripts" / "animation_catalog" / "README.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def mechanics() -> str:
    return (REPO_ROOT / "scripts" / "animation_catalog" / "computer-use.md").read_text(encoding="utf-8")


class TestDocsMatchTheCode:
    """The counts and the control names in the docs are derived, so drift fails here."""

    def test_the_readme_counts_match_the_derived_plan(self, readme, real_plan):
        for name, count_ in real_plan["counts"].items():
            row = next((line for line in readme.splitlines() if line.startswith(f"| `{name}` |")), None)
            assert row, f"the README has no counts row for {name}"
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            assert cells[1] == str(count_), f"README says {name} is {cells[1]}, the plan derives {count_}"

    def test_the_readme_names_both_modules_and_the_outputs(self, readme):
        for token in (
            "gui_capture.py",
            "gui_capture_plan.py",
            driver.READBACK_NAME,
            driver.PACKAGE_NAME,
            "--parse-oracle",
        ):
            assert token in readme, token

    def test_the_readme_says_the_pointer_is_not_moved_and_keeps_the_guard(self, readme):
        """The disclosure inverted, because the behaviour did.

        It used to require "moves the real pointer". The driver posts no mouse events
        now, so a README that still warned about a pointer takeover would be describing a
        tool that no longer exists — and the document guard is still there, for a
        different reason, which the README has to give.
        """
        assert "does not move the pointer" in readme
        assert "moves the real pointer" not in readme
        assert "refuses to start" in readme and "capture deck" in readme
        assert "does not need PowerPoint to be frontmost" in readme

    def test_the_readme_records_why_the_canvas_click_is_gone(self, readme):
        assert "2 of 12" in readme
        assert "Selection Pane" in readme
        for gone in ("--pane-frame", "--zoom", "canvas_point"):
            assert gone in readme, f"the README does not say {gone} is gone"

    def test_the_readme_describes_the_grid_the_plan_derives(self, readme, reopened_plan):
        deck = reopened_plan["deck"]
        assert f"{deck['columns']}x{deck['rows']}" in readme, "the README does not state the derived grid"
        assert "one slide" in readme
        assert "spid" in readme

    def test_the_readme_records_why_slide_navigation_is_gone(self, readme):
        assert "76 rejected" in readme
        assert "scrolled into view" in readme

    def test_the_mechanics_name_every_gallery_control_the_plan_emits(self, mechanics, reopened_plan):
        controls = {target["guiPath"][1] for target in reopened_plan["targets"]}
        missing = sorted(control for control in controls if f"`{control}`" not in mechanics)
        assert not missing, f"control names the plan emits but computer-use.md does not record: {missing}"

    def test_the_mechanics_keep_the_canvas_formula_for_manual_work_only(self, mechanics):
        """The formula is a measurement, so it stays — labelled as not the driver's.

        ``computer-use.md`` documents what the application does, and an operator driving
        it by hand still needs the mapping. What must not survive is the impression that
        the driver uses it.
        """
        for token in ("pane.x", "570.2, 373.4", "Assumptions only a live run can confirm"):
            assert token in mechanics, token
        assert "The driver no longer uses it" in mechanics
        assert "kept for **manual** work" in mechanics

    def test_the_mechanics_record_the_selection_pane_as_the_way_a_shape_is_selected(self, mechanics):
        assert "Why the driver selects shapes in the Selection Pane" in mechanics
        for token in (
            "2 of 12",
            "`Selection Pane...`",
            "`AXOutline`",
            "153 rows",
            "reverse z-order",
            "`AXStaticText`",
            "**No `AXPress`**",
            "set `AXSelected`",
            "no mouse events",
        ):
            assert token in mechanics, f"computer-use.md does not record {token}"

    def test_the_mechanics_record_the_navigator_as_not_drivable(self, mechanics):
        assert "Why the driver does not select slides" in mechanics
        for token in ("Slide 1 of 17 Slides", "scrolled into view", "76 rejected"):
            assert token in mechanics, token

    def test_the_mechanics_no_longer_claim_thumbnails_are_selectable(self, mechanics):
        rows = [line for line in mechanics.splitlines() if line.startswith("| ") and "kAXSelected" in line]
        assert not rows, f"computer-use.md still lists thumbnail selection as an assumption: {rows}"

    def test_the_mechanics_point_at_the_driver(self, mechanics):
        assert "gui_capture.py" in mechanics and "gui_capture_plan.py" in mechanics

    def test_the_mechanics_record_what_a_read_costs_and_where_the_nodes_are(self, mechanics):
        """The measurements that made the driver's shape necessary, in the file for them.

        ``computer-use.md`` is what the application does, and "a full walk of the window
        is 6.4 s because 762 of its 907 nodes are the Selection Pane" is a fact about the
        application, not about the driver. An operator driving it by hand pays the same
        price; without this they would rediscover it.
        """
        for token in (
            "interprocess round trip",
            "907 nodes",
            "762",
            "6.4 s",
            "17.8 s",
            "7 targets in 28 minutes",
            "`AXToolbar`",
            "`AXTabGroup`",
            "top-level\n  child",
            "same document\n  title",
        ):
            assert token in mechanics, f"computer-use.md does not record {token}"

    def test_the_mechanics_name_every_dependency_the_driver_needs(self, mechanics):
        assert "--with lxml" in mechanics
        assert "Quartz\nis not needed" in mechanics

    def test_the_readme_records_the_measured_cost_and_what_was_done_about_it(self, readme):
        """The figures, not an adjective. A README that said "faster" would say nothing."""
        for token in (
            "7 targets in 28 minutes",
            "6.4 s",
            "17.8 s",
            "907 nodes",
            "2,218 attribute reads per target",
            "19,826",
            "8.9x",
            "AXToolbar",
            "AXTabGroup",
            "stops at every container boundary",
            "never widens back to the window",
        ):
            assert token in readme, f"the README does not record {token}"
        assert str(READ_BUDGET_PER_TARGET) in readme.replace(",", ""), (
            "the README does not state the read budget the tests enforce"
        )

    def test_the_readme_says_what_batching_gives_up(self, readme):
        """A trade has to be stated as a trade, including the part that is a loss.

        The framing this was built to said batching gives up only crash granularity. It
        also gives up separating two targets inside one batch that swapped effects, and a
        README that claimed otherwise would be overstating the evidence a capture carries.
        """
        assert "--batch-size" in readme
        assert "One Save per batch" in readme
        assert "crash granularity" in readme
        assert "swap effects" in readme or "swapped effects" in readme
        assert "no spid outside the batch may have gained an effect" in readme
        assert "batchIndex" in readme and "newEffectCount" in readme

    def test_the_readme_documents_every_dependency_and_the_progress_output(self, readme):
        assert "--with lxml" in readme
        assert "Quartz is not among them" in readme
        assert "**stderr**" in readme and "stdout stays pure JSON" in readme


class TestTheClickableFloorIsAPlannerConstraint:
    """The size that broke a live run has to bind the planner, not just a test.

    A grid of 22 pt shapes took 71 presses and landed them on five shapes. The
    fix doubled the short side, and the number then lived only in
    `test_the_whole_catalog_fits_one_slide` — so the planner stayed free to
    derive a grid that assertion would reject. It did: when 16 more tiles became
    capturable, 92 targets came out at 36.5 pt on one slide.
    """

    def test_no_target_count_is_ever_laid_out_below_the_floor(self):
        floor = planner.MIN_SHAPE_SHORT_SIDE_PX
        for targets in (1, 2, 5, 20, 76, 92, 128, 129, 200, 400):
            deck = planner.grid_layout(targets).as_dict()
            short = min(deck["shapePx"])
            assert short >= floor, (
                f"{targets} targets were laid out at {short} px "
                f"({short / 2} pt), under the {floor} px floor"
            )

    def test_a_count_over_capacity_costs_a_slide_rather_than_a_smaller_shape(self):
        capacity = planner.max_targets_per_slide()
        assert planner.grid_layout(capacity).as_dict()["slides"] == 1
        over = planner.grid_layout(capacity + 1).as_dict()
        assert over["slides"] == 2, over
        assert min(over["shapePx"]) >= planner.MIN_SHAPE_SHORT_SIDE_PX

    def test_the_capacity_is_the_floor_rather_than_the_click_margin(self):
        """Capacity used to be derived from twice the click margin, which is 20 pt.

        That made it claim 286 shapes per slide, a number no capture could have
        clicked. It is 128 under the real constraint.
        """
        assert planner.MIN_SHAPE_SHORT_SIDE_PX > 2 * planner.CLICK_MARGIN_PX
        assert planner.max_targets_per_slide() == 128

    def test_the_captured_seventy_six_still_lay_out_exactly_as_they_were(self):
        """The floor must not have moved the grid the committed evidence was captured on."""
        deck = planner.grid_layout(76).as_dict()
        assert (deck["columns"], deck["rows"]) == (10, 8)
        assert tuple(deck["shapePx"]) == (154, 87)
        assert deck["slides"] == 1
