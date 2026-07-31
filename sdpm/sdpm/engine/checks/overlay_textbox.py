"""Overlay textbox detection.

Flags pairs where a `textbox` element overlays a `shape` element with
substantially the same bounding box. The agent-friendly fix is to put the
label in the shape's ``text`` property instead of stacking two elements.

Background — overlay pattern produced by agents:

    {"type": "shape",   "x": 100, "y": 200, "width": 200, "height": 100, ...}
    {"type": "textbox", "x": 100, "y": 200, "width": 200, "height": 100,
     "text": "label", ...}

Correct form:

    {"type": "shape", "x": 100, "y": 200, "width": 200, "height": 100,
     "text": "label", "fontSize": 20,
     "align": "center", "verticalAlign": "middle"}

Why overlay is harmful:

- Independent wrap calculation; if widths drift, the two visually collide.
- Doubles the maintenance cost (two elements must move together).
- The shape's ``measure`` overflow warning does not see the textbox.

This check emits warnings only — it does not block generation.
"""

from __future__ import annotations

from typing import Iterable

# Tolerance (in slide pixels) for treating two elements as occupying the
# same region. Agents sometimes emit small offsets (1–2px) when copying
# coordinates between elements.
_COORD_TOLERANCE = 2


def _is_substantially_same_box(a: dict, b: dict) -> bool:
    """True when two elements' bounding boxes match within tolerance."""
    for key in ("x", "y", "width", "height"):
        av = a.get(key)
        bv = b.get(key)
        if av is None or bv is None:
            return False
        if abs(av - bv) > _COORD_TOLERANCE:
            return False
    return True


def _has_visible_text(element: dict) -> bool:
    """True when ``text`` is present and non-empty (string or list)."""
    text = element.get("text")
    if isinstance(text, str):
        return bool(text.strip())
    if isinstance(text, list):
        return len(text) > 0
    return False


def _iter_overlays(elements: list[dict]) -> Iterable[tuple[int, int, dict, dict]]:
    """Yield (shape_idx, textbox_idx, shape, textbox) for overlapping pairs."""
    for s_idx, shape in enumerate(elements):
        if not isinstance(shape, dict) or shape.get("type") != "shape":
            continue
        for t_idx, tb in enumerate(elements):
            if not isinstance(tb, dict) or tb.get("type") != "textbox":
                continue
            if _is_substantially_same_box(shape, tb):
                yield s_idx, t_idx, shape, tb


def check_overlay_textbox(slides_data: dict) -> list[str]:
    """Check for textbox elements that overlay a shape with the same box.

    Returns a list of warning lines. Empty list if no overlays found.
    The first line is a header, followed by one bullet per slide.
    """
    slides = slides_data.get("slides", [])
    findings: list[str] = []

    for slide_idx, slide in enumerate(slides, start=1):
        elements = slide.get("elements") or []
        if not isinstance(elements, list):
            continue
        slug = slide.get("id", "")
        location = f"page{slide_idx:02d}({slug})" if slug else f"page{slide_idx:02d}"
        for s_idx, t_idx, shape, tb in _iter_overlays(elements):
            shape_has_text = _has_visible_text(shape)
            tb_has_text = _has_visible_text(tb)
            if shape_has_text and tb_has_text:
                hint = "shape and textbox both carry text — drop the textbox"
            else:
                hint = "merge text into shape's `text` property"
            findings.append(
                f"  {location} elements=[{s_idx}, {t_idx}]: "
                f"textbox overlays shape — {hint}"
            )

    if not findings:
        return []
    header = (
        "overlay textbox detected: textbox shares a bounding box with a shape; "
        "put the label in the shape's `text` property instead"
    )
    return [header] + findings
