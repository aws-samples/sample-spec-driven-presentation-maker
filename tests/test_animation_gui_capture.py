# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The GUI capture driver and its plan, verified without PowerPoint and without pyobjc.

The driver's job is to replace a four-call-per-value agent round trip with one script, so
what matters is that everything *except* the accessibility API is settled offline: the
plan is derived from the catalog's own gaps rather than typed out, the click point is
computed from the package and the live frames rather than hardcoded, a failed target is
recorded and the run continues, a resumed run neither repeats nor loses work, and the
record shape is the one ``generate.py --parse-oracle`` already consumes.

The accessibility layer is injected, so every test here runs against a fake PowerPoint
that re-renders its tree on each read — which is also how the "re-resolve by title before
every press" rule gets exercised rather than assumed.
"""

from __future__ import annotations

import ast
import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pytest

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
#: screen point they produced for a shape centred at (140, 190) pt at 92% zoom.
MEASURED_PANE_WINDOW = driver.Frame(254, 144, 1258, 540)
MEASURED_WINDOW_ORIGIN = (0.0, 33.0)
MEASURED_ZOOM = 0.92
MEASURED_SLIDE_PT = (960.0, 540.0)
MEASURED_SHAPE_CENTRE = (140.0, 190.0)
MEASURED_SCREEN_POINT = (570.2, 373.4)


# --- the fake accessibility host --------------------------------------------
@dataclass
class FakeNode:
    """One element of a fake accessibility tree, matching :class:`driver.AXNode`."""

    role: str
    title: str | None = None
    value: str | None = None
    enabled: bool = True
    selected: bool = False
    frame: driver.Frame | None = None
    children: list[FakeNode] = field(default_factory=list)
    on_press: Callable[[], None] | None = None
    on_select: Callable[[], None] | None = None
    press_error: str | None = None

    def press(self) -> None:
        if self.press_error:
            raise driver.TargetFailure(self.press_error)
        if self.on_press is not None:
            self.on_press()

    def select(self) -> None:
        if self.on_select is not None:
            self.on_select()
        else:
            self.press()


ENTRANCE_TILES = ("Fly In", "Fade", "Grow & Turn")
PATH_PRESETS = ("Lines", "Arcs", "Turns")


class FakePowerPoint:
    """A PowerPoint stand-in that rebuilds its tree on every read.

    Nothing here is a cached element: each ``windows()`` call returns new nodes, which is
    how the real application behaves (``computer-use.md``: element identity does not
    survive a read, and a press can scroll a gallery and renumber it).
    """

    def __init__(
        self,
        document: Path,
        slide_count: int,
        *,
        tiles: tuple[str, ...] = ENTRANCE_TILES,
        duplicate_tile: str | None = None,
        never_animates: bool = False,
    ) -> None:
        self.document = document
        self.slide_count = slide_count
        self.tiles = tiles
        self.duplicate_tile = duplicate_tile
        self.never_animates = never_animates
        self.trusted_flag = True
        self.frontmost = driver.BUNDLE_ID
        self.document_title = document.stem
        self.animated: set[int] = set()
        self.selected_slide = 1
        self.shape_selected = False
        self.open_popup: str | None = None
        self.presses: list[tuple[str, int]] = []
        self.clicks: list[tuple[float, float]] = []
        self.reads = 0
        self.saves = 0
        self.slept = 0.0
        self._now = 100.0

    # --- behaviour --------------------------------------------------------
    def _press_tile(self, title: str) -> None:
        self.presses.append((title, self.selected_slide))
        if not self.never_animates:
            self.animated.add(self.selected_slide)

    def _select_slide(self, index: int) -> None:
        self.selected_slide = index
        self.shape_selected = False

    def _save(self) -> None:
        self.saves += 1
        stamp = self.document.stat().st_mtime + 5
        os.utime(self.document, (stamp, stamp))

    # --- the tree ---------------------------------------------------------
    def _thumbnails(self) -> FakeNode:
        rows = []
        for index in range(1, self.slide_count + 1):
            title = f"Slide {index}"
            if index in self.animated:
                title += f" {driver.HAS_ANIMATION}"
            rows.append(
                FakeNode(
                    role="AXRow",
                    title=title,
                    selected=index == self.selected_slide,
                    frame=driver.Frame(0, 150 + 130 * (index - 1), 250, 118),
                    on_select=lambda index=index: self._select_slide(index),
                )
            )
        return FakeNode(role="AXOutline", title="Slide Navigator", children=rows)

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
        animated = self.selected_slide in self.animated
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
                self._thumbnails(),
                FakeNode(
                    role=driver.EDITOR_PANE_ROLE,
                    frame=driver.window_frame_to_screen(MEASURED_PANE_WINDOW, MEASURED_WINDOW_ORIGIN),
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
        self.shape_selected = True

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
    return {
        "plan": "test",
        "shapeName": None,
        "targets": [
            {
                "key": "animation.gallery.entrance.flyIn",
                "slideIndex": 1,
                "guiPath": [planner.ANIMATIONS_TAB, "Entrance Effects", "Fly In"],
                "titleAlternatives": [],
            },
            {
                "key": "animation.gallery.entrance.growTurn",
                "slideIndex": 2,
                "guiPath": [planner.ANIMATIONS_TAB, "Entrance Effects", "Grow & Turn"],
                "titleAlternatives": ["Grow Turn"],
            },
            {
                "key": "animation.gallery.motionPath.lines",
                "slideIndex": 3,
                "guiPath": [planner.ANIMATIONS_TAB, planner.PATH_ANIMATION_CONTROL, "Basic", "Lines"],
                "titleAlternatives": [],
            },
        ],
    }


@pytest.fixture(scope="module")
def built_deck(small_plan, tmp_path_factory) -> dict[str, Any]:
    """Build the capture deck from the small plan, once, through sdpm."""
    root = tmp_path_factory.mktemp("capture")
    deck = root / "deck"
    planner.build_capture_deck(small_plan, deck)
    result = planner.generate_capture_deck(deck, root / "capture-deck.pptx")
    return {
        "deck": deck,
        "package": Path(result["output_path"]),
        "result": result,
        "shapeName": planner.resolve_shape_name(Path(result["output_path"])),
    }


@pytest.fixture
def session(small_plan, built_deck, tmp_path):
    """A runnable session: the built package, a fake PowerPoint, and settings."""
    document = tmp_path / f"{built_deck['package'].stem}.pptx"
    document.write_bytes(built_deck["package"].read_bytes())
    fake = FakePowerPoint(document, slide_count=len(small_plan["targets"]))
    settings = driver.CaptureSettings(
        out_dir=tmp_path / "out",
        document=document,
        shape_name=built_deck["shapeName"],
        timeout=2.0,
    )
    return {"plan": copy.deepcopy(small_plan), "fake": fake, "settings": settings}


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
        for name, count in real_plan["counts"].items():
            assert len(real_plan[name]) == count, name

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

    def test_slide_indices_are_dense_and_in_plan_order(self, real_plan):
        indices = [target["slideIndex"] for target in real_plan["targets"]]
        assert indices == list(range(1, len(indices) + 1))

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

    def test_a_capture_record_carries_the_key_slide_application_readback_and_label(self):
        target = {
            "key": "animation.gallery.entrance.flyIn",
            "slideIndex": 7,
            "guiPath": ["Animations", "Entrance Effects", "Fly In"],
        }
        record = driver.capture_record(
            target,
            applied="Animations > Entrance Effects > Fly In",
            matched_title="Fly In",
            readback={"start": "On Click", "duration": "05.00"},
            thumbnail=f"Slide 7 {driver.HAS_ANIMATION}",
            steps=[{"title": "Fly In", "outcome": "pressed", "role": "AXRadioButton"}],
            saved=True,
        )
        assert record["catalogKey"] == target["key"]
        assert record["slideIndex"] == 7
        assert record["applied"] == "Animations > Entrance Effects > Fly In"
        assert record["ribbonReadBack"] == {"start": "On Click", "duration": "05.00"}
        assert record["thumbnailLabel"].endswith(driver.HAS_ANIMATION)
        assert record["hasAnimation"] is True
        assert record["rejected"] is False
        assert record["error"] is None
        assert record["resolvedBy"] == driver.RESOLVED_BY
        assert record["saved"] is True

    def test_a_rejected_record_keeps_its_error_and_claims_no_resolver(self):
        record = driver.capture_record(
            {"key": "animation.gallery.entrance.whip", "slideIndex": 3, "guiPath": ["Animations", "g", "Whip"]},
            rejected=True,
            error=driver.ControlNotFound("no element titled 'Whip'").as_error(),
        )
        assert record["rejected"] is True
        assert record["resolvedBy"] is None
        assert record["error"] == {"kind": "controlNotFound", "message": "no element titled 'Whip'"}
        assert record["hasAnimation"] is False

    def test_a_gui_record_has_no_scripting_code_it_did_not_measure(self):
        record = driver.capture_record(
            {"key": "animation.gallery.entrance.flyIn", "slideIndex": 1, "guiPath": ["a", "b", "c"]}
        )
        assert record["code"] is None
        assert record["enum"] == driver.RECORD_ENUM
        assert record["enumerator"] == record["catalogKey"]

    def test_parse_oracle_joins_the_records_to_a_package_by_slide_index(self):
        records = [
            driver.application_record("16.113.1"),
            driver.capture_record(
                {"key": "animation.gallery.entrance.flyIn", "slideIndex": 1,
                 "guiPath": ["Animations", "Entrance Effects", "Fly In"]},
                applied="Animations > Entrance Effects > Fly In",
                thumbnail=f"Slide 1 {driver.HAS_ANIMATION}",
            ),
            driver.capture_record(
                {"key": "animation.gallery.entrance.whip", "slideIndex": 2,
                 "guiPath": ["Animations", "Entrance Effects", "Whip"]},
                rejected=True,
                error=driver.ControlNotFound("absent").as_error(),
            ),
        ]
        package = {
            "package": driver.PACKAGE_NAME,
            "slideCount": 2,
            "slides": {
                "1": {"part": "ppt/slides/slide1.xml", "transition": [],
                      "timing": [{"element": "p:cTn", "attributes": {"presetID": "2"}}]},
                "2": {"part": "ppt/slides/slide2.xml", "transition": [], "timing": []},
            },
        }
        merged = merge_oracle_readback(records, package)
        assert merged["candidateRecords"] == 2
        first = merged["candidates"][0]
        assert first["key"] == f"{driver.RECORD_ENUM}.animation.gallery.entrance.flyIn"
        assert first["slideIndex"] == 1
        assert first["ooxml"]["timing"][0]["attributes"]["presetID"] == "2"
        assert first["rejected"] is False
        # The failed target is named as unresolved rather than vanishing from the join.
        assert f"{driver.RECORD_ENUM}.animation.gallery.entrance.whip" in merged["unresolvedCandidates"]


# --- resume -----------------------------------------------------------------
class TestResume:
    """An output directory with records is resumed, not redone and not skipped blindly."""

    def _record(self, key: str, index: int, *, rejected: bool = False) -> dict[str, Any]:
        return driver.capture_record(
            {"key": key, "slideIndex": index, "guiPath": ["Animations", "Entrance Effects", "X"]},
            rejected=rejected,
            error={"kind": "controlNotFound", "message": "absent"} if rejected else None,
        )

    def test_captured_keys_ignores_rejected_records(self):
        records = [self._record("a", 1), self._record("b", 2, rejected=True)]
        assert driver.captured_keys(records) == {"a"}

    def test_a_captured_target_is_skipped_and_a_failed_one_is_retried(self):
        targets = [{"key": "a"}, {"key": "b"}, {"key": "c"}]
        records = [self._record("a", 1), self._record("b", 2, rejected=True)]
        todo, skipped = driver.split_plan(targets, records, force=False)
        assert [target["key"] for target in todo] == ["b", "c"]
        assert skipped == ["a"]

    def test_force_reruns_everything(self):
        targets = [{"key": "a"}, {"key": "b"}]
        todo, skipped = driver.split_plan(targets, [self._record("a", 1)], force=True)
        assert [target["key"] for target in todo] == ["a", "b"]
        assert skipped == []

    def test_retained_records_drop_only_the_targets_being_rerun(self):
        records = [self._record("a", 1), self._record("b", 2), {"record": "application"}]
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

    def test_a_resumed_run_rewrites_the_header_and_keeps_the_prior_records(self, session):
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        lines = session["settings"].readback_path.read_text(encoding="utf-8").strip().splitlines()
        assert json.loads(lines[0])["record"] == "application"
        assert summary["retainedRecords"] == 3


# --- failure recording ------------------------------------------------------
class TestFailureRecording:
    """One bad target costs one record. This is the lesson of the 2026-10-31 run."""

    def test_a_missing_control_is_recorded_and_the_run_continues(self, session):
        session["plan"]["targets"][1]["guiPath"][-1] = "No Such Tile"
        session["plan"]["targets"][1]["titleAlternatives"] = []
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert summary["attempted"] == 3
        assert summary["captured"] == 2
        assert summary["failed"] == 1
        assert summary["failures"][0]["error"]["kind"] == "controlNotFound"
        # The target after the failure still ran.
        assert ("Lines", 3) in session["fake"].presses

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
        assert ("Fly In", 1) not in session["fake"].presses

    def test_a_verification_that_never_arrives_is_a_bounded_timeout(self, session):
        session["fake"].never_animates = True
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert summary["failed"] == 3
        assert {failure["error"]["kind"] for failure in summary["failures"]} == {"timeout"}
        assert driver.HAS_ANIMATION in summary["failures"][0]["error"]["message"]

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

    def test_wait_until_is_bounded_and_reports_what_it_waited_for(self):
        fake = FakePowerPoint(Path("/nonexistent.pptx"), slide_count=1)
        with pytest.raises(driver.DriverTimeout, match="the thumbnail"):
            driver.wait_until(fake, lambda: None, timeout=1.0, what="the thumbnail")
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


# --- coordinate derivation --------------------------------------------------
class TestCoordinateDerivation:
    """The canvas click point is computed, because the shape has no AX element."""

    def test_the_measured_session_reproduces_its_own_screen_point(self):
        pane = driver.window_frame_to_screen(MEASURED_PANE_WINDOW, MEASURED_WINDOW_ORIGIN)
        point = driver.canvas_point(MEASURED_SLIDE_PT, MEASURED_SHAPE_CENTRE, pane, MEASURED_ZOOM)
        assert point == pytest.approx(MEASURED_SCREEN_POINT, abs=0.05)

    def test_a_window_relative_frame_converts_to_screen(self):
        pane = driver.window_frame_to_screen(MEASURED_PANE_WINDOW, MEASURED_WINDOW_ORIGIN)
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

    def test_the_slide_size_and_shape_centre_come_from_the_package(self, built_deck):
        assert driver.read_slide_size_pt(built_deck["package"]) == MEASURED_SLIDE_PT
        centre = driver.read_shape_center_pt(built_deck["package"], 1, built_deck["shapeName"])
        # The committed deck layout reproduces the geometry the 2026-10-31 session measured.
        assert centre == pytest.approx(MEASURED_SHAPE_CENTRE)

    def test_a_shape_the_package_does_not_have_names_the_ones_it_does(self, built_deck):
        with pytest.raises(driver.GeometryError, match="shapes present"):
            driver.read_shape_center_pt(built_deck["package"], 1, "no-such-shape")

    def test_the_geometry_is_read_from_the_live_tree_and_the_package(self, session, built_deck):
        geometry = driver.read_canvas_geometry(session["fake"], session["settings"].document)
        assert geometry.slide_size_pt == MEASURED_SLIDE_PT
        assert geometry.zoom == pytest.approx(MEASURED_ZOOM)
        assert geometry.source == {
            "paneRole": driver.EDITOR_PANE_ROLE,
            "paneSource": "accessibilityTree",
            "zoomSource": "statusBar",
            "zoomTitle": "92%",
        }
        point = geometry.point_for(session["settings"].document, 1, built_deck["shapeName"])
        assert point == pytest.approx(MEASURED_SCREEN_POINT, abs=0.05)

    def test_an_operator_override_is_recorded_as_an_override(self, session):
        geometry = driver.read_canvas_geometry(
            session["fake"],
            session["settings"].document,
            pane=driver.Frame(10, 20, 100, 100),
            zoom=0.5,
        )
        assert geometry.source["paneSource"] == "operatorOverride"
        assert geometry.source["zoomSource"] == "operatorOverride"

    def test_a_missing_editor_pane_is_an_actionable_refusal_not_a_guess(self, session):
        session["settings"].pane_role = "AXNoSuchRole"
        with pytest.raises(driver.DriverRefusal, match="--pane-role"):
            driver.run_capture(session["plan"], session["settings"], session["fake"])

    def test_the_click_lands_on_the_derived_point(self, session, built_deck):
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert session["fake"].clicks[0] == pytest.approx(MEASURED_SCREEN_POINT, abs=0.05)
        assert len(session["fake"].clicks) == 3

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

    def test_a_plan_without_a_shape_name_refuses_rather_than_assuming_one(self, tmp_path, capsys):
        plan = tmp_path / "plan.json"
        plan.write_text(json.dumps({"targets": []}), encoding="utf-8")
        document = tmp_path / "deck.pptx"
        document.write_bytes(b"x")
        code = driver.main(
            ["--plan", str(plan), "--out", str(tmp_path), "--document", str(document), driver.DRIVE_TOKEN]
        )
        assert code == 2
        assert "shapeName" in capsys.readouterr().err


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
    """One slide per target, one named shape, and no motion contributed by sdpm."""

    def test_one_slide_per_target_with_the_key_as_visible_text(self, small_plan, built_deck):
        slides = sorted((built_deck["deck"] / "slides").glob("*.json"))
        assert len(slides) == len(small_plan["targets"])
        first = json.loads(slides[0].read_text(encoding="utf-8"))
        texts = [element.get("text") for element in first["elements"]]
        assert small_plan["targets"][0]["key"] in texts
        assert "Animations > Entrance Effects > Fly In" in texts
        assert [element["id"] for element in first["elements"]][0] == planner.SHAPE_ELEMENT_ID

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
        import zipfile

        with zipfile.ZipFile(built_deck["package"]) as archive:
            for name in archive.namelist():
                blob = archive.read(name)
                assert b"<p:timing" not in blob, name
                assert b"<p:transition" not in blob, name

    def test_the_shape_name_is_read_back_from_the_package_not_assumed(self, built_deck):
        assert built_deck["shapeName"] == planner.resolve_shape_name(built_deck["package"])
        assert built_deck["shapeName"]

    def test_an_empty_plan_has_no_deck(self, tmp_path):
        with pytest.raises(ValueError, match="no targets"):
            planner.build_capture_deck({"targets": []}, tmp_path / "deck")

    def test_a_package_with_two_candidate_shapes_refuses_to_name_one(self, small_plan, tmp_path):
        plan = copy.deepcopy(small_plan)
        deck = tmp_path / "deck"
        planner.build_capture_deck(plan, deck)
        slide = deck / "slides" / "t001.json"
        data = json.loads(slide.read_text(encoding="utf-8"))
        data["elements"].append({**data["elements"][0], "id": "second", "y": 100})
        slide.write_text(json.dumps(data), encoding="utf-8")
        result = planner.generate_capture_deck(deck, tmp_path / "two.pptx")
        with pytest.raises(ValueError, match="expected exactly one"):
            planner.resolve_shape_name(Path(result["output_path"]))


# --- the loop, against the fake ---------------------------------------------
class TestDrivingOneSlidePerTarget:
    """The whole loop: one slide per target, re-read before every press, save each time."""

    def test_a_whole_plan_runs_and_writes_one_record_per_target(self, session):
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert (summary["planned"], summary["attempted"], summary["captured"], summary["failed"]) == (3, 3, 3, 0)
        records = driver.read_records(session["settings"].readback_path)
        assert records[0]["record"] == "application"
        assert [record["catalogKey"] for record in records[1:]] == [
            target["key"] for target in session["plan"]["targets"]
        ]
        assert all(record["hasAnimation"] for record in records[1:])
        assert all(record["ribbonReadBack"]["start"] == "On Click" for record in records[1:])
        assert all(record["ribbonReadBack"]["duration"] == "05.00" for record in records[1:])

    def test_each_press_lands_on_the_slide_the_target_names(self, session):
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert session["fake"].presses == [("Fly In", 1), ("Grow & Turn", 2), ("Lines", 3)]

    def test_the_tree_is_re_read_more_often_than_it_is_pressed(self, session):
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert session["fake"].reads > len(session["fake"].presses) * 2

    def test_the_motion_path_press_happens_in_the_popup_window(self, session):
        plan = {"targets": [session["plan"]["targets"][2]]}
        result = driver.press_path(
            session["fake"],
            plan["targets"][0]["guiPath"],
            timeout=2.0,
        )
        assert session["fake"].open_popup == planner.PATH_ANIMATION_CONTROL
        assert result.matched_title == "Lines"
        outcomes = {step.title: step.outcome for step in result.steps}
        assert outcomes[planner.PATH_ANIMATION_CONTROL] == "openedWindow"
        assert outcomes["Lines"] == "pressed"

    def test_an_absent_grouping_level_is_recorded_rather_than_fatal(self, session):
        session["fake"].shape_selected = True
        result = driver.press_path(
            session["fake"],
            [planner.ANIMATIONS_TAB, planner.PATH_ANIMATION_CONTROL, "Basic", "Lines"],
            timeout=2.0,
        )
        outcomes = {step.title: step.outcome for step in result.steps}
        assert outcomes["Basic"] == "groupAbsent"
        assert outcomes["Lines"] == "pressed"

    def test_a_visible_gallery_is_scoped_into_rather_than_pressed(self, session):
        session["fake"].shape_selected = True
        result = driver.press_path(
            session["fake"], [planner.ANIMATIONS_TAB, "Entrance Effects", "Fly In"], timeout=2.0
        )
        outcomes = {step.title: step.outcome for step in result.steps}
        assert outcomes["Entrance Effects"] == "scoped"
        assert session["fake"].presses == [("Fly In", 1)]

    def test_an_alternative_title_is_tried_and_recorded(self, session):
        session["fake"].shape_selected = True
        session["fake"].tiles = ("Grow Turn",)
        result = driver.press_path(
            session["fake"],
            [planner.ANIMATIONS_TAB, "Entrance Effects", "Grow & Turn"],
            timeout=2.0,
            alternatives=("Grow Turn",),
        )
        assert result.matched_title == "Grow Turn"
        assert session["fake"].presses == [("Grow Turn", 1)]

    def test_the_shape_is_selected_by_a_click_because_it_has_no_element(self, session):
        summary = driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert len(session["fake"].clicks) == summary["attempted"]

    def test_save_is_pressed_once_per_target_so_a_crash_costs_one(self, session):
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert session["fake"].saves == 3

    def test_no_save_means_no_save(self, session):
        session["settings"].save_each = False
        driver.run_capture(session["plan"], session["settings"], session["fake"], version="16.113.1")
        assert session["fake"].saves == 0

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
        assert merged["slideCount"] == 3
        assert merged["candidateRecords"] == 3
        keys = [candidate["key"] for candidate in merged["candidates"]]
        assert keys == [f"{driver.RECORD_ENUM}.{target['key']}" for target in session["plan"]["targets"]]
        # The fake applies nothing to the file, so every slide is honestly unresolved
        # rather than being credited with OOXML the package does not contain.
        assert merged["unresolvedCandidates"] == sorted(keys)

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
        for name, count in real_plan["counts"].items():
            row = next((line for line in readme.splitlines() if line.startswith(f"| `{name}` |")), None)
            assert row, f"the README has no counts row for {name}"
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            assert cells[1] == str(count), f"README says {name} is {cells[1]}, the plan derives {count}"

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

    def test_the_mechanics_name_every_gallery_control_the_plan_emits(self, mechanics, real_plan):
        controls = {target["guiPath"][1] for target in real_plan["targets"]}
        missing = sorted(control for control in controls if f"`{control}`" not in mechanics)
        assert not missing, f"control names the plan emits but computer-use.md does not record: {missing}"

    def test_the_mechanics_record_the_canvas_formula_and_its_check(self, mechanics):
        for token in ("pane.x", "570.2, 373.4", "Assumptions only a live run can confirm"):
            assert token in mechanics, token

    def test_the_mechanics_point_at_the_driver(self, mechanics):
        assert "gui_capture.py" in mechanics and "gui_capture_plan.py" in mechanics
