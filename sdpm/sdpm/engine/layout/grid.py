# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""CSS Grid based layout coordinate calculator."""

from __future__ import annotations

import re


def compute_grid(spec: dict) -> dict:
    """Compute layout coordinates using CSS Grid track-list syntax.

    Args:
        spec: Grid specification with keys:
            area: {"x", "y", "w", "h"} (required)
            columns: track-list string (default "1fr")
            rows: track-list string (default "1fr")
            gap: str or int — "20" or "20 40" (row-gap col-gap)
            areas: 2D list of names (optional)

    Returns:
        Dict of named rectangles with bb coordinates.
    """
    area = spec["area"]
    ax, ay, aw, ah = area["x"], area["y"], area["w"], area["h"]
    col_str = spec.get("columns", "1fr")
    row_str = spec.get("rows", "1fr")
    areas = spec.get("areas")

    row_gap, col_gap = _parse_gap(spec.get("gap", 0))

    col_sizes = _resolve_tracks(col_str, aw, col_gap)
    row_sizes = _resolve_tracks(row_str, ah, row_gap)

    col_pos = _track_positions(ax, col_sizes, col_gap)
    row_pos = _track_positions(ay, row_sizes, row_gap)

    items = spec.get("items", {})

    if areas:
        result = _map_areas(
            areas, col_pos, col_sizes, row_pos, row_sizes, col_gap, row_gap
        )
    else:
        result = {}
        for r in range(len(row_sizes)):
            for c in range(len(col_sizes)):
                rect = _make_rect(
                    col_pos[c], row_pos[r], col_sizes[c], row_sizes[r]
                )
                _add_gap_midpoints(
                    rect, r, c, len(row_sizes), len(col_sizes),
                    col_pos, col_sizes, row_pos, row_sizes, col_gap, row_gap,
                )
                result[f"r{r}c{c}"] = rect

    if items:
        _apply_items(result, items)

    return result


def _parse_gap(value) -> tuple[int, int]:
    """Parse CSS gap shorthand. Returns (row_gap, col_gap)."""
    if isinstance(value, (int, float)):
        g = int(value)
        return g, g
    parts = str(value).split()
    if len(parts) == 1:
        g = int(parts[0])
        return g, g
    return int(parts[0]), int(parts[1])


def _resolve_tracks(track_str: str, available: int, gap: int) -> list[int]:
    """Parse track-list and resolve to pixel sizes."""
    track_str = track_str.strip()

    # Shorthand: "3" -> "1fr 1fr 1fr"
    if re.fullmatch(r"\d+", track_str):
        track_str = " ".join(["1fr"] * int(track_str))

    tokens = track_str.split()
    fixed: list[int | None] = []
    fr_values: list[float] = []

    for t in tokens:
        if t.endswith("px"):
            fixed.append(int(float(t[:-2])))
            fr_values.append(0)
        elif t.endswith("fr"):
            fixed.append(None)
            fr_values.append(float(t[:-2]))
        else:
            fixed.append(None)
            fr_values.append(float(t))

    total_gaps = gap * (len(tokens) - 1)
    total_fixed = sum(v for v in fixed if v is not None)
    remaining = available - total_fixed - total_gaps
    total_fr = sum(fr_values)
    fr_unit = remaining / total_fr if total_fr > 0 else 0

    sizes: list[int] = []
    for f, fr in zip(fixed, fr_values):
        if f is not None:
            sizes.append(f)
        else:
            sizes.append(round(fr * fr_unit))

    # Absorb rounding error in last fr track
    actual_total = sum(sizes) + total_gaps
    diff = available - actual_total
    if diff != 0:
        for i in range(len(sizes) - 1, -1, -1):
            if fixed[i] is None:
                sizes[i] += diff
                break

    return sizes


def _track_positions(start: int, sizes: list[int], gap: int) -> list[int]:
    """Compute start positions for each track."""
    positions = []
    pos = start
    for s in sizes:
        positions.append(pos)
        pos += s + gap
    return positions


def _map_areas(
    areas: list[list[str]],
    col_pos: list[int],
    col_sizes: list[int],
    row_pos: list[int],
    row_sizes: list[int],
    col_gap: int = 0,
    row_gap: int = 0,
) -> dict:
    """Map grid-template-areas to merged rectangles."""
    bounds: dict[str, dict] = {}
    for r, row in enumerate(areas):
        for c, name in enumerate(row):
            if name not in bounds:
                bounds[name] = {"r0": r, "r1": r, "c0": c, "c1": c}
            else:
                b = bounds[name]
                b["r0"] = min(b["r0"], r)
                b["r1"] = max(b["r1"], r)
                b["c0"] = min(b["c0"], c)
                b["c1"] = max(b["c1"], c)

    result = {}
    for name, b in bounds.items():
        x = col_pos[b["c0"]]
        y = row_pos[b["r0"]]
        w = col_pos[b["c1"]] + col_sizes[b["c1"]] - x
        h = row_pos[b["r1"]] + row_sizes[b["r1"]] - y
        rect = _make_rect(x, y, w, h)
        if b["c1"] < len(col_sizes) - 1 and col_gap > 0:
            rect["gx2"] = rect["x2"] + col_gap // 2
        if b["r1"] < len(row_sizes) - 1 and row_gap > 0:
            rect["gy2"] = rect["y2"] + row_gap // 2
        result[name] = rect

    return result


def _make_rect(x: int, y: int, w: int, h: int) -> dict:
    """Create rectangle dict with bb coordinates."""
    return {
        "x": x, "y": y, "w": w, "h": h,
        "x2": x + w, "y2": y + h,
        "cx": x + w // 2, "cy": y + h // 2,
    }


def _add_gap_midpoints(
    rect: dict,
    r: int, c: int,
    n_rows: int, n_cols: int,
    col_pos: list[int], col_sizes: list[int],
    row_pos: list[int], row_sizes: list[int],
    col_gap: int, row_gap: int,
) -> None:
    """Add gx2/gy2 gap midpoint coordinates to rect if applicable."""
    if c < n_cols - 1 and col_gap > 0:
        rect["gx2"] = rect["x2"] + col_gap // 2
    if r < n_rows - 1 and row_gap > 0:
        rect["gy2"] = rect["y2"] + row_gap // 2


def _apply_items(result: dict, items: dict) -> None:
    """Add centered item coordinates to matching cells."""
    for name, item_spec in items.items():
        if name not in result:
            continue
        cell = result[name]
        iw = item_spec["w"]
        item: dict = {"x": cell["x"] + (cell["w"] - iw) // 2, "w": iw}
        if "h" in item_spec:
            ih = item_spec["h"]
            item["y"] = cell["y"] + (cell["h"] - ih) // 2
            item["h"] = ih
        cell["item"] = item
