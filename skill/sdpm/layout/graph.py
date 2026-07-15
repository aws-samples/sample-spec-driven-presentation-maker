# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Graph layout engine: constraint-based placement for non-tree diagrams.

Input format:
{
  "mode": "graph",
  "nodes": {
    "monitor": {"label": "監視（DNA）", "icon": "..."},
    ...
  },
  "constraints": [
    {"type": "above", "node": "monitor", "target": "clap"},
    {"type": "right_of", "node": "prod_nw", "target": "clap"},
    {"type": "v_list", "nodes": ["orchestrator", "verify_agent", "review_agent", "gen_agent"]},
    {"type": "h_list", "nodes": ["operator", "manual_doc", "related_docs"]},
    {"type": "align_y", "nodes": ["verify_agent", "wf_yaml"]},
    {"type": "align_x", "nodes": ["monitor", "clap"]},
  ],
  "edges": [...],
  "groups": [...]
}

Constraint types:
  - above: node is above target (same X, node.y < target.y)
  - below: node is below target
  - left_of: node is to the left of target (same Y)
  - right_of: node is to the right of target (same Y)
  - v_list: nodes arranged vertically, equally spaced
  - h_list: nodes arranged horizontally, equally spaced
  - align_y: nodes share the same Y center
  - align_x: nodes share the same X center

