# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Placement pipeline: scale, translate, align and collect the node/group
geometry computed from the logical structure tree.
"""

import math

# ---------------------------------------------------------------------------
# pt-based calibration constants (true values derived from template metrics)
# ---------------------------------------------------------------------------
_LINE_PT = 13.2       # line height = 1.2 × 11pt font
_PAD_PT = 20.0        # total vertical padding (top + bottom) for box
_HALFWIDTH_PT = 5.0   # average half-width glyph width in pt (≈ 0.455em at 11pt)
_FULLWIDTH_PT = 11.0  # full-width CJK glyph = 1em at 11pt

# Icon label constants (in pt, derived from current px values as true values)
_LABEL_CHAR_PT = 4.0        # 8px × 0.5 = 4pt per half-width char
_LABEL_FULLWIDTH_PT = 8.8   # full-width char ≈ 2.2× half-width in label font (8pt)
_LABEL_HEIGHT_PT = 17.5     # first line height: 35px × 0.5 = 17.5pt
_LABEL_EXTRA_LINE_PT = 9.0  # additional line height: 18px × 0.5 = 9pt


def _text_width_pt(s: str) -> float:
    """Estimate text width in pt for an 11pt font.

    CJK detection: ord > 0x2E80 (covers CJK Unified Ideographs and related).
    """
    return sum(_FULLWIDTH_PT if ord(c) > 0x2E80 else _HALFWIDTH_PT for c in s)


def _label_width_pt(s: str) -> float:
    """Estimate label text width in pt (label uses ~8pt effective size)."""
    return sum(_LABEL_FULLWIDTH_PT if ord(c) > 0x2E80 else _LABEL_CHAR_PT for c in s)


def _layout_scale(node, parent_dir="horizontal", parent_align="center", spacing_scale_h=1.0, spacing_scale_v=1.0, pt_per_px=0.5):
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
                # pt-based line estimation: each line wraps when text width
                # exceeds the box width converted to pt.
                available_pt = bw * pt_per_px
                lines = 0
                for field in [box.get("sublabel"), box.get("title", node.get("id", "")), box.get("description")]:
                    if field:
                        for paragraph in str(field).split("\n"):
                            width_pt = _text_width_pt(paragraph)
                            lines += max(1, math.ceil(width_pt / available_pt))
                bh = math.ceil(lines * _LINE_PT / pt_per_px) + round(_PAD_PT / pt_per_px)
            margin = node.get("margin", {"top": sv(20), "right": sh(20), "bottom": sv(20), "left": sh(20)})
            padding = {"top": 0, "right": 0, "bottom": 0, "left": 0}
            node["_bindings"] = [0, 0, bw, bh]
            node["_margin"] = margin
            node["_padding"] = padding
            return
        # Icon label sizing (pt-based with CJK support)
        raw_label = node.get("label", "")
        label_lines = raw_label.replace("\\n", "\n").split("\n")
        label_w = max((round(_label_width_pt(line) / pt_per_px) for line in label_lines), default=0)
        label_h = round(_LABEL_HEIGHT_PT / pt_per_px * spacing_scale_v) + (len(label_lines) - 1) * round(_LABEL_EXTRA_LINE_PT / pt_per_px * spacing_scale_v)
        # Ensure minimum via sv() for consistency with spacing scale
        label_h = max(label_h, sv(35) + (len(label_lines) - 1) * sv(18)) if spacing_scale_v != 1.0 else label_h
        half_label_overhang = max(0, (label_w - icon_size) // 2)
        margin = node.get("margin", {"top": sv(20), "right": max(sh(20), half_label_overhang + 5), "bottom": label_h + sv(10), "left": max(sh(20), half_label_overhang + 5)})
        padding = {"top": 0, "right": 0, "bottom": 0, "left": 0}
        node["_bindings"] = [0, 0, icon_size, icon_size]
        node["_margin"] = margin
        node["_padding"] = padding
        return

    for child in children:
        _layout_scale(child, direction, align, spacing_scale_h, spacing_scale_v, pt_per_px)

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
