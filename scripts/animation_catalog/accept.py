#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Catalog-derived acceptance harness for PowerPoint animations and transitions.

This is the REQ-9 release gate. It has two halves and they are deliberately
unequal in size:

* **The deterministic half runs by default and offline.** It derives the
  coverage matrix from the checked-in catalog, writes every accepted catalog
  fragment with the real writer, re-imports it with the real reader, checks the
  package-validity invariants REQ-6.2 names, and runs the acceptance fixtures in
  ``tests/fixtures/animations/manifest.json``.
* **The PowerPoint half runs only with ``--powerpoint``.** It reads an actually
  saved package back through Apple Events and detects the repair prompt. This
  sandbox cannot drive PowerPoint (Task 1 recorded ``-10004``), so that path is
  implemented, strictly non-blocking, and fails fast with remediation text.
  It is never approximated and never reported as a pass it did not earn.

Why the matrix is derived rather than chosen
--------------------------------------------
REQ-9.2 forbids discretionary "representative" fixtures. Every cell in
``tests/fixtures/animations/coverage-matrix.json`` therefore comes from a rule
applied to the catalog: an axis value exists because the catalog contains it,
and the cell's representative entry is the first one in the catalog's own
preference order (gallery capture, then GUI item, then key). Nobody picks the
interesting ones. ``--write-matrix`` regenerates the file byte-identically from
an unchanged catalog, with no wall-clock timestamp, and ``--all`` fails if the
checked-in matrix has drifted from a fresh derivation.

Why it exits non-zero today
---------------------------
The catalog still records mappings whose OOXML form PowerPoint has not been
asked for: 262 capture-required refusals and 71 gallery tiles whose behavior
payload was never captured. The writer refuses them by design rather than
guessing. A harness that printed "OK" while those exist would make the gate
worthless, so every gap is counted, keyed and reported, and the process exits
non-zero while any remains. Zero gaps plus a passing ``--powerpoint`` run is
what closes Task 8.

Usage
-----
Run from the repository root::

    uv run python scripts/animation_catalog/accept.py --all
    uv run python scripts/animation_catalog/accept.py --all --json
    uv run python scripts/animation_catalog/accept.py --write-matrix

The PowerPoint half, on a machine where PowerPoint is drivable and a human is
watching the screen::

    uv run python scripts/animation_catalog/accept.py --all --powerpoint

``--powerpoint`` is itself the consent: nothing in sdpm's runtime, tests or CI
passes it, and no scheduled job may. See ``tests/fixtures/animations/README.md``
for the operator procedure and what the human has to confirm by eye.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from lxml import etree

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sdpm.engine.timing import (  # noqa: E402  (path bootstrap must precede the import)
    CATALOG_TARGET_ID,
    CapabilityEntry,
    CapabilityGapError,
    CapabilityIndex,
    MotionWriteError,
    ShapeIdentityRegistry,
    TimingWriter,
    catalog_coverage,
    coverage_summary,
    load_capability_index,
    validate_catalog,
)
from sdpm.engine.timing.reader import (  # noqa: E402
    read_slide_motion,
    reverse_index,
    select_representation,
    supported_requires,
)
from sdpm.engine.timing.transition import build_transition  # noqa: E402

DEFAULT_CATALOG = REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
FIXTURE_DIR = REPO_ROOT / "tests/fixtures/animations"
DEFAULT_MATRIX = FIXTURE_DIR / "coverage-matrix.json"
DEFAULT_MANIFEST = FIXTURE_DIR / "manifest.json"
DEFAULT_TEMPLATE = REPO_ROOT / "sdpm/templates/blank-dark.pptx"

MATRIX_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = 1

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
P15_NS = "http://schemas.microsoft.com/office/powerpoint/2012/main"
P159_NS = "http://schemas.microsoft.com/office/powerpoint/2015/09/main"
#: The prefixes a fixture assertion may use in its XPath.
NS = {
    "p": P_NS,
    "a": A_NS,
    "mc": MC_NS,
    "r": R_NS,
    "p14": P14_NS,
    "p15": P15_NS,
    "p159": P159_NS,
}

#: ``CT_Slide`` child order (ECMA-376 Part 1). ``mc:AlternateContent`` stands in
#: for whichever element it wraps, so it is resolved before the comparison.
SLIDE_CHILD_ORDER = ("cSld", "clrMapOvr", "transition", "timing", "extLst")
#: ``CT_SlideTiming`` child order.
TIMING_CHILD_ORDER = ("tnLst", "bldLst", "extLst")
#: Elements whose ``@spid`` the reader recognises as a shape reference.
SPID_OWNERS = ("spTgt", "bldP", "bldGraphic", "bldDgm", "bldOleChart")

#: Timing values the writer treats as "nothing to persist". The reader omits
#: them, so normalized equality has to drop them on the expected side too
#: rather than call a neutral default a round-trip loss.
NEUTRAL_TIMING = {
    "repeatCount": 1,
    "repeatDurationMs": None,
    "autoReverse": False,
    "acceleration": 0,
    "deceleration": 0,
    "rewind": False,
    "smoothStart": False,
    "smoothEnd": False,
    "bounceEnd": 0,
    "restart": "always",
}

#: A detached catalog slide: one shape, so every fragment has an ``spid`` to
#: resolve, and a ``p:cSld/p:spTree`` so the reader's identity scan works.
CATALOG_SLIDE_XML = (
    '<p:sld xmlns:p="%s" xmlns:a="%s"><p:cSld><p:spTree>'
    '<p:sp><p:nvSpPr><p:cNvPr id="2" name="catalog target"/><p:cNvSpPr/><p:nvPr/>'
    "</p:nvSpPr></p:sp></p:spTree></p:cSld></p:sld>" % (P_NS, A_NS)
)

#: Hard ceiling on any Apple Event. A GUI process that does not answer inside
#: this window is treated as unavailable; the harness never waits on a window.
OSASCRIPT_TIMEOUT_SECONDS = 20.0
POWERPOINT_BUNDLE_ID = "com.microsoft.Powerpoint"
POWERPOINT_APP = Path("/Applications/Microsoft PowerPoint.app")

APPLE_EVENT_REMEDIATION = (
    "Run this on a logged-in macOS desktop session where Microsoft PowerPoint "
    "16.113.1 is installed and the terminal application holds the Automation "
    "and Accessibility permissions for it "
    "(System Settings -> Privacy & Security -> Automation / Accessibility). "
    "A headless, SSH or sandboxed session cannot deliver Apple Events and "
    "reports -10004."
)


# ---------------------------------------------------------------------------
# Result plumbing
# ---------------------------------------------------------------------------
@dataclass
class Check:
    """One named acceptance check and what it proved."""

    id: str
    requirement: str
    status: str  # "passed" | "failed" | "blockedOnPowerPoint"
    detail: str = ""
    findings: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "requirement": self.requirement,
            "status": self.status,
            "detail": self.detail,
        }
        if self.findings:
            payload["findings"] = list(self.findings)
        if self.data:
            payload["data"] = self.data
        return payload


def _passed(check_id: str, requirement: str, detail: str, **data: Any) -> Check:
    return Check(check_id, requirement, "passed", detail, data=data)


def _failed(check_id: str, requirement: str, detail: str, findings: Sequence[str], **data: Any) -> Check:
    return Check(check_id, requirement, "failed", detail, tuple(findings), data=data)


# ---------------------------------------------------------------------------
# Catalog access
# ---------------------------------------------------------------------------
def load_catalog_document(path: Path) -> dict[str, Any]:
    """Load and structurally validate the checked-in catalog."""
    return validate_catalog(json.loads(path.read_text(encoding="utf-8")))


