#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Generate and check the checked-in PowerPoint animation/transition catalog.

The catalog is derived from three independent inputs:

1. the locally installed PowerPoint scripting definition (``PowerPoint.sdef``),
   which supplies the candidate universe (enumerator names and codes);
2. the OOXML evidence tables in this module, which record what retail
   PowerPoint actually writes for each gallery tile; and
3. the checked-in, hand-maintained GUI-surface manifest, which is the expected
   universe of GUI controls/values and their expected disposition.

``--write`` regenerates the catalog deterministically. ``--check`` compares the
local sdef candidate set, the manifest and the catalog, and fails on missing or
extra candidates, missing required metadata, unaccounted GUI items, missing
semanticJson/ooxml on accepted entries, and status drift. Neither mode uses the
network, launches PowerPoint, or runs AppleScript/VBA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SDEF = Path("/Applications/Microsoft PowerPoint.app/Contents/Resources/PowerPoint.sdef")
DEFAULT_MANIFEST = REPO_ROOT / "sdpm/references/catalogs/powerpoint-gui-surface-16.113.1.json"
DEFAULT_CATALOG = REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"

CATALOG_SCHEMA_VERSION = 1
BASELINE_APPLICATION = "Microsoft PowerPoint"
BASELINE_VERSION = "16.113.1"
BASELINE_PLATFORM = "macOS"
# Fixed catalog-generation timestamp (REQ-7.2): only an intentional baseline
# regeneration may change it, so regeneration stays byte-deterministic.
BASELINE_GENERATED_AT = "2026-10-30T00:00:00Z"

STATUSES = ("accepted", "rejected", "nonPersisted", "outOfScope")
CAPABILITY_LEVELS = ("nativeTemplate", "presetMapping", "semanticPreservationOnly")

#: The eight sdef enumerations that form the required candidate universe.
CANDIDATE_ENUMS: dict[str, int] = {
    "MsoAnimEffect": 150,
    "MsoAnimDirection": 45,
    "MsoAnimTriggerType": 5,
    "MsoAnimateByLevel": 12,
    "MsoAnimTextUnitEffect": 3,
    "MsoAnimAfterEffect": 4,
    "MsoAnimType": 9,
    "EPPEntryEffect": 207,
}

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
P15_NS = "http://schemas.microsoft.com/office/powerpoint/2012/main"
P159_NS = "http://schemas.microsoft.com/office/powerpoint/2015/09/main"

#: Versioned AlternateContent support set (REQ-5.4a).
ALTERNATE_CONTENT = {
    "choiceSelection": (
        "evaluate mc:Choice in document order against the supported Requires set, "
        "take the first satisfied Choice, else mc:Fallback, else raw fallback"
    ),
    "supported": [
        {"prefix": "p14", "requires": "p14", "uri": P14_NS, "office": "2010"},
        {"prefix": "p15", "requires": "p15", "uri": P15_NS, "office": "2013"},
        {"prefix": "p159", "requires": "p159", "uri": P159_NS, "office": "2016"},
    ],
    "fallbackObserved": "p:fade for extension transitions; the same standard element when the Choice is a standard element",
}

#: Legacy ``spd`` buckets. slow/med are evidenced by captures that carry no
#: ``p14:dur`` (push spd="slow" -> ribbon 01.00; uncover spd="med" -> 00.75).
LEGACY_SPEED_MS = {"slow": 1000, "med": 750, "fast": 500}
LEGACY_SPEED_EVIDENCE = "slow/med evidenced by native capture; fast inferred from the same bucket scheme"

PROVENANCE_REFERENCES = [
    {
        "id": "office-kit/pptx",
        "url": "https://github.com/office-kit/pptx",
        "commit": "18b7e75cfa7fd1c6e9891ce1285a76c7889b644b",
        "license": "MIT",
        "use": (
            "read-only primary evidence: 95 gallery animation native fixtures, 3 text-build "
            "fixtures and 49 transition gallery fixtures saved by PowerPoint for Mac 16.113.3 "
            "(test/fixtures/native/{animations,transitions}), plus test/fixtures/SOURCES.md capture provenance"
        ),
        "fixtureCorpusDigest": "sha256:71715aa88affbc645166c9bedf1233249c14e74659062eb9e803c54e81056859",
        "fixtureCorpusFiles": 147,
        "capturedApplicationVersion": "16.113.3",
        "vendored": False,
        "note": "no upstream code or fixture bytes are copied into this repository; the OOXML facts were re-derived and the generator is original",
    },
    {
        "id": "ChristopherVR/ooxml",
        "url": "https://github.com/ChristopherVR/ooxml",
        "commit": "e269a0bb944062871e5bcd05856ce65570e2e137",
        "license": "Apache-2.0",
        "use": (
            "read-only cross-check: COM-derived entrance/exit and emphasis presetID tables "
            "(src/core/pptx/core/utils/animation-preset-catalog*.ts, "
            "src/ui/src/pptx/render/animation-preset-ground-truth.ts), including its explicit "
            "statement that the MsoAnimEffect ordinal and the OOXML presetID diverge above 31"
        ),
        "vendored": False,
        "note": "used only to corroborate presetID facts; no code copied",
    },
    {
        "id": "powerpoint-sdef",
        "url": "file:///Applications/Microsoft%20PowerPoint.app/Contents/Resources/PowerPoint.sdef",
        "commit": None,
        "license": "Microsoft PowerPoint for Mac 16.113.1 (local installation, not redistributed)",
        "use": "candidate universe: enumerator names and four-char codes for the eight required enumerations",
        "vendored": False,
        "note": "read locally; no Apple Events are sent and PowerPoint is never launched",
    },
]

# ---------------------------------------------------------------------------
# Transition evidence (49 captured Transitions-gallery tiles)
# ---------------------------------------------------------------------------
# slug, label, group, strategy, element, attrs, durationMs, spd, fallback
TRANSITION_TILES: tuple[tuple[Any, ...], ...] = (
    ("none", "None", "0_0", "none", None, {}, None, None, None),
    ("morph", "Morph", "0_1", "p159", "p159:morph", {"option": "byObject"}, 2000, "slow", "p:fade"),
    ("fade", "Fade", "0_2", "standard", "p:fade", {}, 700, "med", "p:fade"),
    ("push", "Push", "0_3", "standard", "p:push", {"dir": "u"}, 1000, "slow", None),
    ("wipe", "Wipe", "0_4", "standard", "p:wipe", {}, 1000, "slow", None),
    ("split", "Split", "0_5", "standard", "p:split", {"orient": "vert"}, 1500, "slow", "p:split"),
    ("reveal", "Reveal", "0_6", "p14", "p14:reveal", {}, 3400, "slow", "p:fade"),
    ("cut", "Cut", "0_7", "standard", "p:cut", {}, 100, None, "p:cut"),
    ("randomBar", "Random Bars", "0_8", "standard", "p:randomBar", {"dir": "vert"}, 1000, "slow", None),
    ("shape", "Shape", "0_9", "standard", "p:circle", {}, 800, "slow", "p:circle"),
    ("uncover", "Uncover", "0_10", "standard", "p:pull", {}, 750, "med", None),
    ("cover", "Cover", "0_11", "standard", "p:cover", {}, 1000, "slow", None),
    ("flash", "Flash", "0_12", "p14", "p14:flash", {}, 1000, "slow", "p:fade"),
    ("fallOver", "Fall Over", "1_0", "p15", "p15:prstTrans", {"prst": "fallOver"}, 2000, "slow", "p:fade"),
    ("drape", "Drape", "1_1", "p15", "p15:prstTrans", {"prst": "drape"}, 2000, "slow", "p:fade"),
    ("curtains", "Curtains", "1_2", "p15", "p15:prstTrans", {"prst": "curtains"}, 6000, "slow", "p:fade"),
    ("wind", "Wind", "1_3", "p15", "p15:prstTrans", {"prst": "wind"}, 2000, "slow", "p:fade"),
    ("prestige", "Prestige", "1_4", "p15", "p15:prstTrans", {"prst": "prestige"}, 2000, "slow", "p:fade"),
    ("fracture", "Fracture", "1_5", "p15", "p15:prstTrans", {"prst": "fracture"}, 2000, "slow", "p:fade"),
    ("crush", "Crush", "1_6", "p15", "p15:prstTrans", {"prst": "crush"}, 2000, "slow", "p:fade"),
    ("peelOff", "Peel Off", "1_7", "p15", "p15:prstTrans", {"prst": "peelOff"}, 1250, "slow", "p:fade"),
    ("pageCurl", "Page Curl", "1_8", "p15", "p15:prstTrans", {"prst": "pageCurlDouble"}, 1250, "slow", "p:fade"),
    ("airplane", "Airplane", "1_9", "p15", "p15:prstTrans", {"prst": "airplane"}, 1250, "slow", "p:fade"),
    ("origami", "Origami", "1_10", "p15", "p15:prstTrans", {"prst": "origami"}, 3250, "slow", "p:fade"),
    ("dissolve", "Dissolve", "1_11", "standard", "p:dissolve", {}, 1200, "slow", "p:dissolve"),
    ("checker", "Checkerboard", "1_12", "standard", "p:checker", {}, 2500, "slow", "p:checker"),
    ("blinds", "Blinds", "1_13", "standard", "p:blinds", {"dir": "vert"}, 1600, "slow", "p:blinds"),
    ("clock", "Clock", "1_14", "standard", "p:wheel", {"spokes": "1"}, 1000, "slow", None),
    ("ripple", "Ripple", "1_15", "p14", "p14:ripple", {}, 1400, "slow", "p:fade"),
    ("honeycomb", "Honeycomb", "1_16", "p14", "p14:honeycomb", {}, 4400, "slow", "p:fade"),
    ("glitter", "Glitter", "1_17", "p14", "p14:glitter", {"pattern": "hexagon"}, 3900, "slow", "p:fade"),
    ("vortex", "Vortex", "1_18", "p14", "p14:vortex", {"dir": "r"}, 4000, "slow", "p:fade"),
    ("shred", "Shred", "1_19", "p14", "p14:shred", {}, 3000, "slow", "p:fade"),
    ("switch", "Switch", "1_20", "p14", "p14:switch", {"dir": "r"}, 1250, "slow", "p:fade"),
    ("flip", "Flip", "1_21", "p14", "p14:flip", {"dir": "r"}, 1250, "slow", "p:fade"),
    ("gallery", "Gallery", "1_22", "p14", "p14:gallery", {"dir": "l"}, 1600, "slow", "p:fade"),
    ("cube", "Cube", "1_23", "p14", "p14:prism", {}, 1200, "slow", "p:fade"),
    ("doors", "Doors", "1_24", "p14", "p14:doors", {"dir": "vert"}, 1400, "slow", "p:fade"),
    ("box", "Box", "1_25", "p14", "p14:prism", {"isInverted": "1"}, 1600, "slow", "p:fade"),
    ("comb", "Comb", "1_26", "standard", "p:comb", {}, 1000, "slow", None),
    ("zoom", "Zoom", "1_27", "p14", "p14:warp", {"dir": "in"}, 900, "slow", "p:fade"),
    ("random", "Random", "1_28", "standard", "p:random", {}, 1500, "slow", "p:random"),
    ("pan", "Pan", "2_0", "p14", "p14:pan", {"dir": "u"}, 1300, "slow", "p:fade"),
    ("ferris", "Ferris Wheel", "2_1", "p14", "p14:ferris", {"dir": "l"}, 2000, "slow", "p:fade"),
    ("conveyor", "Conveyor", "2_2", "p14", "p14:conveyor", {"dir": "l"}, 1600, "slow", "p:fade"),
    ("rotate", "Rotate", "2_3", "p14", "p14:prism", {"isContent": "1"}, 2000, "slow", "p:fade"),
    ("window", "Window", "2_4", "p14", "p14:window", {"dir": "vert"}, 1500, "slow", "p:fade"),
    ("orbit", "Orbit", "2_5", "p14", "p14:prism", {"isContent": "1", "isInverted": "1"}, 1600, "slow", "p:fade"),
    ("flythrough", "Fly Through", "2_6", "p14", "p14:flythrough", {}, 800, "slow", "p:fade"),
)

TRANSITION_FIXTURE = {
    slug: f"test/fixtures/native/transitions/{index:02d}-{name}.xml"
    for index, (slug, name) in enumerate(
        (
            ("none", "none"),
            ("morph", "morph"),
            ("fade", "fade"),
            ("push", "push"),
            ("wipe", "wipe"),
            ("split", "split"),
            ("reveal", "reveal"),
            ("cut", "cut"),
            ("randomBar", "random-bars"),
            ("shape", "shape"),
            ("uncover", "uncover"),
            ("cover", "cover"),
            ("flash", "flash"),
            ("fallOver", "fall-over"),
            ("drape", "drape"),
            ("curtains", "curtains"),
            ("wind", "wind"),
            ("prestige", "prestige"),
            ("fracture", "fracture"),
            ("crush", "crush"),
            ("peelOff", "peel-off"),
            ("pageCurl", "page-curl"),
            ("airplane", "airplane"),
            ("origami", "origami"),
            ("dissolve", "dissolve"),
            ("checker", "checkerboard"),
            ("blinds", "blinds"),
            ("clock", "clock"),
            ("ripple", "ripple"),
            ("honeycomb", "honeycomb"),
            ("glitter", "glitter"),
            ("vortex", "vortex"),
            ("shred", "shred"),
            ("switch", "switch"),
            ("flip", "flip"),
            ("gallery", "gallery"),
            ("cube", "cube"),
            ("doors", "doors"),
            ("box", "box"),
            ("comb", "comb"),
            ("zoom", "zoom"),
            ("random", "random"),
            ("pan", "pan"),
            ("ferris", "ferris-wheel"),
            ("conveyor", "conveyor"),
            ("rotate", "rotate"),
            ("window", "window"),
            ("orbit", "orbit"),
            ("flythrough", "fly-through"),
        ),
        start=1,
    )
}

TRANSITION_BY_SLUG = {row[0]: row for row in TRANSITION_TILES}

#: Normative ECMA-376 attribute domains used to justify ``presetMapping`` for a
#: non-captured direction on a standard transition element.
STANDARD_DIR_DOMAIN = {
    "p:push": ("l", "r", "u", "d"),
    "p:wipe": ("l", "r", "u", "d"),
    "p:cover": ("l", "r", "u", "d", "lu", "ld", "ru", "rd"),
    "p:pull": ("l", "r", "u", "d", "lu", "ld", "ru", "rd"),
    "p:blinds": ("horz", "vert"),
    "p:checker": ("horz", "vert"),
    "p:comb": ("horz", "vert"),
    "p:randomBar": ("horz", "vert"),
    "p:strips": ("ld", "lu", "rd", "ru"),
    "p:zoom": ("in", "out"),
}

