# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Geometric predicates and defect counting: segment intersection,
crossing pairs, node/group pierces, backwards segments, port sides.
"""

from .model import _find_node, _group_member_ids




def _perp_touch(v_x, h_y, h_x_min, h_x_max, v_y_min, v_y_max):
    """True if a vertical seg (x=v_x, y in [v_y_min,v_y_max]) and a horizontal
    seg (y=h_y, x in [h_x_min,h_x_max]) meet — counting T-junctions.

    The meeting point is (v_x, h_y). It must lie within BOTH segments' spans
    (endpoints included), and be interior to AT LEAST ONE of them. The latter
    excludes only a pure endpoint-to-endpoint touch (two stubs meeting at a
    shared corner/port), which is not a visual crossing. A T-junction — where
    one segment's endpoint lands in the middle of the other (e.g. an arrow
    ending on a line another arrow runs along) — DOES count: the previous
    strict-interior test silently dropped these, so two arrows sharing a y and
    overlapping in x read as uncrossed when they visibly overlap.
    """
    if not (h_x_min <= v_x <= h_x_max and v_y_min <= h_y <= v_y_max):
        return False
    v_interior = v_y_min < h_y < v_y_max
    h_interior = h_x_min < v_x < h_x_max
    return v_interior or h_interior


def _segments_intersect(a1, a2, b1, b2):
    """Test if two axis-aligned segments cross or overlap (for port optimization)."""
    ax1, ay1 = a1
    ax2, ay2 = a2
    bx1, by1 = b1
    bx2, by2 = b2

    a_horiz = ay1 == ay2
    a_vert = ax1 == ax2
    b_horiz = by1 == by2
    b_vert = bx1 == bx2

    if a_horiz and b_vert:
        h_y = ay1
        h_x_min, h_x_max = min(ax1, ax2), max(ax1, ax2)
        v_x = bx1
        v_y_min, v_y_max = min(by1, by2), max(by1, by2)
        return _perp_touch(v_x, h_y, h_x_min, h_x_max, v_y_min, v_y_max)
    if a_vert and b_horiz:
        v_x = ax1
        v_y_min, v_y_max = min(ay1, ay2), max(ay1, ay2)
        h_y = by1
        h_x_min, h_x_max = min(bx1, bx2), max(bx1, bx2)
        return _perp_touch(v_x, h_y, h_x_min, h_x_max, v_y_min, v_y_max)
    if a_horiz and b_horiz and ay1 == by1:
        a_min, a_max = min(ax1, ax2), max(ax1, ax2)
        b_min, b_max = min(bx1, bx2), max(bx1, bx2)
        return min(a_max, b_max) - max(a_min, b_min) > 5
    if a_vert and b_vert and ax1 == bx1:
        a_min, a_max = min(ay1, ay2), max(ay1, ay2)
        b_min, b_max = min(by1, by2), max(by1, by2)
        return min(a_max, b_max) - max(a_min, b_min) > 5
    return False


def _find_first_crossing(edges):
    """Find the first pair of crossing segments across all edges."""
    for i in range(len(edges)):
        pts_i = edges[i]["points"]
        if len(pts_i) < 2 or edges[i].get("_fanout"):
            continue
        for j in range(i + 1, len(edges)):
            pts_j = edges[j]["points"]
            if len(pts_j) < 2 or edges[j].get("_fanout"):
                continue
            for si in range(len(pts_i) - 1):
                for sj in range(len(pts_j) - 1):
                    if _segments_intersect(pts_i[si], pts_i[si + 1], pts_j[sj], pts_j[sj + 1]):
                        return (i, si, j, sj)
    return None


def _segments_overlap_collinear(a1, a2, b1, b2):
    """True if the two axis-aligned segments lie on the same line and overlap
    (as opposed to crossing perpendicularly)."""
    if a1[1] == a2[1] and b1[1] == b2[1] and a1[1] == b1[1]:  # both horizontal, same Y
        a_min, a_max = min(a1[0], a2[0]), max(a1[0], a2[0])
        b_min, b_max = min(b1[0], b2[0]), max(b1[0], b2[0])
        return min(a_max, b_max) - max(a_min, b_min) > 5
    if a1[0] == a2[0] and b1[0] == b2[0] and a1[0] == b1[0]:  # both vertical, same X
        a_min, a_max = min(a1[1], a2[1]), max(a1[1], a2[1])
        b_min, b_max = min(b1[1], b2[1]), max(b1[1], b2[1])
        return min(a_max, b_max) - max(a_min, b_min) > 5
    return False


def _segments_cross(a1, a2, b1, b2):
    """Test if two axis-aligned line segments (a1-a2) and (b1-b2) cross or overlap.

    Detects:
    1. Perpendicular crossings (one horizontal, one vertical)
    2. Collinear overlap (parallel segments sharing the same axis with overlapping range)

    Used by the builder's conservative edge-crossing warning. Distinct from
    ``_segments_intersect`` (which counts T-junctions via ``_perp_touch``): this
    one uses strict interior ``<`` on both segments so a shared endpoint does not
    read as a crossing.
    """
    ax1, ay1 = a1
    ax2, ay2 = a2
    bx1, by1 = b1
    bx2, by2 = b2

    a_horiz = ay1 == ay2
    a_vert = ax1 == ax2
    b_horiz = by1 == by2
    b_vert = bx1 == bx2

    # Perpendicular crossings
    if a_horiz and b_vert:
        h_y = ay1
        h_x_min, h_x_max = min(ax1, ax2), max(ax1, ax2)
        v_x = bx1
        v_y_min, v_y_max = min(by1, by2), max(by1, by2)
        return h_x_min < v_x < h_x_max and v_y_min < h_y < v_y_max
    if a_vert and b_horiz:
        v_x = ax1
        v_y_min, v_y_max = min(ay1, ay2), max(ay1, ay2)
        h_y = by1
        h_x_min, h_x_max = min(bx1, bx2), max(bx1, bx2)
        return h_x_min < v_x < h_x_max and v_y_min < h_y < v_y_max

    # Collinear overlap: both horizontal on same Y
    if a_horiz and b_horiz and ay1 == by1:
        a_min, a_max = min(ax1, ax2), max(ax1, ax2)
        b_min, b_max = min(bx1, bx2), max(bx1, bx2)
        overlap = min(a_max, b_max) - max(a_min, b_min)
        return overlap > 5

    # Collinear overlap: both vertical on same X
    if a_vert and b_vert and ax1 == bx1:
        a_min, a_max = min(ay1, ay2), max(ay1, ay2)
        b_min, b_max = min(by1, by2), max(by1, by2)
        overlap = min(a_max, b_max) - max(a_min, b_min)
        return overlap > 5

    return False


def _find_crossing_pairs(edges):
    """Return the set of edge-index pairs (i, j) that genuinely cross.

    This is the single source of truth for "do two edges cross"; both the QA
    metric (:func:`_count_all_crossings`, which just takes ``len``) and the
    builder's human-readable warning consume it, so the two can never disagree.

    Two edges that SHARE an endpoint node (a fan-out from the same source or a
    fan-in to the same target) are allowed to run on top of each other on their
    shared trunk — that overlap IS the merged bundle, not a crossing. So for
    such pairs we ignore collinear overlaps and only count a genuine
    perpendicular crossing. Unrelated edges still count overlaps (two separate
    arrows drawn on the same line read as a defect).

    Shared-endpoint pairs also produce a perpendicular T-junction where each
    spoke peels off the shared trunk at its own port — the meeting point sits at
    the spoke's true endpoint (pts[0] / pts[-1]). That T is the bundle's
    intended structure, not a crossing, so it is skipped. A meeting that is
    interior to BOTH polylines (a genuine 4-way X, e.g. two spokes crossing
    mid-span) is always counted, even for a shared-endpoint pair."""
    # Pre-compute each edge's bounding box once; two edges whose boxes don't
    # overlap can't cross, so we skip the O(segments²) inner test entirely.
    # This is the hot path (called thousands of times by the bend/side/detour
    # optimizers), so the cheap box reject saves the bulk of the work.
    boxes = []
    for e in edges:
        pts = e["points"]
        if len(pts) < 2:
            boxes.append(None)
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))

    pairs = set()
    for i in range(len(edges)):
        pts_i = edges[i]["points"]
        if len(pts_i) < 2:
            continue
        ei = edges[i]
        bi = boxes[i]
        for j in range(i + 1, len(edges)):
            pts_j = edges[j]["points"]
            if len(pts_j) < 2:
                continue
            bj = boxes[j]
            # Bounding-box reject: no overlap → no crossing.
            if bi[0] > bj[2] or bj[0] > bi[2] or bi[1] > bj[3] or bj[1] > bi[3]:
                continue
            ej = edges[j]
            shares_endpoint = (
                ei.get("from") == ej.get("from")
                or ei.get("to") == ej.get("to")
                or ei.get("from") == ej.get("to")
                or ei.get("to") == ej.get("from")
            )
            found = False
            for si in range(len(pts_i) - 1):
                if found:
                    break
                for sj in range(len(pts_j) - 1):
                    if _segments_intersect(pts_i[si], pts_i[si + 1], pts_j[sj], pts_j[sj + 1]):
                        if shares_endpoint:
                            # A shared-endpoint bundle's collinear overlap is the
                            # intended trunk, not a crossing.
                            if _segments_overlap_collinear(
                                pts_i[si], pts_i[si + 1], pts_j[sj], pts_j[sj + 1]
                            ):
                                continue
                            # Two edges of the SAME fan bundle (same shared trunk)
                            # meet where each spoke peels off that trunk — a
                            # structural T-junction, not a crossing. Skip it, but
                            # only for the trunk-peel T: a genuine interior×
                            # interior X (two spokes truly crossing mid-span) is
                            # still counted.
                            if _is_fan_trunk_t_junction(
                                ei, ej, pts_i, si, pts_j, sj
                            ):
                                continue
                        pairs.add((i, j))
                        found = True
                        break
    return pairs


def _count_all_crossings(edges):
    """Count crossing SEGMENT-pairs across all edges.

    NOTE: this counts every crossing segment-pair, so two edges that cross at
    several segments contribute more than one. That is deliberate — the whole
    order/reflow/bend search was tuned against this magnitude, so it must stay a
    segment count, NOT a distinct-edge-pair count. For the human-readable "which
    edges cross" warning use :func:`_find_crossing_pairs` (distinct edge pairs);
    both share the same per-segment skip rules so they never disagree on
    *whether* a pair crosses, only on how the total is tallied."""
    boxes = []
    for e in edges:
        pts = e["points"]
        if len(pts) < 2:
            boxes.append(None)
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))

    count = 0
    for i in range(len(edges)):
        pts_i = edges[i]["points"]
        if len(pts_i) < 2:
            continue
        ei = edges[i]
        bi = boxes[i]
        for j in range(i + 1, len(edges)):
            pts_j = edges[j]["points"]
            if len(pts_j) < 2:
                continue
            bj = boxes[j]
            if bi[0] > bj[2] or bj[0] > bi[2] or bi[1] > bj[3] or bj[1] > bi[3]:
                continue
            ej = edges[j]
            shares_endpoint = (
                ei.get("from") == ej.get("from")
                or ei.get("to") == ej.get("to")
                or ei.get("from") == ej.get("to")
                or ei.get("to") == ej.get("from")
            )
            for si in range(len(pts_i) - 1):
                for sj in range(len(pts_j) - 1):
                    if _segments_intersect(pts_i[si], pts_i[si + 1], pts_j[sj], pts_j[sj + 1]):
                        if shares_endpoint:
                            if _segments_overlap_collinear(
                                pts_i[si], pts_i[si + 1], pts_j[sj], pts_j[sj + 1]
                            ):
                                continue
                            if _is_fan_trunk_t_junction(
                                ei, ej, pts_i, si, pts_j, sj
                            ):
                                continue
                        count += 1
    return count


def _is_fan_trunk_t_junction(ei, ej, pts_i, si, pts_j, sj):
    """True if two same-bundle fan edges meet at the shared trunk as a peel-off
    T (structural), as opposed to a genuine 4-way crossing.

    Both edges must be `_fan_locked` onto the SAME bundle (same mode, axis,
    trunk coordinate, and shared port). In that bundle the trunk is the line at
    ``trunk`` on the bundle's axis; each spoke leaves the trunk perpendicular.
    Their segments meet on the trunk line. That meeting is the intended shape,
    UNLESS the meeting point is strictly interior to BOTH segments (two spokes
    crossing away from the trunk), which is a real defect and returns False.
    """
    la, lb = ei.get("_fan_locked"), ej.get("_fan_locked")
    if not la or not lb:
        return False
    if (la["mode"] != lb["mode"] or la["axis"] != lb["axis"]
            or la["trunk"] != lb["trunk"] or la["port"] != lb["port"]):
        return False  # different bundles → treat as unrelated, count normally
    a1, a2 = pts_i[si], pts_i[si + 1]
    b1, b2 = pts_j[sj], pts_j[sj + 1]
    a_h, a_v = a1[1] == a2[1], a1[0] == a2[0]
    b_h, b_v = b1[1] == b2[1], b1[0] == b2[0]
    if a_h and b_v:
        mx, my = b1[0], a1[1]
    elif a_v and b_h:
        mx, my = a1[0], b1[1]
    else:
        return False
    # The meeting must lie on the bundle's trunk line; otherwise it is two
    # spokes meeting away from the trunk (count it).
    trunk = la["trunk"]
    on_trunk = (mx == trunk) if la["axis"] == "x" else (my == trunk)
    if not on_trunk:
        return False
    # A real 4-way X (interior to both segments) is a defect even on the trunk;
    # only an endpoint-on-trunk peel-off is structural.
    a_lo_x, a_hi_x = min(a1[0], a2[0]), max(a1[0], a2[0])
    a_lo_y, a_hi_y = min(a1[1], a2[1]), max(a1[1], a2[1])
    b_lo_x, b_hi_x = min(b1[0], b2[0]), max(b1[0], b2[0])
    b_lo_y, b_hi_y = min(b1[1], b2[1]), max(b1[1], b2[1])
    interior_a = a_lo_x < mx < a_hi_x or a_lo_y < my < a_hi_y
    interior_b = b_lo_x < mx < b_hi_x or b_lo_y < my < b_hi_y
    return not (interior_a and interior_b)


# Negative inset = a keep-out margin AROUND each icon. A line running along or
# just outside an icon's edge reads visually as touching/piercing it, so we
# count it as a pierce and push it away. Kept small so legitimate adjacent
# perpendicular stubs are not over-constrained.
_PIERCE_INSET = -9
_PIERCE_WEIGHT = 4


def _seg_pierces_node(p1, p2, n):
    """True if axis-aligned segment p1-p2 passes through (or grazes) node n.

    A negative _PIERCE_INSET expands the test rectangle beyond the icon so
    segments running flush against an edge are flagged, matching what reads
    visually as touching the icon.
    """
    rx, ry = n["x"], n["y"]
    rw, rh = n.get("width", 60), n.get("height", n.get("width", 60))
    x0, y0 = rx + _PIERCE_INSET, ry + _PIERCE_INSET
    x1, y1 = rx + rw - _PIERCE_INSET, ry + rh - _PIERCE_INSET
    ax, ay = p1
    bx, by = p2
    if ax == bx:  # vertical
        return x0 < ax < x1 and min(ay, by) < y1 and max(ay, by) > y0
    if ay == by:  # horizontal
        return y0 < ay < y1 and min(ax, bx) < x1 and max(ax, bx) > x0
    return False


def _count_node_pierces(edges, nodes):
    """Count (edge, node) pairs where an edge passes through a non-endpoint icon."""
    # Pre-compute each node's short id and its expanded pierce box ONCE (this is
    # a hot path called thousands of times by the optimizers). The old code
    # recomputed nid.rsplit and the box for every (edge, node) pair — millions
    # of times on a dense diagram.
    node_info = []
    for nid, n in nodes.items():
        short = nid.rsplit(".", 1)[-1]
        rx, ry = n["x"], n["y"]
        rw = n.get("width", 60)
        rh = n.get("height", rw)
        x0, y0 = rx + _PIERCE_INSET, ry + _PIERCE_INSET
        x1, y1 = rx + rw - _PIERCE_INSET, ry + rh - _PIERCE_INSET
        node_info.append((nid, short, n, x0, y0, x1, y1))

    count = 0
    for e in edges:
        pts = e["points"]
        if len(pts) < 2:
            continue
        ignore = {e["from"], e["to"]}
        # Edge bounding box for a cheap reject against each node's pierce box.
        exs = [p[0] for p in pts]
        eys = [p[1] for p in pts]
        emnx, emny, emxx, emxy = min(exs), min(eys), max(exs), max(eys)
        for nid, short, n, x0, y0, x1, y1 in node_info:
            if nid in ignore or short in ignore:
                continue
            # Box reject: edge bbox vs node's expanded pierce box.
            if emnx > x1 or x0 > emxx or emny > y1 or y0 > emxy:
                continue
            for k in range(len(pts) - 1):
                if _seg_pierces_node(pts[k], pts[k + 1], n):
                    count += 1
                    break
    return count


_GROUP_FRAME_INSET = 2


def _seg_crosses_box(p1, p2, bx, by, bw, bh, inset=0):
    """True if axis-aligned segment p1-p2 passes through rectangle (bx,by,bw,bh).

    `inset` shrinks the rectangle so a segment merely running along the frame
    edge (or a port landing exactly on it) is not counted as crossing through.
    """
    x0, y0 = bx + inset, by + inset
    x1, y1 = bx + bw - inset, by + bh - inset
    ax, ay = p1
    bx2, by2 = p2
    if ax == bx2:  # vertical segment
        return x0 < ax < x1 and min(ay, by2) < y1 and max(ay, by2) > y0
    if ay == by2:  # horizontal segment
        return y0 < ay < y1 and min(ax, bx2) < x1 and max(ax, bx2) > x0
    return False


def _count_group_pierces(edges, groups, nodes):
    """Count (edge, framed-group) pairs where an edge cuts through a group's
    drawn frame without connecting to that group or any icon inside it.

    Only groups with a visible frame (``groupType``) are considered — an
    invisible grouping has no box to violate. An edge is exempt for a group if
    it starts/ends at that group OR at any of its member icons (those edges are
    SUPPOSED to enter the box). Everything else slicing through the frame reads
    as a stray line crossing an unrelated container, which looks broken.
    """
    if not groups:
        return 0
    framed = [(gid, g) for gid, g in groups.items() if g.get("groupType")]
    if not framed:
        return 0
    count = 0
    for e in edges:
        pts = e["points"]
        if len(pts) < 2:
            continue
        efrom = e["from"].rsplit(".", 1)[-1]
        eto = e["to"].rsplit(".", 1)[-1]
        for gid, g in framed:
            gshort = gid.rsplit(".", 1)[-1]
            if efrom == gshort or eto == gshort:
                continue  # edge connects to the group box itself
            members = _group_member_ids(nodes, groups, gid)
            if efrom in members or eto in members:
                continue  # edge connects to an icon inside this group
            if any(_seg_crosses_box(pts[k], pts[k + 1], g["x"], g["y"],
                                    g["width"], g["height"], _GROUP_FRAME_INSET)
                   for k in range(len(pts) - 1)):
                count += 1
    return count


def _count_backwards(edges, nodes):
    """Count edges whose first/last segment heads opposite to its port normal.

    A "backwards" segment leaves (or enters) an icon edge pointing back across
    the icon — e.g. a bottom port whose first move is upward. The port side is
    inferred from the endpoint's position on the node so this works regardless
    of label offset (a bottom port sits below the icon's x-span).
    """
    count = 0
    for e in edges:
        pts = e["points"]
        if len(pts) < 2:
            continue
        src = _find_node(nodes, e["from"])
        dst = _find_node(nodes, e["to"])
        for node, p_port, p_next, leaving in (
            (src, pts[0], pts[1], True),
            (dst, pts[-1], pts[-2], False),
        ):
            if node is None:
                continue
            side = _port_side(node, p_port)
            if side is None:
                continue
            # Outward normal for the port; the adjacent point must lie on the
            # outward side (for a source) — i.e. not back across the icon.
            if side == "right" and p_next[0] < p_port[0] - 2:
                count += 1
            elif side == "left" and p_next[0] > p_port[0] + 2:
                count += 1
            elif side == "bottom" and p_next[1] < p_port[1] - 2:
                count += 1
            elif side == "top" and p_next[1] > p_port[1] + 2:
                count += 1
    return count


def _port_side(node, pt):
    """Infer which icon edge a port point sits on (label-offset aware)."""
    x, y = pt
    cx, cy = node["x"], node["y"]
    w = node.get("width", 60)
    h = node.get("height", w)
    if cx - 2 <= x <= cx + w + 2:
        if y >= cy + h - 2:
            return "bottom"
        if y <= cy + 2:
            return "top"
    if cy - 2 <= y <= cy + h + 2:
        if x <= cx + 2:
            return "left"
        if x >= cx + w - 2:
            return "right"
    return None


def _edge_free_bend(pts):
    """Return ('x'|'y', lo, hi) for the movable middle bend of a 4-point elbow.

    A VHV/HVH path's two middle points share one coordinate (the trunk
    position) that can slide between the two endpoints without moving the
    port-anchored endpoints or creating diagonals. Returns None for paths
    that have no such free bend (straight lines, detours, fan-outs).
    """
    if len(pts) != 4:
        return None
    # HVH: horiz, vert, horiz → middle two points share X (vertical trunk)
    if pts[0][1] == pts[1][1] and pts[1][0] == pts[2][0] and pts[2][1] == pts[3][1]:
        return ("x", pts[0][0], pts[3][0])
    # VHV: vert, horiz, vert → middle two points share Y (horizontal trunk)
    if pts[0][0] == pts[1][0] and pts[1][1] == pts[2][1] and pts[2][0] == pts[3][0]:
        return ("y", pts[0][1], pts[3][1])
    return None
