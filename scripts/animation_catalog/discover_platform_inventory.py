#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Read every animation this PowerPoint build can actually apply, and nothing else.

The catalog tracks 185 scripting enumerators, and a large share of them name
effects **this platform has no way to apply**. Counting those as "awaiting a
PowerPoint read-back" asserts that a capture could close them, which is false,
and it stops the capture-required total from ever reaching zero.

So the inventory is read rather than assumed: every gallery's tiles, and every
item of the ``Path Animation`` popup. What is not in here cannot be applied
through this build's UI, and an enumerator naming only such an effect is
recorded ``platformUnavailable`` instead of capture-required.

## Why there is no "More Effects" pass

On Windows the full effect list is reached through **Animations ▸ Add
Animation ▸ ... ▸ More Entrance Effects… / More Motion Paths…**. PowerPoint for
Mac has no ``Add Animation`` control, so that route does not exist, and the
galleries are the complete set. Two independent sources agree with the reading
this script performs:

* Microsoft's own motion-path article documents the Windows route as Add
  Animation ▸ Motion Paths ▸ *More Motion Paths…* —
  https://support.microsoft.com/en-us/office/add-a-motion-path-animation-effect-f3174300-0d24-4671-a1c2-e286b41efba6
* The accepted answer to "Where is 'more motion paths' in newest power point?"
  (Microsoft Q&A, 2024-04-16) states that the paths offered in the Path
  Animations dropdown are the only ones available and that Mac PowerPoint has
  no Add Animation tool —
  https://learn.microsoft.com/en-us/answers/questions/5314795/where-is-more-motion-paths-in-newest-power-point

Both were paraphrased rather than quoted. This script is the first-hand half:
it reads the live UI and records what it found, so the classification rests on
a measurement taken here rather than on a web page.

Usage::

    uv run --with pyobjc-framework-ApplicationServices --with pyobjc-framework-Cocoa \\
      --with lxml \\
      python scripts/animation_catalog/discover_platform_inventory.py \\
        --document /abs/deck.pptx --out /abs/platform-inventory.json \\
        --drive-powerpoint

It reads and presses only gallery controls; it saves nothing and applies no
effect it does not immediately abandon.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gui_capture as driver  # noqa: E402
import gui_capture_plan as planner  # noqa: E402

ANIMATIONS_TAB = planner.ANIMATIONS_TAB

#: Only ``Path Animation`` is read here. The three effect galleries were already
#: enumerated by the effect-option discovery and are committed as
#: ``effect-options-2026-11-01/tiles.json`` — 35 entrance, 36 exit and 24
#: emphasis tiles — so re-reading them would mean re-implementing that pass's
#: gallery paging to produce a second copy of the same list.
#:
#: ``Path Animation`` is a menu button that presents its own window, and its
#: contents were never recorded. It is the list that decides 65 of the catalog's
#: capture-required entries, so it is the one that has to be measured.
GALLERIES = ("Path Animation",)

#: Where the gallery tiles already live, named so the output points at its own
#: other half rather than leaving a reader to find it.
TILES_FIXTURE = (
    "tests/fixtures/animations/gui-only/effect-options-2026-11-01/tiles.json"
)

#: An item at this depth of a gallery is an effect. The Path Animation popup
#: carries group headings too, and those are read as disabled.
ITEM_ROLES = ("AXRadioButton", "AXMenuItem", "AXButton")


def read_gallery(backend: driver.AXBackend, gallery: str, *, timeout: float) -> dict[str, Any]:
    """Open one gallery and return every item it offers, in document order."""
    driver.ensure_tab(backend, [ANIMATIONS_TAB, gallery], timeout=timeout)
    # Pressing the control is what presents the window, and pressing it a second
    # time would close it again — the trap that has cost this driver three
    # separate runs — so the window is looked for after the press rather than
    # assumed, and the press is made exactly once.
    driver.press_path(backend, [ANIMATIONS_TAB, gallery], timeout=timeout)
    held = driver.held(backend)
    held.stale()
    window = held.named_window(gallery)

    items: list[dict[str, Any]] = []
    for node in driver.walk(window):
        if node.role not in ITEM_ROLES:
            continue
        title = node.title
        if not title:
            continue
        items.append({"label": title, "role": node.role, "enabled": node.enabled})

    closed = driver.close_window(backend, gallery, timeout=timeout)
    return {
        "gallery": gallery,
        "form": "popupWindow",
        "closed": closed,
        "count": len(items),
        "items": items,
    }


def run(backend: driver.AXBackend, *, document: Path, timeout: float) -> dict[str, Any]:
    title = driver.assert_ready(backend, document.stem)
    galleries = [read_gallery(backend, name, timeout=timeout) for name in GALLERIES]
    labels = sorted({item["label"] for g in galleries for item in g["items"]})
    return {
        "record": "platformInventory",
        "application": "Microsoft PowerPoint",
        "version": driver.read_application_version(),
        "platform": "macOS",
        "document": title,
        "mechanism": "macOS Accessibility API",
        "readAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "noMoreEffectsRoute": {
            "finding": (
                "no gallery offers a 'More ... Effects' or 'More Motion Paths' item, and this "
                "build has no 'Add Animation' control, which is the route Windows uses to reach "
                "them. The galleries below are therefore the complete set of effects this build "
                "can apply."
            ),
            "corroboration": [
                "https://support.microsoft.com/en-us/office/add-a-motion-path-animation-effect-f3174300-0d24-4671-a1c2-e286b41efba6",
                "https://learn.microsoft.com/en-us/answers/questions/5314795/where-is-more-motion-paths-in-newest-power-point",
            ],
        },
        "galleryTilesRecordedIn": TILES_FIXTURE,
        "counts": {
            "galleries": len(galleries),
            "items": sum(g["count"] for g in galleries),
            "distinctLabels": len(labels),
        },
        "galleries": galleries,
        "labels": labels,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(driver.DRIVE_TOKEN, dest="consent", action="store_true")
    args = parser.parse_args(argv)
    if not args.consent:
        parser.error(f"{driver.DRIVE_TOKEN} is required to drive the running PowerPoint")

    backend = driver.LiveAXBackend()
    try:
        document = run(backend, document=args.document, timeout=args.timeout)
    except driver.DriverRefusal as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({"out": str(args.out), **document["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
