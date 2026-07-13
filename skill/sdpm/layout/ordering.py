# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Node-order optimization: crossing-minimizing child order within groups,
branch-node promotion, and tile-pool reflow.
"""



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
