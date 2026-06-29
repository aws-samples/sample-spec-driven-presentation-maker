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
    _count_group_pierces,
    _seg_pierces_node,
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


def _seg_pierces_rect(p1, p2, n):
    # Use the engine's own pierce definition so the QA metric and the
    # optimizer's cost function agree on what counts as a pierce/graze.
    return _seg_pierces_node(p1, p2, n)


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
    group_pierces = _count_group_pierces(edges, groups, nodes)

    pierces = []
    diagonals = []
    bad_ports = []
    backwards = []
    wirelength = 0.0

    for e in edges:
        pts = e["points"]
        if len(pts) < 2:
            continue

        # total wire length (paths are axis-aligned, so Manhattan == polyline
        # length). Minimizing this clusters connected icons together.
        for k in range(len(pts) - 1):
            wirelength += abs(pts[k][0] - pts[k + 1][0]) + abs(pts[k][1] - pts[k + 1][1])
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

    w, h = rb[2], rb[3]
    diag = (w * w + h * h) ** 0.5 or 1.0
    # normalize wirelength by the canvas diagonal so the soft term is
    # comparable across differently-sized candidate layouts.
    wire_norm = wirelength / diag
    aspect = (w / h) if h else 0.0

    # Overflow: how far the laid-out bounds exceed the slide frame after
    # scale-to-fit. A tall (vertical-root) layout can stop shrinking once its
    # icons+labels hit their minimum size, leaving height > target_h — those
    # icons render off-slide. This is unusable regardless of crossing count,
    # so it ranks ABOVE crossings in the score. Expressed as a fraction of
    # the target dimension (0 == fits).
    overflow = 0.0
    if target_w and w > target_w:
        overflow += (w - target_w) / target_w
    if target_h and h > target_h:
        overflow += (h - target_h) / target_h

    result = {
        "crossings": crossings,
        "pierces": len(pierces),
        "group_pierces": group_pierces,
        "diagonals": len(diagonals),
        "bad_ports": len(bad_ports),
        "backwards": len(backwards),
        "overflow": round(overflow, 3),
        "wirelength": round(wirelength),
        "wire_norm": round(wire_norm, 3),
        "aspect": round(aspect, 3),
        "size": [round(w), round(h)],
        "detail": {
            "pierces": pierces,
            "diagonals": diagonals,
            "bad_ports": bad_ports,
            "backwards": backwards,
        },
    }
    result["score"] = score(result)
    return result


# Aspect ratio considered visually comfortable for a 16:9 slide body.
_ASPECT_LO, _ASPECT_HI = 1.4, 3.2

# Geometric-defect weights, combined into ONE additive layer so the search
# can't trade one defect class for a worse total of another (e.g. drive
# crossings to 0 by introducing 12 pierces). A pierce (arrow through a
# non-endpoint icon) reads worse than a crossing, so it is weighted heavier;
# a backwards segment is a softer wrongness than either.
_W_CROSS = 1.0
_W_PIERCE = 1.5
_W_GROUP_PIERCE = 1.0
_W_BACK = 0.7
_W_BADPORT = 0.5


def score(m):
    """Multi-objective score; lower is better.

    Two layers, compared lexicographically:
      1. overflow  — does the layout spill off the slide frame? Off-slide
                     icons are unusable regardless of routing quality, so any
                     real overflow outranks everything below.
      2. defects   — a single WEIGHTED SUM of geometric defects (crossings,
                     pierces, backwards, bad ports/diagonals). Combining them
                     additively (rather than as separate lexicographic tiers)
                     prevents the degenerate trade where the search zeroes one
                     defect class by inflating another.
    Soft aesthetic terms (wire length, aspect penalty) break ties within the
    defect layer. This is the "judge" that picks which position-shifted
    candidate is actually good.
    """
    aspect = m["aspect"]
    if aspect < _ASPECT_LO:
        aspect_pen = _ASPECT_LO - aspect
    elif aspect > _ASPECT_HI:
        aspect_pen = aspect - _ASPECT_HI
    else:
        aspect_pen = 0.0
    soft = m["wire_norm"] + 2.0 * aspect_pen
    # Overflow bucketed to 0.1 (10% of a slide dimension) so small rounding
    # jitter doesn't reorder otherwise-equal layouts, but any real off-slide
    # spill outranks every geometric defect below it.
    overflow_bucket = round(m.get("overflow", 0.0) * 10)
    defects = (
        _W_CROSS * m["crossings"]
        + _W_PIERCE * m["pierces"]
        + _W_GROUP_PIERCE * m.get("group_pierces", 0)
        + _W_BACK * m["backwards"]
        + _W_BADPORT * (m["bad_ports"] + m["diagonals"])
    )
    return (
        overflow_bucket,
        round(defects, 2),
        round(soft, 3),
    )


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
          f"group_pierces={result['group_pierces']} "
          f"diagonals={result['diagonals']} bad_ports={result['bad_ports']} "
          f"backwards={result['backwards']} size={result['size']}")
    print(f"overflow={result['overflow']} wirelength={result['wirelength']} "
          f"wire_norm={result['wire_norm']} aspect={result['aspect']} "
          f"score={result['score']}")
    for cat in ("pierces", "diagonals", "bad_ports", "backwards"):
        for d in result["detail"][cat]:
            print(f"  {cat}: {d}")


if __name__ == "__main__":
    main()