# ---------------------------------------------------------------------------
# Animation evidence (95 captured gallery tiles + 3 text-build captures)
# ---------------------------------------------------------------------------
# category, slug, label, presetClass, presetID, presetSubtype, group,
# behavior children, animEffect filter, observed child duration, fixture
ANIMATION_TILES: tuple[tuple[Any, ...], ...] = (
    ("entrance", "appear", "Appear", "entr", 1, 0, "0_0", ("set",), None, None, "01-appear"),
    ("entrance", "blinds", "Blinds", "entr", 3, 10, "0_1", ("animEffect", "set"), "blinds(horizontal)", 500, "02-blinds"),
    ("entrance", "checkerboard", "Checkerboard", "entr", 5, 10, "0_2", ("animEffect", "set"), "checkerboard(across)", 500, "03-checkerboard"),
    ("entrance", "dissolveIn", "Dissolve In", "entr", 9, 0, "0_3", ("animEffect", "set"), "dissolve", 500, "04-dissolve-in"),
    ("entrance", "flyIn", "Fly In", "entr", 2, 4, "0_4", ("anim", "set"), None, 500, "05-fly-in"),
    ("entrance", "peekIn", "Peek In", "entr", 12, 4, "0_5", ("anim", "animEffect", "set"), "wipe(up)", 500, "06-peek-in"),
    ("entrance", "randomBars", "Random Bars", "entr", 14, 10, "0_6", ("animEffect", "set"), "randombar(horizontal)", 500, "07-random-bars"),
    ("entrance", "shape", "Shape", "entr", 6, 16, "0_7", ("animEffect", "set"), "circle(in)", 2000, "08-shape"),
    ("entrance", "split", "Split", "entr", 16, 21, "0_8", ("animEffect", "set"), "barn(inVertical)", 500, "09-split"),
    ("entrance", "strips", "Strips", "entr", 18, 12, "0_9", ("animEffect", "set"), "strips(downLeft)", 500, "10-strips"),
    ("entrance", "wedge", "Wedge", "entr", 20, 0, "0_10", ("animEffect", "set"), "wedge", 2000, "11-wedge"),
    ("entrance", "wheel", "Wheel", "entr", 21, 1, "0_11", ("animEffect", "set"), "wheel(1)", 2000, "12-wheel"),
    ("entrance", "wipe", "Wipe", "entr", 22, 4, "0_12", ("animEffect", "set"), "wipe(down)", 500, "13-wipe"),
    ("entrance", "expand", "Expand", "entr", 55, 0, "1_0", ("anim", "animEffect", "set"), "fade", 1000, "14-expand"),
    ("entrance", "fade", "Fade", "entr", 10, 0, "1_1", ("animEffect", "set"), "fade", 500, "15-fade"),
    ("entrance", "swivel", "Swivel", "entr", 45, 0, "1_2", ("anim", "animEffect", "set"), "fade", 2000, "16-swivel"),
    ("entrance", "zoom", "Zoom", "entr", 53, 16, "1_3", ("anim", "animEffect", "set"), "fade", 500, "17-zoom"),
    ("entrance", "centerRevolve", "Center Revolve", "entr", 43, 0, "2_0", ("anim", "animEffect", "set"), "fade", 100, "18-center-revolve"),
    ("entrance", "floatIn", "Float In", "entr", 42, 0, "2_1", ("anim", "animEffect", "set"), "fade", 1000, "19-float-in"),
    ("entrance", "growTurn", "Grow & Turn", "entr", 31, 0, "2_2", ("anim", "animEffect", "set"), "fade", 1000, "20-grow-turn"),
    ("entrance", "riseUp", "Rise Up", "entr", 37, 0, "2_3", ("anim", "animEffect", "set"), "fade", 1000, "21-rise-up"),
    ("entrance", "spinner", "Spinner", "entr", 49, 0, "2_4", ("anim", "animEffect", "set"), "fade", 500, "22-spinner"),
    ("entrance", "basicZoom", "Basic Zoom", "entr", 23, 16, "2_5", ("anim", "set"), None, 500, "23-basic-zoom"),
    ("entrance", "stretch", "Stretch", "entr", 17, 10, "2_6", ("anim", "set"), None, 500, "24-stretch"),
    ("entrance", "boomerang", "Boomerang", "entr", 25, 0, "3_0", ("anim", "animEffect", "set"), "fade", 500, "25-boomerang"),
    ("entrance", "bounce", "Bounce", "entr", 26, 0, "3_1", ("anim", "animEffect", "animScale", "set"), "wipe(down)", 580, "26-bounce"),
    ("entrance", "credits", "Credits", "entr", 28, 0, "3_2", ("anim", "set"), None, 15000, "27-credits"),
    ("entrance", "curveUp", "Curve Up", "entr", 52, 0, "3_3", ("animEffect", "animMotion", "animScale", "set"), "fade", 1000, "28-curve-up"),
    ("entrance", "drop", "Drop", "entr", 38, 0, "3_4", ("anim", "set"), None, 455, "29-drop"),
    ("entrance", "flip", "Flip", "entr", 56, 0, "3_5", ("anim", "animRot", "set"), None, 500, "30-flip"),
    ("entrance", "float", "Float", "entr", 30, 0, "3_6", ("anim", "animEffect", "set"), "fade", 800, "31-float"),
    ("entrance", "pinwheel", "Pinwheel", "entr", 35, 0, "3_7", ("anim", "animEffect", "set"), "fade", 2000, "32-pinwheel"),
    ("entrance", "spiralIn", "Spiral In", "entr", 15, 0, "3_8", ("anim", "set"), None, 1000, "33-spiral-in"),
    ("entrance", "basicSwivel", "Basic Swivel", "entr", 19, 10, "3_9", ("anim", "set"), None, 5000, "34-basic-swivel"),
    ("entrance", "whip", "Whip", "entr", 41, 0, "3_10", ("anim", "animEffect", "set"), "fade", 500, "35-whip"),
    ("exit", "blinds", "Blinds", "exit", 3, 10, "0_0", ("animEffect", "set"), "blinds(horizontal)", None, "36-blinds"),
    ("exit", "checkerboard", "Checkerboard", "exit", 5, 10, "0_1", ("animEffect", "set"), "checkerboard(across)", None, "37-checkerboard"),
    ("exit", "disappear", "Disappear", "exit", 1, 0, "0_2", ("set",), None, None, "38-disappear"),
    ("exit", "dissolveOut", "Dissolve Out", "exit", 9, 0, "0_3", ("animEffect", "set"), "dissolve", None, "39-dissolve-out"),
    ("exit", "flyOut", "Fly Out", "exit", 2, 4, "0_4", ("anim", "set"), None, 500, "40-fly-out"),
    ("exit", "peekOut", "Peek Out", "exit", 12, 4, "0_5", ("anim", "animEffect", "set"), "wipe(down)", 500, "41-peek-out"),
    ("exit", "randomBars", "Random Bars", "exit", 14, 10, "0_6", ("animEffect", "set"), "randombar(horizontal)", None, "42-random-bars"),
    ("exit", "shape", "Shape", "exit", 6, 32, "0_7", ("animEffect", "set"), "circle(out)", None, "43-shape"),
    ("exit", "split", "Split", "exit", 16, 21, "0_8", ("animEffect", "set"), "barn(inVertical)", None, "44-split"),
    ("exit", "strips", "Strips", "exit", 18, 12, "0_9", ("animEffect", "set"), "strips(downLeft)", None, "45-strips"),
    ("exit", "wedge", "Wedge", "exit", 20, 0, "0_10", ("animEffect", "set"), "wedge", None, "46-wedge"),
    ("exit", "wheel", "Wheel", "exit", 21, 1, "0_11", ("animEffect", "set"), "wheel(1)", None, "47-wheel"),
    ("exit", "wipe", "Wipe", "exit", 22, 4, "0_12", ("animEffect", "set"), "wipe(down)", None, "48-wipe"),
    ("exit", "contract", "Contract", "exit", 55, 0, "1_0", ("anim", "animEffect", "set"), "fade", 1000, "49-contract"),
    ("exit", "fade", "Fade", "exit", 10, 0, "1_1", ("animEffect", "set"), "fade", None, "50-fade"),
    ("exit", "swivel", "Swivel", "exit", 45, 0, "1_2", ("anim", "animEffect", "set"), "fade", 2000, "51-swivel"),
    ("exit", "zoom", "Zoom", "exit", 53, 32, "1_3", ("anim", "animEffect", "set"), "fade", 500, "52-zoom"),
    ("exit", "centerRevolve", "Center Revolve", "exit", 43, 0, "2_0", ("anim", "animEffect", "set"), "fade", 400, "53-center-revolve"),
    ("exit", "collapse", "Collapse", "exit", 17, 10, "2_1", ("anim", "set"), None, 500, "54-collapse"),
    ("exit", "floatOut", "Float Out", "exit", 42, 0, "2_2", ("anim", "animEffect", "set"), "fade", 1000, "55-float-out"),
    ("exit", "shrinkTurn", "Shrink & Turn", "exit", 31, 0, "2_3", ("anim", "animEffect", "set"), "fade", 1000, "56-shrink-turn"),
    ("exit", "sinkDown", "Sink Down", "exit", 37, 0, "2_4", ("anim", "animEffect", "set"), "fade", 1000, "57-sink-down"),
    ("exit", "spinner", "Spinner", "exit", 49, 0, "2_5", ("anim", "animEffect", "set"), "fade", 500, "58-spinner"),
    ("exit", "basicZoom", "Basic Zoom", "exit", 23, 32, "2_6", ("anim", "set"), None, 500, "59-basic-zoom"),
    ("exit", "stretchy", "Stretchy", "exit", 50, 0, "2_7", ("anim", "animEffect", "set"), "fade", 1000, "60-stretchy"),
    ("exit", "boomerang", "Boomerang", "exit", 25, 0, "3_0", ("anim", "animEffect", "set"), "fade", 500, "61-boomerang"),
    ("exit", "bounce", "Bounce", "exit", 26, 0, "3_1", ("anim", "animEffect", "animScale", "set"), "wipe(down)", 1822, "62-bounce"),
    ("exit", "credits", "Credits", "exit", 28, 0, "3_2", ("anim", "set"), None, 15000, "63-credits"),
    ("exit", "curveDown", "Curve Down", "exit", 52, 0, "3_3", ("animEffect", "animMotion", "animScale", "set"), "fade", 1000, "64-curve-down"),
    ("exit", "drop", "Drop", "exit", 38, 0, "3_4", ("anim", "set"), None, 1000, "65-drop"),
    ("exit", "flip", "Flip", "exit", 56, 0, "3_5", ("anim", "animRot", "set"), None, 500, "66-flip"),
    ("exit", "float", "Float", "exit", 30, 0, "3_6", ("anim", "animEffect", "set"), "fade", 800, "67-float"),
    ("exit", "pinwheel", "Pinwheel", "exit", 35, 0, "3_7", ("anim", "animEffect", "set"), "fade", 2000, "68-pinwheel"),
    ("exit", "spiralOut", "Spiral Out", "exit", 15, 0, "3_8", ("anim", "set"), None, 1000, "69-spiral-out"),
    ("exit", "basicSwivel", "Basic Swivel", "exit", 19, 10, "3_9", ("anim", "set"), None, 5000, "70-basic-swivel"),
    ("exit", "whip", "Whip", "exit", 41, 0, "3_10", ("anim", "animEffect", "set"), "fade", 500, "71-whip"),
    ("emphasis", "fillColor", "Fill Color", "emph", 1, 2, "0_0", ("animClr", "set"), None, 2000, "72-fill-color"),
    ("emphasis", "fontColor", "Font Color", "emph", 3, 2, "0_1", ("animClr",), None, None, "73-font-color"),
    ("emphasis", "growShrink", "Grow/Shrink", "emph", 6, 0, "0_2", ("animScale",), None, None, "74-grow-shrink"),
    ("emphasis", "lineColor", "Line Color", "emph", 7, 2, "0_3", ("animClr", "set"), None, 2000, "75-line-color"),
    ("emphasis", "spin", "Spin", "emph", 8, 0, "0_4", ("animRot",), None, None, "76-spin"),
    ("emphasis", "transparency", "Transparency", "emph", 9, 0, "0_5", ("animEffect", "set"), "image", None, "77-transparency"),
    ("emphasis", "boldFlash", "Bold Flash", "emph", 10, 0, "1_0", ("anim",), None, None, "78-bold-flash"),
    ("emphasis", "brushColor", "Brush Color", "emph", 16, 0, "1_1", ("set",), None, 500, "79-brush-color"),
    ("emphasis", "complementaryColor", "Complementary Color", "emph", 21, 0, "1_2", ("animClr", "set"), None, 500, "80-complementary-color"),
    ("emphasis", "complementaryColor2", "Complementary Color 2", "emph", 22, 0, "1_3", ("animClr", "set"), None, 500, "81-complementary-color-2"),
    ("emphasis", "contrastingColor", "Contrasting Color", "emph", 23, 0, "1_4", ("animClr", "set"), None, 500, "82-contrasting-color"),
    ("emphasis", "darken", "Darken", "emph", 24, 0, "1_5", ("animClr", "set"), None, 500, "83-darken"),
    ("emphasis", "desaturate", "Desaturate", "emph", 25, 0, "1_6", ("animClr", "set"), None, 500, "84-desaturate"),
    ("emphasis", "lighten", "Lighten", "emph", 30, 0, "1_7", ("animClr", "set"), None, 500, "85-lighten"),
    ("emphasis", "objectColor", "Object Color", "emph", 19, 0, "1_8", ("animClr", "set"), None, 500, "86-object-color"),
    ("emphasis", "pulse", "Pulse", "emph", 26, 0, "1_9", ("animEffect", "animScale"), "fade", 250, "87-pulse"),
    ("emphasis", "underline", "Underline", "emph", 18, 0, "1_10", ("set",), None, None, "88-underline"),
    ("emphasis", "colorPulse", "Color Pulse", "emph", 27, 0, "2_0", ("animClr", "set"), None, 250, "89-color-pulse"),
    ("emphasis", "growWithColor", "Grow With Color", "emph", 28, 0, "2_1", ("anim", "animClr", "set"), None, 500, "90-grow-with-color"),
    ("emphasis", "shimmer", "Shimmer", "emph", 36, 0, "2_2", ("anim", "animRot", "animScale"), None, 250, "91-shimmer"),
    ("emphasis", "teeter", "Teeter", "emph", 32, 0, "2_3", ("animRot",), None, 200, "92-teeter"),
    ("emphasis", "blink", "Blink", "emph", 35, 0, "3_0", ("anim",), None, None, "93-blink"),
    ("emphasis", "boldReveal", "Bold Reveal", "emph", 15, 0, "3_1", ("set",), None, None, "94-bold-reveal"),
    ("emphasis", "wave", "Wave", "emph", 34, 0, "3_2", ("animMotion", "animRot"), None, 125, "95-wave"),
)

ANIMATION_BY_KEY = {(row[0], row[1]): row for row in ANIMATION_TILES}
#: Gallery tiles keyed by presetClass + presetID, for enum-to-preset joins.
ANIMATION_BY_PRESET: dict[tuple[str, int], tuple[Any, ...]] = {}
for _row in ANIMATION_TILES:
    ANIMATION_BY_PRESET.setdefault((_row[3], _row[4]), _row)

# ---------------------------------------------------------------------------
# EPPEntryEffect dispositions
# ---------------------------------------------------------------------------
# Values whose four-char code starts with 0x00f60d are PowerPoint's legacy
# per-shape *entry animation* band (AnimationSettings.EntryEffect), not slide
# transitions; they are resolved by code prefix, not by this table.
SHAPE_ENTRY_CODE_PREFIX = "0x00f60d"

NATIVE = "nativeTemplate"
PRESET = "presetMapping"
SEMANTIC = "semanticPreservationOnly"

_LEGACY_NO_ELEMENT = (
    "legacy EPPEntryEffect value with no PowerPoint 16.113.1 Transitions-gallery tile and no "
    "established PresentationML element in this environment; PowerPoint read-back is required "
    "(Task 8) before it can be accepted. Recorded as outside the Task 3 accepted surface, not as "
    "a PowerPoint rejection."
)

