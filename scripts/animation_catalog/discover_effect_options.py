#!/usr/bin/env python3
"""Read, per gallery tile, the settings its ``Effect Options`` window offers.

A direction persists as ``p:cTn/@presetSubtype`` and 45 of them are open in the
catalog. They cannot be planned from those 45 names, because **the labels are
per effect**: Fly In offers eight compass points, a Wipe four, and an effect
with no direction at all offers none. So this is a discovery pass, and the
capture plan is derived from its output.

It measures **labels, not values**. Nothing is saved and no package is read: the
whole pass is "apply a tile, open its ``Effect Options`` window, read the
titles, close it again". The value behind each label is measured by the capture
run that follows, which saves and reads ``presetSubtype`` per press.

Two mechanics it has to respect, both already paid for elsewhere:

* ``Effect Options`` is **disabled until an effect is selected**, and pressing
  the tile is what selects one. Measured the same way ``Duration:`` was.
* Pressing ``Effect Options`` while its window is open **closes** it — the trap
  that has now cost three different runs (an active ribbon tab, the Selection
  Pane, a gallery's palette). So the window's presence is read, never assumed.

Usage::

    uv run --with pyobjc-framework-ApplicationServices --with pyobjc-framework-Cocoa \\
      --with lxml \\
      python scripts/animation_catalog/discover_effect_options.py \\
        --tiles /abs/tiles.json --document /abs/capture-deck.pptx \\
        --shape 'Rounded Rectangle 73' --out /abs/effect-options.json \\
        --drive-powerpoint

It needs no focus: PowerPoint may stay behind whatever the operator is doing.
Resumable — a tile already in ``--out`` is skipped unless ``--force``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gui_capture as driver  # noqa: E402
import gui_capture_plan as planner  # noqa: E402

#: The ribbon control that opens the window, and the window's own title.
EFFECT_OPTIONS = "Effect Options"

#: How deep inside the window a value can sit. The measured shape is shallow —
#: window ▸ group ▸ value — and a bound means a window shaped differently fails
#: loudly instead of being walked to the bottom.
MAX_WINDOW_DEPTH = 6


def read_effect_options(backend: driver.AXBackend, *, timeout: float) -> list[dict[str, Any]]:
    """Return every titled element of the open window, in document order.

    **It records and does not interpret**, and that is the lesson of two wrong
    readings. The first took the window as a flat list of titles and treated a
    title from a hardcoded set as a group heading; Fly In looked perfect
    (``Direction`` then eight compass points) and Spin reported **79
    directions**, because its window also carries an ``Amount`` group and a
    whole colour picker. The second grouped by the nearest titled ancestor, and
    the window turned out to be **flat**: ``Direction``, its values,
    ``Sequence`` and its values are all siblings, so everything landed in one
    bucket.

    What separates a heading from a value is neither the title nor the depth.
    Measured on Fly In and Spin, it is the pair ``(role, enabled)`` at depth 2:

    =========================  ====================================
    ``AXMenuButton`` disabled  a **heading**: ``Direction``, ``Amount``
    ``AXMenuButton`` enabled   a **value**: ``From Bottom``, ``Clockwise``
    ``AXGroup`` at depth 2     the colour picker, whose 71 disabled
                               ``AXRadioButton`` children sit at depth 3+
    =========================  ====================================

    All of it is recorded per element anyway, and the grouping is derived
    **offline** — where a wrong guess costs a re-read of a JSON file rather than
    another half-hour pass over 95 tiles, which is what the first two cost.
    """
    window = driver.wait_until(
        backend,
        lambda: driver.find_window(backend, EFFECT_OPTIONS),
        timeout=timeout,
        what=f"the {EFFECT_OPTIONS!r} window to open",
    )
    elements: list[dict[str, Any]] = []
    stack: list[tuple[Any, int]] = [(window, 0)]
    while stack:
        node, depth = stack.pop()
        title = node.title
        if title and depth:
            elements.append(
                {
                    "title": title,
                    "role": node.role,
                    "enabled": node.enabled,
                    "selected": node.selected,
                    "depth": depth,
                }
            )
        if depth >= MAX_WINDOW_DEPTH:
            continue
        stack.extend((child, depth + 1) for child in reversed(list(node.children)))
    return elements


def set_effect_options_open(backend: driver.AXBackend, *, want: bool, timeout: float) -> None:
    """Open or close the window by pressing the ribbon control, reading first.

    The control toggles, so its effect depends on a state that must be read.
    Pressing it blind is how the last target of the 76-value run failed.
    """
    view = driver.held(backend)
    for _ in range(2):
        view.stale()
        is_open = driver.find_window(view, EFFECT_OPTIONS) is not None
        if is_open == want:
            return
        control = driver._resolve_in(  # noqa: SLF001 - same package
            driver.resolve_scope(view, driver.RIBBON_SCOPE), EFFECT_OPTIONS
        )
        if not control.enabled:
            raise driver.ControlNotFound(
                f"{EFFECT_OPTIONS!r} is disabled, so no effect is selected"
            )
        control.press()
        view.stale()
        driver.wait_until(
            view,
            lambda: (driver.find_window(view, EFFECT_OPTIONS) is not None) == want,
            timeout=timeout,
            swallow=(),
            what=f"the {EFFECT_OPTIONS!r} window to be {'open' if want else 'closed'}",
        )
        return
    raise driver.ControlNotFound(f"could not get {EFFECT_OPTIONS!r} to {'open' if want else 'close'}")


def discover_tile(
    backend: driver.AXBackend,
    gallery: str,
    tile: dict[str, Any],
    *,
    shape: str,
    document: Path,
    timeout: float,
) -> dict[str, Any]:
    """Apply one tile and record what its ``Effect Options`` window offers."""
    record: dict[str, Any] = {
        "key": tile["key"],
        "gallery": gallery,
        "label": tile["label"],
        "elements": [],
        "error": None,
    }
    try:
        row_index, row_count = driver.shape_row_index(document, 1, shape)
        driver.select_shape(
            backend, shape, row_index=row_index, row_count=row_count, timeout=timeout
        )
        driver.ensure_tab(backend, [planner.ANIMATIONS_TAB, gallery], timeout=timeout)
        # The window must be shut before the tile is pressed: it belongs to the
        # previous effect, and an open one would be read again as this tile's.
        try:
            set_effect_options_open(backend, want=False, timeout=timeout)
        except driver.ControlNotFound:
            pass
        result = driver.press_path(
            backend, [planner.ANIMATIONS_TAB, gallery, tile["label"]], timeout=timeout
        )
        record["matchedTitle"] = result.matched_title
        set_effect_options_open(backend, want=True, timeout=timeout)
        record["elements"] = read_effect_options(backend, timeout=timeout)
        set_effect_options_open(backend, want=False, timeout=timeout)
    except driver.TargetFailure as exc:
        record["error"] = exc.as_error()
    return record


def run(
    tiles: dict[str, list[dict[str, Any]]],
    *,
    shape: str,
    document: Path,
    out: Path,
    timeout: float,
    force: bool,
    backend: driver.AXBackend,
) -> dict[str, Any]:
    """Walk every tile, writing the read-back incrementally."""
    done: dict[str, dict[str, Any]] = {}
    if out.exists() and not force:
        done = {
            record["key"]: record
            for record in json.loads(out.read_text(encoding="utf-8")).get("tiles", [])
        }
    title = driver.assert_ready(backend, document.stem)
    driver.open_selection_pane(backend, timeout=timeout)

    records = list(done.values())
    planned = sum(len(items) for items in tiles.values())
    for gallery, items in sorted(tiles.items()):
        for tile in items:
            if tile["key"] in done:
                continue
            record = discover_tile(
                driver.held(backend), gallery, tile,
                shape=shape, document=document, timeout=timeout,
            )
            records.append(record)
            titles = [e["title"] for e in record["elements"]]
            print(
                f"{len(records)}/{planned} {tile['key']}: "
                f"{len(titles)} titled element(s)"
                + (f" ERROR {record['error']['kind']}" if record["error"] else ""),
                file=sys.stderr,
            )
            summary = {
                "document": title,
                "shape": shape,
                "planned": planned,
                "read": len(records),
                "withElements": sum(1 for r in records if r["elements"]),
                "failed": sum(1 for r in records if r["error"]),
                "tiles": sorted(records, key=lambda r: r["key"]),
            }
            out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return json.loads(out.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tiles", type=Path, required=True)
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--shape", required=True, help="the shape every tile is applied to")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--force", action="store_true", help="re-read tiles already recorded")
    parser.add_argument(driver.DRIVE_TOKEN, dest="consent", action="store_true")
    args = parser.parse_args(argv)
    if not args.consent:
        print(
            f"FAIL: refusing to drive PowerPoint without {driver.DRIVE_TOKEN}",
            file=sys.stderr,
        )
        return 2
    tiles = json.loads(args.tiles.read_text(encoding="utf-8"))
    try:
        summary = run(
            tiles,
            shape=args.shape,
            document=args.document,
            out=args.out,
            timeout=args.timeout,
            force=args.force,
            backend=driver.LiveAXBackend(),
        )
    except driver.DriverRefusal as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in summary.items() if k != "tiles"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
