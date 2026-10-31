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
three ways that each cost the driver a live run if it got them wrong:

- it has **no slide navigator at all**, so a reintroduced ``select_slide`` could not work
  against it;
- its clicks are **hit-tested against the real package geometry**, so a click computed
  from the wrong shape selects the wrong shape rather than being quietly forgiven;
- its Save **writes a real ``p:timing`` tree into the package** and renumbers every
  timing ``id`` while doing it, because nothing offline can promise PowerPoint does not.
"""

from __future__ import annotations

import ast
import copy
import json
import math
import os
import re
import zipfile
from dataclasses import dataclass, field
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

#: The window-relative editor pane and window origin measured on 2026-10-31, with the
#: screen point they produced for a shape centred at (140, 190) pt at 92% zoom. This is a
#: pin on :func:`driver.canvas_point` itself, not on any deck's layout.
MEASURED_PANE_WINDOW = driver.Frame(254, 144, 1258, 540)
MEASURED_WINDOW_ORIGIN = (0.0, 33.0)
MEASURED_ZOOM = 0.92
MEASURED_SLIDE_PT = (960.0, 540.0)
MEASURED_SHAPE_CENTRE = (140.0, 190.0)
MEASURED_SCREEN_POINT = (570.2, 373.4)

#: The title the live editor area carries, verbatim from a 2026-10-31 read.
EDITOR_AREA_TITLE = "Slide Editor Pane, Slide 1 of 1 Slides"

#: The target count the checked-in catalog derives today, and the grid it fits on one
#: slide. Both are asserted against the plan rather than trusted.
EXPECTED_TARGETS = 76
EXPECTED_GRID = (8, 10)


def measured_pane() -> driver.Frame:
    return driver.window_frame_to_screen(MEASURED_PANE_WINDOW, MEASURED_WINDOW_ORIGIN)


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


def shape_rects_pt(package: Path, slide_index: int) -> dict[str, tuple[float, float, float, float]]:
    """Return ``spid -> (x1, y1, x2, y2)`` in slide points for every shape on a slide.

    Read here with its own XML pass rather than through the driver, so the fake's
    hit-testing is not the driver's own idea of where a shape is.
    """
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    with zipfile.ZipFile(package) as archive:
        root = etree.fromstring(archive.read(f"ppt/slides/slide{slide_index}.xml"), parser=parser)
    rects: dict[str, tuple[float, float, float, float]] = {}
    for shape in root.iter():
        if etree.QName(shape).localname != "sp":
            continue
        props = next((el for el in shape.iter() if etree.QName(el).localname == "cNvPr"), None)
        off = next((el for el in shape.iter() if etree.QName(el).localname == "off"), None)
        ext = next((el for el in shape.iter() if etree.QName(el).localname == "ext"), None)
        if props is None or off is None or ext is None:
            continue
        x, y = int(off.get("x")) / 12700, int(off.get("y")) / 12700
        cx, cy = int(ext.get("cx")) / 12700, int(ext.get("cy")) / 12700
        rects[props.get("id")] = (x, y, x + cx, y + cy)
    return rects


# --- the fake accessibility host --------------------------------------------
@dataclass
class FakeNode:
    """One element of a fake accessibility tree, matching :class:`driver.AXNode`."""

    role: str
    title: str | None = None
    value: str | None = None
    enabled: bool = True
    frame: driver.Frame | None = None
    children: list[FakeNode] = field(default_factory=list)
    on_press: Callable[[], None] | None = None
    press_error: str | None = None

    def press(self) -> None:
        if self.press_error:
            raise driver.TargetFailure(self.press_error)
        if self.on_press is not None:
            self.on_press()


ENTRANCE_TILES = ("Fly In", "Fade", "Grow & Turn")
PATH_PRESETS = ("Lines", "Arcs", "Turns")


class FakePowerPoint:
    """A PowerPoint stand-in that rebuilds its tree on every read.

    Nothing here is a cached element: each ``windows()`` call returns new nodes, which is
    how the real application behaves (``computer-use.md``: element identity does not
    survive a read, and a press can scroll a gallery and renumber it).

    It has **no slide navigator**, because the live 2026-10-31 run established that the
    navigator is not drivable: its cells publish no actions and only the few scrolled into
    view exist at all. A driver that still needed one would fail here.

    A click is hit-tested against the package's own shape rectangles, mapped to the screen
    with the same pane and zoom the tree advertises. ``pointer_offset`` shifts where the
    click is taken to land, which is how a mis-aimed click is exercised; a click that hits
    nothing deselects, exactly as clicking empty canvas does.
    """

    def __init__(
        self,
        document: Path,
        *,
        slide_index: int = 1,
        tiles: tuple[str, ...] = ENTRANCE_TILES,
        duplicate_tile: str | None = None,
        applies_effect: bool = True,
        pointer_offset: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        self.document = document
        self.slide_index = slide_index
        self.tiles = tiles
        self.duplicate_tile = duplicate_tile
        self.applies_effect = applies_effect
        self.pointer_offset = pointer_offset
        self.trusted_flag = True
        self.frontmost = driver.BUNDLE_ID
        self.document_title = document.stem
        #: spid -> (presetID, presetClass), replaced per shape exactly as a gallery press
        #: replaces the selected shape's effect.
        self.effects: dict[str, tuple[str, str]] = {}
        self.selected_spid: str | None = None
        self.open_popup: str | None = None
        self.presses: list[tuple[str, str | None]] = []
        self.clicks: list[tuple[float, float]] = []
        self.reads = 0
        self.saves = 0
        self.slept = 0.0
        self._now = 100.0
        self._rects = shape_rects_pt(document, slide_index)

    # --- behaviour --------------------------------------------------------
    @property
    def shape_selected(self) -> bool:
        return self.selected_spid is not None

    def spid_at(self, x: float, y: float) -> str | None:
        """Which shape a click at this screen point lands on, topmost first."""
        pane = measured_pane()
        point = (x + self.pointer_offset[0], y + self.pointer_offset[1])
        for spid in sorted(self._rects, key=int, reverse=True):
            x1, y1, x2, y2 = self._rects[spid]
            top_left = driver.canvas_point(MEASURED_SLIDE_PT, (x1, y1), pane, MEASURED_ZOOM)
            bottom_right = driver.canvas_point(MEASURED_SLIDE_PT, (x2, y2), pane, MEASURED_ZOOM)
            if top_left[0] <= point[0] <= bottom_right[0] and top_left[1] <= point[1] <= bottom_right[1]:
                return spid
        return None

    def _press_tile(self, title: str) -> None:
        self.presses.append((title, self.selected_spid))
        if self.applies_effect and self.selected_spid is not None:
            self.effects[self.selected_spid] = TILE_PRESETS.get(title, DEFAULT_PRESET)

    def _save(self) -> None:
        self.saves += 1
        write_effects(self.document, self.slide_index, self.effects)
        # Guarantees the (mtime, size) pair the driver waits on changes even when the
        # effects did not, so a save is never mistaken for a hang.
        stamp = self.document.stat().st_mtime + 5
        os.utime(self.document, (stamp, stamp))

    # --- the tree ---------------------------------------------------------
    def _gallery(self) -> FakeNode:
        titles = list(self.tiles)
        if self.duplicate_tile:
            titles.append(self.duplicate_tile)
        return FakeNode(
            role="AXGroup",
            title="Entrance Effects",
            enabled=self.shape_selected,
            children=[
                FakeNode(
                    role="AXRadioButton",
                    title=title,
                    enabled=self.shape_selected,
                    on_press=lambda title=title: self._press_tile(title),
                )
                for title in titles
            ],
        )

    def _path_animation_button(self) -> FakeNode:
        return FakeNode(
            role="AXMenuButton",
            title=planner.PATH_ANIMATION_CONTROL,
            enabled=self.shape_selected,
            on_press=lambda: setattr(self, "open_popup", planner.PATH_ANIMATION_CONTROL),
        )

    def _document_window(self) -> FakeNode:
        animated = self.selected_spid in self.effects
        return FakeNode(
            role="AXWindow",
            title=self.document_title,
            frame=driver.Frame(*MEASURED_WINDOW_ORIGIN, 1512, 900),
            children=[
                FakeNode(role="AXButton", title=driver.SAVE_LABEL, on_press=self._save),
                FakeNode(
                    role="AXTabGroup",
                    children=[
                        FakeNode(role="AXRadioButton", title="Transitions"),
                        FakeNode(role="AXRadioButton", title=planner.ANIMATIONS_TAB),
                    ],
                ),
                self._gallery(),
                self._path_animation_button(),
                FakeNode(
                    role="AXPopUpButton",
                    title=driver.START_LABEL,
                    value="On Click" if animated else None,
                ),
                FakeNode(
                    role="AXIncrementor",
                    title=driver.DURATION_LABEL,
                    value="05.00" if animated else None,
                ),
                # The real tree nests a titled editor area inside a framed scroll area,
                # and the driver identifies the pane by that title rather than by being
                # the largest pane of a role — picking the largest returned the outer
                # split that also holds the navigator and the notes, which put every
                # click off its shape. The inner area's own frame lags a ribbon
                # expand/collapse, so the container is what gets measured.
                FakeNode(
                    role="AXScrollArea",
                    frame=measured_pane(),
                    children=[
                        FakeNode(
                            role=driver.EDITOR_PANE_ROLE,
                            # A literal, not the driver's own constant: a test that
                            # changes the prefix the driver looks for must be able to
                            # make the tree stop matching it.
                            title=EDITOR_AREA_TITLE,
                            frame=measured_pane(),
                        )
                    ],
                ),
                FakeNode(role="AXButton", title=f"{int(MEASURED_ZOOM * 100)}%"),
            ],
        )

    def _popup_window(self) -> FakeNode:
        return FakeNode(
            role="AXWindow",
            title=planner.PATH_ANIMATION_CONTROL,
            children=[
                FakeNode(
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

    def windows(self) -> list[Any]:
        self.reads += 1
        windows = [self._document_window()]
        if self.open_popup:
            windows.append(self._popup_window())
        return windows

    def click(self, x: float, y: float) -> None:
        self.clicks.append((x, y))
        self.selected_spid = self.spid_at(x, y)

    def now(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self.slept += seconds
        self._now += seconds


# --- fixtures ---------------------------------------------------------------
@pytest.fixture(scope="module")
def real_plan() -> dict[str, Any]:
    """The plan derived from the checked-in catalog and manifest."""
    return planner.build_plan(
        planner.load_json(planner.DEFAULT_CATALOG), planner.load_json(planner.DEFAULT_MANIFEST)
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

    def test_the_plan_has_targets_and_names_what_it_was_derived_from(self, real_plan):
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

    def test_a_gallery_target_names_the_tab_the_gallery_and_the_tile(self, real_plan):
        by_key = {target["key"]: target for target in real_plan["targets"]}
        target = by_key["animation.gallery.entrance.flyIn"]
        assert target["guiPath"] == [planner.ANIMATIONS_TAB, "Entrance Effects", "Fly In"]
        assert by_key["animation.gallery.exit.flyOut"]["guiPath"][1] == "Exit Effects"
        assert by_key["animation.gallery.emphasis.pulse"]["guiPath"][1] == "Emphasis Effects"

    def test_a_motion_path_goes_through_the_path_animation_window(self, real_plan):
        by_key = {target["key"]: target for target in real_plan["targets"]}
        assert by_key["animation.gallery.motionPath.lines"]["guiPath"] == [
            planner.ANIMATIONS_TAB,
            planner.PATH_ANIMATION_CONTROL,
            "Lines",
        ]

    def test_an_irregular_label_comes_from_the_table_and_keeps_the_derived_form(self, real_plan):
        by_key = {target["key"]: target for target in real_plan["targets"]}
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
        assert "drawn on the canvas" in reasons["animation.gallery.motionPath.custom"]
        assert "media object" in reasons["animation.gallery.media.mediaStop"]
        assert "effect dialog" in reasons["animation.afterAnimation.dim"]
        assert all(reasons.values())

    def test_gaps_without_the_capture_flag_are_listed_rather_than_implied_closed(self, real_plan):
        keys = {entry["key"] for entry in real_plan["gapsWithoutCaptureFlag"]}
        # computer-use.md Steps 3 to 5 are exactly these, and none carries requiresCapture.
        assert "animation.timing.rewind" in keys
        assert "animation.sound.effect" in keys
        assert "animation.start.none" in keys
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
        catalog = planner.load_json(planner.DEFAULT_CATALOG)
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
    """One slide of many shapes, with a layout that is checked rather than eyeballed."""

    def test_the_whole_catalog_fits_one_slide(self, real_plan):
        assert real_plan["counts"]["targets"] == EXPECTED_TARGETS
        deck = real_plan["deck"]
        assert deck["slides"] == 1
        assert deck["split"] is False
        assert (deck["columns"], deck["rows"]) == EXPECTED_GRID
        assert {target["slideIndex"] for target in real_plan["targets"]} == {1}

    def test_every_target_gets_its_own_cell_in_plan_order(self, real_plan):
        cells = [(target["slideIndex"], target["cellIndex"]) for target in real_plan["targets"]]
        assert len(set(cells)) == len(cells)
        assert [target["targetIndex"] for target in real_plan["targets"]] == list(
            range(1, len(real_plan["targets"]) + 1)
        )
        assert [cell for _slide, cell in cells] == list(range(1, len(cells) + 1))

    def test_no_two_shapes_overlap_and_no_shape_leaves_the_slide(self, real_plan):
        rects = [planner.Rect(**target["shapeRectPx"]) for target in real_plan["targets"]]
        for first in range(len(rects)):
            for second in range(first + 1, len(rects)):
                assert not rects[first].overlaps(rects[second]), (first, second)
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

    def test_the_grid_reports_the_basis_it_was_computed_in(self, real_plan):
        deck = real_plan["deck"]
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
            click_point=(570.21, 373.44),
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
        assert record["clickPoint"] == [570.2, 373.4]
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
        after = [{"spid": None, "spids": ["2", "4"], "cTn": {"presetID": "2"}}]
        with pytest.raises(driver.EffectMisattributed, match=r"\['2', '4'\]"):
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
        assert "did not add exactly one" in summary["failures"][0]["error"]["message"]
        # The presses did happen; what failed is the evidence, and it says so.
        assert len(session["fake"].presses) == 3

    def test_a_click_that_lands_on_the_wrong_shape_is_rejected_naming_both_spids(self, session):
        """A mis-aimed click selects the neighbour, so the effect is the neighbour's."""
        geometry = driver.read_canvas_geometry(session["fake"], session["settings"].document)
        targets = session["plan"]["targets"]
        first = geometry.point_for(session["settings"].document, 1, targets[0]["shapeName"])
        second = geometry.point_for(session["settings"].document, 1, targets[1]["shapeName"])
        session["fake"].pointer_offset = (second[0] - first[0], second[1] - first[1])

        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
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

    def test_a_click_that_lands_on_no_shape_is_a_bounded_timeout(self, session):
        session["fake"].pointer_offset = (5_000.0, 5_000.0)
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert summary["failed"] == 3
        assert {failure["error"]["kind"] for failure in summary["failures"]} == {"timeout"}
        assert session["fake"].presses == []

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

    def test_the_driver_no_longer_selects_anything_by_accessibility_attribute(self):
        source = DRIVER_SOURCE.read_text(encoding="utf-8")
        assert "kAXSelectedAttribute" not in source
        assert "HAS_ANIMATION" not in source
        assert not hasattr(driver, "HAS_ANIMATION")
        assert not hasattr(driver, "select_slide")

    def test_the_module_docstring_records_both_live_failures(self):
        doc = driver.__doc__ or ""
        assert "76 records, 0 captured, 76 rejected" in doc
        assert "no actions at all" in doc, "the unselectable navigator cells are not recorded"
        assert "scrolled into view" in doc, "the 6-visible-cells limit is not recorded"
        assert "Do not reintroduce" in doc

    def test_the_fake_powerpoint_has_no_navigator_to_fall_back_on(self, session):
        window = driver.document_window(session["fake"])
        roles = {node.role for node in driver.walk(window)}
        assert not roles & {"AXRow", "AXCell", "AXOutline"}