# name -> (kind, target, attribute overrides, capability level)
#   kind "tile" -> target is a TRANSITION_TILES slug
#   kind "std"  -> target is a standard ECMA-376 element with no gallery tile
#   kind "oos"  -> target is the reason string
EPP_MAP: dict[str, tuple[str, str, dict[str, str], str]] = {
    # --- standard elements that the gallery captures directly -------------
    "entry effect cut": ("tile", "cut", {}, NATIVE),
    "entry effect cut black": ("tile", "cut", {"thruBlk": "1"}, PRESET),
    "entry effect fade": ("tile", "fade", {}, NATIVE),
    "entry effect fade smoothly": ("tile", "fade", {}, NATIVE),
    "entry effect fade black": ("tile", "fade", {"thruBlk": "1"}, PRESET),
    "entry effect dissolve": ("tile", "dissolve", {}, NATIVE),
    "entry effect random": ("tile", "random", {}, NATIVE),
    "entry effect blinds horizontal": ("tile", "blinds", {"dir": "horz"}, PRESET),
    "entry effect blinds vertical": ("tile", "blinds", {"dir": "vert"}, NATIVE),
    "entry effect checkerboard across": ("tile", "checker", {}, NATIVE),
    "entry effect checkerboard down": ("tile", "checker", {"dir": "vert"}, PRESET),
    "entry effect comb horizontal": ("tile", "comb", {}, NATIVE),
    "entry effect comb vertical": ("tile", "comb", {"dir": "vert"}, PRESET),
    "entry effect random bars horizontal": ("tile", "randomBar", {"dir": "horz"}, PRESET),
    "entry effect random bars vertical": ("tile", "randomBar", {"dir": "vert"}, NATIVE),
    "entry effect circle": ("tile", "shape", {}, NATIVE),
    "entry effect push down": ("tile", "push", {"dir": "d"}, PRESET),
    "entry effect push left": ("tile", "push", {"dir": "l"}, PRESET),
    "entry effect push right": ("tile", "push", {"dir": "r"}, PRESET),
    "entry effect push up": ("tile", "push", {"dir": "u"}, NATIVE),
    "entry effect wipe down": ("tile", "wipe", {"dir": "d"}, PRESET),
    "entry effect wipe left": ("tile", "wipe", {}, NATIVE),
    "entry effect wipe right": ("tile", "wipe", {"dir": "r"}, PRESET),
    "entry effect wipe up": ("tile", "wipe", {"dir": "u"}, PRESET),
    "entry effect cover left": ("tile", "cover", {}, NATIVE),
    "entry effect cover right": ("tile", "cover", {"dir": "r"}, PRESET),
    "entry effect cover up": ("tile", "cover", {"dir": "u"}, PRESET),
    "entry effect cover down": ("tile", "cover", {"dir": "d"}, PRESET),
    "entry effect cover left up": ("tile", "cover", {"dir": "lu"}, PRESET),
    "entry effect cover left down": ("tile", "cover", {"dir": "ld"}, PRESET),
    "entry effect cover right up": ("tile", "cover", {"dir": "ru"}, PRESET),
    "entry effect cover right down": ("tile", "cover", {"dir": "rd"}, PRESET),
    "entry effect uncover left": ("tile", "uncover", {}, NATIVE),
    "entry effect uncover right": ("tile", "uncover", {"dir": "r"}, PRESET),
    "entry effect uncover up": ("tile", "uncover", {"dir": "u"}, PRESET),
    "entry effect uncover down": ("tile", "uncover", {"dir": "d"}, PRESET),
    "entry effect uncover left up": ("tile", "uncover", {"dir": "lu"}, PRESET),
    "entry effect uncover left down": ("tile", "uncover", {"dir": "ld"}, PRESET),
    "entry effect uncover right up": ("tile", "uncover", {"dir": "ru"}, PRESET),
    "entry effect uncover right down": ("tile", "uncover", {"dir": "rd"}, PRESET),
    "entry effect split horizontal in": ("tile", "split", {"orient": "horz", "dir": "in"}, PRESET),
    "entry effect split horizontal out": ("tile", "split", {"orient": "horz", "dir": "out"}, PRESET),
    "entry effect split vertical in": ("tile", "split", {"orient": "vert", "dir": "in"}, PRESET),
    "entry effect split vertical out": ("tile", "split", {"orient": "vert", "dir": "out"}, NATIVE),
    "entry effect wheel 1 spoke": ("tile", "clock", {"spokes": "1"}, NATIVE),
    "entry effect wheel 2 spokes": ("tile", "clock", {"spokes": "2"}, PRESET),
    "entry effect wheel 3 spokes": ("tile", "clock", {"spokes": "3"}, PRESET),
    "entry effect wheel 4 spokes": ("tile", "clock", {"spokes": "4"}, PRESET),
    "entry effect wheel 8 spokes": ("tile", "clock", {"spokes": "8"}, PRESET),
    "entry effect wheel reverse 1 spoke": ("tile", "clock", {"spokes": "1", "reverse": "1"}, SEMANTIC),
    # --- standard elements with no 16.113.1 gallery tile -------------------
    "entry effect diamond": ("std", "p:diamond", {}, PRESET),
    "entry effect plus": ("std", "p:plus", {}, PRESET),
    "entry effect wedge": ("std", "p:wedge", {}, PRESET),
    "entry effect news flash": ("std", "p:newsflash", {}, PRESET),
    "entry effect spinner": ("std", "p:newsflash", {}, PRESET),
    "entry effect strips left down": ("std", "p:strips", {"dir": "ld"}, PRESET),
    "entry effect strips left up": ("std", "p:strips", {"dir": "lu"}, PRESET),
    "entry effect strips right down": ("std", "p:strips", {"dir": "rd"}, PRESET),
    "entry effect strips right up": ("std", "p:strips", {"dir": "ru"}, PRESET),
    "entry effect strips down left": ("std", "p:strips", {"dir": "ld"}, PRESET),
    "entry effect strips down right": ("std", "p:strips", {"dir": "rd"}, PRESET),
    "entry effect strips up left": ("std", "p:strips", {"dir": "lu"}, PRESET),
    "entry effect strips up right": ("std", "p:strips", {"dir": "ru"}, PRESET),
    # --- Morph (Task 1 spike + native capture) ----------------------------
    "entry effect morph by object": ("tile", "morph", {"option": "byObject"}, NATIVE),
    "entry effect morph by word": ("tile", "morph", {"option": "byWord"}, PRESET),
    "entry effect morph by char": ("tile", "morph", {"option": "byChar"}, PRESET),
    # --- p14 extension tiles ----------------------------------------------
    "entry effect flash once slow": ("tile", "flash", {}, NATIVE),
    "entry effect flash once medium": ("tile", "flash", {}, PRESET),
    "entry effect flash once fast": ("tile", "flash", {}, PRESET),
    "entry effect flashbulb": ("tile", "flash", {}, SEMANTIC),
    "entry effect reveal smooth left": ("tile", "reveal", {}, NATIVE),
    "entry effect reveal smooth right": ("tile", "reveal", {"dir": "r"}, SEMANTIC),
    "entry effect reveal black left": ("tile", "reveal", {"thruBlk": "1"}, SEMANTIC),
    "entry effect reveal black right": ("tile", "reveal", {"thruBlk": "1", "dir": "r"}, SEMANTIC),
    "entry effect ripple center": ("tile", "ripple", {}, NATIVE),
    "entry effect ripple left up": ("tile", "ripple", {"dir": "lu"}, SEMANTIC),
    "entry effect ripple left down": ("tile", "ripple", {"dir": "ld"}, SEMANTIC),
    "entry effect ripple right up": ("tile", "ripple", {"dir": "ru"}, SEMANTIC),
    "entry effect ripple right down": ("tile", "ripple", {"dir": "rd"}, SEMANTIC),
    "entry effect honeycomb": ("tile", "honeycomb", {}, NATIVE),
    "entry effect glitter hexagon left": ("tile", "glitter", {"pattern": "hexagon"}, NATIVE),
    "entry effect glitter hexagon right": ("tile", "glitter", {"pattern": "hexagon", "dir": "r"}, SEMANTIC),
    "entry effect glitter hexagon up": ("tile", "glitter", {"pattern": "hexagon", "dir": "u"}, SEMANTIC),
    "entry effect glitter hexagon down": ("tile", "glitter", {"pattern": "hexagon", "dir": "d"}, SEMANTIC),
    "entry effect glitter diamond left": ("tile", "glitter", {"pattern": "diamond"}, SEMANTIC),
    "entry effect glitter diamond right": ("tile", "glitter", {"pattern": "diamond", "dir": "r"}, SEMANTIC),
    "entry effect glitter diamond up": ("tile", "glitter", {"pattern": "diamond", "dir": "u"}, SEMANTIC),
    "entry effect glitter diamond down": ("tile", "glitter", {"pattern": "diamond", "dir": "d"}, SEMANTIC),
    "entry effect vortex right": ("tile", "vortex", {"dir": "r"}, NATIVE),
    "entry effect vortex left": ("tile", "vortex", {"dir": "l"}, SEMANTIC),
    "entry effect vortex up": ("tile", "vortex", {"dir": "u"}, SEMANTIC),
    "entry effect vortex down": ("tile", "vortex", {"dir": "d"}, SEMANTIC),
    "entry effect shred strips in": ("tile", "shred", {}, NATIVE),
    "entry effect shred strips out": ("tile", "shred", {"dir": "out"}, SEMANTIC),
    "entry effect shred rectangle in": ("tile", "shred", {"pattern": "rectangle"}, SEMANTIC),
    "entry effect shred rectangle out": ("tile", "shred", {"pattern": "rectangle", "dir": "out"}, SEMANTIC),
    "entry effect switch right": ("tile", "switch", {"dir": "r"}, NATIVE),
    "entry effect switch left": ("tile", "switch", {"dir": "l"}, SEMANTIC),
    "entry effect switch up": ("tile", "switch", {"dir": "u"}, SEMANTIC),
    "entry effect switch down": ("tile", "switch", {"dir": "d"}, SEMANTIC),
    "entry effect flip right": ("tile", "flip", {"dir": "r"}, NATIVE),
    "entry effect flip left": ("tile", "flip", {"dir": "l"}, SEMANTIC),
    "entry effect flip up": ("tile", "flip", {"dir": "u"}, SEMANTIC),
    "entry effect flip down": ("tile", "flip", {"dir": "d"}, SEMANTIC),
    "entry effect gallery left": ("tile", "gallery", {"dir": "l"}, NATIVE),
    "entry effect gallery right": ("tile", "gallery", {"dir": "r"}, SEMANTIC),
    "entry effect cube left": ("tile", "cube", {}, NATIVE),
    "entry effect cube right": ("tile", "cube", {"dir": "r"}, SEMANTIC),
    "entry effect cube up": ("tile", "cube", {"dir": "u"}, SEMANTIC),
    "entry effect cube down": ("tile", "cube", {"dir": "d"}, SEMANTIC),
    "entry effect box left": ("tile", "box", {"isInverted": "1"}, NATIVE),
    "entry effect box right": ("tile", "box", {"isInverted": "1", "dir": "r"}, SEMANTIC),
    "entry effect box up": ("tile", "box", {"isInverted": "1", "dir": "u"}, SEMANTIC),
    "entry effect box down": ("tile", "box", {"isInverted": "1", "dir": "d"}, SEMANTIC),
    "entry effect rotate left": ("tile", "rotate", {"isContent": "1"}, NATIVE),
    "entry effect rotate right": ("tile", "rotate", {"isContent": "1", "dir": "r"}, SEMANTIC),
    "entry effect rotate up": ("tile", "rotate", {"isContent": "1", "dir": "u"}, SEMANTIC),
    "entry effect rotate down": ("tile", "rotate", {"isContent": "1", "dir": "d"}, SEMANTIC),
    "entry effect orbit left": ("tile", "orbit", {"isContent": "1", "isInverted": "1"}, NATIVE),
    "entry effect orbit right": ("tile", "orbit", {"isContent": "1", "isInverted": "1", "dir": "r"}, SEMANTIC),
    "entry effect orbit up": ("tile", "orbit", {"isContent": "1", "isInverted": "1", "dir": "u"}, SEMANTIC),
    "entry effect orbit down": ("tile", "orbit", {"isContent": "1", "isInverted": "1", "dir": "d"}, SEMANTIC),
    "entry effect doors vertical": ("tile", "doors", {"dir": "vert"}, NATIVE),
    "entry effect doors horizontal": ("tile", "doors", {"dir": "horz"}, SEMANTIC),
    "entry effect window vertical": ("tile", "window", {"dir": "vert"}, NATIVE),
    "entry effect window horizontal": ("tile", "window", {"dir": "horz"}, SEMANTIC),
    "entry effect warp in": ("tile", "zoom", {"dir": "in"}, NATIVE),
    "entry effect warp out": ("tile", "zoom", {"dir": "out"}, SEMANTIC),
    "entry effect pan up": ("tile", "pan", {"dir": "u"}, NATIVE),
    "entry effect pan left": ("tile", "pan", {"dir": "l"}, SEMANTIC),
    "entry effect pan right": ("tile", "pan", {"dir": "r"}, SEMANTIC),
    "entry effect pan down": ("tile", "pan", {"dir": "d"}, SEMANTIC),
    "entry effect ferris wheel left": ("tile", "ferris", {"dir": "l"}, NATIVE),
    "entry effect ferris wheel right": ("tile", "ferris", {"dir": "r"}, SEMANTIC),
    "entry effect conveyor left": ("tile", "conveyor", {"dir": "l"}, NATIVE),
    "entry effect conveyor right": ("tile", "conveyor", {"dir": "r"}, SEMANTIC),
    "entry effect fly through in": ("tile", "flythrough", {}, NATIVE),
    "entry effect fly through out": ("tile", "flythrough", {"dir": "out"}, SEMANTIC),
    "entry effect fly through in bounce": ("tile", "flythrough", {"hasBounce": "1"}, SEMANTIC),
    "entry effect fly through out bounce": ("tile", "flythrough", {"dir": "out", "hasBounce": "1"}, SEMANTIC),
    # --- p15 prstTrans tiles ----------------------------------------------
    "entry effect fall over left": ("tile", "fallOver", {}, NATIVE),
    "entry effect fall over right": ("tile", "fallOver", {"invX": "1"}, SEMANTIC),
    "entry effect drape left": ("tile", "drape", {}, NATIVE),
    "entry effect drape right": ("tile", "drape", {"invX": "1"}, SEMANTIC),
    "entry effect curtains": ("tile", "curtains", {}, NATIVE),
    "entry effect wind left": ("tile", "wind", {}, NATIVE),
    "entry effect wind right": ("tile", "wind", {"invX": "1"}, SEMANTIC),
    "entry effect prestige": ("tile", "prestige", {}, NATIVE),
    "entry effect fracture": ("tile", "fracture", {}, NATIVE),
    "entry effect crush": ("tile", "crush", {}, NATIVE),
    "entry effect peel off left": ("tile", "peelOff", {}, NATIVE),
    "entry effect peel off right": ("tile", "peelOff", {"invX": "1"}, SEMANTIC),
    "entry effect page curl double left": ("tile", "pageCurl", {"prst": "pageCurlDouble"}, NATIVE),
    "entry effect page curl double right": ("tile", "pageCurl", {"prst": "pageCurlDouble", "invX": "1"}, SEMANTIC),
    "entry effect page curl single left": ("tile", "pageCurl", {"prst": "pageCurlSingle"}, SEMANTIC),
    "entry effect page curl single right": ("tile", "pageCurl", {"prst": "pageCurlSingle", "invX": "1"}, SEMANTIC),
    "entry effect airplane left": ("tile", "airplane", {}, NATIVE),
    "entry effect airplane right": ("tile", "airplane", {"invX": "1"}, SEMANTIC),
    "entry effect origami left": ("tile", "origami", {}, NATIVE),
    "entry effect origami right": ("tile", "origami", {"invX": "1"}, SEMANTIC),
    # --- legacy values with no established representation ------------------
    "entry effect appear": ("oos", _LEGACY_NO_ELEMENT, {}, ""),
    "entry effect box in": ("oos", _LEGACY_NO_ELEMENT, {}, ""),
    "entry effect box out": ("oos", _LEGACY_NO_ELEMENT, {}, ""),
}

# ---------------------------------------------------------------------------
# MsoAnimEffect dispositions
# ---------------------------------------------------------------------------
#: Highest MsoAnimEffect ordinal for which the ordinal equals the OOXML
#: entrance/exit presetID. Corroborated twice: every captured native entrance
#: fixture at or below 31 carries presetID == ordinal, and the COM-derived
#: reference states the two numberings "diverge from id 32 up".
ENTR_EXIT_CONFIDENT_MAX = 31
ENTR_EXIT_ORDINAL_MAX = 53
MEDIA_ORDINAL_RANGE = (83, 85)
PATH_ORDINAL_MIN = 86

ENTR_EXIT_DIVERGENCE_GAP = (
    "MsoAnimEffect ordinal {ordinal} is above the corroborated ordinal==presetID band (<= 31). "
    "The OOXML entrance/exit presetID for this effect is not established in this environment "
    "(documented divergence: msoAnimEffectLightSpeed is 32 but saves presetID 34; "
    "msoAnimEffectFold is 53 but saves 58). Resolve by PowerPoint read-back (Task 8) before "
    "emitting a presetID."
)

#: Name-matched gallery tiles for the diverged band. Recorded so Task 4 has a
#: candidate to verify, explicitly flagged as a name match rather than proof.
EFFECT_NAME_MATCH: dict[str, tuple[str, str]] = {
    "animation type pinwheel": ("entrance", "pinwheel"),
    "animation type rise up": ("entrance", "riseUp"),
    "animation type whip": ("entrance", "whip"),
    "animation type center revolve": ("entrance", "centerRevolve"),
    "animation type spinner": ("entrance", "spinner"),
    "animation type stretchy": ("exit", "stretchy"),
    "animation type expand": ("entrance", "expand"),
    "animation type flip": ("entrance", "flip"),
    "animation type shimmer": ("emphasis", "shimmer"),
}

#: MsoAnimEffect emphasis names -> OOXML ``emph`` presetID.
EMPHASIS_PRESET_ID: dict[str, int | None] = {
    "animation type change fill color": 1,
    "animation type change font": 2,
    "animation type change font color": 3,
    "animation type change font size": 4,
    "animation type change font style": 5,
    "animation type grow shrink": 6,
    "animation type change line color": 7,
    "animation type spin": 8,
    "animation type transparency": 9,
    "animation type bold flash": 10,
    "animation type blast": None,
    "animation type bold reveal": 15,
    "animation type brush on color": 16,
    "animation type brush on underline": 18,
    "animation type color blend": None,
    "animation type color wave": None,
    "animation type complementary color": 21,
    "animation type complementary color 2": 22,
    "animation type constrasting color": 23,
    "animation type darken": 24,
    "animation type desaturate": 25,
    "animation type flash bulb": 26,
    "animation type flicker": 27,
    "animation type grow with color": 28,
    "animation type lighten": 30,
    "animation type style emphasis": None,
    "animation type teeter": 32,
    "animation type vertical grow": None,
    "animation type wave": 34,
}

#: ``mediacall`` presetIDs. Only Play is captured (native media timing fixture
#: carries presetClass="mediacall" presetID="1").
MEDIA_PRESET: dict[str, tuple[int | None, str, str]] = {
    "animation type media play": (1, NATIVE, "playFrom(0.0)"),
    "animation type media pause": (None, SEMANTIC, "pauseFrom"),
    "animation type media stop": (None, SEMANTIC, "stop"),
}

# ---------------------------------------------------------------------------
# Remaining enum dispositions
# ---------------------------------------------------------------------------
#: MsoAnimTriggerType -> semantic trigger + OOXML nodeType (normative
#: ST_TLTimeNodeType values; clickEffect and interactiveSeq are both captured).
TRIGGER_MAP: dict[str, tuple[str, str | None, str]] = {
    "on page click": ("onPageClick", "clickEffect", NATIVE),
    "with previous": ("withPrevious", "withEffect", PRESET),
    "after previous": ("afterPrevious", "afterEffect", PRESET),
    "on shape click": ("onShapeClick", "interactiveSeq", NATIVE),
    "no trigger": ("none", None, SEMANTIC),
}

#: MsoAnimTextUnitEffect -> semantic text unit + OOXML p:iterate type
#: (normative ST_IterateType); "by paragraph" needs no p:iterate.
TEXT_UNIT_MAP: dict[str, tuple[str, str | None, str]] = {
    "by paragraph": ("byParagraph", None, NATIVE),
    "by word": ("byWord", "wd", PRESET),
    "by character": ("byCharacter", "lt", PRESET),
}

#: MsoAnimateByLevel -> semantic value and OOXML build attributes.
LEVEL_MAP: dict[str, tuple[str, str, dict[str, str], str]] = {
    "text by no levels": ("asOneObject", "bldP", {}, NATIVE),
    "text by all levels": ("allParagraphLevels", "bldP", {"build": "allAtOnce"}, NATIVE),
    "text by first level": ("byParagraphLevel1", "bldP", {"build": "p", "bldLvl": "1"}, PRESET),
    "text by second level": ("byParagraphLevel2", "bldP", {"build": "p", "bldLvl": "2"}, PRESET),
    "text by third level": ("byParagraphLevel3", "bldP", {"build": "p", "bldLvl": "3"}, PRESET),
    "text by fourth level": ("byParagraphLevel4", "bldP", {"build": "p", "bldLvl": "4"}, PRESET),
    "text by fifth level": ("byParagraphLevel5", "bldP", {"build": "p", "bldLvl": "5"}, PRESET),
    "chart all at once": ("chartAllAtOnce", "bldGraphic", {"build": "allAtOnce"}, PRESET),
    "chart by category": ("chartByCategory", "bldGraphic", {"build": "category"}, PRESET),
    "chart by ctageory elements": ("chartByCategoryElement", "bldGraphic", {"build": "catElem"}, PRESET),
    "chart by series": ("chartBySeries", "bldGraphic", {"build": "series"}, PRESET),
    "chart by series elements": ("chartBySeriesElement", "bldGraphic", {"build": "seriesEl"}, PRESET),
}

