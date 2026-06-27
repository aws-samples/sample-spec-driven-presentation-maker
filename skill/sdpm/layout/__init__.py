# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Layout engine: compute coordinates from logical structure JSON."""


def optimize_order(tree):
    """Pre-process: reorder children in leaf-only groups to minimize edge crossings.

    Uses brute-force permutation search for small groups (≤7 leaves) and
    heuristic sorting for larger ones. Counts actual crossing pairs to find
    the optimal order.

    Mutates tree in-place. Call before _layout_scale.
    """
    connections = tree.get("connections", [])
    if not connections:
        return
    _optimize_group_order(tree, connections)


def _optimize_group_order(node, connections):
    """Recursively optimize child order within leaf-only groups."""
    children = node.get("children", [])
    if not children:
        return

    for child in children:
        _optimize_group_order(child, connections)

    leaf_children = [c for c in children if not c.get("children")]
    if len(leaf_children) < 2 or len(leaf_children) != len(children):
        return

    leaf_ids = [c["id"] for c in children]

    # Collect connections relevant to this group's leaves
    relevant = []
    for conn in connections:
        src, dst = conn["from"], conn["to"]
        src_in = src in leaf_ids
        dst_in = dst in leaf_ids
        if src_in or dst_in:
            relevant.append(conn)

    if not relevant:
        return

    # For brute-force: try all permutations if ≤7 leaves
    if len(children) <= 7:
        best_order = _find_min_crossing_order(children, relevant, connections)
        if best_order is not None:
            node["children"] = best_order
            return

    # Fallback heuristic for larger groups: sort by connected peer position
    flat_order = []
    _flatten_ids_from_root(node, flat_order)
    id_position = {nid: i for i, nid in enumerate(flat_order)}
    node["children"] = sorted(children, key=lambda c: _heuristic_sort_key(c["id"], connections, id_position))


def _find_min_crossing_order(children, relevant, all_connections):
    """Try all permutations and return the one with fewest crossings."""
    from itertools import permutations

    best_crossings = None
    best_perm = None

    # Determine fixed external peer positions from the tree structure
    peer_positions = _compute_peer_positions(children, all_connections)

    for perm in permutations(children):
        perm_ids = [c["id"] for c in perm]
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


