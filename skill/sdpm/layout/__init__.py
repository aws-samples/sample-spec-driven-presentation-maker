# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Layout engine: compute coordinates from logical structure JSON."""


def optimize_order(tree, enable_reflow=True):
    """Pre-process: reorder children in groups to minimize edge crossings.

    Handles both leaf-only AND mixed groups (groups containing sub-groups).
    Uses brute-force permutation search for small groups (≤7 children) and
    heuristic sorting for larger ones. Counts actual crossing pairs using a
    two-layer position model (internal positions + external peer positions).

    ``enable_reflow`` runs the tile-pool reflow pass at the end. It is set
    False when the reflow pass itself re-lays-out candidate arrangements, so
    the real-routing evaluation does not recurse back into reflow.

    Mutates tree in-place. Call before _layout_scale.
    """
    connections = tree.get("connections", [])
    if not connections:
        return
    # Shape-first pre-pass: pull degree-1 auxiliary nodes that sit ON the main
    # flow line out into a perpendicular lane so the straight through-edge does
    # not pierce them (e.g. a Bedrock fallback wedged between Router and the
    # model group). Runs before ordering so the new sub-groups get ordered too.
    _promote_branch_nodes(tree, connections)
    # Also tag hand-authored invisible lanes (e.g. a {router, bedrock} vertical
    # column the LLM wrote directly) with their flow anchor, so the same
    # anchor-on-flow alignment applies as for engine-promoted lanes.
    _tag_manual_branch_anchors(tree, connections)
    # Order children within each group to minimize crossings. Uses a routed-
    # quality model that accounts not just for leaf-vs-leaf crossings but also
    # for an edge to a sibling GROUP box having to detour around a nearer child
    # (see _count_crossings_for_mixed_order's peer-adjacency term).
    _optimize_group_order(tree, connections)
    # Reflow tile pools: a group whose children are all anonymous, frameless,
    # leaf-only sub-columns of one orientation (pure tiling with no semantic
    # sub-grouping) can have its leaves reassigned across columns to shorten
    # wiring — seating externally-connected leaves at the peer-facing end.
    # Ordering alone can't do this (it never moves a leaf between sub-columns).
    if enable_reflow:
        _reflow_tile_pools(tree)


def _tag_manual_branch_anchors(node, connections, root=None):
    """Tag hand-authored invisible linear sub-groups with their flow anchor.

    The engine's own _promote_branch_nodes tags the lanes IT creates, but an
    author may hand-write the same shape — an invisible (no groupType/label)
    horizontal/vertical group stacking a flow node with an auxiliary one, e.g.
    ``{router, bedrock}`` so Bedrock sits beside Router. Block-placement then
    centres that group by its bounding box, pushing the flow node off the main
    line. We detect such a group and tag it with ``_branch_anchor`` = the sole
    member that connects OUTSIDE the group (the flow node); the layout pass then
    keeps that member on the flow line and lets the rest hang off to the side.
    Mutates in place. Skips groups that already carry the tag.
    """
    if root is None:
        root = node
    for child in node.get("children", []):
        _tag_manual_branch_anchors(child, connections, root)

    children = node.get("children", [])
    if len(children) < 2 or node.get("_branch_anchor"):
        return
    # Only invisible linear groups qualify (a visible box is a deliberate
    # cluster, not a flow node + offset branch).
    if node.get("direction") not in ("horizontal", "vertical"):
        return
    if node.get("groupType") or node.get("label"):
        return
    # Every direct child must be a bare leaf (the {anchor, branch} pattern).
    member_ids = []
    for c in children:
        if c.get("children") or "id" not in c:
            return
        member_ids.append(c["id"])
    member_set = set(member_ids)

    # An "anchor" is a member that connects to something OUTSIDE this group.
    outward = []
    for c in children:
        cid = c["id"]
        for conn in connections:
            other = None
            if conn["from"] == cid:
                other = conn["to"]
            elif conn["to"] == cid:
                other = conn["from"]
            if other is not None and other not in member_set:
                outward.append(cid)
                break
    # Tag only when exactly ONE member reaches outside — that is unambiguously
    # the flow node; the rest are branches hanging off it.
    if len(outward) == 1:
        node["_branch_anchor"] = outward[0]


def _promote_branch_nodes(node, connections, root=None):
    """Move degree-1 'branch' leaves off the main flow into a perpendicular lane.

    Detects the human-layout pattern: in a linear (horizontal/vertical) group,
    a leaf ``b`` with exactly one connection whose anchor ``a`` is a sibling in
    the same group, where another edge from ``a`` runs straight past ``b``'s
    slot to a node on the far side. Drawn linearly, that through-edge pierces
    ``b``. The fix (Shape-First / bend-minimisation philosophy: keep the main
    line straight, displace the auxiliary node) wraps ``{a, b}`` into an
    invisible sub-group oriented PERPENDICULAR to the parent, so ``a`` stays on
    the flow line and ``b`` is offset to the side. Mutates ``node`` in place.
    """
    if root is None:
        root = node
    children = node.get("children", [])
    # Depth-first so inner groups are handled before we look at this level.
    for child in children:
        _promote_branch_nodes(child, connections, root)
    children = node.get("children", [])
    direction = node.get("direction")
    if len(children) < 3 or direction not in ("horizontal", "vertical"):
        return

    # Map each direct child -> the leaf ids it contains; and each leaf -> the
    # index of the direct child that owns it (a sub-group counts as one slot).
    leaf_to_idx = {}
    for i, c in enumerate(children):
        ids = []
        _collect_leaf_ids(c, ids)
        for lid in ids:
            leaf_to_idx[lid] = i

    # Global degree + neighbour list over all connections.
    deg = {}
    nbr = {}
    for conn in connections:
        for a, b in ((conn["from"], conn["to"]), (conn["to"], conn["from"])):
            deg[a] = deg.get(a, 0) + 1
            nbr.setdefault(a, []).append(b)

    # Collect qualifying branch leaves, grouped by their anchor.
    branches_by_anchor = {}
    for i, c in enumerate(children):
        if c.get("children"):
            continue  # only bare leaves can be branch nodes
        bid = c.get("id")
        if bid is None or deg.get(bid, 0) != 1:
            continue
        aid = nbr[bid][0]
        ia = leaf_to_idx.get(aid)
        if ia is None or children[ia].get("children"):
            continue  # anchor must be a direct-child leaf of this same group
        # Is there a through-edge from the anchor that crosses b's slot?
        ib = i
        through = False
        for other in nbr.get(aid, []):
            if other == bid:
                continue
            ic = leaf_to_idx.get(other)
            if ic is not None and (ia - ib) * (ic - ib) < 0:
                through = True
                break
        if through:
            branches_by_anchor.setdefault(aid, (ia, []))[1].append((ib, c))

    if not branches_by_anchor:
        return

    perp = "vertical" if direction == "horizontal" else "horizontal"
    remove = set()
    inserts = {}  # insertion index -> new sub-group node
    for aid, (ia, brs) in branches_by_anchor.items():
        anchor = children[ia]
        slot = min([ia] + [ib for ib, _ in brs])
        # anchor first so it keeps the centred slot on the flow line; branches
        # follow in their original order.
        members = [anchor] + [c for _, c in sorted(brs)]
        inserts[slot] = {
            "id": "_branchlane_" + (aid or "x"),
            "direction": perp,
            "children": members,
            # Remember which member is the flow anchor so the layout pass can
            # keep IT (not the lane's centroid) on the main flow line, letting
            # the branch hang off to the side.
            "_branch_anchor": aid,
        }
        remove.add(ia)
        remove.update(ib for ib, _ in brs)

    rebuilt = []
    for i, c in enumerate(children):
        if i in inserts:
            rebuilt.append(inserts[i])
        if i in remove:
            continue
        rebuilt.append(c)
    node["children"] = rebuilt


