#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Derive the capture plan for every effect-option value the discovery pass found.

``discover_effect_options.py`` recorded, per gallery tile, every titled element
of its ``Effect Options`` window. This turns that into targets the capture
driver can run, and it is a separate step on purpose: the discovery records and
does not interpret, so the grouping rule lives here where getting it wrong
costs a re-read of a JSON file rather than another half-hour pass over 95 tiles.

## The grouping rule, measured

At depth 2 inside the window, an ``AXMenuButton`` that is **disabled** is a
heading (``Direction``, ``Amount``, ``Spokes``) and an **enabled** one is a
value under the heading before it. The colour picker is an ``AXGroup`` whose 71
disabled radio buttons sit at depth 3 and deeper, so depth alone excludes it.

``Sequence`` is skipped. Its three values are the text-unit setting, which is
already writable and is not an effect option in the sense this plan captures.

## Each target is two presses

A value is only reachable once an effect is applied — ``Effect Options`` reads
``enabled=False`` until then — so a target carries a ``prerequisite`` path that
presses the tile, and its own path presses the value inside the window the
control opens. The driver supports both; what it needs from here is for the
pair to be named.

Usage::

    uv run python scripts/animation_catalog/effect_options_plan.py \\
      --discovery /abs/effect-options.json --out /abs/plan.json \\
      --build-deck /abs/deck --generate /abs/capture-deck.pptx
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gui_capture_plan as planner  # noqa: E402

#: The ribbon control every target presses to reach its value.
EFFECT_OPTIONS = "Effect Options"

#: Recorded but not captured here: these three are the text-unit setting, which
#: the catalog already writes. Leaving them in would add 95 targets that
#: measure something already measured.
SKIPPED_HEADINGS = ("Sequence",)

#: Only elements at this depth are the effect's own settings. The colour picker
#: lives deeper and is not a setting of the effect.
SETTING_DEPTH = 2
SETTING_ROLE = "AXMenuButton"

PLAN_NAME = "effect-options"


def settings_of(elements: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Return ``heading -> values`` for one tile's window, in document order."""
    groups: dict[str, list[str]] = {}
    heading = ""
    for element in elements:
        if element.get("depth") != SETTING_DEPTH or element.get("role") != SETTING_ROLE:
            continue
        if not element.get("enabled"):
            heading = str(element.get("title"))
            groups.setdefault(heading, [])
            continue
        if heading:
            groups.setdefault(heading, []).append(str(element.get("title")))
    return {name: values for name, values in groups.items() if values}


def slugify(label: str) -> str:
    """Return a camelCase key fragment for a GUI label.

    ``From Bottom-Left`` becomes ``fromBottomLeft``, ``4 Spokes`` becomes
    ``spokes4``: a leading digit cannot start an identifier, so a label that
    begins with one is rotated rather than prefixed with an underscore.
    """
    words = [word for word in label.replace("-", " ").replace("%", " percent").split() if word]
    if words and words[0][0].isdigit():
        words = words[1:] + [words[0]]
    head, *rest = words or [label]
    return head.lower() + "".join(word[:1].upper() + word[1:].lower() for word in rest)


def build_targets(discovery: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one target per (tile, value) pair the discovery recorded."""
    targets: list[dict[str, Any]] = []
    for tile in discovery.get("tiles", []):
        if tile.get("error"):
            continue
        gallery = tile["gallery"]
        label = tile.get("matchedTitle") or tile["label"]
        for heading, values in settings_of(tile.get("elements") or []).items():
            if heading in SKIPPED_HEADINGS:
                continue
            for value in values:
                targets.append(
                    {
                        # The effect's **category and slug**, not the slug alone.
                        # With the slug alone, entrance.blinds and exit.blinds
                        # collapse to one key: 133 targets became 97, and two
                        # targets sharing a key share a shape, which is exactly
                        # the ambiguity the attribution gate exists to refuse.
                        "key": (
                            f"animation.effectOptions.{slugify(heading)}"
                            f".{tile['key'].removeprefix('animation.gallery.')}"
                            f".{slugify(value)}"
                        ),
                        "effectKey": tile["key"],
                        "setting": heading,
                        "value": value,
                        "prerequisite": [planner.ANIMATIONS_TAB, gallery, label],
                        "guiPath": [planner.ANIMATIONS_TAB, EFFECT_OPTIONS, value],
                        "titleAlternatives": [],
                    }
                )
    targets.sort(key=lambda target: target["key"])
    return targets


def build_plan(discovery: dict[str, Any]) -> dict[str, Any]:
    """Return the whole plan, laid out on as few slides as the grid allows."""
    targets = build_targets(discovery)
    grid = planner.assign_cells(targets)
    return {
        "plan": PLAN_NAME,
        "driver": planner.DRIVER,
        "shapeNames": {},
        "deck": grid.as_dict(),
        "generatedFrom": {
            "discovery": discovery.get("readBack") or "effect-options.json",
            "document": discovery.get("document"),
            "tilesRead": discovery.get("read"),
            "selection": (
                "every enabled AXMenuButton at depth 2 of a tile's Effect Options window, "
                f"grouped under the disabled one before it, excluding {', '.join(SKIPPED_HEADINGS)}"
            ),
        },
        "counts": {
            "targets": len(targets),
            "settings": len({target["setting"] for target in targets}),
            "effects": len({target["effectKey"] for target in targets}),
        },
        "targets": targets,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--build-deck", type=Path, help="write the capture deck's JSON here")
    parser.add_argument("--generate", type=Path, help="generate the deck package here")
    args = parser.parse_args(argv)

    discovery = json.loads(args.discovery.read_text(encoding="utf-8"))
    plan = build_plan(discovery)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

    summary: dict[str, Any] = {"plan": str(args.out), **plan["counts"], "deck": plan["deck"]}
    if args.build_deck:
        planner.build_capture_deck(plan, args.build_deck)
        summary["deckJson"] = str(args.build_deck)
    if args.generate:
        if not args.build_deck:
            parser.error("--generate needs --build-deck")
        result = planner.generate_capture_deck(args.build_deck, args.generate)
        package = Path(result["output_path"])
        names = planner.resolve_shape_names(package, plan)
        planner.apply_shape_names(plan, names)
        args.out.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        summary["package"] = str(package)
        summary["shapeNames"] = len(names)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
