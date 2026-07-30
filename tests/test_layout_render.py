# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for sdpm.engine.layout.render and sdpm.engine.layout.metrics."""

from __future__ import annotations

import copy

from sdpm.engine.layout.metrics import measure, measure_layout, score
from sdpm.engine.layout.render import build_layout, render_architecture

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SIMPLE_CHAIN = {
    "direction": "horizontal",
    "children": [
        {"id": "user", "icon": "material/person", "label": "User"},
        {"id": "vpc", "groupType": "vpc", "label": "VPC", "children": [
            {"id": "alb", "icon": "aws/elastic-load-balancing", "label": "ALB"},
            {"id": "ecs", "icon": "aws/fargate", "label": "Fargate"},
        ]},
        {"id": "db", "icon": "aws/aurora", "label": "Aurora"},
    ],
    "connections": [
        {"from": "user", "to": "alb"},
        {"from": "alb", "to": "ecs"},
        {"from": "ecs", "to": "db"},
    ],
}


# ---------------------------------------------------------------------------
# render_architecture
# ---------------------------------------------------------------------------

def test_render_architecture_result_shape():
    result = render_architecture(copy.deepcopy(_SIMPLE_CHAIN),
                                 x=100, y=180, width=1720, height=800)
    assert isinstance(result["elements"], list)
    assert result["elements"], "expected placed elements"
    bbox = result["bbox"]
    assert set(bbox) >= {"x", "y", "width", "height"}
    metrics = result["metrics"]
    for key in ("crossings", "pierces", "group_pierces", "overflow", "score"):
        assert key in metrics


def test_render_architecture_simple_chain_is_clean():
    result = render_architecture(copy.deepcopy(_SIMPLE_CHAIN),
                                 x=100, y=180, width=1720, height=800)
    m = result["metrics"]
    assert m["crossings"] == 0
    assert m["pierces"] == 0
    assert m["group_pierces"] == 0
    assert m["overflow"] == 0


def test_render_architecture_element_types():
    result = render_architecture(copy.deepcopy(_SIMPLE_CHAIN),
                                 x=100, y=180, width=1720, height=800)
    types = {e["type"] for e in result["elements"]}
    assert "arch-group" in types  # the VPC frame
    assert "image" in types       # the icons


def test_render_architecture_include_metrics_false():
    result = render_architecture(copy.deepcopy(_SIMPLE_CHAIN),
                                 x=100, y=180, width=1720, height=800,
                                 include_metrics=False)
    assert "metrics" not in result
    assert result["elements"]


def test_render_architecture_does_not_mutate_input():
    tree = copy.deepcopy(_SIMPLE_CHAIN)
    snapshot = copy.deepcopy(tree)
    render_architecture(tree, x=100, y=180, width=1720, height=800)
    assert tree == snapshot


def test_render_architecture_target_area_override():
    tree = copy.deepcopy(_SIMPLE_CHAIN)
    tree["targetArea"] = {"x": 50, "y": 50, "width": 900, "height": 500}
    result = render_architecture(tree)
    bbox = result["bbox"]
    # Layout must land inside (or at) the requested target area.
    assert bbox["width"] <= 900 * 1.1
    assert bbox["height"] <= 500 * 1.1


# ---------------------------------------------------------------------------
# build_layout
# ---------------------------------------------------------------------------

def test_build_layout_scales_to_fit():
    nodes, groups, edges, rb, _h, _v = build_layout(
        copy.deepcopy(_SIMPLE_CHAIN), 0, 0, 1720, 800)
    assert nodes, "expected collected nodes"
    assert "vpc" in groups
    assert len(edges) == 3
    # Fit tolerance: the loop breaks within 3% of target.
    assert rb[2] <= 1720 * 1.1


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def test_measure_detects_crossing():
    # Two edges forming an X: (0,0)->(100,100) and (0,100)->(100,0).
    nodes = {
        "a": {"x": -10, "y": -10, "width": 10, "height": 10},
        "b": {"x": 100, "y": 100, "width": 10, "height": 10},
        "c": {"x": -10, "y": 100, "width": 10, "height": 10},
        "d": {"x": 100, "y": -10, "width": 10, "height": 10},
    }
    edges = [
        {"from": "a", "to": "b", "points": [(0, 0), (50, 0), (50, 100), (100, 100)]},
        {"from": "c", "to": "d", "points": [(0, 105), (50, 105), (50, 5), (100, 5)]},
    ]
    m = measure_layout(nodes, {}, edges, [0, 0, 110, 115])
    assert m["crossings"] >= 1


def test_measure_clean_layout_scores_zero_defects():
    m = measure(copy.deepcopy(_SIMPLE_CHAIN))
    assert m["crossings"] == 0
    assert m["pierces"] == 0
    assert m["group_pierces"] == 0


def test_score_orders_defects():
    clean = measure(copy.deepcopy(_SIMPLE_CHAIN))
    dirty = dict(clean, crossings=clean["crossings"] + 2)
    assert score(dirty) > score(clean)