def _optimize_group_order(node, connections, root=None):
    """Recursively optimize child order within groups (leaf-only AND mixed)."""
    if root is None:
        root = node
    children = node.get("children", [])
    if not children:
        return

    # Recurse depth-first so inner groups are optimized before outer ones
    for child in children:
        _optimize_group_order(child, connections, root)

    if len(children) < 2:
        return

    # Collect ALL leaf ids reachable from each child (for mixed groups)
    child_leaf_ids = {}
    for c in children:
        ids = []
        _collect_leaf_ids(c, ids)
        child_leaf_ids[c["id"]] = ids

    # All leaf ids in this group (union of children's leaves)
    all_leaf_ids = set()
    for ids in child_leaf_ids.values():
        all_leaf_ids.update(ids)

    if not all_leaf_ids:
        return

    # Collect connections relevant to any leaf in this group
    relevant = []
    for conn in connections:
        src, dst = conn["from"], conn["to"]
        if src in all_leaf_ids or dst in all_leaf_ids:
            relevant.append(conn)

    if not relevant:
        return

    # Identify internal order constraints:
    # If a connection goes from a leaf in child A to a leaf in child B,
    # child A must come before child B.
    leaf_to_child_id = {}
    for cid, leaf_ids in child_leaf_ids.items():
        for lid in leaf_ids:
            leaf_to_child_id[lid] = cid

    internal_order_constraints = []
    for conn in connections:
        src, dst = conn["from"], conn["to"]
        if src in leaf_to_child_id and dst in leaf_to_child_id:
            src_child = leaf_to_child_id[src]
            dst_child = leaf_to_child_id[dst]
            if src_child != dst_child:
                internal_order_constraints.append((src_child, dst_child))

    # For brute-force: try all permutations if ≤7 children
    if len(children) <= 7:
        best_order = _find_min_crossing_order_mixed(
            children, relevant, connections, internal_order_constraints,
            child_leaf_ids, root
        )
        if best_order is not None:
            node["children"] = best_order
            return

    # Fallback heuristic for larger groups: sort by connected peer position
    flat_order = []
    _flatten_ids_from_root(root, flat_order)
    id_position = {nid: i for i, nid in enumerate(flat_order)}
    node["children"] = sorted(children, key=lambda c: _heuristic_sort_key_mixed(c, connections, id_position, child_leaf_ids))


# Max leaves in a tile pool we will exhaustively reflow (n! candidate arrangements
# each re-routed; 6 → 720 is the practical ceiling for the local pass).
_REFLOW_MAX_LEAVES = 6


def _is_tile_column(node):
    """A tile is an anonymous, frameless, leaf-only sub-group (pure spacing,
    no semantic meaning): no groupType, no label, no branch-anchor tag, and all
    of its own children are leaves."""
    kids = node.get("children")
    if not kids:
        return False
    if node.get("groupType") or node.get("label") or node.get("_branch_anchor"):
        return False
    return all(not k.get("children") for k in kids)


def _find_tile_pools(node, out):
    """Collect groups that are pure tile pools.

    A tile pool is a group whose children are ALL anonymous frameless leaf-only
    sub-columns (tiles) of the SAME orientation, with ≥2 tiles. Such a group is
    a grid with no semantic sub-grouping, so its leaves are interchangeable
    across tiles — safe to reassign to shorten wiring.
    """
    kids = node.get("children", [])
    if kids:
        tiles = [k for k in kids if _is_tile_column(k)]
        if len(tiles) >= 2 and len(tiles) == len(kids):
            dirs = {t.get("direction") for t in tiles}
            total = sum(len(t["children"]) for t in tiles)
            if len(dirs) == 1 and 2 <= total <= _REFLOW_MAX_LEAVES:
                out.append(node)
        for k in kids:
            _find_tile_pools(k, out)


def _defect_tuple(tree, width, height):
    """Optimize child order (WITHOUT reflow), route the tree, and return the
    lexicographic quality key used to compare tile arrangements: hard defects
    first, then wire length as the soft tie-break.

    The intra-column order of each candidate is decided by the normal order
    optimizer (reflow disabled so it can't recurse), so the reflow search only
    has to explore how leaves are *partitioned* across columns — not their order
    within a column."""
    import copy
    from .render import build_layout
    from .metrics import measure_layout
    t = copy.deepcopy(tree)
    optimize_order(t, enable_reflow=False)
    nodes, groups, edges, rb, _ch, _cv = build_layout(
        t, None, None, width, height, optimize=False)
    m = measure_layout(nodes, groups, edges, rb, width, height)
    return (round(m["overflow"], 3), m["crossings"], m["pierces"],
            m["group_pierces"], m["backwards"], m["wire_norm"])


def _column_partitions(leaf_ids, col_sizes):
    """Yield every way to partition ``leaf_ids`` into ordered columns of the
    given sizes, as a tuple of frozensets (membership only — intra-column order
    is decided later by the order optimizer). Deduplicates equal-size columns so
    (A|B) and (B|A) are not both tried."""
    from itertools import combinations

    def rec(remaining, sizes):
        if not sizes:
            yield ()
            return
        size = sizes[0]
        for combo in combinations(sorted(remaining), size):
            rest = remaining - set(combo)
            for tail in rec(rest, sizes[1:]):
                yield (frozenset(combo),) + tail

    seen = set()
    for parts in rec(set(leaf_ids), col_sizes):
        # Canonicalize columns of equal size to dedupe symmetric partitions.
        key = tuple(sorted(parts, key=lambda s: sorted(s)))
        if key in seen:
            continue
        seen.add(key)
        yield parts


