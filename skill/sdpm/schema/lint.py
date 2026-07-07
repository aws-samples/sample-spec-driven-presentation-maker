# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Slide JSON linter — validates elements against slide-json-spec.md."""

from __future__ import annotations

import re

_COLOR_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')
_ALIGN_VALUES = {"left", "center", "right"}
_VALIGN_VALUES = {"top", "middle", "bottom"}


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


def lint_and_sanitize(slide: dict) -> tuple[dict, list[dict]]:
    """Validate slide JSON and remove deprecated properties.

    Called before persisting slide JSON (S3 write-back or local file save).
    Text-based only — no PPTX build needed.

    Args:
        slide: Single slide dict (with "elements" key).

    Returns:
        (sanitized_slide, diagnostics) — cleaned dict and list of issues found.
    """
    import copy
    cleaned = copy.deepcopy(slide)
    diagnostics: list[dict] = []
    for ei, elem in enumerate(cleaned.get("elements") or []):
        diagnostics.extend(_lint_element(0, ei, elem))
        if elem.pop("_spAutoFit", None):
            diagnostics.append(_diag(0, ei, "deprecated-autofit",
                "_spAutoFit is deprecated and was removed. "
                "Use measure to detect overflow instead."))
    return cleaned, diagnostics


def _diag(slide: int, element: int, rule: str, message: str) -> dict:
    return {"slide": slide, "element": element, "rule": rule, "message": message}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _lint_element(si: int, ei: int, elem: dict) -> list[dict]:
    if "_comment" in elem:
        return []
    etype = elem.get("type")
    if etype is None:
        return [_diag(si, ei, "missing-type", "element has no 'type' field")]
    results: list[dict] = []
    checker = _TYPE_CHECKERS.get(etype)
    if checker:
        results.extend(checker(si, ei, elem))
    # Common checks for all element types
    results.extend(_lint_common(si, ei, elem))
    # Layout quality checks (readability) — warnings, not blockers
    if etype == "textbox":
        results.extend(_lint_textbox_overflow(si, ei, elem))
    return results


# ===================================================================
# Common checks (all element types)
# ===================================================================

def _lint_common(si: int, ei: int, elem: dict) -> list[dict]:
    results: list[dict] = []
    # opacity
    val = elem.get("opacity")
    if val is not None and (not isinstance(val, (int, float)) or val < 0 or val > 1):
        results.append(_diag(si, ei, "invalid-opacity",
                             f"opacity {val} is out of range. Must be 0–1."))
    # fontSize
    fs = elem.get("fontSize")
    if fs is not None:
        if not isinstance(fs, (int, float)) or fs <= 0:
            results.append(_diag(si, ei, "invalid-fontSize",
                                 f"fontSize {fs} is invalid. Must be a positive number."))
        elif isinstance(fs, float) and fs != 10.5:
            results.append(_diag(si, ei, "invalid-fontSize",
                                 f"fontSize {fs} is non-integer. Only integers and 10.5 are valid."))
    # color fields
    for key in ("fill", "color", "fontColor", "line"):
        c = elem.get(key)
        if isinstance(c, str) and c not in ("none", ""):
            if c.startswith("#") and not _COLOR_RE.match(c):
                results.append(_diag(si, ei, "invalid-color",
                                     f"'{key}' value '{c}' is not valid #RRGGBB."))
    # align
    a = elem.get("align")
    if a is not None and a not in _ALIGN_VALUES:
        results.append(_diag(si, ei, "invalid-align",
                             f"align '{a}' is not valid. Allowed: {sorted(_ALIGN_VALUES)}"))
    # verticalAlign
    va = elem.get("verticalAlign")
    if va is not None and va not in _VALIGN_VALUES:
        results.append(_diag(si, ei, "invalid-verticalAlign",
                             f"verticalAlign '{va}' is not valid. Allowed: {sorted(_VALIGN_VALUES)}"))
    # out-of-bounds (bbox elements)
    etype = elem.get("type", "")
    if etype in ("shape", "textbox", "image", "chart", "table", "video", "freeform"):
        x = elem.get("x", 0)
        y = elem.get("y", 0)
        w = elem.get("width", 0)
        h = elem.get("height", 0)
        if isinstance(x, (int, float)) and isinstance(w, (int, float)) and x + w > 1920:
            results.append(_diag(si, ei, "out-of-bounds",
                                 f"x({x}) + width({w}) = {x+w} exceeds slide width 1920."))
        if isinstance(y, (int, float)) and isinstance(h, (int, float)) and y + h > 1080:
            results.append(_diag(si, ei, "out-of-bounds",
                                 f"y({y}) + height({h}) = {y+h} exceeds slide height 1080."))
    return results