#: MsoAnimAfterEffect -> semantic afterEffect.type.
AFTER_EFFECT_MAP: dict[str, tuple[str, list[str], str]] = {
    "no after effect": ("none", [], NATIVE),
    "dim": ("dim", ["p:animClr", "p:cTn/@afterEffect"], SEMANTIC),
    "hide": ("hide", ["p:set"], SEMANTIC),
    "hide on next click": ("hideOnNextClick", ["p:set", "p:cTn/@afterEffect"], SEMANTIC),
}

#: MsoAnimType -> the nine behavior primitives and their OOXML elements.
BEHAVIOR_MAP: dict[str, tuple[str, str | None, str]] = {
    "animation type motion": ("motion", "p:animMotion", NATIVE),
    "animation type color": ("color", "p:animClr", NATIVE),
    "animation type scale": ("scale", "p:animScale", NATIVE),
    "animation type rotation": ("rotation", "p:animRot", NATIVE),
    "animation type property": ("property", "p:anim", NATIVE),
    "animation type command": ("command", "p:cmd", NATIVE),
    "animation type filter": ("filter", "p:animEffect", NATIVE),
    "animation type set": ("set", "p:set", NATIVE),
    "animation type none": ("none", None, ""),
}

#: Observed ``presetSubtype`` codes, recorded so Task 4/8 can resolve the
#: MsoAnimDirection vocabulary. No direction *name* is bound to a code by the
#: available evidence, so every MsoAnimDirection candidate stays
#: semantic-preservation-only.
PRESET_SUBTYPE_EVIDENCE = [
    {"code": 0, "observedOn": "Appear, Fade, Wedge, most emphasis tiles", "meaning": "no direction"},
    {"code": 1, "observedOn": "Wheel (gallery default 1 spoke)", "meaning": "1 spoke"},
    {"code": 2, "observedOn": "Fill Color, Font Color, Line Color", "meaning": "colour-effect variant"},
    {"code": 4, "observedOn": "Fly In, Peek In, Wipe (gallery default)", "meaning": "four-way direction default"},
    {"code": 10, "observedOn": "Blinds, Checkerboard, Random Bars, Stretch, Basic Swivel", "meaning": "horizontal/across axis"},
    {"code": 12, "observedOn": "Strips (filter strips(downLeft))", "meaning": "corner direction"},
    {"code": 16, "observedOn": "Shape, Zoom, Basic Zoom entrance", "meaning": "in"},
    {"code": 21, "observedOn": "Split (filter barn(inVertical))", "meaning": "vertical in"},
    {"code": 32, "observedOn": "Shape, Zoom, Basic Zoom exit", "meaning": "out"},
]

DIRECTION_GAP = (
    "MsoAnimDirection values are effect-specific and persist as p:cTn/@presetSubtype. "
    "The available evidence binds subtype codes to gallery tiles, not to direction names, so the "
    "code for this direction is not established here; see presetSubtypeEvidence and resolve by "
    "PowerPoint read-back (Task 8)."
)

#: Behavior payloads, split into what a normative ECMA-376 element/attribute
#: establishes and what only a PowerPoint capture can establish.
#:
#: The gallery capture recorded *which* behavior children PowerPoint wrote for
#: each tile, not the values inside them. The writer may therefore generate
#: only the presets whose every child appears under ``resolved``; a preset with
#: any ``unresolved`` child is refused outright, because emitting the node
#: without its coordinates, colour or formula would be a silent approximation.
BEHAVIOR_PAYLOADS = {
    "capabilityLevel": PRESET,
    "evidence": (
        "ECMA-376 Part 1 PresentationML animation behaviours (CT_TLSetBehavior, "
        "CT_TLAnimateEffectBehavior, CT_TLCommandBehavior, CT_TLCommonBehaviorData) and the "
        "animation attribute-name vocabulary"
    ),
    "verification": "powerPointReadBackRequired",
    "resolved": {
        "p:set": {
            "attrName": "style.visibility",
            "entrance": "visible",
            "exit": "hidden",
            "payload": "p:to/p:strVal/@val",
            "behaviorTiming": {
                "durMs": 1,
                "fill": "hold",
                "entranceDelayMs": 0,
                "exitDelayOffsetMs": -1,
                "note": (
                    "CT_TLCommonBehaviorData always carries a p:cTn, so the visibility change is a "
                    "one-millisecond discrete state change held by fill=hold rather than a "
                    "duration-less node. An entrance shows the shape at the effect start "
                    "(delay 0); an exit hides it exitDelayOffsetMs from the end of the active "
                    "duration, so the outgoing filter stays visible for the whole effect and the "
                    "state change finishes exactly with it."
                ),
            },
            "note": "an entrance makes the shape visible and an exit hides it; the emphasis p:set "
                    "children (Underline, Bold Reveal, Brush Color) set a font attribute whose name "
                    "is not captured, so those tiles are refused",
        },
        "p:animEffect": {
            "attribute": "transition",
            "entrance": "in",
            "exit": "out",
            "transitionDomain": ["in", "out", "none"],
            "filter": "the captured animEffectFilter string of the same catalog entry",
            "note": "ST_TLAnimateEffectTransition is normative; the filter strings come from the "
                    "native captures, and an entry without one is refused",
        },
        "p:cmd": {
            "attributes": {"type": "call", "cmd": "the captured command string"},
            "typeDomain": ["evt", "call", "verb"],
            "note": "only media Play is captured (cmd playFrom(0.0)); ST_TLCommandType is the "
                    "allowlist the writer validates an explicit behaviors list against",
        },
    },
    "unresolved": {
        "p:anim": "the animated attribute name and value formula of a gallery preset are not captured",
        "p:animMotion": "preset motion-path geometry (p:animMotion/@path) is not captured",
        "p:animScale": "the preset scale factors are not captured",
        "p:animRot": "the preset rotation angle is not captured",
        "p:animClr": "the preset target colour is not captured",
    },
    "childOrder": (
        "the capture reports a tile's behavior children as a set, not in document order, so the "
        "writer emits them in the recorded order. Visibility is governed by the p:set start "
        "condition above, not by the node's position among its siblings."
    ),
    "writerRule": (
        "generate a preset only when every behavior child it records appears under resolved. A "
        "preset with any unresolved child raises BehaviorPayloadGapError naming each one; the "
        "writer never emits a behavior node whose payload it had to omit. An explicit JSON "
        "behaviors list supplies exact values and is written verbatim after its enumerated "
        "attributes are validated against the ECMA-376 allowlists."
    ),
}

#: Standard ECMA-376 transition elements with no 16.113.1 gallery tile. They
#: are catalogued so import can decode them and the writer can round-trip them.
STANDARD_ONLY_TRANSITIONS = (
    ("diamond", "p:diamond", {}),
    ("plus", "p:plus", {}),
    ("wedge", "p:wedge", {}),
    ("newsflash", "p:newsflash", {}),
    ("strips", "p:strips", {"dir": "ld"}),
    ("zoom", "p:zoom", {"dir": "in"}),
)

# ---------------------------------------------------------------------------
# Semantic JSON helpers
# ---------------------------------------------------------------------------
CATALOG_TARGET = "catalogTarget"
CATALOG_EFFECT_ID = "catalogEffect"

BASE_TIMING = {
    "durationMs": 500,
    "repeatCount": 1,
    "repeatDurationMs": None,
    "autoReverse": False,
    "acceleration": 0,
    "deceleration": 0,
    "restart": "always",
    "rewind": False,
    "smoothStart": False,
    "smoothEnd": False,
    "bounceEnd": 0,
}


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``patch`` into a copy of ``base``."""
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def semantic_parameters(slug: str, attributes: dict[str, str]) -> dict[str, Any]:
    """Return the semantic ``transition.parameters`` for one OOXML attribute set.

    Every attribute that distinguishes one accepted value from another stays in
    the semantic JSON, including ``p15:prstTrans/@prst`` (Page Curl Single and
    Double differ only there). Morph's GUI label is "variant"; PowerPoint
    persists it as ``p159:morph/@option``.
    """
    if slug == "morph":
        return {"variant": attributes["option"]}
    return dict(attributes)


def transition_semantic(**patch: Any) -> dict[str, Any]:
    """Return a complete semantic slide-transition fragment."""
    base = {
        "effect": "fade",
        "parameters": {},
        "durationMs": 700,
        "advance": {"onClick": True, "afterMs": None},
        "sound": None,
    }
    return {"transition": _merge(base, patch)}


def effect_semantic(**patch: Any) -> dict[str, Any]:
    """Return a complete semantic main-sequence animation fragment."""
    base = {
        "id": CATALOG_EFFECT_ID,
        "target": {"element": CATALOG_TARGET},
        # The carrier preset of a control entry has to be reproducible on its
        # own, otherwise every timing/trigger/build example would fail on the
        # carrier instead of exercising its own value. Entrance Fade is the
        # fully captured baseline: presetID 10, p:animEffect filter "fade" and
        # the normative visibility p:set.
        #
        # ``variant`` stays null unless an entry is specifically about a
        # direction: a non-null variant means "use this MsoAnimDirection", and
        # those names are the only ones the catalog defines.
        "preset": {"category": "entrance", "effect": "fade", "variant": None},
        "start": {"type": "onPageClick", "delayMs": 0},
        "timing": dict(BASE_TIMING),
        "afterEffect": {"type": "none"},
        "sound": None,
    }
    effect = _merge(base, patch)
    if "behaviors" in patch:
        effect.pop("preset", None)
    return {"animations": {"mainSequence": [effect], "interactiveSequences": []}}


def interactive_semantic(effect: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a semantic fragment whose only effect sits in an interactive sequence."""
    effect = effect or effect_semantic()["animations"]["mainSequence"][0]
    return {
        "animations": {
            "mainSequence": [],
            "interactiveSequences": [
                {
                    "id": "catalogSequence",
                    "trigger": {"type": "onShapeClick", "target": CATALOG_TARGET, "delayMs": 0},
                    "effects": [effect],
                }
            ],
        }
    }


def trigger_semantic(trigger: str) -> dict[str, Any]:
    """Return the semantic fragment for one MsoAnimTriggerType value.

    PowerPoint persists a shape-click trigger as an interactive sequence whose
    start condition targets the clicked shape, not as a main-sequence effect,
    so that value is modelled with the sequence it actually produces.
    """
    if trigger == "onShapeClick":
        return interactive_semantic()
    return effect_semantic(start={"type": trigger, "delayMs": 0})


#: Example inter-item delay for the by-word / by-character fragments below.
#: ``CT_TLIterateData`` is a choice of exactly one ``p:tmAbs`` or ``p:tmPct``,
#: so a text unit cannot be expressed without an interval. The capture does
#: not record what PowerPoint writes when the GUI field is left alone, so the
#: catalog's semantic JSON carries an explicit, writable example value and the
#: writer requires one rather than inventing a default.
CATALOG_ITEM_DELAY_PERCENT = 10


def text_unit_semantic(unit: str) -> dict[str, Any]:
    """Return a complete semantic fragment for one text-unit value."""
    text: dict[str, Any] = {"unit": unit}
    if unit != "byParagraph":
        text["interItemDelayPercent"] = CATALOG_ITEM_DELAY_PERCENT
    return effect_semantic(text=text)


#: Complete payloads for the behavior-primitive fragments. An accepted entry's
#: semantic JSON has to be a full, writable example (REQ-7.2), and the writer
#: emits only behaviors that carry an explicit payload, so every primitive
#: supplies one here. These are illustrative authoring values, not captured
#: preset values: what a *gallery preset* puts inside the same element stays
#: unresolved under ``BEHAVIOR_PAYLOADS['unresolved']``.
BEHAVIOR_EXAMPLE_PAYLOADS: dict[str, dict[str, Any]] = {
    "motion": {"path": "M 0 0 L 0.25 0 E", "pathEditMode": "relative", "origin": "layout"},
    "color": {"to": "#FF8800"},
    "scale": {"to": {"x": 1.5, "y": 1.5}},
    "rotation": {"by": 360},
    "property": {"attrName": "ppt_x", "to": "0.75", "calcMode": "lin", "valueType": "num"},
    "command": {"command": "playFrom", "value": "0.0"},
    "filter": {"filter": "fade", "transition": "in"},
    "set": {"attrName": "style.visibility", "to": "visible"},
}


def behavior_semantic(kind: str) -> dict[str, Any]:
    """Return a complete semantic fragment for one behavior primitive."""
    return effect_semantic(behaviors=[{"type": kind, **BEHAVIOR_EXAMPLE_PAYLOADS[kind]}])


def preset_payload_gap(category: str, children: tuple[str, ...] | list[str] | None,
                       animation_filter: str | None, command: str | None = None) -> list[str]:
    """Return the behavior children of a preset whose payload is unresolved.

    This is the catalog side of the writer's payload gate. ``p:set`` is
    established only for the entrance/exit visibility change, ``p:animEffect``
    only when the tile carries a captured filter string, and ``p:cmd`` only
    when it carries a captured command. Everything else listed under
    ``BEHAVIOR_PAYLOADS['unresolved']`` has no captured value, so the entry
    records the gap and the writer refuses it instead of emitting a
    payload-free node. ``None`` children means no tile was captured at all,
    which is the strongest form of the same gap.
    """
    if children is None:
        return ["-"]
    unresolved: list[str] = []
    for child in children:
        tag = child if child.startswith("p:") else f"p:{child}"
        if tag == "p:set":
            if category not in {"entrance", "exit"}:
                unresolved.append(tag)
        elif tag == "p:animEffect":
            if not animation_filter:
                unresolved.append(tag)
        elif tag == "p:cmd":
            if not command:
                unresolved.append(tag)
        else:
            unresolved.append(tag)
    return unresolved


def catalog_slide(semantic: dict[str, Any]) -> dict[str, Any]:
    """Wrap a semantic fragment in the minimal slide that validates it."""
    slide: dict[str, Any] = {"elements": [{"type": "text", "id": CATALOG_TARGET, "text": "catalog"}]}
    slide.update(semantic)
    return slide


