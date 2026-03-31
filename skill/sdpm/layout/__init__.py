# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Layout engine: compute coordinates from logical structure JSON."""


def _layout_scale(node, parent_dir="horizontal", parent_align="center", spacing_scale_h=1.0, spacing_scale_v=1.0):
    """Recursive layout engine. Calculates bindings (x, y, width, height) for each node bottom-up."""
    children = node.get("children", [])
    direction = node.get("direction", parent_dir)
    align = node.get("align", parent_align)
    is_group = len(children) > 0
    icon_size = node.get("iconSize", 60)

    def sh(v):
        return max(10, round(v * spacing_scale_h))
    def sv(v):
        return max(10, round(v * spacing_scale_v))

    if is_group:
        margin = node.get("margin", {"top": sv(20), "right": sh(20), "bottom": sv(20), "left": sh(20)})
        padding = node.get("padding", {"top": sv(70), "right": sh(30), "bottom": sv(30), "left": sh(30)})
    else:
        box = node.get("box")
        if box:
            bw = box.get("width", 240)
            if "height" in box:
                bh = box["height"]
            else:
                char_per_line = max(1, bw // 10)
                lines = 0
                for field in [box.get("sublabel"), box.get("title", node.get("id", "")), box.get("description")]:
                    if field:
                        for paragraph in str(field).split("\n"):
                            lines += max(1, -(-len(paragraph) // char_per_line))
                bh = lines * 24 + 40
            margin = node.get("margin", {"top": sv(20), "right": sh(20), "bottom": sv(20), "left": sh(20)})
            padding = {"top": 0, "right": 0, "bottom": 0, "left": 0}
            node["_bindings"] = [0, 0, bw, bh]
            node["_margin"] = margin
            node["_padding"] = padding
            return
        label_h = sv(35)
        raw_label = node.get("label", "")
        label_lines = raw_label.replace("\\n", "\n").split("\n")
        label_w = max((len(line) * 8 for line in label_lines), default=0)
        label_h = sv(35) + (len(label_lines) - 1) * sv(18)
        half_label_overhang = max(0, (label_w - icon_size) // 2)
        margin = node.get("margin", {"top": sv(20), "right": max(sh(20), half_label_overhang + 5), "bottom": label_h + sv(10), "left": max(sh(20), half_label_overhang + 5)})
        padding = {"top": 0, "right": 0, "bottom": 0, "left": 0}
        node["_bindings"] = [0, 0, icon_size, icon_size]
        node["_margin"] = margin
        node["_padding"] = padding
        return

    for child in children:
        _layout_scale(child, direction, align, spacing_scale_h, spacing_scale_v)

    reverse = node.get("reverse", False)
    ordered = list(reversed(children)) if reverse else children
    for i, child in enumerate(ordered):
        cb = child["_bindings"]
        cm = child["_margin"]
        if i == 0:
            dx = cm["left"] - cb[0]
            dy = cm["top"] - cb[1]
            _layout_translate(child, dx, dy)
        else:
            prev = ordered[i - 1]
            pb = prev["_bindings"]
            pm = prev["_margin"]
            cb = child["_bindings"]
            if direction == "horizontal":
                nx = pb[0] + pb[2] + pm["right"] + cm["left"]
                if align == "top":
                    ny = ordered[0]["_bindings"][1]
                elif align == "bottom":
                    ny = pb[0 + 1] + pb[3] - cb[3]
                else:
                    ny = pb[1] + (pb[3] - cb[3]) // 2
                _layout_translate(child, nx - cb[0], ny - cb[1])
            else:
                ny = pb[1] + pb[3] + pm["bottom"] + cm["top"]
                if align == "left":
                    nx = ordered[0]["_bindings"][0]
                elif align == "right":
                    nx = pb[0] + pb[2] - cb[2]
                else:
                    nx = pb[0] + (pb[2] - cb[2]) // 2
                _layout_translate(child, nx - cb[0], ny - cb[1])

    min_x = min(c["_bindings"][0] - c["_margin"]["left"] for c in children)
    min_y = min(c["_bindings"][1] - c["_margin"]["top"] for c in children)
    max_x = max(c["_bindings"][0] + c["_bindings"][2] + c["_margin"]["right"] for c in children)
    max_y = max(c["_bindings"][1] + c["_bindings"][3] + c["_margin"]["bottom"] for c in children)

    gx = min_x - padding["left"]
    gy = min_y - padding["top"]
    gw = (max_x - min_x) + padding["left"] + padding["right"]
    gh = (max_y - min_y) + padding["top"] + padding["bottom"]

    node["_bindings"] = [gx, gy, gw, gh]
    node["_margin"] = margin
    node["_padding"] = padding


def _layout_translate(node, dx, dy):
    """Translate node and all descendants by (dx, dy)."""
    b = node["_bindings"]
    node["_bindings"] = [b[0] + dx, b[1] + dy, b[2], b[3]]
    for child in node.get("children", []):
        _layout_translate(child, dx, dy)


def _layout_collect(node, nodes_out, groups_out, prefix=""):
    """Collect flat node/group dicts from tree."""
    nid = prefix + node["id"] if prefix else node["id"]
    b = node["_bindings"]
    entry = {"x": b[0], "y": b[1], "width": b[2], "height": b[3]}
    if node.get("label"):
        entry["label"] = node["label"]
    children = node.get("children", [])
    if children:
        child_ids = [prefix + node["id"] + "." + c["id"] if prefix else node["id"] + "." + c["id"] for c in children]
        entry["children"] = child_ids
        entry["direction"] = node.get("direction", "horizontal")
        pad = node.get("_padding", {})
        entry["_padding"] = pad
        if node.get("groupType"):
            entry["groupType"] = node["groupType"]
        groups_out[nid] = entry
        for child in children:
            _layout_collect(child, nodes_out, groups_out, nid + ".")
    else:
        if node.get("icon"):
            entry["icon"] = node["icon"]
        if node.get("box"):
            entry["box"] = node["box"]
        nodes_out[nid] = entry


def _layout_route_connections(connections, nodes, groups=None):
    """Route connections between nodes. Returns list of edge dicts with points."""
    groups = groups or {}
    # Build node-to-group mapping and obstacle list
    node_group = {}
    for gid, g in groups.items():
        for cid in g.get("children", []):
            node_group[cid] = gid
    obstacles = [{"x": g["x"], "y": g["y"], "width": g["width"], "height": g["height"]} for g in groups.values()]

    port_counts = {}
    port_indices = {}

    conn_sides = []
    for conn in connections:
        src = _find_node(nodes, conn["from"])
        dst = _find_node(nodes, conn["to"])
        if not src or not dst:
            conn_sides.append((None, None, None, None))
            continue
        # Determine group direction if both nodes share a parent group
        group_dir = None
        src_gid = _find_group_for(conn["from"], node_group)
        dst_gid = _find_group_for(conn["to"], node_group)
        if src_gid and src_gid == dst_gid:
            group_dir = groups[src_gid].get("direction", "horizontal")
        src_side, dst_side = _auto_sides(src, dst, group_dir)
        conn_sides.append((src, dst, src_side, dst_side))
        sk = (conn["from"], src_side)
        dk = (conn["to"], dst_side)
        port_counts[sk] = port_counts.get(sk, 0) + 1
        port_counts[dk] = port_counts.get(dk, 0) + 1

    port_cursors = {}
    for i, (src, dst, src_side, dst_side) in enumerate(conn_sides):
        if src is None:
            continue
        for nid, side in [(connections[i]["from"], src_side), (connections[i]["to"], dst_side)]:
            k = (nid, side)
            port_cursors[k] = port_cursors.get(k, 0)
            port_indices[(i, nid)] = port_cursors[k]
            port_cursors[k] += 1

    edges = []
    for i, conn in enumerate(connections):
        src, dst, src_side, dst_side = conn_sides[i]
        if src is None:
            edges.append({"from": conn["from"], "to": conn["to"], "label": conn.get("label", ""), "points": []})
            continue
        label_h = 30 if src.get("label") else 0
        sp = _port_point(src, src_side, port_indices[(i, conn["from"])], port_counts[(conn["from"], src_side)], label_h)
        tp = _port_point(dst, dst_side, port_indices[(i, conn["to"])], port_counts[(conn["to"], dst_side)], label_h)
        points = _elbow_path(sp, tp, src_side, dst_side, obstacles)
        edges.append({"from": conn["from"], "to": conn["to"], "label": conn.get("label", ""), "points": points})

    # T8: Align bend positions for fan-out (same src+side) and fan-in (same dst+side)
    _align_fan_bends(edges, conn_sides, connections)

    return edges


# Max spread between dst (or src) centers to allow grouping
_FAN_SPREAD_LIMIT = 600


def _align_fan_bends(edges, conn_sides, connections):
    """Align bend positions and merge ports for fan-out and fan-in groups."""
    # Fan-out: same src + same src_side
    src_groups = {}
    for i, (src, dst, src_side, dst_side) in enumerate(conn_sides):
        if src is None or len(edges[i]["points"]) <= 2:
            continue
        k = (connections[i]["from"], src_side)
        src_groups.setdefault(k, []).append(i)

    for indices in src_groups.values():
        if len(indices) < 2:
            continue
        _rewrite_fan(edges, conn_sides, indices, mode="fan_out")

    # Fan-in: same dst + same dst_side
    dst_groups = {}
    for i, (src, dst, src_side, dst_side) in enumerate(conn_sides):
        if src is None or len(edges[i]["points"]) <= 2:
            continue
        k = (connections[i]["to"], dst_side)
        dst_groups.setdefault(k, []).append(i)

    for indices in dst_groups.values():
        if len(indices) < 2:
            continue
        _rewrite_fan(edges, conn_sides, indices, mode="fan_in")


_FAN_BEND_MARGIN = 30


def _rewrite_fan(edges, conn_sides, indices, mode):
    """Rewrite fan-out/fan-in elbows: unified trunk port + bend near targets."""
    _, _, src_side, dst_side = conn_sides[indices[0]]
    vertical = (src_side if mode == "fan_out" else dst_side) in ("top", "bottom")

    # Check spread limit
    if mode == "fan_out":
        targets = [edges[i]["points"][-1] for i in indices]
    else:
        targets = [edges[i]["points"][0] for i in indices]
    coords = [t[0 if vertical else 1] for t in targets]
    if max(coords) - min(coords) > _FAN_SPREAD_LIMIT:
        return

    # Pre-compute unified port center
    if mode == "fan_out":
        all_ports = [edges[j]["points"][0] for j in indices]
    else:
        all_ports = [edges[j]["points"][-1] for j in indices]
    if vertical:
        port_center = sum(p[0] for p in all_ports) // len(all_ports)
    else:
        port_center = sum(p[1] for p in all_ports) // len(all_ports)

    for i in indices:
        pts = edges[i]["points"]
        if len(pts) < 4:
            continue
        src_pt = list(pts[0])
        dst_pt = list(pts[-1])

        if mode == "fan_out":
            if vertical:
                bend_y = dst_pt[1] - _FAN_BEND_MARGIN
                pts[0] = [port_center, src_pt[1]]
                pts[1] = [port_center, bend_y]
                pts[2] = [dst_pt[0], bend_y]
                pts[3] = [dst_pt[0], dst_pt[1]]
            else:
                bend_x = dst_pt[0] - _FAN_BEND_MARGIN
                pts[0] = [src_pt[0], port_center]
                pts[1] = [bend_x, port_center]
                pts[2] = [bend_x, dst_pt[1]]
                pts[3] = [dst_pt[0], dst_pt[1]]
        else:
            if vertical:
                bend_y = src_pt[1] + _FAN_BEND_MARGIN
                pts[0] = [src_pt[0], src_pt[1]]
                pts[1] = [src_pt[0], bend_y]
                pts[2] = [port_center, bend_y]
                pts[3] = [port_center, dst_pt[1]]
            else:
                bend_x = src_pt[0] + _FAN_BEND_MARGIN
                pts[0] = [src_pt[0], src_pt[1]]
                pts[1] = [bend_x, src_pt[1]]
                pts[2] = [bend_x, port_center]
                pts[3] = [dst_pt[0], port_center]


def _find_group_for(node_id, node_group):
    """Find parent group id for a node, handling qualified ids."""
    if node_id in node_group:
        return node_group[node_id]
    for nid, gid in node_group.items():
        if nid.endswith("." + node_id):
            return gid
    return None


def _find_node(nodes, node_id):
    if node_id in nodes:
        return nodes[node_id]
    for nid, n in nodes.items():
        if nid.endswith("." + node_id):
            return n
    return None


def _auto_sides(src, dst, group_direction=None):
    if group_direction == "horizontal":
        sx = src["x"] + src["width"] // 2
        dx = dst["x"] + dst["width"] // 2
        return ("right", "left") if dx > sx else ("left", "right")
    if group_direction == "vertical":
        sy = src["y"] + src["height"] // 2
        dy = dst["y"] + dst["height"] // 2
        return ("bottom", "top") if dy > sy else ("top", "bottom")
    sx = src["x"] + src["width"] // 2
    sy = src["y"] + src["height"] // 2
    dx = dst["x"] + dst["width"] // 2
    dy = dst["y"] + dst["height"] // 2
    diffx, diffy = dx - sx, dy - sy
    # Prefer vertical when dx and dy are close (within 30% ratio)
    # This produces more natural top-down flow in diagrams
    if abs(diffy) > 0 and abs(diffx) / abs(diffy) < 1.3:
        return ("bottom", "top") if diffy > 0 else ("top", "bottom")
    if abs(diffx) >= abs(diffy):
        return ("right", "left") if diffx > 0 else ("left", "right")
    else:
        return ("bottom", "top") if diffy > 0 else ("top", "bottom")


def _port_point(node, side, index, count, label_h):
    x, y, w, h = node["x"], node["y"], node["width"], node["height"]
    t = 0.5 if count <= 1 else (index + 1) / (count + 1)
    if side == "right":
        return [x + w, round(y + h * t)]
    elif side == "left":
        return [x, round(y + h * t)]
    elif side == "bottom":
        return [round(x + w * t), y + h + label_h]
    else:
        return [round(x + w * t), y]


SNAP_THRESHOLD = 15
MIN_BEND_MARGIN = 20
OBSTACLE_MARGIN = 10


def _calc_bend(val, lo, hi, obstacles, axis):
    """Calculate bend position avoiding obstacle boundaries."""
    val = max(val, lo + MIN_BEND_MARGIN)
    val = min(val, hi - MIN_BEND_MARGIN)
    for obs in obstacles:
        if axis == "x":
            edge_lo, edge_hi = obs["x"], obs["x"] + obs["width"]
        else:
            edge_lo, edge_hi = obs["y"], obs["y"] + obs["height"]
        if abs(val - edge_lo) <= OBSTACLE_MARGIN:
            val = edge_lo - OBSTACLE_MARGIN - 5
        elif abs(val - edge_hi) <= OBSTACLE_MARGIN:
            val = edge_hi + OBSTACLE_MARGIN + 5
    return val


def _elbow_path(sp, tp, src_side, dst_side, obstacles=None):
    obstacles = obstacles or []
    sx, sy = sp
    tx, ty = tp
    if src_side in ("left", "right") and dst_side in ("left", "right"):
        if abs(sy - ty) <= SNAP_THRESHOLD:
            mid_y = (sy + ty) // 2
            return [[sx, mid_y], [tx, mid_y]]
        mx = _calc_bend((sx + tx) // 2, min(sx, tx), max(sx, tx), obstacles, "x")
        return [[sx, sy], [mx, sy], [mx, ty], [tx, ty]]
    if src_side in ("top", "bottom") and dst_side in ("top", "bottom"):
        if abs(sx - tx) <= SNAP_THRESHOLD:
            mid_x = (sx + tx) // 2
            return [[mid_x, sy], [mid_x, ty]]
        my = _calc_bend((sy + ty) // 2, min(sy, ty), max(sy, ty), obstacles, "y")
        return [[sx, sy], [sx, my], [tx, my], [tx, ty]]
    if src_side in ("left", "right"):
        return [[sx, sy], [tx, sy], [tx, ty]]
    else:
        return [[sx, sy], [sx, ty], [tx, ty]]


def box_to_elements(nid, node, is_dark=True):
    """Convert box node to shape + textbox elements."""
    box = node["box"]
    x, y, w, h = node["x"], node["y"], node["width"], node["height"]
    color = box.get("color", "#438DD5")
    line_color = box.get("line", color)

    shape = {
        "type": "shape", "shape": "rounded_rectangle",
        "x": x, "y": y, "width": w, "height": h,
        "fill": color, "opacity": 0.18,
        "line": line_color, "lineWidth": 1.2,
        "adjustments": [0.07], "shadow": "sm",
    }

    label_color = "#FFFFFF" if is_dark else "#000000"
    sub_color = "#8FA7C4" if is_dark else "#5A6B7D"
    desc_color = "#7A8B9C" if is_dark else "#6B7C8D"

    parts = []
    sublabel = box.get("sublabel")
    if sublabel:
        parts.append("{{" + sub_color + ":" + sublabel + "}}")
    label = box.get("title", nid)
    parts.append("{{bold," + label_color + ":" + label + "}}")
    description = box.get("description")
    if description:
        parts.append("{{" + desc_color + ":" + description + "}}")

    textbox = {
        "type": "textbox",
        "x": x, "y": y, "width": w, "height": h,
        "align": "center", "valign": "middle",
        "fontSize": 11, "text": "\n".join(parts),
    }

    return [shape, textbox]