def digest(payload: bytes) -> str:
    """Return the stable content digest used in every provenance block."""
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def repo_path(path: Path) -> str:
    """Render a path relative to the repository when it lives inside it."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def accepted_entries(catalog: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    """Return ``(group, entry)`` for every accepted catalog fragment."""
    rows: list[tuple[str, Mapping[str, Any]]] = []
    for group in ("guiItems", "candidates"):
        for entry in catalog.get(group) or ():
            if entry.get("status") == "accepted":
                rows.append((group, entry))
    return rows


def gui_key_of(group: str, entry: Mapping[str, Any]) -> str:
    """Return the GUI-surface key an entry belongs to.

    A GUI item *is* its own key; a scripting candidate names the GUI item it was
    assigned to. Both sides therefore collapse onto the same family, which is
    what lets one axis value own entries from both arrays.
    """
    return str(entry["key"] if group == "guiItems" else entry.get("guiKey") or entry["key"])


#: GUI-key segments that name a control group rather than a single value, so the
#: family is three segments deep instead of two.
_DEEP_FAMILIES = frozenset({"gallery", "moreEffects", "effectOptions", "textOptions", "behavior"})


def family_of(group: str, entry: Mapping[str, Any]) -> str:
    """Return the catalog-derived family path of one entry."""
    parts = gui_key_of(group, entry).split(".")
    if len(parts) >= 3 and parts[1] in _DEEP_FAMILIES:
        return ".".join(parts[:3])
    return ".".join(parts[:2])


def preference(group: str, entry: Mapping[str, Any]) -> tuple[int, int, str]:
    """Deterministic representative order, mirroring the reader's own rule.

    ``sdpm.engine.timing.reader._preference`` prefers a captured gallery tile
    over an enum candidate that merely corroborates the same mapping. Using the
    same order here means the matrix names the catalog key that actually owns a
    form in both directions, instead of a second key describing it.
    """
    ooxml = entry.get("ooxml") or {}
    return (
        0 if "galleryTile" in ooxml else 1,
        0 if group == "guiItems" else 1,
        str(entry["key"]),
    )


def catalog_establishes_form(entry: Mapping[str, Any]) -> bool:
    """True when the catalog establishes an OOXML element form for an entry.

    This is deliberately a property of the *catalog alone* —
    ``status == accepted`` with no ``ooxml.gap`` and no ``ooxml.requiresCapture``
    — so the checked-in matrix never encodes writer state and cannot drift when
    the writer changes. :class:`CapabilityEntry` owns the rule, so there is one
    definition of it rather than a copy.

    Whether the writer can *also* fill in a preset's behavior payload is a
    second, finer gate that lives in the writer
    (:func:`sdpm.engine.timing.writer.preset_payload_gaps`). The harness
    discovers it by running the writer, which is where that truth belongs; the
    matrix only records what the catalog itself claims.
    """
    probe = CapabilityEntry(
        key=str(entry["key"]),
        status=str(entry.get("status")),
        level=str(entry.get("capabilityLevel") or ""),
        ooxml=entry.get("ooxml") or {},
        semantic=entry.get("semanticJson") or {},
        group="guiItems",
    )
    return probe.writable


# ---------------------------------------------------------------------------
# Coverage matrix derivation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Cell:
    """One coverage-matrix cell: an axis value and the entries that own it."""

    id: str
    axis: str
    value: str
    members: tuple[tuple[str, Mapping[str, Any]], ...]
    covered_by: tuple[str, ...] = ()
    note: str = ""

    def representative(self) -> tuple[str, Mapping[str, Any]] | None:
        ordered = sorted(self.members, key=lambda row: preference(*row))
        return ordered[0] if ordered else None

    def established_representative(self) -> tuple[str, Mapping[str, Any]] | None:
        """Return the first member whose OOXML form the catalog establishes."""
        ordered = sorted(
            (row for row in self.members if catalog_establishes_form(row[1])),
            key=lambda row: preference(*row),
        )
        return ordered[0] if ordered else None

    def as_json(self) -> dict[str, Any]:
        rep = self.representative()
        established = self.established_representative()
        payload: dict[str, Any] = {
            "id": self.id,
            "axis": self.axis,
            "value": self.value,
            "catalogKey": None if rep is None else str(rep[1]["key"]),
            "catalogGroup": None if rep is None else rep[0],
            "status": "notInCatalog" if rep is None else str(rep[1].get("status")),
            "capabilityLevel": None if rep is None else (rep[1].get("capabilityLevel") or None),
            "verification": None if rep is None else (rep[1].get("verification") or None),
            "members": len(self.members),
            "formEstablishedMembers": sum(1 for row in self.members if catalog_establishes_form(row[1])),
            "formEstablishedCatalogKey": None if established is None else str(established[1]["key"]),
        }
        if self.covered_by:
            payload["coveredBy"] = list(self.covered_by)
        if self.note:
            payload["note"] = self.note
        return payload


def _numeric_paths(catalog: Mapping[str, Any]) -> dict[str, dict[float, list[tuple[str, Mapping[str, Any]]]]]:
    """Collect every numeric semantic-JSON path and the values the catalog pins.

    Boundary classes have to come from the catalog too, so the observed value
    set *is* the domain: its minimum, its most frequent value and its maximum
    are the minimum/normal/maximum classes REQ-9.2 asks for. Where the catalog
    pins only one value the three classes collapse onto one fixture, and the
    matrix says so rather than implying a range nobody established.
    """
    paths: dict[str, dict[float, list[tuple[str, Mapping[str, Any]]]]] = {}

    def walk(node: Any, prefix: str, row: tuple[str, Mapping[str, Any]]) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                walk(value, f"{prefix}.{key}", row)
        elif isinstance(node, list):
            for value in node:
                walk(value, f"{prefix}[]", row)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            paths.setdefault(prefix.lstrip("."), {}).setdefault(float(node), []).append(row)

    for group, entry in accepted_entries(catalog):
        walk(entry.get("semanticJson") or {}, "", (group, entry))
    return paths


def _group(rows: Iterable[tuple[str, Mapping[str, Any]]], key: Callable[[str, Mapping[str, Any]], str | None]):
    buckets: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for group, entry in rows:
        value = key(group, entry)
        if value is not None:
            buckets.setdefault(value, []).append((group, entry))
    return buckets


def _first_effect(entry: Mapping[str, Any]) -> Mapping[str, Any] | None:
    animations = (entry.get("semanticJson") or {}).get("animations")
    if not isinstance(animations, Mapping):
        return None
    sequence = animations.get("mainSequence")
    if isinstance(sequence, list) and sequence and isinstance(sequence[0], Mapping):
        return sequence[0]
    return None


#: Build elements, by the target family they address.
_BUILD_ELEMENT_FAMILIES = {
    "p:bldGraphic": "chart",
    "p:bldOleChart": "chart",
    "p:bldDgm": "smartArt",
    "p:bldP": "buildLevel",
}


def _target_family(group: str, entry: Mapping[str, Any]) -> str | None:
    """Classify an entry by the kind of thing it animates.

    The classification follows what the entry *is about* — its semantic payload
    and the build element its OOXML mapping names — not an incidental side
    effect. Nearly every gallery tile records ``ooxml.buildList`` because
    PowerPoint writes ``p:bldP/@animBg`` beside it, but a tile still animates a
    shape; treating that as a paragraph-build target would empty the shape cell
    and overfill the build cell.
    """
    effect = _first_effect(entry)
    if effect is None:
        return None
    element = str((entry.get("ooxml") or {}).get("element") or "")
    target = effect.get("target") or {}
    if "chart" in effect or _BUILD_ELEMENT_FAMILIES.get(element) == "chart":
        return "chart"
    if "smartArt" in effect or _BUILD_ELEMENT_FAMILIES.get(element) == "smartArt":
        return "smartArt"
    if isinstance(target, Mapping) and "paragraphRange" in target:
        return "paragraphRange"
    if "text" in effect or _BUILD_ELEMENT_FAMILIES.get(element) == "buildLevel":
        return "buildLevel"
    preset = effect.get("preset") or {}
    if isinstance(preset, Mapping) and preset.get("category") == "media":
        return "media"
    return "shape"


def build_matrix(catalog: Mapping[str, Any], index: CapabilityIndex, *, catalog_digest: str) -> dict[str, Any]:
    """Derive the whole coverage matrix from the checked-in catalog."""
    rows = accepted_entries(catalog)
    supported = [str(row["requires"]) for row in catalog["alternateContent"].get("supported") or () if row.get("requires")]

    def namespace_value(group: str, entry: Mapping[str, Any]) -> str:
        ooxml = entry.get("ooxml") or {}
        if not ooxml.get("alternateContent"):
            return "direct"
        requires = ooxml.get("requires")
        return f"choice:{requires}" if requires in supported else "choice:standard"

    def fallback_value(group: str, entry: Mapping[str, Any]) -> str | None:
        ooxml = entry.get("ooxml") or {}
        if not ooxml.get("alternateContent") or not ooxml.get("fallbackElement"):
            return None
        requires = ooxml.get("requires")
        return f"fallback:{requires}" if requires in supported else "fallback:standard"

    def transition_effect(group: str, entry: Mapping[str, Any]) -> str | None:
        transition = (entry.get("semanticJson") or {}).get("transition")
        return str(transition["effect"]) if isinstance(transition, Mapping) else None

    def transition_parameters(group: str, entry: Mapping[str, Any]) -> str | None:
        transition = (entry.get("semanticJson") or {}).get("transition")
        if not isinstance(transition, Mapping):
            return None
        keys = sorted(transition.get("parameters") or {})
        return "+".join(keys) if keys else "none"

    def animation_category(group: str, entry: Mapping[str, Any]) -> str | None:
        effect = _first_effect(entry)
        if effect is None:
            return None
        preset = effect.get("preset")
        if isinstance(preset, Mapping):
            return str(preset.get("category"))
        return "custom" if "behaviors" in effect else None

    def animation_variant(group: str, entry: Mapping[str, Any]) -> str | None:
        effect = _first_effect(entry)
        if effect is None:
            return None
        preset = effect.get("preset")
        if not isinstance(preset, Mapping):
            return None
        options = preset.get("options")
        if isinstance(options, Mapping) and options:
            return ",".join(f"{setting}={value}" for setting, value in sorted(options.items()))
        return "none"

    cells: list[Cell] = []

    def add(axis: str, buckets: Mapping[str, list[tuple[str, Mapping[str, Any]]]]) -> None:
        for value in sorted(buckets):
            cells.append(Cell(f"{axis}:{value}", axis, value, tuple(buckets[value])))

    add("mapping", _group(rows, lambda g, e: str((e.get("ooxml") or {}).get("strategy") or "") or None))
    add("namespace", _group(rows, namespace_value))
    add("namespace", _group(rows, fallback_value))
    add("animationCategory", _group(rows, animation_category))
    add("animationFamily", _group(rows, lambda g, e: family_of(g, e) if gui_key_of(g, e).startswith("animation.") else None))
    add("transitionEffect", _group(rows, transition_effect))
    add("transitionParameters", _group(rows, transition_parameters))
    add("animationVariant", _group(rows, animation_variant))
    add("targetFamily", _group(rows, _target_family))

    # The placeholder target family is a builder distinction, not a catalog
    # one: every catalog fragment animates the same synthetic shape. The axis
    # value still has to exist, so it is declared here with no catalog key and
    # an explicit owning fixture instead of being quietly dropped.
    cells.append(
        Cell(
            "targetFamily:placeholder",
            "targetFamily",
            "placeholder",
            (),
            covered_by=("fixture:placeholder-target",),
            note=(
                "the catalog's fragments all animate one synthetic shape, so no catalog entry "
                "distinguishes a layout placeholder; the acceptance fixture does"
            ),
        )
    )

    for path, values in sorted(_numeric_paths(catalog).items()):
        ordered = sorted(values)
        modal = max(ordered, key=lambda value: (len(values[value]), -value))
        classes = {"minimum": ordered[0], "normal": modal, "maximum": ordered[-1]}
        for boundary, value in classes.items():
            rendered = int(value) if float(value).is_integer() else value
            cells.append(
                Cell(
                    f"boundary:{path}:{boundary}",
                    "boundary",
                    f"{path}:{boundary}",
                    tuple(values[value]),
                    note=(
                        f"catalog-pinned value {rendered}; the catalog establishes "
                        f"{len(ordered)} distinct value(s) for this path"
                    ),
                )
            )

    axes: dict[str, int] = {}
    for cell in cells:
        axes[cell.axis] = axes.get(cell.axis, 0) + 1

    return {
        "schemaVersion": MATRIX_SCHEMA_VERSION,
        "derivation": {
            "rule": (
                "every cell is produced by a rule applied to the checked-in catalog; no entry is "
                "selected by hand (REQ-9.2). An axis value exists because the catalog contains it, "
                "and each cell's representative is the first member in the catalog's own preference "
                "order (captured gallery tile, then GUI item, then key)."
            ),
            "representativeOrder": ["galleryTileCaptured", "guiItemBeforeCandidate", "keyAscending"],
            "formEstablished": (
                "catalog-derived: accepted status with no ooxml.gap and no ooxml.requiresCapture. It "
                "records what the catalog itself claims and never encodes writer state, so this file "
                "cannot drift when the writer changes. Whether a preset's behavior payload is also "
                "captured is a finer gate the harness discovers by running the writer."
            ),
            "boundaryClasses": (
                "minimum and maximum are the smallest and largest value the catalog pins for a "
                "numeric semantic-JSON path; normal is the most frequently pinned value, ties "
                "resolved to the smaller. A path with one pinned value collapses all three classes "
                "onto one fixture and says so in the cell note."
            ),
            "reproducible": (
                "derived only from the catalog bytes named below, with no wall-clock timestamp, so "
                "two runs over an unchanged catalog are byte-identical."
            ),
        },
        "source": {
            "catalog": repo_path(DEFAULT_CATALOG),
            "catalogDigest": catalog_digest,
            "catalogGeneratedAt": catalog["baseline"]["generatedAt"],
            "guiManifest": catalog["baseline"]["guiManifest"],
            "baseline": {
                "application": catalog["baseline"]["application"],
                "version": catalog["baseline"]["version"],
                "platform": catalog["baseline"]["platform"],
            },
            "supportedChoiceRequires": supported,
            "acceptedEntries": len(rows),
        },
        "axes": {name: axes[name] for name in sorted(axes)},
        "cellCount": len(cells),
        "cells": [cell.as_json() for cell in sorted(cells, key=lambda cell: (cell.axis, cell.value))],
    }


def dump_matrix(matrix: Mapping[str, Any]) -> str:
    """Serialize the matrix deterministically."""
    return json.dumps(matrix, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def matrix_cells(matrix: Mapping[str, Any], index: CapabilityIndex, catalog: Mapping[str, Any]) -> list[Cell]:
    """Rebuild :class:`Cell` objects for a matrix document, for walking."""
    by_key = {str(entry["key"]): (group, entry) for group, entry in accepted_entries(catalog)}
    cells: list[Cell] = []
    for raw in matrix.get("cells") or ():
        members: list[tuple[str, Mapping[str, Any]]] = []
        for name in (raw.get("catalogKey"), raw.get("formEstablishedCatalogKey")):
            if name and name in by_key and by_key[name] not in members:
                members.append(by_key[name])
        cells.append(
            Cell(
                str(raw["id"]),
                str(raw["axis"]),
                str(raw["value"]),
                tuple(members),
                covered_by=tuple(raw.get("coveredBy") or ()),
                note=str(raw.get("note") or ""),
            )
        )
    return cells


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def normalize(value: Any) -> Any:
    """Drop nulls and sort keys so two semantic trees compare structurally."""
    if isinstance(value, Mapping):
        return {key: normalize(item) for key, item in sorted(value.items()) if item is not None}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return value


def normalize_effect(effect: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one animation effect for equality.

    Timing values the writer persists nothing for are removed from both sides:
    the reader cannot invent ``autoReverse: false`` from XML that never carried
    it, and calling that a round-trip loss would be noise. Everything else is
    compared as written.
    """
    pruned = dict(effect)
    timing = {
        key: item
        for key, item in (effect.get("timing") or {}).items()
        if not (key in NEUTRAL_TIMING and item == NEUTRAL_TIMING[key])
    }
    pruned["timing"] = timing
    return normalize(pruned)