# ---------------------------------------------------------------------------
# GUI control items that are not a single enum value
# ---------------------------------------------------------------------------
# key, status, capabilityLevel, ooxml mapping, semantic fragment, reason
CONTROL_ITEMS: tuple[tuple[str, str, str, dict[str, Any] | None, dict[str, Any] | None, str | None], ...] = (
    (
        "transition.duration",
        "accepted",
        PRESET,
        {"strategy": "attribute", "attributes": ["p14:dur", "p:transition/@spd"], "legacySpeedMs": LEGACY_SPEED_MS,
         "note": "p14:dur carries milliseconds inside mc:Choice; spd is the legacy bucket PowerPoint keeps in both branches"},
        transition_semantic(durationMs=1250),
        None,
    ),
    (
        "transition.advance.onMouseClick",
        "accepted",
        PRESET,
        {"strategy": "attribute", "attributes": ["p:transition/@advClick"]},
        transition_semantic(advance={"onClick": True, "afterMs": None}),
        None,
    ),
    (
        "transition.advance.afterTime",
        "accepted",
        PRESET,
        {"strategy": "attribute", "attributes": ["p:transition/@advTm"], "note": "advTm is milliseconds"},
        transition_semantic(advance={"onClick": False, "afterMs": 3000}),
        None,
    ),
    (
        "transition.sound.effect",
        "accepted",
        SEMANTIC,
        {"strategy": "relationship", "elements": ["p:sndAc", "p:stSnd", "p:snd"],
         "gap": "the exact p:sndAc/p:stSnd shape PowerPoint 16.113.1 writes for a transition sound is not captured here"},
        transition_semantic(sound={"src": "audio/chime.wav", "mediaType": "audio/wav", "loop": False}),
        None,
    ),
    (
        "transition.sound.loopUntilNext",
        "accepted",
        SEMANTIC,
        {"strategy": "relationship", "elements": ["p:sndAc", "p:stSnd/@loop"],
         "gap": "loop flag placement not captured here"},
        transition_semantic(sound={"src": "audio/chime.wav", "mediaType": "audio/wav", "loop": True}),
        None,
    ),
    (
        "transition.morph.objectMatching",
        "accepted",
        NATIVE,
        {"strategy": "shapeName", "convention": "!!<name>",
         "note": "Microsoft's documented forced-Morph Selection Pane naming convention, proven by the Task 1 Morph spike"},
        transition_semantic(effect="morph", parameters={"variant": "byObject"}, durationMs=2000),
        None,
    ),
    (
        "transition.applyToAll",
        "nonPersisted",
        "",
        None,
        None,
        "Apply To All is a command: it copies the active transition onto every slide. sdpm represents it by writing the same transition object into each slide JSON; nothing deck-global persists.",
    ),
    (
        "transition.preview",
        "nonPersisted",
        "",
        None,
        None,
        "Preview replays the transition in the editor and writes nothing to the package.",
    ),
    (
        "transition.effectOptions.menu",
        "nonPersisted",
        "",
        None,
        None,
        "The Effect Options menu is a container; the chosen value persists through its EPPEntryEffect candidate.",
    ),
    (
        "animation.sequence.main",
        "accepted",
        NATIVE,
        {"strategy": "timingNode", "elements": ["p:seq/@concurrent", "p:cTn/@nodeType=mainSeq"]},
        effect_semantic(),
        None,
    ),
    (
        "animation.sequence.interactive",
        "accepted",
        NATIVE,
        {"strategy": "timingNode", "elements": ["p:seq/@nodeType=interactiveSeq", "p:cond/@evt=onClick"]},
        interactive_semantic(),
        None,
    ),
    (
        "animation.pane.order",
        "accepted",
        NATIVE,
        {"strategy": "documentOrder", "note": "effect order is p:par document order inside the sequence"},
        effect_semantic(),
        None,
    ),
    (
        "animation.pane.preview",
        "nonPersisted",
        "",
        None,
        None,
        "Play From / Play Selected replays effects in the editor and writes nothing to the package.",
    ),
    (
        "animation.animationPainter",
        "nonPersisted",
        "",
        None,
        None,
        "Animation Painter copies effects between shapes; the copied effects persist through their own entries.",
    ),
    (
        "animation.target.shape",
        "accepted",
        NATIVE,
        {"strategy": "target", "elements": ["p:tgtEl/p:spTgt/@spid"]},
        effect_semantic(),
        None,
    ),
    (
        "animation.target.paragraphRange",
        "accepted",
        NATIVE,
        {"strategy": "target", "elements": ["p:spTgt/p:txEl/p:pRg/@st", "p:spTgt/p:txEl/p:pRg/@end"]},
        effect_semantic(target={"element": CATALOG_TARGET, "paragraphRange": {"start": 0, "end": 0}}),
        None,
    ),
    (
        "animation.target.buildList",
        "accepted",
        NATIVE,
        {"strategy": "target", "elements": ["p:bldLst/p:bldP/@spid", "p:bldLst/p:bldP/@grpId"]},
        effect_semantic(),
        None,
    ),
    (
        "animation.timing.durationMs",
        "accepted",
        NATIVE,
        {"strategy": "attribute", "attributes": ["p:cTn/@dur"]},
        effect_semantic(timing={"durationMs": 2000}),
        None,
    ),
    (
        "animation.timing.delayMs",
        "accepted",
        NATIVE,
        {"strategy": "attribute", "attributes": ["p:cond/@delay"]},
        effect_semantic(start={"type": "afterPrevious", "delayMs": 500}),
        None,
    ),
    (
        "animation.timing.repeatCount",
        "accepted",
        PRESET,
        {"strategy": "attribute", "attributes": ["p:cTn/@repeatCount"], "note": "1000 per repetition in OOXML"},
        effect_semantic(timing={"repeatCount": 3}),
        None,
    ),
    (
        "animation.timing.repeatDurationMs",
        "accepted",
        PRESET,
        {"strategy": "attribute", "attributes": ["p:cTn/@repeatDur"]},
        effect_semantic(timing={"repeatDurationMs": 4000}),
        None,
    ),
    (
        "animation.timing.autoReverse",
        "accepted",
        NATIVE,
        {"strategy": "attribute", "attributes": ["p:cTn/@autoRev"], "note": "captured on the Pulse emphasis animScale"},
        effect_semantic(timing={"autoReverse": True}),
        None,
    ),
    (
        "animation.timing.acceleration",
        "accepted",
        PRESET,
        {"strategy": "attribute", "attributes": ["p:cTn/@accel"],
         "note": "ST_PositiveFixedPercentage of the active duration: 100% is 100000"},
        effect_semantic(timing={"acceleration": 0.2}),
        None,
    ),
    (
        "animation.timing.deceleration",
        "accepted",
        PRESET,
        {"strategy": "attribute", "attributes": ["p:cTn/@decel"],
         "note": "ST_PositiveFixedPercentage of the active duration: 100% is 100000"},
        effect_semantic(timing={"deceleration": 0.2}),
        None,
    ),
    (
        "animation.timing.rewind",
        "accepted",
        SEMANTIC,
        {"strategy": "attribute", "attributes": ["p:cTn/@fill", "p:cTn/@autoRev"],
         "gap": "the attribute PowerPoint 16.113.1 writes for Rewind when done playing is not captured here"},
        effect_semantic(timing={"rewind": True}),
        None,
    ),
    (
        "animation.timing.smoothStart",
        "accepted",
        SEMANTIC,
        {"strategy": "attribute", "attributes": ["p:cTn/@accel"],
         "gap": "Smooth start is a motion-path option; its persisted form is not captured here"},
        effect_semantic(timing={"smoothStart": True}),
        None,
    ),
    (
        "animation.timing.smoothEnd",
        "accepted",
        SEMANTIC,
        {"strategy": "attribute", "attributes": ["p:cTn/@decel"],
         "gap": "Smooth end is a motion-path option; its persisted form is not captured here"},
        effect_semantic(timing={"smoothEnd": True}),
        None,
    ),
    (
        "animation.timing.bounceEnd",
        "accepted",
        SEMANTIC,
        {"strategy": "behavior", "elements": ["p:animScale", "p:anim"],
         "gap": "Bounce end is synthesised from extra behaviours; the exact native form is not captured here"},
        effect_semantic(timing={"bounceEnd": 300}),
        None,
    ),
    (
        "animation.timing.triggerTarget",
        "accepted",
        NATIVE,
        {"strategy": "target", "elements": ["p:cond/p:tgtEl/p:spTgt/@spid"]},
        interactive_semantic(),
        None,
    ),
    (
        "animation.textOptions.reverseOrder",
        "accepted",
        PRESET,
        {"strategy": "attribute", "attributes": ["p:bldP/@rev"]},
        effect_semantic(text={"reverseOrder": True}),
        None,
    ),
    (
        "animation.textOptions.animateAttachedShape",
        "accepted",
        NATIVE,
        {"strategy": "attribute", "attributes": ["p:bldP/@animBg"], "note": "captured as animBg=\"1\" on every shape-level gallery fixture"},
        effect_semantic(text={"animateBackground": True}),
        None,
    ),
    (
        "animation.textOptions.interItemDelayPercent",
        "accepted",
        PRESET,
        {"strategy": "behavior", "elements": ["p:iterate/p:tmPct", "p:iterate/p:tmAbs"]},
        effect_semantic(text={"unit": "byWord", "interItemDelayPercent": 10}),
        None,
    ),
    (
        "animation.afterAnimation.dimColor",
        "accepted",
        SEMANTIC,
        {"strategy": "behavior", "elements": ["p:animClr"],
         "gap": "the dim colour node PowerPoint writes after the effect is not captured here"},
        effect_semantic(afterEffect={"type": "dim", "color": "#808080"}),
        None,
    ),
    (
        "animation.sound.effect",
        "accepted",
        SEMANTIC,
        {"strategy": "relationship", "elements": ["p:audio", "p:snd"],
         "gap": "effect-sound placement inside the effect par is not captured here"},
        effect_semantic(sound={"src": "audio/click.wav", "mediaType": "audio/wav", "loop": False}),
        None,
    ),
    (
        "animation.sound.stopPreviousSound",
        "accepted",
        SEMANTIC,
        {"strategy": "behavior", "elements": ["p:cmd"],
         "gap": "Stop previous sound persists as a command node whose exact form is not captured here"},
        effect_semantic(sound={"src": "audio/click.wav", "mediaType": "audio/wav", "loop": False, "stopPrevious": True}),
        None,
    ),
    (
        "animation.media.bookmarkTrigger",
        "accepted",
        SEMANTIC,
        {"strategy": "timingNode", "elements": ["p14:bmkTgt", "p:cond/@evt=onBegin"],
         "gap": "bookmark trigger markup is not captured here"},
        effect_semantic(start={"type": "withPrevious", "delayMs": 0, "bookmark": "cue1"}),
        None,
    ),
    (
        "animation.media.playFromBookmark",
        "accepted",
        SEMANTIC,
        {"strategy": "behavior", "elements": ["p:cmd/@cmd=playFrom"],
         "note": "playFrom(0.0) is captured in the native media timing fixture; a non-zero bookmark offset is not"},
        behavior_semantic("command"),
        None,
    ),
)

#: Motion-path gallery groups. The persisted payload is p:animMotion/@path,
#: which the available evidence does not contain for the preset paths.
MOTION_PATH_GROUPS = ("lines", "arcs", "turns", "shapes", "loops", "custom")

#: SmartArt/diagram build values (normative ST_AnimationDgmBuildType).
SMARTART_BUILDS = {
    "asOneObject": "whole",
    "allAtOnce": "allAtOnce",
    "oneByOne": "one",
    "byBranchOneByOne": "cust",
    "byLevelAtOnce": "lvlAtOnce",
    "byLevelOneByOne": "lvlOne",
}

#: Text sequence options, all three captured natively.
TEXT_SEQUENCES = {
    "asOneObject": ({}, "96-fly-in-on-3-paragraph-text-box-gallery-default-sequence-as-one-object"),
    "allAtOnce": ({"build": "allAtOnce"}, "98-fly-in-on-3-paragraph-text-box-sequence-all-at-once"),
    "byParagraph": ({"build": "p"}, "99-fly-in-on-3-paragraph-text-box-sequence-by-paragraph"),
}

#: p:cTn/@restart values (normative ST_TLTimeNodeRestartType).
RESTART_VALUES = {"always": PRESET, "whenNotActive": PRESET, "never": NATIVE}

#: "More … Effects" dialog surfaces.
MORE_EFFECT_DIALOGS = ("entrance", "emphasis", "exit", "motionPath")

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
NATIVE_REPO = "office-kit/pptx"
NATIVE_COMMIT = "18b7e75cfa7fd1c6e9891ce1285a76c7889b644b"
SDEF_SOURCE = "PowerPoint.sdef (local installation)"


#: Spelled-out leading digits, so every derived identifier starts with a letter
#: (the frozen model requires ``^[A-Za-z][A-Za-z0-9._-]*$``).
NUMBER_WORDS = {"1": "one", "2": "two", "3": "three", "4": "four", "5": "five",
                "6": "six", "7": "seven", "8": "eight", "9": "nine"}


def camel(text: str) -> str:
    """Return a lowerCamelCase identifier for an sdef enumerator name."""
    parts = [part for part in "".join(c if c.isalnum() else " " for c in text).split() if part]
    if not parts:
        raise ValueError(f"cannot derive an identifier from {text!r}")
    if parts[0] in NUMBER_WORDS:
        parts[0] = NUMBER_WORDS[parts[0]]
    head, *rest = parts
    return head.lower() + "".join(part[:1].upper() + part[1:].lower() for part in rest)


def read_sdef(path: Path) -> dict[str, list[tuple[str, str]]]:
    """Read the required enumerations from a PowerPoint scripting definition."""
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.parse(str(path), parser=parser).getroot()
    found: dict[str, list[tuple[str, str]]] = {}
    for enumeration in root.iter("enumeration"):
        name = enumeration.get("name")
        if name in CANDIDATE_ENUMS:
            found[name] = [
                (item.get("name") or "", item.get("code") or "")
                for item in enumeration.findall("enumerator")
            ]
    return found


def native_evidence(fixture: str, group: str) -> dict[str, Any]:
    """Return the provenance record for one captured native fixture."""
    return {
        "source": NATIVE_REPO,
        "commit": NATIVE_COMMIT,
        "fixture": f"test/fixtures/native/{group}/{fixture}.xml",
        "capturedApplicationVersion": "16.113.3",
    }


def transition_template(slug: str, attrs: dict[str, str]) -> dict[str, Any]:
    """Return the OOXML mapping metadata for one transition value."""
    row = TRANSITION_BY_SLUG[slug]
    _, label, group, strategy, element, default_attrs, duration, spd, fallback = row
    merged = dict(default_attrs)
    merged.update(attrs)
    requires = {"standard": None, "p14": "p14", "p15": "p15", "p159": "p159", "none": None}[strategy]
    return {
        "strategy": strategy,
        "element": element,
        "attributes": merged,
        "requires": requires,
        "namespace": {"standard": P_NS, "p14": P14_NS, "p15": P15_NS, "p159": P159_NS, "none": None}[strategy],
        "alternateContent": bool(requires) or fallback is not None,
        "fallbackElement": fallback,
        "defaultDurationMs": duration,
        "legacySpeed": spd,
        "galleryTile": f"{label} ({group})",
    }


def apply_payload_gap(ooxml: dict[str, Any], category: str) -> dict[str, Any]:
    """Record the unresolved behavior payloads of an already-built preset mapping.

    Used by the candidate entries that reuse a captured tile's
    ``behaviorChildren``. An entry that already records a stronger gap (a
    missing ``presetID``, say) keeps it; the payload gap is only added when the
    identifier side is otherwise complete.
    """
    unresolved = preset_payload_gap(
        category, ooxml.get("behaviorChildren"), ooxml.get("animEffectFilter"), ooxml.get("command")
    )
    if not unresolved or "gap" in ooxml:
        return ooxml
    ooxml["unresolvedPayloads"] = unresolved
    ooxml["requiresCapture"] = True
    if unresolved == ["-"]:
        ooxml["gap"] = (
            "the presetID is corroborated but no gallery tile was captured for this effect, so its "
            "behaviour children and their payloads are unknown and the effect cannot be written"
        )
        return ooxml
    ooxml["gap"] = (
        f"the capture records {', '.join(ooxml['behaviorChildren'])} for this effect but not the value "
        f"payload of {', '.join(unresolved)}, so the effect cannot be reproduced; see "
        "behaviorPayloads.unresolved"
    )
    return ooxml


def animation_template(row: tuple[Any, ...]) -> dict[str, Any]:
    """Return the OOXML mapping metadata for one captured gallery tile."""
    category, _slug, label, preset_class, preset_id, subtype, group, children, filt, duration, _fixture = row
    template = {
        "strategy": "preset",
        "element": "p:cTn",
        "presetClass": preset_class,
        "presetId": preset_id,
        "presetSubtype": subtype,
        "behaviorChildren": [f"p:{child}" for child in children],
        "animEffectFilter": filt,
        "observedChildDurationMs": duration,
        "buildList": "p:bldP/@animBg=1" if category != "text" else "p:bldP",
        "galleryTile": f"{label} ({group})",
    }
    unresolved = preset_payload_gap(category, template["behaviorChildren"], filt)
    if unresolved:
        template["unresolvedPayloads"] = unresolved
        template["requiresCapture"] = True
        template["gap"] = (
            f"the capture records {', '.join(template['behaviorChildren'])} for this tile but not the "
            f"value payload of {', '.join(unresolved)} (coordinates, colour, scale, angle or the "
            "animated attribute name), so the effect cannot be reproduced; see "
            "behaviorPayloads.unresolved"
        )
    return template


def build_template(element: str, attrs: dict[str, str]) -> dict[str, Any]:
    """Return the OOXML mapping metadata for one build list entry.

    ``p:bldP`` carries the paragraph build in its own attributes. A chart build
    does not: ``CT_TLGraphicalObjectBuild`` has no build attribute, so the
    value lives on the ``a:bldChart`` child of ``p:bldSub``. A diagram build
    uses ``p:bldDgm/@bld``.
    """
    if element == "bldP":
        return {"strategy": "build", "element": "p:bldP", "attributes": dict(attrs)}
    value = attrs.get("build", "")
    if element == "bldGraphic":
        return {
            "strategy": "build",
            "element": "p:bldGraphic",
            "child": "p:bldSub/a:bldChart",
            "attribute": "bld",
            "value": value,
            "note": (
                "CT_TLGraphicalObjectBuild has no build attribute: the chart build type lives on the "
                "a:bldChart child of p:bldSub (ECMA-376 Part 1 DrawingML "
                "CT_AnimationChartBuildProperties). The bld token still needs Task 8 read-back."
            ),
        }
    return {
        "strategy": "build",
        "element": f"p:{element}",
        "attribute": "bld",
        "value": value,
        "note": (
            "CT_TLBuildDiagram carries the diagram build type in @bld (ECMA-376 Part 1); the token "
            "still needs Task 8 read-back."
        ),
    }


def _accepted(key: str, level: str, ooxml: dict[str, Any], semantic: dict[str, Any], evidence: dict[str, Any],
              **extra: Any) -> dict[str, Any]:
    entry = {
        "key": key,
        "status": "accepted",
        "capabilityLevel": level,
        "semanticJson": semantic,
        "ooxml": ooxml,
        "evidence": evidence,
        "verification": "nativeCapture" if level == NATIVE else "powerPointReadBackRequired",
    }
    entry.update(extra)
    return entry


def _unaccepted(key: str, status: str, reason: str, **extra: Any) -> dict[str, Any]:
    entry = {
        "key": key,
        "status": status,
        "reason": reason,
        "verification": "powerPointReadBackRequired" if status == "outOfScope" else "deterministic",
    }
    entry.update(extra)
    return entry


#: Pinned evidence for the control items whose capability level is
#: ``nativeTemplate``. Every such claim must name the artefact it came from.
CONTROL_EVIDENCE: dict[str, dict[str, Any]] = {
    "animation.sequence.main": native_evidence("01-appear", "animations/entrance"),
    "animation.sequence.interactive": {
        "source": NATIVE_REPO, "commit": NATIVE_COMMIT,
        "fixture": "test/fixtures/native-media-interactive-timing.xml",
        "capturedApplicationVersion": "16.113.3",
    },
    "animation.pane.order": native_evidence(
        "99-fly-in-on-3-paragraph-text-box-sequence-by-paragraph", "animations/text"),
    "animation.target.shape": native_evidence("01-appear", "animations/entrance"),
    "animation.target.paragraphRange": native_evidence(
        "99-fly-in-on-3-paragraph-text-box-sequence-by-paragraph", "animations/text"),
    "animation.target.buildList": native_evidence("01-appear", "animations/entrance"),
    "animation.timing.durationMs": native_evidence("05-fly-in", "animations/entrance"),
    "animation.timing.delayMs": native_evidence("05-fly-in", "animations/entrance"),
    "animation.timing.autoReverse": native_evidence("87-pulse", "animations/emphasis"),
    "animation.timing.triggerTarget": {
        "source": NATIVE_REPO, "commit": NATIVE_COMMIT,
        "fixture": "test/fixtures/native-media-interactive-timing.xml",
        "capturedApplicationVersion": "16.113.3",
    },
    "animation.textOptions.animateAttachedShape": native_evidence("01-appear", "animations/entrance"),
    "transition.morph.objectMatching": {
        "source": "sdpm Task 1 Morph spike",
        "commit": None,
        "fixture": "tests/fixtures/animations/morph-spike/manifest.json",
        "note": "verified by scripts/animation_catalog/morph_probe.py --verify-package",
    },
}