# ===================================================================
# line
# ===================================================================

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

    if not has_points and not has_x1:
        if has_bbox:
            bbox_found = sorted(_BBOX_KEYS & elem.keys())
            results.append(_diag(
                si, ei, "line-bbox-keys",
                f"line element uses {bbox_found} instead of x1/y1/x2/y2. "
                f"line requires x1/y1 (start) and x2/y2 (end), or points for polyline."))
        else:
            results.append(_diag(
                si, ei, "line-missing-coords",
                "line element has no coordinates. Use x1/y1/x2/y2 or points."))

    if has_x1 and not has_points:
        for k in ("x1", "y1", "x2", "y2"):
            if k not in elem:
                results.append(_diag(
                    si, ei, "line-missing-coord",
                    f"line element missing '{k}'. All of x1/y1/x2/y2 are required."))

    if has_points:
        pts = elem["points"]
        if not isinstance(pts, list) or len(pts) < 2:
            results.append(_diag(
                si, ei, "line-points-invalid",
                "line points must be an array of 2+ coordinate pairs."))

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
                f"line '{key}' value '{val}' is not valid. Allowed: {sorted(allowed)}"))

    return results


# ===================================================================
# shape
# ===================================================================

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
    if shape is None:
        # The builder silently skips shape elements without a 'shape' key,
        # so the element would vanish from the PPTX with no trace.
        results.append(_diag(si, ei, "shape-missing-name",
                             "shape element requires 'shape' (e.g. 'rectangle'). "
                             "Without it the element is silently dropped from the PPTX."))
    elif shape not in _SHAPE_NAMES:
        results.append(_diag(si, ei, "shape-unknown-name",
                             f"shape name '{shape}' is not recognized."))
    results.extend(_lint_bbox_required(si, ei, elem, "shape"))
    return results


# ===================================================================
# textbox
# ===================================================================

def _lint_textbox(si: int, ei: int, elem: dict) -> list[dict]:
    results: list[dict] = []
    if "height" not in elem:
        results.append(_diag(si, ei, "textbox-missing-height",
                             "textbox requires 'height'. Text overflow cannot be detected without it."))
    return results


# ===================================================================
# image
# ===================================================================

def _lint_image(si: int, ei: int, elem: dict) -> list[dict]:
    results: list[dict] = []
    if "src" not in elem:
        results.append(_diag(si, ei, "image-missing-src",
                             "image element requires 'src'."))
    results.extend(_lint_bbox_required(si, ei, elem, "image"))
    return results


# ===================================================================
# chart
# ===================================================================

_CHART_TYPES = {"bar", "line", "pie", "donut"}


def _lint_chart(si: int, ei: int, elem: dict) -> list[dict]:
    results: list[dict] = []
    ct = elem.get("chartType")
    if ct is None:
        results.append(_diag(si, ei, "chart-missing-chartType",
                             "chart element has no 'chartType'. Specify bar, line, pie, or donut."))
    elif ct not in _CHART_TYPES:
        results.append(_diag(si, ei, "chart-invalid-chartType",
                             f"chartType '{ct}' is not valid. Allowed: {sorted(_CHART_TYPES)}"))

    series = elem.get("series")
    if not series:
        results.append(_diag(si, ei, "chart-missing-series",
                             "chart element has no 'series' data."))
    else:
        cats = elem.get("categories", [])
        if cats:
            n_cats = len(cats)
            for i, s in enumerate(series):
                vals = s.get("values", [])
                if len(vals) != n_cats:
                    results.append(_diag(
                        si, ei, "chart-series-values-mismatch",
                        f"series[{i}] has {len(vals)} values but categories has {n_cats}."))

    if elem.get("holeSize") is not None and ct != "donut":
        results.append(_diag(si, ei, "chart-holeSize-wrong-type",
                             f"holeSize is only valid for chartType 'donut', not '{ct}'."))
    if elem.get("stacked") and ct not in ("bar", None):
        results.append(_diag(si, ei, "chart-stacked-wrong-type",
                             f"stacked is only valid for chartType 'bar', not '{ct}'."))

    results.extend(_lint_bbox_required(si, ei, elem, "chart"))
    return results