def _reflow_tile_pools(tree, width=1720, height=800):
    """Repartition leaves across the columns of each tile pool to shorten wiring.

    A tile pool is a group whose children are all anonymous, frameless, leaf-only
    sub-columns of one orientation — pure tiling with no semantic sub-grouping.
    Ordering alone never moves a leaf between sub-columns, so an author's column
    split (e.g. Orders+Payments in one column, Catalog+Cart in the other) is
    frozen even when regrouping would shorten wiring.

    For each pool we enumerate the ways to split its leaves across the columns
    (membership only — each candidate's intra-column order is then set by the
    normal order optimizer), re-route each with the REAL engine, and keep the
    best. A candidate is kept only if it does not worsen any hard defect
    (overflow/crossings/pierces/group_pierces/backwards) versus the author's
    arrangement; wire length breaks ties. Because hard defects rank ahead of
    wire, reflow can never trade a crossing for shorter wire — it is a pure
    quality-preserving cleanup.
    """
    pools = []
    _find_tile_pools(tree, pools)
    if not pools:
        return

    for pool in pools:
        tiles = pool["children"]
        col_sizes = [len(t["children"]) for t in tiles]
        leaves = [leaf for t in tiles for leaf in t["children"]]
        by_id = {leaf["id"]: leaf for leaf in leaves}
        leaf_ids = [leaf["id"] for leaf in leaves]

        def apply_partition(parts):
            """Fill each tile column with the members of the corresponding
            partition set (intra-column order is refined later by the optimizer,
            so any stable order is fine here)."""
            for ci, members in enumerate(parts):
                tiles[ci]["children"] = [by_id[i] for i in leaf_ids if i in members]

        # Baseline: the author's arrangement, order-optimized.
        author_parts = tuple(
            frozenset(leaf["id"] for leaf in tile["children"]) for tile in tiles)
        best_parts = author_parts
        best_key = _defect_tuple(tree, width, height)

        for parts in _column_partitions(leaf_ids, col_sizes):
            if parts == author_parts:
                continue
            apply_partition(parts)
            key = _defect_tuple(tree, width, height)
            if key < best_key:
                best_key = key
                best_parts = parts

        apply_partition(best_parts)
        # Let the order optimizer set the final intra-column order for the chosen
        # partition (reflow disabled to avoid recursing into this pass).
        optimize_order(tree, enable_reflow=False)


def _collect_leaf_ids(node, out):
    """Collect all leaf node ids reachable from a node."""
    children = node.get("children", [])
    if not children:
        if "id" in node:
            out.append(node["id"])
        return
    for child in children:
        _collect_leaf_ids(child, out)


def _find_min_crossing_order_mixed(children, relevant, all_connections, internal_order_constraints, child_leaf_ids, root):
    """Try all permutations of children (mixed groups) and return the one with fewest crossings.

    For mixed groups, each child may be a leaf OR a sub-group containing multiple leaves.
    The crossing count uses ALL leaves within each child's subtree.
    """
    from itertools import permutations

    best_key = None
    best_perm = None

    # Two position maps from the full tree:
    #  - leaf-only, for the crossing count (unchanged legacy behaviour — adding
    #    group ids here would reclassify group-endpoint edges and shuffle orders
    #    on unrelated diagrams like omnichannel).
    #  - group-inclusive, for the detour tie-break ONLY, so a many-to-one edge
    #    to a sibling GROUP box is visible when seating its single connected
    #    child (the DR diagram's API → Data tier).
    leaf_positions = _compute_global_peer_positions(children, all_connections, child_leaf_ids, root)
    group_positions = _compute_global_peer_positions(children, all_connections, child_leaf_ids, root, include_groups=True)

    for perm in permutations(children):
        perm_ids = [c["id"] for c in perm]

        # Skip permutations that violate internal order constraints
        if internal_order_constraints:
            valid = True
            for src, dst in internal_order_constraints:
                if src in perm_ids and dst in perm_ids:
                    if perm_ids.index(src) > perm_ids.index(dst):
                        valid = False
                        break
            if not valid:
                continue

        crossings = _count_crossings_for_mixed_order(perm, relevant, leaf_positions, child_leaf_ids)
        # Tie-break: among equal-crossing orders prefer the one where each child
        # that connects to an OUTSIDE peer sits at the end of the row facing that
        # peer. Otherwise a lone edge to a sibling group (e.g. an API container →
        # the Data tier) leaves author order and detours around the outer
        # sibling. This is a pure secondary key — it can never pick an order with
        # more crossings — so it can't regress a diagram that ordering already
        # solved; it only breaks ties the crossing count leaves open.
        detour = _peer_detour_cost(perm, relevant, group_positions, child_leaf_ids)
        key = (crossings, detour)
        if best_key is None or key < best_key:
            best_key = key
            best_perm = list(perm)
            if crossings == 0 and detour == 0:
                break

    return best_perm


def _peer_detour_cost(perm, relevant, global_positions, child_leaf_ids):
    """Secondary ordering key: how far each externally-connected child sits from
    the row end facing its outside peer.

    For every edge between an internal leaf and an external peer (leaf OR group
    box), the internal endpoint ideally sits at the row end nearest that peer —
    the right end if the peer is to the right (higher global position than this
    row's own centre), the left end if to the left. The cost sums the slot
    distance from that ideal end; 0 when every connected child already hugs the
    correct end. The datum is THIS row's mean peer-space position (not a global
    average), so left/right is judged relative to the row itself — the fix for
    the earlier version that flipped sides between otherwise-identical rows.
    """
    n = len(perm)
    # Slot of each internal leaf under this permutation, and per-child leaf sets.
    leaf_slot = {}
    internal = set()
    child_leaf_sets = []
    for slot, child in enumerate(perm):
        cl = set(child_leaf_ids.get(child["id"], [child["id"]]))
        child_leaf_sets.append(cl)
        for lid in cl:
            leaf_slot[lid] = slot
            internal.add(lid)

    # Only apply this tie-break when EXACTLY ONE direct child connects outside
    # the group. That is the unambiguous "seat the one connected child at the
    # peer-facing end" case (the DR diagram's API container). When several
    # children connect outside, where each should sit is a multi-way trade the
    # crossing model already handles; forcing one toward a peer end there just
    # shuffles the row and can push another edge through a frame (the
    # omnichannel services regression). Return 0 = no tie-break preference.
    connected_children = 0
    for cl in child_leaf_sets:
        if any((cn["from"] in cl and cn["to"] not in internal)
               or (cn["to"] in cl and cn["from"] not in internal)
               for cn in relevant):
            connected_children += 1
    if connected_children != 1:
        return 0

    # This row's own centre in global peer-space: mean global position of the
    # external peers it connects to (so "left/right" is relative to the row).
    peer_positions = []
    for conn in relevant:
        for a, b in ((conn["from"], conn["to"]), (conn["to"], conn["from"])):
            if a in internal and b in global_positions and b not in internal:
                peer_positions.append(global_positions[b])
    if not peer_positions:
        return 0
    datum = sum(peer_positions) / len(peer_positions)
    cost = 0
    for conn in relevant:
        for a, b in ((conn["from"], conn["to"]), (conn["to"], conn["from"])):
            if a in leaf_slot and b in global_positions and b not in internal:
                ideal = (n - 1) if global_positions[b] >= datum else 0
                cost += abs(leaf_slot[a] - ideal)
    return cost