def gui_items() -> list[dict[str, Any]]:
    """Derive the catalog's GUI-item accounting from the evidence tables."""
    items: list[dict[str, Any]] = []

    for row in TRANSITION_TILES:
        slug, label = row[0], row[1]
        key = f"transition.gallery.{slug}"
        if slug == "none":
            items.append(_unaccepted(
                key, "nonPersisted",
                "the None tile removes the transition: PowerPoint writes no p:transition element, and sdpm "
                "represents it by omitting slide.transition",
            ))
            continue
        ooxml = transition_template(slug, {})
        params = semantic_parameters(slug, ooxml["attributes"])
        items.append(_accepted(
            key, NATIVE, ooxml,
            transition_semantic(effect=slug, parameters=params, durationMs=ooxml["defaultDurationMs"]),
            native_evidence(TRANSITION_FIXTURE[slug].rsplit("/", 1)[-1][:-4], "transitions"),
            label=label,
        ))

    for name, element, attrs in STANDARD_ONLY_TRANSITIONS:
        items.append(_accepted(
            f"transition.standardElement.{name}", PRESET,
            {"strategy": "standard", "element": element, "attributes": attrs, "requires": None,
             "namespace": P_NS, "alternateContent": False, "fallbackElement": None,
             "defaultDurationMs": None, "legacySpeed": None,
             "note": "normative ECMA-376 transition element with no 16.113.1 gallery tile; required so import can decode it"},
            transition_semantic(effect=name, parameters=attrs, durationMs=1000),
            {"source": "ECMA-376 Part 1 PresentationML slide transitions", "commit": None},
        ))

    items.append(_unaccepted(
        "transition.legacyEntryEffect", "outOfScope", _LEGACY_NO_ELEMENT, openQuestion=True,
    ))
    items.append(_unaccepted(
        "animation.legacyShapeEntryEffect", "outOfScope",
        "EPPEntryEffect values in the 0x00f60d** band are PowerPoint's legacy per-shape entry animations "
        "(AnimationSettings.EntryEffect), not slide transitions. The equivalent modern surface is the "
        "Animations gallery, accounted through the MsoAnimEffect candidates.",
    ))

    for row in ANIMATION_TILES:
        category, slug = row[0], row[1]
        items.append(_accepted(
            f"animation.gallery.{category}.{slug}", NATIVE, animation_template(row),
            effect_semantic(preset={"category": "entrance" if category == "text" else category,
                                    "effect": slug, "variant": None}),
            native_evidence(row[10], f"animations/{category}"),
            label=row[2],
        ))

    for name, (preset_id, level, command) in MEDIA_PRESET.items():
        slug = camel(name).replace("animationType", "") or name
        slug = slug[0].lower() + slug[1:]
        ooxml = {
            "strategy": "preset", "element": "p:cTn", "presetClass": "mediacall",
            "presetId": preset_id, "presetSubtype": 0,
            "behaviorChildren": ["p:cmd"], "command": command,
            "requiresCapture": preset_id is None,
        }
        if preset_id is None:
            ooxml["gap"] = (
                "presetClass mediacall is captured, but this command's presetID is not; only Play "
                "(presetID 1, cmd playFrom(0.0)) appears in the available native media timing evidence"
            )
        items.append(_accepted(
            f"animation.gallery.media.{slug}", level, ooxml,
            effect_semantic(preset={"category": "media", "effect": slug, "variant": None}),
            native_evidence("native-media-background-timing", "") if preset_id else
            {"source": "ECMA-376 presetClass mediacall", "commit": None},
        ))

    for group in MOTION_PATH_GROUPS:
        items.append(_accepted(
            f"animation.gallery.motionPath.{group}", SEMANTIC,
            {"strategy": "animMotion", "element": "p:animMotion", "pathAttribute": "p:animMotion/@path",
             "requiresCapture": True,
             "gap": "PowerPoint carries preset motion paths as literal SVG path data in p:animMotion/@path; "
                    "that geometry is not present in the available evidence, so the writer must emit a "
                    "custom path or defer until Task 8 captures it"},
            effect_semantic(preset={"category": "motionPath", "effect": group, "variant": None}),
            {"source": "Animations ribbon gallery, Motion Paths group", "commit": None},
        ))

    for dialog in MORE_EFFECT_DIALOGS:
        items.append(_unaccepted(
            f"animation.moreEffects.{dialog}", "nonPersisted",
            f"the More {dialog} Effects dialog is a selection surface; the chosen effect persists through "
            f"its own MsoAnimEffect candidate",
        ))

    items.append(_accepted(
        "animation.addAnimation.customBehavior", SEMANTIC,
        {"strategy": "behaviorPrimitives", "elements": [v[1] for v in BEHAVIOR_MAP.values() if v[1]],
         "note": "a custom effect is modelled as an explicit behaviours list rather than a preset"},
        behavior_semantic("set"),
        {"source": SDEF_SOURCE, "commit": None},
    ))

    return items


def enum_value_items(sdef_enums: dict[str, list[tuple[str, str]]]) -> list[dict[str, Any]]:
    """Derive the GUI items that correspond one-to-one with an enum value."""
    items: list[dict[str, Any]] = []

    for name, (semantic, node_type, level) in TRIGGER_MAP.items():
        ooxml = {"strategy": "timingNode", "nodeType": node_type}
        if node_type is None:
            ooxml["gap"] = (
                "msoAnimTriggerNone reports an effect with no trigger; the persisted form is the absence of "
                "a start condition and is not captured here"
            )
        items.append(_accepted(
            f"animation.start.{semantic}", level, ooxml,
            trigger_semantic(semantic),
            native_evidence("05-fly-in", "animations/entrance") if level == NATIVE
            else {"source": "ECMA-376 ST_TLTimeNodeType", "commit": None},
        ))

    for name, (semantic, iterate, level) in TEXT_UNIT_MAP.items():
        items.append(_accepted(
            f"animation.textOptions.unit.{semantic}", level,
            {"strategy": "iterate", "element": "p:iterate", "type": iterate,
             "interval": "p:tmPct or p:tmAbs, required by CT_TLIterateData"},
            text_unit_semantic(semantic),
            native_evidence("99-fly-in-on-3-paragraph-text-box-sequence-by-paragraph", "animations/text")
            if level == NATIVE else {"source": "ECMA-376 ST_IterateType", "commit": None},
        ))

    for name, (semantic, element, attrs, level) in LEVEL_MAP.items():
        items.append(_accepted(
            f"animation.textOptions.level.{semantic}", level,
            build_template(element, attrs),
            effect_semantic(text={"level": semantic}) if element == "bldP"
            else effect_semantic(chart={"build": semantic}),
            native_evidence("96-fly-in-on-3-paragraph-text-box-gallery-default-sequence-as-one-object",
                            "animations/text") if level == NATIVE
            else {"source": "ECMA-376 ST_AnimationChartBuildType / CT_TLBuildParagraph", "commit": None},
        ))

    for name, (semantic, elements, level) in AFTER_EFFECT_MAP.items():
        ooxml: dict[str, Any] = {"strategy": "afterEffect", "candidateElements": elements}
        if level != NATIVE:
            ooxml["requiresCapture"] = True
            ooxml["gap"] = (
                "the node PowerPoint 16.113.1 writes for this After animation value is not captured here; "
                "the listed ECMA-376 elements are the candidates to verify in Task 8"
            )
        items.append(_accepted(
            f"animation.afterAnimation.{semantic}", level, ooxml,
            effect_semantic(afterEffect={"type": semantic}),
            native_evidence("01-appear", "animations/entrance") if level == NATIVE
            else {"source": "ECMA-376 CT_TLCommonTimeNodeData/@afterEffect", "commit": None},
        ))

    for name, (semantic, element, level) in BEHAVIOR_MAP.items():
        key = f"animation.behavior.{semantic}"
        if element is None:
            items.append(_unaccepted(
                key, "nonPersisted",
                "msoAnimTypeNone reports the absence of a behaviour; PowerPoint writes no behaviour node, so "
                "a no-op behaviour round-trips in JSON with no OOXML counterpart",
            ))
            continue
        items.append(_accepted(
            key, level, {"strategy": "behavior", "element": element},
            behavior_semantic(semantic),
            native_evidence("05-fly-in", "animations/entrance"),
        ))

    for enumerator, _code in sdef_enums["MsoAnimDirection"]:
        semantic = camel(enumerator)
        items.append(_accepted(
            f"animation.effectOptions.direction.{semantic}", SEMANTIC,
            {"strategy": "presetSubtype", "attribute": "p:cTn/@presetSubtype", "presetSubtype": None,
             "requiresCapture": True, "gap": DIRECTION_GAP},
            effect_semantic(preset={"category": "entrance", "effect": "flyIn", "variant": semantic}),
            {"source": SDEF_SOURCE, "commit": None},
        ))

    for value, level in RESTART_VALUES.items():
        items.append(_accepted(
            f"animation.timing.restart.{value}", level,
            {"strategy": "attribute", "attributes": ["p:cTn/@restart"],
             "value": {"always": "always", "whenNotActive": "whenNotActive", "never": "never"}[value]},
            effect_semantic(timing={"restart": value}),
            native_evidence("01-appear", "animations/entrance") if level == NATIVE
            else {"source": "ECMA-376 ST_TLTimeNodeRestartType", "commit": None},
        ))

    for value, (attrs, fixture) in TEXT_SEQUENCES.items():
        items.append(_accepted(
            f"animation.textOptions.sequence.{value}", NATIVE,
            {"strategy": "build", "element": "p:bldP", "attributes": attrs},
            effect_semantic(text={"sequence": value}),
            native_evidence(fixture, "animations/text"),
        ))

    for value, build in SMARTART_BUILDS.items():
        items.append(_accepted(
            f"animation.smartArt.build.{value}", PRESET,
            build_template("bldDgm", {"build": build}),
            effect_semantic(smartArt={"build": value}),
            {"source": "ECMA-376 ST_AnimationDgmBuildType", "commit": None},
        ))

    for key, status, level, ooxml, semantic, reason in CONTROL_ITEMS:
        if status == "accepted":
            assert ooxml is not None and semantic is not None
            evidence = CONTROL_EVIDENCE.get(
                key, {"source": "PowerPoint 16.113.1 ribbon/dialog surface", "commit": None})
            items.append(_accepted(key, level, ooxml, semantic, evidence))
        else:
            items.append(_unaccepted(key, status, reason or ""))

    return items


# ---------------------------------------------------------------------------
# Candidate accounting
# ---------------------------------------------------------------------------
def _effect_ordinal(code: str) -> int:
    return int(code, 16) & 0xFF


def _epp_candidate(key: str, enumerator: str, code: str) -> dict[str, Any]:
    if enumerator == "entry effect unset":
        return _unaccepted(
            key, "rejected",
            "enumeration sentinel: PowerPoint reports 'unset' for a slide whose transition is not set; it is "
            "not a value the GUI can apply",
            guiKey="transition.gallery.none", verification="deterministic",
        )
    if enumerator == "entry effect none":
        return _unaccepted(
            key, "nonPersisted",
            "no transition: PowerPoint writes no p:transition element, and sdpm omits slide.transition",
            guiKey="transition.gallery.none",
        )
    if code.startswith(SHAPE_ENTRY_CODE_PREFIX):
        return _unaccepted(
            key, "outOfScope",
            "legacy per-shape entry animation (AnimationSettings.EntryEffect band 0x00f60d**), not a slide "
            "transition; the modern equivalent is accounted through the MsoAnimEffect candidates",
            guiKey="animation.legacyShapeEntryEffect",
        )

    kind, target, attrs, level = EPP_MAP[enumerator]
    if kind == "oos":
        return _unaccepted(key, "outOfScope", target, guiKey="transition.legacyEntryEffect", openQuestion=True)
    if kind == "std":
        name = next(n for n, element, _ in STANDARD_ONLY_TRANSITIONS if element == target)
        ooxml = {"strategy": "standard", "element": target, "attributes": attrs, "requires": None,
                 "namespace": P_NS, "alternateContent": False, "fallbackElement": None,
                 "attributeDomain": STANDARD_DIR_DOMAIN.get(target)}
        return _accepted(
            key, level, ooxml,
            transition_semantic(effect=name, parameters=attrs, durationMs=1000),
            {"source": "ECMA-376 Part 1 PresentationML slide transitions", "commit": None},
            guiKey=f"transition.standardElement.{name}",
        )

    ooxml = transition_template(target, attrs)
    row = TRANSITION_BY_SLUG[target]
    if level == SEMANTIC:
        ooxml["requiresCapture"] = True
        ooxml["gap"] = (
            f"the {row[4]} attribute values for this variant are an extension-namespace detail that the "
            "available native capture does not contain; the captured default is "
            f"{row[5] or 'no attributes'}. Resolve by PowerPoint read-back (Task 8)."
        )
    elif level == PRESET and ooxml["strategy"] == "standard":
        ooxml["attributeDomain"] = STANDARD_DIR_DOMAIN.get(ooxml["element"])
    params = semantic_parameters(target, ooxml["attributes"])
    evidence = native_evidence(TRANSITION_FIXTURE[target].rsplit("/", 1)[-1][:-4], "transitions")
    return _accepted(
        key, level, ooxml,
        transition_semantic(effect=target, parameters=params, durationMs=ooxml["defaultDurationMs"]),
        evidence, guiKey=f"transition.gallery.{target}",
    )


def _effect_candidate(key: str, enumerator: str, code: str) -> dict[str, Any]:
    ordinal = _effect_ordinal(code)
    if ordinal == 0:
        return _accepted(
            key, SEMANTIC,
            {"strategy": "behaviorPrimitives", "presetClass": None, "presetId": None, "requiresCapture": False,
             "note": "msoAnimEffectCustom is not a gallery preset; a custom effect is written as explicit "
                     "behaviour primitives"},
            behavior_semantic("set"),
            {"source": SDEF_SOURCE, "commit": None},
            guiKey="animation.addAnimation.customBehavior",
        )
    if ordinal <= ENTR_EXIT_ORDINAL_MAX:
        tile = ANIMATION_BY_PRESET.get(("entr", ordinal)) or ANIMATION_BY_PRESET.get(("exit", ordinal))
        if ordinal <= ENTR_EXIT_CONFIDENT_MAX:
            level = NATIVE if tile else PRESET
            ooxml = {
                "strategy": "preset", "element": "p:cTn", "presetClass": ["entr", "exit"],
                "presetId": ordinal, "presetSubtype": tile[5] if tile else None,
                "behaviorChildren": [f"p:{c}" for c in tile[7]] if tile else None,
                "animEffectFilter": tile[8] if tile else None,
                "note": "the MsoAnimEffect ordinal equals the OOXML entrance/exit presetID in this band; an "
                        "exit effect uses the same presetID with presetClass=\"exit\"",
            }
            if tile:
                apply_payload_gap(ooxml, tile[0])
            else:
                apply_payload_gap(ooxml, "entrance")
            evidence = (
                native_evidence(tile[10], f"animations/{tile[0]}") if tile
                else {"source": "COM-derived entrance/exit presetID table (ChristopherVR/ooxml)",
                      "commit": "e269a0bb944062871e5bcd05856ce65570e2e137"}
            )
            extra: dict[str, Any] = {"guiKey": f"animation.gallery.{tile[0]}.{tile[1]}" if tile
                                     else "animation.moreEffects.entrance"}
            return _accepted(key, level, ooxml, effect_semantic(
                preset={"category": "entrance", "effect": tile[1] if tile else camel(enumerator.replace("animation type", "")),
                        "variant": None}), evidence, **extra)

        match = EFFECT_NAME_MATCH.get(enumerator)
        ooxml = {
            "strategy": "preset", "element": "p:cTn", "presetClass": ["entr", "exit"],
            "presetId": None, "presetSubtype": None, "requiresCapture": True,
            "gap": ENTR_EXIT_DIVERGENCE_GAP.format(ordinal=ordinal),
        }
        if match:
            tile_row = ANIMATION_BY_KEY[match]
            ooxml["nameMatchedGalleryItem"] = f"animation.gallery.{match[0]}.{match[1]}"
            ooxml["nameMatchedPresetId"] = tile_row[4]
            ooxml["nameMatchConfidence"] = (
                "nameMatchOnly: the COM-derived reference warns that the MsoAnimEffect constant does not "
                "reliably land on the catalog's assumed id for a gallery name above 26"
            )
        return _accepted(
            key, SEMANTIC, ooxml,
            effect_semantic(preset={"category": "entrance",
                                    "effect": camel(enumerator.replace("animation type", "")), "variant": None}),
            {"source": SDEF_SOURCE, "commit": None},
            guiKey=(f"animation.gallery.{match[0]}.{match[1]}" if match else "animation.moreEffects.entrance"),
        )

    if enumerator in EMPHASIS_PRESET_ID:
        preset_id = EMPHASIS_PRESET_ID[enumerator]
        tile = ANIMATION_BY_PRESET.get(("emph", preset_id)) if preset_id else None
        level = NATIVE if tile else (PRESET if preset_id else SEMANTIC)
        ooxml = {
            "strategy": "preset", "element": "p:cTn", "presetClass": "emph",
            "presetId": preset_id, "presetSubtype": tile[5] if tile else None,
            "behaviorChildren": [f"p:{c}" for c in tile[7]] if tile else None,
            "animEffectFilter": tile[8] if tile else None,
        }
        if preset_id is None:
            ooxml["requiresCapture"] = True
            ooxml["gap"] = (
                "this emphasis effect has no entry in the COM-derived emphasis presetID table and no gallery "
                "tile, so its OOXML presetID is not established; resolve by PowerPoint read-back (Task 8)"
            )
        apply_payload_gap(ooxml, "emphasis")
        evidence = (
            native_evidence(tile[10], "animations/emphasis") if tile
            else {"source": "COM-derived emphasis presetID table (ChristopherVR/ooxml)",
                  "commit": "e269a0bb944062871e5bcd05856ce65570e2e137"} if preset_id
            else {"source": SDEF_SOURCE, "commit": None}
        )
        return _accepted(
            key, level, ooxml,
            effect_semantic(preset={"category": "emphasis",
                                    "effect": tile[1] if tile else camel(enumerator.replace("animation type", "")),
                                    "variant": None}),
            evidence,
            guiKey=f"animation.gallery.emphasis.{tile[1]}" if tile else "animation.moreEffects.emphasis",
        )

    if enumerator in MEDIA_PRESET:
        preset_id, level, command = MEDIA_PRESET[enumerator]
        slug = camel(enumerator.replace("animation type", ""))
        ooxml = {"strategy": "preset", "element": "p:cTn", "presetClass": "mediacall",
                 "presetId": preset_id, "presetSubtype": 0, "behaviorChildren": ["p:cmd"], "command": command,
                 "requiresCapture": preset_id is None}
        if preset_id is None:
            ooxml["gap"] = (
                "presetClass mediacall is captured but this command's presetID is not; only Play is present "
                "in the available native media timing evidence"
            )
        return _accepted(
            key, level, ooxml,
            effect_semantic(preset={"category": "media", "effect": slug, "variant": None}),
            native_evidence("native-media-background-timing", "") if preset_id
            else {"source": "ECMA-376 presetClass mediacall", "commit": None},
            guiKey=f"animation.gallery.media.{slug}",
        )

    slug = camel(enumerator.replace("animation type", ""))
    return _accepted(
        key, SEMANTIC,
        {"strategy": "animMotion", "element": "p:animMotion", "presetClass": "path",
         "presetId": None, "pathAttribute": "p:animMotion/@path", "requiresCapture": True,
         "gap": "a preset motion path persists as literal SVG path data in p:animMotion/@path; the OOXML "
                "presetID is informational only. That geometry is not in the available evidence, so the "
                "writer must emit a custom path or defer until Task 8 captures it."},
        effect_semantic(preset={"category": "motionPath", "effect": slug, "variant": None}),
        {"source": SDEF_SOURCE, "commit": None},
        guiKey="animation.moreEffects.motionPath",
    )


