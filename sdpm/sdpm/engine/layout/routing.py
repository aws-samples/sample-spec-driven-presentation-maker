# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Edge routing: orthogonal connection paths plus the port/group-bus/fan
alignment passes that run directly on freshly routed edges.
"""

from .geometry import (
    _count_all_crossings,
    _count_backwards,
    _count_group_pierces,
    _count_node_pierces,
    _find_first_crossing,
    _segments_intersect,
)
from .model import (
    _auto_sides,
    _detour_path,
    _elbow_path,
    _find_endpoint,
    _find_group,
    _find_group_for,
    _find_node,
    _group_member_ids,
    _port_point,
)
from .refine import (
    _MAX_RESOLVE_ITERATIONS,
    _W_GROUP_PIERCE_ENGINE,
    _defect_weight,
    _detour_around_pierces,
    _edge_pierces,
    _optimize_bends,
    _reselect_sides,
    _resolve_crossing_search,
    _rewrite_fan,
    _separate_close_bends,
)




def _layout_route_connections(connections, nodes, groups=None):
    """Route connections between nodes. Returns list of edge dicts with points."""
    groups = groups or {}
    # Build node-to-group mapping and obstacle list
    node_group = {}
    for gid, g in groups.items():
        for cid in g.get("children", []):
            node_group[cid] = gid
    obstacles = [{"x": g["x"], "y": g["y"], "width": g["width"], "height": g["height"]} for g in groups.values()]
    # Also add all nodes as obstacles so arrows avoid passing through icons
    for nid, n in nodes.items():
        obstacles.append({"x": n["x"], "y": n["y"], "width": n.get("width", 60), "height": n.get("height", 60), "_node": nid})

    port_counts = {}
    port_indices = {}

    # First pass: identify reverse-flow connections (they use bottom ports, not side ports)
    # Skip if explicit side hints are provided (graph layout mode).
    # Only treat as reverse if the horizontal displacement is dominant (not a vertical connection).
    reverse_set = set()
    for i, conn in enumerate(connections):
        if conn.get("srcSide") or conn.get("dstSide"):
            continue
        src = _find_node(nodes, conn["from"])
        dst = _find_node(nodes, conn["to"])
        if src and dst and dst["x"] + dst["width"] < src["x"]:
            src_cy = src["y"] + src.get("height", 60) / 2
            dst_cy = dst["y"] + dst.get("height", 60) / 2
            dx = src["x"] - (dst["x"] + dst["width"])
            dy = abs(dst_cy - src_cy)
            # Only treat as a reverse-flow (U-shaped detour) when the target is
            # to the left AND roughly on the same row — a genuine feedback loop.
            # If the target is also well above/below, a normal elbow routes it
            # cleanly; the U-detour would wrap awkwardly into the wrong edge.
            if dx > dy * 2:
                reverse_set.add(i)

    # Track decided sides per source node to ensure consistency for fan-out
    decided_src_side = {}

    # Identify fan-out sources (nodes with multiple forward targets).
    # For fan-out nodes, pre-compute the best exit side by majority vote
    # of what _auto_sides would choose, preferring horizontal ("right"/"left").
    _src_target_count: dict = {}
    _src_side_votes: dict = {}  # {src_id: {"right": n, "left": n, ...}}
    for idx, conn in enumerate(connections):
        if idx in reverse_set:
            continue
        if conn.get("srcSide") or conn.get("dstSide"):
            continue
        sid = conn["from"]
        _src_target_count[sid] = _src_target_count.get(sid, 0) + 1
        src = _find_node(nodes, conn["from"])
        dst = _find_node(nodes, conn["to"])
        if src and dst:
            s_side, _ = _auto_sides(src, dst, None)
            _src_side_votes.setdefault(sid, {})
            _src_side_votes[sid][s_side] = _src_side_votes[sid].get(s_side, 0) + 1
    fanout_sources = {sid for sid, cnt in _src_target_count.items() if cnt >= 2}

    # Pre-decide a shared exit side for a fan-out source ONLY when a strict
    # majority of its targets naturally want the same side. Forcing one side
    # when targets are scattered (e.g. one to the right, one below-left) makes
    # the minority arrows exit backwards through the source icon. When there is
    # no majority, leave the source un-decided so each edge keeps its natural
    # side. Among ties, prefer horizontal ("right" > "left") for left→right flow.
    for sid in fanout_sources:
        votes = _src_side_votes.get(sid, {})
        if not votes:
            continue
        total = sum(votes.values())
        # candidate = the side with the most votes (horizontal preferred on tie)
        ordered = sorted(votes.items(), key=lambda kv: (-kv[1], {"right": 0, "left": 1, "bottom": 2, "top": 3}.get(kv[0], 9)))
        best_side, best_n = ordered[0]
        if best_n > total / 2:
            decided_src_side[sid] = best_side

    conn_sides = []
    for i, conn in enumerate(connections):
        src, _src_is_grp = _find_endpoint(nodes, groups, conn["from"])
        dst, _dst_is_grp = _find_endpoint(nodes, groups, conn["to"])
        if not src or not dst:
            conn_sides.append((None, None, None, None))
            continue
        if i in reverse_set:
            conn_sides.append((src, dst, "bottom", "bottom"))
            continue

        # Allow explicit side hints from connection spec
        explicit_src = conn.get("srcSide")
        explicit_dst = conn.get("dstSide")

        group_dir = None
        src_gid = _find_group_for(conn["from"], node_group)
        dst_gid = _find_group_for(conn["to"], node_group)
        if src_gid and src_gid == dst_gid:
            group_dir = groups[src_gid].get("direction", "horizontal")
        src_side, dst_side = _auto_sides(src, dst, group_dir)

        if explicit_src:
            src_side = explicit_src
        if explicit_dst:
            dst_side = explicit_dst

        # Consistency: if this source already has a decided side for forward connections,
        # reuse it to prevent some arrows exiting from a different side (e.g. bottom).
        # Skip this override when explicit sides are provided, or when the decided side
        # is perpendicular to the natural direction (would create a bad route).
        # Exception: for fan-out sources (1 source → N targets), ALWAYS apply the
        # decided side to keep all arrows exiting from the same edge.
        src_id = conn["from"]
        if not explicit_src and not explicit_dst:
            if src_id in decided_src_side:
                decided = decided_src_side[src_id]
                # For fan-out sources, always use the decided side.
                # For non-fan-out, only apply if same axis (horizontal↔horizontal
                # or vertical↔vertical) to avoid bad routes.
                h_sides = {"left", "right"}
                natural_axis = "h" if src_side in h_sides else "v"
                decided_axis = "h" if decided in h_sides else "v"
                # Never apply the decided side if the target lies on the OPPOSITE
                # side, which would make the arrow exit backwards through the
                # source icon (e.g. forcing "right" when the target is to the
                # left). Check the target's actual direction relative to source.
                decided_is_backwards = False
                # Whether the decided side's axis matches the target's DOMINANT
                # direction. Forcing a vertical (top/bottom) exit toward a target
                # that is primarily to the side (or vice-versa) makes the arrow
                # wrap awkwardly around the target — so only force when the axes
                # agree, even for fan-out sources.
                decided_axis_matches_target = True
                if src and dst:
                    s_cx = src["x"] + src.get("width", 60) / 2
                    s_cy = src["y"] + src.get("height", 60) / 2
                    d_cx = dst["x"] + dst.get("width", 60) / 2
                    d_cy = dst["y"] + dst.get("height", 60) / 2
                    if decided == "right" and d_cx < s_cx:
                        decided_is_backwards = True
                    elif decided == "left" and d_cx > s_cx:
                        decided_is_backwards = True
                    elif decided == "bottom" and d_cy < s_cy:
                        decided_is_backwards = True
                    elif decided == "top" and d_cy > s_cy:
                        decided_is_backwards = True
                    adx = abs(d_cx - s_cx)
                    ady = abs(d_cy - s_cy)
                    target_axis = "h" if adx >= ady else "v"
                    decided_axis_matches_target = (target_axis == decided_axis)
                apply_decided = (
                    (not decided_is_backwards)
                    and decided_axis_matches_target
                    and ((src_id in fanout_sources) or (natural_axis == decided_axis))
                )
                if apply_decided:
                    src_side = decided
                    # Fix dst_side for fan-out: use opposite side, but if dst
                    # is directly above/below src (not to the side), keep natural dst_side
                    if src_id in fanout_sources:
                        if src and dst:
                            src_cx = src["x"] + src.get("width", 60) / 2
                            dst_cx = dst["x"] + dst.get("width", 60) / 2
                            src_cy = src["y"] + src.get("height", 60) / 2
                            dst_cy = dst["y"] + dst.get("height", 60) / 2
                            adx = abs(dst_cx - src_cx)
                            ady = abs(dst_cy - src_cy)
                            if ady > adx * 2:
                                # Target is mostly above/below — use natural sides
                                natural_src, natural_dst = _auto_sides(src, dst, None)
                                src_side = natural_src
                                dst_side = natural_dst
                            else:
                                # Target is to the side — use opposite
                                if src_side == "right":
                                    dst_side = "left"
                                elif src_side == "left":
                                    dst_side = "right"
                                elif src_side == "bottom":
                                    dst_side = "top"
                                elif src_side == "top":
                                    dst_side = "bottom"
                        else:
                            if src_side == "right":
                                dst_side = "left"
                            elif src_side == "left":
                                dst_side = "right"
                            elif src_side == "bottom":
                                dst_side = "top"
                            elif src_side == "top":
                                dst_side = "bottom"
                    else:
                        if src_side == "right" and dst_side == "top":
                            dst_side = "left"
                        elif src_side == "left" and dst_side == "bottom":
                            dst_side = "right"
                        elif src_side == "bottom" and dst_side == "right":
                            dst_side = "top"
                        elif src_side == "top" and dst_side == "left":
                            dst_side = "bottom"
            else:
                decided_src_side[src_id] = src_side

        conn_sides.append((src, dst, src_side, dst_side))
        sk = (conn["from"], src_side)
        dk = (conn["to"], dst_side)
        port_counts[sk] = port_counts.get(sk, 0) + 1
        port_counts[dk] = port_counts.get(dk, 0) + 1

    # Optimize port assignment order to minimize crossings.
    # Group connections by (node, side), then try permutations of port order.
    # Exclude reverse connections (they use dedicated bottom ports).
    port_groups = {}
    for i, (src, dst, src_side, dst_side) in enumerate(conn_sides):
        if src is None or i in reverse_set:
            continue
        sk = (connections[i]["from"], src_side)
        dk = (connections[i]["to"], dst_side)
        port_groups.setdefault(sk, []).append(i)
        port_groups.setdefault(dk, []).append(i)

    port_indices = _optimize_port_order(port_groups, conn_sides, connections, nodes, port_counts, obstacles)

    # Compute global bounding box for detour routing
    all_y = []
    for n in nodes.values():
        all_y.append(n["y"])
        all_y.append(n["y"] + n["height"])
    global_bottom = max(all_y) + 60 if all_y else 500

    # Compute fan-out shared bend X for right-side fan-outs.
    # All connections from a fan-out source share the same bend X (midpoint to nearest target).
    fanout_bend_x = {}
    for sid in fanout_sources:
        if decided_src_side.get(sid) == "right":
            src_node = _find_node(nodes, sid)
            if not src_node:
                continue
            src_right = src_node["x"] + src_node["width"]
            # Find nearest target left edge
            target_lefts = []
            for idx, conn in enumerate(connections):
                if conn["from"] == sid and idx not in reverse_set:
                    dst_node = _find_node(nodes, conn["to"])
                    if dst_node:
                        target_lefts.append(dst_node["x"])
            # Only consider targets to the right of source
            right_targets = [x for x in target_lefts if x > src_right]
            if right_targets:
                nearest_left = min(right_targets)
                fanout_bend_x[sid] = src_right + (nearest_left - src_right) * 0.45
            elif target_lefts:
                # All targets are to the left or same X — use a fixed offset
                fanout_bend_x[sid] = src_right + 30

    edges = []
    for i, conn in enumerate(connections):
        src, dst, src_side, dst_side = conn_sides[i]
        if src is None:
            edges.append({"from": conn["from"], "to": conn["to"], "label": conn.get("label", ""), "points": []})
            continue

        # Group endpoints: the port sits on the group's box edge (no label
        # offset), and the line is allowed to enter the box — so the group's
        # own member icons are excluded from this edge's obstacles.
        src_is_grp = _find_node(nodes, conn["from"]) is None
        dst_is_grp = _find_node(nodes, conn["to"]) is None

        if i in reverse_set:
            src_node = _find_node(nodes, conn["from"])
            dst_node = _find_node(nodes, conn["to"])
            label_h_src = 30 if src_node.get("label") else 0
            label_h_dst = 30 if dst_node.get("label") else 0
            sp = _port_point(src_node, "bottom", 0, 1, label_h_src)
            tp = _port_point(dst_node, "bottom", 0, 1, label_h_dst)
            points = _detour_path(sp, tp, "bottom", "bottom", global_bottom)
        else:
            # A group port uses no label height; a node port offsets the bottom
            # edge by the label band.
            src_label_h = 0 if src_is_grp else (30 if src.get("label") else 0)
            dst_label_h = 0 if dst_is_grp else (30 if dst.get("label") else 0)
            sp = _port_point(src, src_side, port_indices[(i, conn["from"])], port_counts[(conn["from"], src_side)], src_label_h)
            tp = _port_point(dst, dst_side, port_indices[(i, conn["to"])], port_counts[(conn["to"], dst_side)], dst_label_h)

            # Route every edge with the standard elbow path. The downstream
            # bend optimizer, side reselection, and detour passes shape each
            # edge to minimize crossings/pierces — a shared fan-out trunk is
            # no longer special-cased because, when targets sit on a row with
            # an obstacle between them, a fixed trunk grazes that obstacle and
            # no trunk position can avoid it (only a detour can).
            excl = {conn["from"], conn["to"]}
            # Connecting to/from a group means the line may pass into that
            # group's box — exclude the group's member icons (and the group
            # box itself) from this edge's obstacles.
            if src_is_grp:
                excl |= _group_member_ids(nodes, groups, conn["from"])
            if dst_is_grp:
                excl |= _group_member_ids(nodes, groups, conn["to"])
            conn_obs = [o for o in obstacles if o.get("_node") not in excl]
            points = _elbow_path(sp, tp, src_side, dst_side, conn_obs)
        edge_entry = {"from": conn["from"], "to": conn["to"], "label": conn.get("label", ""), "points": points}
        if src_is_grp:
            edge_entry["_src_group"] = conn["from"]
        if dst_is_grp:
            edge_entry["_dst_group"] = conn["to"]
        edges.append(edge_entry)

    # T8: Merge fan-out/fan-in groups onto a unified port + shared trunk when
    # "fan": "merge" is set. This is treated as a HARD CONSTRAINT: the merged
    # edges are tagged `_fan_locked` and every downstream pass leaves their
    # trunks untouched. Crossing avoidance for merged fans comes from placement
    # (the order/direction search) and from routing the OTHER edges around the
    # fixed trunks — not from un-merging them.
    _align_fan_bends(edges, conn_sides, connections, nodes, groups)

    # T9: Safe bend separation — shift overlapping vertical bends apart
    # while preserving axis-alignment (only move X of vertical segments,
    # never touch start/end points). Skips locked fan trunks.
    _safe_separate_bends(edges)

    # T10: Bend optimization — slide each free (middle) bend of an elbow path
    # along its axis to minimize a global cost (crossings + weighted icon
    # pierces). The free bend of a 4-point VHV/HVH path can move without
    # touching the port-anchored endpoints, so axis-alignment and
    # perpendicularity are preserved. This is the primary crossing/pierce
    # reducer; it never introduces diagonals or backwards segments.
    _optimize_bends(edges, nodes)

    # T11: Side/port reselection — a remaining pierce is usually a poor choice
    # of which icon edge the arrow attaches to. Re-route each still-piercing
    # edge through the elbow router with an alternative (src_side, dst_side),
    # keeping it only if it lowers pierces without raising crossings. Adds no
    # segments (unlike a detour), so it cannot cause a crossing blow-up, and
    # endpoints stay perpendicular because every port comes from _port_point.
    obstacles_re = [o for o in obstacles if o.get("_node")]
    # Guard the whole reselect pass on the global weighted defect score: the
    # per-edge slack (allowing +1 crossing to clear a pierce) is locally sound
    # but can accumulate across edges into a net-worse layout. Roll back if the
    # weighted total (crossings + 1.5*pierces + 0.7*backwards) regresses.
    _resel_before = _defect_weight((_count_all_crossings(edges),
                                    _count_node_pierces(edges, nodes),
                                    _count_backwards(edges, nodes)))
    _resel_snapshot = [list(map(list, e["points"])) for e in edges]
    _reselect_sides(edges, nodes, obstacles_re)
    _resel_after = _defect_weight((_count_all_crossings(edges),
                                   _count_node_pierces(edges, nodes),
                                   _count_backwards(edges, nodes)))
    if _resel_after > _resel_before:
        for e, pts in zip(edges, _resel_snapshot):
            e["points"] = pts
    _optimize_bends(edges, nodes)

    # T12: Obstacle detour — for pierces that no side/port choice can clear
    # (e.g. an icon stacked directly between source and target in the same
    # column), splice an axis-aligned jog around the obstacle. Each candidate
    # is judged by the weighted defect score (pierce 1.5 > cross 1.0), so a jog
    # may add a crossing to lift a line off an icon it cuts through. The jog is
    # spliced into the interior of a segment, so endpoints never move and no
    # diagonal is ever produced. Guarded on the global weighted total so the
    # per-edge slack can't accumulate into a net-worse layout.
    _det_before = _defect_weight((_count_all_crossings(edges),
                                  _count_node_pierces(edges, nodes)
                                  + _count_group_pierces(edges, groups, nodes),
                                  _count_backwards(edges, nodes)))
    _det_snapshot = [list(map(list, e["points"])) for e in edges]
    _detour_around_pierces(edges, nodes, groups)
    _det_after = _defect_weight((_count_all_crossings(edges),
                                 _count_node_pierces(edges, nodes)
                                 + _count_group_pierces(edges, groups, nodes),
                                 _count_backwards(edges, nodes)))
    if _det_after > _det_before:
        for e, pts in zip(edges, _det_snapshot):
            e["points"] = pts

    # T13: Port recentering — by now each edge's actual entry/exit side may
    # differ from the side that seeded port_counts (fan merge, side reselect,
    # and elbow re-picks all move endpoints). That stale count left, e.g., a
    # lone right-side edge sharing a "2 ports" slot and sitting off-center.
    # Recompute the real per-(node, side) usage from geometry and redistribute
    # the ports evenly along each edge, snapping the adjacent bend so the stub
    # stays perpendicular. Fan-locked endpoints are fixed and excluded.
    # Guarded per (node, side) group: each redistribution is kept only if it
    # does not increase global crossings — centering a port can occasionally
    # re-introduce a crossing that bend-opt had removed.
    _recenter_ports(edges, nodes)

    # T14: Group bus bundling — when several edges share a GROUP endpoint
    # (many-to-one to a box), bundle them so they enter/leave the box edge as a
    # tidy parallel bus instead of fanning to scattered points. Nested lanes
    # ordered by the opposite end keep the bundle crossing-free. Guarded on the
    # global crossing count.
    _align_group_bus(edges, nodes, groups)

    # T15: Straighten solo group-endpoint edges. A connection to a GROUP box
    # defaults its port to the box center, so a node→tall-group (or small-group→
    # tall-group) edge bends into an L even when a straight run fits inside both
    # facing edges — the "Step Functions → Processing" / "Processing → Shared"
    # L-bends. Slide the port that has the larger box to the smaller endpoint's
    # center so the arrow becomes a clean straight line. Guarded; bundles owned
    # by the group bus (T14) are left alone.
    _straighten_group_edges(edges, nodes, groups)

    # T16: U-turn a group-endpoint monitor edge around framed boxes. An edge
    # from a GROUP box to a far node with framed groups in between (e.g. the ETL
    # group → CloudWatch across the Consumers frame) defaults to a right-exit
    # that the detour pass can only hack past, leaving a staircase that still
    # grazes the frame. This one-shot pass tries a single clean U: exit the
    # group's BOTTOM (or TOP), run a trunk just past the obstacle boxes, and
    # enter the far node on the matching face. Committed only if it lowers the
    # weighted defect total. Cheap: one candidate per qualifying edge.
    _uturn_group_endpoint_edges(edges, nodes, groups)

    return edges


_UTURN_CLEAR = 20


def _uturn_group_endpoint_edges(edges, nodes, groups):
    """Reroute a solo group-endpoint edge that cuts framed boxes into a clean U.

    Targets an edge with a GROUP endpoint that still pierces one or more framed
    group boxes (a monitor/aggregator line crossing the diagram). Builds ONE
    candidate per vertical direction: leave the group box's bottom (or top) edge,
    run a horizontal trunk just beyond ALL the boxes it would otherwise cross,
    then rise/drop into the far endpoint on that same vertical face. Keeps the
    candidate only if the global weighted defect total strictly improves and
    crossings do not rise. O(edges × groups) — no port/side search.
    """
    if not groups:
        return edges
    framed = [g for g in groups.values() if g.get("groupType")]
    if not framed:
        return edges

    def weighted():
        return _defect_weight((_count_all_crossings(edges),
                               _count_node_pierces(edges, nodes)
                               + _W_GROUP_PIERCE_ENGINE * _count_group_pierces(edges, groups, nodes),
                               _count_backwards(edges, nodes)))

    for e in edges:
        if e.get("_fan_locked") or e.get("_fanout"):
            continue
        if len(e["points"]) < 2:
            continue
        # Must involve a group endpoint and still have a routing defect (a
        # framed-box cut OR a non-endpoint icon pierce) the prior passes left —
        # the staircase the detour produced still grazes icons/frames.
        if not (e.get("_src_group") or e.get("_dst_group")):
            continue
        if (_count_group_pierces([e], groups, nodes) == 0
                and not _edge_pierces(e, nodes)):
            continue
        src, src_is_grp = _find_endpoint(nodes, groups, e["from"])
        dst, dst_is_grp = _find_endpoint(nodes, groups, e["to"])
        if not src or not dst:
            continue

        # Boxes this edge must clear (framed, not its own endpoints/members).
        efrom, eto = e["from"].rsplit(".", 1)[-1], e["to"].rsplit(".", 1)[-1]
        boxes = []
        for gid, g in groups.items():
            if not g.get("groupType"):
                continue
            gshort = gid.rsplit(".", 1)[-1]
            if gshort in (efrom, eto):
                continue
            members = _group_member_ids(nodes, groups, gid)
            if efrom in members or eto in members:
                continue
            boxes.append(g)
        if not boxes:
            continue

        s_label = 0 if src_is_grp else (30 if src.get("label") else 0)
        d_label = 0 if dst_is_grp else (30 if dst.get("label") else 0)
        sx_c = src["x"] + src["width"] // 2
        dx_c = dst["x"] + dst["width"] // 2
        snap = [list(map(list, ee["points"])) for ee in edges]
        before = weighted()
        before_cross = _count_all_crossings(edges)

        best = None
        for vside in ("bottom", "top"):
            # Trunk Y just past every box on the chosen vertical side, and past
            # both endpoints' own extents so the stubs don't clip their boxes.
            if vside == "bottom":
                trunk_y = max([g["y"] + g["height"] for g in boxes]
                              + [src["y"] + src["height"], dst["y"] + dst["height"]]) + _UTURN_CLEAR
                sp = [sx_c, src["y"] + src["height"] + s_label]
                tp = [dx_c, dst["y"] + dst["height"] + d_label]
            else:
                trunk_y = min([g["y"] for g in boxes]
                              + [src["y"], dst["y"]]) - _UTURN_CLEAR
                sp = [sx_c, src["y"]]
                tp = [dx_c, dst["y"]]
            cand = [sp, [sp[0], trunk_y], [tp[0], trunk_y], tp]
            e["points"] = cand
            w = weighted()
            if (w < before and _count_all_crossings(edges) <= before_cross
                    and (best is None or w < best[0])):
                best = (w, [list(p) for p in cand])
            for ee, pts in zip(edges, snap):
                ee["points"] = pts

        if best is not None:
            e["points"] = best[1]
    return edges


def _straighten_group_edges(edges, nodes, groups):
    """Make a solo group-endpoint edge a straight line when one fits.

    A connection whose endpoint is a GROUP box gets its port at the box center,
    so when the two endpoints differ in cross-axis extent (a 60px icon vs a
    765px column, or two columns of unequal height) the elbow router bends the
    edge even though a single straight segment would fit inside both facing
    edges. For each such edge whose two ports sit on facing horizontal (or
    facing vertical) sides, we choose a common cross-axis coordinate that lies
    inside BOTH endpoints' spans — preferring the SMALLER endpoint's center, so
    single icons and small boxes attach at their visual middle and the larger
    box absorbs the offset — and re-emit a straight 2-point edge.

    Left untouched: fan trunks (the merge is a hard constraint) and any edge
    sharing a group endpoint with another edge (a many-to-one bundle owned by
    the group-bus pass, T14). Guarded on the global weighted defect total so
    straightening can never add a crossing, icon pierce, or frame pierce.
    """
    if not edges:
        return edges

    # Count edges per group endpoint so many-to-one bundles stay with the bus.
    grp_use = {}
    for e in edges:
        if e.get("_src_group"):
            grp_use[("src", e["_src_group"])] = grp_use.get(("src", e["_src_group"]), 0) + 1
        if e.get("_dst_group"):
            grp_use[("dst", e["_dst_group"])] = grp_use.get(("dst", e["_dst_group"]), 0) + 1

    def weighted(es):
        return _defect_weight((_count_all_crossings(es),
                               _count_node_pierces(es, nodes)
                               + _count_group_pierces(es, groups, nodes),
                               _count_backwards(es, nodes)))

    for e in edges:
        if e.get("_fan_locked") or e.get("_fanout"):
            continue
        pts = e["points"]
        if len(pts) < 2:
            continue
        # Only group-endpoint edges suffer the box-center kink; node→node edges
        # are already snapped straight by the elbow router when they line up.
        if not (e.get("_src_group") or e.get("_dst_group")):
            continue
        if e.get("_src_group") and grp_use.get(("src", e["_src_group"]), 0) >= 2:
            continue
        if e.get("_dst_group") and grp_use.get(("dst", e["_dst_group"]), 0) >= 2:
            continue
        s_geom, _ = _find_endpoint(nodes, groups, e["from"])
        d_geom, _ = _find_endpoint(nodes, groups, e["to"])
        if not s_geom or not d_geom:
            continue
        first_h = abs(pts[0][1] - pts[1][1]) <= 2
        first_v = abs(pts[0][0] - pts[1][0]) <= 2
        last_h = abs(pts[-1][1] - pts[-2][1]) <= 2
        last_v = abs(pts[-1][0] - pts[-2][0]) <= 2

        new_pts = None
        if first_h and last_h and abs(pts[0][1] - pts[-1][1]) > 2:
            # Both ports on left/right edges → straighten on a common Y.
            lo = max(s_geom["y"], d_geom["y"])
            hi = min(s_geom["y"] + s_geom["height"], d_geom["y"] + d_geom["height"])
            if hi - lo > 2:
                if s_geom["height"] <= d_geom["height"]:
                    c = s_geom["y"] + s_geom["height"] / 2
                else:
                    c = d_geom["y"] + d_geom["height"] / 2
                y = round(min(max(c, lo + 1), hi - 1))
                new_pts = [[pts[0][0], y], [pts[-1][0], y]]
        elif first_v and last_v and abs(pts[0][0] - pts[-1][0]) > 2:
            # Both ports on top/bottom edges → straighten on a common X.
            lo = max(s_geom["x"], d_geom["x"])
            hi = min(s_geom["x"] + s_geom["width"], d_geom["x"] + d_geom["width"])
            if hi - lo > 2:
                if s_geom["width"] <= d_geom["width"]:
                    c = s_geom["x"] + s_geom["width"] / 2
                else:
                    c = d_geom["x"] + d_geom["width"] / 2
                x = round(min(max(c, lo + 1), hi - 1))
                new_pts = [[x, pts[0][1]], [x, pts[-1][1]]]
        if new_pts is None:
            continue

        snap = [list(map(list, ee["points"])) for ee in edges]
        before = weighted(edges)
        e["points"] = new_pts
        if weighted(edges) > before:
            for ee, p in zip(edges, snap):
                ee["points"] = p
    return edges


_PORT_EPS = 4
_GROUP_BUS_PORT_GAP = 26
_GROUP_BUS_LANE_GAP = 14


def _align_group_bus(edges, nodes, groups):
    """Bundle edges that share a group endpoint into a parallel bus on the box.

    For each group that is the target (or source) of 2+ edges, route those
    edges so their final (or first) approach runs as nested parallel lanes into
    adjacent ports centered on the box edge facing the other ends. Ordering the
    lanes by the opposite end's position keeps the bundle free of self-cross.
    Kept only if it does not raise the global crossing count.
    """
    if not groups:
        return edges

    # Collect bundles: (group_id, role) -> list of edges, where role is 'dst'
    # (edges ending at the group) or 'src' (edges starting at the group).
    bundles = {}
    for e in edges:
        if len(e["points"]) < 2:
            continue
        # A fan-merged group edge is already a deliberate single-trunk bundle;
        # leave it to the fan layout, don't re-bundle it here.
        if e.get("_fan_locked"):
            continue
        if e.get("_dst_group"):
            bundles.setdefault((e["_dst_group"], "dst"), []).append(e)
        if e.get("_src_group"):
            bundles.setdefault((e["_src_group"], "src"), []).append(e)

    for (gid, role), all_grp_edges in bundles.items():
        if len(all_grp_edges) < 2:
            continue
        g = _find_group(groups, gid)
        if not g:
            continue
        gx, gy, gw, gh = g["x"], g["y"], g["width"], g["height"]
        bcx, bcy = gx + gw / 2, gy + gh / 2

        # The "free end" of each edge is the non-group end.
        def free_pt(e):
            return e["points"][0] if role == "dst" else e["points"][-1]

        # Assign each edge to the box side its OWN free end faces (not the
        # bundle centroid). A group can radiate in several directions at once —
        # e.g. Stream Processing → Firehose (right), → OpenSearch (above),
        # → CloudWatch (below). Bundling all three onto one centroid side drags
        # the up/down edges out the right face and makes them detour. Only edges
        # that genuinely share a side should share a bus.
        by_side = {}
        for e in all_grp_edges:
            fp = free_pt(e)
            dx, dy = fp[0] - bcx, fp[1] - bcy
            if abs(dx) >= abs(dy):
                e_side = "left" if dx < 0 else "right"
            else:
                e_side = "top" if dy < 0 else "bottom"
            by_side.setdefault(e_side, []).append(e)

        for side, grp_edges in by_side.items():
            # A single edge on a side keeps its natural port — nothing to bundle.
            if len(grp_edges) < 2:
                continue
            vertical_ports = side in ("left", "right")  # ports vary along Y

            snapshot = [list(map(list, e["points"])) for e in edges]
            before = _count_all_crossings(edges)

            # Order edges by their free end's coordinate along the port axis so
            # adjacent ports connect to adjacent sources (no self-cross).
            grp_edges.sort(key=lambda e: free_pt(e)[1] if vertical_ports else free_pt(e)[0])
            n = len(grp_edges)
            # Box-edge anchor coordinates (the fixed coordinate of the port line).
            bx = gx if side == "left" else (gx + gw)        # used when vertical_ports
            by = gy if side == "top" else (gy + gh)          # used otherwise

            for rank, e in enumerate(grp_edges):
                off = (rank - (n - 1) / 2) * _GROUP_BUS_PORT_GAP
                fp = free_pt(e)
                # Nested lane: outer (farther from center) edges turn earlier so
                # the bundle telescopes without crossing.
                lane_depth = (n - rank) * _GROUP_BUS_LANE_GAP if role == "dst" else (rank + 1) * _GROUP_BUS_LANE_GAP
                if vertical_ports:
                    py = round(bcy + off)
                    # Outer lanes turn farther from the box so it telescopes.
                    lane = (gx - 20 - lane_depth) if side == "left" else (gx + gw + 20 + lane_depth)
                    port = [bx, py]
                    if role == "dst":
                        e["points"] = [fp, [lane, fp[1]], [lane, py], port]
                    else:
                        e["points"] = [port, [lane, py], [lane, fp[1]], fp]
                else:
                    px = round(bcx + off)
                    lane = (gy - 20 - lane_depth) if side == "top" else (gy + gh + 20 + lane_depth)
                    port = [px, by]
                    if role == "dst":
                        e["points"] = [fp, [fp[0], lane], [px, lane], port]
                    else:
                        e["points"] = [port, [px, lane], [fp[0], lane], fp]

            if _count_all_crossings(edges) > before:
                for e, pts in zip(edges, snapshot):
                    e["points"] = pts

    return edges


def _recenter_ports(edges, nodes):
    """Evenly redistribute each node-edge's ports using the ACTUAL drawn sides.

    Endpoints are the only points moved (plus the immediately adjacent bend, to
    keep the first/last stub axis-aligned). A single edge on a side lands dead
    center; N edges split the side into N+1 even slots, ordered by the position
    of their opposite end so they don't cross at the port. This corrects the
    off-center stubs left by stale port_counts after fan/side changes.
    """
    def side_of(node, pt):
        x, y = pt
        nx, ny = node["x"], node["y"]
        w = node.get("width", 60)
        h = node.get("height", w)
        if nx - _PORT_EPS <= x <= nx + w + _PORT_EPS:
            if y >= ny + h - _PORT_EPS:
                return "bottom"
            if y <= ny + _PORT_EPS:
                return "top"
        if ny - _PORT_EPS <= y <= ny + h + _PORT_EPS:
            if x <= nx + _PORT_EPS:
                return "left"
            if x >= nx + w - _PORT_EPS:
                return "right"
        return None

    # Gather endpoints to move: (node, side) -> list of (edge, end_index, opp_pt)
    groups = {}
    for e in edges:
        pts = e["points"]
        if len(pts) < 2 or e.get("_fanout"):
            continue
        for end_idx, nid in ((0, e["from"]), (-1, e["to"])):
            # Skip the locked end of a fan edge (its port is the shared trunk port).
            if e.get("_fan_locked"):
                lock = e["_fan_locked"]
                # fan_out: shared port at start; fan_in: shared port at end.
                if (lock["mode"] == "fan_out" and end_idx == 0) or \
                   (lock["mode"] == "fan_in" and end_idx == -1):
                    continue
            node = _find_node(nodes, nid)
            if node is None:
                continue
            s = side_of(node, pts[end_idx])
            if s is None:
                continue
            opp = pts[-1] if end_idx == 0 else pts[0]
            groups.setdefault((nid, s), []).append((e, end_idx, opp, node))

    for (nid, side), members in groups.items():
        node = members[0][3]
        nx, ny = node["x"], node["y"]
        w = node.get("width", 60)
        h = node.get("height", w)
        label_h = 30 if node.get("label") else 0
        n = len(members)
        # Order members along the edge by the coordinate of their opposite end,
        # so adjacent ports connect to adjacent targets (minimizes self-cross).
        if side in ("left", "right"):
            members.sort(key=lambda m: m[2][1])  # by opposite Y
        else:
            members.sort(key=lambda m: m[2][0])  # by opposite X

        # Snapshot the edges this group touches so we can roll back if centering
        # the ports happens to add a crossing the optimizer had removed.
        touched = {id(e): list(map(list, e["points"])) for e, _, _, _ in members}
        before = _count_all_crossings(edges)

        for slot, (e, end_idx, opp, _node) in enumerate(members):
            t = (slot + 1) / (n + 1)
            pts = e["points"]
            if side == "right":
                newp = [nx + w, round(ny + h * t)]
            elif side == "left":
                newp = [nx, round(ny + h * t)]
            elif side == "bottom":
                newp = [round(nx + w * t), ny + h + label_h]
            else:  # top
                newp = [round(nx + w * t), ny]
            # Move the endpoint and snap the adjacent bend to keep the stub
            # perpendicular: for a left/right port the stub is horizontal, so
            # the neighbor shares the new Y; for top/bottom it shares the new X.
            adj_idx = 1 if end_idx == 0 else len(pts) - 2
            if 0 <= adj_idx < len(pts):
                if side in ("left", "right"):
                    pts[adj_idx] = [pts[adj_idx][0], newp[1]]
                else:
                    pts[adj_idx] = [newp[0], pts[adj_idx][1]]
            pts[end_idx] = newp

        if _count_all_crossings(edges) > before:
            for e, _, _, _ in members:
                e["points"] = touched[id(e)]


def _safe_separate_bends(edges):
    """Separate overlapping vertical bends by shifting their X position.

    Rules:
    - Only shifts X of vertical segments (never Y of horizontal segments)
    - Never moves pts[0] or pts[-1] (port-anchored)
    - When shifting a vertical segment's X, also updates the adjacent horizontal
      segments' endpoints to maintain connectivity
    - Minimum separation: 30px between parallel vertical bends
    """
    MIN_SEP = 30

    # Collect vertical segments: (edge_idx, seg_start_idx, x, y_lo, y_hi)
    v_segs = []
    for ei, e in enumerate(edges):
        pts = e["points"]
        if e.get("_fanout") or e.get("_fan_locked"):
            continue
        for k in range(len(pts) - 1):
            if abs(pts[k][0] - pts[k+1][0]) <= 3 and abs(pts[k][1] - pts[k+1][1]) > 10:
                # Vertical segment, not touching start/end
                if k == 0 or k == len(pts) - 2:
                    continue
                x = pts[k][0]
                y_lo = min(pts[k][1], pts[k+1][1])
                y_hi = max(pts[k][1], pts[k+1][1])
                v_segs.append((ei, k, x, y_lo, y_hi))

    # Group vertical segments by similar X (within MIN_SEP)
    v_segs.sort(key=lambda s: s[2])
    groups = []
    current_group = []
    for seg in v_segs:
        if current_group and abs(seg[2] - current_group[0][2]) > MIN_SEP:
            if len(current_group) >= 2:
                groups.append(current_group)
            current_group = [seg]
        else:
            current_group.append(seg)
    if len(current_group) >= 2:
        groups.append(current_group)

    # For each group, check if Y ranges overlap and spread X positions
    for group in groups:
        # Filter to segments with overlapping Y ranges
        overlapping = []
        for i, seg in enumerate(group):
            for other in group[i+1:]:
                if seg[3] < other[4] and seg[4] > other[3]:
                    if seg not in overlapping:
                        overlapping.append(seg)
                    if other not in overlapping:
                        overlapping.append(other)

        if len(overlapping) < 2:
            continue

        # Spread evenly around the center X
        center_x = sum(s[2] for s in overlapping) / len(overlapping)
        n = len(overlapping)
        for i, (ei, k, old_x, y_lo, y_hi) in enumerate(sorted(overlapping, key=lambda s: s[3])):
            new_x = round(center_x + (i - (n-1)/2) * MIN_SEP)
            if new_x == old_x:
                continue
            pts = edges[ei]["points"]
            # Shift the vertical segment
            pts[k] = [new_x, pts[k][1]]
            pts[k+1] = [new_x, pts[k+1][1]]
            # Fix adjacent horizontal segments
            if k > 0 and abs(pts[k-1][1] - pts[k][1]) <= 3:
                pts[k-1] = [pts[k-1][0], pts[k-1][1]]  # keep, connectivity maintained by polyline
            if k+2 < len(pts) and abs(pts[k+1][1] - pts[k+2][1]) <= 3:
                pass  # horizontal after — connectivity OK since pts[k+1] x changed

    # Safety net: if any diagonal segments remain, insert L-shaped intermediates
    for e in edges:
        new_pts = [e["points"][0]]
        pts = e["points"]
        for k in range(1, len(pts)):
            dx = abs(pts[k][0] - new_pts[-1][0])
            dy = abs(pts[k][1] - new_pts[-1][1])
            if dx > 3 and dy > 3:
                new_pts.append([pts[k][0], new_pts[-1][1]])
            new_pts.append(pts[k])
        e["points"] = new_pts

    return edges


def _optimize_port_order(port_groups, conn_sides, connections, nodes, port_counts, obstacles):
    """Find the port index assignment that minimizes edge crossings.

    For each (node, side) with multiple ports, try all permutations (≤6)
    and pick the one with fewest crossings. For larger groups, use a
    heuristic: sort ports by the Y (or X) coordinate of the peer endpoint.
    """
    from itertools import permutations

    # Start with sequential assignment
    port_indices = {}
    port_cursors = {}
    for i, (src, dst, src_side, dst_side) in enumerate(conn_sides):
        if src is None:
            continue
        for nid, side in [(connections[i]["from"], src_side), (connections[i]["to"], dst_side)]:
            k = (nid, side)
            port_cursors[k] = port_cursors.get(k, 0)
            port_indices[(i, nid)] = port_cursors[k]
            port_cursors[k] += 1

    # For each port group with ≥2 connections, optimize the order
    for (nid, side), conn_indices in port_groups.items():
        if len(conn_indices) < 2:
            continue

        count = port_counts[(nid, side)]
        node = _find_node(nodes, nid)
        if not node:
            continue

        if len(conn_indices) <= 6:
            # Brute force: try all permutations
            best_crossings = None
            best_assignment = None

            for perm in permutations(range(count)):
                # Assign port indices according to this permutation
                test_indices = dict(port_indices)
                for slot, ci in enumerate(conn_indices):
                    test_indices[(ci, nid)] = perm[slot]

                crossings = _count_port_crossings(conn_indices, test_indices, conn_sides, connections, nodes, port_counts, obstacles)
                if best_crossings is None or crossings < best_crossings:
                    best_crossings = crossings
                    best_assignment = perm
                    if crossings == 0:
                        break

            if best_assignment is not None:
                for slot, ci in enumerate(conn_indices):
                    port_indices[(ci, nid)] = best_assignment[slot]
        else:
            # Heuristic: sort by peer endpoint coordinate
            _heuristic_port_sort(conn_indices, nid, side, port_indices, conn_sides, connections, nodes)

    return port_indices


def _count_port_crossings(conn_indices, port_indices, conn_sides, connections, nodes, port_counts, obstacles):
    """Count crossings among a set of edges sharing a port group."""
    # Generate paths for the relevant connections
    paths = []
    for ci in conn_indices:
        src, dst, src_side, dst_side = conn_sides[ci]
        if src is None:
            continue
        label_h = 30 if src.get("label") else 0
        sp = _port_point(src, src_side, port_indices[(ci, connections[ci]["from"])], port_counts[(connections[ci]["from"], src_side)], label_h)
        tp = _port_point(dst, dst_side, port_indices[(ci, connections[ci]["to"])], port_counts[(connections[ci]["to"], dst_side)], label_h)
        path = _elbow_path(sp, tp, src_side, dst_side, obstacles)
        paths.append(path)

    # Count pairwise segment crossings
    crossings = 0
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            for si in range(len(paths[i]) - 1):
                for sj in range(len(paths[j]) - 1):
                    if _segments_intersect(paths[i][si], paths[i][si + 1], paths[j][sj], paths[j][sj + 1]):
                        crossings += 1
    return crossings


def _heuristic_port_sort(conn_indices, nid, side, port_indices, conn_sides, connections, nodes):
    """Sort ports by peer endpoint coordinate when brute force is too expensive."""
    peer_coords = []
    for ci in conn_indices:
        src, dst, src_side, dst_side = conn_sides[ci]
        if connections[ci]["from"] == nid:
            peer = _find_node(nodes, connections[ci]["to"])
            coord = (peer["y"] + peer["height"] // 2) if peer else 0
        else:
            peer = _find_node(nodes, connections[ci]["from"])
            coord = (peer["y"] + peer["height"] // 2) if peer else 0
        peer_coords.append((coord, ci))

    # Sort by peer Y coordinate (or X for vertical sides)
    if side in ("top", "bottom"):
        for ci in conn_indices:
            src, dst, src_side, dst_side = conn_sides[ci]
            if connections[ci]["from"] == nid:
                peer = _find_node(nodes, connections[ci]["to"])
                coord = (peer["x"] + peer["width"] // 2) if peer else 0
            else:
                peer = _find_node(nodes, connections[ci]["from"])
                coord = (peer["x"] + peer["width"] // 2) if peer else 0
            peer_coords.append((coord, ci))
        peer_coords = peer_coords[len(conn_indices):]

    peer_coords.sort(key=lambda t: t[0])
    for slot, (_, ci) in enumerate(peer_coords):
        port_indices[(ci, nid)] = slot


# Max spread between dst (or src) centers to allow grouping
_FAN_SPREAD_LIMIT = 600


def _align_fan_bends(edges, conn_sides, connections, nodes=None, groups=None):
    """Align bend positions and merge ports for fan-out and fan-in groups.

    Only activates when connections have "fan": "merge" set. A merged group is
    a hard constraint: all edges sharing the same source (fan-out) or the same
    target (fan-in) are forced onto ONE unified port and a shared trunk bend,
    regardless of which icon edge the router originally chose. The side is
    decided by majority vote across the group's edges so a single odd-side edge
    no longer splinters the group (the previous (from, src_side) keying did).

    After this runs, each rewritten edge carries `_fan_locked` so downstream
    optimizers (bend slide, side reselect, detour) leave its trunk alone — the
    merge is the spec, and crossing reduction must work AROUND it, not undo it.
    """
    def _apply_fan_guarded(indices, mode):
        # The user wants same-purpose edges merged, so a merge that adds only a
        # MODEST number of crossings is kept (a tidy trunk reads better than a
        # few crossings). Roll back when:
        #   - the merged trunk PIERCES any icon. A fan bundle is `_fan_locked`,
        #     so the downstream pierce-resolution passes (side reselect, detour)
        #     CANNOT clear it later — whatever the locked trunk cuts through is
        #     permanent. Individually-routed edges, by contrast, get cleaned up
        #     by those passes, so an unmerged fan whose members pierce here may
        #     still reach 0 pierces in the final layout. Hence the test is
        #     "trunk pierces anything at all" (after_p > 0), not the weaker
        #     "merge ADDED pierces" — the latter compares two pre-optimization
        #     snapshots and wrongly keeps a doomed locked trunk (e.g. four
        #     agents fanning into a Bedrock hub through the icons below them).
        #   - the merge adds MORE crossings than the bundle size — a sign the
        #     trunk is fighting another structure (e.g. a hub that is both a
        #     fan-in and fan-out target), where separate routing is cleaner.
        snap = {j: list(map(list, edges[j]["points"])) for j in indices}
        before_c = _count_all_crossings(edges)
        _rewrite_fan(edges, conn_sides, indices, mode=mode, nodes=nodes, groups=groups)
        after_p = _count_node_pierces([edges[j] for j in indices], nodes)
        after_c = _count_all_crossings(edges)
        if after_p > 0 or (after_c - before_c) > len(indices):
            for j in indices:
                edges[j]["points"] = snap[j]
                edges[j].pop("_fan_locked", None)

    # Fan-out: group purely by source node (side decided later by vote).
    src_groups = {}
    for i, (src, dst, src_side, dst_side) in enumerate(conn_sides):
        if src is None or len(edges[i]["points"]) < 2:
            continue
        if connections[i].get("fan") != "merge":
            continue
        src_groups.setdefault(connections[i]["from"], []).append(i)

    for indices in src_groups.values():
        if len(indices) < 2:
            continue
        _apply_fan_guarded(indices, "fan_out")

    # Fan-in: group purely by target node.
    dst_groups = {}
    for i, (src, dst, src_side, dst_side) in enumerate(conn_sides):
        if src is None or len(edges[i]["points"]) < 2:
            continue
        if connections[i].get("fan") != "merge":
            continue
        dst_groups.setdefault(connections[i]["to"], []).append(i)

    for indices in dst_groups.values():
        if len(indices) < 2:
            continue
        _apply_fan_guarded(indices, "fan_in")


def _spread_overlapping_bends(edges, conn_sides, connections):
    """Iteratively resolve edge crossings and separate close bends.

    Phase 1: Resolve all crossings by searching for optimal bend shifts.
    Phase 2: Separate bends that are too close (even if not crossing).
    """
    # Phase 1: resolve crossings
    for _iteration in range(_MAX_RESOLVE_ITERATIONS):
        crossing = _find_first_crossing(edges)
        if crossing is None:
            break
        i, si, j, sj = crossing
        _resolve_crossing_search(edges, i, si, j, sj)

    # Phase 2: separate close parallel bends
    _separate_close_bends(edges)
