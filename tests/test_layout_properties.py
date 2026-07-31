# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Property-based tests for the layout engine.

Generates random logical-structure trees (seeded, deterministic) and checks
invariants that must hold for ANY input — the pipeline never crashes, geometry
is well-formed, metrics are internally consistent, and core geometric
predicates are symmetric. No new test dependency: a seeded random.Random
stands in for hypothesis.
"""

from __future__ import annotations

import random

from sdpm.engine.layout.geometry import _count_all_crossings, _segments_cross
from sdpm.engine.layout.metrics import measure, score
from sdpm.engine.layout.render import build_layout, render_architecture

_ICONS = ["aws/lambda", "aws/s3", "aws/dynamodb", "aws/api-gateway",
          "aws/sqs", "aws/fargate", "material/person", "aws/cloudfront"]
_GROUP_TYPES = ["vpc", "generic", "region"]

_N_CASES = 12


def _random_tree(rng: random.Random) -> dict:
    """Build a random 1-2 level tree of 3-10 leaves with random connections."""
    n_leaves = rng.randint(3, 10)
    leaf_ids = [f"n{i}" for i in range(n_leaves)]

    children: list[dict] = []
    pool = list(leaf_ids)
    rng.shuffle(pool)
    # Chance to wrap a run of leaves into a (possibly nested) group.
    while pool:
        take = rng.randint(1, min(4, len(pool)))
        members, pool = pool[:take], pool[take:]
        leaves = [{"id": m, "icon": rng.choice(_ICONS), "label": m.upper()}
                  for m in members]
        if take > 1 and rng.random() < 0.6:
            children.append({
                "id": f"g{len(children)}",
                "groupType": rng.choice(_GROUP_TYPES),
                "label": f"Group {len(children)}",
                "direction": rng.choice(["horizontal", "vertical"]),
                "children": leaves,
            })
        else:
            children.extend(leaves)
    rng.shuffle(children)

    connections = []
    n_conns = rng.randint(1, min(8, n_leaves * 2))
    for _ in range(n_conns):
        a, b = rng.sample(leaf_ids, 2)
        conn = {"from": a, "to": b}
        if rng.random() < 0.2:
            conn["label"] = "conn"
        if rng.random() < 0.15:
            conn["fan"] = "merge"
        connections.append(conn)

    return {
        "direction": rng.choice(["horizontal", "vertical"]),
        "children": children,
        "connections": connections,
    }


def _cases():
    for seed in range(_N_CASES):
        yield seed, _random_tree(random.Random(seed))


# The pipeline is the expensive part (~0.1-0.5s per tree), and several tests
# assert different invariants over the same layouts — build each case once.
_LAYOUT_CACHE: dict = {}
_RENDER_CACHE: dict = {}


def _built(seed, tree):
    if seed not in _LAYOUT_CACHE:
        _LAYOUT_CACHE[seed] = build_layout(tree, 0, 0, 1720, 800)
    return _LAYOUT_CACHE[seed]


def _rendered(seed, tree):
    if seed not in _RENDER_CACHE:
        _RENDER_CACHE[seed] = render_architecture(
            tree, x=0, y=0, width=1720, height=800)
    return _RENDER_CACHE[seed]


# ---------------------------------------------------------------------------
# Pipeline invariants
# ---------------------------------------------------------------------------

def test_render_never_crashes_and_shape_holds():
    for seed, tree in _cases():
        result = _rendered(seed, tree)
        assert result["elements"], f"seed={seed}: no elements"
        bbox = result["bbox"]
        assert bbox["width"] > 0 and bbox["height"] > 0, f"seed={seed}"
        m = result["metrics"]
        for key in ("crossings", "pierces", "group_pierces", "overflow"):
            assert m[key] >= 0, f"seed={seed}: negative {key}"


def test_all_leaves_are_placed():
    for seed, tree in _cases():
        nodes, groups, edges, rb, _h, _v = _built(seed, tree)
        leaf_ids = {c["id"] for c in tree["children"] if "icon" in c}
        for g in tree["children"]:
            if "children" in g:
                leaf_ids |= {c["id"] for c in g["children"]}
        # Nodes inside a group are collected under a dot-qualified id
        # ("g0.n7"), so match on the unqualified tail.
        placed_tails = {nid.rsplit(".", 1)[-1] for nid in nodes}
        assert leaf_ids <= placed_tails, (
            f"seed={seed}: missing {leaf_ids - placed_tails}")
        # Every placed node has finite, positive dimensions.
        for nid, n in nodes.items():
            assert n["width"] > 0 and n["height"] > 0, f"seed={seed}: {nid}"


def test_every_connection_gets_an_edge():
    for seed, tree in _cases():
        _nodes, _groups, edges, _rb, _h, _v = _built(seed, tree)
        assert len(edges) == len(tree["connections"]), f"seed={seed}"
        for e in edges:
            pts = e.get("points", [])
            assert len(pts) >= 2, f"seed={seed}: degenerate edge {e}"


def test_measure_matches_render_metrics():
    """measure() and render_architecture() must agree — they share the
    pipeline, so a disagreement means the two entry points drifted (or the
    pipeline is non-deterministic). Runs both entry points independently,
    so keep the seed count small."""
    for seed, tree in list(_cases())[:5]:
        rendered = render_architecture(tree, x=0, y=0, width=1720, height=800)
        measured = measure(tree)
        for key in ("crossings", "pierces", "group_pierces"):
            assert rendered["metrics"][key] == measured[key], (
                f"seed={seed}: {key} render={rendered['metrics'][key]} "
                f"measure={measured[key]}")


def test_score_is_monotone_in_each_defect():
    base = measure(_random_tree(random.Random(0)))
    for key in ("crossings", "pierces", "group_pierces", "backwards"):
        worse = dict(base, **{key: base[key] + 1})
        assert score(worse) > score(base), f"score not monotone in {key}"


# ---------------------------------------------------------------------------
# Geometric predicate properties
# ---------------------------------------------------------------------------

def _random_segment(rng):
    p1 = (rng.randint(0, 500), rng.randint(0, 500))
    p2 = (rng.randint(0, 500), rng.randint(0, 500))
    return p1, p2


def test_segments_cross_is_symmetric():
    rng = random.Random(42)
    for _ in range(300):
        a1, a2 = _random_segment(rng)
        b1, b2 = _random_segment(rng)
        assert _segments_cross(a1, a2, b1, b2) == _segments_cross(b1, b2, a1, a2)
        # Endpoint order within a segment must not matter either.
        assert _segments_cross(a1, a2, b1, b2) == _segments_cross(a2, a1, b1, b2)


def test_segment_never_crosses_itself():
    rng = random.Random(43)
    for _ in range(100):
        a1, a2 = _random_segment(rng)
        assert not _segments_cross(a1, a2, a1, a2)


def test_count_all_crossings_is_order_invariant():
    rng = random.Random(44)
    for seed, tree in list(_cases())[:10]:
        _n, _g, edges, _rb, _h, _v = _built(seed, tree)
        if len(edges) < 2:
            continue
        baseline = _count_all_crossings(edges)
        shuffled = list(edges)
        rng.shuffle(shuffled)
        assert _count_all_crossings(shuffled) == baseline, f"seed={seed}"
