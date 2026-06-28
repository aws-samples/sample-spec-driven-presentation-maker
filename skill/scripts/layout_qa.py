# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Layout QA harness: objective quality metrics for the layout engine.

Runs the REAL engine pipeline (same as pptx_builder.cmd_layout) on a logical
structure JSON, then measures geometric quality:
  - crossings   : pairs of edge segments that intersect
  - pierces     : edge segments passing through a non-endpoint node icon
  - diagonals   : segments that are neither horizontal nor vertical
  - bad_ports   : first/last segment not perpendicular to its node edge
  - backwards   : first segment travels opposite to the port's outward normal

Usage:
  python3 layout_qa.py <input.json> [--width W] [--height H] [--json]
"""

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdpm.layout import (  # noqa: E402
    optimize_order,
    _layout_scale,
    _layout_translate,
    _layout_collect,
    _layout_route_connections,
    _count_all_crossings,
    _find_node,
)

_TOL = 2


def _build_layout(tree, target_w=None, target_h=None):
    """Replicate cmd_layout's scale/translate/collect/route pipeline."""
    direction = tree.get("direction", "horizontal")
    align = tree.get("align", "center")
    optimize_order(tree)

    def build_root():
        return {
            "id": "_root",
            "children": copy.deepcopy(tree.get("children", tree.get("nodes", []))),
            "direction": direction,
            "align": align,
        }

    root = build_root()
    _layout_scale(root, direction, align)
    cum_h = cum_v = 1.0
    if target_w or target_h:
        for _ in range(10):
            rb = root["_bindings"]
            sx = target_w / rb[2] if target_w else 1.0
            sy = target_h / rb[3] if target_h else 1.0
            if abs(sx - 1.0) < 0.03 and abs(sy - 1.0) < 0.03:
                break
            cum_h *= sx
            cum_v *= sy
            root = build_root()
            _layout_scale(root, direction, align, cum_h, cum_v)

    rb = root["_bindings"]
    _layout_translate(root, -rb[0], -rb[1])
    nodes, groups = {}, {}
    for child in root["children"]:
        _layout_collect(child, nodes, groups)
    edges = _layout_route_connections(tree.get("connections", []), nodes, groups)
    return nodes, groups, edges, root["_bindings"]


def _seg_pierces_rect(p1, p2, n, inset=4):
    rx, ry = n["x"], n["y"]
    rw, rh = n.get("width", 60), n.get("height", n.get("width", 60))
    x0, y0, x1, y1 = rx + inset, ry + inset, rx + rw - inset, ry + rh - inset
    ax, ay = p1
    bx, by = p2
    if ax == bx:  # vertical
        return x0 < ax < x1 and min(ay, by) < y1 and max(ay, by) > y0
    if ay == by:  # horizontal
        return y0 < ay < y1 and min(ax, bx) < x1 and max(ax, bx) > x0
    # diagonal: bounding-box overlap as a coarse test
    return min(ax, bx) < x1 and max(ax, bx) > x0 and min(ay, by) < y1 and max(ay, by) > y0


def _side_of(node, pt):
    """Classify which edge a port point sits on.

    Ports on the bottom edge are offset downward by the label height, so a
    point below the icon that is horizontally inside the icon's x-span is a
    bottom port (not a left/right one). Likewise points above are top ports.
    """
    x, y = pt
    cx, cy = node["x"], node["y"]
    w = node.get("width", 60)
    h = node.get("height", w)
    # Inside the icon's horizontal span and at/below or at/above → top/bottom port
    if cx - _TOL <= x <= cx + w + _TOL:
        if y >= cy + h - _TOL:
            return "bottom"
        if y <= cy + _TOL:
            return "top"
    # Inside the icon's vertical span → left/right port
    if cy - _TOL <= y <= cy + h + _TOL:
        if x <= cx + _TOL:
            return "left"
        if x >= cx + w - _TOL:
            return "right"
    # Fallback: nearest edge
    d = {
        "left": abs(x - cx),
        "right": abs(x - (cx + w)),
        "top": abs(y - cy),
        "bottom": abs(y - (cy + h)),
    }
    return min(d, key=d.get)


