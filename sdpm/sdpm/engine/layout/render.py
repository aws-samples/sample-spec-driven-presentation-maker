# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Architecture diagram renderer: logical-structure JSON → placed elements.

This is the canonical pipeline. The ``layout`` CLI command and the QA metrics
harness both call into here instead of re-implementing the scale/route steps.

- :func:`build_layout` runs the placement pipeline (optimize order → scale to
  fit → translate → collect → route) and returns the collected geometry.
- :func:`render_architecture` builds the sdpm ``elements`` array, generates
  human-readable ``warnings``, and attaches objective ``metrics``.

The pipeline respects the root ``reverse`` flag so the measured geometry
matches what the CLI actually draws.
"""

import copy

from . import (
    _find_crossing_pairs,
    _group_member_ids,
    _layout_collect,
    _layout_route_connections,
    _layout_scale,
    _layout_translate,
    _seg_crosses_box,
    box_to_elements,
    cancel_cross_axis_squash,
    measure_natural_child_sizes,
    optimize_order,
)

# Number of scale-to-fit refinement passes. Every real diagram converges in
# ~3 passes (the loop breaks once the fit ratio is within 3%); the cap is a
# safety bound.
_FIT_ITERATIONS = 8


def build_layout(tree, x=None, y=None, width=None, height=None, optimize=True, pt_per_px=0.5):
    """Run the placement pipeline on a logical-structure ``tree``.

    Returns ``(nodes, groups, edges, root_bindings, cum_h, cum_v)`` where
    ``root_bindings`` is ``[x, y, w, h]``. ``x``/``y`` offset the whole diagram
    (default: origin); ``width``/``height`` are the scale-to-fit target box.

    ``tree`` is deep-copied, so the caller's dict is not mutated (aside from the
    order-optimization pass, which operates on the copy).

    ``optimize=False`` skips the order-optimization pre-pass. The tile-pool
    reflow inside ``optimize_order`` uses this to score candidate arrangements
    by real routing without recursing back into itself.

    ``pt_per_px`` is the ratio of physical pt to virtual px (default 0.5 for
    16:9 at 1920px logical width). Controls box height estimation accuracy
    across different template aspect ratios.
    """
    tree = copy.deepcopy(tree)
    direction = tree.get("direction", "horizontal")
    align = tree.get("align", "center")
    reverse = tree.get("reverse", False)

    # Optimize node order within groups to minimize edge crossings.
    if optimize:
        optimize_order(tree)

    def build_root():
        root = {"id": "_root",
                "children": copy.deepcopy(tree.get("children", tree.get("nodes", []))),
                "direction": direction, "align": align}
        if reverse:
            root["reverse"] = True
        return root

    # Pass 1: natural size.
    root = build_root()
    _layout_scale(root, direction, align, pt_per_px=pt_per_px)

    # Record each top-level group's NATURAL cross-axis size so we can later tell
    # which groups fit on their own (before any global squash).
    natural_sizes = measure_natural_child_sizes(tree, root)

    cum_h = 1.0
    cum_v = 1.0
    if width or height:
        for _ in range(_FIT_ITERATIONS):
            rb = root["_bindings"]
            sx = width / rb[2] if width else 1.0
            sy = height / rb[3] if height else 1.0
            if abs(sx - 1.0) < 0.03 and abs(sy - 1.0) < 0.03:
                break
            cum_h *= sx
            cum_v *= sy
            root = build_root()
            _layout_scale(root, direction, align, cum_h, cum_v, pt_per_px=pt_per_px)
        # A single oversized group forces a global cross-axis squash that would
        # crush short siblings. Cancel that squash on the groups that already
        # fit (the slide may overflow — that's the oversized group's problem,
        # flagged by a warning — but the groups that fit stay readable).
        if cancel_cross_axis_squash(tree, natural_sizes, cum_h, cum_v, width, height):
            root = build_root()
            _layout_scale(root, direction, align, cum_h, cum_v, pt_per_px=pt_per_px)

    rb = root["_bindings"]
    ox = (x or 0) - rb[0]
    oy = (y or 0) - rb[1]
    _layout_translate(root, ox, oy)

    # Center if still slightly off from target.
    rb = root["_bindings"]
    if width and abs(rb[2] - width) > 5:
        dx = (width - rb[2]) // 2
        _layout_translate(root, dx, 0)
    if height and abs(rb[3] - height) > 5:
        dy = (height - rb[3]) // 2
        _layout_translate(root, 0, dy)

    # Collect results.
    nodes_out = {}
    groups_out = {}
    for child in root["children"]:
        _layout_collect(child, nodes_out, groups_out)

    edges_out = []
    connections = tree.get("connections", [])
    if connections:
        edges_out = _layout_route_connections(connections, nodes_out, groups_out)

    return nodes_out, groups_out, edges_out, root["_bindings"], cum_h, cum_v


def _build_elements(tree, nodes_out, groups_out, edges_out, is_dark):
    """Build the sdpm elements array from collected geometry."""
    elements = []

    # Groups (largest first for correct z-order).
    for gid, g in sorted(groups_out.items(), key=lambda x: -x[1]["width"] * x[1]["height"]):
        gt = g.get("groupType")
        if not gt:
            continue
        elements.append({"type": "arch-group", "groupType": gt, "x": g["x"], "y": g["y"],
                         "width": g["width"], "height": g["height"],
                         "label": g.get("label", gid.rsplit(".", 1)[-1])})

    # Nodes.
    for nid, n in nodes_out.items():
        if n.get("box"):
            elements.extend(box_to_elements(nid, n, is_dark))
        elif n.get("icon"):
            elements.append({"type": "image", "src": n["icon"], "x": n["x"], "y": n["y"],
                            "width": n["width"], "label": n.get("label", nid.rsplit(".", 1)[-1]),
                            "labelPosition": "bottom"})

    # Edges as elbow connectors. Track label positions for overlap avoidance.
    placed_labels = []
    for e in edges_out:
        pts = e["points"]
        if len(pts) < 2:
            continue
        sx, sy = pts[0]
        ex, ey = pts[-1]

        # Emit as polyline for: 3+ point paths (precise routing), fan-out, detours, complex
        is_detour = len(pts) >= 4 and pts[0][1] == pts[-1][1] and any(p[1] != pts[0][1] for p in pts[1:-1])
        is_fanout = e.get("_fanout", False)
        is_multipoint = len(pts) >= 3
        if is_detour or is_fanout or is_multipoint or len(pts) >= 6:
            el = {"type": "line", "arrowEnd": "arrow",
                  "points": [[p[0], p[1]] for p in pts]}
            elements.append(el)
        else:
            el = {"type": "line", "x1": sx, "y1": sy, "x2": ex, "y2": ey, "arrowEnd": "arrow"}
            if len(pts) > 2:
                el["connectorType"] = "elbow"
                dx = ex - sx
                dy = ey - sy
                if len(pts) >= 4 and (abs(dx) > 0 or abs(dy) > 0):
                    # 4 points: [start, bend1, bend2, end]
                    # Determine if first segment is vertical based on points.
                    # If points have been shifted (non-axis-aligned), fall back to
                    # overall direction: if |dy| > |dx|, prefer V-H-V (bentConnector3)
                    seg1_vertical = abs(pts[0][0] - pts[1][0]) <= abs(pts[0][1] - pts[1][1])
                    if abs(pts[0][0] - pts[1][0]) > 5 and abs(pts[0][1] - pts[1][1]) > 5:
                        seg1_vertical = abs(dy) > abs(dx)
                    if seg1_vertical:
                        # V-H-V → elbowStart vertical
                        # For U-shaped detour (sy==ty), use the bend Y relative to path height
                        if dy != 0:
                            adj = (pts[1][1] - sy) / dy
                        else:
                            # sy == ty: use max extent as reference
                            path_max_y = max(p[1] for p in pts)
                            path_min_y = min(p[1] for p in pts)
                            path_dy = path_max_y - sy if path_max_y > sy else path_min_y - sy
                            adj = (pts[1][1] - sy) / path_dy if path_dy != 0 else 0.5
                            # Override: place end at same Y as start by using full extent
                            dy = path_dy
                            ey = sy + dy
                            el["y2"] = ey
                        el["preset"] = "bentConnector3"
                        el["elbowStart"] = "vertical"
                        el["adjustments"] = [max(-2.0, min(3.0, adj))]
                    else:
                        # H-V-H → bentConnector4
                        adj1 = (pts[1][0] - sx) / dx if dx != 0 else 0.5
                        adj2 = (pts[2][1] - sy) / dy if dy != 0 else 0.5
                        # Clamp adj1: must go forward from start (min 0.15 = short horizontal stub)
                        adj1_min = 0.15 if dx > 0 else -1.0
                        adj1_max = 2.0 if dx > 0 else -0.15
                        el["preset"] = "bentConnector4"
                        el["adjustments"] = [max(adj1_min, min(adj1_max, adj1)), max(-1.0, min(2.0, adj2))]
                elif dy != 0 or dx != 0:
                    el["adjustments"] = [0.5]
            elements.append(el)

        label = e.get("label", "")
        if not label:
            continue

        # Apply user labelOffset if provided.
        conn_obj = None
        for c in (tree.get("connections") or []):
            if c.get("from") == e["from"] and c.get("to") == e["to"]:
                conn_obj = c
                break
        user_offset = (conn_obj or {}).get("labelOffset", {})

        # Find longest segment midpoint.
        best_mid = None
        best_len = -1
        best_horizontal = True
        for si in range(len(pts) - 1):
            ax, ay = pts[si]
            bx, by = pts[si + 1]
            seg_len = abs(bx - ax) + abs(by - ay)
            if seg_len > best_len:
                best_len = seg_len
                best_mid = ((ax + bx) // 2, (ay + by) // 2)
                best_horizontal = abs(bx - ax) > abs(by - ay)
        mx, my = best_mid or ((pts[0][0] + pts[-1][0]) // 2, (pts[0][1] + pts[-1][1]) // 2)

        tw = max(len(label) * 11, 60)
        th = 30
        arrow_len = abs(ex - sx) + abs(ey - sy)

        # Position: below for horizontal, right for vertical.
        if best_horizontal:
            lx, ly = mx - tw // 2, my + 2
            # Short arrow: place label below arrow end
            if arrow_len < tw + 20:
                ly = my + 12
        else:
            lx, ly = mx + 6, my - th // 2

        # Apply user offset.
        lx += user_offset.get("x", 0)
        ly += user_offset.get("y", 0)

        # Overlap avoidance: shift if colliding with existing labels.
        for px, py, pw, ph in placed_labels:
            if lx < px + pw and lx + tw > px and ly < py + ph and ly + th > py:
                if best_horizontal:
                    ly = py + ph + 2
                else:
                    ly = py + ph + 2
        placed_labels.append((lx, ly, tw, th))

        elements.append({"type": "textbox", "x": lx, "y": ly, "width": tw, "height": th,
                         "fontSize": 9, "align": "center", "verticalAlign": "top",
                         "fill": "#000000", "opacity": 0.7, "line": "none",
                         "marginTop": 0, "marginBottom": 0, "marginLeft": 0, "marginRight": 0,
                         "text": "{{#8FA7C4:" + label + "}}"})

    return elements


def _build_warnings(nodes_out, groups_out, edges_out, rb,
                    target_w, target_h, cum_h, cum_v, scaled):
    """Generate human-readable layout warnings (facts, not prescriptions)."""
    warnings = []
    if target_w:
        ratio_w = rb[2] / target_w
        if ratio_w < 0.5:
            warnings.append(f"Layout uses only {round(ratio_w*100)}% of target width ({rb[2]}px / {target_w}px). Consider placing top-level groups horizontally.")
        if rb[2] > target_w:
            warnings.append(f"Layout width {rb[2]}px exceeds target {target_w}px. Consider reducing horizontal elements or splitting into multiple rows.")
    if target_h:
        ratio_h = rb[3] / target_h
        if ratio_h < 0.5:
            warnings.append(f"Layout uses only {round(ratio_h*100)}% of target height ({rb[3]}px / {target_h}px). Consider adding vertical spacing or stacking groups vertically.")
        if rb[3] > target_h:
            warnings.append(f"Layout height {rb[3]}px exceeds target {target_h}px. Consider reducing nesting depth or placing groups horizontally.")
    if scaled:
        if cum_h < 0.5:
            warnings.append(f"Horizontal spacing compressed to {round(cum_h*100)}%. Consider reducing horizontal elements.")
        if cum_v < 0.5:
            warnings.append(f"Vertical spacing compressed to {round(cum_v*100)}%. Consider reducing vertical stacking.")

    # Check per-group size.
    for gid, g in groups_out.items():
        children = g.get("children", [])
        if len(children) >= 3:
            glabel = g.get("label", gid.rsplit(".", 1)[-1])
            if target_h and g["height"] > (target_h * 0.6):
                warnings.append(f"Group \"{glabel}\" is tall ({g['height']}px). Consider direction: horizontal for its children.")
            if target_w and g["width"] > (target_w * 0.8):
                warnings.append(f"Group \"{glabel}\" is wide ({g['width']}px). Consider direction: vertical for its children.")

    # Check label overlaps.
    label_rects = []
    for nid, n in nodes_out.items():
        lbl = n.get("label", "")
        if lbl:
            lw = len(lbl) * 8 + 10
            lh = 20
            lx = n["x"] + (n["width"] - lw) / 2
            ly = n["y"] + n["height"]
            label_rects.append((nid, lbl, lx, ly, lw, lh))
    for i in range(len(label_rects)):
        for j in range(i + 1, len(label_rects)):
            _, l1, x1, y1, w1, h1 = label_rects[i]
            _, l2, x2, y2, w2, h2 = label_rects[j]
            gap = 5
            if x1 - gap < x2 + w2 and x1 + w1 + gap > x2 and y1 - gap < y2 + h2 and y1 + h1 + gap > y2:
                warnings.append(f"Labels \"{l1}\" and \"{l2}\" overlap. Increase spacing or shorten labels.")

    # Check edge-node crossings.
    margin = 5
    crossing_reported = set()
    for e in edges_out:
        pts = e["points"]
        if len(pts) < 2:
            continue
        src_id, dst_id = e["from"], e["to"]
        edge_key = f"{src_id}→{dst_id}"
        for seg_i in range(len(pts) - 1):
            x1, y1 = pts[seg_i]
            x2, y2 = pts[seg_i + 1]
            seg_min_x, seg_max_x = min(x1, x2), max(x1, x2)
            seg_min_y, seg_max_y = min(y1, y2), max(y1, y2)
            for nid, n in nodes_out.items():
                if nid.endswith(src_id) or nid.endswith(dst_id):
                    continue
                report_key = (edge_key, n.get("label", nid))
                if report_key in crossing_reported:
                    continue
                nx, ny, nw, nh = n["x"], n["y"], n["width"], n["height"]
                if seg_max_x > nx + margin and seg_min_x < nx + nw - margin and seg_max_y > ny + margin and seg_min_y < ny + nh - margin:
                    warnings.append(f'Edge {edge_key} passes through node "{n.get("label", nid)}".')
                    crossing_reported.add(report_key)

    # Check edge-edge crossings (segment intersection).
    # Use the SAME crossing detector the QA metric uses, so a fan-merge trunk's
    # structural T-junction (spokes peeling off a shared trunk) is not reported
    # as a crossing. Previously the builder used a naive segment-intersection
    # test that flagged every shared trunk, contradicting the QA "crossings=0".
    for i, j in sorted(_find_crossing_pairs(edges_out)):
        e_i = f"{edges_out[i]['from']}→{edges_out[i]['to']}"
        e_j = f"{edges_out[j]['from']}→{edges_out[j]['to']}"
        warnings.append(f"Edges {e_i} and {e_j} cross.")

    # Group-frame pierce: an edge slices through a framed group's box without
    # connecting to that group or any icon inside it. The engine auto-detours
    # only when it can FULLY clear the box; a residual pierce here is a
    # structural problem the author must fix (the line has nowhere clean to go
    # because an unrelated container sits across its path).
    gframe_reported = set()
    for e in edges_out:
        pts = e["points"]
        if len(pts) < 2:
            continue
        efrom = e["from"].rsplit(".", 1)[-1]
        eto = e["to"].rsplit(".", 1)[-1]
        for gid, g in groups_out.items():
            if not g.get("groupType"):
                continue
            gshort = gid.rsplit(".", 1)[-1]
            if efrom == gshort or eto == gshort:
                continue
            members = _group_member_ids(nodes_out, groups_out, gid)
            if efrom in members or eto in members:
                continue
            key = (e["from"], e["to"], gid)
            if key in gframe_reported:
                continue
            if any(_seg_crosses_box(pts[k], pts[k + 1], g["x"], g["y"],
                                    g["width"], g["height"], 2)
                   for k in range(len(pts) - 1)):
                glabel = g.get("label", gshort)
                warnings.append(
                    f'Edge {e["from"]}→{e["to"]} passes through group '
                    f'"{glabel}" without connecting to it.')
                gframe_reported.add(key)

    # Structure suggestions: sibling size imbalance.
    all_items = {}
    all_items.update(groups_out)
    all_items.update(nodes_out)
    for gid, g in groups_out.items():
        child_ids = g.get("children", [])
        if len(child_ids) < 2:
            continue
        has_group_child = any(cid in groups_out for cid in child_ids)
        if not has_group_child:
            continue
        child_bboxes = []
        for cid in child_ids:
            c = all_items.get(cid)
            if c:
                child_bboxes.append((cid, c))
        if len(child_bboxes) < 2:
            continue
        direction = g.get("direction", "horizontal")
        axis = "height" if direction == "horizontal" else "width"
        # Only compare group children (skip leaf nodes).
        group_children = [(cid, c) for cid, c in child_bboxes if cid in groups_out]
        if len(group_children) < 2:
            continue
        sizes = [(cid, c[axis]) for cid, c in group_children]
        max_cid, max_s = max(sizes, key=lambda x: x[1])
        min_cid, min_s = min(sizes, key=lambda x: x[1])
        if min_s <= 0 or max_s / min_s < 2.0:
            continue
        max_label = all_items.get(max_cid, {}).get("label", max_cid)
        min_label = all_items.get(min_cid, {}).get("label", min_cid)
        ratio = max_s / min_s
        # Add packing efficiency as supplementary info.
        pad = g.get("_padding", {})
        content_w = g["width"] - pad.get("left", 0) - pad.get("right", 0)
        content_h = g["height"] - pad.get("top", 0) - pad.get("bottom", 0)
        content_area = max(content_w, 1) * max(content_h, 1)
        child_area = sum(c["width"] * c["height"] for _, c in child_bboxes)
        eff = round(child_area / content_area * 100)
        warnings.append(f"Group \"{g.get('label', g.get('id', '?'))}\" children {axis} imbalance: \"{max_label}\"={max_s}px vs \"{min_label}\"={min_s}px (ratio {ratio:.1f}:1, packing {eff}%). Consider redistributing children or changing direction. Note: restructuring may affect arrow routing.")

    return warnings


def render_architecture(tree, x=None, y=None, width=None, height=None,
                        theme="dark", include_metrics=True, pt_per_px=0.5):
    """Render a logical-structure ``tree`` to placed sdpm elements.

    Returns a dict with:
      - ``elements``: sdpm element array (arch-groups, images/boxes, connectors)
      - ``bbox``: final bounding box ``{x, y, width, height}`` after scale-to-fit
      - ``warnings``: human-readable facts about layout defects (may be empty)
      - ``metrics``: objective QA metrics (crossings/pierces/group_pierces/
        overflow/score, …) when ``include_metrics`` is True

    ``targetArea`` inside the tree (``{x, y, width, height}``) overrides the
    corresponding argument when that argument is falsy.

    ``pt_per_px`` is the ratio of physical pt to virtual px (default 0.5 for
    16:9 at 1920px logical width). Pass ``slideSize.ptPerPx`` from the deck
    JSON when targeting non-16:9 templates.
    """
    target_area = tree.get("targetArea", {})
    if target_area:
        if "x" in target_area and not x:
            x = target_area["x"]
        if "y" in target_area and not y:
            y = target_area["y"]
        if "width" in target_area and not width:
            width = target_area["width"]
        if "height" in target_area and not height:
            height = target_area["height"]

    nodes_out, groups_out, edges_out, rb, cum_h, cum_v = build_layout(
        tree, x, y, width, height, pt_per_px=pt_per_px)

    is_dark = theme == "dark"
    elements = _build_elements(tree, nodes_out, groups_out, edges_out, is_dark)
    warnings = _build_warnings(nodes_out, groups_out, edges_out, rb,
                               width, height, cum_h, cum_v, bool(width or height))

    output = {
        "elements": elements,
        "bbox": {"x": rb[0], "y": rb[1], "width": rb[2], "height": rb[3]},
    }
    if warnings:
        output["warnings"] = warnings

    if include_metrics:
        from .metrics import measure_layout
        output["metrics"] = measure_layout(
            nodes_out, groups_out, edges_out, rb,
            width or 1720, height or 800)

    return output
