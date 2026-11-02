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

#: The checked-in scripting-oracle capture. ``--write`` folds it into the
#: catalog, so a promoted entry is derived from evidence in the repository
#: rather than hand-edited into the JSON, and ``--check`` fails when the two
#: drift apart. ``--parse-oracle`` regenerates the merged file from the two
#: raw artefacts beside it.
DEFAULT_ORACLE_EVIDENCE = REPO_ROOT / "tests/fixtures/animations/oracle-16.113.1"
ORACLE_EVIDENCE_MERGED = "merged-evidence.json"
ORACLE_EVIDENCE_PACKAGE = "powerpoint-oracle.pptx"
ORACLE_EVIDENCE_READBACK = "powerpoint-readback.jsonl"

#: The checked-in GUI capture: every animation value the ribbon can reach,
#: applied through the accessibility driver and read back out of the package
#: PowerPoint saved. It closes a different gap from the scripting oracle's.
#: The oracle could not apply an animation at all — ``add effect`` is declared
#: in the dictionary and unimplemented in this build — and the catalog's
#: animation presets therefore came from captured native fixtures, which
#: record **which** behaviour children a tile writes but not **what they say**.
#: This capture's package records both, so the payload gap that kept 71 tiles
#: capture-required is measured here rather than inferred.
DEFAULT_GUI_CAPTURE_EVIDENCE = (
    REPO_ROOT / "tests/fixtures/animations/gui-only/batch-2026-11-01-complete"
)

#: Every checked-in gallery capture, in the order they were taken; a later one
#: wins a key the earlier also carries. There is more than one because the
#: surface grew: the 2026-11-01 batch covered the gaps the catalog knew about,
#: and reading the ``Path Animation`` popup then exposed its **Complex** group —
#: seven paths this build applies that the catalog had no key for, hidden behind
#: 65 Windows-only path enumerators it cannot.
GUI_CAPTURE_EVIDENCE_DIRS = (
    DEFAULT_GUI_CAPTURE_EVIDENCE,
    REPO_ROOT / "tests/fixtures/animations/gui-only/motion-paths-complex-2026-11-02",
)
GUI_CAPTURE_MERGED = "merged-evidence.json"
GUI_CAPTURE_PACKAGE = "powerpoint-oracle.pptx"
GUI_CAPTURE_READBACK = "powerpoint-readback.jsonl"

#: The effect-option capture: every value of every setting a gallery tile's
#: ``Effect Options`` control offers. 133 values over 6 settings on 33 of the 95
#: tiles; the other 62 offer only ``Sequence``, which is the text-unit setting
#: and already writable.
#:
#: These are **per effect**, which is the finding that shapes the catalog: Fly
#: In's ``From Right`` and Stretch's ``From Right`` are different measurements,
#: and 7 of the 37 (effect, setting) groups do not move ``presetSubtype`` at all
#: — Spin's direction is the *sign* of ``p:animRot/@by``. So an option carries
#: its own behaviours, and lives inside its effect's entry rather than in a
#: shared direction vocabulary.
DEFAULT_EFFECT_OPTIONS_EVIDENCE = (
    REPO_ROOT / "tests/fixtures/animations/gui-only/effect-options-capture-2026-11-02"
)
EFFECT_OPTIONS_MERGED = "merged-effect-options.json"
EFFECT_OPTIONS_DATE = "2026-11-02"

CATALOG_SCHEMA_VERSION = 1
BASELINE_APPLICATION = "Microsoft PowerPoint"
BASELINE_VERSION = "16.113.1"
BASELINE_PLATFORM = "macOS"
# Fixed catalog-generation timestamp (REQ-7.2): only an intentional baseline
# regeneration may change it, so regeneration stays byte-deterministic.
BASELINE_GENERATED_AT = "2026-10-30T00:00:00Z"

STATUSES = ("accepted", "rejected", "nonPersisted", "outOfScope")
CAPABILITY_LEVELS = ("nativeTemplate", "presetMapping", "semanticPreservationOnly")

#: Four-character type code of each required enumeration, from the ``code``
#: attribute of its ``<enumeration>`` element. An Apple Event enumerator is a
#: descriptor of *this* type carrying the enumerator's own four bytes, so the
#: oracle needs both halves to name a constant by code instead of by term.
#: ``--check --require-sdef`` compares every one of these against the local
#: scripting definition, so a PowerPoint upgrade that renumbers an enumeration
#: fails rather than silently probing the wrong values.
CANDIDATE_ENUM_CODES: dict[str, str] = {
    "MsoAnimEffect": "AnFX",
    "MsoAnimDirection": "AnDi",
    "MsoAnimTriggerType": "AnTr",
    "MsoAnimateByLevel": "AnLv",
    "MsoAnimTextUnitEffect": "AnTU",
    "MsoAnimAfterEffect": "AnAE",
    "MsoAnimType": "AnTy",
    "EPPEntryEffect": "pEeF",
}

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
#:
#: Twelve members, where Microsoft's VBA documentation lists 28. The difference
#: is not an omission: the missing 16 are the 15 ``msoAnimateDiagram*`` members
#: plus the read-only ``msoAnimateLevelMixed`` sentinel, and PowerPoint for Mac
#: 16.113.1 publishes none of them in its scripting definition — ``grep
#: 'diagram'`` over PowerPoint.sdef returns nothing. So this map covers the
#: whole enumeration *this platform exposes*: 5 chart levels and 7 text levels.
#:
#: SmartArt build values therefore do not arrive through this enumeration at
#: all. They are the six ``animation.smartArt.build.*`` entries, mapped from the
#: OOXML side (``p:bldDgm/@build``) instead.
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
    # "ctageory" is **not** a typo in this file. PowerPoint for Mac 16.113.1
    # ships that spelling in its own scripting definition
    # (/Applications/Microsoft PowerPoint.app/Contents/Resources/PowerPoint.sdef),
    # so it is the literal string the AppleScript interface accepts. Microsoft's
    # VBA documentation spells the Windows constant correctly
    # (msoAnimateChartByCategoryElements), which is what makes this look wrong.
    # Correcting it here would break the oracle; see the test that guards it.
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
    "MsoAnimDirection is not sdpm's input vocabulary for a direction. Directions were measured "
    "per effect and live in each gallery entry's ooxml.effectOptions, written as "
    "preset.options.direction; this enumerator is tracked only for sdef coverage. It has no "
    "presetSubtype of its own because the name does not identify one: 33 of the 45 enumerators "
    "are not offered by any gallery tile, and of the 36 direction labels the tiles do offer, 24 "
    "have no MsoAnimDirection name. The same label also means different subtypes on different "
    "effects, so a name-to-subtype table cannot exist."
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
        # No ``variant``. It named one of the 45 ``MsoAnimDirection``
        # enumerators, and the effect-option capture showed that vocabulary does
        # not describe the galleries: 33 of the 45 are not reachable from any
        # tile, and 24 of the 36 labels the tiles do offer have no name in it.
        # A setting is now written as ``preset.options``, which names the
        # setting too and is validated against the effect's own measured values
        # in ``ooxml.effectOptions``.
        "preset": {"category": "entrance", "effect": "fade"},
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
#:
#: The last seven are the popup's **Complex** group, and they were missing
#: entirely until the platform inventory read the popup: the catalog tracked 65
#: Windows-only path enumerators that this build cannot apply, and behind that
#: noise nobody noticed seven paths it can. ``discover_platform_inventory.py``
#: records the full list, so a group added to the popup shows up as a label with
#: no key rather than staying invisible.
MOTION_PATH_GROUPS = (
    # Custom — drawn on the canvas, so deferred rather than captured.
    "custom",
    # Basic — measured on 2026-11-01.
    "lines",
    "arcs",
    "turns",
    "shapes",
    "loops",
    # Complex — applicable here, never captured.
    "bounce",
    "invertedShape",
    "specialCurve",
    "specialShape",
    "spiral",
    "star",
    "waves",
)

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


def read_sdef_enum_codes(path: Path) -> dict[str, str]:
    """Read the four-character type code of each required enumeration.

    An enumerator's own code is only half of its Apple Event descriptor: the
    other half is the type code of the enumeration it belongs to, which is what
    the oracle needs to name a constant without using its ambiguous term.
    """
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.parse(str(path), parser=parser).getroot()
    return {
        enumeration.get("name") or "": enumeration.get("code") or ""
        for enumeration in root.iter("enumeration")
        if enumeration.get("name") in CANDIDATE_ENUMS
    }


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