def _compute_global_peer_positions(children, all_connections, child_leaf_ids, root, include_groups=False):
    """Compute normalized positions for external peers.

    External peers are nodes NOT contained in any of the children being permuted.
    Their position is based on DFS order of leaf nodes in the root tree,
    normalized to a [0, N] range where N is the number of internal leaf slots.

    ``include_groups`` also registers GROUP ids at the mean position of their
    member leaves. This is used ONLY by the detour tie-break (so a many-to-one
    edge to a sibling group box is visible when seating the single connected
    child). The crossing count deliberately uses the leaf-only map — adding
    groups there reclassifies group-endpoint edges and shuffles unrelated
    diagrams' orders.
    """
    # All leaves within this group
    all_internal = set()
    for ids in child_leaf_ids.values():
        all_internal.update(ids)

    # Get global DFS order of ALL leaf nodes only
    global_leaves = []
    _collect_leaf_ids(root, global_leaves)

    # Only external leaves get positions
    external_leaves = [lid for lid in global_leaves if lid not in all_internal]
    if not external_leaves:
        return {}

    # Assign sequential positions to external leaves
    pos = {lid: i for i, lid in enumerate(external_leaves)}

    if include_groups:
        # Position external GROUP ids at the mean position of their members so a
        # connection targeting a group BOX (e.g. an API container → the Data
        # tier) is visible to the detour tie-break.
        def _register(node):
            ml = []
            _collect_leaf_ids(node, ml)
            gid = node.get("id")
            if gid is not None and node.get("children"):
                ext = [pos[m] for m in ml if m in pos]
                if ext and not any(m in all_internal for m in ml):
                    pos[gid] = sum(ext) / len(ext)
            for ch in node.get("children", []):
                _register(ch)
        _register(root)
    return pos


def _count_crossings_for_mixed_order(perm, relevant, global_positions, child_leaf_ids):
    """Count edge crossings for a specific permutation of children in a mixed group.

    Two edges cross if their internal endpoints are in one order but their
    external endpoints are in the opposite order. For edges where BOTH endpoints
    are internal, they cross if one child's position inverts relative to another.

    Uses a two-layer approach:
    - Internal positions: assigned based on permutation order (sequential ints)
    - External positions: from global_positions (sequential ints, different namespace)

    For crossing detection, only edges sharing the same "side" (both internal-to-external
    or both internal-to-internal) can cross each other.
    """
    # Assign positions to all internal leaves based on the permutation order
    internal_positions = {}
    pos_counter = 0
    for child in perm:
        cid = child["id"]
        leaves = child_leaf_ids.get(cid, [])
        if not leaves:
            internal_positions[cid] = pos_counter
            pos_counter += 1
        else:
            for lid in leaves:
                internal_positions[lid] = pos_counter
                pos_counter += 1

    # Categorize edges:
    # Type A: internal→external (src is internal, dst is external)
    # Type B: external→internal (src is external, dst is internal)
    # Type C: internal→internal (both endpoints internal)
    edges_a = []  # (internal_pos, external_pos)
    edges_b = []  # (external_pos, internal_pos)
    edges_c = []  # (internal_pos_src, internal_pos_dst)

    for conn in relevant:
        src, dst = conn["from"], conn["to"]
        src_int = internal_positions.get(src)
        dst_int = internal_positions.get(dst)
        src_ext = global_positions.get(src)
        dst_ext = global_positions.get(dst)

        if src_int is not None and dst_int is not None:
            edges_c.append((src_int, dst_int))
        elif src_int is not None and dst_ext is not None:
            edges_a.append((src_int, dst_ext))
        elif src_ext is not None and dst_int is not None:
            edges_b.append((src_ext, dst_int))

    # Count crossings within each category
    crossings = 0

    # Type A crossings: two edges from internal to external cross if
    # internal order and external order are inverted
    for i in range(len(edges_a)):
        for j in range(i + 1, len(edges_a)):
            a1, b1 = edges_a[i]
            a2, b2 = edges_a[j]
            if (a1 - a2) * (b1 - b2) < 0:
                crossings += 1

    # Type B crossings: two edges from external to internal cross if
    # external order and internal order are inverted
    for i in range(len(edges_b)):
        for j in range(i + 1, len(edges_b)):
            a1, b1 = edges_b[i]
            a2, b2 = edges_b[j]
            if (a1 - a2) * (b1 - b2) < 0:
                crossings += 1

    # Type C crossings: internal-to-internal edges
    for i in range(len(edges_c)):
        for j in range(i + 1, len(edges_c)):
            a1, b1 = edges_c[i]
            a2, b2 = edges_c[j]
            if (a1 - a2) * (b1 - b2) < 0:
                crossings += 1

    return crossings


def _heuristic_sort_key_mixed(child, connections, id_position, child_leaf_ids):
    """Heuristic sort key for a child (leaf or sub-group) in a mixed group."""
    cid = child["id"]
    leaf_ids = child_leaf_ids.get(cid, [cid])

    weights = []
    for lid in leaf_ids:
        for conn in connections:
            if conn["from"] == lid and conn["to"] in id_position:
                weights.append(id_position[conn["to"]])
            if conn["to"] == lid and conn["from"] in id_position:
                weights.append(id_position[conn["from"]])
    if weights:
        return sum(weights) / len(weights)
    return id_position.get(cid, 0)


