# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for pt/px calibration in placement.py.

Validates:
(a) 16:9 default box height pin (new pt-based values)
(b) CJK description produces more lines than ASCII at same char count
(c) pt_per_px=0.375 (4:3) produces taller boxes than 16:9 (0.5)
(d) pt_per_px omitted: build_layout existing calls work unchanged
"""

from __future__ import annotations

import copy
import math

from sdpm.engine.layout.placement import (
    _FULLWIDTH_PT,
    _HALFWIDTH_PT,
    _LINE_PT,
    _PAD_PT,
    _layout_scale,
    _text_width_pt,
)
from sdpm.engine.layout.render import build_layout, render_architecture


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_box_node(title: str = "Service", description: str = "", width: int = 240):
    """Create a minimal box node for placement testing."""
    box = {"title": title, "width": width}
    if description:
        box["description"] = description
    return {"id": "test_node", "box": box}


def _get_box_height(node: dict, pt_per_px: float = 0.5) -> int:
    """Run _layout_scale on a box node and return computed height."""
    n = copy.deepcopy(node)
    # Wrap in a minimal root so _layout_scale treats it as a leaf
    _layout_scale(n, pt_per_px=pt_per_px)
    return n["_bindings"][3]


# ---------------------------------------------------------------------------
# (a) 16:9 default box height pin (pt-based values)
# ---------------------------------------------------------------------------

def test_box_height_single_short_title():
    """A short title (single line) should produce a predictable height."""
    node = _make_box_node(title="Lambda", description="")
    h = _get_box_height(node, pt_per_px=0.5)
    # 1 line: ceil(1 * 13.2 / 0.5) + round(20.0 / 0.5) = ceil(26.4) + 40 = 27 + 40 = 67
    expected = math.ceil(1 * _LINE_PT / 0.5) + round(_PAD_PT / 0.5)
    assert h == expected, f"expected {expected}, got {h}"


def test_box_height_title_and_description():
    """Title + description: each computed separately (separate lines)."""
    node = _make_box_node(title="API Gateway", description="REST endpoint for users")
    h = _get_box_height(node, pt_per_px=0.5)
    # Title: "API Gateway" = 11 chars × 5pt = 55pt width. bw=240, available=120pt. 1 line.
    # Desc: "REST endpoint for users" = 23 chars × 5pt = 115pt. available=120pt. 1 line.
    # Total: 2 lines → ceil(2 * 13.2 / 0.5) + round(20 / 0.5) = ceil(52.8) + 40 = 53 + 40 = 93
    expected = math.ceil(2 * _LINE_PT / 0.5) + round(_PAD_PT / 0.5)
    assert h == expected, f"expected {expected}, got {h}"


def test_box_height_wrapping_description():
    """A long description wraps to multiple lines."""
    # 30 chars × 5pt = 150pt. available at bw=240: 120pt. ceil(150/120) = 2 lines for desc.
    desc = "A" * 30
    node = _make_box_node(title="S3", description=desc)
    h = _get_box_height(node, pt_per_px=0.5)
    # Title "S3": 2 chars × 5pt = 10pt < 120pt → 1 line
    # Desc: 30 chars × 5pt = 150pt. ceil(150/120) = 2 lines
    # Total: 3 lines
    expected = math.ceil(3 * _LINE_PT / 0.5) + round(_PAD_PT / 0.5)
    assert h == expected, f"expected {expected}, got {h}"


# ---------------------------------------------------------------------------
# (b) CJK description produces more lines
# ---------------------------------------------------------------------------

def test_cjk_description_more_lines():
    """CJK characters (11pt each) wrap much sooner than ASCII (5pt each)."""
    ascii_desc = "A" * 20  # 20 × 5pt = 100pt; fits in 120pt (1 line)
    cjk_desc = "あ" * 20  # 20 × 11pt = 220pt; ceil(220/120) = 2 lines

    h_ascii = _get_box_height(_make_box_node(title="X", description=ascii_desc))
    h_cjk = _get_box_height(_make_box_node(title="X", description=cjk_desc))

    # ASCII: title(1) + desc(1) = 2 lines
    # CJK: title(1) + desc(2) = 3 lines
    assert h_cjk > h_ascii, f"CJK height {h_cjk} should exceed ASCII height {h_ascii}"


def test_cjk_text_width_pt():
    """_text_width_pt correctly distinguishes CJK from ASCII."""
    ascii_str = "hello"  # 5 × 5pt = 25pt
    cjk_str = "日本語"  # 3 × 11pt = 33pt

    assert _text_width_pt(ascii_str) == 5 * _HALFWIDTH_PT
    assert _text_width_pt(cjk_str) == 3 * _FULLWIDTH_PT


def test_mixed_cjk_ascii_width():
    """Mixed CJK/ASCII string correctly sums both widths."""
    mixed = "Hello世界"  # 5 × 5pt + 2 × 11pt = 25 + 22 = 47pt
    assert _text_width_pt(mixed) == 5 * _HALFWIDTH_PT + 2 * _FULLWIDTH_PT


# ---------------------------------------------------------------------------
# (c) pt_per_px=0.375 (4:3) produces taller boxes than 16:9 (0.5)
# ---------------------------------------------------------------------------

def test_43_taller_than_169():
    """4:3 template (pt_per_px=0.375) should produce taller boxes than 16:9 (0.5)."""
    node = _make_box_node(title="Service", description="Handles requests")
    h_169 = _get_box_height(node, pt_per_px=0.5)
    h_43 = _get_box_height(node, pt_per_px=0.375)
    assert h_43 > h_169, f"4:3 height {h_43} should exceed 16:9 height {h_169}"


def test_43_height_formula():
    """Verify the exact formula for 4:3."""
    node = _make_box_node(title="Lambda", description="")
    h = _get_box_height(node, pt_per_px=0.375)
    # 1 line: ceil(1 * 13.2 / 0.375) + round(20.0 / 0.375) = ceil(35.2) + round(53.33) = 36 + 53 = 89
    expected = math.ceil(1 * _LINE_PT / 0.375) + round(_PAD_PT / 0.375)
    assert h == expected, f"expected {expected}, got {h}"


def test_43_wrapping_differs():
    """Same text may wrap more in 4:3 since available pt per px is smaller."""
    # 22 chars × 5pt = 110pt.
    # At bw=240: 16:9 available = 240×0.5 = 120pt → 1 line.
    #            4:3 available = 240×0.375 = 90pt → ceil(110/90) = 2 lines.
    desc = "A" * 22
    node = _make_box_node(title="X", description=desc)
    h_169 = _get_box_height(node, pt_per_px=0.5)
    h_43 = _get_box_height(node, pt_per_px=0.375)
    # 16:9: title(1) + desc(1) = 2 lines
    # 4:3: title(1) + desc(2) = 3 lines (more wrapping AND bigger px per line)
    assert h_43 > h_169


# ---------------------------------------------------------------------------
# (d) pt_per_px omission: build_layout existing calls work unchanged
# ---------------------------------------------------------------------------

_SIMPLE_TREE = {
    "direction": "horizontal",
    "children": [
        {"id": "a", "icon": "aws/lambda", "label": "Lambda"},
        {"id": "b", "icon": "aws/s3", "label": "S3"},
    ],
    "connections": [{"from": "a", "to": "b"}],
}


def test_build_layout_no_pt_per_px_arg():
    """build_layout works without explicit pt_per_px (uses default 0.5)."""
    nodes, groups, edges, rb, cum_h, cum_v = build_layout(
        copy.deepcopy(_SIMPLE_TREE), x=100, y=180, width=1720, height=800)
    assert "a" in nodes or any("a" in k for k in nodes)
    assert rb[2] > 0 and rb[3] > 0


def test_render_architecture_no_pt_per_px_arg():
    """render_architecture works without explicit pt_per_px (uses default 0.5)."""
    result = render_architecture(copy.deepcopy(_SIMPLE_TREE),
                                 x=100, y=180, width=1720, height=800)
    assert "elements" in result
    assert "bbox" in result
    assert result["bbox"]["width"] > 0


def test_build_layout_explicit_pt_per_px():
    """build_layout accepts explicit pt_per_px keyword."""
    nodes, groups, edges, rb, cum_h, cum_v = build_layout(
        copy.deepcopy(_SIMPLE_TREE), x=100, y=180, width=1720, height=800,
        pt_per_px=0.375)
    assert rb[2] > 0 and rb[3] > 0


def test_render_architecture_explicit_pt_per_px():
    """render_architecture accepts explicit pt_per_px keyword."""
    result = render_architecture(copy.deepcopy(_SIMPLE_TREE),
                                 x=100, y=180, width=1720, height=800,
                                 pt_per_px=0.375)
    assert "elements" in result
    assert result["bbox"]["width"] > 0


# ---------------------------------------------------------------------------
# Box with explicit height: pt_per_px should NOT affect it
# ---------------------------------------------------------------------------

def test_explicit_height_ignores_pt_per_px():
    """When box has explicit height, pt_per_px should not change it."""
    node = {"id": "n", "box": {"title": "Fixed", "width": 240, "height": 100}}
    h_05 = _get_box_height(node, pt_per_px=0.5)
    h_0375 = _get_box_height(node, pt_per_px=0.375)
    assert h_05 == 100
    assert h_0375 == 100