def tile_duration_ms(row: tuple[Any, ...]) -> int | None:
    """Return the ``timing.durationMs`` one gallery tile's semantic JSON should claim.

    ``observedChildDurationMs`` carries two different kinds of ``None``, and
    they must not be collapsed:

    * The tile's **only** behaviour child is the normative visibility
      ``p:set``. There is nothing to give a duration to — PowerPoint persists
      Appear and Disappear as a discrete toggle — so the effect really is
      instantaneous and the semantic JSON must not claim a duration. Saying
      500 ms here makes the entry contradict its own capture, and the writer
      then emits XML the reader cannot read back as what was written.
    * The tile animates something (``p:anim``, ``p:animEffect``, …) but the
      available capture did not record a child duration. ``None`` means
      *unknown*, not instantaneous, so the carrier default stands as the
      authoring example and the entry stays capture-required.
    """
    _category, _slug, _label, _preset_class, _preset_id, _subtype, _group, children, _filt, duration, _fixture = row
    if duration is not None:
        return duration
    return None if tuple(children) == ("set",) else BASE_TIMING["durationMs"]


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
            effect_semantic(
                preset={"category": "entrance" if category == "text" else category,
                        "effect": slug},
                timing={"durationMs": tile_duration_ms(row)},
            ),
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
            effect_semantic(preset={"category": "media", "effect": slug}),
            native_evidence("native-media-background-timing", "") if preset_id else
            {"source": "ECMA-376 presetClass mediacall", "commit": None},
        ))

    for group in MOTION_PATH_GROUPS:
        if group == "custom":
            # Custom is not one path. It is the popup's four Draw tools, whose
            # geometry the user draws on the canvas, so there is no fixed value
            # for a capture to record — capturing one drawing would catalog
            # that drawing, not the tile. The drawn path is authorable and does
            # persist, through a `motion` behaviour whose `path` sdpm writes
            # verbatim; it just does not belong to this preset key.
            items.append(_unaccepted(
                f"animation.gallery.motionPath.{group}", "nonPersisted",
                "the Custom group is a selection surface for the four Draw tools, whose geometry is drawn "
                "rather than preset; a drawn path persists through a motion behaviour carrying it as "
                "p:animMotion/@path, so no fixed geometry belongs to this key",
            ))
            continue
        items.append(_accepted(
            f"animation.gallery.motionPath.{group}", SEMANTIC,
            {"strategy": "animMotion", "element": "p:animMotion", "pathAttribute": "p:animMotion/@path",
             "requiresCapture": True,
             "gap": "PowerPoint carries preset motion paths as literal SVG path data in p:animMotion/@path; "
                    "that geometry is not present in the available evidence, so the writer must emit a "
                    "custom path or defer until Task 8 captures it"},
            effect_semantic(preset={"category": "motionPath", "effect": group}),
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
        if node_type is None:
            # Exactly parallel to ``animation.behavior.none``: the enumerator
            # reports an absence, not a value. There is no start condition in
            # the package to measure, so filing it as awaiting a capture asks
            # PowerPoint to produce the bytes of a thing that has none. An
            # effect with no start condition also never plays, so there is
            # nothing for sdpm to author either.
            items.append(_unaccepted(
                f"animation.start.{semantic}", "nonPersisted",
                "msoAnimTriggerNone reports an effect with no trigger; its persisted form is the absence of "
                "a start condition, so PowerPoint writes no p:cond and sdpm has no value to author",
            ))
            continue
        items.append(_accepted(
            f"animation.start.{semantic}", level,
            {"strategy": "timingNode", "nodeType": node_type},
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
            # The example asks for the enumerator by name through the new
            # vocabulary, so the writer refuses it and quotes this entry's own
            # gap. Without that the example would write a plain Fly In — the
            # tile's default direction — and the entry would report itself
            # generated while demonstrating nothing it describes.
            # The example asks for the enumerator by name through the new
            # vocabulary, so the writer refuses it and quotes this entry's own
            # gap. Without that the example would write a plain Fly In — the
            # tile's default direction — and the entry would report itself
            # generated while demonstrating nothing it describes.
            effect_semantic(preset={"category": "entrance", "effect": "flyIn",
                                    "options": {"direction": semantic}}),
            {"source": SDEF_SOURCE, "commit": None},
            noSdpmInput=True,
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
                 # No capture records a default duration for a standard element
                 # that has no gallery tile, so the entry says so instead of
                 # letting its semantic JSON's carrier value read as measured.
                 "defaultDurationMs": None,
                 "durationEvidence": (
                     "not captured: this value has no Transitions-gallery tile, so PowerPoint's own default "
                     "duration for it is unknown. The semantic JSON carries sdpm's carrier default as an "
                     "authoring example, not as a measurement."
                 ),
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
                preset={"category": "entrance", "effect": tile[1] if tile else camel(enumerator.replace("animation type", ""))}), evidence, **extra)

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
            ooxml["presetClass"] = [tile_row[3]]
        # The category comes from the matched tile, never from the assumption
        # that an MsoAnimEffect ordinal in this band names an entrance effect.
        # Seven of the nine matches happen to be entrance effects and the
        # hardcoded value was right by luck; `shimmer` is **emphasis** and
        # `stretchy` is **exit**, so for those two the example asked the writer
        # for an entrance effect that does not exist, it was refused, and the
        # entry was counted as awaiting a PowerPoint read-back. Nothing needed
        # measuring: both tiles were already measured, under the gallery this
        # entry's own `guiKey` names.
        preset = (
            {"category": match[0], "effect": match[1]} if match
            else {"category": "entrance", "effect": camel(enumerator.replace("animation type", ""))}
        )
        evidence = (
            native_evidence(ANIMATION_BY_KEY[match][10], f"animations/{match[0]}") if match
            else {"source": SDEF_SOURCE, "commit": None}
        )
        return _accepted(
            key, SEMANTIC, ooxml,
            effect_semantic(preset=preset),
            evidence,
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
                                    "effect": tile[1] if tile else camel(enumerator.replace("animation type", ""))}),
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
            effect_semantic(preset={"category": "media", "effect": slug}),
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
        effect_semantic(preset={"category": "motionPath", "effect": slug}),
        {"source": SDEF_SOURCE, "commit": None},
        guiKey="animation.moreEffects.motionPath",
    )


# ---------------------------------------------------------------------------
# Captured scripting-oracle evidence
# ---------------------------------------------------------------------------
#: What the capture under :data:`DEFAULT_ORACLE_EVIDENCE` is, and what it is
#: not. Every statement here is a property of the checked-in artefacts.
ORACLE_CAPTURE_DATE = "2026-10-31"
ORACLE_CAPTURE_DRIVER = "AppleScript scripting dictionary; no Visual Basic"
#: ``verification`` value of an entry promoted from the capture. It names the
#: artefact instead of asking for a read-back that has now happened.
ORACLE_VERIFICATION = "scriptingOracleCapture"
#: ``evidence.source`` of a promoted entry.
ORACLE_SOURCE = "sdpm scripting oracle capture"

#: Element prefix -> (strategy, requires, namespace). A promoted entry takes
#: its namespace facts from the element PowerPoint actually wrote, which is how
#: ``entry effect wheel reverse 1 spoke`` moves from the standard ``p:wheel``
#: the catalog guessed to the ``p14:wheelReverse`` PowerPoint writes.
ORACLE_ELEMENT_STRATEGY = {
    "p": ("standard", None, P_NS),
    "p14": ("p14", "p14", P14_NS),
    "p15": ("p15", "p15", P15_NS),
    "p159": ("p159", "p159", P159_NS),
}