def _find_min_crossing_order(children, relevant, all_connections, internal_order_constraints=None):
    """Try all permutations and return the one with fewest crossings."""
    from itertools import permutations

    best_crossings = None
    best_perm = None

    # Determine fixed external peer positions from the tree structure
    peer_positions = _compute_peer_positions(children, all_connections)

    for perm in permutations(children):
        perm_ids = [c["id"] for c in perm]

        # Skip permutations that violate internal order constraints
        if internal_order_constraints:
            valid = True
            for src, dst in internal_order_constraints:
                if src in perm_ids and dst in perm_ids:
                    if perm_ids.index(src) > perm_ids.index(dst):
                        valid = False
                        break
            if not valid:
                continue

        crossings = _count_crossings_for_order(perm_ids, relevant, peer_positions)
        if best_crossings is None or crossings < best_crossings:
            best_crossings = crossings
            best_perm = list(perm)
            if crossings == 0:
                break

    return best_perm


def _compute_peer_positions(children, all_connections):
    """Compute fixed positions for external peers (nodes outside this group).

    External peers are assigned positions based on their relative order among
    each other — determined by their index in the sibling group they belong to.
    This position is independent of the permutation being tested.
    """
    leaf_ids = set(c["id"] for c in children)
    # Collect all external peers connected to this group
    peers = set()
    for conn in all_connections:
        if conn["from"] in leaf_ids and conn["to"] not in leaf_ids:
            peers.add(conn["to"])
        if conn["to"] in leaf_ids and conn["from"] not in leaf_ids:
            peers.add(conn["from"])

    # Group external peers by which group-internal nodes they connect to.
    # Peers connecting to the same set of internal nodes should have the same position.
    # Peers are ordered by their first appearance in connections list.
    peer_order = []
    seen = set()
    for conn in all_connections:
        for p in [conn["from"], conn["to"]]:
            if p in peers and p not in seen:
                peer_order.append(p)
                seen.add(p)

    # Assign a simple sequential position based on order of appearance
    return {p: i for i, p in enumerate(peer_order)}


def _count_crossings_for_order(ordered_ids, relevant, peer_positions):
    """Count edge crossings given a specific ordering of nodes in a group.

    Uses fixed peer_positions for external nodes and the permutation positions
    for internal nodes. Two edges cross if their endpoint orders are inverted.
    """
    pos = {nid: i for i, nid in enumerate(ordered_ids)}
    id_set = set(ordered_ids)

    edges = []
    for conn in relevant:
        src, dst = conn["from"], conn["to"]
        if src in id_set and dst in id_set:
            edges.append((pos[src], pos[dst]))
        elif src in id_set:
            ext_pos = peer_positions.get(dst, len(ordered_ids) / 2)
            edges.append((pos[src], ext_pos))
        elif dst in id_set:
            ext_pos = peer_positions.get(src, len(ordered_ids) / 2)
            edges.append((ext_pos, pos[dst]))

    crossings = 0
    for i in range(len(edges)):
        for j in range(i + 1, len(edges)):
            a1, b1 = edges[i]
            a2, b2 = edges[j]
            if (a1 - a2) * (b1 - b2) < 0:
                crossings += 1
    return crossings


def _flatten_ids_from_root(node, out):
    """Collect all node ids in DFS order from a subtree root."""
    if "id" in node:
        out.append(node["id"])
    for child in node.get("children", []):
        _flatten_ids_from_root(child, out)


def _heuristic_sort_key(child_id, connections, id_position):
    """Fallback heuristic: sort by average position of connected source nodes."""
    src_positions = []
    for conn in connections:
        if conn["to"] == child_id and conn["from"] in id_position:
            src_positions.append(id_position[conn["from"]])
    if src_positions:
        return sum(src_positions) / len(src_positions)
    weights = []
    for conn in connections:
        if conn["from"] == child_id and conn["to"] in id_position:
            weights.append(id_position[conn["to"]])
        if conn["to"] == child_id and conn["from"] in id_position:
            weights.append(id_position[conn["from"]])
    if weights:
        return sum(weights) / len(weights)
    return id_position.get(child_id, 0)


def _layout_scale(node, parent_dir="horizontal", parent_align="center", spacing_scale_h=1.0, spacing_scale_v=1.0):
    """Recursive layout engine. Calculates bindings (x, y, width, height) for each node bottom-up."""
    children = node.get("children", [])
    direction = node.get("direction", parent_dir)
    align = node.get("align", parent_align)
    is_group = len(children) > 0
    icon_size = node.get("iconSize", 60)

    # A per-node spacing scale lets the fit pass compress ONE overflowing group
    # (and its descendants) without touching sibling groups that already fit.
    # Multiplies into the inherited factor so nested overrides compose.
    spacing_scale_h *= node.get("_hscale", 1.0)
    spacing_scale_v *= node.get("_vscale", 1.0)

    def sh(v):
        return max(10, round(v * spacing_scale_h))
    def sv(v):
        return max(10, round(v * spacing_scale_v))

    if is_group:
        has_visual_group = node.get("groupType") or node.get("label")
        if has_visual_group:
            margin = node.get("margin", {"top": sv(20), "right": sh(20), "bottom": sv(20), "left": sh(20)})
            padding = node.get("padding", {"top": sv(70), "right": sh(30), "bottom": sv(30), "left": sh(30)})
        else:
            margin = node.get("margin", {"top": sv(5), "right": sh(5), "bottom": sv(5), "left": sh(5)})
            padding = node.get("padding", {"top": sv(5), "right": sh(5), "bottom": sv(5), "left": sh(5)})
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

    # Post-process 1: align corresponding leaves across sibling vertical groups
    # so that e.g. Lambda(row1) in group A has the same Y as DynamoDB(row1) in group B.
    if direction == "horizontal":
        _align_corresponding_leaves_y(ordered)
    elif direction == "vertical":
        _align_corresponding_leaves_x(ordered)

    # Post-process 2: align leaf nodes to the median leaf center of sibling groups.
    # This ensures single icons sit at the visual center of adjacent vertical groups
    # rather than at the center of the group's bounding box (which includes padding).
    if align == "center" and direction == "horizontal":
        _align_leaves_to_sibling_centers(ordered)
    elif align == "center" and direction == "vertical":
        _align_leaves_to_sibling_centers_h(ordered)

    # The alignment passes above translate LEAVES (including ones nested inside
    # child sub-groups) without touching the sub-group's own box. Re-derive each
    # child group's bbox bottom-up so its frame still wraps its (now-moved)
    # icons — otherwise the box stays at the pre-alignment position and the
    # shifted icons spill outside the frame (e.g. a Data Tier whose ElastiCache
    # dropped below the solid border).
    for c in children:
        if c.get("children"):
            _recompute_group_bbox(c)

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