# --- coordinate derivation --------------------------------------------------
class TestCoordinateDerivation:
    """The canvas click point is computed, because the shape has no AX element."""

    def test_the_measured_session_reproduces_its_own_screen_point(self):
        point = driver.canvas_point(MEASURED_SLIDE_PT, MEASURED_SHAPE_CENTRE, measured_pane(), MEASURED_ZOOM)
        assert point == pytest.approx(MEASURED_SCREEN_POINT, abs=0.05)

    def test_a_window_relative_frame_converts_to_screen(self):
        pane = measured_pane()
        assert (pane.x, pane.y, pane.width, pane.height) == (254, 177, 1258, 540)

    def test_zoom_changes_the_point_and_a_bad_zoom_is_refused(self):
        pane = driver.Frame(0, 0, 1000, 1000)
        at_half = driver.canvas_point((1000, 1000), (100, 100), pane, 0.5)
        assert at_half == pytest.approx((300.0, 300.0))
        with pytest.raises(driver.GeometryError):
            driver.canvas_point((1000, 1000), (100, 100), pane, 0.0)

    def test_the_zoom_comes_from_the_status_bar_title(self):
        assert driver.parse_zoom("92%") == pytest.approx(0.92)
        assert driver.parse_zoom(" 100 % ") == pytest.approx(1.0)
        with pytest.raises(driver.GeometryError):
            driver.parse_zoom("Fit to Window")

    def test_the_slide_size_comes_from_the_package_and_both_readers_agree(self, built_deck):
        assert driver.read_slide_size_pt(built_deck["package"]) == MEASURED_SLIDE_PT
        assert planner.read_slide_size_pt(built_deck["package"]) == MEASURED_SLIDE_PT

    def test_each_shape_centre_in_the_package_is_the_one_the_grid_asked_for(self, built_deck, small_plan):
        slide_w, _slide_h = driver.read_slide_size_pt(built_deck["package"])
        scale = slide_w / planner.DECK_BASIS_PX[0]
        for target in small_plan["targets"]:
            rect = planner.Rect(**target["shapeRectPx"])
            wanted = (rect.center[0] * scale, rect.center[1] * scale)
            centre = driver.read_shape_center_pt(
                built_deck["package"], target["slideIndex"], built_deck["names"][target["key"]]
            )
            assert math.dist(centre, wanted) <= planner.MATCH_TOLERANCE_PT

    def test_the_geometry_is_read_from_the_live_tree_and_the_package(self, session):
        geometry = driver.read_canvas_geometry(session["fake"], session["settings"].document)
        assert geometry.slide_size_pt == MEASURED_SLIDE_PT
        assert geometry.zoom == pytest.approx(MEASURED_ZOOM)
        # The pane is the framed container holding the titled editor area, so the role
        # recorded is the container's and the source names how it was found. Measured:
        # choosing the largest element of a fixed role returned the outer split that also
        # holds the navigator and the notes, and every click then missed its shape.
        assert geometry.source == {
            "paneRole": "AXScrollArea",
            "paneSource": "editorPaneContainer",
            "zoomSource": "statusBar",
            "zoomTitle": "92%",
        }
        target = session["plan"]["targets"][0]
        centre = driver.read_shape_center_pt(session["settings"].document, 1, target["shapeName"])
        assert geometry.point_for(session["settings"].document, 1, target["shapeName"]) == pytest.approx(
            driver.canvas_point(MEASURED_SLIDE_PT, centre, measured_pane(), MEASURED_ZOOM)
        )

    def test_an_operator_override_is_recorded_as_an_override(self, session):
        geometry = driver.read_canvas_geometry(
            session["fake"],
            session["settings"].document,
            pane=driver.Frame(10, 20, 100, 100),
            zoom=0.5,
        )
        assert geometry.source["paneSource"] == "operatorOverride"
        assert geometry.source["zoomSource"] == "operatorOverride"

    def test_a_missing_editor_pane_is_an_actionable_refusal_not_a_guess(self, session, monkeypatch):
        """No titled editor area means no mapping, and the run refuses rather than guessing.

        A guessed pane is not a visible failure: the click lands on empty canvas, the
        previously selected shape stays selected, and the next press silently overwrites
        *its* effect. That is what a live run produced — 71 presses, five effects, one of
        them an entrance class on a shape whose target was an emphasis value.
        """
        monkeypatch.setattr(driver, "EDITOR_PANE_TITLE_PREFIX", "No Such Pane Title")
        with pytest.raises(driver.DriverRefusal, match="--pane-frame"):
            driver.run_capture(session["plan"], session["settings"], session["fake"])

    def test_every_click_lands_on_its_own_target_shape(self, session):
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        fake = session["fake"]
        assert len(fake.clicks) == summary["attempted"] == 3
        assert len(set(fake.clicks)) == 3, "three targets on one slide must click three points"
        for target, point in zip(session["plan"]["targets"], fake.clicks):
            assert fake.spid_at(*point) == session["spids"][target["key"]]

    def test_pane_frame_parsing_refuses_anything_but_four_numbers(self):
        assert driver.parse_pane_frame("1,2,3,4") == driver.Frame(1, 2, 3, 4)
        assert driver.parse_pane_frame(None) is None
        for bad in ("1,2,3", "a,b,c,d", "1,2,0,4"):
            with pytest.raises(ValueError):
                driver.parse_pane_frame(bad)


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
            "scripts/animation_catalog/README.md",
            "scripts/animation_catalog/computer-use.md",
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

    def test_it_refuses_when_powerpoint_is_not_frontmost(self, session):
        session["fake"].frontmost = "com.apple.Terminal"
        with pytest.raises(driver.DriverRefusal, match="frontmost"):
            driver.run_capture(session["plan"], session["settings"], session["fake"])
        assert session["fake"].clicks == []

    def test_it_refuses_a_document_that_is_not_the_capture_deck(self, session):
        session["fake"].document_title = "Q3 Business Review"
        with pytest.raises(driver.DriverRefusal, match="not the expected capture deck"):
            driver.run_capture(session["plan"], session["settings"], session["fake"])
        assert session["fake"].clicks == []

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
        assert session["fake"].clicks == []

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
        # The label wraps onto two lines, and stripping the wrap gives the key back
        # exactly — nothing about the key is abbreviated away.
        texts = {element["text"].replace("\n", ""): element for element in elements}
        for target in small_plan["targets"]:
            assert target["key"] in texts, "a human cannot tell which shape is which target"
            label = texts[target["key"]]
            rect = planner.Rect(**target["shapeRectPx"])
            # Directly under its own shape, same width, so the pairing is unambiguous.
            assert (label["x"], label["y"]) == (rect.x, rect.y + rect.height)
            assert label["width"] == rect.width

    def test_a_wrapped_label_loses_nothing_and_fits_its_box(self, real_plan):
        longest = max((target["key"] for target in real_plan["targets"]), key=len)
        wrapped = planner.label_text(longest)
        assert wrapped.replace("\n", "") == longest
        assert wrapped.count("\n") == 1
        width_pt = real_plan["deck"]["shapePx"][0] / 2
        for line in wrapped.splitlines():
            # Arial's lowercase averages well under 0.5 em, so 0.5 is the pessimistic
            # bound; a line that fits under it fits.
            assert len(line) * planner.LABEL_FONT_PT * 0.5 <= width_pt, line
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
        assert [record["effectCount"] for record in records] == [
            {"before": 0, "after": 1},
            {"before": 1, "after": 2},
            {"before": 2, "after": 3},
        ]

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
        assert outcomes[planner.PATH_ANIMATION_CONTROL] == "openedWindow"
        assert outcomes["Arcs"] == "pressed"

    def test_an_absent_grouping_level_is_recorded_rather_than_fatal(self, session):
        session["fake"].selected_spid = "2"
        result = driver.press_path(
            session["fake"],
            [planner.ANIMATIONS_TAB, planner.PATH_ANIMATION_CONTROL, "Basic", "Lines"],
            timeout=2.0,
        )
        outcomes = {step.title: step.outcome for step in result.steps}
        assert outcomes["Basic"] == "groupAbsent"
        assert outcomes["Lines"] == "pressed"

    def test_a_visible_gallery_is_scoped_into_rather_than_pressed(self, session):
        session["fake"].selected_spid = "2"
        result = driver.press_path(
            session["fake"], [planner.ANIMATIONS_TAB, "Entrance Effects", "Fly In"], timeout=2.0
        )
        outcomes = {step.title: step.outcome for step in result.steps}
        assert outcomes["Entrance Effects"] == "scoped"
        assert session["fake"].presses == [("Fly In", "2")]

    def test_an_alternative_title_is_tried_and_recorded(self, session):
        session["fake"].selected_spid = "2"
        session["fake"].tiles = ("Grow Turn",)
        result = driver.press_path(
            session["fake"],
            [planner.ANIMATIONS_TAB, "Entrance Effects", "Grow & Turn"],
            timeout=2.0,
            alternatives=("Grow Turn",),
        )
        assert result.matched_title == "Grow Turn"
        assert session["fake"].presses == [("Grow Turn", "2")]

    def test_the_shape_is_selected_by_a_click_because_it_has_no_element(self, session):
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert len(session["fake"].clicks) == summary["attempted"]

    def test_save_is_pressed_once_per_target_so_a_crash_costs_one(self, session):
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
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

    def test_the_summary_reports_the_derived_canvas_mapping(self, session):
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert summary["canvas"]["slideSizePt"] == list(MEASURED_SLIDE_PT)
        assert summary["canvas"]["zoom"] == pytest.approx(MEASURED_ZOOM)
        assert summary["canvas"]["paneFrame"] == [254, 177, 1258, 540]


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

    def test_the_readme_discloses_that_the_pointer_moves_and_the_guard(self, readme):
        assert "moves the real pointer" in readme
        assert "refuses to start" in readme and "frontmost" in readme

    def test_the_readme_describes_the_grid_the_plan_derives(self, readme, real_plan):
        deck = real_plan["deck"]
        assert f"{deck['columns']}x{deck['rows']}" in readme, "the README does not state the derived grid"
        assert "one slide" in readme
        assert "spid" in readme

    def test_the_readme_records_why_slide_navigation_is_gone(self, readme):
        assert "76 rejected" in readme
        assert "scrolled into view" in readme

    def test_the_mechanics_name_every_gallery_control_the_plan_emits(self, mechanics, real_plan):
        controls = {target["guiPath"][1] for target in real_plan["targets"]}
        missing = sorted(control for control in controls if f"`{control}`" not in mechanics)
        assert not missing, f"control names the plan emits but computer-use.md does not record: {missing}"

    def test_the_mechanics_record_the_canvas_formula_and_its_check(self, mechanics):
        for token in ("pane.x", "570.2, 373.4", "Assumptions only a live run can confirm"):
            assert token in mechanics, token

    def test_the_mechanics_record_the_navigator_as_not_drivable(self, mechanics):
        assert "Why the driver does not select slides" in mechanics
        for token in ("Slide 1 of 17 Slides", "scrolled into view", "76 rejected"):
            assert token in mechanics, token

    def test_the_mechanics_no_longer_claim_thumbnails_are_selectable(self, mechanics):
        rows = [line for line in mechanics.splitlines() if line.startswith("| ") and "kAXSelected" in line]
        assert not rows, f"computer-use.md still lists thumbnail selection as an assumption: {rows}"

    def test_the_mechanics_point_at_the_driver(self, mechanics):
        assert "gui_capture.py" in mechanics and "gui_capture_plan.py" in mechanics
