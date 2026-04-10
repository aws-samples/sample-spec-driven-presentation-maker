# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Slide JSON linter — validates elements against slide-json-spec.md."""

from __future__ import annotations


def lint(data: list | dict) -> list[dict]:
    """Lint slide JSON and return diagnostics.

    Args:
        data: Slide list or presentation dict with "slides" key.

    Returns:
        List of diagnostic dicts with slide, element, rule, message.
        Empty list means no issues found.
    """
    slides = data.get("slides", data) if isinstance(data, dict) else data
    if not isinstance(slides, list):
        return []
    diagnostics: list[dict] = []
    for si, slide in enumerate(slides):
        for ei, elem in enumerate(slide.get("elements") or []):
            diagnostics.extend(_lint_element(si, ei, elem))
    return diagnostics


def _diag(slide: int, element: int, rule: str, message: str) -> dict:
    return {"slide": slide, "element": element, "rule": rule, "message": message}


# ---------------------------------------------------------------------------
# Per-element-type linting
# ---------------------------------------------------------------------------

def _lint_element(si: int, ei: int, elem: dict) -> list[dict]:
    etype = elem.get("type")
    if etype is None:
        return [_diag(si, ei, "missing-type", "element has no 'type' field")]
    results: list[dict] = []
    checker = _CHECKERS.get(etype)
    if checker:
        results.extend(checker(si, ei, elem))
    return results


# --- line ---

# Keys valid for line elements per slide-json-spec.md
_LINE_COORD_KEYS = {"x1", "y1", "x2", "y2"}
_LINE_POLYLINE_KEYS = {"points"}
_LINE_STYLE_KEYS = {
    "color", "lineWidth", "dashStyle", "connectorType", "elbowStart",
    "preset", "adjustments", "arrowStart", "arrowEnd", "lineGradient",
    "opacity",
}
_LINE_META_KEYS = {"type", "_comment"}
_LINE_ALL_KEYS = _LINE_COORD_KEYS | _LINE_POLYLINE_KEYS | _LINE_STYLE_KEYS | _LINE_META_KEYS

# Keys that belong to bbox-positioned elements (shape/textbox/image), not line
_BBOX_KEYS = {"x", "y", "width", "height"}

_ARROW_VALUES = {"arrow", "triangle", "stealth", "oval", "diamond", "none"}
_DASH_VALUES = {"solid", "dash", "dot", "dash_dot", "long_dash", "square_dot",
                "dash_dot_dot", "long_dash_dot"}
_CONNECTOR_VALUES = {"straight", "elbow", "curved"}


def _lint_line(si: int, ei: int, elem: dict) -> list[dict]:
    results: list[dict] = []
    has_points = "points" in elem
    has_x1 = "x1" in elem
    has_bbox = bool(_BBOX_KEYS & elem.keys())

    # Core coordinate check
    if not has_points and not has_x1:
        if has_bbox:
            bbox_found = sorted(_BBOX_KEYS & elem.keys())
            results.append(_diag(
                si, ei, "line-bbox-keys",
                f"line element uses {bbox_found} instead of x1/y1/x2/y2. "
                f"line requires x1/y1 (start) and x2/y2 (end), or points for polyline."
            ))
        else:
            results.append(_diag(
                si, ei, "line-missing-coords",
                "line element has no coordinates. Use x1/y1/x2/y2 or points."
            ))

    if has_x1 and not has_points:
        for k in ("x1", "y1", "x2", "y2"):
            if k not in elem:
                results.append(_diag(
                    si, ei, "line-missing-coord",
                    f"line element missing '{k}'. All of x1/y1/x2/y2 are required."
                ))

    # Polyline validation
    if has_points:
        pts = elem["points"]
        if not isinstance(pts, list) or len(pts) < 2:
            results.append(_diag(
                si, ei, "line-points-invalid",
                "line points must be an array of 2+ coordinate pairs."
            ))

    # Enum checks
    for key, allowed in (
        ("arrowStart", _ARROW_VALUES),
        ("arrowEnd", _ARROW_VALUES),
        ("dashStyle", _DASH_VALUES),
        ("connectorType", _CONNECTOR_VALUES),
    ):
        val = elem.get(key)
        if val is not None and val not in allowed:
            results.append(_diag(
                si, ei, f"line-invalid-{key}",
                f"line '{key}' value '{val}' is not valid. Allowed: {sorted(allowed)}"
            ))

    return results


# --- shape ---

_SHAPE_NAMES = {
    "rectangle", "rounded_rectangle", "oval", "circle",
    "arrow_right", "arrow_left", "arrow_up", "arrow_down",
    "arrow_circular", "arrow_left_right", "arrow_up_down",
    "arrow_curved_right", "arrow_curved_left", "arrow_curved_up", "arrow_curved_down",
    "arrow_circular_left", "arrow_circular_left_right",
    "triangle", "diamond", "pentagon", "hexagon", "cross",
    "trapezoid", "parallelogram", "chevron", "donut", "arc", "block_arc",
    "chord", "pie", "pie_wedge", "cloud", "lightning_bolt", "star_5_point",
    "no_symbol",
    "callout_rectangle", "callout_rounded_rectangle", "callout_oval",
    "flowchart_process", "flowchart_decision", "flowchart_terminator",
    "left_brace", "right_brace", "left_bracket", "right_bracket",
}


def _lint_shape(si: int, ei: int, elem: dict) -> list[dict]:
    results: list[dict] = []
    shape = elem.get("shape")
    if shape is not None and shape not in _SHAPE_NAMES:
        results.append(_diag(
            si, ei, "shape-unknown-name",
            f"shape name '{shape}' is not recognized."
        ))
    results.extend(_lint_bbox(si, ei, elem, "shape"))
    results.extend(_lint_opacity(si, ei, elem))
    return results


# --- textbox ---

def _lint_textbox(si: int, ei: int, elem: dict) -> list[dict]:
    results: list[dict] = []
    if "height" not in elem:
        results.append(_diag(
            si, ei, "textbox-missing-height",
            "textbox requires 'height'. Text overflow cannot be detected without it."
        ))
    results.extend(_lint_opacity(si, ei, elem))
    return results


# --- image ---

def _lint_image(si: int, ei: int, elem: dict) -> list[dict]:
    results: list[dict] = []
    if "src" not in elem:
        results.append(_diag(
            si, ei, "image-missing-src",
            "image element requires 'src'."
        ))
    results.extend(_lint_bbox(si, ei, elem, "image"))
    results.extend(_lint_opacity(si, ei, elem))
    return results


# --- common helpers ---

def _lint_bbox(si: int, ei: int, elem: dict, etype: str) -> list[dict]:
    results: list[dict] = []
    for k in ("x", "y"):
        if k not in elem:
            results.append(_diag(
                si, ei, f"{etype}-missing-{k}",
                f"{etype} element missing '{k}'."
            ))
    return results


def _lint_opacity(si: int, ei: int, elem: dict) -> list[dict]:
    val = elem.get("opacity")
    if val is not None and (not isinstance(val, (int, float)) or val < 0 or val > 1):
        return [_diag(
            si, ei, "invalid-opacity",
            f"opacity {val} is out of range. Must be 0–1."
        )]
    return []


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_CHECKERS = {
    "line": _lint_line,
    "shape": _lint_shape,
    "textbox": _lint_textbox,
    "image": _lint_image,
}