# ===================================================================
# table
# ===================================================================

def _lint_table(si: int, ei: int, elem: dict) -> list[dict]:
    results: list[dict] = []
    headers = elem.get("headers")
    rows = elem.get("rows")

    if not headers:
        results.append(_diag(si, ei, "table-missing-headers",
                             "table element has no 'headers'."))
    if not rows:
        results.append(_diag(si, ei, "table-missing-rows",
                             "table element has no 'rows'."))

    if headers and isinstance(headers, list):
        n_cols = len(headers)
        col_widths = elem.get("colWidths")
        if col_widths and isinstance(col_widths, list) and len(col_widths) != n_cols:
            results.append(_diag(
                si, ei, "table-column-count-mismatch",
                f"colWidths has {len(col_widths)} entries but headers has {n_cols} columns."))
        if rows and isinstance(rows, list):
            for ri, row in enumerate(rows):
                if isinstance(row, list) and len(row) != n_cols:
                    results.append(_diag(
                        si, ei, "table-column-count-mismatch",
                        f"rows[{ri}] has {len(row)} cells but headers has {n_cols} columns."))

    results.extend(_lint_bbox_required(si, ei, elem, "table"))
    return results


# ===================================================================
# freeform
# ===================================================================

_FREEFORM_CMDS = {"M", "L", "C", "Q", "A", "Z"}


def _lint_freeform(si: int, ei: int, elem: dict) -> list[dict]:
    results: list[dict] = []
    path = elem.get("path")
    paths = elem.get("paths")
    custom = elem.get("customGeometry")

    if not path and not paths and not custom:
        results.append(_diag(si, ei, "freeform-missing-path",
                             "freeform element has no 'path', 'paths', or 'customGeometry'."))

    if path and isinstance(path, list):
        if path and path[0].get("cmd") != "M":
            results.append(_diag(si, ei, "freeform-no-moveTo",
                                 "freeform path must start with 'M' (moveTo) command."))
        for pi, cmd in enumerate(path):
            c = cmd.get("cmd")
            if c and c not in _FREEFORM_CMDS:
                results.append(_diag(
                    si, ei, "freeform-invalid-cmd",
                    f"freeform path[{pi}] cmd '{c}' is not valid. Allowed: {sorted(_FREEFORM_CMDS)}"))

    results.extend(_lint_bbox_required(si, ei, elem, "freeform"))
    return results


# ===================================================================
# include
# ===================================================================

def _lint_include(si: int, ei: int, elem: dict) -> list[dict]:
    if "src" not in elem:
        return [_diag(si, ei, "include-missing-src",
                       "include element requires 'src'.")]
    return []


# ===================================================================
# video
# ===================================================================

def _lint_video(si: int, ei: int, elem: dict) -> list[dict]:
    results: list[dict] = []
    if "src" not in elem:
        results.append(_diag(si, ei, "video-missing-src",
                             "video element requires 'src'."))
    results.extend(_lint_bbox_required(si, ei, elem, "video"))
    return results


# ===================================================================
# Layout quality checks (readability warnings)
# ===================================================================
# Deliberately minimal. Rules considered and rejected:
# - minimum font size: no universal threshold exists — chart legends use 10,
#   diagram annotations 11 (both per official guides). Per-deck minimums are
#   the Token Discipline check's job (checks/font_size.py).
# - declared-color contrast: the declared fill/background rarely matches what
#   actually renders behind text (template backgrounds, overlays, gradients).
#   Contrast belongs in rendering-based measurement (SVG), not here.