def effect_diff(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[str]:
    """Return the JSON paths where two normalized effects disagree."""
    left, right = normalize_effect(expected), normalize_effect(actual)
    findings: list[str] = []
    for key in sorted(set(left) | set(right)):
        if left.get(key) == right.get(key):
            continue
        if key == "timing":
            for inner in sorted(set(left.get("timing", {})) | set(right.get("timing", {}))):
                if left.get("timing", {}).get(inner) != right.get("timing", {}).get(inner):
                    findings.append(
                        f"timing.{inner}: wrote {left.get('timing', {}).get(inner)!r}, "
                        f"read {right.get('timing', {}).get(inner)!r}"
                    )
        else:
            findings.append(f"{key}: wrote {left.get(key)!r}, read {right.get(key)!r}")
    return findings


# ---------------------------------------------------------------------------
# Package-validity invariants (REQ-6.2)
# ---------------------------------------------------------------------------
def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def active_branch(node: etree._Element) -> etree._Element:
    """Return the branch a conforming consumer actually applies.

    Uniqueness and ordering hold *within one active timing branch*: an
    ``mc:Fallback`` legitimately repeats the IDs of the Choice it replaces,
    because only one of them is ever live.
    """
    if _local(node) != "AlternateContent":
        return node
    for child in node:
        if isinstance(child.tag, str) and _local(child) == "Choice":
            return child
    return node


def timing_findings(fragment: etree._Element, *, known_spids: Sequence[int], what: str) -> list[str]:
    """Check unique cTn IDs, schema child order, spid validity and rIds."""
    findings: list[str] = []
    branch = active_branch(fragment)

    ids = branch.xpath(".//p:cTn/@id", namespaces=NS)
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    if duplicates:
        findings.append(f"{what}: duplicate p:cTn/@id in the active branch: {duplicates}")
    if not ids:
        findings.append(f"{what}: the timing tree carries no p:cTn")
    non_numeric = [value for value in ids if not str(value).isdigit()]
    if non_numeric:
        findings.append(f"{what}: non-numeric p:cTn/@id {non_numeric}")

    for timing in branch.iter(f"{{{P_NS}}}timing"):
        order = [_local(child) for child in timing if isinstance(child.tag, str)]
        ranks = [TIMING_CHILD_ORDER.index(name) for name in order if name in TIMING_CHILD_ORDER]
        unknown = [name for name in order if name not in TIMING_CHILD_ORDER]
        if unknown:
            findings.append(f"{what}: p:timing carries unexpected children {unknown}")
        if ranks != sorted(ranks):
            findings.append(f"{what}: p:timing children are out of schema order: {order}")
        if not timing.xpath("./p:tnLst/p:par/p:cTn[@nodeType='tmRoot']", namespaces=NS):
            findings.append(f"{what}: p:timing has no p:cTn[@nodeType='tmRoot']")

    allowed = set(known_spids)
    for owner in SPID_OWNERS:
        for value in branch.xpath(f".//p:{owner}/@spid", namespaces=NS):
            if not str(value).isdigit():
                findings.append(f"{what}: p:{owner}/@spid {value!r} is not a shape id")
            elif int(value) not in allowed:
                findings.append(f"{what}: p:{owner}/@spid {value} resolves to no shape in the slide")

    for node in branch.iter():
        if not isinstance(node.tag, str):
            continue
        for name, value in node.attrib.items():
            if name.startswith(f"{{{R_NS}}}") and not str(value).startswith("rId"):
                findings.append(f"{what}: {_local(node)} carries a malformed relationship id {value!r}")
    return findings


def transition_findings(node: etree._Element, entry: Mapping[str, Any], *, what: str) -> list[str]:
    """Check the direct and AlternateContent transition forms."""
    findings: list[str] = []
    ooxml = entry.get("ooxml") or {}
    wrapped = _local(node) == "AlternateContent"
    if bool(ooxml.get("alternateContent")) and not wrapped and ooxml.get("requires"):
        findings.append(f"{what}: catalog requires {ooxml['requires']!r} but the writer emitted a direct p:transition")
    if not wrapped:
        if _local(node) != "transition":
            findings.append(f"{what}: expected p:transition, got {_local(node)}")
        return findings

    choices = node.findall(f"{{{MC_NS}}}Choice")
    fallbacks = node.findall(f"{{{MC_NS}}}Fallback")
    if not choices:
        findings.append(f"{what}: mc:AlternateContent has no mc:Choice")
    for choice in choices:
        if not (choice.get("Requires") or "").split():
            findings.append(f"{what}: mc:Choice without @Requires")
        if not choice.xpath("./p:transition", namespaces=NS):
            findings.append(f"{what}: mc:Choice carries no p:transition")
    expected_fallback = ooxml.get("fallbackElement")
    if expected_fallback:
        if len(fallbacks) != 1:
            findings.append(f"{what}: expected exactly one mc:Fallback, found {len(fallbacks)}")
        else:
            payload = [
                f"p:{_local(child)}"
                for transition in fallbacks[0].xpath("./p:transition", namespaces=NS)
                for child in transition
                if isinstance(child.tag, str)
            ]
            if not fallbacks[0].xpath("./p:transition", namespaces=NS):
                findings.append(f"{what}: mc:Fallback carries no p:transition")
            elif payload and expected_fallback not in payload:
                findings.append(
                    f"{what}: mc:Fallback payload {payload} does not carry the catalog's "
                    f"fallbackElement {expected_fallback!r}"
                )
    return findings


def slide_order_findings(slide: etree._Element, *, what: str) -> list[str]:
    """Check CT_Slide child order, resolving AlternateContent to its payload."""
    ranks: list[int] = []
    order: list[str] = []
    for child in slide:
        if not isinstance(child.tag, str):
            continue
        name = _local(child)
        if name == "AlternateContent":
            payload = {
                _local(inner)
                for branch in child
                for inner in branch
                if isinstance(inner.tag, str)
            }
            name = next((item for item in SLIDE_CHILD_ORDER if item in payload), name)
        order.append(name)
        if name in SLIDE_CHILD_ORDER:
            ranks.append(SLIDE_CHILD_ORDER.index(name))
    if ranks != sorted(ranks):
        return [f"{what}: slide children are out of CT_Slide order: {order}"]
    return []


# ---------------------------------------------------------------------------
# Catalog slide helpers
# ---------------------------------------------------------------------------
def catalog_slide() -> tuple[etree._Element, ShapeIdentityRegistry, list[int]]:
    """Return a detached catalog slide, its registry and its shape ids."""
    slide = etree.fromstring(CATALOG_SLIDE_XML)
    shape = slide.find(f"{{{P_NS}}}cSld/{{{P_NS}}}spTree/{{{P_NS}}}sp")
    registry = ShapeIdentityRegistry("catalog")
    registry.register(CATALOG_TARGET_ID, [shape], source_path="catalog")
    spids = [int(value) for value in slide.xpath(".//p:cNvPr/@id", namespaces=NS)]
    return slide, registry, spids


@dataclass
class EntryOutcome:
    """What one accepted catalog entry did through writer and reader."""

    key: str
    group: str
    kind: str
    outcome: str  # "generated" | "refused" | "error"
    reversible: bool = False
    equal: bool = False
    gap: str = ""
    elements: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()
    diff: tuple[str, ...] = ()


def walk_entry(
    group: str,
    entry: Mapping[str, Any],
    *,
    index: CapabilityIndex,
    reversible_transitions: Mapping[str, Any],
    reversible_presets: Mapping[str, Any],
) -> EntryOutcome:
    """Write one catalog entry, re-import it, and record exactly what happened."""
    key = str(entry["key"])
    semantic = entry.get("semanticJson") or {}
    transition = semantic.get("transition")
    kind = "transition" if isinstance(transition, Mapping) else "animation"
    slide, registry, spids = catalog_slide()
    try:
        if kind == "transition":
            node, _report = build_transition(transition, index=index, slide_slug="catalog")
        else:
            node = TimingWriter(registry, index=index, slide_slug="catalog").build(semantic.get("animations"))
    except CapabilityGapError as error:
        return EntryOutcome(key, group, kind, "refused", gap=str(error), elements=tuple(error.elements))
    except MotionWriteError as error:
        return EntryOutcome(key, group, kind, "error", findings=(str(error),))

    slide.append(node)
    findings: list[str] = list(slide_order_findings(slide, what=key))
    if kind == "transition":
        findings += transition_findings(node, entry, what=key)
    else:
        findings += timing_findings(node, known_spids=spids, what=key)

    outcome = EntryOutcome(key, group, kind, "generated", findings=tuple(findings))
    try:
        motion = read_slide_motion(slide, slide_slug="catalog", index=index)
    except Exception as error:  # noqa: BLE001  - any reader failure is a finding, not a crash
        outcome.findings = outcome.findings + (f"{key}: the reader raised {type(error).__name__}: {error}",)
        return outcome

    # Reversibility is **measured**, not looked up. It used to be membership in
    # the reader's reverse index, and that index maps each OOXML form to exactly
    # one preferred key — so every other key describing the same form was
    # counted one-way even when its own example round-tripped perfectly. 143 of
    # the 210 did. The property that matters is `JSON -> PPTX -> the same JSON`,
    # and which catalog key the reader resolved on the way is not part of it.
    if kind == "transition":
        expected, actual = normalize(transition), normalize(motion.transition or {})
        outcome.equal = expected == actual
        outcome.reversible = outcome.equal or key in reversible_transitions
        if outcome.reversible and not outcome.equal:
            outcome.diff = (f"transition: wrote {expected!r}, read {actual!r}",)
        return outcome

    written_sequence = (semantic.get("animations") or {}).get("mainSequence") or []
    if not written_sequence:
        # An entry whose example animates nothing — an interactive-sequence or
        # pane-ordering record. There is no effect to compare, so reversibility
        # stays whatever the index says.
        outcome.reversible = key in reversible_presets
        return outcome
    expected_effect = written_sequence[0]
    read_sequence = (motion.animations or {}).get("mainSequence") or []
    if not read_sequence:
        # Nothing came back, so there is nothing to compare. Claimed reversible
        # only if the index says this key is the form's inverse target, which
        # makes the empty read a reportable failure rather than a silent pass.
        outcome.reversible = key in reversible_presets
        if outcome.reversible:
            outcome.diff = (f"{key}: the reader returned no mainSequence effect",)
        return outcome
    diff = effect_diff(expected_effect, read_sequence[0])
    outcome.equal = not diff
    outcome.reversible = outcome.equal or key in reversible_presets
    outcome.diff = tuple(diff)
    return outcome


# ---------------------------------------------------------------------------
# Acceptance fixtures
# ---------------------------------------------------------------------------
def load_fixture_manifest(path: Path) -> dict[str, Any]:
    """Load the acceptance fixture index."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1:
        raise ValueError(f"{path}: schemaVersion must be 1")
    if not isinstance(manifest.get("packages"), list) or not manifest["packages"]:
        raise ValueError(f"{path}: packages must be a non-empty array")
    seen: set[str] = set()
    for package in manifest["packages"]:
        for required in ("id", "purpose", "requirement", "deck", "slides", "covers", "proves", "powerPointReadBack"):
            if required not in package:
                raise ValueError(f"{path}: package {package.get('id')!r} is missing {required!r}")
        if package["id"] in seen:
            raise ValueError(f"{path}: duplicate package id {package['id']!r}")
        seen.add(package["id"])
    return manifest


def build_fixture_package(package: Mapping[str, Any], out_dir: Path, *, template: Path) -> Path:
    """Build one acceptance fixture into a real .pptx on disk."""
    from sdpm.engine.builder import PPTXBuilder

    media_dir = out_dir / f"{package['id']}-media"
    media_dir.mkdir(parents=True, exist_ok=True)
    for name in package.get("media") or ():
        # A tiny but structurally plausible MP4 header: python-pptx only needs
        # bytes plus a content type to create the media part and its timing.
        (media_dir / name).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 128)

    deck = package["deck"]
    builder = PPTXBuilder(
        template,
        fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"},
        default_text_color="#FFFFFF",
        base_dir=media_dir,
        animations_enabled=bool(deck.get("animations", {}).get("enabled", False)),
        transitions_enabled=bool(deck.get("transitions", {}).get("enabled", False)),
    )
    for slide_def in package["slides"]:
        builder.add_slide(slide_def)
    target = out_dir / f"{package['id']}.pptx"
    builder.prs.save(str(target))
    return target


def fixture_slides(path: Path) -> list[etree._Element]:
    """Return the slide XML of a built package, in slide order."""
    from pptx import Presentation

    presentation = Presentation(str(path))
    return [etree.fromstring(etree.tostring(slide._element)) for slide in presentation.slides]


def _timing_nodes(slide: etree._Element) -> list[etree._Element]:
    return [
        child
        for child in slide
        if isinstance(child.tag, str)
        and (
            _local(child) == "timing"
            or (
                _local(child) == "AlternateContent"
                and child.xpath(".//p:timing", namespaces=NS)
            )
        )
    ]


def check_fixture(
    package: Mapping[str, Any],
    path: Path,
    *,
    index: CapabilityIndex,
) -> Check:
    """Run one acceptance fixture's offline assertions."""
    findings: list[str] = []
    slides = fixture_slides(path)
    expected = package.get("slideCount")
    if expected is not None and len(slides) != expected:
        findings.append(f"expected {expected} slides, built {len(slides)}")

    supported = supported_requires(index)
    observations: dict[str, Any] = {"slides": len(slides), "package": path.name}

    for position, slide in enumerate(slides, start=1):
        label = f"{package['id']} slide {position}"
        findings += slide_order_findings(slide, what=label)
        timings = _timing_nodes(slide)
        if len(timings) > 1:
            findings.append(f"{label}: {len(timings)} timing representations (python-pptx issue 954)")
        spids = [int(value) for value in slide.xpath(".//p:cNvPr/@id", namespaces=NS)]
        for timing in timings:
            findings += timing_findings(timing, known_spids=spids, what=label)
        try:
            select_representation(slide, "timing", supported=supported)
            select_representation(slide, "transition", supported=supported)
        except Exception as error:  # noqa: BLE001
            findings.append(f"{label}: representation selection failed: {error}")

    for name, assertion in (package.get("assert") or {}).items():
        findings += run_fixture_assertion(name, assertion, slides, observations, label=package["id"])

    if findings:
        return _failed(
            f"fixture:{package['id']}",
            package["requirement"],
            package["purpose"],
            findings,
            **observations,
        )
    return _passed(f"fixture:{package['id']}", package["requirement"], package["purpose"], **observations)


def run_fixture_assertion(
    name: str,
    assertion: Mapping[str, Any],
    slides: Sequence[etree._Element],
    observations: dict[str, Any],
    *,
    label: str,
) -> list[str]:
    """Evaluate one declarative assertion from the fixture manifest.

    Assertions are data in ``manifest.json`` rather than code here, so adding a
    fixture does not mean editing the harness. Each one is an XPath plus the
    count the fixture claims; an unknown assertion kind is a failure, never a
    silent skip.
    """
    index = assertion.get("slide")
    targets = slides if index is None else ([slides[index - 1]] if 0 < index <= len(slides) else [])
    if index is not None and not targets:
        return [f"{label}/{name}: slide {index} does not exist"]

    found = 0
    for slide in targets:
        try:
            found += len(slide.xpath(assertion["xpath"], namespaces=NS))
        except etree.XPathError as error:
            return [f"{label}/{name}: invalid xpath: {error}"]
    observations.setdefault("assertions", {})[name] = found

    if "count" in assertion:
        if found != assertion["count"]:
            return [f"{label}/{name}: expected {assertion['count']} node(s), found {found} ({assertion['xpath']})"]
        return []
    if "minimum" in assertion:
        if found < assertion["minimum"]:
            return [f"{label}/{name}: expected at least {assertion['minimum']} node(s), found {found}"]
        return []
    return [f"{label}/{name}: assertion declares neither 'count' nor 'minimum'"]


def check_identical_timing(packages: Mapping[str, Path], pair: Mapping[str, Any]) -> Check:
    """Prove that switching one feature off leaves the other's XML untouched."""
    left, right = pair["packages"]
    missing = [name for name in (left, right) if name not in packages]
    if missing:
        return _failed(
            f"invariant:{pair['id']}",
            pair["requirement"],
            pair["purpose"],
            [f"fixture package(s) not built: {missing}"],
        )

    def canonical(path: Path) -> list[bytes]:
        # A detached subtree inherits its namespace declarations from an
        # ancestor lxml no longer has, and c14n2 refuses an undeclared prefix.
        # Round-tripping through tostring materializes the declarations.
        return [
            etree.tostring(etree.fromstring(etree.tostring(node)), method="c14n2")
            for slide in fixture_slides(path)
            for node in _timing_nodes(slide)
        ]

    before, after = canonical(packages[left]), canonical(packages[right])
    if before != after:
        return _failed(
            f"invariant:{pair['id']}",
            pair["requirement"],
            pair["purpose"],
            [
                f"{left} produced {len(before)} timing representation(s) and {right} produced "
                f"{len(after)}; the canonical XML differs, so turning the feature off changed timing"
            ],
        )
    return _passed(
        f"invariant:{pair['id']}",
        pair["requirement"],
        pair["purpose"],
        timingRepresentations=len(before),
    )


# ---------------------------------------------------------------------------
# PowerPoint oracle path
# ---------------------------------------------------------------------------
def osascript(script: str) -> tuple[int, str, str]:
    """Run one AppleScript with a hard timeout and no GUI wait.

    ``open -W`` and any other indefinite wait on a GUI process are forbidden
    (notes.md, 2026-10-30 23:49): a blocked tool call is not a verification
    result. Everything here is bounded, and a timeout is reported as a timeout.
    """
    binary = shutil.which("osascript")
    if binary is None:
        return (127, "", "osascript is not on PATH")
    try:
        completed = subprocess.run(  # noqa: S603  - fixed binary, no shell, bounded
            [binary, "-e", script],
            capture_output=True,
            text=True,
            timeout=OSASCRIPT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return (
            124,
            "",
            f"no reply within {OSASCRIPT_TIMEOUT_SECONDS:g}s; a modal dialog (for example the "
            "file-repair prompt) is the usual cause",
        )
    except OSError as error:
        return (126, "", f"cannot launch osascript: {error}")
    return (completed.returncode, completed.stdout.strip(), completed.stderr.strip())


def is_privilege_violation(detail: str) -> bool:
    """True when a failure is the sandbox refusing the Apple Event itself."""
    return "-10004" in detail or "privilege violation" in detail.lower()


def powerpoint_availability() -> dict[str, Any]:
    """Decide, without blocking, whether Apple Events can drive PowerPoint.

    The probe is deliberately a *document-model* event. ``get version`` is
    answered out of the application registry and succeeds even where every
    useful event is refused — this host answers ``get version`` with 16.113.1
    and then fails ``count of documents`` with -10004. Probing the shallow
    property would report "available" and turn every read-back into a spurious
    failure, which is exactly the false result this harness must not produce.
    ``count of documents`` is read-only, opens no window and needs the same
    privilege the read-back needs.
    """
    if sys.platform != "darwin":
        return {
            "available": False,
            "reason": f"platform {sys.platform!r} has no Apple Events",
            "remediation": APPLE_EVENT_REMEDIATION,
        }
    if not POWERPOINT_APP.exists():
        return {
            "available": False,
            "reason": f"{POWERPOINT_APP} is not installed",
            "remediation": APPLE_EVENT_REMEDIATION,
        }
    version_code, version_out, _ = osascript(f'tell application id "{POWERPOINT_BUNDLE_ID}" to get version')
    version = version_out if version_code == 0 else ""
    code, _out, err = osascript(f'tell application id "{POWERPOINT_BUNDLE_ID}" to count of documents')
    if code == 0:
        return {"available": True, "reason": "", "version": version, "probe": "count of documents"}
    detail = err or f"osascript exited {code}"
    if is_privilege_violation(detail):
        detail = (
            "PowerPoint answers static properties"
            + (f" (version {version})" if version else "")
            + " but refuses every document-model Apple Event with -10004 (privilege violation), so "
            "this session cannot open or read back a package"
        )
    return {
        "available": False,
        "reason": detail,
        "remediation": APPLE_EVENT_REMEDIATION,
        "version": version,
        "probe": "count of documents",
    }


def powerpoint_read_back(packages: Mapping[str, Path], manifest: Mapping[str, Any]) -> tuple[dict[str, Any], list[Check]]:
    """Run the PowerPoint half: open a saved package, read it back, close it.

    Nothing here is simulated. When Apple Events are unavailable the function
    returns the reason and every read-back check is reported as
    ``blockedOnPowerPoint`` — an explicit, counted gap, not a pass.
    """
    availability = powerpoint_availability()
    report: dict[str, Any] = {"attempted": True, **availability, "readBack": []}
    checks: list[Check] = []
    expected = [
        package
        for package in manifest["packages"]
        if package.get("powerPointReadBack", {}).get("required")
    ]

    if not availability["available"]:
        for package in expected:
            checks.append(
                Check(
                    f"powerpoint:{package['id']}",
                    package["requirement"],
                    "blockedOnPowerPoint",
                    package["powerPointReadBack"]["expect"],
                    (availability["reason"],),
                    {"package": package["id"], "remediation": availability.get("remediation", "")},
                )
            )
        return report, checks

    for package in expected:
        path = packages.get(package["id"])
        if path is None:
            checks.append(
                _failed(
                    f"powerpoint:{package['id']}",
                    package["requirement"],
                    package["powerPointReadBack"]["expect"],
                    ["the fixture package was not built"],
                )
            )
            continue
        code, out, err = osascript(_read_back_script(path))
        entry = {"package": package["id"], "exit": code, "stdout": out, "stderr": err}
        report["readBack"].append(entry)
        if code == 124:
            # A dialog is the only thing that holds an Apple Event open this
            # long, and the repair prompt is the dialog REQ-9.3 forbids.
            checks.append(
                _failed(
                    f"powerpoint:{package['id']}",
                    package["requirement"],
                    package["powerPointReadBack"]["expect"],
                    [f"repair prompt suspected: {err}"],
                    repairPromptSuspected=True,
                )
            )
            continue
        if code != 0:
            detail = err or f"osascript exited {code}"
            if is_privilege_violation(detail):
                # The sandbox refused the event. That is an environment block,
                # not evidence about the package, and must never be recorded as
                # a package failure.
                checks.append(
                    Check(
                        f"powerpoint:{package['id']}",
                        package["requirement"],
                        "blockedOnPowerPoint",
                        package["powerPointReadBack"]["expect"],
                        (detail,),
                        {"package": package["id"], "remediation": APPLE_EVENT_REMEDIATION},
                    )
                )
            else:
                checks.append(
                    _failed(
                        f"powerpoint:{package['id']}",
                        package["requirement"],
                        package["powerPointReadBack"]["expect"],
                        [detail],
                    )
                )
            continue
        observed = [piece.strip() for piece in out.split("\x1f") if piece.strip()]
        wanted = list(package["powerPointReadBack"].get("transitions") or ())
        if wanted and observed != wanted:
            checks.append(
                _failed(
                    f"powerpoint:{package['id']}",
                    package["requirement"],
                    package["powerPointReadBack"]["expect"],
                    [f"read back {observed}, expected {wanted}"],
                )
            )
            continue
        checks.append(
            Check(
                f"powerpoint:{package['id']}",
                package["requirement"],
                "passed" if not package["powerPointReadBack"].get("humanConfirms") else "blockedOnPowerPoint",
                package["powerPointReadBack"]["expect"],
                ()
                if not package["powerPointReadBack"].get("humanConfirms")
                else (
                    "the remaining claim is visual and only a human watching playback can confirm it: "
                    + "; ".join(package["powerPointReadBack"]["humanConfirms"]),
                ),
                {"package": package["id"], "transitions": observed},
            )
        )
    return report, checks


def _read_back_script(path: Path) -> str:
    """Return the AppleScript that opens, reads back and closes one package.

    It never activates PowerPoint, never saves, and closes without saving, so a
    read-back cannot mutate the fixture. The unit separator joins the per-slide
    values because AppleScript list text is locale-dependent.
    """
    quoted = str(path).replace("\\", "\\\\").replace('"', '\\"')
    return (
        f'tell application id "{POWERPOINT_BUNDLE_ID}"\n'
        f'  set theDoc to open "{quoted}"\n'
        "  set readings to {}\n"
        "  repeat with theSlide in (slides of theDoc)\n"
        "    set end of readings to (entry effect of slide show transition of theSlide) as text\n"
        "  end repeat\n"
        '  set AppleScript\'s text item delimiters to (ASCII character 31)\n'
        "  set result to readings as text\n"
        "  close theDoc saving no\n"
        "  return result\n"
        "end tell"
    )


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
def run_acceptance(
    *,
    catalog_path: Path,
    matrix_path: Path,
    manifest_path: Path,
    template: Path,
    use_powerpoint: bool,
    out_dir: Path | None,
) -> dict[str, Any]:
    """Run the deterministic half, optionally the PowerPoint half, and report."""
    catalog_bytes = catalog_path.read_bytes()
    catalog = load_catalog_document(catalog_path)
    catalog_digest = digest(catalog_bytes)
    index = load_capability_index(catalog_path)
    checks: list[Check] = []

    # --- the matrix is derived, and the checked-in copy must match ---------
    derived = build_matrix(catalog, index, catalog_digest=catalog_digest)
    derived_text = dump_matrix(derived)
    if matrix_path.exists():
        checked_in = matrix_path.read_text(encoding="utf-8")
        if checked_in == derived_text:
            checks.append(
                _passed(
                    "matrix:derivation",
                    "REQ-9.2",
                    "the checked-in coverage matrix is byte-identical to a fresh derivation from the catalog",
                    cells=derived["cellCount"],
                )
            )
        else:
            checks.append(
                _failed(
                    "matrix:derivation",
                    "REQ-9.2",
                    "the checked-in coverage matrix has drifted from the catalog",
                    ["run: uv run python scripts/animation_catalog/accept.py --write-matrix"],
                )
            )
        matrix = json.loads(checked_in)
    else:
        checks.append(
            _failed(
                "matrix:derivation",
                "REQ-9.2",
                "the coverage matrix is missing",
                [f"{matrix_path} does not exist; run --write-matrix"],
            )
        )
        matrix = derived

    # --- every accepted catalog entry, through writer and reader -----------
    reverse = reverse_index(index)
    reversible_transitions = {entry.key: entry for entry in reverse.transitions.values()}
    reversible_presets = {entry.key: entry for entry in reverse.presets.values()}
    outcomes: dict[str, EntryOutcome] = {}
    for group, entry in accepted_entries(catalog):
        outcomes[str(entry["key"])] = walk_entry(
            group,
            entry,
            index=index,
            reversible_transitions=reversible_transitions,
            reversible_presets=reversible_presets,
        )

    structural = [finding for outcome in outcomes.values() for finding in outcome.findings]
    if structural:
        checks.append(
            _failed(
                "package:validity",
                "REQ-6.2",
                "every generated fragment must carry unique cTn ids, schema child order and resolvable spids/rIds",
                structural[:40],
                totalFindings=len(structural),
            )
        )
    else:
        checks.append(
            _passed(
                "package:validity",
                "REQ-6.2",
                "every generated fragment carries unique cTn ids, schema child order and resolvable spids/rIds",
                fragments=sum(1 for outcome in outcomes.values() if outcome.outcome == "generated"),
            )
        )

    reversible = [outcome for outcome in outcomes.values() if outcome.reversible]
    unequal = [outcome for outcome in reversible if not outcome.equal]
    if unequal:
        checks.append(
            _failed(
                "roundTrip:normalizedEquality",
                "REQ-5.1",
                "JSON -> PPTX -> JSON must preserve normalized semantic values for every invertible "
                "entry; a loss here is a disagreement between the catalog's semanticJson and the "
                "OOXML its own ooxml block records, not a reader defect",
                [f"{outcome.key}: {'; '.join(outcome.diff)}" for outcome in unequal],
                invertibleEntries=len(reversible),
            )
        )
    else:
        checks.append(
            _passed(
                "roundTrip:normalizedEquality",
                "REQ-5.1",
                "every invertible catalog entry survives JSON -> PPTX -> JSON unchanged",
                invertibleEntries=len(reversible),
                transitions=sum(1 for outcome in reversible if outcome.kind == "transition"),
                presets=sum(1 for outcome in reversible if outcome.kind == "animation"),
            )
        )

    writer_errors = [outcome for outcome in outcomes.values() if outcome.outcome == "error"]
    if writer_errors:
        checks.append(
            _failed(
                "writer:noUnexpectedFailure",
                "REQ-6.4",
                "a catalog entry must either generate or raise a deterministic capability refusal",
                [f"{outcome.key}: {'; '.join(outcome.findings)}" for outcome in writer_errors],
            )
        )
    else:
        checks.append(
            _passed(
                "writer:noUnexpectedFailure",
                "REQ-6.4",
                "every accepted entry either generated or refused deterministically",
                entries=len(outcomes),
            )
        )

    # --- walk every coverage-matrix cell ----------------------------------
    cells = matrix_cells(matrix, index, catalog)
    cell_report: list[dict[str, Any]] = []
    for cell in cells:
        established = cell.established_representative()
        if established is not None:
            key = str(established[1]["key"])
            outcome = outcomes.get(key)
            if outcome is None:
                state, detail = "failed", "the representative entry is not in the accepted catalog"
            elif outcome.findings:
                state, detail = "failed", "; ".join(outcome.findings[:3])
            elif outcome.outcome == "refused":
                # The catalog establishes the element form, but the writer still
                # refuses: the remaining gap is the behavior payload.
                state, detail = "blockedOnCapture", outcome.gap
            elif outcome.outcome != "generated":
                state, detail = "failed", f"the entry neither generated nor refused: {outcome.outcome}"
            elif outcome.reversible and not outcome.equal:
                state, detail = "failed", "; ".join(outcome.diff[:3])
            elif outcome.reversible:
                state, detail = "verified", "generated and read back to equal semantic JSON"
            else:
                state, detail = "oneWay", "generated, but the catalog records no inverse mapping yet"
            cell_report.append({"cell": cell.id, "state": state, "catalogKey": key, "detail": detail})
            continue
        if cell.covered_by:
            owners = [check for check in checks if check.id in cell.covered_by]
            cell_report.append(
                {
                    "cell": cell.id,
                    "state": "fixture",
                    "catalogKey": None,
                    "detail": "covered by " + ", ".join(cell.covered_by),
                    "fixtures": list(cell.covered_by),
                    "fixtureStatus": [check.status for check in owners] or ["pending"],
                }
            )
            continue
        rep = cell.representative()
        outcome = outcomes.get(str(rep[1]["key"])) if rep else None
        cell_report.append(
            {
                "cell": cell.id,
                "state": "blockedOnCapture",
                "catalogKey": None if rep is None else str(rep[1]["key"]),
                "detail": (outcome.gap if outcome and outcome.gap else "no catalog member establishes an OOXML form"),
            }
        )

    # --- acceptance fixtures ---------------------------------------------
    manifest = load_fixture_manifest(manifest_path)
    scratch = out_dir or Path(tempfile.mkdtemp(prefix="sdpm-accept-"))
    scratch.mkdir(parents=True, exist_ok=True)
    packages: dict[str, Path] = {}
    fixture_checks: list[Check] = []
    for package in manifest["packages"]:
        try:
            packages[package["id"]] = build_fixture_package(package, scratch, template=template)
        except Exception as error:  # noqa: BLE001
            fixture_checks.append(
                _failed(
                    f"fixture:{package['id']}",
                    package["requirement"],
                    package["purpose"],
                    [f"building the package raised {type(error).__name__}: {error}"],
                )
            )
            continue
        fixture_checks.append(check_fixture(package, packages[package["id"]], index=index))
    for pair in manifest.get("invariants") or ():
        fixture_checks.append(check_identical_timing(packages, pair))
    checks += fixture_checks

    # Cells owned by a fixture are resolved once the fixture checks exist.
    by_id = {check.id: check for check in checks}
    for row in cell_report:
        if row["state"] != "fixture":
            continue
        statuses = [by_id[name].status for name in row.get("fixtures", ()) if name in by_id]
        row["fixtureStatus"] = statuses or ["missing"]
        if statuses and all(status == "passed" for status in statuses):
            row["state"] = "verified"
        elif "failed" in statuses or not statuses:
            row["state"] = "failed"
        else:
            row["state"] = "blockedOnPowerPoint"

    # --- the gaps ---------------------------------------------------------
    records = catalog_coverage(index, catalog=catalog)
    writer_summary = coverage_summary(records)
    # Split off the entries no capture can ever close. They are tracked so the
    # sdef enumeration is accounted for, but counting them as "awaiting a
    # PowerPoint read-back" asserts something their own recorded gap denies —
    # and it means the capture-required total can never reach zero, so it stops
    # being a measure of progress.
    no_sdpm_input = sorted(
        record.key for record in records if record.outcome == "refused" and record.no_sdpm_input
    )
    capture_required = sorted(
        record.key
        for record in records
        if record.outcome == "refused" and not record.elements and not record.no_sdpm_input
    )
    payload_gaps = sorted(
        (
            {"key": record.key, "group": record.group, "elements": list(record.elements)}
            for record in records
            if record.outcome == "refused" and record.elements
        ),
        key=lambda row: row["key"],
    )
    gallery_payload_gaps = [row for row in payload_gaps if row["group"] == "guiItems"]
    one_way = sorted(
        outcome.key
        for outcome in outcomes.values()
        if outcome.outcome == "generated" and not outcome.reversible
    )
    partial = [
        {"key": outcome.key, "paths": list(outcome.diff)}
        for outcome in sorted(outcomes.values(), key=lambda item: item.key)
        if outcome.reversible and not outcome.equal
    ]
    degenerate = [
        row["id"]
        for row in matrix.get("cells") or ()
        if row["axis"] == "boundary" and "1 distinct value(s)" in str(row.get("note", ""))
    ]

    gaps = {
        "captureRequired": {
            "count": len(capture_required),
            "meaning": "accepted catalog mappings whose OOXML element form PowerPoint has not been asked for",
            "closes": "PowerPoint read-back (--powerpoint) recording the element and attributes for each key",
            "keys": capture_required,
        },
        "noSdpmInput": {
            "count": len(no_sdpm_input),
            "meaning": (
                "enumerators tracked for sdef coverage that no sdpm JSON can ask for, so no "
                "capture closes them. The 45 MsoAnimDirection names are these: a direction is "
                "measured per effect and written as preset.options.direction, and the enumerator "
                "name does not identify a presetSubtype — 33 of the 45 are not offered by any "
                "gallery tile, and the same label means different subtypes on different effects"
            ),
            "closes": "nothing; these are recorded as out of the input vocabulary, not as a gap",
            "keys": no_sdpm_input,
        },
        "behaviorPayloads": {
            "count": len(gallery_payload_gaps),
            "meaning": (
                "gallery tiles whose behavior children were captured but whose payload values "
                "(coordinates, colour, scale, angle, animated attribute) were not"
            ),
            "closes": "PowerPoint read-back capturing each behavior node's payload",
            "entries": gallery_payload_gaps,
            "mirroredCandidates": len(payload_gaps) - len(gallery_payload_gaps),
            "allEntries": payload_gaps,
        },
        "oneWayOnly": {
            "count": len(one_way),
            "meaning": (
                "entries the writer emits but the catalog records no inverse mapping for, so "
                "PPTX -> JSON keeps them raw instead of semantic"
            ),
            "closes": "the same read-back: a captured presetSubtype/attribute domain makes the form invertible",
            "keys": one_way,
        },
        "partialRoundTrip": {
            "count": len(partial),
            "meaning": "invertible entries that lost a semantic field between write and read",
            "entries": partial,
        },
    }

    powerpoint: dict[str, Any] = {
        "attempted": False,
        "available": False,
        "reason": "not requested; pass --powerpoint on a machine where PowerPoint is drivable",
        "readBack": [],
    }
    if use_powerpoint:
        powerpoint, powerpoint_checks = powerpoint_read_back(packages, manifest)
        checks += powerpoint_checks

    blockers: list[str] = []
    for check in checks:
        if check.status == "failed":
            blockers.append(f"check {check.id} failed")
        elif check.status == "blockedOnPowerPoint":
            blockers.append(f"check {check.id} is blocked on PowerPoint")
    # ``noSdpmInput`` is deliberately not a blocker: it counts entries nothing
    # can close, so gating on it would make the gate unpassable by design.
    for name in ("captureRequired", "behaviorPayloads", "oneWayOnly", "partialRoundTrip"):
        if gaps[name]["count"]:
            blockers.append(f"{gaps[name]['count']} {name} gap(s) remain")
    if not use_powerpoint:
        blockers.append("the PowerPoint oracle half has not run (REQ-9.3 is unproven without --powerpoint)")

    cell_states: dict[str, int] = {}
    for row in cell_report:
        cell_states[row["state"]] = cell_states.get(row["state"], 0) + 1

    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "harness": repo_path(Path(__file__)),
        "mode": {"all": True, "powerPoint": use_powerpoint, "offline": not use_powerpoint},
        "catalog": {
            "path": repo_path(catalog_path),
            "digest": catalog_digest,
            "generatedAt": catalog["baseline"]["generatedAt"],
            "guiManifest": catalog["baseline"]["guiManifest"],
            "acceptedEntries": len(outcomes),
        },
        "matrix": {
            "path": repo_path(matrix_path),
            "digest": digest(derived_text.encode("utf-8")),
            "cellCount": len(cells),
            "axes": matrix.get("axes", {}),
            "states": cell_states,
            "cells": cell_report,
        },
        "writer": writer_summary,
        "roundTrip": {
            "invertibleEntries": len(reversible),
            "equal": sum(1 for outcome in reversible if outcome.equal),
            "transitions": sum(1 for outcome in reversible if outcome.kind == "transition"),
            "presets": sum(1 for outcome in reversible if outcome.kind == "animation"),
        },
        "checks": [check.as_json() for check in checks],
        "gaps": gaps,
        "informational": {
            "boundaryClassesWithOnePinnedValue": degenerate,
            "meaning": (
                "the catalog pins a single value for these numeric paths, so the minimum, normal and "
                "maximum classes share one fixture. Not a release blocker; a note for the read-back."
            ),
        },
        "powerPoint": powerpoint,
        "fixturePackages": {name: path.name for name, path in sorted(packages.items())},
        "gate": {"pass": not blockers, "blockers": blockers},
        "exitCode": 0 if not blockers else 1,
    }


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------
def render(report: Mapping[str, Any]) -> str:
    """Render the report for a human, keys included so the list is actionable."""
    lines: list[str] = []
    catalog = report["catalog"]
    lines.append("PowerPoint animation/transition acceptance")
    lines.append(f"  catalog        {catalog['path']} ({catalog['acceptedEntries']} accepted entries)")
    lines.append(f"  catalog digest {catalog['digest']}")
    lines.append(f"  matrix         {report['matrix']['path']} ({report['matrix']['cellCount']} cells)")
    lines.append(f"  mode           {'offline' if report['mode']['offline'] else 'offline + PowerPoint oracle'}")

    lines.append("")
    lines.append("Coverage matrix cells by state")
    for state, count in sorted(report["matrix"]["states"].items()):
        lines.append(f"  {state:18} {count}")

    lines.append("")
    lines.append("Writer coverage")
    writer = report["writer"]
    lines.append(f"  generated {writer['generated']['total']}  refused {writer['refused']['total']}  "
                 f"total {writer['total']}")
    round_trip = report["roundTrip"]
    lines.append(
        f"  invertible {round_trip['invertibleEntries']} "
        f"(transitions {round_trip['transitions']}, presets {round_trip['presets']}), "
        f"equal {round_trip['equal']}"
    )

    lines.append("")
    lines.append("Checks")
    for check in report["checks"]:
        mark = {"passed": "PASS", "failed": "FAIL", "blockedOnPowerPoint": "BLOCKED"}[check["status"]]
        lines.append(f"  [{mark:7}] {check['id']}  ({check['requirement']})")
        lines.append(f"            {check['detail']}")
        for finding in check.get("findings", []):
            lines.append(f"            - {finding}")

    lines.append("")
    lines.append("Gaps (each key is the stable catalog key that closes it)")
    gaps = report["gaps"]
    lines.append(f"  captureRequired   {gaps['captureRequired']['count']}")
    for key in gaps["captureRequired"]["keys"]:
        lines.append(f"      {key}")
    lines.append(
        f"  behaviorPayloads  {gaps['behaviorPayloads']['count']} gallery tiles "
        f"(+{gaps['behaviorPayloads']['mirroredCandidates']} mirrored enum candidates)"
    )
    for row in gaps["behaviorPayloads"]["entries"]:
        lines.append(f"      {row['key']}  unresolved: {', '.join(row['elements'])}")
    lines.append(f"  oneWayOnly        {gaps['oneWayOnly']['count']}")
    for key in gaps["oneWayOnly"]["keys"]:
        lines.append(f"      {key}")
    lines.append(f"  partialRoundTrip  {gaps['partialRoundTrip']['count']}")
    for row in gaps["partialRoundTrip"]["entries"]:
        lines.append(f"      {row['key']}  {'; '.join(row['paths'])}")

    powerpoint = report["powerPoint"]
    lines.append("")
    lines.append("PowerPoint oracle")
    lines.append(f"  attempted {powerpoint['attempted']}  available {powerpoint['available']}")
    if powerpoint.get("reason"):
        lines.append(f"  reason    {powerpoint['reason']}")
    if powerpoint.get("remediation"):
        lines.append(f"  fix       {powerpoint['remediation']}")

    lines.append("")
    lines.append(f"GATE: {'PASS' if report['gate']['pass'] else 'FAIL'}")
    for blocker in report["gate"]["blockers"]:
        lines.append(f"  - {blocker}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="run the full catalog-derived acceptance sweep")
    parser.add_argument(
        "--powerpoint",
        action="store_true",
        help="also run the PowerPoint read-back half; this flag is the operator's explicit consent",
    )
    parser.add_argument("--write-matrix", action="store_true", help="regenerate the coverage matrix from the catalog")
    parser.add_argument("--json", action="store_true", help="emit the structured report on stdout and nothing else")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--out", type=Path, default=None, help="keep the built fixture packages in this directory")
    args = parser.parse_args(argv)

    if args.write_matrix:
        catalog_bytes = args.catalog.read_bytes()
        catalog = load_catalog_document(args.catalog)
        index = load_capability_index(args.catalog)
        matrix = build_matrix(catalog, index, catalog_digest=digest(catalog_bytes))
        text = dump_matrix(matrix)
        args.matrix.parent.mkdir(parents=True, exist_ok=True)
        args.matrix.write_text(text, encoding="utf-8")
        payload = {
            "wrote": repo_path(args.matrix),
            "cellCount": matrix["cellCount"],
            "axes": matrix["axes"],
            "digest": digest(text.encode("utf-8")),
        }
        print(json.dumps(payload, indent=2))
        return 0

    if not args.all and not args.powerpoint:
        parser.error("pass --all (optionally with --powerpoint), or --write-matrix")

    report = run_acceptance(
        catalog_path=args.catalog,
        matrix_path=args.matrix,
        manifest_path=args.manifest,
        template=args.template,
        use_powerpoint=args.powerpoint,
        out_dir=args.out,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render(report))
    return int(report["exitCode"])


if __name__ == "__main__":
    raise SystemExit(main())