def candidate_entries(sdef_enums: dict[str, list[tuple[str, str]]]) -> list[dict[str, Any]]:
    """Account for every candidate in the eight required sdef enumerations."""
    entries: list[dict[str, Any]] = []
    for enum_name in CANDIDATE_ENUMS:
        for enumerator, code in sdef_enums[enum_name]:
            key = f"{enum_name}.{enumerator}"
            if enum_name == "EPPEntryEffect":
                entry = _epp_candidate(key, enumerator, code)
            elif enum_name == "MsoAnimEffect":
                entry = _effect_candidate(key, enumerator, code)
            elif enum_name == "MsoAnimDirection":
                semantic = camel(enumerator)
                entry = _accepted(
                    key, SEMANTIC,
                    {"strategy": "presetSubtype", "attribute": "p:cTn/@presetSubtype", "presetSubtype": None,
                     "requiresCapture": True, "gap": DIRECTION_GAP},
                    effect_semantic(preset={"category": "entrance", "effect": "flyIn", "variant": semantic}),
                    {"source": SDEF_SOURCE, "commit": None},
                    guiKey=f"animation.effectOptions.direction.{semantic}",
                )
            elif enum_name == "MsoAnimTriggerType":
                semantic, node_type, level = TRIGGER_MAP[enumerator]
                ooxml = {"strategy": "timingNode", "nodeType": node_type}
                if node_type is None:
                    ooxml["requiresCapture"] = True
                    ooxml["gap"] = (
                        "msoAnimTriggerNone reports an effect with no trigger; its persisted form is not "
                        "captured here"
                    )
                entry = _accepted(
                    key, level, ooxml, trigger_semantic(semantic),
                    native_evidence("05-fly-in", "animations/entrance") if level == NATIVE
                    else {"source": "ECMA-376 ST_TLTimeNodeType", "commit": None},
                    guiKey=f"animation.start.{semantic}",
                )
            elif enum_name == "MsoAnimateByLevel":
                semantic, element, attrs, level = LEVEL_MAP[enumerator]
                entry = _accepted(
                    key, level, build_template(element, attrs),
                    effect_semantic(text={"level": semantic}) if element == "bldP"
                    else effect_semantic(chart={"build": semantic}),
                    native_evidence("96-fly-in-on-3-paragraph-text-box-gallery-default-sequence-as-one-object",
                                    "animations/text") if level == NATIVE
                    else {"source": "ECMA-376 ST_AnimationChartBuildType / CT_TLBuildParagraph", "commit": None},
                    guiKey=f"animation.textOptions.level.{semantic}",
                )
            elif enum_name == "MsoAnimTextUnitEffect":
                semantic, iterate, level = TEXT_UNIT_MAP[enumerator]
                entry = _accepted(
                    key, level,
                    {"strategy": "iterate", "element": "p:iterate", "type": iterate,
                     "interval": "p:tmPct or p:tmAbs, required by CT_TLIterateData"},
                    text_unit_semantic(semantic),
                    native_evidence("99-fly-in-on-3-paragraph-text-box-sequence-by-paragraph", "animations/text")
                    if level == NATIVE else {"source": "ECMA-376 ST_IterateType", "commit": None},
                    guiKey=f"animation.textOptions.unit.{semantic}",
                )
            elif enum_name == "MsoAnimAfterEffect":
                semantic, elements, level = AFTER_EFFECT_MAP[enumerator]
                ooxml = {"strategy": "afterEffect", "candidateElements": elements}
                if level != NATIVE:
                    ooxml["requiresCapture"] = True
                    ooxml["gap"] = (
                        "the node PowerPoint 16.113.1 writes for this After animation value is not captured "
                        "here; the listed ECMA-376 elements are the candidates to verify in Task 8"
                    )
                entry = _accepted(
                    key, level, ooxml, effect_semantic(afterEffect={"type": semantic}),
                    native_evidence("01-appear", "animations/entrance") if level == NATIVE
                    else {"source": "ECMA-376 CT_TLCommonTimeNodeData/@afterEffect", "commit": None},
                    guiKey=f"animation.afterAnimation.{semantic}",
                )
            else:  # MsoAnimType
                semantic, element, level = BEHAVIOR_MAP[enumerator]
                if element is None:
                    entry = _unaccepted(
                        key, "nonPersisted",
                        "msoAnimTypeNone reports the absence of a behaviour; PowerPoint writes no behaviour "
                        "node, so a no-op behaviour round-trips in JSON with no OOXML counterpart",
                        guiKey=f"animation.behavior.{semantic}",
                    )
                else:
                    entry = _accepted(
                        key, level, {"strategy": "behavior", "element": element},
                        behavior_semantic(semantic),
                        native_evidence("05-fly-in", "animations/entrance"),
                        guiKey=f"animation.behavior.{semantic}",
                    )
            entry["enum"] = enum_name
            entry["enumerator"] = enumerator
            entry["code"] = code
            entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Catalog assembly and checking
# ---------------------------------------------------------------------------
def build_catalog(manifest: dict[str, Any], sdef_enums: dict[str, list[tuple[str, str]]]) -> dict[str, Any]:
    """Build the full catalog from the evidence tables and the sdef."""
    items = gui_items() + enum_value_items(sdef_enums)
    items.sort(key=lambda entry: entry["key"])
    candidates = candidate_entries(sdef_enums)
    candidates.sort(key=lambda entry: entry["key"])
    counts: dict[str, int] = {status: 0 for status in STATUSES}
    for entry in candidates:
        counts[entry["status"]] += 1
    item_counts: dict[str, int] = {status: 0 for status in STATUSES}
    for entry in items:
        item_counts[entry["status"]] += 1
    return {
        "schemaVersion": CATALOG_SCHEMA_VERSION,
        "baseline": {
            "application": BASELINE_APPLICATION,
            "version": BASELINE_VERSION,
            "platform": BASELINE_PLATFORM,
            "generatedAt": BASELINE_GENERATED_AT,
            "guiManifest": f"{DEFAULT_MANIFEST.name}@{manifest['manifestVersion']}",
        },
        "provenance": {
            "references": PROVENANCE_REFERENCES,
            "legacySpeedMs": LEGACY_SPEED_MS,
            "legacySpeedEvidence": LEGACY_SPEED_EVIDENCE,
            "presetSubtypeEvidence": PRESET_SUBTYPE_EVIDENCE,
            "entranceExitConfidentOrdinalMax": ENTR_EXIT_CONFIDENT_MAX,
            "generator": "scripts/animation_catalog/generate.py",
            "powerPointAutomation": (
                "not used: the AppleScript oracle in scripts/animation_catalog/powerpoint.applescript was "
                "never executed for this catalog. The Task 1 spike recorded a -10004 privilege violation when "
                "addressing PowerPoint from this dashboard, and Task 3 was scoped not to launch or drive "
                "PowerPoint, so every value here comes from the offline scripting definition, captured native "
                "OOXML, and normative schema. VBA is not used at all."
            ),
        },
        "alternateContent": ALTERNATE_CONTENT,
        "behaviorPayloads": BEHAVIOR_PAYLOADS,
        "capabilityLevels": {
            NATIVE: "exact OOXML captured from retail PowerPoint for this value",
            PRESET: "element/attribute/identifier fixed by a normative ECMA-376 enumeration or corroborated by two independent sources; no visual capture",
            SEMANTIC: "JSON round-trip only; the OOXML identifier or geometry is not established here and the writer must capture it or emit a documented fallback",
        },
        "summary": {
            "candidateEnums": dict(CANDIDATE_ENUMS),
            "candidateTotal": sum(CANDIDATE_ENUMS.values()),
            "candidateStatusCounts": counts,
            "guiItemTotal": len(items),
            "guiItemStatusCounts": item_counts,
            "openQuestions": sum(1 for entry in candidates + items if entry.get("openQuestion")),
        },
        "guiItems": items,
        "candidates": candidates,
    }