def measure(tree, target_w=1720, target_h=800):
    nodes, groups, edges, rb = _build_layout(tree, target_w, target_h)

    crossings = _count_all_crossings(edges)

    pierces = []
    diagonals = []
    bad_ports = []
    backwards = []

    for e in edges:
        pts = e["points"]
        if len(pts) < 2:
            continue
        ig = {e["from"], e["to"]}
        src = _find_node(nodes, e["from"])
        dst = _find_node(nodes, e["to"])

        # pierces
        for nid, n in nodes.items():
            short = nid.rsplit(".", 1)[-1]
            if short in ig or nid in ig:
                continue
            for k in range(len(pts) - 1):
                if _seg_pierces_rect(pts[k], pts[k + 1], n):
                    pierces.append((f"{e['from'].rsplit('.',1)[-1]}->{e['to'].rsplit('.',1)[-1]}", short))
                    break

        # diagonals
        for k in range(len(pts) - 1):
            dx = abs(pts[k][0] - pts[k + 1][0])
            dy = abs(pts[k][1] - pts[k + 1][1])
            if dx > _TOL and dy > _TOL:
                diagonals.append((f"{e['from'].rsplit('.',1)[-1]}->{e['to'].rsplit('.',1)[-1]}", pts[k], pts[k + 1]))

        # port perpendicularity + backwards (skip detours which legitimately exit bottom)
        if src is not None:
            ss = _side_of(src, pts[0])
            seg = (pts[0], pts[1])
            horiz = abs(seg[0][1] - seg[1][1]) <= _TOL
            vert = abs(seg[0][0] - seg[1][0]) <= _TOL
            exp_horiz = ss in ("left", "right")
            if exp_horiz and not horiz:
                bad_ports.append((f"src {e['from'].rsplit('.',1)[-1]}", ss, "not-horizontal"))
            if (not exp_horiz) and not vert:
                bad_ports.append((f"src {e['from'].rsplit('.',1)[-1]}", ss, "not-vertical"))
            # backwards: exits right but first seg goes left, etc.
            if ss == "right" and seg[1][0] < seg[0][0] - _TOL:
                backwards.append(f"{e['from'].rsplit('.',1)[-1]}[right]->{e['to'].rsplit('.',1)[-1]}")
            if ss == "left" and seg[1][0] > seg[0][0] + _TOL:
                backwards.append(f"{e['from'].rsplit('.',1)[-1]}[left]->{e['to'].rsplit('.',1)[-1]}")
            if ss == "bottom" and seg[1][1] < seg[0][1] - _TOL:
                backwards.append(f"{e['from'].rsplit('.',1)[-1]}[bottom]->{e['to'].rsplit('.',1)[-1]}")
            if ss == "top" and seg[1][1] > seg[0][1] + _TOL:
                backwards.append(f"{e['from'].rsplit('.',1)[-1]}[top]->{e['to'].rsplit('.',1)[-1]}")

        if dst is not None:
            ds = _side_of(dst, pts[-1])
            seg = (pts[-2], pts[-1])
            horiz = abs(seg[0][1] - seg[1][1]) <= _TOL
            vert = abs(seg[0][0] - seg[1][0]) <= _TOL
            exp_horiz = ds in ("left", "right")
            if exp_horiz and not horiz:
                bad_ports.append((f"dst {e['to'].rsplit('.',1)[-1]}", ds, "not-horizontal"))
            if (not exp_horiz) and not vert:
                bad_ports.append((f"dst {e['to'].rsplit('.',1)[-1]}", ds, "not-vertical"))

    return {
        "crossings": crossings,
        "pierces": len(pierces),
        "diagonals": len(diagonals),
        "bad_ports": len(bad_ports),
        "backwards": len(backwards),
        "size": [round(rb[2]), round(rb[3])],
        "detail": {
            "pierces": pierces,
            "diagonals": diagonals,
            "bad_ports": bad_ports,
            "backwards": backwards,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--width", type=int, default=1720)
    ap.add_argument("--height", type=int, default=800)
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    args = ap.parse_args()

    tree = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = measure(tree, args.width, args.height)

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return

    print(f"crossings={result['crossings']} pierces={result['pierces']} "
          f"diagonals={result['diagonals']} bad_ports={result['bad_ports']} "
          f"backwards={result['backwards']} size={result['size']}")
    for cat in ("pierces", "diagonals", "bad_ports", "backwards"):
        for d in result["detail"][cat]:
            print(f"  {cat}: {d}")


if __name__ == "__main__":
    main()
