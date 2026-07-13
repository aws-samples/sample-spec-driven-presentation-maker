# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Diagram model helpers: node/group lookup, port geometry, elbow paths
and box-node element generation.
"""



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


def _find_group(groups, gid):
    """Resolve a group by id (qualified or short), if groups is provided."""
    if not groups:
        return None
    if gid in groups:
        return groups[gid]
    for g_id, g in groups.items():
        if g_id.endswith("." + gid):
            return g
    return None


def _find_endpoint(nodes, groups, eid):
    """Resolve a connection endpoint that may be a node OR a group.

    Returns (geom, is_group): geom is a dict with x/y/width/height (both nodes
    and laid-out groups carry these), is_group flags a group target so callers
    can treat the box edge as the port and skip the group's own children as
    obstacles. A node takes precedence over a group with the same id.
    """
    n = _find_node(nodes, eid)
    if n is not None:
        return n, False
    g = _find_group(groups, eid)
    if g is not None:
        return g, True
    return None, False


def _group_qualified_id(groups, gid):
    """Return the fully-qualified key of group gid in the flat groups dict."""
    if not groups:
        return None
    if gid in groups:
        return gid
    for g_id in groups:
        if g_id.endswith("." + gid):
            return g_id
    return None


def _group_member_ids(nodes, groups, gid):
    """Short ids of all leaf nodes inside group gid (for obstacle exclusion).

    The collected `groups` dict stores children as qualified id strings, and
    every leaf node inside the group is a key in `nodes` prefixed by the
    group's qualified id. We match on that prefix.
    """
    qid = _group_qualified_id(groups, gid)
    if not qid:
        return set()
    prefix = qid + "."
    out = set()
    for nid in nodes:
        if nid == qid or nid.startswith(prefix):
            out.add(nid.rsplit(".", 1)[-1])
    return out


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


def _fix_bends_inside_nodes(edges, nodes, connections):
    """Post-process: fix bends that pass through or graze node icons.

    Checks intermediate points AND segments between them. If a vertical
    segment at x=N would pass through a node's x-range and y-range,
    shift the bend X to avoid it.
    """
    margin = 15
    for ei, e in enumerate(edges):
        pts = e["points"]
        if len(pts) < 3:
            continue
        src_id = e.get("from", "")
        dst_id = e.get("to", "")
        for nid, n in nodes.items():
            if nid == src_id or nid == dst_id:
                continue
            nx, ny = n["x"], n["y"]
            nw = n.get("width", 60)
            nh = n.get("height", 60)
            # Check intermediate segments (between first and last segments)
            for k in range(1, len(pts) - 2):
                p1 = pts[k]
                p2 = pts[k + 1]
                # Vertical segment: same X, check if it passes through node
                if abs(p1[0] - p2[0]) < 3:
                    seg_x = p1[0]
                    seg_y_lo = min(p1[1], p2[1])
                    seg_y_hi = max(p1[1], p2[1])
                    if (nx - margin < seg_x < nx + nw + margin and
                            seg_y_lo < ny + nh + margin and seg_y_hi > ny - margin):
                        new_x = nx - margin - 5
                        # Shift both points of this vertical segment
                        pts[k] = [new_x, pts[k][1]]
                        pts[k+1] = [new_x, pts[k+1][1]]
                        # Also fix the adjacent horizontal segments to stay connected
                        if k > 0 and abs(pts[k-1][1] - pts[k][1]) < 3:
                            pts[k-1] = [pts[k-1][0], pts[k][1]]
                        if k + 2 < len(pts) and abs(pts[k+1][1] - pts[k+2][1]) < 3:
                            pts[k+2] = [pts[k+2][0], pts[k+1][1]]
                        break
                # Horizontal segment: same Y, check if it passes through node
                elif abs(p1[1] - p2[1]) < 3:
                    seg_y = p1[1]
                    seg_x_lo = min(p1[0], p2[0])
                    seg_x_hi = max(p1[0], p2[0])
                    if (ny - margin < seg_y < ny + nh + margin and
                            seg_x_lo < nx + nw + margin and seg_x_hi > nx - margin):
                        new_y = ny - margin - 5
                        pts[k] = [pts[k][0], new_y]
                        pts[k+1] = [pts[k+1][0], new_y]
                        # Fix adjacent vertical segments
                        if k > 0 and abs(pts[k-1][0] - pts[k][0]) < 3:
                            pts[k-1] = [pts[k][0], pts[k-1][1]]
                        if k + 2 < len(pts) and abs(pts[k+1][0] - pts[k+2][0]) < 3:
                            pts[k+2] = [pts[k+1][0], pts[k+2][1]]
                        break


SNAP_THRESHOLD = 5
MIN_BEND_MARGIN = 20
OBSTACLE_MARGIN = 10


def _calc_bend(val, lo, hi, obstacles, axis):
    """Calculate bend position avoiding obstacle boundaries and interiors."""
    val = max(val, lo + MIN_BEND_MARGIN)
    val = min(val, hi - MIN_BEND_MARGIN)
    for obs in obstacles:
        if axis == "x":
            edge_lo, edge_hi = obs["x"] - OBSTACLE_MARGIN, obs["x"] + obs["width"] + OBSTACLE_MARGIN
        else:
            edge_lo, edge_hi = obs["y"] - OBSTACLE_MARGIN, obs["y"] + obs["height"] + OBSTACLE_MARGIN
        if edge_lo < val < edge_hi:
            # Bend is inside obstacle — move to nearest edge outside
            dist_to_lo = val - edge_lo
            dist_to_hi = edge_hi - val
            if dist_to_lo <= dist_to_hi:
                val = edge_lo - 5
            else:
                val = edge_hi + 5
    val = max(val, lo + MIN_BEND_MARGIN)
    val = min(val, hi - MIN_BEND_MARGIN)
    return val


_DETOUR_MARGIN = 40


def _detour_path(sp, tp, src_side, dst_side, global_bottom):
    """Generate a U-shaped detour path for reverse-flow connections.

    Routes below all nodes: src → down → across → up → dst
    Always produces a 4-point path (コの字):
      [src] → [src_x, bottom] → [dst_x, bottom] → [dst]
    """
    sx, sy = sp
    tx, ty = tp
    bottom_y = global_bottom + _DETOUR_MARGIN

    # Always route: straight down from src, horizontal across bottom, straight up to dst
    return [[sx, sy], [sx, bottom_y], [tx, bottom_y], [tx, ty]]


def _elbow_path(sp, tp, src_side, dst_side, obstacles=None):
    obstacles = obstacles or []
    sx, sy = sp
    tx, ty = tp
    if src_side in ("left", "right") and dst_side in ("left", "right"):
        if abs(sy - ty) <= SNAP_THRESHOLD:
            return [[sx, sy], [tx, sy]]
        mx = _calc_bend((sx + tx) // 2, min(sx, tx), max(sx, tx), obstacles, "x")
        return [[sx, sy], [mx, sy], [mx, ty], [tx, ty]]
    if src_side in ("top", "bottom") and dst_side in ("top", "bottom"):
        if abs(sx - tx) <= SNAP_THRESHOLD:
            return [[sx, sy], [sx, ty]]
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