# Text metrics calibrated against actual LibreOffice rendering (SVG export,
# 1920x1080 px space where 1pt = 2px), stable across fonts:
#   char width: halfwidth ~= fontSize x 1.0 px, fullwidth ~= fontSize x 2.0 px
#   line height: ~fontSize x 2.35 px (multi-line; single line ~2.1)
# _LINE_HEIGHT_FACTOR / _OVERFLOW_MARGIN = 2.35, so the warning fires right
# at the measured overflow boundary. The margin absorbs word-wrap slack and
# the ~15px top/bottom text insets we don't model.
_LINE_HEIGHT_FACTOR = 2.7
_OVERFLOW_MARGIN = 1.15

# Strips {{attrs:...}} styling directives down to their text content.
_STYLED_DIRECTIVE_RE = re.compile(r'\{\{[^:}]*:([^}]*)\}\}')


def _valid_font_size(val) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0


def _estimate_line_width_px(text: str, font_size: float) -> float:
    """Width guide from slide-json-spec.md: fullwidth = pt*2, halfwidth = pt*1."""
    from sdpm.utils.text import is_fullwidth
    return sum(font_size * (2 if is_fullwidth(ch) else 1) for ch in text)


def _estimate_text_lines(text: str, font_size: float, usable_width: float) -> int:
    """Estimate rendered line count of text (with \\n) wrapped to usable_width."""
    total = 0
    for raw_line in text.split("\n"):
        if not raw_line:
            total += 1
            continue
        line_w = _estimate_line_width_px(raw_line, font_size)
        total += max(1, -(-int(line_w) // max(1, int(usable_width))))
    return total


def _estimate_height_px(lines: int, font_size: float) -> float:
    return max(1, lines) * font_size * _LINE_HEIGHT_FACTOR


def _lint_textbox_overflow(si: int, ei: int, elem: dict) -> list[dict]:
    if elem.get("autoWidth"):
        return []
    width = elem.get("width")
    height = elem.get("height")
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        return []
    if width <= 0 or height <= 0:
        return []
    margin_lr = 0.0
    for k in ("marginLeft", "marginRight"):
        m = elem.get(k)
        if isinstance(m, (int, float)):
            margin_lr += m
    usable_width = width - margin_lr
    if usable_width <= 0:
        return []

    default_fs = elem.get("fontSize")
    est = 0.0
    paragraphs = elem.get("paragraphs")
    if isinstance(paragraphs, list) and paragraphs:
        for para in paragraphs:
            if not isinstance(para, dict):
                return []
            text = para.get("text")
            fs = para.get("fontSize", default_fs)
            if not isinstance(text, str) or not _valid_font_size(fs):
                return []  # any unmeasurable paragraph -> skip whole element
            clean = _STYLED_DIRECTIVE_RE.sub(r'\1', text)
            lines = _estimate_text_lines(clean, fs, usable_width)
            est += _estimate_height_px(lines, fs)
    else:
        text = elem.get("text")
        if not isinstance(text, str) or not text or not _valid_font_size(default_fs):
            return []
        clean = _STYLED_DIRECTIVE_RE.sub(r'\1', text)
        lines = _estimate_text_lines(clean, default_fs, usable_width)
        est = _estimate_height_px(lines, default_fs)

    margin_tb = 0.0
    for k in ("marginTop", "marginBottom"):
        m = elem.get(k)
        if isinstance(m, (int, float)):
            margin_tb += m
    est += margin_tb

    if est > height * _OVERFLOW_MARGIN:
        return [_diag(
            si, ei, "textbox-overflow-risk",
            f"estimated text height ~{est:.0f}px exceeds declared height {height}px. "
            f"Text likely overflows — shorten text, widen the box, or increase height. "
            f"Verify with measure (this estimate is heuristic).")]
    return []


# ===================================================================
# Helpers
# ===================================================================

def _lint_bbox_required(si: int, ei: int, elem: dict, etype: str) -> list[dict]:
    results: list[dict] = []
    for k in ("x", "y"):
        if k not in elem:
            results.append(_diag(si, ei, f"{etype}-missing-{k}",
                                 f"{etype} element missing '{k}'."))
    return results


# ===================================================================
# Registry
# ===================================================================

_TYPE_CHECKERS = {
    "line": _lint_line,
    "shape": _lint_shape,
    "textbox": _lint_textbox,
    "image": _lint_image,
    "chart": _lint_chart,
    "table": _lint_table,
    "freeform": _lint_freeform,
    "include": _lint_include,
    "video": _lint_video,
}