Coordinate system: 1920x1080 px (EMU_PER_PX = 6350, 1px = 0.5pt on 960x540 slide).
"""

from . import _layout_route_connections

_SLIDE_W = 1920
_SLIDE_H = 1080
_MARGIN_TOP = 160
_MARGIN_BOTTOM = 80
_MARGIN_LEFT = 100
_MARGIN_RIGHT = 100


def layout_graph(spec, target_x=None, target_y=None, target_w=None, target_h=None, theme="dark"):
    """Compute graph layout from constraint-based spec."""
    target_x = target_x if target_x is not None else _MARGIN_LEFT
    target_y = target_y if target_y is not None else _MARGIN_TOP
    target_w = target_w if target_w is not None else (_SLIDE_W - _MARGIN_LEFT - _MARGIN_RIGHT)
    target_h = target_h if target_h is not None else (_SLIDE_H - _MARGIN_TOP - _MARGIN_BOTTOM)

    node_defs = spec.get("nodes", {})
    constraints = spec.get("constraints", [])
    edges = spec.get("edges", [])
    group_defs = spec.get("groups", [])
    icon_size = spec.get("iconSize", 110)
    gap_h = spec.get("gapH", 200)
    gap_v = spec.get("gapV", 160)

    # --- Phase 1: Solve constraints to get relative positions ---
    positions = _solve_constraints(list(node_defs.keys()), constraints, icon_size, gap_h, gap_v)

    # --- Phase 2: Scale and translate to fit target area ---
    if not positions:
        return [], {}, {}

    min_x = min(p[0] for p in positions.values())
    min_y = min(p[1] for p in positions.values())
    max_x = max(p[0] for p in positions.values())
    max_y = max(p[1] for p in positions.values())

    range_x = max_x - min_x if max_x > min_x else 1
    range_y = max_y - min_y if max_y > min_y else 1

    # Scale to fit, preserving aspect ratio
    scale_x = (target_w - icon_size) / range_x if range_x > 0 else 1.0
    scale_y = (target_h - icon_size) / range_y if range_y > 0 else 1.0
    scale = min(scale_x, scale_y, 1.0)

    # Center within target area
    scaled_w = range_x * scale
    scaled_h = range_y * scale
    offset_x = target_x + (target_w - scaled_w - icon_size) / 2
    offset_y = target_y + (target_h - scaled_h - icon_size) / 2

    nodes_out = {}
    for nid, (rx, ry) in positions.items():
        nx = round(offset_x + (rx - min_x) * scale)
        ny = round(offset_y + (ry - min_y) * scale)
        node_def = node_defs.get(nid, {})
        nodes_out[nid] = {
            "x": nx, "y": ny,
            "width": icon_size, "height": icon_size,
            "icon": node_def.get("icon", ""),
            "label": node_def.get("label", nid),
        }

    # --- Phase 3: Build groups ---
    groups_out = {}
    for gdef in group_defs:
        gid = gdef["id"]
        gnodes = gdef.get("nodes", [])
        contained = [nodes_out[nid] for nid in gnodes if nid in nodes_out]
        if not contained:
            continue
        pad_x, pad_top, pad_bot = 35, 55, 35
        gx = min(n["x"] for n in contained) - pad_x
        gy = min(n["y"] for n in contained) - pad_top
        gx2 = max(n["x"] + n["width"] for n in contained) + pad_x
        gy2 = max(n["y"] + n["height"] for n in contained) + pad_bot
        groups_out[gid] = {
            "x": gx, "y": gy,
            "width": gx2 - gx, "height": gy2 - gy,
            "label": gdef.get("label", gid),
            "groupType": f"generic-{gdef.get('style', 'dashed')}",
            "children": gnodes,
        }

    # --- Phase 4: Route connections ---
    connections = []
    for e in edges:
        conn = {"from": e["from"], "to": e["to"]}
        src = nodes_out.get(e["from"])
        dst = nodes_out.get(e["to"])
        if src and dst:
            sides = _compute_sides(src, dst)
            conn["srcSide"] = sides[0]
            conn["dstSide"] = sides[1]
        connections.append(conn)
    edges_out = _layout_route_connections(connections, nodes_out, groups_out)

    edge_map = {(e["from"], e["to"]): e for e in edges}
    for eo in edges_out:
        edef = edge_map.get((eo["from"], eo["to"]), {})
        if edef.get("label"):
            eo["label"] = edef["label"]
        if edef.get("lineWidth"):
            eo["lineWidth"] = edef["lineWidth"]

    # --- Phase 5: Build elements ---
    elements = _build_elements(nodes_out, groups_out, edges_out)
    return elements, nodes_out, groups_out


def _solve_constraints(node_ids, constraints, icon_size, gap_h, gap_v):
    """Solve positional constraints using iterative relaxation.

    Strategy: list constraints establish structure, then relative/align
    constraints adjust positions without breaking list structure.
    """
    pos = {nid: [0.0, 0.0] for nid in node_ids}

    # Track which axis is locked per node (from list constraints)
    x_locked = {}  # nid → list_id (nodes in h_list have locked relative X)
    y_locked = {}  # nid → list_id (nodes in v_list have locked relative Y)
    list_groups = []  # (axis, nodes, gap)

    # Phase 1: Apply list constraints — these define relative positions within groups
    for ci, c in enumerate(constraints):
        ctype = c["type"]
        if ctype == "h_list":
            nodes = c["nodes"]
            g = c.get("gap", gap_h)
            base_x = pos[nodes[0]][0]
            for i, nid in enumerate(nodes):
                pos[nid][0] = base_x + i * (icon_size + g)
                x_locked[nid] = ci
            list_groups.append(("x", nodes, g))
        elif ctype == "v_list":
            nodes = c["nodes"]
            g = c.get("gap", gap_v)
            base_y = pos[nodes[0]][1]
            for i, nid in enumerate(nodes):
                pos[nid][1] = base_y + i * (icon_size + g)
                y_locked[nid] = ci
            list_groups.append(("y", nodes, g))

    # Phase 2: Iteratively apply relative and alignment constraints
    # These move entire groups when a node belongs to a list
    for _ in range(20):
        for c in constraints:
            ctype = c["type"]
            if ctype == "above":
                node, target = c["node"], c["target"]
                needed_y = pos[target][1] - icon_size - gap_v
                if pos[node][1] > needed_y:
                    _shift_node_y(pos, node, needed_y, y_locked, list_groups)
            elif ctype == "below":
                node, target = c["node"], c["target"]
                needed_y = pos[target][1] + icon_size + gap_v
                if pos[node][1] < needed_y:
                    _shift_node_y(pos, node, needed_y, y_locked, list_groups)
            elif ctype == "right_of":
                node, target = c["node"], c["target"]
                needed_x = pos[target][0] + icon_size + gap_h
                if pos[node][0] < needed_x:
                    _shift_node_x(pos, node, needed_x, x_locked, list_groups)
            elif ctype == "left_of":
                node, target = c["node"], c["target"]
                needed_x = pos[target][0] - icon_size - gap_h
                if pos[node][0] > needed_x:
                    _shift_node_x(pos, node, needed_x, x_locked, list_groups)
            elif ctype == "align_y":
                nodes = c["nodes"]
                avg_y = sum(pos[n][1] for n in nodes) / len(nodes)
                for n in nodes:
                    _shift_node_y(pos, n, avg_y, y_locked, list_groups)
            elif ctype == "align_x":
                nodes = c["nodes"]
                avg_x = sum(pos[n][0] for n in nodes) / len(nodes)
                for n in nodes:
                    _shift_node_x(pos, n, avg_x, x_locked, list_groups)

    # Phase 3: Resolve overlaps — push overlapping nodes apart
    node_list = list(pos.keys())
    for _ in range(20):
        moved = False
        for i in range(len(node_list)):
            for j in range(i + 1, len(node_list)):
                a, b = node_list[i], node_list[j]
                dx = abs(pos[a][0] - pos[b][0])
                dy = abs(pos[a][1] - pos[b][1])
                if dx < icon_size * 0.9 and dy < icon_size * 0.9:
                    # Push apart in the axis with more freedom
                    if a not in x_locked and b not in x_locked:
                        pos[b][0] += icon_size + gap_h * 0.5
                        moved = True
                    elif a not in y_locked and b not in y_locked:
                        pos[b][1] += icon_size + gap_v * 0.5
                        moved = True
                    else:
                        # Both locked — push the unlocked axis
                        if a not in x_locked:
                            pos[a][0] -= icon_size + gap_h * 0.5
                            moved = True
                        elif b not in x_locked:
                            pos[b][0] += icon_size + gap_h * 0.5
                            moved = True
        if not moved:
            break

    return {nid: (p[0], p[1]) for nid, p in pos.items()}


def _shift_node_x(pos, nid, new_x, x_locked, list_groups):
    """Move a node's X. If it's in an h_list, shift the whole list."""
    if nid in x_locked:
        # Find the list group and shift all members
        delta = new_x - pos[nid][0]
        for axis, nodes, gap in list_groups:
            if axis == "x" and nid in nodes:
                for n in nodes:
                    pos[n][0] += delta
                return
    pos[nid][0] = new_x


def _shift_node_y(pos, nid, new_y, y_locked, list_groups):
    """Move a node's Y. If it's in a v_list, shift the whole list."""
    if nid in y_locked:
        delta = new_y - pos[nid][1]
        for axis, nodes, gap in list_groups:
            if axis == "y" and nid in nodes:
                for n in nodes:
                    pos[n][1] += delta
                return
    pos[nid][1] = new_y


def _compute_sides(src, dst):
    """Determine optimal connection sides based on relative positions."""
    src_cx = src["x"] + src["width"] / 2
    src_cy = src["y"] + src["height"] / 2
    dst_cx = dst["x"] + dst["width"] / 2
    dst_cy = dst["y"] + dst["height"] / 2

    dx = dst_cx - src_cx
    dy = dst_cy - src_cy
    adx = abs(dx)
    ady = abs(dy)

    if adx > ady * 0.7:
        return ("right", "left") if dx > 0 else ("left", "right")
    if ady > adx * 0.7:
        return ("bottom", "top") if dy > 0 else ("top", "bottom")
    if dx > 0:
        return ("right", "left")
    if dy > 0:
        return ("bottom", "top")
    return ("top", "bottom")


def _build_elements(nodes_out, groups_out, edges_out):
    """Convert to sdpm elements array."""
    elements = []

    for _, g in sorted(groups_out.items(), key=lambda x: -x[1]["width"] * x[1]["height"]):
        gt = g.get("groupType")
        if not gt:
            continue
        elements.append({
            "type": "arch-group", "groupType": gt,
            "x": g["x"], "y": g["y"],
            "width": g["width"], "height": g["height"],
            "label": g.get("label", ""),
        })

    for nid, n in nodes_out.items():
        if n.get("icon"):
            elements.append({
                "type": "image", "src": n["icon"],
                "x": n["x"], "y": n["y"], "width": n["width"],
                "label": n.get("label", nid), "labelPosition": "bottom",
            })

    for e in edges_out:
        pts = e["points"]
        if len(pts) < 2:
            continue
        sx, sy = pts[0]
        ex, ey = pts[-1]

        is_detour = (len(pts) >= 4 and pts[0][1] == pts[-1][1]
                     and any(p[1] != pts[0][1] for p in pts[1:-1]))
        if is_detour or len(pts) >= 6:
            el = {"type": "line", "arrowEnd": "arrow",
                  "points": [[p[0], p[1]] for p in pts]}
        else:
            el = {"type": "line", "x1": sx, "y1": sy, "x2": ex, "y2": ey, "arrowEnd": "arrow"}
            if len(pts) > 2:
                el["connectorType"] = "elbow"
                dx = ex - sx
                dy = ey - sy
                if len(pts) >= 4 and (abs(dx) > 0 or abs(dy) > 0):
                    seg1_vert = abs(pts[0][0] - pts[1][0]) <= abs(pts[0][1] - pts[1][1])
                    if seg1_vert:
                        adj = (pts[1][1] - sy) / dy if dy != 0 else 0.5
                        el["preset"] = "bentConnector3"
                        el["elbowStart"] = "vertical"
                        el["adjustments"] = [max(-2.0, min(3.0, adj))]
                    else:
                        adj1 = (pts[1][0] - sx) / dx if dx != 0 else 0.5
                        adj2 = (pts[2][1] - sy) / dy if dy != 0 else 0.5
                        el["preset"] = "bentConnector4"
                        el["adjustments"] = [max(-1.0, min(2.0, adj1)), max(-1.0, min(2.0, adj2))]
                elif dy != 0 or dx != 0:
                    el["adjustments"] = [0.5]

        if e.get("lineWidth"):
            el["lineWidth"] = e["lineWidth"]
        elements.append(el)

        label = e.get("label", "")
        if label:
            mid_idx = len(pts) // 2
            mx, my = pts[mid_idx]
            elements.append({
                "type": "text", "x": mx - 40, "y": my - 25,
                "width": 100, "body": label, "fontSize": 10,
            })

    return elements
