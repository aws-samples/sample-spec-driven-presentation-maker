# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Route refinement: bend optimization, side reselection, pierce detours,
bend separation and fan-trunk rewriting.
"""

from .geometry import (
    _GROUP_FRAME_INSET,
    _PIERCE_WEIGHT,
    _count_all_crossings,
    _count_backwards,
    _count_group_pierces,
    _count_node_pierces,
    _edge_free_bend,
    _seg_crosses_box,
    _seg_pierces_node,
)
from .model import (
    _auto_sides,
    _elbow_path,
    _find_endpoint,
    _find_node,
    _group_member_ids,
    _port_point,
)




_MAX_RESOLVE_ITERATIONS = 30
_BEND_CANDIDATES = [-120, -100, -80, -60, -50, -40, -30, -20, -10, 10, 20, 30, 40, 50, 60, 80, 100, 120]


_BEND_OPT_PASSES = 40
_BEND_OPT_STEP = 4
_BEND_OPT_INSET = 6


def _optimize_bends(edges, nodes):
    """Slide free elbow bends to minimize global crossings + weighted pierces.

    Coordinate descent: repeatedly try shifting each edge's free middle bend
    to a range of candidate positions between its endpoints, keep the best.
    Only the two middle points of a 4-point VHV/HVH path move, and only along
    the trunk axis, so endpoints stay port-anchored and no diagonals appear.
    Skips fan-out edges (they share a deliberate trunk) and detours.
    """
    if not edges:
        return edges

    def cost(es):
        return _count_all_crossings(es) + _PIERCE_WEIGHT * _count_node_pierces(es, nodes)

    cur_cost = cost(edges)
    for _ in range(_BEND_OPT_PASSES):
        improved = False
        for e in edges:
            # A locked fan trunk must not move — sliding its free bend is what
            # shifts the shared trunk line, which would break the merge the
            # user explicitly requested. Leave it fixed.
            if e.get("_fan_locked"):
                continue
            # Fan-out edges start on a shared trunk but are still free to be
            # refined individually; optimizing them too reduces crossings
            # without breaking axis-alignment (their middle bend is free).
            fv = _edge_free_bend(e["points"])
            if not fv:
                continue
            axis, lo, hi = fv
            lo, hi = min(lo, hi), max(lo, hi)
            if hi - lo < 2 * _BEND_OPT_INSET:
                continue
            idx = 0 if axis == "x" else 1
            orig = e["points"][1][idx]
            best_val = orig
            best_cost = cur_cost
            cand = int(lo) + _BEND_OPT_INSET
            while cand < int(hi) - _BEND_OPT_INSET:
                if cand != orig:
                    saved1, saved2 = e["points"][1][idx], e["points"][2][idx]
                    e["points"][1][idx] = cand
                    e["points"][2][idx] = cand
                    c = cost(edges)
                    if c < best_cost:
                        best_cost = c
                        best_val = cand
                    e["points"][1][idx] = saved1
                    e["points"][2][idx] = saved2
                cand += _BEND_OPT_STEP
            if best_val != orig:
                e["points"][1][idx] = best_val
                e["points"][2][idx] = best_val
                cur_cost = best_cost
                improved = True
        if not improved:
            break
    return edges


def _optimize_single_bend(cand_pts, edge, edges, nodes):
    """Return cand_pts with its single free elbow bend slid to lowest weighted
    cost, evaluated against the live edge set (edge temporarily holds cand_pts).

    Used when judging a reselect candidate so we compare its BEST shape, not the
    arbitrary mid-bend the router emits. Only the two middle points of a 4-point
    VHV/HVH path move, along the trunk axis, so endpoints stay port-anchored.
    """
    fv = _edge_free_bend(cand_pts)
    if not fv:
        return cand_pts
    axis, lo, hi = fv
    lo, hi = min(lo, hi), max(lo, hi)
    if hi - lo < 2 * _BEND_OPT_INSET:
        return cand_pts
    idx = 0 if axis == "x" else 1
    saved = edge["points"]
    best = [list(p) for p in cand_pts]
    edge["points"] = best
    best_w = _defect_weight((_count_all_crossings(edges),
                             _count_node_pierces(edges, nodes),
                             _count_backwards(edges, nodes)))
    v = int(lo) + _BEND_OPT_INSET
    while v < int(hi) - _BEND_OPT_INSET:
        trial = [list(p) for p in cand_pts]
        trial[1][idx] = v
        trial[2][idx] = v
        edge["points"] = trial
        w = _defect_weight((_count_all_crossings(edges),
                            _count_node_pierces(edges, nodes),
                            _count_backwards(edges, nodes)))
        if w < best_w:
            best_w = w
            best = trial
        v += _BEND_OPT_STEP
    edge["points"] = saved
    return best


_SIDE_RESELECT_PASSES = 6
# (port_index, port_count): center, then 1/4, 1/2, 3/4 along the edge.
_PORT_TRIALS = [(0, 1), (0, 3), (1, 3), (2, 3)]

# Weights for comparing routing defects when reselecting sides. A pierce is the
# most visually damaging (a line cutting through an icon), so it outweighs a
# crossing; a backwards stub is the mildest. These mirror layout_qa.score().
_DEFECT_W = (1.0, 1.5, 0.7)  # (crossings, pierces, backwards)
# A line cutting through a framed group's box (without connecting to it or any
# icon inside) reads as broken. Weighted like a crossing — bad, but lighter
# than an icon pierce — and only steers the detour pass (it cannot un-pierce a
# box by changing port sides, only by routing around it).
_W_GROUP_PIERCE_ENGINE = 1.0
# How many extra crossings a side change may introduce to clear a pierce. One
# crossing is an acceptable price to stop a line cutting through an icon.
_RESELECT_CROSS_SLACK = 1


def _defect_weight(score):
    """Weighted scalar of a (crossings, pierces, backwards) tuple; lower better."""
    return sum(w * s for w, s in zip(_DEFECT_W, score))


def _candidate_side_pairs(src, dst):
    """Geometrically sane (src_side, dst_side) pairs; natural pair first.

    A "sane" side points toward the target — never away from it (which would
    force a backwards U-turn). For a target down-and-right of the source this
    yields src in {right, bottom} and dst in {left, top}.
    """
    s_cx = src["x"] + src.get("width", 60) / 2
    s_cy = src["y"] + src.get("height", 60) / 2
    d_cx = dst["x"] + dst.get("width", 60) / 2
    d_cy = dst["y"] + dst.get("height", 60) / 2
    src_sides, dst_sides = [], []
    if d_cx >= s_cx:
        src_sides.append("right")
        dst_sides.append("left")
    if d_cx <= s_cx:
        src_sides.append("left")
        dst_sides.append("right")
    if d_cy >= s_cy:
        src_sides.append("bottom")
        dst_sides.append("top")
    if d_cy <= s_cy:
        src_sides.append("top")
        dst_sides.append("bottom")
    pairs = []
    nat = _auto_sides(src, dst, None)
    pairs.append(nat)
    for s in dict.fromkeys(src_sides):
        for d in dict.fromkeys(dst_sides):
            if (s, d) not in pairs:
                pairs.append((s, d))
    return pairs


def _is_axis_aligned(pts):
    return all(
        pts[k][0] == pts[k + 1][0] or pts[k][1] == pts[k + 1][1]
        for k in range(len(pts) - 1)
    )


def _normalize_path(pts):
    """Collapse a polyline's degenerate artifacts in place-safe form.

    Splicing jogs (and stacking several) can leave a path with:
      - zero-length segments (consecutive identical points), and
      - redundant collinear vertices (three points in a row on one axis),
    which both read as a kink at a point that isn't really a corner and which
    inflate the crossing count when a stray zero-length stub coincides with
    another edge. This removes both without moving any real corner, so the
    drawn shape is identical but minimal. Endpoints (pts[0], pts[-1]) are
    preserved. Returns a new list; never shortens below 2 points.
    """
    if len(pts) < 2:
        return [list(p) for p in pts]
    # 1) drop consecutive duplicates (zero-length segments)
    dedup = [list(pts[0])]
    for p in pts[1:]:
        if p[0] != dedup[-1][0] or p[1] != dedup[-1][1]:
            dedup.append(list(p))
    # 2) drop the middle of any three collinear points (same X or same Y run)
    if len(dedup) <= 2:
        return dedup
    out = [dedup[0]]
    for i in range(1, len(dedup) - 1):
        a, b, c = out[-1], dedup[i], dedup[i + 1]
        collinear_x = a[0] == b[0] == c[0]
        collinear_y = a[1] == b[1] == c[1]
        if collinear_x or collinear_y:
            continue  # b lies on the straight run a→c; skip it
        out.append(b)
    out.append(dedup[-1])
    return out


def _entry_exit_ok(pts, src_side, dst_side):
    """First segment perpendicular to src edge, last to dst edge (no backwards).

    Rejects degenerate zero-length leading/trailing segments, which would
    otherwise read as both horizontal and vertical and let a parallel
    (non-perpendicular) run slip through.
    """
    if len(pts) < 2:
        return False
    if pts[0] == pts[1] or pts[-1] == pts[-2]:
        return False
    first_h = pts[0][1] == pts[1][1]
    last_h = pts[-1][1] == pts[-2][1]
    src_h = src_side in ("left", "right")
    dst_h = dst_side in ("left", "right")
    return (first_h == src_h) and (last_h == dst_h)


def _edge_pierces(e, nodes):
    """True if edge e passes through any non-endpoint icon interior."""
    pts = e["points"]
    if len(pts) < 2:
        return False
    ignore = {e["from"], e["to"]}
    for nid, n in nodes.items():
        short = nid.rsplit(".", 1)[-1]
        if nid in ignore or short in ignore:
            continue
        if any(_seg_pierces_node(pts[k], pts[k + 1], n) for k in range(len(pts) - 1)):
            return True
    return False


def _edge_backwards(e, nodes):
    """True if edge e has a first/last segment heading against its port normal."""
    return _count_backwards([e], nodes) > 0


def _path_stability(pts):
    """Tie-break key: prefer fewer, shorter segments."""
    length = sum(
        abs(pts[k + 1][0] - pts[k][0]) + abs(pts[k + 1][1] - pts[k][1])
        for k in range(len(pts) - 1)
    )
    return (len(pts), length)


def _reselect_sides(edges, nodes, obstacles):
    """Remove pierces by re-choosing icon side/port, never by adding segments.

    For each still-piercing edge, re-route via the elbow router using
    alternative (src_side, dst_side) pairs and port positions. Accept the
    alternative only if it does not raise the global crossing count and
    strictly lowers the global (crossings, pierces) tuple. Because crossings
    is a hard ceiling, structural pierces (where every alternative raises
    crossings) are correctly left untouched. Endpoints stay perpendicular
    because they come from _port_point; no diagonals because _elbow_path only
    emits H/V segments.
    """
    for _ in range(_SIDE_RESELECT_PASSES):
        piercing = [
            ei for ei, e in enumerate(edges)
            if not e.get("_fanout") and not e.get("_fan_locked")
            and len(e["points"]) >= 2
            and (_edge_pierces(e, nodes) or _edge_backwards(e, nodes))
        ]
        piercing.sort(key=lambda ei: (edges[ei]["from"], edges[ei]["to"]))
        committed = False

        for ei in piercing:
            e = edges[ei]
            src = _find_node(nodes, e["from"])
            dst = _find_node(nodes, e["to"])
            if not src or not dst:
                continue
            obs_excl = [o for o in obstacles if o.get("_node") not in (e["from"], e["to"])]
            label_h = 30 if src.get("label") else 0

            base = (_count_all_crossings(edges), _count_node_pierces(edges, nodes),
                    _count_backwards(edges, nodes))
            orig_pts = e["points"]
            best_pts = None
            best_score = base

            for (s_side, d_side) in _candidate_side_pairs(src, dst):
                for (si, sc) in _PORT_TRIALS:
                    for (qi, qc) in _PORT_TRIALS:
                        sp = _port_point(src, s_side, si, sc, label_h)
                        tp = _port_point(dst, d_side, qi, qc, label_h)
                        cand = _elbow_path(sp, tp, s_side, d_side, obs_excl)
                        if not _is_axis_aligned(cand):
                            continue
                        if not _entry_exit_ok(cand, s_side, d_side):
                            continue
                        # Judge the candidate by its BEST achievable shape: slide
                        # its free trunk bend to the lowest-cost position before
                        # scoring. A bottom→top reroute past a row of icons looks
                        # bad at the default mid-bend but clears everything once
                        # the trunk is nudged into the gap — evaluate THAT.
                        cand = _optimize_single_bend(cand, e, edges, nodes)
                        e["points"] = cand
                        score = (_count_all_crossings(edges), _count_node_pierces(edges, nodes),
                                 _count_backwards(edges, nodes))
                        e["points"] = orig_pts
                        # A pierce (line through a non-endpoint icon) reads worse
                        # than a crossing, so judge candidates by a WEIGHTED total
                        # (pierce 1.5 > cross 1.0 > backwards 0.7) rather than a
                        # strict crossings-first ceiling. This lets a still-piercing
                        # edge clear the icon even when doing so adds one crossing,
                        # matching the layout_qa objective. A guard still rejects
                        # trades that pile on crossings (more than +_RESELECT_CROSS_SLACK).
                        if score[0] > base[0] + _RESELECT_CROSS_SLACK:
                            continue
                        better = (
                            _defect_weight(score) < _defect_weight(best_score)
                            or (best_pts is not None
                                and _defect_weight(score) == _defect_weight(best_score)
                                and _path_stability(cand) < _path_stability(best_pts))
                        )
                        if better:
                            best_score = score
                            best_pts = cand

            if (best_pts is not None
                    and _defect_weight(best_score) < _defect_weight(base)
                    and best_score[0] <= base[0] + _RESELECT_CROSS_SLACK):
                e["points"] = best_pts
                committed = True

        if not committed:
            break
    return edges


_DETOUR_FACE_MARGIN = 18
_DETOUR_PASSES = 6
_JOG_ARM_STEP = 12


def _optimize_jog_arm(cand, k, edge, edges, nodes):
    """Slide a freshly-spliced jog arm to its lowest-cost parallel position.

    A jog splices 4 points at index k+1: [arm_a, corner_a, corner_b, arm_b].
    The two corners share one free coordinate (the arm's offset from the
    pierced segment) — x for a jog off a vertical segment, y for a horizontal
    one. The raw candidate hugs the obstacle face; sliding the arm outward can
    clear other edges it would otherwise cross. We scan a range of offsets and
    keep the one with the lowest weighted defect, evaluated against the live
    edge set. Endpoints (arm_a, arm_b) stay put, so the splice remains interior
    and axis-aligned.
    """
    if len(cand) < k + 5:
        return cand
    ca, cb = cand[k + 2], cand[k + 3]
    # Determine the free axis: corners share x (vertical-seg jog) or y (horiz).
    if ca[0] == cb[0]:
        axis = 0  # corners share X — slide X
    elif ca[1] == cb[1]:
        axis = 1  # corners share Y — slide Y
    else:
        return cand  # not a clean bracket

    def weighted(pts_override):
        saved = edge["points"]
        edge["points"] = pts_override
        s = (_count_all_crossings(edges), _count_node_pierces(edges, nodes),
             _count_backwards(edges, nodes))
        edge["points"] = saved
        return _defect_weight(s)

    base_val = ca[axis]
    best = cand
    best_w = weighted(cand)
    # Search outward on both sides of the current arm offset.
    for delta in range(-120, 121, _JOG_ARM_STEP):
        if delta == 0:
            continue
        v = base_val + delta
        trial = [list(p) for p in cand]
        trial[k + 2][axis] = v
        trial[k + 3][axis] = v
        if not _is_axis_aligned(trial):
            continue
        # The arm must not now pierce the very obstacle it was meant to clear,
        # nor any other — that is captured by the pierce term in the weight.
        w = weighted(trial)
        if w < best_w:
            best_w = w
            best = trial
    return best


def _jog_candidates(seg_a, seg_b, n):
    """Axis-aligned bracket detours around node n for piercing segment a->b.

    Returns replacement point-lists that splice into the segment interior:
    a -> (parallel run past one face of n) -> b. Every introduced segment is
    horizontal or vertical, and seg_a/seg_b are preserved verbatim, so true
    endpoints (when a/b are pts[0]/pts[-1]) never move. A candidate is
    discarded when the obstacle extends past the segment's own span (the jog
    would need to move an endpoint), guaranteeing the splice stays interior.
    """
    nx0, ny0 = n["x"], n["y"]
    nx1 = nx0 + n.get("width", 60)
    ny1 = ny0 + n.get("height", n.get("width", 60))
    m = _DETOUR_FACE_MARGIN
    out = []
    if seg_a[0] == seg_b[0]:  # vertical segment at x=X -> jog left/right
        x = seg_a[0]
        y_lo, y_hi = min(seg_a[1], seg_b[1]), max(seg_a[1], seg_b[1])
        # Bracket arms run parallel just past the obstacle's vertical extent,
        # clamped to stay strictly inside the segment span so the splice never
        # moves an endpoint. If the obstacle protrudes past an end, clamp the
        # arm to that endpoint (collapsing the stub to zero length there).
        b_lo = max(y_lo, ny0 - m)
        b_hi = min(y_hi, ny1 + m)
        if b_lo >= b_hi:
            return out  # no overlap to bracket
        for cx in (nx0 - m, nx1 + m):
            out.append([list(seg_a), [x, b_lo], [cx, b_lo], [cx, b_hi], [x, b_hi], list(seg_b)])
    elif seg_a[1] == seg_b[1]:  # horizontal segment at y=Y -> jog up/down
        y = seg_a[1]
        x_lo, x_hi = min(seg_a[0], seg_b[0]), max(seg_a[0], seg_b[0])
        b_lo = max(x_lo, nx0 - m)
        b_hi = min(x_hi, nx1 + m)
        if b_lo >= b_hi:
            return out
        for cy in (ny0 - m, ny1 + m):
            out.append([list(seg_a), [b_lo, y], [b_lo, cy], [b_hi, cy], [b_hi, y], list(seg_b)])
    return out


def _detour_around_pierces(edges, nodes, groups=None):
    """Splice obstacle jogs to clear pierces no side/port choice can fix.

    Obstacles are both non-endpoint ICONS and framed GROUP boxes that an edge
    cuts through without connecting to (group-frame pierce). The same bracket
    jog clears either — a box is just a wider obstacle. Group pierces feed the
    weighted cost so a detour around a frame is taken when it does not cost more
    crossings/icon-pierces than it saves.

    Greedy, one commit at a time, re-measuring the full live edge set after
    every tentative change. A jog is committed only if the global
    (crossings, pierces) tuple strictly improves AND crossings does not rise.
    This makes crossings monotone non-increasing — the separate-pass blow-up
    (where locally-accepted jogs interacted to raise global crossings) cannot
    recur. Structural pierces, whose every jog raises crossings, are left.
    """
    if not edges:
        return edges

    # Framed groups an edge may need to detour around (box obstacles).
    framed = [(gid, g) for gid, g in (groups or {}).items() if g.get("groupType")]

    def cost(es):
        gp = _count_group_pierces(es, groups, nodes) if framed else 0
        return (_count_all_crossings(es),
                _count_node_pierces(es, nodes) + _W_GROUP_PIERCE_ENGINE * gp,
                _count_backwards(es, nodes))

    for _ in range(_DETOUR_PASSES):
        cur = cost(edges)
        if cur[1] == 0:
            break
        improved = False

        for e in edges:
            # A locked fan trunk must keep its shape — splicing a jog into it
            # would bend the shared trunk and break the merge. Skip it; other
            # edges detour around it instead.
            if e.get("_fan_locked"):
                continue
            # Fan-out edges are eligible: a jog around an obstacle does not
            # break the shared-trunk concept, and the global gate below only
            # commits it when it strictly helps.
            pts = e["points"]
            if len(pts) < 2:
                continue
            ignore = {e["from"], e["to"]}
            # Box obstacles this edge must avoid: framed groups it neither
            # connects to nor has a member endpoint in.
            efrom = e["from"].rsplit(".", 1)[-1]
            eto = e["to"].rsplit(".", 1)[-1]
            box_obstacles = []
            for gid, g in framed:
                gshort = gid.rsplit(".", 1)[-1]
                if efrom == gshort or eto == gshort:
                    continue
                members = _group_member_ids(nodes, groups, gid)
                if efrom in members or eto in members:
                    continue
                box_obstacles.append(g)
            # A box detour is only worth taking if it removes ALL frame pierces
            # this edge causes — a partial detour that still clips a box just
            # adds wire/bends for a still-broken look (the microservices
            # bus-through-services case). Icon-pierce jogs keep their original
            # partial-improvement behaviour.
            base = cost(edges)
            best_pts = None
            best_score = base
            # Scan each segment for a pierced obstacle; build jog candidates.
            for k in range(len(pts) - 1):
                seg_a, seg_b = pts[k], pts[k + 1]
                # Obstacles for this segment: non-endpoint icons it pierces, plus
                # framed group boxes it cuts through.
                hit_obs = []
                for nid, n in nodes.items():
                    short = nid.rsplit(".", 1)[-1]
                    if nid in ignore or short in ignore:
                        continue
                    if _seg_pierces_node(seg_a, seg_b, n):
                        hit_obs.append((n, False))
                for g in box_obstacles:
                    if _seg_crosses_box(seg_a, seg_b, g["x"], g["y"],
                                        g["width"], g["height"], _GROUP_FRAME_INSET):
                        hit_obs.append((g, True))
                for n, is_box in hit_obs:
                    for repl in _jog_candidates(seg_a, seg_b, n):
                        cand = pts[:k + 1] + repl[1:-1] + pts[k + 1:]
                        if not _is_axis_aligned(cand):
                            continue
                        # The raw jog hugs the obstacle's face; that arm position
                        # may cross other edges. Slide the jog arm to its best
                        # position FIRST, then judge — mirrors evaluating a config
                        # by its post-bend-optimization quality, not its raw form.
                        cand = _optimize_jog_arm(cand, k, e, edges, nodes)
                        # Strip zero-length / collinear artifacts the splice (or
                        # a previously-committed jog stacked on this segment) may
                        # have left, so a stray stub can't fake a crossing and the
                        # committed shape is minimal.
                        cand = _normalize_path(cand)
                        saved = e["points"]
                        e["points"] = cand
                        score = cost(edges)
                        # A box detour must fully clear this edge's frame
                        # pierces; a partial escape is rejected so we never
                        # commit a longer, still-piercing route.
                        box_pierce_after = (_count_group_pierces([e], groups, nodes)
                                            if box_obstacles else 0)
                        e["points"] = saved
                        # Box detour: accept ONLY when it fully clears this
                        # edge of every frame it cut through. A still-clipping
                        # detour (after > 0) is the structural case the user
                        # must fix by restructuring — leave it untouched and let
                        # the warning flag it.
                        if is_box and box_pierce_after != 0:
                            continue
                        # Judge by weighted defect (pierce 1.5 > cross 1.0): a jog
                        # may add up to _RESELECT_CROSS_SLACK crossings to lift a
                        # line off an icon it cuts through, which reads far worse
                        # than a crossing. Mirrors _reselect_sides.
                        if score[0] > base[0] + _RESELECT_CROSS_SLACK:
                            continue
                        if _defect_weight(score) < _defect_weight(best_score) or (
                            best_pts is not None
                            and _defect_weight(score) == _defect_weight(best_score)
                            and _path_stability(cand) < _path_stability(best_pts)
                        ):
                            best_score = score
                            best_pts = cand
            if (best_pts is not None
                    and _defect_weight(best_score) < _defect_weight(base)
                    and best_score[0] <= base[0] + _RESELECT_CROSS_SLACK):
                e["points"] = best_pts
                improved = True

        if not improved:
            break
    return edges


_MIN_BEND_SEPARATION = 40


def _resolve_crossing_search(edges, i, si, j, sj):
    """Try all candidate shifts for both crossing edges and pick the best.

    Scoring: (crossings, -min_bend_separation, displacement)
    1. Minimize total crossings (most important)
    2. Maximize minimum distance between parallel bends (visual clarity)
    3. Minimize displacement from original position (stability)
    """
    import copy

    pts_i = edges[i]["points"]
    pts_j = edges[j]["points"]
    a1, a2 = pts_i[si], pts_i[si + 1]
    b1, b2 = pts_j[sj], pts_j[sj + 1]

    current_crossings = _count_all_crossings(edges)
    current_separation = _min_bend_separation(edges)
    best_score = (current_crossings, -current_separation, 0)
    best_patch = None

    candidates = []
    for edge_idx, seg_idx, pt1, pt2 in [(i, si, a1, a2), (j, sj, b1, b2)]:
        is_vert = pt1[0] == pt2[0]
        is_horiz = pt1[1] == pt2[1]
        if is_vert:
            for delta in _BEND_CANDIDATES:
                candidates.append((edge_idx, "x", seg_idx, delta))
        if is_horiz:
            for delta in _BEND_CANDIDATES:
                candidates.append((edge_idx, "y", seg_idx, delta))

    for edge_idx, axis, seg, delta in candidates:
        test_edges = copy.deepcopy(edges)
        pts = test_edges[edge_idx]["points"]

        if axis == "x":
            _apply_bend_shift_x(pts, seg, delta)
        else:
            _apply_bend_shift_y(pts, seg, delta)

        crossings = _count_all_crossings(test_edges)
        separation = _min_bend_separation(test_edges)
        score = (crossings, -separation, abs(delta))

        if score < best_score:
            best_score = score
            best_patch = (edge_idx, copy.deepcopy(test_edges[edge_idx]["points"]))

    if best_patch is not None:
        edge_idx, new_pts = best_patch
        edges[edge_idx]["points"] = new_pts


def _min_bend_separation(edges):
    """Calculate the minimum distance between parallel bend segments.

    Checks all pairs of vertical bends (same-ish Y range) for X separation,
    and all pairs of horizontal bends (same-ish X range) for Y separation.
    Returns the minimum separation found (larger = better visual clarity).
    """
    vertical_bends = []
    horizontal_bends = []

    for e in edges:
        pts = e["points"]
        if len(pts) < 4:
            continue
        for k in range(len(pts) - 1):
            p1, p2 = pts[k], pts[k + 1]
            if p1[0] == p2[0] and abs(p1[1] - p2[1]) > 10:
                y_min, y_max = min(p1[1], p2[1]), max(p1[1], p2[1])
                vertical_bends.append((p1[0], y_min, y_max))
            elif p1[1] == p2[1] and abs(p1[0] - p2[0]) > 10:
                x_min, x_max = min(p1[0], p2[0]), max(p1[0], p2[0])
                horizontal_bends.append((p1[1], x_min, x_max))

    min_sep = 9999

    for a in range(len(vertical_bends)):
        for b in range(a + 1, len(vertical_bends)):
            ax, ay_min, ay_max = vertical_bends[a]
            bx, by_min, by_max = vertical_bends[b]
            overlap_y = min(ay_max, by_max) - max(ay_min, by_min)
            if overlap_y > 10:
                sep = abs(ax - bx)
                if sep < min_sep:
                    min_sep = sep

    for a in range(len(horizontal_bends)):
        for b in range(a + 1, len(horizontal_bends)):
            ay, ax_min, ax_max = horizontal_bends[a]
            by, bx_min, bx_max = horizontal_bends[b]
            overlap_x = min(ax_max, bx_max) - max(ax_min, bx_min)
            if overlap_x > 10:
                sep = abs(ay - by)
                if sep < min_sep:
                    min_sep = sep

    return min_sep


def _separate_close_bends(edges):
    """Spread parallel bends that are too close, distributing them evenly.

    Groups vertical bends that share a similar X position (within _MIN_BEND_SEPARATION)
    AND whose Y ranges are adjacent or overlapping. Spreads their X positions evenly
    with _MIN_BEND_SEPARATION between each.
    Does not introduce new crossings.
    """
    import copy

    # Collect all vertical bend segments: (edge_idx, seg_idx, x, y_min, y_max)
    v_bends = []
    for ei, e in enumerate(edges):
        if e.get("_fanout"):
            continue
        pts = e["points"]
        for k in range(len(pts) - 1):
            if pts[k][0] == pts[k + 1][0] and abs(pts[k][1] - pts[k + 1][1]) > 10:
                y_min = min(pts[k][1], pts[k + 1][1])
                y_max = max(pts[k][1], pts[k + 1][1])
                v_bends.append((ei, k, pts[k][0], y_min, y_max))

    # Group bends that are close in X AND adjacent/overlapping in Y
    # BUT: only group bends from DIFFERENT source nodes.
    # Bends from the same source should be aligned (not separated).
    used = set()
    groups = []
    for a in range(len(v_bends)):
        if a in used:
            continue
        group = [a]
        group_y_min = v_bends[a][3]
        group_y_max = v_bends[a][4]
        src_a = edges[v_bends[a][0]]["from"]
        for b in range(a + 1, len(v_bends)):
            if b in used:
                continue
            ei_b = v_bends[b][0]
            src_b = edges[ei_b]["from"]
            # Skip if same source — those should stay aligned
            if src_b == src_a:
                continue
            _, _, bx, by_min, by_max = v_bends[b]
            group_x_avg = sum(v_bends[idx][2] for idx in group) // len(group)
            if abs(bx - group_x_avg) >= _MIN_BEND_SEPARATION:
                continue
            gap = max(by_min - group_y_max, group_y_min - by_max)
            if gap < 50:
                group.append(b)
                group_y_min = min(group_y_min, by_min)
                group_y_max = max(group_y_max, by_max)
        if len(group) < 2:
            continue
        used.update(group)
        groups.append(group)

    # Spread each group evenly
    for group in groups:
        group_bends = [(v_bends[idx], idx) for idx in group]
        group_bends.sort(key=lambda t: (t[0][3] + t[0][4]) / 2)
        center_x = sum(v[0][2] for v in group_bends) // len(group_bends)
        spread_total = _MIN_BEND_SEPARATION * (len(group_bends) - 1)
        start_x = center_x - spread_total // 2

        current_crossings = _count_all_crossings(edges)
        for slot, (bend_info, _) in enumerate(group_bends):
            ei, seg_k, old_x, _, _ = bend_info
            new_x = start_x + slot * _MIN_BEND_SEPARATION
            if new_x == old_x:
                continue
            test_edges = copy.deepcopy(edges)
            delta = new_x - old_x
            _apply_bend_shift_x(test_edges[ei]["points"], seg_k, delta)
            if _count_all_crossings(test_edges) <= current_crossings:
                _apply_bend_shift_x(edges[ei]["points"], seg_k, delta)

    # Align bends from the same source to a single X position
    _align_same_source_bends(edges)

    # Also spread close horizontal segments
    _separate_close_horizontal_segments(edges)


def _align_same_source_bends(edges):
    """Align bends from the same source node to a single X (or Y) position.

    When multiple edges fan out from the same node, their vertical bends
    should share the same X so they look like a clean tree branch.
    Only aligns if it doesn't introduce new crossings.
    """
    import copy

    # Group edges by source
    src_groups = {}
    for ei, e in enumerate(edges):
        pts = e["points"]
        if len(pts) < 4:
            continue
        src_groups.setdefault(e["from"], []).append(ei)

    current_crossings = _count_all_crossings(edges)

    for src, edge_indices in src_groups.items():
        if len(edge_indices) < 2:
            continue

        # Skip alignment if start Y positions differ (fan-out with distributed ports)
        start_ys = [edges[ei]["points"][0][1] for ei in edge_indices]
        if max(start_ys) - min(start_ys) > 10:
            continue

        # Collect vertical bend X positions for these edges
        bend_xs = []
        for ei in edge_indices:
            pts = edges[ei]["points"]
            for k in range(len(pts) - 1):
                if pts[k][0] == pts[k + 1][0] and abs(pts[k][1] - pts[k + 1][1]) > 5:
                    bend_xs.append((ei, k, pts[k][0]))
                    break

        if len(bend_xs) < 2:
            continue

        # All already aligned?
        xs = [x for _, _, x in bend_xs]
        if max(xs) - min(xs) <= 5:
            continue

        # Try aligning to the median X
        target_x = sorted(xs)[len(xs) // 2]

        # Test: align all to target_x
        test_edges = copy.deepcopy(edges)
        for ei, k, old_x in bend_xs:
            if old_x != target_x:
                delta = target_x - old_x
                _apply_bend_shift_x(test_edges[ei]["points"], k, delta)

        if _count_all_crossings(test_edges) <= current_crossings:
            for ei, k, old_x in bend_xs:
                if old_x != target_x:
                    delta = target_x - old_x
                    _apply_bend_shift_x(edges[ei]["points"], k, delta)

    # Same for destination (fan-in): align bends going to the same target
    dst_groups = {}
    for ei, e in enumerate(edges):
        pts = e["points"]
        if len(pts) < 4:
            continue
        dst_groups.setdefault(e["to"], []).append(ei)

    current_crossings = _count_all_crossings(edges)

    for dst, edge_indices in dst_groups.items():
        if len(edge_indices) < 2:
            continue

        bend_xs = []
        for ei in edge_indices:
            pts = edges[ei]["points"]
            for k in range(len(pts) - 1):
                if pts[k][0] == pts[k + 1][0] and abs(pts[k][1] - pts[k + 1][1]) > 5:
                    bend_xs.append((ei, k, pts[k][0]))
                    break

        if len(bend_xs) < 2:
            continue

        xs = [x for _, _, x in bend_xs]
        if max(xs) - min(xs) <= 5:
            continue

        target_x = sorted(xs)[len(xs) // 2]

        test_edges = copy.deepcopy(edges)
        for ei, k, old_x in bend_xs:
            if old_x != target_x:
                delta = target_x - old_x
                _apply_bend_shift_x(test_edges[ei]["points"], k, delta)

        if _count_all_crossings(test_edges) <= current_crossings:
            for ei, k, old_x in bend_xs:
                if old_x != target_x:
                    delta = target_x - old_x
                    _apply_bend_shift_x(edges[ei]["points"], k, delta)


def _separate_close_horizontal_segments(edges):
    """Detect horizontal segments at nearly the same Y with overlapping X range.

    When two horizontal segments from different edges are within
    _MIN_BEND_SEPARATION/2 in Y and overlap in X, shift one edge's bend
    to create visual separation.
    """
    import copy

    # Collect all horizontal segments: (edge_idx, seg_idx, y, x_min, x_max)
    h_segs = []
    for ei, e in enumerate(edges):
        pts = e["points"]
        for k in range(len(pts) - 1):
            if pts[k][1] == pts[k + 1][1] and abs(pts[k][0] - pts[k + 1][0]) > 20:
                x_min = min(pts[k][0], pts[k + 1][0])
                x_max = max(pts[k][0], pts[k + 1][0])
                h_segs.append((ei, k, pts[k][1], x_min, x_max))

    current_crossings = _count_all_crossings(edges)
    adjusted = set()
    for a in range(len(h_segs)):
        for b in range(a + 1, len(h_segs)):
            ei_a, k_a, y_a, xmin_a, xmax_a = h_segs[a]
            ei_b, k_b, y_b, xmin_b, xmax_b = h_segs[b]
            if ei_a == ei_b:
                continue
            y_diff = abs(y_a - y_b)
            if y_diff >= _MIN_BEND_SEPARATION // 2:
                continue
            overlap = min(xmax_a, xmax_b) - max(xmin_a, xmin_b)
            if overlap <= 20:
                continue

            # Try shifting either edge's vertical bend X to shorten/lengthen
            # the horizontal segment so they no longer overlap in X.
            resolved = False
            for ei, k in [(ei_a, k_a), (ei_b, k_b)]:
                if ei in adjusted or resolved:
                    continue
                pts = edges[ei]["points"]
                # Find the vertical bend in this edge
                for vk in range(len(pts) - 1):
                    if pts[vk][0] == pts[vk + 1][0] and abs(pts[vk][1] - pts[vk + 1][1]) > 5:
                        # Try shifting this bend X to reduce horizontal overlap
                        other_xmin = xmin_b if ei == ei_a else xmin_a
                        other_xmax = xmax_b if ei == ei_a else xmax_a
                        # Shift bend to just before or after the other segment
                        for delta in [-60, -40, 60, 40, -80, 80, -100, 100]:
                            test_edges = copy.deepcopy(edges)
                            _apply_bend_shift_x(test_edges[ei]["points"], vk, delta)
                            # Check: overlap reduced AND no new crossings
                            new_crossings = _count_all_crossings(test_edges)
                            # Recalculate overlap
                            new_pts = test_edges[ei]["points"]
                            for nk in range(len(new_pts) - 1):
                                if new_pts[nk][1] == new_pts[nk + 1][1] and abs(new_pts[nk][0] - new_pts[nk + 1][0]) > 20:
                                    new_xmin = min(new_pts[nk][0], new_pts[nk + 1][0])
                                    new_xmax = max(new_pts[nk][0], new_pts[nk + 1][0])
                                    if abs(new_pts[nk][1] - (y_b if ei == ei_a else y_a)) < _MIN_BEND_SEPARATION // 2:
                                        new_overlap = min(new_xmax, other_xmax) - max(new_xmin, other_xmin)
                                        if new_overlap <= 20 and new_crossings <= current_crossings:
                                            _apply_bend_shift_x(edges[ei]["points"], vk, delta)
                                            adjusted.add(ei)
                                            resolved = True
                                            break
                            if resolved:
                                break
                        break


def _apply_bend_shift_x(points, seg_idx, delta):
    """Shift the vertical bend at seg_idx by delta on the X axis.

    Never moves the first or last point (port-anchored endpoints).
    """
    if len(points) < 3:
        return
    p1 = points[seg_idx]
    p2 = points[min(seg_idx + 1, len(points) - 1)]
    if p1[0] == p2[0]:
        target_x = p1[0]
    elif seg_idx > 0 and points[seg_idx - 1][0] == p1[0]:
        target_x = p1[0]
    else:
        target_x = p1[0]

    for i, pt in enumerate(points):
        if i == 0 or i == len(points) - 1:
            continue
        if pt[0] == target_x:
            pt[0] += delta


def _apply_bend_shift_y(points, seg_idx, delta):
    """Shift the horizontal bend at seg_idx by delta on the Y axis.

    Never moves the first or last point (port-anchored endpoints).
    Only shifts points that are part of an internal horizontal segment
    (not adjacent to the start/end points).
    """
    if len(points) < 4:
        return
    p1 = points[seg_idx]
    p2 = points[min(seg_idx + 1, len(points) - 1)]
    if p1[1] == p2[1]:
        target_y = p1[1]
    elif seg_idx > 0 and points[seg_idx - 1][1] == p1[1]:
        target_y = p1[1]
    else:
        target_y = p1[1]

    # Don't shift if target_y matches start or end Y (would break port alignment)
    if target_y == points[0][1] or target_y == points[-1][1]:
        return

    for i, pt in enumerate(points):
        if i == 0 or i == len(points) - 1:
            continue
        if pt[1] == target_y:
            pt[1] += delta


def _update_bend_x(points, old_x, new_x):
    """Update bend X coordinate in a 4-point elbow path."""
    for pt in points:
        if abs(pt[0] - old_x) < 3:
            pt[0] = new_x


_FAN_BEND_MARGIN = 30
# How far past a framed group's edge the fan trunk is pushed so the split/merge
# happens clearly outside the box, not flush against the frame.
_FAN_GROUP_CLEARANCE = 22


def _enclosing_framed_group(groups, nodes, node_id):
    """Return the geometry of the framed group that directly encloses node_id.

    A fan hub that lives inside a drawn box should split/merge OUTSIDE that box.
    We find the framed (groupType) group whose member set contains node_id and,
    if several nest, pick the SMALLEST (innermost) by area — that is the frame
    the trunk must clear first. Returns the group dict or None.
    """
    if not groups:
        return None
    short = node_id.rsplit(".", 1)[-1]
    best = None
    for gid, g in groups.items():
        if not g.get("groupType"):
            continue
        members = _group_member_ids(nodes, groups, gid)
        if short in members:
            area = g["width"] * g["height"]
            if best is None or area < best[0]:
                best = (area, g)
    return best[1] if best else None


def _push_trunk_outside_group(trunk_v, side, vertical, nearest, hbox):
    """Shift a fan trunk coordinate to just past the hub's enclosing frame.

    The trunk is the shared line where the bundle splits (fan-out) or merges
    (fan-in). When the hub sits inside a framed box, a trunk flush against the
    icon still bends inside the frame. Push it past the frame edge it exits
    through (by _FAN_GROUP_CLEARANCE), but clamp so it never reaches/over­shoots
    the nearest spoke — leaving the spoke side of the gap for the actual fan.
    No-op when there is no enclosing frame or the push would cross the spoke.
    """
    if hbox is None:
        return trunk_v
    if vertical:
        edge = hbox["y"] + hbox["height"] if side == "bottom" else hbox["y"]
    else:
        edge = hbox["x"] + hbox["width"] if side == "right" else hbox["x"]
    if side in ("right", "bottom"):
        target = edge + _FAN_GROUP_CLEARANCE
        # only push outward, and stay short of the nearest spoke
        if target > trunk_v and target < nearest:
            return target
    else:  # left / top — frame edge is on the smaller-coordinate side
        target = edge - _FAN_GROUP_CLEARANCE
        if target < trunk_v and target > nearest:
            return target
    return trunk_v


def _fan_side_vote(edges, conn_sides, indices, mode, nodes=None, groups=None):
    """Pick the single shared hub side for a fan group from GEOMETRY.

    The hub end (src for fan-out, dst for fan-in) must agree on ONE side so all
    edges leave/enter through one unified port. We choose the box edge that
    faces the spokes' centroid: e.g. a hub directly BELOW a row of spokes is
    entered through its TOP. This is far more robust than the old majority vote
    over per-edge router sides, which picked "right" for a hub sitting squarely
    below its sources (each spoke saw a different diagonal direction).
    """
    hub_id = edges[indices[0]]["from"] if mode == "fan_out" else edges[indices[0]]["to"]
    hub, _ = _find_endpoint(nodes or {}, groups or {}, hub_id)
    spokes = []
    for i in indices:
        sid = edges[i]["to"] if mode == "fan_out" else edges[i]["from"]
        s, _ = _find_endpoint(nodes or {}, groups or {}, sid)
        if s is not None:
            spokes.append(s)
    if hub is not None and spokes:
        hcx = hub["x"] + hub["width"] / 2
        hcy = hub["y"] + hub["height"] / 2
        scx = sum(s["x"] + s["width"] / 2 for s in spokes) / len(spokes)
        scy = sum(s["y"] + s["height"] / 2 for s in spokes) / len(spokes)
        dx, dy = scx - hcx, scy - hcy  # direction from hub toward spokes
        if abs(dx) >= abs(dy):
            return "right" if dx > 0 else "left"
        return "bottom" if dy > 0 else "top"

    # Fallback: majority vote over router-chosen sides.
    pref = {"right": 0, "left": 1, "bottom": 2, "top": 3}
    votes = {}
    for i in indices:
        _, _, src_side, dst_side = conn_sides[i]
        side = src_side if mode == "fan_out" else dst_side
        if side:
            votes[side] = votes.get(side, 0) + 1
    if not votes:
        return "right"
    return sorted(votes.items(), key=lambda kv: (-kv[1], pref.get(kv[0], 9)))[0][0]


def _rewrite_fan(edges, conn_sides, indices, mode, nodes=None, groups=None):
    """Force a fan-out/fan-in group onto a unified port and a shared trunk.

    The merge is a hard constraint (the LLM asked for it), so we rebuild every
    edge in the group from scratch as a clean 4-point elbow:
      - one shared port on the hub node (computed from node geometry, centered),
      - a shared trunk coordinate (all edges bend at the same line),
      - the spoke then peels off to each individual target/source.
    The hub may be a NODE or a GROUP (box) — both expose x/y/width/height, so a
    group hub gets a single shared port on its box edge just like a node. Edges
    that had become detours (len>4) are rebuilt too. Each edge is tagged
    `_fan_locked` so downstream optimizers don't undo the alignment.
    """
    if not indices:
        return
    side = _fan_side_vote(edges, conn_sides, indices, mode, nodes, groups)
    vertical = side in ("top", "bottom")

    # Resolve the hub (shared end) — node OR group — and its geometry.
    hub_id = edges[indices[0]]["from"] if mode == "fan_out" else edges[indices[0]]["to"]
    hub, hub_is_group = _find_endpoint(nodes or {}, groups or {}, hub_id)

    # Unified port point on the hub edge, centered along that edge.
    if hub is not None:
        hx, hy, hw, hh = hub["x"], hub["y"], hub["width"], hub["height"]
        # A group port sits on the box edge (no label band offset).
        label_h = 0 if hub_is_group else (30 if hub.get("label") else 0)
        if side == "right":
            port = [hx + hw, hy + hh // 2]
        elif side == "left":
            port = [hx, hy + hh // 2]
        elif side == "bottom":
            port = [hx + hw // 2, hy + hh + label_h]
        else:  # top
            port = [hx + hw // 2, hy]
    else:
        # Fall back to averaging the existing ports if geometry is unavailable.
        ends = [edges[j]["points"][0] if mode == "fan_out" else edges[j]["points"][-1]
                for j in indices]
        port = [sum(p[0] for p in ends) // len(ends), sum(p[1] for p in ends) // len(ends)]

    # Shared trunk coordinate: a line in the GAP between the hub port and the
    # nearest spoke. It must stay strictly between the two — if the gap is
    # narrower than the preferred margin, fall back to the midpoint rather than
    # overshooting the spoke (which would drive the trunk into the spoke icons,
    # the bug that made stacked fan-outs pierce their targets).
    spoke_ends = [edges[j]["points"][-1] if mode == "fan_out" else edges[j]["points"][0]
                  for j in indices]

    def _gap_trunk(p0, nearest):
        # p0 = hub port coordinate, nearest = closest spoke coordinate.
        lo, hi = (p0, nearest) if p0 <= nearest else (nearest, p0)
        mid = (p0 + nearest) // 2
        if hi - lo <= 2 * _FAN_BEND_MARGIN:
            return mid  # gap too tight for the margin → sit in the middle
        # otherwise sit _FAN_BEND_MARGIN away from the hub, toward the spoke
        return p0 + _FAN_BEND_MARGIN if p0 < nearest else p0 - _FAN_BEND_MARGIN

    if vertical:
        spoke_vs = [p[1] for p in spoke_ends]
        nearest = min(spoke_vs) if side == "bottom" else max(spoke_vs)
        trunk_v = _gap_trunk(port[1], nearest)
    else:
        spoke_hs = [p[0] for p in spoke_ends]
        nearest = min(spoke_hs) if side == "right" else max(spoke_hs)
        trunk_v = _gap_trunk(port[0], nearest)

    # Keep the split/merge OUTSIDE the hub's framed group. When the hub icon
    # lives inside a drawn box (e.g. EventBridge inside "Orchestration"), a
    # trunk sitting just past the icon still bends WHILE inside the frame, so
    # the fan visibly branches within an unrelated container. Push the trunk
    # past the frame edge it exits through (plus a margin) so the bundle leaves
    # the box as one line and only fans out beyond it — but never past the
    # nearest spoke (that would drive the trunk into the targets). Only applies
    # when the hub is a NODE enclosed by a framed group on the exit side.
    if not hub_is_group and groups:
        trunk_v = _push_trunk_outside_group(
            trunk_v, side, vertical, nearest,
            _enclosing_framed_group(groups, nodes, hub_id))

    # The spoke nodes (the N individual ends) must ALSO leave/enter through a
    # consistent edge — the one facing the trunk. A fan-in to a trunk BELOW the
    # agents means every agent exits its BOTTOM edge (not whichever side the
    # router first picked, which left planner exiting "right" and coder "left").
    # The spoke side is the side facing the trunk: opposite the hub side for the
    # spoke's own port normal.
    def spoke_port(node, sside, is_group):
        nx, ny, nw, nh = node["x"], node["y"], node["width"], node["height"]
        nlabel_h = 0 if is_group else (30 if node.get("label") else 0)
        if sside == "bottom":
            return [nx + nw // 2, ny + nh + nlabel_h]
        if sside == "top":
            return [nx + nw // 2, ny]
        if sside == "right":
            return [nx + nw, ny + nh // 2]
        return [nx, ny + nh // 2]  # left

    for i in indices:
        # spoke end = the per-edge individual end (target for fan-out, source for
        # fan-in); it may itself be a node OR a group.
        spoke_id = edges[i]["to"] if mode == "fan_out" else edges[i]["from"]
        spoke_node, spoke_is_group = _find_endpoint(nodes or {}, groups or {}, spoke_id)
        pts = edges[i]["points"]

        # Decide which spoke edge faces the trunk. The trunk is a line on the
        # `side` axis relative to the hub; the spoke must exit toward it.
        if vertical:
            # trunk is a horizontal line at y=trunk_v; spoke exits bottom if it
            # sits above the trunk, else top.
            ref = (spoke_node["y"] + spoke_node["height"] // 2) if spoke_node else pts[0][1]
            s_side = "bottom" if trunk_v >= ref else "top"
        else:
            ref = (spoke_node["x"] + spoke_node["width"] // 2) if spoke_node else pts[0][0]
            s_side = "right" if trunk_v >= ref else "left"

        if spoke_node is not None:
            spoke_pt = spoke_port(spoke_node, s_side, spoke_is_group)
        else:
            spoke_pt = list(pts[-1] if mode == "fan_out" else pts[0])

        if mode == "fan_out":
            tgt = spoke_pt
            if vertical:
                edges[i]["points"] = [list(port), [port[0], trunk_v], [tgt[0], trunk_v], tgt]
            else:
                edges[i]["points"] = [list(port), [trunk_v, port[1]], [trunk_v, tgt[1]], tgt]
        else:  # fan_in
            srcp = spoke_pt
            if vertical:
                edges[i]["points"] = [srcp, [srcp[0], trunk_v], [port[0], trunk_v], list(port)]
            else:
                edges[i]["points"] = [srcp, [trunk_v, srcp[1]], [trunk_v, port[1]], list(port)]
        # Lock the trunk: downstream optimizers must not move the shared
        # coordinate. The spoke (3rd point toward the individual end) stays
        # free to be nudged if needed.
        edges[i]["_fan_locked"] = {
            "mode": mode,
            "axis": "y" if vertical else "x",
            "trunk": trunk_v,
            "port": list(port),
        }