def dump(catalog: dict[str, Any]) -> str:
    """Serialise the catalog deterministically."""
    return json.dumps(catalog, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def check(manifest: dict[str, Any], catalog: dict[str, Any],
          sdef_enums: dict[str, list[tuple[str, str]]] | None,
          oracle_text: str | None = None) -> list[str]:
    """Compare sdef, manifest, catalog and oracle. Return human findings."""
    findings: list[str] = []

    baseline = catalog.get("baseline", {})
    for field in ("application", "version", "platform", "generatedAt", "guiManifest"):
        if not str(baseline.get(field, "")).strip():
            findings.append(f"catalog.baseline.{field} is missing")
    if baseline.get("generatedAt") != BASELINE_GENERATED_AT:
        findings.append(
            f"catalog.baseline.generatedAt drifted: {baseline.get('generatedAt')!r} != {BASELINE_GENERATED_AT!r}"
        )
    expected_manifest = f"{DEFAULT_MANIFEST.name}@{manifest.get('manifestVersion')}"
    if baseline.get("guiManifest") != expected_manifest:
        findings.append(f"catalog.baseline.guiManifest {baseline.get('guiManifest')!r} != {expected_manifest!r}")

    manifest_items = {entry["key"]: entry for entry in manifest.get("items", [])}
    catalog_items = {entry["key"]: entry for entry in catalog.get("guiItems", [])}
    for key in sorted(manifest_items.keys() - catalog_items.keys()):
        findings.append(f"GUI manifest item {key!r} is not accounted for by the catalog")
    for key in sorted(catalog_items.keys() - manifest_items.keys()):
        findings.append(f"catalog GUI item {key!r} is absent from the GUI manifest")
    for key in sorted(manifest_items.keys() & catalog_items.keys()):
        expected = manifest_items[key].get("status")
        actual = catalog_items[key].get("status")
        if expected != actual:
            findings.append(f"GUI item {key!r} status drift: manifest expects {expected!r}, catalog has {actual!r}")
        for field in ("control", "value", "surface", "sourceEvidence", "persisted", "verificationMethod"):
            if field not in manifest_items[key]:
                findings.append(f"GUI manifest item {key!r} is missing required field {field!r}")

    manifest_candidates = {entry["key"]: entry for entry in manifest.get("candidates", [])}
    catalog_candidates = {entry["key"]: entry for entry in catalog.get("candidates", [])}
    for key in sorted(manifest_candidates.keys() - catalog_candidates.keys()):
        findings.append(f"GUI manifest candidate {key!r} is missing from the catalog")
    for key in sorted(catalog_candidates.keys() - manifest_candidates.keys()):
        findings.append(f"catalog candidate {key!r} is absent from the GUI manifest")
    for key in sorted(manifest_candidates.keys() & catalog_candidates.keys()):
        expected = manifest_candidates[key].get("status")
        actual = catalog_candidates[key].get("status")
        if expected != actual:
            findings.append(f"candidate {key!r} status drift: manifest expects {expected!r}, catalog has {actual!r}")
        if manifest_candidates[key].get("guiKey") != catalog_candidates[key].get("guiKey"):
            findings.append(
                f"candidate {key!r} guiKey drift: manifest {manifest_candidates[key].get('guiKey')!r} != "
                f"catalog {catalog_candidates[key].get('guiKey')!r}"
            )

    for group, entries in (("guiItems", catalog_items), ("candidates", catalog_candidates)):
        for key, entry in sorted(entries.items()):
            status = entry.get("status")
            if status not in STATUSES:
                findings.append(f"{group} {key!r} has invalid status {status!r}")
                continue
            if status == "accepted":
                if entry.get("capabilityLevel") not in CAPABILITY_LEVELS:
                    findings.append(f"{group} {key!r} is accepted without a valid capabilityLevel")
                if not isinstance(entry.get("semanticJson"), dict) or not entry["semanticJson"]:
                    findings.append(f"{group} {key!r} is accepted without semanticJson")
                ooxml = entry.get("ooxml")
                if not isinstance(ooxml, dict) or not ooxml:
                    findings.append(f"{group} {key!r} is accepted without ooxml metadata")
                elif entry.get("capabilityLevel") == NATIVE and not entry.get("evidence", {}).get("fixture"):
                    findings.append(f"{group} {key!r} claims nativeTemplate without a fixture reference")
                elif entry.get("capabilityLevel") == SEMANTIC and not (ooxml.get("gap") or ooxml.get("note")):
                    findings.append(f"{group} {key!r} is semanticPreservationOnly without a documented gap")
            elif not str(entry.get("reason", "")).strip():
                findings.append(f"{group} {key!r} has status {status!r} without a reason")
            if group == "candidates" and entry.get("guiKey") not in catalog_items:
                findings.append(f"candidate {key!r} references unknown GUI key {entry.get('guiKey')!r}")

    declared = manifest.get("candidateEnums", [])
    declared_counts = {row["enum"]: row["expectedCount"] for row in declared}
    if declared_counts != CANDIDATE_ENUMS:
        findings.append(
            f"GUI manifest candidateEnums {declared_counts} != generator expectation {dict(CANDIDATE_ENUMS)}"
        )
    for enum_name, expected_count in CANDIDATE_ENUMS.items():
        actual = sum(1 for entry in catalog_candidates.values() if entry.get("enum") == enum_name)
        if actual != expected_count:
            findings.append(f"catalog has {actual} {enum_name} candidates, expected {expected_count}")

    if oracle_text is not None:
        findings.extend(oracle_findings(oracle_text, sdef_enums))

    if sdef_enums is None:
        return findings

    for enum_name, expected_count in CANDIDATE_ENUMS.items():
        local = sdef_enums.get(enum_name)
        if local is None:
            findings.append(f"local sdef does not expose enumeration {enum_name}")
            continue
        if len(local) != expected_count:
            findings.append(f"local sdef {enum_name} has {len(local)} enumerators, expected {expected_count}")
        local_keys = {f"{enum_name}.{name}" for name, _ in local}
        catalog_keys = {k for k, v in catalog_candidates.items() if v.get("enum") == enum_name}
        for key in sorted(local_keys - catalog_keys):
            findings.append(f"local sdef candidate {key!r} is missing from the catalog")
        for key in sorted(catalog_keys - local_keys):
            findings.append(f"catalog candidate {key!r} is not in the local sdef")
        for name, code in local:
            entry = catalog_candidates.get(f"{enum_name}.{name}")
            if entry is not None and entry.get("code") != code:
                findings.append(f"candidate {enum_name}.{name} code drift: {entry.get('code')!r} != {code!r}")

    regenerated = build_catalog(manifest, sdef_enums)
    if dump(regenerated) != dump(catalog):
        findings.append("checked-in catalog differs from a deterministic regeneration (run --write)")
    return findings


# ---------------------------------------------------------------------------
# Oracle script: generated candidate arrays, syntax contract, package analysis
# ---------------------------------------------------------------------------
#: The checked-in scripting oracle. This module generates the candidate arrays
#: inside it and checks them, but never starts it: driving PowerPoint is a
#: maintainer action that the oracle itself gates behind an explicit argument.
DEFAULT_ORACLE = Path(__file__).resolve().parent / "powerpoint.applescript"

ORACLE_BEGIN = "-- >>> BEGIN GENERATED sdef CANDIDATE ARRAYS >>>"
ORACLE_END = "-- <<< END GENERATED sdef CANDIDATE ARRAYS <<<"
ORACLE_RUN_TOKEN = "--run-powerpoint"
ORACLE_ARRAY_KINDS = ("constants", "names", "codes")

#: Object-model constructs the oracle must use, each one declared by the local
#: scripting definition. A rewrite that drifts back to a shape the dictionary
#: does not expose - a settable ``entry effect`` on ``slide``, an
#: ``animation effect`` element, a ``main sequence`` hanging off the slide
#: rather than off its ``timeline`` - fails ``--check``.
REQUIRED_ORACLE_TOKENS: tuple[str, ...] = (
    "entry effect of slide show transition of theSlide",
    "transition duration of slide show transition of theSlide",
    "main sequence of timeline of theSlide",
    "add effect (main sequence of timeline of theSlide) for theShape",
    "fx theConstant trigger on page click",
    "fx baseEffect trigger theConstant",
    "fx baseEffect level theConstant trigger on page click",
    "convert to text unit effect (main sequence of timeline of theSlide)",
    "add behavior theEffect type theConstant",
    "animation effect type of theEffect",
    "direction of effect parameters of theEffect",
    "build by level of effect information of theEffect",
    "text unit effect information of effect information of theConverted",
    "after effect information of effect information of theEffect",
    "animation behavior type of theBehavior",
    "count of effects of main sequence of timeline of theSlide",
    "auto shape type:autoshape rounded rectangle",
    "layout:slide layout blank",
    "save probe in (POSIX file packagePath) as save as Open XML presentation",
)

#: Markers of an unfinished oracle. The Task 3 draft shipped empty candidate
#: lists and a constant mapper that always raised; neither may come back.
FORBIDDEN_ORACLE_TOKENS: tuple[str, ...] = (
    "return {}",
    "fill from",
    "before running",
    "TODO",
    "FIXME",
    "not implemented",
)

#: Namespace prefixes used when reporting OOXML facts from a saved package.
ORACLE_PREFIXES = {
    P_NS: "p",
    P14_NS: "p14",
    P15_NS: "p15",
    P159_NS: "p159",
    MC_NS: "mc",
    "http://schemas.openxmlformats.org/drawingml/2006/main": "a",
}

ORACLE_SLIDE_PART = re.compile(r"ppt/slides/slide(\d+)\.xml")
_ORACLE_HANDLER = re.compile(r"^on (\w+)\(\)\n(.*?)\nend \1$", re.MULTILINE | re.DOTALL)

#: Timing elements worth reporting, and the behaviour elements summarised under
#: each preset node.
ORACLE_TIMING_ELEMENTS = frozenset({
    "cTn", "cond", "iterate", "bldP", "bldDgm", "bldGraphic", "bldLst",
    "anim", "animClr", "animEffect", "animMotion", "animRot", "animScale", "cmd", "set",
})
ORACLE_BEHAVIOR_ELEMENTS = frozenset({
    "anim", "animClr", "animEffect", "animMotion", "animRot", "animScale", "cmd", "set",
})
#: A ``p:cTn`` is only reported when it carries one of these, which is what
#: separates a preset or trigger node from the wrappers around it.
ORACLE_CTN_ATTRS = ("presetClass", "presetID", "presetSubtype", "nodeType", "afterEffect")


def oracle_prefix(enum_name: str) -> str:
    """Return the handler-name prefix the oracle uses for one enumeration."""
    for acronym in ("EPP", "Mso"):
        if enum_name.startswith(acronym):
            return acronym.lower() + enum_name[len(acronym):]
    return enum_name[:1].lower() + enum_name[1:]


def _oracle_list(items: list[str], indent: str) -> str:
    return "{" + (", \u00ac\n" + indent).join(items) + "}"


def render_oracle_arrays(sdef_enums: dict[str, list[tuple[str, str]]]) -> str:
    """Render the oracle's generated region from the scripting definition.

    Three parallel arrays per enumeration: the AppleScript enum constants
    themselves, their sdef names, and their sdef codes. The constants sit in a
    ``using terms from`` block so the compiler resolves them where the handler
    is defined, which is what removes the need for a name-to-constant mapper at
    run time.
    """
    total = sum(len(sdef_enums[name]) for name in CANDIDATE_ENUMS)
    lines = [
        "-- Generated by scripts/animation_catalog/generate.py --write from the locally",
        "-- installed PowerPoint scripting definition: "
        f"{total} candidates in {len(CANDIDATE_ENUMS)} enumerations,",
        "-- in sdef document order. Do not edit by hand. --check --require-sdef compares",
        "-- every name and every code in this region against the scripting definition,",
        "-- so a PowerPoint upgrade shows up as a failure rather than as silent drift.",
        "--",
        "-- Each enumeration gets three parallel arrays: the enum constants themselves,",
        "-- resolved at compile time inside a \"using terms from\" block so no",
        "-- name-to-constant mapper is needed at run time; their sdef names, for the",
        "-- JSONL records; and their sdef codes, for drift detection.",
        "",
    ]
    for enum_name in CANDIDATE_ENUMS:
        values = sdef_enums[enum_name]
        prefix = oracle_prefix(enum_name)
        names = [name for name, _ in values]
        codes = [code for _, code in values]
        lines.append(f"-- {enum_name}: {len(values)} candidates")
        lines.append(f"on {prefix}Constants()")
        lines.append("\tusing terms from application \"Microsoft PowerPoint\"")
        lines.append("\t\treturn " + _oracle_list(names, "\t\t\t"))
        lines.append("\tend using terms from")
        lines.append(f"end {prefix}Constants")
        lines.append("")
        for kind, items in (("Names", names), ("Codes", codes)):
            lines.append(f"on {prefix}{kind}()")
            lines.append("\treturn " + _oracle_list([f'"{item}"' for item in items], "\t\t"))
            lines.append(f"end {prefix}{kind}")
            lines.append("")
    return "\n".join(lines)


def split_oracle(script_text: str) -> tuple[str, str, str]:
    """Split the oracle into (head including the begin marker, region, tail)."""
    begin = ORACLE_BEGIN + "\n"
    start = script_text.find(begin)
    if start < 0:
        raise ValueError(f"oracle script has no {ORACLE_BEGIN!r} marker")
    end = script_text.find(ORACLE_END, start)
    if end < 0:
        raise ValueError(f"oracle script has no {ORACLE_END!r} marker")
    return script_text[: start + len(begin)], script_text[start + len(begin): end], script_text[end:]


def rewrite_oracle(script_text: str, sdef_enums: dict[str, list[tuple[str, str]]]) -> str:
    """Return the oracle with its generated region refreshed from the sdef."""
    head, _region, tail = split_oracle(script_text)
    return head + render_oracle_arrays(sdef_enums) + tail


def _oracle_items(body: str) -> list[str]:
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end < start:
        return []
    inner = body[start + 1: end].replace("\u00ac", " ")
    return [item.strip().strip('"') for item in inner.split(",") if item.strip()]


def parse_oracle_arrays(region: str) -> dict[str, dict[str, list[str]]]:
    """Read the generated arrays back out of the oracle, per enumeration."""
    by_prefix = {oracle_prefix(name): name for name in CANDIDATE_ENUMS}
    arrays: dict[str, dict[str, list[str]]] = {}
    for match in _ORACLE_HANDLER.finditer(region):
        handler, body = match.group(1), match.group(2)
        for kind in ORACLE_ARRAY_KINDS:
            suffix = kind.capitalize()
            if handler.endswith(suffix) and handler[: -len(suffix)] in by_prefix:
                arrays.setdefault(by_prefix[handler[: -len(suffix)]], {})[kind] = _oracle_items(body)
    return arrays


def oracle_findings(script_text: str,
                    sdef_enums: dict[str, list[tuple[str, str]]] | None = None) -> list[str]:
    """Check the oracle: no placeholders, right object model, sdef agreement."""
    try:
        _head, region, _tail = split_oracle(script_text)
    except ValueError as exc:
        return [str(exc)]

    findings: list[str] = []
    for token in FORBIDDEN_ORACLE_TOKENS:
        if token in script_text:
            findings.append(f"oracle script still carries the unfinished-work token {token!r}")
    for token in REQUIRED_ORACLE_TOKENS:
        if token not in script_text:
            findings.append(f"oracle script is missing the required object-model construct {token!r}")
    if ORACLE_RUN_TOKEN not in script_text:
        findings.append(f"oracle script does not gate PowerPoint behind {ORACLE_RUN_TOKEN!r}")

    arrays = parse_oracle_arrays(region)
    for enum_name, expected_count in CANDIDATE_ENUMS.items():
        group = arrays.get(enum_name)
        if not group:
            findings.append(f"oracle script has no generated arrays for {enum_name}")
            continue
        for kind in ORACLE_ARRAY_KINDS:
            values = group.get(kind)
            if values is None:
                findings.append(f"oracle script has no {enum_name} {kind} array")
            elif len(values) != expected_count:
                findings.append(
                    f"oracle script {enum_name} {kind} array has {len(values)} entries, "
                    f"expected {expected_count}"
                )
        if group.get("constants") is not None and group.get("constants") != group.get("names"):
            findings.append(
                f"oracle script {enum_name} constants and names are not one-to-one, so a record "
                "would report a name the constant did not apply"
            )

    if sdef_enums is None:
        return findings

    for enum_name in CANDIDATE_ENUMS:
        local = sdef_enums.get(enum_name)
        group = arrays.get(enum_name)
        if local is None or not group:
            continue
        names = [name for name, _ in local]
        codes = [code for _, code in local]
        for kind, expected in (("constants", names), ("names", names), ("codes", codes)):
            actual = group.get(kind) or []
            if actual == expected:
                continue
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            if missing:
                findings.append(
                    f"oracle script {enum_name} {kind} array is missing {len(missing)} sdef "
                    f"value(s), first {missing[0]!r}"
                )
            if extra:
                findings.append(
                    f"oracle script {enum_name} {kind} array carries {len(extra)} value(s) that are "
                    f"not in the local sdef, first {extra[0]!r}"
                )
            if not missing and not extra:
                findings.append(f"oracle script {enum_name} {kind} array is out of sdef order")
    if script_text != rewrite_oracle(script_text, sdef_enums):
        findings.append("oracle script candidate arrays differ from a deterministic regeneration (run --write)")
    return findings


# --- offline analysis of the package the oracle saves ----------------------
def _oracle_local(element: Any) -> str:
    tag = element.tag
    if not isinstance(tag, str):
        return ""
    return tag.rpartition("}")[2]


def _oracle_qname(element: Any) -> str:
    tag = element.tag
    if not isinstance(tag, str) or not tag.startswith("{"):
        return str(tag)
    uri, _, local = tag[1:].partition("}")
    return f"{ORACLE_PREFIXES.get(uri, uri)}:{local}"


def _oracle_attributes(element: Any) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for key in sorted(element.attrib):
        name = key
        if key.startswith("{"):
            uri, _, local = key[1:].partition("}")
            name = f"{ORACLE_PREFIXES.get(uri, uri)}:{local}"
        attributes[name] = element.attrib[key]
    return attributes


def _oracle_transition(root: Any) -> list[dict[str, Any]]:
    """Report every slide transition, with its AlternateContent branch."""
    records: list[dict[str, Any]] = []
    for element in root.iter():
        if _oracle_local(element) != "transition":
            continue
        branch: str | None = None
        requires: str | None = None
        parent = element.getparent()
        while parent is not None:
            local = _oracle_local(parent)
            if local in ("Choice", "Fallback"):
                branch, requires = local, parent.get("Requires")
                break
            parent = parent.getparent()
        records.append({
            "element": _oracle_qname(element),
            "attributes": _oracle_attributes(element),
            "alternateContentBranch": branch,
            "requires": requires,
            "effects": [
                {"element": _oracle_qname(child), "attributes": _oracle_attributes(child)}
                for child in element if isinstance(child.tag, str)
            ],
        })
    return records


def _oracle_timing(root: Any) -> list[dict[str, Any]]:
    """Report the timing facts no dictionary property exposes."""
    nodes: list[dict[str, Any]] = []
    for element in root.iter():
        local = _oracle_local(element)
        if local not in ORACLE_TIMING_ELEMENTS:
            continue
        attributes = _oracle_attributes(element)
        if local == "cTn" and not any(attr in attributes for attr in ORACLE_CTN_ATTRS):
            continue
        record: dict[str, Any] = {"element": _oracle_qname(element), "attributes": attributes}
        if local == "cTn":
            record["behaviorChildren"] = sorted({
                _oracle_qname(child) for child in element.iter()
                if _oracle_local(child) in ORACLE_BEHAVIOR_ELEMENTS
            })
        nodes.append(record)
    return nodes


def parse_oracle_package(package: Path) -> dict[str, Any]:
    """Read the oracle's saved package offline, slide part by slide part.

    This is the other half of the oracle's division of labour: the AppleScript
    side applies a candidate and reports what the dictionary can read, and this
    side recovers what it cannot - preset identifiers and subtypes, trigger node
    types, after-effect values, motion-path geometry and the extension-namespace
    transition attributes. It needs no PowerPoint and no network.
    """
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    slides: dict[str, Any] = {}
    with zipfile.ZipFile(package) as archive:
        parts: dict[int, str] = {}
        for name in archive.namelist():
            match = ORACLE_SLIDE_PART.fullmatch(name)
            if match:
                parts[int(match.group(1))] = name
        for index in sorted(parts):
            root = etree.fromstring(archive.read(parts[index]), parser=parser)
            slides[str(index)] = {
                "part": parts[index],
                "transition": _oracle_transition(root),
                "timing": _oracle_timing(root),
            }
    return {"package": package.name, "slideCount": len(slides), "slides": slides}


def read_oracle_readback(path: Path) -> list[dict[str, Any]]:
    """Read the oracle's JSONL read-back, keeping unparsable lines visible."""
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


def merge_oracle_readback(records: list[dict[str, Any]], package: dict[str, Any]) -> dict[str, Any]:
    """Join the oracle's read-back with the OOXML facts from its package."""
    slides = package.get("slides", {})
    merged: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for record in records:
        if "enum" not in record:
            continue
        facts = slides.get(str(record.get("slideIndex")), {})
        entry = {
            "key": f"{record['enum']}.{record.get('enumerator')}",
            "enum": record["enum"],
            "enumerator": record.get("enumerator"),
            "code": record.get("code"),
            "slideIndex": record.get("slideIndex"),
            "dictionaryApplied": record.get("applied"),
            "rejected": bool(record.get("rejected")),
            "resolvedBy": record.get("resolvedBy"),
            "ooxml": {"transition": facts.get("transition", []), "timing": facts.get("timing", [])},
        }
        if record.get("error"):
            entry["error"] = record["error"]
        if not entry["ooxml"]["transition"] and not entry["ooxml"]["timing"]:
            unresolved.append(entry["key"])
        merged.append(entry)
    return {
        "package": package.get("package"),
        "slideCount": package.get("slideCount"),
        "candidateRecords": len(merged),
        "unresolvedCandidates": sorted(unresolved),
        "candidates": merged,
    }


def analyse_oracle_output(out_dir: Path) -> int:
    """Analyse an oracle output directory and print the merged evidence."""
    package = out_dir / "powerpoint-oracle.pptx"
    readback = out_dir / "powerpoint-readback.jsonl"
    if not package.exists():
        print(f"FAIL: no oracle package at {package}", file=sys.stderr)
        return 1
    parsed = parse_oracle_package(package)
    records = read_oracle_readback(readback) if readback.exists() else []
    print(json.dumps(merge_oracle_readback(records, parsed), indent=2, ensure_ascii=False))
    return 0


def load_json(path: Path) -> dict[str, Any]:
    """Read a JSON object from disk."""
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the checked-in manifest, catalog and oracle")
    parser.add_argument("--write", action="store_true",
                        help="regenerate the catalog and the oracle's candidate arrays deterministically")
    parser.add_argument("--parse-oracle", type=Path, metavar="DIR",
                        help="analyse a saved oracle output directory offline and print the merged evidence")
    parser.add_argument("--sdef", type=Path, default=DEFAULT_SDEF)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--oracle", type=Path, default=DEFAULT_ORACLE)
    parser.add_argument("--require-sdef", action="store_true", help="fail when the local sdef is unavailable")
    args = parser.parse_args(argv)
    if not args.check and not args.write and args.parse_oracle is None:
        parser.error("pass --check, --write or --parse-oracle")

    if args.parse_oracle is not None:
        return analyse_oracle_output(args.parse_oracle)

    manifest = load_json(args.manifest)
    sdef_enums = read_sdef(args.sdef) if args.sdef.exists() else None
    if sdef_enums is None and args.require_sdef:
        print(f"FAIL: no scripting definition at {args.sdef}", file=sys.stderr)
        return 1
    oracle_text = args.oracle.read_text(encoding="utf-8") if args.oracle.exists() else None
    if oracle_text is None and args.require_sdef:
        print(f"FAIL: no oracle script at {args.oracle}", file=sys.stderr)
        return 1

    if args.write:
        if sdef_enums is None:
            print("FAIL: --write needs the local PowerPoint scripting definition", file=sys.stderr)
            return 1
        catalog = build_catalog(manifest, sdef_enums)
        args.catalog.parent.mkdir(parents=True, exist_ok=True)
        args.catalog.write_text(dump(catalog), encoding="utf-8")
        written = {"catalog": str(args.catalog),
                   "catalogSha256": hashlib.sha256(args.catalog.read_bytes()).hexdigest()}
        if oracle_text is not None:
            refreshed = rewrite_oracle(oracle_text, sdef_enums)
            if refreshed != oracle_text:
                args.oracle.write_text(refreshed, encoding="utf-8")
            written["oracle"] = str(args.oracle)
            written["oracleSha256"] = hashlib.sha256(args.oracle.read_bytes()).hexdigest()
            written["oracleCandidatesRegenerated"] = sum(len(sdef_enums[name]) for name in CANDIDATE_ENUMS)
        print(json.dumps({"wrote": written, **catalog["summary"]}, indent=2))
        return 0

    findings = check(manifest, load_json(args.catalog), sdef_enums, oracle_text)
    if sdef_enums is None:
        print("note: local scripting definition unavailable; skipped the sdef comparison")
    if oracle_text is None:
        print("note: oracle script unavailable; skipped the object-model and candidate-array checks")
    for finding in findings:
        print(f"FAIL: {finding}")
    if findings:
        print(f"{len(findings)} finding(s)")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