def cancel_cross_axis_squash(tree, natural_sizes, cum_h, cum_v, target_w, target_h):
    """Undo the global cross-axis squash on sibling groups that already fit.

    The global fit applies ONE scale per axis. On the CROSS axis (height for a
    horizontal root, width for a vertical one) sibling groups don't sum — the
    total is just the largest. So when one tall group (e.g. a 4-team agent tower)
    forces the whole slide to squash vertically, short siblings (Entry,
    Orchestration) get dragged down with it and turn unreadable.

    The cross axis can't be made to fit by scaling alone if the tall group is
    genuinely too big (its icons, not just gaps, fill the height) — the layout
    WILL overflow, and that's acceptable; the overflow warning tells the author
    to restructure the tall group. What we refuse to accept is crushing the
    groups that DID fit. So for each top-level group whose NATURAL cross-axis
    size already fit the target, we cancel the global cross-axis squash by
    giving it a compensating `_vscale`/`_hscale` ( = 1/cum ), restoring its
    natural size; the oversized group keeps the squash. Mutates `tree`; returns
    True if any compensation was assigned (caller re-runs `_layout_scale`).
    """
    direction = tree.get("direction", "horizontal")
    src_children = tree.get("children", tree.get("nodes", []))
    changed = False
    # Only meaningful when the cross axis was actually compressed (<1).
    if direction == "horizontal" and target_h and cum_v and cum_v < 0.97:
        for src in src_children:
            if not src.get("children"):
                continue
            if natural_sizes.get(id(src), (0, 0))[1] <= target_h:
                src["_vscale"] = src.get("_vscale", 1.0) * (1.0 / cum_v)
                changed = True
    elif direction == "vertical" and target_w and cum_h and cum_h < 0.97:
        for src in src_children:
            if not src.get("children"):
                continue
            if natural_sizes.get(id(src), (0, 0))[0] <= target_w:
                src["_hscale"] = src.get("_hscale", 1.0) * (1.0 / cum_h)
                changed = True
    return changed


def measure_natural_child_sizes(tree, root):
    """Map each top-level source child -> its natural (w, h) before global fit.

    Keyed by id() of the source-child dict so it survives the deepcopy/rebuild
    cycle as long as the caller passes the SAME tree dicts. Used by
    cancel_cross_axis_squash to tell which groups fit on their own.
    """
    out = {}
    src_children = tree.get("children", tree.get("nodes", []))
    laid = root.get("children", [])
    if len(laid) != len(src_children):
        return out
    for src, node in zip(src_children, laid):
        b = node["_bindings"]
        out[id(src)] = (b[2], b[3])
    return out


def _recompute_group_bbox(node):
    """Re-derive a group's bbox from its children, bottom-up, in place.

    Used after the leaf-alignment passes move icons that live inside nested
    sub-groups: those moves don't update the sub-group's own `_bindings`, so its
    frame would otherwise stay where it was before the shift and no longer wrap
    its icons. Recurses so deep nesting is corrected from the leaves up. Reuses
    the group's stored `_padding` so the frame keeps its label band and margins.

    A grown sub-group can also start OVERLAPPING a sibling that was placed
    against its old (smaller) bounds — e.g. a Data Tier that stretched to match
    a tall sibling column now collides with the Observability group stacked
    below it. After re-deriving child boxes we re-flow this node's children
    along its own axis to restore the margin gaps, then derive this node's box.
    """
    children = node.get("children")
    if not children:
        return
    for c in children:
        if c.get("children"):
            _recompute_group_bbox(c)
    _reflow_children_along_axis(node, children)
    padding = node.get("_padding", {"top": 0, "right": 0, "bottom": 0, "left": 0})
    min_x = min(c["_bindings"][0] - c["_margin"]["left"] for c in children)
    min_y = min(c["_bindings"][1] - c["_margin"]["top"] for c in children)
    max_x = max(c["_bindings"][0] + c["_bindings"][2] + c["_margin"]["right"] for c in children)
    max_y = max(c["_bindings"][1] + c["_bindings"][3] + c["_margin"]["bottom"] for c in children)
    node["_bindings"] = [
        min_x - padding["left"],
        min_y - padding["top"],
        (max_x - min_x) + padding["left"] + padding["right"],
        (max_y - min_y) + padding["top"] + padding["bottom"],
    ]


def _reflow_children_along_axis(node, children):
    """Push apart consecutive children that overlap on the group's main axis.

    Only moves along the layout axis (vertical group → shift Y, horizontal →
    shift X) and only ever forward (never pulls a child back), so the cross-axis
    alignment the leaf passes just established is preserved. A no-op when the
    children already clear each other — the common case — so it cannot disturb
    a layout that didn't grow.
    """
    direction = node.get("direction", "horizontal")
    if len(children) < 2:
        return
    reverse = node.get("reverse", False)
    ordered = list(reversed(children)) if reverse else children
    for i in range(1, len(ordered)):
        prev = ordered[i - 1]["_bindings"]
        pm = ordered[i - 1]["_margin"]
        cur = ordered[i]["_bindings"]
        cm = ordered[i]["_margin"]
        if direction == "vertical":
            need_top = prev[1] + prev[3] + pm["bottom"] + cm["top"]
            delta = need_top - cur[1]
            if delta > 0:
                _layout_translate(ordered[i], 0, delta)
        else:
            need_left = prev[0] + prev[2] + pm["right"] + cm["left"]
            delta = need_left - cur[0]
            if delta > 0:
                _layout_translate(ordered[i], delta, 0)


def _ranges_overlap(lo1, hi1, lo2, hi2):
    """True if the 1-D intervals [lo1,hi1] and [lo2,hi2] overlap."""
    return lo1 < hi2 and lo2 < hi1


def _cluster_groups_by_axis_overlap(groups_with_leaves, axis):
    """Partition same-count groups into clusters that genuinely share a row
    (axis="x", i.e. their X spans overlap → stacked vertically) or a column
    (axis="y", i.e. their Y spans overlap → placed side by side).

    Leaf alignment only makes sense WITHIN such a cluster. Aligning the Nth
    leaf across groups that are laid out along the same axis we're aligning
    (e.g. forcing the 1st leaf of four side-by-side horizontal groups to one X)
    collapses them onto each other — the bug this guards against.
    """
    # bindings: [x, y, w, h]. axis "x" → position x(0), size w(2);
    # axis "y" → position y(1), size h(3).
    pos_idx = 0 if axis == "x" else 1
    size_idx = 2 if axis == "x" else 3
    items = []
    for group, leaves in groups_with_leaves:
        b = group["_bindings"]
        lo = b[pos_idx]
        hi = b[pos_idx] + b[size_idx]
        items.append((lo, hi, group, leaves))
    items.sort(key=lambda it: it[0])

    clusters = []
    for lo, hi, group, leaves in items:
        placed = False
        for cluster in clusters:
            # cluster shares the span if it overlaps ANY member
            if any(_ranges_overlap(lo, hi, c_lo, c_hi) for c_lo, c_hi, _, _ in cluster):
                cluster.append((lo, hi, group, leaves))
                placed = True
                break
        if not placed:
            clusters.append([(lo, hi, group, leaves)])
    return [[(g, lv) for _, _, g, lv in cluster] for cluster in clusters]