def _align_corresponding_leaves_y(ordered):
    """Align Y of corresponding leaves across all vertical groups in the subtree.

    Collects all vertical groups (at any depth) with the same leaf count and
    aligns their Nth leaves to the same Y center.
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
        leaf_count = len(groups_with_same_count[0][1])
        for row_idx in range(leaf_count):
            row_leaves = [leaves[row_idx] for _, leaves in groups_with_same_count]
            centers = [leaf["_bindings"][1] + leaf["_bindings"][3] // 2 for leaf in row_leaves]
            target_cy = max(centers)
            for leaf in row_leaves:
                b = leaf["_bindings"]
                current_cy = b[1] + b[3] // 2
                dy = target_cy - current_cy
                if dy != 0:
                    _layout_translate(leaf, 0, dy)


def _align_corresponding_leaves_x(ordered):
    """Align X of corresponding leaves across all horizontal groups in the subtree."""
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
        leaf_count = len(groups_with_same_count[0][1])
        for col_idx in range(leaf_count):
            col_leaves = [leaves[col_idx] for _, leaves in groups_with_same_count]
            centers = [leaf["_bindings"][0] + leaf["_bindings"][2] // 2 for leaf in col_leaves]
            target_cx = max(centers)
            for leaf in col_leaves:
                b = leaf["_bindings"]
                current_cx = b[0] + b[2] // 2
                dx = target_cx - current_cx
                if dx != 0:
                    _layout_translate(leaf, dx, 0)


def _collect_vertical_groups(node, out):
    """Recursively collect vertical groups with their direct leaves."""
    if not node.get("children"):
        return
    if node.get("direction", "horizontal") == "vertical":
        leaves = [c for c in node["children"] if not c.get("children")]
        if leaves:
            out.append((node, leaves))
    for child in node.get("children", []):
        _collect_vertical_groups(child, out)


def _collect_horizontal_groups(node, out):
    """Recursively collect horizontal groups with their direct leaves."""
    if not node.get("children"):
        return
    if node.get("direction", "horizontal") == "horizontal":
        leaves = [c for c in node["children"] if not c.get("children")]
        if leaves:
            out.append((node, leaves))
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

    # Fallback: direct-child leaves from any group
    if not same_dir_leaf_centers:
        for child in ordered:
            if child.get("children"):
                for grandchild in child["children"]:
                    if not grandchild.get("children"):
                        b = grandchild["_bindings"]
                        same_dir_leaf_centers.append(b[1] + b[3] // 2)

    # Final fallback: all leaf centers
    if not same_dir_leaf_centers:
        for child in ordered:
            if child.get("children"):
                centers = _find_leaf_centers_y(child)
                if centers:
                    same_dir_leaf_centers.extend(centers)

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

    # T8: Align bend positions for fan-out/fan-in only when "fan": "merge" is set
    _align_fan_bends(edges, conn_sides, connections)

    # T9: Spread overlapping elbow bends from the same source
    _spread_overlapping_bends(edges, conn_sides, connections)

    return edges


# Max spread between dst (or src) centers to allow grouping
_FAN_SPREAD_LIMIT = 600


def _align_fan_bends(edges, conn_sides, connections):
    """Align bend positions and merge ports for fan-out and fan-in groups.

    Only activates when connections have "fan": "merge" set.
    Default behavior keeps ports separate (split).
    """
    # Fan-out: same src + same src_side, only if all connections in the group have fan=merge
    src_groups = {}
    for i, (src, dst, src_side, dst_side) in enumerate(conn_sides):
        if src is None or len(edges[i]["points"]) <= 2:
            continue
        if connections[i].get("fan") != "merge":
            continue
        k = (connections[i]["from"], src_side)
        src_groups.setdefault(k, []).append(i)

    for indices in src_groups.values():
        if len(indices) < 2:
            continue
        _rewrite_fan(edges, conn_sides, indices, mode="fan_out")

    # Fan-in: same dst + same dst_side, only if all connections in the group have fan=merge
    dst_groups = {}
    for i, (src, dst, src_side, dst_side) in enumerate(conn_sides):
        if src is None or len(edges[i]["points"]) <= 2:
            continue
        if connections[i].get("fan") != "merge":
            continue
        k = (connections[i]["to"], dst_side)
        dst_groups.setdefault(k, []).append(i)

    for indices in dst_groups.values():
        if len(indices) < 2:
            continue
        _rewrite_fan(edges, conn_sides, indices, mode="fan_in")


_BEND_OVERLAP_THRESHOLD = 15
_BEND_SPREAD_STEP = 20


def _spread_overlapping_bends(edges, conn_sides, connections):
    """Detect and spread elbow bends that overlap from the same source node.

    When multiple elbows from the same source have bend segments at nearly
    the same X (or Y), space them apart to avoid visual overlap.
    """
    # Group edges by source node
    src_edge_groups = {}
    for i, (src, dst, src_side, dst_side) in enumerate(conn_sides):
        if src is None:
            continue
        pts = edges[i]["points"]
        if len(pts) < 4:
            continue
        k = connections[i]["from"]
        src_edge_groups.setdefault(k, []).append(i)

    for indices in src_edge_groups.values():
        if len(indices) < 2:
            continue
        # Check if bends are on vertical segments (H-V-H pattern)
        # For H-V-H: bend is at pts[1][0] (= pts[2][0])
        bend_xs = []
        for idx in indices:
            pts = edges[idx]["points"]
            if len(pts) >= 4:
                # H-V-H: first segment is horizontal, bend is vertical
                if abs(pts[0][1] - pts[1][1]) < 5:
                    bend_xs.append((idx, pts[1][0]))
        if len(bend_xs) < 2:
            continue

        # Sort by bend X position
        bend_xs.sort(key=lambda t: t[1])

        # Check for overlaps and spread
        for j in range(1, len(bend_xs)):
            prev_idx, prev_x = bend_xs[j - 1]
            curr_idx, curr_x = bend_xs[j]
            if abs(curr_x - prev_x) < _BEND_OVERLAP_THRESHOLD:
                # Spread apart
                new_prev_x = prev_x - _BEND_SPREAD_STEP // 2
                new_curr_x = curr_x + _BEND_SPREAD_STEP // 2
                _update_bend_x(edges[prev_idx]["points"], prev_x, new_prev_x)
                _update_bend_x(edges[curr_idx]["points"], curr_x, new_curr_x)
                bend_xs[j - 1] = (prev_idx, new_prev_x)
                bend_xs[j] = (curr_idx, new_curr_x)

    # Same for destination node (fan-in)
    dst_edge_groups = {}
    for i, (src, dst, src_side, dst_side) in enumerate(conn_sides):
        if src is None:
            continue
        pts = edges[i]["points"]
        if len(pts) < 4:
            continue
        k = connections[i]["to"]
        dst_edge_groups.setdefault(k, []).append(i)

    for indices in dst_edge_groups.values():
        if len(indices) < 2:
            continue
        bend_xs = []
        for idx in indices:
            pts = edges[idx]["points"]
            if len(pts) >= 4:
                if abs(pts[-1][1] - pts[-2][1]) < 5:
                    bend_xs.append((idx, pts[-2][0]))
        if len(bend_xs) < 2:
            continue
        bend_xs.sort(key=lambda t: t[1])
        for j in range(1, len(bend_xs)):
            prev_idx, prev_x = bend_xs[j - 1]
            curr_idx, curr_x = bend_xs[j]
            if abs(curr_x - prev_x) < _BEND_OVERLAP_THRESHOLD:
                new_prev_x = prev_x - _BEND_SPREAD_STEP // 2
                new_curr_x = curr_x + _BEND_SPREAD_STEP // 2
                _update_bend_x(edges[prev_idx]["points"], prev_x, new_prev_x)
                _update_bend_x(edges[curr_idx]["points"], curr_x, new_curr_x)
                bend_xs[j - 1] = (prev_idx, new_prev_x)
                bend_xs[j] = (curr_idx, new_curr_x)


def _update_bend_x(points, old_x, new_x):
    """Update bend X coordinate in a 4-point elbow path."""
    for pt in points:
        if abs(pt[0] - old_x) < 3:
            pt[0] = new_x


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


SNAP_THRESHOLD = 5
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
