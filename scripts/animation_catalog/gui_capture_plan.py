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
    one slide each.
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

## The deck

``--build-deck`` writes an sdpm deck with one slide per target, one named shape, and the
target key as visible text, then ``--generate`` builds it through ``sdpm.api.generate``
with **both motion switches off** so sdpm contributes no motion of its own and every
``p:timing`` tree in the saved package came from PowerPoint.

Usage::

    uv run python scripts/animation_catalog/gui_capture_plan.py --emit-plan \\
      --out /abs/out/plan.json --build-deck /abs/out/deck --generate /abs/out/capture-deck.pptx
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = REPO_ROOT / "sdpm" / "references" / "catalogs"
DEFAULT_CATALOG = CATALOG_DIR / "powerpoint-animation-catalog.json"
DEFAULT_MANIFEST = CATALOG_DIR / "powerpoint-gui-surface-16.113.1.json"
DEFAULT_TEMPLATE = REPO_ROOT / "sdpm" / "templates" / "blank-dark.pptx"

#: The driver this plan feeds.
DRIVER = "scripts/animation_catalog/gui_capture.py"

#: The element id the deck gives the shape to click. sdpm names the *shape* itself from
#: its geometry rather than from this id, so the name the driver looks up is read back out
#: of the generated package by :func:`resolve_shape_name` instead of being assumed here.
SHAPE_ELEMENT_ID = "target"

#: The geometry preset of that shape, which is how it is identified in the package.
SHAPE_PRESET = "roundRect"

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


# --- the plan ---------------------------------------------------------------
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

    for index, target in enumerate(targets, start=1):
        target["slideIndex"] = index

    return {
        "plan": "sdpm animation GUI capture",
        "driver": DRIVER,
        # Filled in by --generate from the package sdpm actually wrote, because sdpm
        # derives a shape's name from its geometry rather than from the element id.
        "shapeName": None,
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
def slide_json(target: dict[str, Any]) -> dict[str, Any]:
    """One slide: one named shape to click, and the target key as visible text.

    The shape's name is what the driver looks up in the package to compute its click
    point, and the visible key is what lets a saved slide be read back against the target
    it was meant for rather than against its position in a list.
    """
    index = target["slideIndex"]
    return {
        "layout": "Blank",
        "elements": [
            {
                "id": SHAPE_ELEMENT_ID,
                "type": "shape",
                "shape": "rounded_rectangle",
                "text": f"{index:03d}",
                "x": 120,
                "y": 300,
                "width": 320,
                "height": 160,
                "fontSize": 40,
            },
            {
                "id": "label",
                "type": "textbox",
                "text": target["key"],
                "x": 120,
                "y": 120,
                "width": 1040,
                "height": 70,
                "fontSize": 24,
            },
            {
                "id": "howto",
                "type": "textbox",
                "text": " > ".join(target["guiPath"]),
                "x": 120,
                "y": 200,
                "width": 1040,
                "height": 60,
                "fontSize": 16,
            },
        ],
    }


def build_capture_deck(plan: dict[str, Any], deck_dir: Path, *, template: Path = DEFAULT_TEMPLATE) -> Path:
    """Write the sdpm deck source for a plan: one slide per target, in plan order."""
    targets = plan.get("targets", [])
    if not targets:
        raise ValueError("the plan has no targets, so there is no deck to build")
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
    for target in targets:
        slug = f"t{target['slideIndex']:03d}"
        outline.append(f"- [{slug}] {target['slideIndex']:03d} {target['key']}")
        (deck_dir / "slides" / f"{slug}.json").write_text(
            json.dumps(slide_json(target), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
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


def resolve_shape_name(package: Path, *, preset: str = SHAPE_PRESET) -> str:
    """Read the name sdpm gave the target shape, from the package it actually wrote.

    The driver clicks a point computed from this shape, so the name has to be the one in
    the file rather than the element id the deck JSON asked for. Requiring exactly one
    such shape per slide, with one name across every slide, is what makes the click point
    attributable: two candidates would mean the driver could compute a point for the
    wrong shape and the record would still name the right target.
    """
    import zipfile

    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    names: dict[str, list[int]] = {}
    slide_part = re.compile(r"ppt/slides/slide(\d+)\.xml")
    with zipfile.ZipFile(package) as archive:
        parts = sorted(
            ((int(match.group(1)), match.group(0)) for match in map(slide_part.fullmatch, archive.namelist()) if match)
        )
        if not parts:
            raise ValueError(f"{package} has no slide parts")
        for index, part in parts:
            root = etree.fromstring(archive.read(part), parser=parser)
            found = [
                name
                for shape in root.iter()
                if etree.QName(shape).localname == "sp"
                and any(
                    etree.QName(el).localname == "prstGeom" and el.get("prst") == preset for el in shape.iter()
                )
                for name in (
                    next(
                        (
                            el.get("name")
                            for el in shape.iter()
                            if etree.QName(el).localname == "cNvPr" and el.get("name")
                        ),
                        None,
                    ),
                )
                if name
            ]
            if len(found) != 1:
                raise ValueError(f"slide {index} has {len(found)} {preset} shapes, expected exactly one: {found}")
            names.setdefault(found[0], []).append(index)
    if len(names) != 1:
        raise ValueError(f"the {preset} shape is not named consistently across slides: { {k: len(v) for k, v in names.items()} }")
    return next(iter(names))


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


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not any((args.emit_plan, args.build_deck, args.generate, args.summary)):
        build_parser().error("pass --emit-plan, --summary, --build-deck or --generate")

    try:
        plan = build_plan(load_json(args.catalog), load_json(args.manifest))
    except (OSError, ValueError, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    report: dict[str, Any] = {"counts": plan["counts"]}
    if args.build_deck:
        build_capture_deck(plan, args.build_deck, template=args.template)
        report["deck"] = str(args.build_deck)
    if args.generate:
        if not args.build_deck:
            print("FAIL: --generate needs --build-deck", file=sys.stderr)
            return 1
        result = generate_capture_deck(args.build_deck, args.generate)
        # Read the shape name back out of the package before the plan is written, so the
        # plan the driver reads names the shape the file actually carries.
        plan["shapeName"] = resolve_shape_name(Path(result["output_path"]))
        report["package"] = result["output_path"]
        report["slideCount"] = result["slide_count"]
        report["shapeName"] = plan["shapeName"]
        warnings = result.get("warnings") or []
        if warnings:
            # A capture deck is deliberately lopsided — the shape sits low so the key is
            # readable above it — so the layout warnings repeat once per slide. Reported
            # as a count plus the distinct kinds, which is the part worth reading.
            report["warningCount"] = len(warnings)
            report["distinctWarnings"] = sorted({re.sub(r"^page\d+ ", "", text) for text in warnings})
    # Written last: --generate is what settles ``shapeName``.
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