def _align_corresponding_leaves_y(ordered):
    """Align Y of corresponding leaves across vertical groups that sit SIDE BY
    SIDE (their Y spans overlap). Groups stacked vertically must NOT be aligned
    to each other — that would collapse them onto one row.

    Collects all vertical groups (at any depth) with the same leaf count, then
    aligns Nth leaves to the same Y center only within each side-by-side cluster.
    """
    vertical_groups = []
    for child in ordered:
        _collect_vertical_groups(child, vertical_groups)

    if len(vertical_groups) < 2:
        return

    by_count = {}
    for group, leaves in vertical_groups:
        n = len(leaves)
        by_count.setdefault(n, []).append((group, leaves))

    for groups_with_same_count in by_count.values():
        if len(groups_with_same_count) < 2:
            continue
        # Only align groups whose Y spans overlap (truly side by side).
        for cluster in _cluster_groups_by_axis_overlap(groups_with_same_count, "y"):
            if len(cluster) < 2:
                continue
            leaf_count = len(cluster[0][1])
            for row_idx in range(leaf_count):
                row_leaves = [leaves[row_idx] for _, leaves in cluster]
                centers = [leaf["_bindings"][1] + leaf["_bindings"][3] // 2 for leaf in row_leaves]
                target_cy = max(centers)
                for leaf in row_leaves:
                    b = leaf["_bindings"]
                    current_cy = b[1] + b[3] // 2
                    dy = target_cy - current_cy
                    if dy != 0:
                        _layout_translate(leaf, 0, dy)


def _align_corresponding_leaves_x(ordered):
    """Align X of corresponding leaves across horizontal groups that are STACKED
    VERTICALLY (their X spans overlap). Groups placed side by side must NOT be
    aligned to each other — that would collapse them onto one column.
    """
    horizontal_groups = []
    for child in ordered:
        _collect_horizontal_groups(child, horizontal_groups)

    if len(horizontal_groups) < 2:
        return

    by_count = {}
    for group, leaves in horizontal_groups:
        n = len(leaves)
        by_count.setdefault(n, []).append((group, leaves))

    for groups_with_same_count in by_count.values():
        if len(groups_with_same_count) < 2:
            continue
        # Only align groups whose X spans overlap (truly stacked vertically).
        for cluster in _cluster_groups_by_axis_overlap(groups_with_same_count, "x"):
            if len(cluster) < 2:
                continue
            leaf_count = len(cluster[0][1])
            for col_idx in range(leaf_count):
                col_leaves = [leaves[col_idx] for _, leaves in cluster]
                centers = [leaf["_bindings"][0] + leaf["_bindings"][2] // 2 for leaf in col_leaves]
                target_cx = max(centers)
                for leaf in col_leaves:
                    b = leaf["_bindings"]
                    current_cx = b[0] + b[2] // 2
                    dx = target_cx - current_cx
                    if dx != 0:
                        _layout_translate(leaf, dx, 0)


def _collect_vertical_groups(node, out):
    """Collect the OUTERMOST vertical groups with their direct leaves.

    Descends through horizontal groups (their vertical children may be genuine
    side-by-side peers) but STOPS at a vertical group: a vertical sub-group
    nested inside another vertical column is that column's internal structure
    (e.g. an {Inference, Bedrock} branch deep inside a Processing column), NOT a
    peer of the column's top-level siblings. Collecting it would let row
    alignment drag an unrelated top-level group down to match a deeply-nested
    one — the bug that bent group-to-group arrows into L shapes.
    """
    if not node.get("children"):
        return
    if node.get("direction", "horizontal") == "vertical":
        leaves = [c for c in node["children"] if not c.get("children")]
        # Only a CLEAN column (every direct child is a bare leaf) can be
        # row-aligned: row N must mean the same thing in every column. A column
        # that also holds a sub-group (e.g. Processing = three Lambdas + an
        # {Inference, Bedrock} branch) has its leaves bunched at the top while a
        # peer column spreads them over its full height — aligning row-by-row
        # then drags the mixed column's box center off the flow line. Skip it.
        if leaves and len(leaves) == len(node["children"]):
            out.append((node, leaves))
        return  # internals of a vertical column are not peers of its siblings
    for child in node.get("children", []):
        _collect_vertical_groups(child, out)


def _collect_horizontal_groups(node, out):
    """Collect the OUTERMOST horizontal groups with their direct leaves.

    Mirror of _collect_vertical_groups: descends through vertical groups but
    stops at a horizontal group, so a horizontal sub-row nested inside another
    horizontal row is not column-aligned with that row's top-level siblings.
    """
    if not node.get("children"):
        return
    if node.get("direction", "horizontal") == "horizontal":
        leaves = [c for c in node["children"] if not c.get("children")]
        # Only a CLEAN row (every direct child is a bare leaf) can be
        # column-aligned — see _collect_vertical_groups for the rationale.
        if leaves and len(leaves) == len(node["children"]):
            out.append((node, leaves))
        return  # internals of a horizontal row are not peers of its siblings
    for child in node.get("children", []):
        _collect_horizontal_groups(child, out)


def _get_direct_leaves(node):
    """Get direct leaf children (non-recursively) of a node."""
    leaves = []
    for child in node.get("children", []):
        if not child.get("children"):
            leaves.append(child)
    return leaves


def _layout_translate(node, dx, dy):
    """Translate node and all descendants by (dx, dy)."""
    b = node["_bindings"]
    node["_bindings"] = [b[0] + dx, b[1] + dy, b[2], b[3]]
    for child in node.get("children", []):
        _layout_translate(child, dx, dy)


def _find_leaf_centers_y(node):
    """Collect Y-centers of all leaf nodes in a subtree."""
    if not node.get("children"):
        b = node["_bindings"]
        return [b[1] + b[3] // 2]
    centers = []
    for child in node["children"]:
        centers.extend(_find_leaf_centers_y(child))
    return centers


def _find_leaf_centers_x(node):
    """Collect X-centers of all leaf nodes in a subtree."""
    if not node.get("children"):
        b = node["_bindings"]
        return [b[0] + b[2] // 2]
    centers = []
    for child in node["children"]:
        centers.extend(_find_leaf_centers_x(child))
    return centers


def _align_leaves_to_sibling_centers(ordered):
    """For horizontal layout: align leaf Y-center to sibling groups' direct-child leaf Y-center.

    Prioritizes leaves from groups with the same direction (horizontal),
    since those represent the main flow continuation.
    """
    # Collect cy of direct-child leaves from sibling groups with same direction
    same_dir_leaf_centers = []
    for child in ordered:
        if child.get("children") and child.get("direction", "horizontal") == "horizontal":
            for grandchild in child["children"]:
                if not grandchild.get("children"):
                    b = grandchild["_bindings"]
                    same_dir_leaf_centers.append(b[1] + b[3] // 2)

    # Fallback: for each leaf, find the adjacent group and use its leaf median
    if not same_dir_leaf_centers:
        leaf_indices = [i for i, c in enumerate(ordered) if not c.get("children")]
        group_indices = [i for i, c in enumerate(ordered) if c.get("children")]
        if leaf_indices and group_indices:
            # Use the group nearest to the first leaf
            first_leaf_idx = leaf_indices[0]
            nearest_group_idx = min(group_indices, key=lambda g: abs(g - first_leaf_idx))
            centers = _find_leaf_centers_y(ordered[nearest_group_idx])
            if centers:
                same_dir_leaf_centers.append((min(centers) + max(centers)) // 2)

    if not same_dir_leaf_centers:
        return

    target_cy = (min(same_dir_leaf_centers) + max(same_dir_leaf_centers)) // 2

    for child in ordered:
        if not child.get("children"):
            b = child["_bindings"]
            current_cy = b[1] + b[3] // 2
            dy = target_cy - current_cy
            if dy != 0:
                _layout_translate(child, 0, dy)
    _align_branch_lane_anchors(ordered, target_cy, axis="y")


def _align_leaves_to_sibling_centers_h(ordered):
    """For vertical layout: align leaf X-center to sibling groups' direct-child leaf X-center."""
    same_dir_leaf_centers = []
    for child in ordered:
        if child.get("children") and child.get("direction", "horizontal") == "vertical":
            for grandchild in child["children"]:
                if not grandchild.get("children"):
                    b = grandchild["_bindings"]
                    same_dir_leaf_centers.append(b[0] + b[2] // 2)

    if not same_dir_leaf_centers:
        for child in ordered:
            if child.get("children"):
                for grandchild in child["children"]:
                    if not grandchild.get("children"):
                        b = grandchild["_bindings"]
                        same_dir_leaf_centers.append(b[0] + b[2] // 2)

    if not same_dir_leaf_centers:
        for child in ordered:
            if child.get("children"):
                centers = _find_leaf_centers_x(child)
                if centers:
                    same_dir_leaf_centers.extend(centers)

    if not same_dir_leaf_centers:
        return

    target_cx = (min(same_dir_leaf_centers) + max(same_dir_leaf_centers)) // 2

    for child in ordered:
        if not child.get("children"):
            b = child["_bindings"]
            current_cx = b[0] + b[2] // 2
            dx = target_cx - current_cx
            if dx != 0:
                _layout_translate(child, dx, 0)
    _align_branch_lane_anchors(ordered, target_cx, axis="x")


def _align_branch_lane_anchors(ordered, target, axis):
    """Shift each promoted branch lane so its ANCHOR (not the lane centroid)
    sits on the main flow line.

    A branch lane (created by _promote_branch_nodes) stacks {anchor, branch}
    perpendicular to the flow. Block-placement centres the lane's bounding box,
    which pushes the anchor off the flow axis. We translate the whole lane so
    the anchor's center returns to ``target`` and the branch hangs off to the
    side, keeping the through-flow edge straight. axis "y" → vertical flow
    offset (horizontal parent); axis "x" → horizontal offset (vertical parent).
    """
    pos_idx = 1 if axis == "y" else 0
    size_idx = 3 if axis == "y" else 2
    for child in ordered:
        aid = child.get("_branch_anchor")
        if not aid or not child.get("children"):
            continue
        anchor = next((m for m in child["children"] if m.get("id") == aid), None)
        if anchor is None:
            continue
        ab = anchor["_bindings"]
        anchor_center = ab[pos_idx] + ab[size_idx] // 2
        delta = target - anchor_center
        if delta != 0:
            if axis == "y":
                _layout_translate(child, 0, delta)
            else:
                _layout_translate(child, delta, 0)


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
                v_sides = {"top", "bottom"}
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

        is_fanout_edge = False
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

    for (gid, role), grp_edges in bundles.items():
        if len(grp_edges) < 2:
            continue
        g = _find_group(groups, gid)
        if not g:
            continue
        gx, gy, gw, gh = g["x"], g["y"], g["width"], g["height"]

        # The "free end" of each edge is the non-group end.
        def free_pt(e):
            return e["points"][0] if role == "dst" else e["points"][-1]

        # Decide which box side faces the bundle: compare the free ends'
        # centroid to the box center.
        fxs = [free_pt(e)[0] for e in grp_edges]
        fys = [free_pt(e)[1] for e in grp_edges]
        cfx, cfy = sum(fxs) / len(fxs), sum(fys) / len(fys)
        bcx, bcy = gx + gw / 2, gy + gh / 2
        dx, dy = cfx - bcx, cfy - bcy
        if abs(dx) >= abs(dy):
            side = "left" if dx < 0 else "right"
        else:
            side = "top" if dy < 0 else "bottom"
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
            # Nested lane: outer (farther from center) edges turn earlier so the
            # bundle telescopes without crossing.
            lane_depth = (n - rank) * _GROUP_BUS_LANE_GAP if role == "dst" else (rank + 1) * _GROUP_BUS_LANE_GAP
            if vertical_ports:
                py = round(bcy + off)
                # Outer lanes turn farther from the box so the bundle telescopes.
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


_MAX_RESOLVE_ITERATIONS = 30
_BEND_CANDIDATES = [-120, -100, -80, -60, -50, -40, -30, -20, -10, 10, 20, 30, 40, 50, 60, 80, 100, 120]


def _spread_overlapping_bends(edges, conn_sides, connections):
    """Iteratively resolve edge crossings and separate close bends.

    Phase 1: Resolve all crossings by searching for optimal bend shifts.
    Phase 2: Separate bends that are too close (even if not crossing).
    """
    import copy

    # Phase 1: resolve crossings
    for _iteration in range(_MAX_RESOLVE_ITERATIONS):
        crossing = _find_first_crossing(edges)
        if crossing is None:
            break
        i, si, j, sj = crossing
        _resolve_crossing_search(edges, i, si, j, sj)

    # Phase 2: separate close parallel bends
    _separate_close_bends(edges)


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


def _count_all_crossings(edges):
    """Count crossing pairs across all edges.

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
            for si in range(len(pts_i) - 1):
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
                            new_h_y = None
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
