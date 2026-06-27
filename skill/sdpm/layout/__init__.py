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

    # Identify internal connections (both src and dst within this group)
    # Their src must appear before dst in any valid permutation.
    internal_order_constraints = []
    for conn in connections:
        src, dst = conn["from"], conn["to"]
        if src in leaf_ids and dst in leaf_ids:
            internal_order_constraints.append((src, dst))

    # For brute-force: try all permutations if ≤7 leaves
    if len(children) <= 7:
        best_order = _find_min_crossing_order(children, relevant, connections, internal_order_constraints)
        if best_order is not None:
            node["children"] = best_order
            return

    # Fallback heuristic for larger groups: sort by connected peer position
    flat_order = []
    _flatten_ids_from_root(node, flat_order)
    id_position = {nid: i for i, nid in enumerate(flat_order)}
    node["children"] = sorted(children, key=lambda c: _heuristic_sort_key(c["id"], connections, id_position))


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
            if dx > dy * 0.5:
                reverse_set.add(i)

    # Track decided sides per source node to ensure consistency for fan-out
    decided_src_side = {}

    conn_sides = []
    for i, conn in enumerate(connections):
        src = _find_node(nodes, conn["from"])
        dst = _find_node(nodes, conn["to"])
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
        src_id = conn["from"]
        if not explicit_src and not explicit_dst:
            if src_id in decided_src_side:
                decided = decided_src_side[src_id]
                # Only apply if decided side is compatible with natural direction
                # (same axis: both horizontal or both vertical)
                h_sides = {"left", "right"}
                v_sides = {"top", "bottom"}
                natural_axis = "h" if src_side in h_sides else "v"
                decided_axis = "h" if decided in h_sides else "v"
                if natural_axis == decided_axis:
                    src_side = decided
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

    edges = []
    for i, conn in enumerate(connections):
        src, dst, src_side, dst_side = conn_sides[i]
        if src is None:
            edges.append({"from": conn["from"], "to": conn["to"], "label": conn.get("label", ""), "points": []})
            continue

        if i in reverse_set:
            src_node = _find_node(nodes, conn["from"])
            dst_node = _find_node(nodes, conn["to"])
            label_h_src = 30 if src_node.get("label") else 0
            label_h_dst = 30 if dst_node.get("label") else 0
            sp = _port_point(src_node, "bottom", 0, 1, label_h_src)
            tp = _port_point(dst_node, "bottom", 0, 1, label_h_dst)
            points = _detour_path(sp, tp, "bottom", "bottom", global_bottom)
        else:
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
        return h_x_min < v_x < h_x_max and v_y_min < h_y < v_y_max
    if a_vert and b_horiz:
        v_x = ax1
        v_y_min, v_y_max = min(ay1, ay2), max(ay1, ay2)
        h_y = by1
        h_x_min, h_x_max = min(bx1, bx2), max(bx1, bx2)
        return h_x_min < v_x < h_x_max and v_y_min < h_y < v_y_max
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
        if len(pts_i) < 2:
            continue
        for j in range(i + 1, len(edges)):
            pts_j = edges[j]["points"]
            if len(pts_j) < 2:
                continue
            for si in range(len(pts_i) - 1):
                for sj in range(len(pts_j) - 1):
                    if _segments_intersect(pts_i[si], pts_i[si + 1], pts_j[sj], pts_j[sj + 1]):
                        return (i, si, j, sj)
    return None


def _count_all_crossings(edges):
    """Count total crossing pairs across all edges."""
    count = 0
    for i in range(len(edges)):
        pts_i = edges[i]["points"]
        if len(pts_i) < 2:
            continue
        for j in range(i + 1, len(edges)):
            pts_j = edges[j]["points"]
            if len(pts_j) < 2:
                continue
            for si in range(len(pts_i) - 1):
                for sj in range(len(pts_j) - 1):
                    if _segments_intersect(pts_i[si], pts_i[si + 1], pts_j[sj], pts_j[sj + 1]):
                        count += 1
    return count


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