def oracle_provenance(evidence: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Describe the capture, including the two things it does not establish."""
    probed = sorted({str(record.get("enum")) for record in evidence.values()})
    durations = sorted({
        str((oracle_transition_form(record) or {}).get("transitionAttributes", {}).get("p14:dur"))
        for record in evidence.values()
        if oracle_transition_form(record) is not None
    })
    return {
        "fixture": DEFAULT_ORACLE_EVIDENCE.relative_to(REPO_ROOT).as_posix(),
        "package": ORACLE_EVIDENCE_PACKAGE,
        "readBack": ORACLE_EVIDENCE_READBACK,
        "merged": ORACLE_EVIDENCE_MERGED,
        "application": BASELINE_APPLICATION,
        "version": BASELINE_VERSION,
        "platform": BASELINE_PLATFORM,
        "capturedAt": ORACLE_CAPTURE_DATE,
        "driver": ORACLE_CAPTURE_DRIVER,
        "candidateRecords": len(evidence),
        "probedEnumerations": probed,
        "unprobedEnumerations": [name for name in CANDIDATE_ENUMS if name not in probed],
        "unprobedReason": (
            "the run aborted in msoAnimDirectionConstants before these probes, so this capture says "
            "nothing about them; their entries carry no capture block"
        ),
        "animationHalf": (
            "every MsoAnimEffect candidate was refused with \u201cmain sequence of timeline of slide N of "
            "presentation \u201cPresentation1\u201d doesn\u2019t understand the \u201cadd effect\u201d message\u201d, and no slide in "
            "the package carries p:timing. add effect is declared in PowerPoint.sdef but PowerPoint for Mac "
            "16.113.1 does not implement it on main sequence, so no animation value can be captured through "
            "the dictionary at all; the GUI procedure in scripts/animation_catalog/computer-use.md is the "
            "only animation-side route"
        ),
        "legacyShapeEntryEffects": (
            "the refused EPPEntryEffect candidates are the 0x00f60d** per-shape entry-effect band plus the "
            "'unset' sentinel. A refusal there confirms the catalog's outOfScope classification rather than "
            "recording a gap"
        ),
        "transitionDurationObserved": durations,
        "transitionDurationEvidence": (
            "every captured transition carries the same spd and p14:dur, because the probe set the slide's "
            "entry effect and nothing else: the value is the transition duration the script-created probe "
            "slide already held, not the effect's own default. One effect default is known from two other "
            "measurements that disagree with it - the Box tile's native capture and the Transitions ribbon "
            "both read 1600 ms - so defaultDurationMs keeps its native-capture value and this capture is "
            "recorded as the probe-context duration only"
        ),
    }


def load_oracle_evidence(directory: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return the merged scripting-oracle evidence keyed by candidate key.

    The merged file is the join of the oracle's JSONL read-back and the OOXML
    extracted from its saved package, produced by ``--parse-oracle``. Reading
    the checked-in join - rather than re-deriving it from the package - keeps
    ``--write`` free of a zip parse while leaving the merge itself reproducible
    from the two artefacts beside it.
    """
    directory = directory or DEFAULT_ORACLE_EVIDENCE
    path = directory / ORACLE_EVIDENCE_MERGED
    document = json.loads(path.read_text(encoding="utf-8"))
    records: dict[str, dict[str, Any]] = {}
    for record in document.get("candidates", []):
        key = record.get("key")
        if isinstance(key, str):
            records[key] = record
    return records


def oracle_transition_form(record: dict[str, Any]) -> dict[str, Any] | None:
    """Return the transition form PowerPoint wrote for one probed candidate.

    ``None`` means the slide carries no ``p:transition`` at all, which is
    itself evidence: the candidate was either refused or applied without
    persisting anything.
    """
    branches = (record.get("ooxml") or {}).get("transition") or []
    choice = next((b for b in branches if b.get("alternateContentBranch") == "Choice"), None)
    plain = next((b for b in branches if b.get("alternateContentBranch") is None), None)
    fallback = next((b for b in branches if b.get("alternateContentBranch") == "Fallback"), None)
    primary = choice or plain
    if primary is None or not primary.get("effects"):
        return None
    effect = primary["effects"][0]
    form: dict[str, Any] = {
        "element": effect["element"],
        "attributes": dict(effect.get("attributes") or {}),
        # The attributes of p:transition itself, not of the effect child.
        "transitionAttributes": dict(primary.get("attributes") or {}),
        "alternateContentBranch": primary.get("alternateContentBranch"),
        "choiceRequires": primary.get("requires"),
        "fallbackElement": None,
    }
    if fallback is not None and fallback.get("effects"):
        form["fallbackElement"] = fallback["effects"][0]["element"]
    return form


def oracle_capture_block(record: dict[str, Any], form: dict[str, Any] | None) -> dict[str, Any]:
    """Return the per-entry provenance block for one probed candidate."""
    block: dict[str, Any] = {
        "source": ORACLE_SOURCE,
        "application": BASELINE_APPLICATION,
        "version": BASELINE_VERSION,
        "capturedAt": ORACLE_CAPTURE_DATE,
        "driver": ORACLE_CAPTURE_DRIVER,
        "fixture": f"{DEFAULT_ORACLE_EVIDENCE.relative_to(REPO_ROOT).as_posix()}/{ORACLE_EVIDENCE_PACKAGE}",
        "readBack": f"{DEFAULT_ORACLE_EVIDENCE.relative_to(REPO_ROOT).as_posix()}/{ORACLE_EVIDENCE_READBACK}",
        "slideIndex": record.get("slideIndex"),
        "requested": record.get("enumerator"),
        "dictionaryApplied": record.get("dictionaryApplied"),
    }
    if record.get("rejected"):
        block["outcome"] = "rejectedByPowerPoint"
        block["error"] = record.get("error")
        block["classification"] = (
            "the dictionary does not implement add effect on main sequence in this build, so no animation "
            "value could be applied at all; this says nothing about the value's OOXML mapping"
            if record.get("enum") == "MsoAnimEffect" else
            "PowerPoint refused to set this entry effect"
        )
    elif form is None:
        block["outcome"] = "appliedWithoutPersistedForm"
    else:
        block["outcome"] = "transitionWritten"
        block["element"] = form["element"]
        block["attributes"] = form["attributes"]
        block["transitionAttributes"] = form["transitionAttributes"]
        block["alternateContentBranch"] = form["alternateContentBranch"]
        block["choiceRequires"] = form["choiceRequires"]
        block["fallbackElement"] = form["fallbackElement"]
    if record.get("dictionaryApplied") not in (None, record.get("enumerator")):
        block["coercedByPowerPoint"] = (
            f"PowerPoint reported {record['dictionaryApplied']!r} after being asked for "
            f"{record.get('enumerator')!r}, so the written form belongs to the value it substituted"
        )
    return block


def oracle_measured_forms(evidence: dict[str, dict[str, Any]]) -> dict[str, set[frozenset[tuple[str, str]]]]:
    """Return, per element, every attribute set the capture measured for it.

    Used to tell a restatement from a contradiction. ``entry effect vortex
    left`` was written as a bare ``<p14:vortex/>``, and no other vortex value
    was written as ``dir="l"``, so the catalog's explicit ``dir="l"`` is a
    restatement of whatever default PowerPoint left out. ``entry effect
    airplane right`` was written without ``invX``, and ``airplane left`` *was*
    written with ``invX="1"`` - so keeping the catalog's ``invX="1"`` on the
    right-hand value would give two values one form, which the capture denies.
    """
    forms: dict[str, set[frozenset[tuple[str, str]]]] = {}
    for record in evidence.values():
        form = oracle_transition_form(record)
        if form is None:
            continue
        forms.setdefault(form["element"], set()).add(frozenset(form["attributes"].items()))
    return forms


def oracle_attribute_merge(catalogued: dict[str, str], captured: dict[str, str],
                           measured: set[frozenset[tuple[str, str]]]) -> tuple[dict[str, str], dict[str, Any]]:
    """Resolve one element's attribute set against the capture, attribute by attribute.

    Two different things can be true of the same element at once, so the
    comparison is per attribute rather than per set:

    * An attribute the capture **wrote** is measured, and its value replaces
      whatever the catalog had inferred from the enumerator's name. This is
      where the capture corrects the catalog - ``entry effect cube right`` is
      ``dir="u"``, not the ``dir="r"`` its name suggests.
    * An attribute the catalog states and the capture **left out** stays. An
      omitted attribute is at its schema default, so the explicit form is the
      same document, and it is the only thing that still distinguishes this
      variant in the semantic JSON and in the writer's parameter lookup.
      ``entry effect glitter diamond left`` is written ``<p14:glitter
      dir="r"/>``: ``pattern`` is left out because diamond is the default, and
      dropping the catalog's ``pattern="diamond"`` would make the entry
      indistinguishable from the hexagon tile on the way back in.

    A retained attribute is given up when keeping it would reproduce a form the
    capture measured for a *different* value: ``entry effect airplane right``
    was written without ``invX``, and ``airplane left`` was written *with*
    ``invX="1"``, so ``invX="1"`` is that value's form and cannot also be this
    one's omitted default.
    """
    retained = {name: value for name, value in catalogued.items() if name not in captured}
    corrected = {name: value for name, value in captured.items() if catalogued.get(name) != value}
    merged = {**retained, **captured}
    report: dict[str, Any] = {}
    if retained and frozenset(merged.items()) in measured:
        report["attributeConflict"] = (
            f"keeping {', '.join(sorted(retained))} would reproduce the form the capture measured for a "
            "different value of this element, so the capture's own attribute set is used instead"
        )
        retained, merged = {}, dict(captured)
    if corrected and retained:
        relation = "correctsValuesAndKeepsOmittedDefaults"
    elif corrected:
        relation = "correctsValues"
    elif retained:
        relation = "keepsOmittedDefaults"
    else:
        relation = "agrees"
    report["attributeRelation"] = relation
    if corrected:
        report["correctedAttributes"] = {
            name: {"catalogued": catalogued.get(name), "captured": value} for name, value in corrected.items()
        }
    if retained:
        report["keptAttributes"] = retained
        report["keptAttributesNote"] = (
            f"PowerPoint wrote no {', '.join(sorted(retained))} on this element. An omitted attribute sits at "
            "its schema default, so the explicit form the catalog keeps is the same document; that these "
            "particular values are the defaults is not itself measured here."
        )
    return merged, report


def promote_oracle_capture(entry: dict[str, Any], record: dict[str, Any],
                           measured: dict[str, set[frozenset[tuple[str, str]]]] | None = None) -> dict[str, Any]:
    """Fold one captured candidate's evidence into its catalog entry.

    An accepted transition candidate that PowerPoint wrote a ``p:transition``
    for is promoted: the element and its attributes become the measured ones,
    the capture-required gap goes away, and the capability level, verification
    and evidence name the artefact the values came from. Everything else -
    a rejection, a value applied without a persisted form, a candidate whose
    entry is not an accepted transition mapping - only gains the ``capture``
    block, because the capture says nothing that would change its mapping.

    Attributes are resolved one at a time by
    :func:`oracle_attribute_merge`, which is where a measured value replaces an
    inferred one and where an attribute PowerPoint left out keeps its explicit
    catalogued form.
    """
    form = oracle_transition_form(record)
    entry["capture"] = oracle_capture_block(record, form)
    ooxml = entry.get("ooxml")
    if record.get("rejected") and record.get("enum") == "EPPEntryEffect" and entry.get("status") == "accepted":
        # A transition value the catalog accepts that PowerPoint would not set.
        # The refusal is evidence about the enumerator, not about the element,
        # so the mapping stands and the contradiction is recorded rather than
        # resolved either way.
        entry["capture"]["contradictsAcceptedMapping"] = (
            f"the catalog accepts a <{ooxml.get('element')}> mapping for this value, but PowerPoint refused "
            "to set the enumerator at all, so the mapping cannot be confirmed through the dictionary; the "
            "GUI procedure in scripts/animation_catalog/computer-use.md is the remaining route"
        )
    if form is None or not isinstance(ooxml, dict) or entry.get("status") != "accepted":
        return entry
    if "element" not in ooxml:
        return entry

    prefix = form["element"].partition(":")[0]
    strategy, requires, namespace = ORACLE_ELEMENT_STRATEGY[prefix]
    catalogued = dict(ooxml.get("attributes") or {})
    if ooxml.get("element") != form["element"]:
        # A different element has a different attribute list, so nothing the
        # catalog carried can be restated on it.
        unexpressible = {
            name: value for name, value in catalogued.items() if name not in form["attributes"]
        }
        if unexpressible:
            # The element PowerPoint writes has no attribute for part of what
            # selects this value: a reversed Clock is ``p14:wheelReverse``,
            # where "reverse" is the element *name*. So selecting and writing
            # are two different attribute sets, and conflating them leaves only
            # bad options — emit an attribute the element does not have, or
            # collapse the value onto the plain Clock tile, which writes a
            # different element.
            #
            # They are therefore recorded separately. ``selectorAttributes`` is
            # the parameter set the semantic JSON selects this entry with, and
            # ``attributes`` is what goes on the element. The writer matches on
            # the first and emits the second, so the measured form is reachable
            # from a parameter set after all.
            entry["capture"]["attributeRelation"] = "selectsByParameterWritesElement"
            entry["capture"]["elementCarriesAsName"] = sorted(unexpressible)
            entry["capture"]["supersededElement"] = ooxml.get("element")
            entry["capture"]["supersededAttributes"] = dict(catalogued)
            ooxml.pop("requiresCapture", None)
            ooxml.pop("gap", None)
            ooxml["selectorAttributes"] = dict(catalogued)
            ooxml["selectorNote"] = (
                f"<{form['element']}> carries {', '.join(sorted(unexpressible))} in its element name rather "
                f"than as an attribute, so the parameter set that selects this value is not the attribute "
                f"set written onto the element. selectorAttributes is the former, attributes the latter."
            )
            ooxml["element"] = form["element"]
            ooxml["alternateContent"] = requires is not None or form["fallbackElement"] is not None
            ooxml["fallbackElement"] = form["fallbackElement"]
            ooxml["attributes"] = dict(form["attributes"])
            ooxml["strategy"] = strategy
            if namespace:
                ooxml["namespace"] = namespace
            if requires is not None:
                ooxml["requires"] = requires
            entry["capabilityLevel"] = NATIVE
            entry["verification"] = ORACLE_VERIFICATION
            entry["evidence"] = {
                "source": ORACLE_SOURCE,
                "commit": None,
                "fixture": entry["capture"]["fixture"],
                "capturedApplicationVersion": BASELINE_VERSION,
                "slideIndex": record.get("slideIndex"),
            }
            # The example keeps the **selector** parameters. Deriving them from
            # the written attributes, as the ordinary promotion does, would drop
            # `reverse` and leave the example selecting the plain Clock tile.
            semantic = entry.get("semanticJson", {}).get("transition")
            if isinstance(semantic, dict):
                semantic["parameters"] = semantic_parameters(
                    str(semantic.get("effect")), dict(ooxml["selectorAttributes"])
                )
            return entry
        attributes = dict(form["attributes"])
        entry["capture"]["attributeRelation"] = "replacesElementAndAttributes"
        entry["capture"]["supersededElement"] = ooxml.get("element")
        entry["capture"]["supersededAttributes"] = catalogued
        ooxml["element"] = form["element"]
        ooxml["alternateContent"] = requires is not None or form["fallbackElement"] is not None
        ooxml["fallbackElement"] = form["fallbackElement"]
    else:
        attributes, report = oracle_attribute_merge(
            catalogued, form["attributes"], (measured or {}).get(form["element"], set())
        )
        entry["capture"].update(report)
    ooxml["attributes"] = attributes
    ooxml["strategy"] = strategy
    ooxml["requires"] = requires
    ooxml["namespace"] = namespace
    if strategy == "standard":
        domain = STANDARD_DIR_DOMAIN.get(form["element"])
        if domain is None:
            ooxml.pop("attributeDomain", None)
        else:
            ooxml["attributeDomain"] = domain
    else:
        ooxml.pop("attributeDomain", None)
    ooxml.pop("requiresCapture", None)
    ooxml.pop("gap", None)

    entry["capabilityLevel"] = NATIVE
    entry["verification"] = ORACLE_VERIFICATION
    entry["evidence"] = {
        "source": ORACLE_SOURCE,
        "commit": None,
        "fixture": entry["capture"]["fixture"],
        "capturedApplicationVersion": BASELINE_VERSION,
        "slideIndex": record.get("slideIndex"),
    }
    semantic = entry.get("semanticJson", {}).get("transition")
    if isinstance(semantic, dict):
        slug = semantic.get("effect")
        semantic["parameters"] = semantic_parameters(str(slug), dict(ooxml["attributes"]))
    return entry


def load_gui_capture_evidence(directory: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return the checked-in GUI capture, keyed by catalog key.

    Reads the merged join rather than re-deriving it from the package, for the
    same reason the scripting oracle's loader does: ``--write`` stays free of a
    zip parse while the merge itself stays reproducible from the two artefacts
    beside it with ``--parse-gui-capture``.
    """
    directories = [directory] if directory is not None else list(GUI_CAPTURE_EVIDENCE_DIRS)
    records: dict[str, dict[str, Any]] = {}
    for folder in directories:
        path = folder / GUI_CAPTURE_MERGED
        if not path.exists():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        for record in document.get("captures", []):
            key = record.get("catalogKey")
            if isinstance(key, str) and "effect" in record:
                # A later batch wins: a key captured again was captured again
                # for a reason, and the newest reading is the one to trust.
                records[key] = {**record, "capturedIn": folder.name}
    return records


def ribbon_duration_ms(value: Any) -> int | None:
    """Return the ribbon's ``Duration`` read-back in milliseconds, or None.

    The field reads ``00.50`` for half a second and **``Auto``** for an effect
    with no finite duration — measured on Bold Reveal and Transparency, whose
    behaviours carry ``dur="indefinite"``. ``None`` means "this effect has no
    numeric duration", which is why it cannot be scaled, and it must not be
    confused with zero.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return int(round(float(value) * 1000))
    except ValueError:
        return None


def measured_behavior(behavior: dict[str, Any]) -> dict[str, Any]:
    """Normalise one measured behaviour into the form the writer emits from.

    ``dur`` and ``delay`` are lifted out of the timing attributes as integers,
    because they are the two the duration rule scales and the writer has to do
    arithmetic on them. Everything else is kept verbatim as strings: the
    measured values are what makes the output byte-exact, and re-deriving any of
    them would be the inference this capture exists to remove.

    A ``dur`` of ``indefinite`` stays a string under ``attributes``. It is not a
    number and PowerPoint does not scale it.
    """
    timing = dict(behavior.get("timing") or {})
    duration = timing.pop("dur", None)
    delay = timing.pop("delay", None)
    measured: dict[str, Any] = {
        "element": behavior["element"],
        "attributes": dict(behavior.get("attributes") or {}),
        "attrNames": list(behavior.get("attrNames") or []),
    }
    if duration is not None:
        try:
            measured["durMs"] = int(duration)
        except ValueError:
            timing["dur"] = duration
    if delay is not None:
        measured["delayMs"] = int(delay)
    if timing:
        measured["timingAttributes"] = timing
    if behavior.get("carrier"):
        measured["carrier"] = dict(behavior["carrier"])
    if behavior.get("values"):
        measured["values"] = behavior["values"]
    return measured


def gui_capture_block(record: dict[str, Any]) -> dict[str, Any]:
    """Return the per-entry provenance block for one GUI-captured value.

    The batch comes from the record, not from a constant. There is more than one
    checked-in capture now, and a block naming the wrong one would point a
    reader at a package that does not contain the entry — provenance that is
    worse than none, because it looks checkable and is not.
    """
    folder = record.get("capturedIn") or DEFAULT_GUI_CAPTURE_EVIDENCE.name
    batch = next(
        (d for d in GUI_CAPTURE_EVIDENCE_DIRS if d.name == folder),
        DEFAULT_GUI_CAPTURE_EVIDENCE,
    )
    fixture = batch.relative_to(REPO_ROOT).as_posix()
    return {
        "source": GUI_CAPTURE_SOURCE,
        "application": BASELINE_APPLICATION,
        "version": BASELINE_VERSION,
        "capturedAt": GUI_CAPTURE_DATE if batch is DEFAULT_GUI_CAPTURE_EVIDENCE else None,
        "capturedIn": folder,
        "driver": GUI_CAPTURE_DRIVER,
        "fixture": f"{fixture}/{GUI_CAPTURE_PACKAGE}",
        "readBack": f"{fixture}/{GUI_CAPTURE_READBACK}",
        "merged": f"{fixture}/{GUI_CAPTURE_MERGED}",
        "guiPath": list(record.get("guiPath") or []),
        "matchedTitle": record.get("matchedTitle"),
        "slideIndex": record.get("slideIndex"),
        "shapeName": record.get("shapeName"),
        "shapeSpid": record.get("shapeSpid"),
        "attributedSpid": record.get("attributedSpid"),
        "selectionRowIndex": record.get("selectionRowIndex"),
        "selectedBy": record.get("selectedBy"),
        "ribbonReadBack": record.get("ribbonReadBack"),
    }


def promote_gui_capture(entry: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Fold one GUI-captured animation effect into its catalog entry.

    What this closes is the **payload** gap, not the identifier one. The native
    fixtures already gave 71 of these entries a ``presetId`` — read correctly,
    every one of the 71 agrees with what the ribbon wrote — and recorded *which*
    behaviour children a tile writes. What they did not record is what those
    children say, so the entries stayed ``requiresCapture`` and the writer
    refused them. This capture measures the payloads, so the refusal is lifted
    for the entries it covers and for no others.

    Three things are written:

    * ``ooxml.behaviors`` — the measured behaviours **in document order, with
      duplicates**. 57 of the 76 effects repeat an element (entrance Bounce has
      eight ``p:animScale``), so a set keyed by element name cannot express
      them and the writer emits from this list instead of from
      ``behaviorChildren``. ``behaviorChildren`` is kept as the distinct names
      so the reader's existing cross-check still works against it.
    * ``ooxml.measuredDurationMs`` — the duration the measured timings belong
      to, read off the ribbon. ``null`` for an effect the field reports as
      ``Auto``; those carry ``dur="indefinite"`` and cannot be scaled at all.
    * ``ooxml.durationScaling`` — the measured rule for writing the effect at
      another duration, including its one-millisecond limit. Stated per entry
      rather than only in the provenance, because it is the entry's own
      accuracy claim.

    A measured ``presetId`` that disagrees with the catalogued one **replaces**
    it and the difference is recorded, exactly as the transition capture does.
    """
    effect = record.get("effect") or {}
    attributes = dict(effect.get("attributes") or {})
    ooxml = entry.get("ooxml")
    entry["capture"] = gui_capture_block(record)
    if not isinstance(ooxml, dict) or entry.get("status") != "accepted":
        return entry

    measured_class = attributes.get("presetClass")
    measured_id = int(attributes["presetID"]) if attributes.get("presetID") else None
    measured_subtype = int(attributes.get("presetSubtype") or 0)
    catalogued = (ooxml.get("presetClass"), ooxml.get("presetId"), ooxml.get("presetSubtype"))
    if catalogued[1] is None:
        entry["capture"]["identifierRelation"] = "measuredWhereNoneWasRecorded"
    elif catalogued == (measured_class, measured_id, measured_subtype):
        entry["capture"]["identifierRelation"] = "confirmsCatalogued"
    else:
        entry["capture"]["identifierRelation"] = "replacesCatalogued"
        entry["capture"]["supersededIdentifier"] = {
            "presetClass": catalogued[0], "presetId": catalogued[1], "presetSubtype": catalogued[2],
        }

    behaviors = [measured_behavior(behavior) for behavior in effect.get("behaviors") or []]
    duration_ms = ribbon_duration_ms((record.get("ribbonReadBack") or {}).get("duration"))
    ooxml["strategy"] = "preset"
    ooxml["element"] = "p:cTn"
    ooxml["presetClass"] = measured_class
    ooxml["presetId"] = measured_id
    ooxml["presetSubtype"] = measured_subtype
    ooxml["nodeType"] = attributes.get("nodeType")
    ooxml["effectAttributes"] = {
        name: value for name, value in attributes.items()
        if name not in ("presetClass", "presetID", "presetSubtype")
    }
    if effect.get("iterate"):
        ooxml["iterate"] = effect["iterate"]
    ooxml["behaviors"] = behaviors
    ooxml["behaviorChildren"] = sorted({behavior["element"] for behavior in behaviors})
    ooxml["measuredDurationMs"] = duration_ms
    ooxml["durationScaling"] = GUI_DURATION_SCALING if duration_ms is not None else GUI_DURATION_FIXED
    ooxml.pop("unresolvedPayloads", None)
    ooxml.pop("requiresCapture", None)
    ooxml.pop("gap", None)
    ooxml.pop("pathAttribute", None)
    # Replaced by measuredDurationMs, which is the duration the measured timings
    # belong to rather than one child's observed duration. Leaving it would also
    # misfire: the writer falls back to it when the JSON names no duration, and
    # for the two effects whose duration is 'Auto' that fallback would request a
    # duration the effect cannot have.
    ooxml.pop("observedChildDurationMs", None)
    # The entry's own authoring example now asks for exactly what was measured,
    # so following the catalog produces the measured bytes. ``None`` for an
    # effect with no numeric duration, which is a statement rather than an
    # omission: its behaviours are 'indefinite'.
    effects = ((entry.get("semanticJson") or {}).get("animations") or {}).get("mainSequence") or []
    if effects and isinstance(effects[0], dict) and isinstance(effects[0].get("timing"), dict):
        effects[0]["timing"]["durationMs"] = duration_ms

    entry["capabilityLevel"] = NATIVE
    entry["verification"] = GUI_CAPTURE_VERIFICATION
    entry["evidence"] = {
        "source": GUI_CAPTURE_SOURCE,
        "commit": None,
        "fixture": entry["capture"]["fixture"],
        "capturedApplicationVersion": BASELINE_VERSION,
        "slideIndex": record.get("slideIndex"),
    }
    return entry


def promote_gui_captures(items: list[dict[str, Any]],
                         evidence: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold every GUI capture into the item it names. Unmatched keys are an error.

    A capture whose key no entry carries is a refusal rather than a shrug: the
    key is how the measurement reaches the catalog, so a typo or a renamed entry
    would otherwise silently leave the measurement out and the entry
    capture-required with nobody the wiser.
    """
    by_key = {entry["key"]: entry for entry in items}
    missing = sorted(key for key in evidence if key not in by_key)
    if missing:
        raise SystemExit(
            f"FAIL: the GUI capture names {len(missing)} key(s) no catalog item carries: {missing}"
        )
    for key, record in evidence.items():
        promote_gui_capture(by_key[key], record)
    return items


def option_slug(label: str) -> str:
    """Return the JSON name for a GUI label.

    Mirrors ``effect_options_plan.slugify`` exactly, because the plan's target
    keys and the catalog's option names have to agree for the evidence to reach
    the entry: ``From Bottom-Left`` is ``fromBottomLeft``, ``4 Spokes`` is
    ``spokes4`` (a name cannot start with a digit), ``25%`` is ``percent25``.
    """
    words = [word for word in label.replace("-", " ").replace("%", " percent").split() if word]
    if words and words[0][0].isdigit():
        words = words[1:] + [words[0]]
    head, *rest = words or [label]
    return head.lower() + "".join(word[:1].upper() + word[1:].lower() for word in rest)


def load_effect_options_evidence(
    directory: Path | None = None,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Return ``effectKey -> setting -> [measured value]`` from the merged capture.

    The merge is produced by ``effect_options_merge.py``, which refuses to
    publish a set where two values of one setting carry the same OOXML — that
    is how three values which had silently recorded their effect's **default**
    were found. Reading its output rather than the raw captures means the
    catalog cannot be built from an unverified reading.
    """
    directory = directory or DEFAULT_EFFECT_OPTIONS_EVIDENCE
    path = directory / EFFECT_OPTIONS_MERGED
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    counts = document.get("counts") or {}
    if counts.get("missing") or counts.get("collisions"):
        raise SystemExit(
            f"FAIL: {path} reports {counts.get('missing')} unmeasured and "
            f"{counts.get('collisions')} colliding effect option(s); run "
            "effect_options_merge.py --check and re-capture before generating"
        )
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for target in document.get("targets") or []:
        grouped.setdefault(target["effectKey"], {}).setdefault(target["setting"], []).append(
            target
        )
    return grouped


def promote_effect_options(
    entry: dict[str, Any], settings: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """Write one gallery entry's measured ``Effect Options`` values into its OOXML.

    Each value carries its own ``presetSubtype`` **and** its own behaviours,
    because neither alone is sufficient:

    * 9 of the 37 groups never move ``presetSubtype``. Spin's Clockwise and
      Counterclockwise are both subtype 0 and differ only in the sign of
      ``p:animRot/@by``, so a subtype-only option would write one direction for
      both.
    * No group moves ``presetSubtype`` *alone*. The behaviours are what actually
      animate the shape — the subtype is the label PowerPoint names the effect
      by — so the writer has to emit the measured behaviours either way.

    ``default`` names the value whose OOXML equals what pressing the tile alone
    produces, and ``defaultResolvedBy`` says how that was established:

    ``signature``
        The tile's own measured ``presetSubtype`` and behaviours match the
        value's exactly. The strongest answer, available for the 14 effects the
        gallery capture measured.
    ``presetSubtype``
        19 of the 95 tiles were outside the gallery capture's plan and carry no
        measured behaviours, so there is nothing to compare. The subtype the
        catalog already holds from native fixtures identifies the value instead,
        and only when it matches **exactly one** of them.
    ``siblingSetting``
        Neither worked, but **another setting of the same effect** resolved its
        own default — and pressing a setting's default value leaves the effect
        at the tile's default, so that value's bytes *are* the tile's bytes.
        Comparing against them resolves what the tile alone could not.

        This is what settles ``Shape``'s ``Shapes``. Its four values all carry
        the tile's subtype, because the shape lives in ``p:animEffect/@filter``
        rather than in the subtype, and ``Shape`` is one of the 19 tiles with no
        measured behaviours of its own. But its ``Direction`` default resolved
        to ``in``, and ``direction=in`` measured ``circle(in)`` — identical to
        ``shapes=circle``. So Circle is the default, derived from measurement
        rather than assumed.

    ``None``
        None of the three worked, and the catalog says so rather than picking.
    """
    ooxml = entry.get("ooxml")
    if not isinstance(ooxml, dict) or entry.get("status") != "accepted":
        return entry

    tile_signature = json.dumps(
        {
            "presetSubtype": ooxml.get("presetSubtype"),
            "behaviors": ooxml.get("behaviors") or [],
        },
        sort_keys=True,
    )

    options: dict[str, Any] = {}
    for setting, targets in sorted(settings.items()):
        values: dict[str, Any] = {}
        default_slug: str | None = None
        for target in sorted(targets, key=lambda item: item["value"]):
            behaviors = [measured_behavior(b) for b in target.get("behaviors") or []]
            subtype_text = (target.get("effectAttributes") or {}).get("presetSubtype")
            subtype = int(subtype_text) if subtype_text is not None else None
            slug = option_slug(target["value"])
            values[slug] = {
                "label": target["value"],
                "presetSubtype": subtype,
                "behaviors": behaviors,
                "behaviorChildren": sorted({b["element"] for b in behaviors}),
                # The duration the option's own timings belong to, read off the
                # ribbon when it was captured. Omitting it was a defect: the
                # writer's overlay reads this field to let an option be written
                # at another duration, and without it every option fell back to
                # its effect's duration — which 19 of the 95 tiles do not have.
                "measuredDurationMs": target.get("measuredDurationMs"),
                "measuredIn": target.get("measuredIn"),
            }
            signature = json.dumps(
                {"presetSubtype": subtype, "behaviors": behaviors}, sort_keys=True
            )
            if signature == tile_signature:
                default_slug = slug
        resolved_by = "signature" if default_slug is not None else None
        if default_slug is None and not (ooxml.get("behaviors") or []):
            # No measured behaviours to compare against, so fall back to the
            # subtype the catalog holds from native fixtures. Only a unique
            # match counts: a setting whose values all share the tile's subtype
            # cannot be resolved this way, and guessing one would put a default
            # label on bytes that do not belong to it.
            matches = [
                slug
                for slug, value in values.items()
                if value["presetSubtype"] == ooxml.get("presetSubtype")
            ]
            if len(matches) == 1:
                default_slug = matches[0]
                resolved_by = "presetSubtype"
        options[option_slug(setting)] = {
            "setting": setting,
            "default": default_slug,
            "defaultResolvedBy": resolved_by,
            "values": values,
        }

    _resolve_default_from_sibling(options)
    _lift_tile_behaviours_from_default(entry, options)

    ooxml["effectOptions"] = options
    # Measured one setting at a time: each value was applied with every *other*
    # setting left at its default. For the four effects offering two settings at
    # once that leaves the combinations unmeasured, and the writer refuses them
    # rather than composing two measurements into a value PowerPoint never
    # wrote. Recorded here so the refusal quotes the catalog instead of a
    # hardcoded sentence.
    if len(options) > 1:
        combinations = 1
        for option in options.values():
            combinations *= len(option["values"])
        ooxml["effectOptionCombinations"] = {
            "measured": "oneSettingAtATime",
            "settings": sorted(options),
            "combinations": combinations,
            "gap": (
                "each value was measured with the effect's other setting left at its default, "
                f"so the {combinations} combinations of "
                f"{' and '.join(sorted(options))} are not measured; ask for one setting at a time"
            ),
        }
    entry.setdefault("capture", {})["effectOptions"] = {
        "source": GUI_CAPTURE_SOURCE,
        "application": BASELINE_APPLICATION,
        "version": BASELINE_VERSION,
        "capturedAt": EFFECT_OPTIONS_DATE,
        "driver": GUI_CAPTURE_DRIVER,
        "merged": (
            DEFAULT_EFFECT_OPTIONS_EVIDENCE.relative_to(REPO_ROOT).as_posix()
            + f"/{EFFECT_OPTIONS_MERGED}"
        ),
        "settings": sorted(options),
        "values": sum(len(option["values"]) for option in options.values()),
        "verifiedBy": (
            "effect_options_merge.py: no two values of one setting carry the same OOXML"
        ),
    }
    return entry


def _behaviour_signature(behaviors: list[dict[str, Any]]) -> str:
    """The part of a behaviour list that identifies a value, timings excluded.

    ``dur`` and ``delay`` are left out because they belong to the duration the
    capture ran at, and two captures of the same effect at different durations
    would otherwise look like different values.
    """
    return json.dumps(
        [
            {
                "element": behavior.get("element"),
                "attributes": behavior.get("attributes") or {},
                "attrNames": behavior.get("attrNames") or [],
                "values": behavior.get("values") or {},
            }
            for behavior in behaviors
        ],
        sort_keys=True,
    )


def _resolve_default_from_sibling(options: dict[str, Any]) -> None:
    """Resolve a setting's default from another setting of the same effect.

    Pressing a setting's **default** value leaves the effect exactly as pressing
    the tile alone does, so a resolved default's bytes are the tile's bytes.
    That makes it a usable reference for a sibling setting the tile itself could
    not resolve — which is the only way ``Shape``'s ``Shapes`` can be resolved
    at all, since ``Shape`` has no measured behaviours and all four of its
    shapes carry the tile's subtype.
    """
    references = [
        option["values"][option["default"]]
        for option in options.values()
        if option.get("default") and option.get("defaultResolvedBy") in ("signature", "presetSubtype")
    ]
    if not references:
        return
    signatures = {_behaviour_signature(reference.get("behaviors") or []) for reference in references}
    if len(signatures) != 1:
        # Two settings disagree about what the tile's default bytes are, so
        # neither can serve as a reference. Nothing is resolved rather than
        # picking one.
        return
    (reference_signature,) = signatures
    for option in options.values():
        if option.get("default") is not None:
            continue
        matches = [
            value
            for value, measured in option["values"].items()
            if _behaviour_signature(measured.get("behaviors") or []) == reference_signature
        ]
        if len(matches) == 1:
            option["default"] = matches[0]
            option["defaultResolvedBy"] = "siblingSetting"


#: Where the read of this build's applicable effects lives. Two halves: the
#: gallery tiles, enumerated by the effect-option discovery, and the ``Path
#: Animation`` popup, read by ``discover_platform_inventory.py``.
DEFAULT_PLATFORM_INVENTORY = (
    REPO_ROOT
    / "tests/fixtures/animations/gui-only/platform-inventory-2026-11-02/platform-inventory.json"
)
DEFAULT_GALLERY_TILES = (
    REPO_ROOT / "tests/fixtures/animations/gui-only/effect-options-2026-11-01/tiles.json"
)


def _label_key(label: str) -> str:
    """Compare labels by letters and digits only.

    ``Grow/Shrink`` and ``grow shrink``, ``4 Point Star`` and ``4 point star``
    are the same effect under two spellings — the sdef enumerator and the
    ribbon label never agree on punctuation or case.
    """
    return re.sub(r"[^a-z0-9]", "", label.lower())


def applicable_labels_by_surface(
    inventory: Path | None = None, tiles: Path | None = None
) -> dict[str, set[str]]:
    """Return the applicable effect labels, kept apart by the surface offering them.

    The two surfaces must not be merged. A motion path is offered only by the
    ``Path Animation`` popup and an entrance/emphasis/exit effect only by its
    gallery, so a label found on one says nothing about the other — and the
    names do collide. ``Wave`` is an Emphasis tile while the popup's path is
    ``Waves``; ``Spiral`` is a popup path and no gallery offers it.
    """
    paths: set[str] = set()
    inventory_path = inventory or DEFAULT_PLATFORM_INVENTORY
    if inventory_path.exists():
        document = json.loads(inventory_path.read_text(encoding="utf-8"))
        paths.update(_label_key(label) for label in document.get("labels") or ())
        for gallery in document.get("galleries") or ():
            for item in gallery.get("items") or ():
                label = item.get("label") if isinstance(item, dict) else item
                if label:
                    paths.add(_label_key(str(label)))

    galleries: set[str] = set()
    tiles_path = tiles or DEFAULT_GALLERY_TILES
    if tiles_path.exists():
        document = json.loads(tiles_path.read_text(encoding="utf-8"))
        for gallery in document.values():
            for item in gallery:
                label = item.get("label") if isinstance(item, dict) else item
                if label:
                    galleries.add(_label_key(str(label)))
    return {"path": paths, "gallery": galleries}


def applicable_effect_labels(
    inventory: Path | None = None, tiles: Path | None = None
) -> set[str]:
    """Every effect label this build can apply, both surfaces together.

    Kept for callers that only need "is this reachable at all". Classification
    must use :func:`applicable_labels_by_surface` instead: matching against the
    union lets a gallery effect vouch for a motion path of the same name.
    """
    by_surface = applicable_labels_by_surface(inventory, tiles)
    return by_surface["path"] | by_surface["gallery"]


def mark_platform_unavailable(items: list[dict[str, Any]]) -> int:
    """Flag the enumerators this build has no way to apply, and say why.

    The sdef names 185 animation enumerators. Most of the ``MsoAnimEffect``
    ones are Windows-era effects — ``bean path``, ``buzzsaw path``, ``light
    speed``, ``zip`` — and **PowerPoint for Mac cannot apply them at all**: on
    Windows the full list is reached through ``Add Animation ▸ … ▸ More Entrance
    Effects…`` / ``More Motion Paths…``, and this build has no ``Add
    Animation`` control, so the galleries are the whole set.

    Recording them as capture-required claimed a PowerPoint read-back would
    close them. It would not, on this platform, and the count could never reach
    zero — the same defect that ``noSdpmInput`` fixed for the direction names,
    one layer down.

    ``platformUnavailable`` is deliberately **not** ``noSdpmInput``. The reason
    differs and so does the remedy: a direction name can never identify a
    ``presetSubtype``, whereas these effects are perfectly real and simply out
    of reach *here*. A capture on Windows, or a Mac build that gains ``Add
    Animation``, would close them.
    """
    by_surface = applicable_labels_by_surface()
    if not any(by_surface.values()):
        return 0
    marked = 0
    for entry in items:
        key = str(entry.get("key", ""))
        if not key.startswith("MsoAnimEffect.animation type "):
            continue
        ooxml = entry.get("ooxml")
        if not isinstance(ooxml, dict) or not ooxml.get("requiresCapture"):
            continue
        enumerator = key.removeprefix("MsoAnimEffect.animation type ")
        # A motion path is reachable only through the Path Animation popup and
        # an entrance/emphasis/exit effect only through its gallery, so each is
        # checked against its own surface. Matching the union spared two
        # enumerators this build cannot apply: `wave path` was vouched for by
        # the Emphasis tile `Wave` (the popup's path is `Waves`), and `spiral`
        # by the popup's `Spiral` path (no gallery offers it).
        surface = "path" if enumerator.endswith(" path") else "gallery"
        label = enumerator.removesuffix(" path")
        if _label_key(label) in by_surface[surface]:
            continue
        offered = "popup" if surface == "path" else "gallery"
        entry["platformUnavailable"] = {
            "platform": "macOS",
            "application": BASELINE_APPLICATION,
            "version": BASELINE_VERSION,
            "surface": surface,
            "reason": (
                f"no {offered} of this build offers {label!r}. The full effect list is "
                "reached on Windows through Add Animation, which PowerPoint for Mac does not "
                "have, so no capture on this platform can record this enumerator's OOXML form"
            ),
            "readFrom": [
                DEFAULT_PLATFORM_INVENTORY.relative_to(REPO_ROOT).as_posix(),
                DEFAULT_GALLERY_TILES.relative_to(REPO_ROOT).as_posix(),
            ],
            "corroboration": [
                "https://support.microsoft.com/en-us/office/add-a-motion-path-animation-effect-f3174300-0d24-4671-a1c2-e286b41efba6",
                "https://learn.microsoft.com/en-us/answers/questions/5314795/where-is-more-motion-paths-in-newest-power-point",
            ],
            "closes": "a capture on a platform whose PowerPoint offers the effect",
        }
        marked += 1
    return marked


def _lift_tile_behaviours_from_default(
    entry: dict[str, Any], options: dict[str, Any]
) -> None:
    """Give a tile the measured behaviours of its own default option.

    19 of the 95 tiles fell outside the gallery capture's plan and carry no
    measured behaviours, so the writer builds theirs from the catalog's general
    rules instead of transcribing them. For 8 exit tiles that is not merely
    less exact, it is a refusal: the synthesised form has to derive where the
    visibility ``p:set`` ends from a duration the entry does not record, so
    ``blinds``, ``checkerboard``, ``randomBars``, ``shape``, ``split``,
    ``strips``, ``wheel`` and ``wipe`` reject a plain write unless the caller
    names ``timing.durationMs`` — while the *same effect with an option* writes
    happily, because the option supplies measured behaviours. One effect, two
    requirements, decided by an unrelated field.

    Nothing new has to be measured to fix it. Pressing a setting's **default**
    value leaves the effect exactly as pressing the tile alone does, so that
    value's behaviours are the tile's behaviours. They were captured; they were
    just filed one level down.

    Only a resolved default is used, and only when the tile has none of its
    own, so this never overwrites a measurement with an inference.
    """
    ooxml = entry.get("ooxml")
    if not isinstance(ooxml, dict) or (ooxml.get("behaviors") or []):
        return
    for setting, option in sorted(options.items()):
        default = option.get("default")
        if not default or option.get("defaultResolvedBy") not in (
            "signature",
            "presetSubtype",
            "siblingSetting",
        ):
            continue
        measured = option["values"][default]
        behaviors = measured.get("behaviors") or []
        if not behaviors:
            continue
        ooxml["behaviors"] = behaviors
        ooxml["behaviorChildren"] = sorted({b["element"] for b in behaviors})
        if measured.get("measuredDurationMs") is not None:
            ooxml["measuredDurationMs"] = measured["measuredDurationMs"]
            ooxml["durationScaling"] = GUI_DURATION_SCALING
        ooxml.pop("unresolvedPayloads", None)
        ooxml.pop("requiresCapture", None)
        ooxml.pop("gap", None)
        entry.setdefault("capture", {})["behavioursLiftedFrom"] = {
            "setting": setting,
            "value": default,
            "resolvedBy": option.get("defaultResolvedBy"),
            "why": (
                "pressing a setting's default value leaves the effect at the tile's own "
                "default, so this value's measured behaviours are the tile's"
            ),
        }
        entry["capabilityLevel"] = NATIVE
        entry["verification"] = GUI_CAPTURE_VERIFICATION
        return


def promote_all_effect_options(
    items: list[dict[str, Any]],
    evidence: dict[str, dict[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """Fold every measured effect option into the entry its effect names."""
    by_key = {entry["key"]: entry for entry in items}
    missing = sorted(key for key in evidence if key not in by_key)
    if missing:
        raise SystemExit(
            f"FAIL: the effect-option capture names {len(missing)} effect(s) no catalog item "
            f"carries: {missing}"
        )
    for key, settings in evidence.items():
        promote_effect_options(by_key[key], settings)
    return items


def align_candidate_durations(candidates: list[dict[str, Any]],
                              items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the example duration of a candidate that mirrors a non-scalable tile.

    A candidate whose own enumerator → OOXML mapping the dictionary could not
    establish is still writable, because it resolves by ``presetClass`` +
    ``presetID`` to a gallery tile the GUI capture measured. Two of those tiles
    — Bold Reveal and Transparency — have **no numeric duration**: the ribbon
    reports ``Auto`` and their behaviours carry ``dur="indefinite"``. A
    candidate still claiming a duration would therefore ask the writer for
    something the effect cannot have, and the writer rightly refuses it.

    So the candidate's example is corrected to match the tile it resolves to.
    The alternative was to let the writer ignore a duration it cannot honour,
    which would mean a caller's explicit request disappearing silently.
    """
    fixed = {
        (entry["ooxml"].get("presetClass"), entry["ooxml"].get("presetId"))
        for entry in items
        if isinstance(entry.get("ooxml"), dict)
        and entry["ooxml"].get("measuredDurationMs") is None
        and (entry["ooxml"].get("durationScaling") or {}).get("rule") == "notScalable"
    }
    for entry in candidates:
        ooxml = entry.get("ooxml")
        if not isinstance(ooxml, dict):
            continue
        # Some candidate mappings record a LIST of presetIDs — one enumerator
        # covering several tiles — which cannot identify a single tile and is
        # skipped rather than coerced into one.
        identity = (ooxml.get("presetClass"), ooxml.get("presetId"))
        scalar = (int, str, type(None))
        if not all(isinstance(part, scalar) for part in identity) or identity not in fixed:
            continue
        effects = ((entry.get("semanticJson") or {}).get("animations") or {}).get("mainSequence") or []
        if effects and isinstance(effects[0], dict) and isinstance(effects[0].get("timing"), dict):
            effects[0]["timing"]["durationMs"] = None
    return candidates


def candidate_entries(sdef_enums: dict[str, list[tuple[str, str]]],
                      evidence: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Account for every candidate in the eight required sdef enumerations."""
    evidence = {} if evidence is None else evidence
    measured = oracle_measured_forms(evidence)
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
                    effect_semantic(preset={"category": "entrance", "effect": "flyIn",
                                            "options": {"direction": semantic}}),
                    {"source": SDEF_SOURCE, "commit": None},
                    guiKey=f"animation.effectOptions.direction.{semantic}",
                    noSdpmInput=True,
                )
            elif enum_name == "MsoAnimTriggerType":
                semantic, node_type, level = TRIGGER_MAP[enumerator]
                if node_type is None:
                    # See the matching branch in enum_value_items: an absence
                    # is not a value awaiting measurement.
                    entry = _unaccepted(
                        key, "nonPersisted",
                        "msoAnimTriggerNone reports an effect with no trigger; its persisted form is the "
                        "absence of a start condition, so PowerPoint writes no p:cond and sdpm has no value "
                        "to author",
                        guiKey=f"animation.start.{semantic}",
                    )
                else:
                    entry = _accepted(
                        key, level,
                        {"strategy": "timingNode", "nodeType": node_type},
                        trigger_semantic(semantic),
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
            record = evidence.get(key)
            if record is not None:
                promote_oracle_capture(entry, record, measured)
            entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Catalog assembly and checking
# ---------------------------------------------------------------------------
def build_catalog(manifest: dict[str, Any], sdef_enums: dict[str, list[tuple[str, str]]],
                  evidence: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build the full catalog from the evidence tables, the sdef and the capture."""
    if evidence is None:
        evidence = load_oracle_evidence()
    items = promote_gui_captures(
        gui_items() + enum_value_items(sdef_enums), load_gui_capture_evidence()
    )
    # After the gallery capture, not before: an option's default is resolved by
    # comparing it against what pressing the tile alone produces, and that
    # comparison needs the tile's own measured behaviours already in place.
    items = promote_all_effect_options(items, load_effect_options_evidence())
    items.sort(key=lambda entry: entry["key"])
    candidates = align_candidate_durations(candidate_entries(sdef_enums, evidence), items)
    candidates.sort(key=lambda entry: entry["key"])
    # Last of all, and over **both** groups, so it sees the final
    # requiresCapture state: an entry a capture has just closed must not then be
    # labelled unreachable. The MsoAnimEffect enumerators live in `candidates`,
    # which is why marking only `items` found nothing.
    mark_platform_unavailable(items + candidates)
    capture_counts = {
        "probed": sum(1 for entry in candidates if "capture" in entry),
        "transitionWritten": sum(
            1 for entry in candidates if entry.get("capture", {}).get("outcome") == "transitionWritten"
        ),
        "rejectedByPowerPoint": sum(
            1 for entry in candidates if entry.get("capture", {}).get("outcome") == "rejectedByPowerPoint"
        ),
        "appliedWithoutPersistedForm": sum(
            1 for entry in candidates if entry.get("capture", {}).get("outcome") == "appliedWithoutPersistedForm"
        ),
        "promoted": sum(1 for entry in candidates if entry.get("verification") == ORACLE_VERIFICATION),
    }
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
                "used once, deliberately, by a maintainer: scripts/animation_catalog/powerpoint.applescript "
                f"was run on {ORACLE_CAPTURE_DATE} from a terminal holding the Automation grant - the sdpm "
                "dashboard itself still cannot, because addressing PowerPoint from it is refused with a "
                "-10004 privilege violation - and its "
                "output is checked in under provenance.scriptingOracle.fixture. An entry whose verification "
                f"is {ORACLE_VERIFICATION!r} carries the OOXML PowerPoint wrote for it; every other value "
                "still comes from the offline scripting definition, captured native OOXML, and normative "
                "schema. sdpm's runtime, CLI, MCP servers, tests and CI never pass the oracle's consent "
                "argument, so nothing here launches PowerPoint on its own (REQ-7.3), and VBA is not used at "
                "all."
            ),
            "scriptingOracle": oracle_provenance(evidence),
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
            "scriptingOracleCapture": capture_counts,
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

    if DEFAULT_SDEF.exists():
        local_codes = read_sdef_enum_codes(DEFAULT_SDEF)
        for enum_name, expected_code in CANDIDATE_ENUM_CODES.items():
            actual_code = local_codes.get(enum_name)
            if actual_code != expected_code:
                findings.append(
                    f"local sdef enumeration {enum_name} has type code {actual_code!r}, expected "
                    f"{expected_code!r}; the oracle names every one of its candidates with that code"
                )

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
#: Handler that turns one candidate's ``<enumeration type code><enumerator
#: code>`` into the Apple Event constant it names. The generated arrays call
#: it instead of carrying bare enumerator terms.
ORACLE_CONSTANT_HANDLER = "on enumConstant(typedCode)"

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


def oracle_typed_code(enum_name: str, code: str) -> str:
    """Return the twelve characters that name one enumerator by code.

    The enumeration's four-character type code followed by the enumerator's own
    eight hexadecimal digits, upper-cased:
    ``EPPEntryEffect`` + ``0x00f60f55`` -> ``pEeF00F60F55``. The oracle turns
    this into the Apple Event constant itself at run time.
    """
    return CANDIDATE_ENUM_CODES[enum_name] + code.removeprefix("0x").upper()


def oracle_constant_call(enum_name: str, code: str) -> str:
    """Return the AppleScript expression the generated arrays use for one value."""
    return f'my enumConstant("{oracle_typed_code(enum_name, code)}")'


def render_oracle_arrays(sdef_enums: dict[str, list[tuple[str, str]]]) -> str:
    """Render the oracle's generated region from the scripting definition.

    Three parallel arrays per enumeration: the constants, their sdef names and
    their sdef codes. A constant is named by code - the enumeration's type code
    plus the enumerator's own - and built by the oracle's ``enumConstant``
    handler, never written as a bare AppleScript term. A term is ambiguous in
    two ways that a code is not: ``top``, ``font bold``, ``font italic`` and
    ``dim`` are PowerPoint *property* names, so the compiler resolves them as
    property references and evaluating one raises -1728; and ``horizontal`` and
    ``vertical`` compile to constants of a different enumeration entirely
    (``TxOr``, text orientation), which is worse because nothing fails - the
    probe would apply the wrong value and the record would name the right one.
    Naming every candidate by code removes both, by construction, instead of
    keeping a list of the terms known to collide.
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
        "-- Each enumeration gets three parallel arrays: the constants, each named by",
        "-- its enumeration type code plus its own enumerator code and built by",
        "-- enumConstant rather than written as a bare AppleScript term, which would be",
        "-- ambiguous against PowerPoint's property names and against other",
        "-- enumerations; their sdef names, for the JSONL records; and their sdef codes,",
        "-- for drift detection.",
        "",
    ]
    for enum_name in CANDIDATE_ENUMS:
        values = sdef_enums[enum_name]
        prefix = oracle_prefix(enum_name)
        names = [name for name, _ in values]
        codes = [code for _, code in values]
        constants = [oracle_constant_call(enum_name, code) for code in codes]
        lines.append(f"-- {enum_name}: {len(values)} candidates, type code {CANDIDATE_ENUM_CODES[enum_name]}")
        lines.append(f"on {prefix}Constants()")
        lines.append("\treturn " + _oracle_list(constants, "\t\t"))
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
    if ORACLE_CONSTANT_HANDLER not in script_text:
        findings.append(
            f"oracle script has no {ORACLE_CONSTANT_HANDLER!r} handler, so its generated arrays cannot name "
            "a candidate by code"
        )
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
        constants, codes = group.get("constants"), group.get("codes")
        if constants is not None and codes is not None and len(constants) == len(codes):
            expected = [oracle_constant_call(enum_name, code) for code in codes]
            if constants != expected:
                wrong = next(
                    (actual for actual, want in zip(constants, expected) if actual != want), constants[0]
                )
                findings.append(
                    f"oracle script {enum_name} constants are not each the code of their own candidate, so a "
                    f"record would report a name the constant did not apply, first {wrong!r}"
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
        constants = [oracle_constant_call(enum_name, code) for code in codes]
        for kind, expected in (("constants", constants), ("names", names), ("codes", codes)):
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


# --- the GUI capture: animation effects measured through the ribbon ---------
GUI_CAPTURE_RECORD = "guiCapture"
GUI_CAPTURE_SOURCE = "sdpm GUI capture"
GUI_CAPTURE_DATE = "2026-11-01"
GUI_CAPTURE_DRIVER = "macOS accessibility API; no Apple Events and no Visual Basic"
#: Written into a promoted entry's ``verification``. Deliberately distinct from
#: the scripting oracle's and from ``nativeCapture``: an entry says which of the
#: three measured it, and the three reached different parts of the surface.
GUI_CAPTURE_VERIFICATION = "guiCapture"

#: What writing a measured effect at a duration other than the measured one
#: does, and what it costs. Measured 2026-11-01 over 4 effects and 41
#: behaviours at ratios x2, x3/2 and x9/8; the numbers are in
#: ``scripts/animation_catalog/computer-use.md``.
GUI_DURATION_SCALING = {
    "rule": "proportional",
    "scales": ["durMs", "delayMs"],
    "exempt": {
        "element": "p:set",
        "attrName": "style.visibility",
        "durMs": 1,
        "delayMs": "0 for an entrance; measured recomputed as duration - 1 for an exit, not scaled",
    },
    "unchanged": [
        "every behaviour attribute (@path, @by, @filter, @calcmode, @valueType)",
        "presetClass, presetId, presetSubtype",
        "the behaviour count and their order",
    ],
    "accuracy": (
        "byte-exact at measuredDurationMs, because the measured integers are written as they "
        "stand. At another duration the product may land on an exact half, and PowerPoint's own "
        "float precision then rounds those both ways - 580 -> 652 down and 1324 -> 1490 up at the "
        "same ratio - so a scaled value may differ from PowerPoint by 1 ms. Measured, not estimated."
    ),
    "evidence": "scripts/animation_catalog/computer-use.md, 'What the Duration field does to an effect's XML'",
}

#: For an effect the ribbon reports as ``Auto``. Its behaviours carry
#: ``dur="indefinite"``, so there is nothing to scale and nothing to scale it
#: against; the measured form is the only form.
GUI_DURATION_FIXED = {
    "rule": "notScalable",
    "reason": (
        "the ribbon reports this effect's Duration as 'Auto' and its behaviours carry "
        "dur=\"indefinite\"; there is no numeric duration to scale from or to"
    ),
    "evidence": "scripts/animation_catalog/computer-use.md, 'What the Duration field does to an effect's XML'",
}

#: The behaviour elements a preset effect writes beneath its ``p:cTn``. The same
#: set the native captures summarise by name — what is new here is each one's
#: payload.
GUI_BEHAVIOR_ELEMENTS = ORACLE_BEHAVIOR_ELEMENTS

#: Depth and node bounds on the payload dump of one behaviour. A behaviour's
#: subtree is shallow (``p:cBhvr`` ▸ ``p:cTn`` ▸ ``p:stCondLst`` ▸ ``p:cond`` is
#: the deepest path), so a tree deeper than this is not the shape measured and
#: failing loudly beats recording something else.
GUI_PAYLOAD_MAX_DEPTH = 8
GUI_PAYLOAD_MAX_NODES = 400


def _xml_subtree(element: Any, *, depth: int = 0) -> dict[str, Any]:
    """Return one element as ``{element, attributes, children}``, bounded.

    Deliberately generic. The alternative was a reader per OOXML value shape —
    ``p:to/p:strVal/@val`` for a visibility set, ``p:to/a:srgbClr/@val`` for a
    colour, ``@x``/``@y`` on a ``CT_TLPoint`` for a scale — and enumerating
    those would be me deciding in advance what PowerPoint writes. A faithful
    dump cannot omit a shape nobody anticipated, and the merged evidence file is
    where fidelity belongs; the catalog gets the normalised view built from it.
    """
    if depth > GUI_PAYLOAD_MAX_DEPTH:
        raise ValueError(
            f"a behaviour subtree is deeper than {GUI_PAYLOAD_MAX_DEPTH} at "
            f"{_oracle_qname(element)}; the measured shape is shallower, so this is not it"
        )
    return {
        "element": _oracle_qname(element),
        "attributes": _oracle_attributes(element),
        "children": [_xml_subtree(child, depth=depth + 1) for child in element],
    }


def _behavior_timing(behavior: Any) -> dict[str, Any]:
    """Return the timing ``p:cBhvr/p:cTn`` gives one behaviour, flattened.

    The delay lives one level further down, in ``p:stCondLst/p:cond/@delay``,
    and it is the one attribute that distinguishes the two halves of a Wave
    (``p:animRot by="1500000"`` at delay 0, then ``by="-1500000"`` at delay
    125), so it is lifted to the same level as the duration rather than left
    inside a nested condition list.
    """
    timing: dict[str, Any] = {}
    for child in behavior:
        if _oracle_local(child) != "cBhvr":
            continue
        for inner in child:
            if _oracle_local(inner) != "cTn":
                continue
            timing.update(_oracle_attributes(inner))
            timing.pop("id", None)
            for condition in inner.iter():
                if _oracle_local(condition) == "cond" and condition.get("delay") is not None:
                    timing.setdefault("delay", condition.get("delay"))
    return timing


def _behavior_attr_names(behavior: Any) -> list[str]:
    """Return the animated attribute names, in document order.

    ``p:attrNameLst`` is what the payload gap meant by "the animated attribute
    name". A Wave's motion names ``ppt_x`` and ``ppt_y``; its rotations name
    ``r``; an emphasis ``p:set`` names the font attribute the catalog refused
    those tiles for not knowing.
    """
    return [
        (element.text or "").strip()
        for element in behavior.iter()
        if _oracle_local(element) == "attrName" and (element.text or "").strip()
    ]


#: The payload children of a behaviour. ``p:to``/``p:from``/``p:by`` carry a
#: single target value; ``p:tavLst`` carries a keyframe list instead, and it is
#: where a ``p:anim`` keeps everything it says — Fly In's ``p:anim`` has no
#: ``p:to`` at all and would have been recorded as payload-less without it.
GUI_VALUE_ELEMENTS = ("to", "from", "by", "tavLst")


def _behavior_values(behavior: Any) -> dict[str, Any]:
    """Return the value payloads of one behaviour, as subtrees.

    Subtrees rather than scalars because the value is not one thing: a colour
    ``p:to`` holds an ``a:srgbClr`` or an ``a:schemeClr``, a scale ``p:to``
    carries ``@x``/``@y`` on itself, a visibility ``p:to`` holds a ``p:strVal``,
    and a ``p:anim`` has no ``p:to`` but a ``p:tavLst`` of keyframes. Flattening
    those to a string would lose which of them it was.
    """
    values: dict[str, Any] = {}
    for child in behavior:
        local = _oracle_local(child)
        if local in GUI_VALUE_ELEMENTS:
            values[local] = _xml_subtree(child)
    return values


def _behavior_carrier(behavior: Any) -> dict[str, Any]:
    """Return ``p:cBhvr``'s own attributes: how the behaviour combines, not when.

    ``@additive`` is the one that changes what the effect does — Fly In's
    ``p:anim`` is ``additive="base"``, so its keyframes are relative to the
    shape's own position rather than absolute — and it is neither timing nor a
    value, so it is recorded on its own rather than merged into either.
    """
    for child in behavior:
        if _oracle_local(child) == "cBhvr":
            return _oracle_attributes(child)
    return {}


def _effect_iterate(ctn: Any) -> dict[str, Any] | None:
    """Return the effect's ``p:iterate``, or None when it has none.

    12 of the 76 captured effects carry one, and it is not decoration: it is
    what makes an effect play per letter or per word instead of once for the
    shape, and it sits on the effect node rather than on a behaviour. Measured
    forms are ``type="lt"`` with ``p:tmPct`` 10000, 4000 or 50000, and one with
    ``p:tmAbs`` 25. An effect written without it animates the whole shape at
    once, which is a different animation.
    """
    for child in ctn:
        if _oracle_local(child) != "iterate":
            continue
        return {
            "attributes": _oracle_attributes(child),
            "children": [_xml_subtree(inner) for inner in child],
        }
    return None


def effect_behaviors(ctn: Any) -> list[dict[str, Any]]:
    """Return every behaviour child of one preset effect, in document order.

    Document order matters and is preserved: the two ``p:animRot`` halves of a
    Wave differ only in their ``by`` and their delay, so a set would collapse
    them and a sort would make the pair's order an accident of attribute values.
    """
    behaviors: list[dict[str, Any]] = []
    seen = 0
    for element in ctn.iter():
        if _oracle_local(element) not in GUI_BEHAVIOR_ELEMENTS:
            continue
        seen += 1
        if seen > GUI_PAYLOAD_MAX_NODES:
            raise ValueError(
                f"one effect published more than {GUI_PAYLOAD_MAX_NODES} behaviours; that is not "
                "the shape measured"
            )
        behaviors.append(
            {
                "element": _oracle_qname(element),
                "attributes": _oracle_attributes(element),
                "carrier": _behavior_carrier(element),
                "timing": _behavior_timing(element),
                "attrNames": _behavior_attr_names(element),
                "values": _behavior_values(element),
            }
        )
    return behaviors


def parse_gui_capture_package(package: Path) -> dict[str, dict[str, Any]]:
    """Return every preset effect in a captured package, keyed by its target spid.

    One slide carries all 76 effects, and each is identified by the
    ``p:spTgt/@spid`` of the shape it animates — which is exactly how the driver
    attributed it. An effect targeting more than one spid is **not** keyed: that
    would be an effect the capture cannot attribute to one shape, so it is
    reported unattributable rather than assigned to the first spid it names.
    """
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    by_spid: dict[str, dict[str, Any]] = {}
    collisions: set[str] = set()
    with zipfile.ZipFile(package) as archive:
        for name in sorted(archive.namelist()):
            if not ORACLE_SLIDE_PART.fullmatch(name):
                continue
            root = etree.fromstring(archive.read(name), parser=parser)
            for element in root.iter():
                if _oracle_local(element) != "cTn" or element.get("presetID") is None:
                    continue
                spids = sorted({
                    target.get("spid")
                    for target in element.iter()
                    if _oracle_local(target) == "spTgt" and target.get("spid")
                })
                attributes = _oracle_attributes(element)
                attributes.pop("id", None)
                effect = {
                    "part": name,
                    "attributes": attributes,
                    "spids": spids,
                    "iterate": _effect_iterate(element),
                    "behaviors": effect_behaviors(element),
                }
                if len(spids) != 1:
                    continue
                spid = spids[0]
                if spid in by_spid:
                    collisions.add(spid)
                by_spid[spid] = effect
    for spid in collisions:
        by_spid[spid]["ambiguous"] = (
            "more than one preset effect on this slide targets this spid, so the package cannot "
            "say which of them belongs to the record"
        )
    return by_spid


def parse_gui_capture_package_all(package: Path) -> dict[str, list[dict[str, Any]]]:
    """Return **every** preset effect per target spid, not one.

    :func:`parse_gui_capture_package` keeps one effect per spid, which is right
    for a capture where each shape carries one. The effect-options capture is
    not that: each shape carries **two** — the tile's default and a second one
    holding the pressed value — so resolving them needs both, and the ordering
    inside a spid is document order.
    """
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    by_spid: dict[str, list[dict[str, Any]]] = {}
    with zipfile.ZipFile(package) as archive:
        for name in sorted(archive.namelist()):
            if not ORACLE_SLIDE_PART.fullmatch(name):
                continue
            root = etree.fromstring(archive.read(name), parser=parser)
            for element in root.iter():
                if _oracle_local(element) != "cTn" or element.get("presetID") is None:
                    continue
                spids = sorted({
                    target.get("spid")
                    for target in element.iter()
                    if _oracle_local(target) == "spTgt" and target.get("spid")
                })
                if len(spids) != 1:
                    continue
                attributes = _oracle_attributes(element)
                attributes.pop("id", None)
                by_spid.setdefault(spids[0], []).append(
                    {
                        "part": name,
                        "attributes": attributes,
                        "spids": spids,
                        "iterate": _effect_iterate(element),
                        "behaviors": effect_behaviors(element),
                    }
                )
    return by_spid


def merge_gui_capture(records: list[dict[str, Any]],
                      effects: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Join the driver's read-back with the effects its saved package holds.

    The join is on ``attributedSpid`` — the spid the driver verified the effect
    landed on — never on slide or record order, because every record shares one
    slide and order survives nothing.

    A record whose spid the package does not carry, or carries twice, lands in
    ``unresolved`` with the reason. Nothing is guessed into place: the catalog
    reads this file, so an unresolved record must stay visible rather than
    become an entry promoted on a joined-by-position effect.
    """
    merged: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for record in records:
        if record.get("record") != GUI_CAPTURE_RECORD:
            continue
        key = record.get("catalogKey")
        spid = record.get("attributedSpid")
        effect = effects.get(str(spid)) if spid else None
        entry: dict[str, Any] = {
            "key": key,
            "catalogKey": key,
            "slideIndex": record.get("slideIndex"),
            "guiPath": record.get("guiPath"),
            "matchedTitle": record.get("matchedTitle"),
            "shapeName": record.get("shapeName"),
            "shapeSpid": record.get("shapeSpid"),
            "attributedSpid": spid,
            "selectionRowIndex": record.get("selectionRowIndex"),
            "selectedBy": record.get("selectedBy"),
            "ribbonReadBack": record.get("ribbonReadBack"),
            "rejected": bool(record.get("rejected")),
            "capturedAt": record.get("capturedAt"),
        }
        if record.get("rejected"):
            entry["error"] = record.get("error")
            unresolved.append({"key": key, "reason": "the driver rejected this target"})
        elif effect is None:
            unresolved.append(
                {"key": key, "reason": f"the package carries no preset effect targeting spid {spid!r}"}
            )
        elif "ambiguous" in effect:
            unresolved.append({"key": key, "reason": effect["ambiguous"]})
        else:
            entry["effect"] = effect
        merged.append(entry)
    merged.sort(key=lambda entry: str(entry["key"]))
    unresolved.sort(key=lambda row: str(row["key"]))
    return {
        "source": GUI_CAPTURE_SOURCE,
        "application": BASELINE_APPLICATION,
        "version": BASELINE_VERSION,
        "capturedAt": GUI_CAPTURE_DATE,
        "driver": GUI_CAPTURE_DRIVER,
        "package": GUI_CAPTURE_PACKAGE,
        "readBack": GUI_CAPTURE_READBACK,
        "captureRecords": len(merged),
        "effectsInPackage": len(effects),
        "resolved": sum(1 for entry in merged if "effect" in entry),
        "unresolved": unresolved,
        "captures": merged,
    }


def analyse_gui_capture(out_dir: Path) -> int:
    """Analyse a GUI capture directory and print the merged evidence."""
    package = out_dir / GUI_CAPTURE_PACKAGE
    readback = out_dir / GUI_CAPTURE_READBACK
    if not package.exists():
        print(f"FAIL: no captured package at {package}", file=sys.stderr)
        return 1
    if not readback.exists():
        print(f"FAIL: no read-back at {readback}", file=sys.stderr)
        return 1
    effects = parse_gui_capture_package(package)
    records = read_oracle_readback(readback)
    print(json.dumps(merge_gui_capture(records, effects), indent=2, ensure_ascii=False))
    return 0


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
    parser.add_argument("--parse-gui-capture", type=Path, metavar="DIR",
                        help="analyse a saved GUI capture directory offline and print the merged evidence")
    parser.add_argument("--sdef", type=Path, default=DEFAULT_SDEF)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--oracle", type=Path, default=DEFAULT_ORACLE)
    parser.add_argument("--require-sdef", action="store_true", help="fail when the local sdef is unavailable")
    args = parser.parse_args(argv)
    if (not args.check and not args.write and args.parse_oracle is None
            and args.parse_gui_capture is None):
        parser.error("pass --check, --write, --parse-oracle or --parse-gui-capture")

    if args.parse_oracle is not None:
        return analyse_oracle_output(args.parse_oracle)

    if args.parse_gui_capture is not None:
        return analyse_gui_capture(args.parse_gui_capture)

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
