# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Layout rules over the boxes the browser check measured on one HTML slide (pure).

``measured`` is what the measuring script returns for a slide (``browser_check``)::

    {"width": W, "height": H, "elements": [
        {"kind": "ph" | "region" | "child" | "free", "label": 'data-ph="title"',
         "region": <index of the enclosing region element, when inside one>,
         "box": [x, y, w, h], "scroll": [scrollWidth, scrollHeight, clientWidth, clientHeight]},
    …]}

Boxes are canvas px relative to the slide. ``decorations`` are the layout's template
decorations (``{name, source, bbox{x, y, w, h}, kind}``).

Rules (an intersection counts when both of its sides exceed ``tol``; "contains" is
within ``tol``):

    overlap             partial overlap (neither contains the other) between top-level
                        blocks (ph, region, free) or between children of the same region
    overflow            content larger than its box (scroll size past the client size) for
                        ph / region / child / free, or any element past the slide edge
    outside-region      an element inside a region extends past the region's box
    decoration-overlap  an element over a template decoration of kind ``band`` or
                        ``obstacle`` (placeholders skip ``band``, which backs them; ``ground``
                        is ignored)

More than ``MAX_FINDINGS`` findings: the last one is ``… and N more``.
"""

from __future__ import annotations

from typing import Any, Iterable

TOLERANCE_PX = 4
MAX_FINDINGS = 10

_SCROLL_KINDS = ("ph", "region", "child", "free")


def _diag(slug: str, rule: str, message: str) -> dict:
    return {"slug": slug, "rule": rule, "message": f"{rule}: {message}"}


def _px(value: float) -> int:
    return int(round(value))


def _intersection(a, b) -> tuple[float, float]:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(w, 0.0), max(h, 0.0)


def _contains(outer, inner, tol: float) -> bool:
    return (inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol
            and inner[0] + inner[2] <= outer[0] + outer[2] + tol
            and inner[1] + inner[3] <= outer[1] + outer[3] + tol)


def _excess(inner, outer) -> list[tuple[float, str]]:
    """How far ``inner`` extends past ``outer`` on each side: ``(px, side word)``."""
    return [
        (outer[1] - inner[1], "above"),
        (inner[1] + inner[3] - (outer[1] + outer[3]), "below"),
        (outer[0] - inner[0], "left of"),
        (inner[0] + inner[2] - (outer[0] + outer[2]), "right of"),
    ]


def _bbox(decoration: dict) -> list[float]:
    b = decoration.get("bbox") or {}
    return [b.get("x", 0), b.get("y", 0), b.get("w", 0), b.get("h", 0)]


def _pairs(items: list[int]) -> Iterable[tuple[int, int]]:
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            yield a, b


def judge_slide(slug: str, measured: dict[str, Any], decorations: list[dict] | None = None, *,
                tol: float = TOLERANCE_PX) -> list[dict]:
    """Layout diagnostics ``{slug, rule, message}`` for one measured slide."""
    elements = measured.get("elements") or []
    width, height = measured.get("width") or 0, measured.get("height") or 0
    out: list[dict] = []

    def label(i: int) -> str:
        return str(elements[i].get("label", "element"))

    def box(i: int) -> list[float]:
        return elements[i]["box"]

    # overlap: top-level blocks, then the children of each region
    groups: dict[Any, list[int]] = {}
    for i, el in enumerate(elements):
        groups.setdefault(el.get("region"), []).append(i)
    for members in groups.values():
        for a, b in _pairs(members):
            iw, ih = _intersection(box(a), box(b))
            if iw > tol and ih > tol and not _contains(box(a), box(b), tol) \
                    and not _contains(box(b), box(a), tol):
                out.append(_diag(slug, "overlap", f"{label(a)} × {label(b)} ({_px(iw)}×{_px(ih)} px); "
                                                   "move or resize one so each has its own space"))

    # overflow: content past its box, elements past the slide edge
    for i, el in enumerate(elements):
        scroll = el.get("scroll")
        if el.get("kind") in _SCROLL_KINDS and scroll and scroll[2] > 0 and scroll[3] > 0:
            sw, sh, cw, ch = scroll
            if sh > ch + tol or sw > cw + tol:
                out.append(_diag(slug, "overflow", f"{label(i)} content {_px(sw)}×{_px(sh)} px exceeds its "
                                                   f"box {_px(cw)}×{_px(ch)} px; shorten the content, "
                                                   "use a smaller --fs-* token or enlarge the box, "
                                                   "leaving a little room (fonts differ between "
                                                   "machines)"))
        if width and height:
            past = [(px, side) for px, side in _excess(box(i), [0, 0, width, height]) if px > tol]
            if past:
                px, side = max(past)
                edge = {"above": "top", "below": "bottom", "left of": "left", "right of": "right"}[side]
                out.append(_diag(slug, "overflow", f"{label(i)} extends {_px(px)} px past the slide's "
                                                   f"{edge} edge; keep it inside the canvas"))

    # outside-region: an element inside a region past the region's box
    for i, el in enumerate(elements):
        region = el.get("region")
        if region is None or not 0 <= region < len(elements):
            continue
        past = [(px, side) for px, side in _excess(box(i), box(region)) if px > tol]
        if past:
            px, side = max(past)
            out.append(_diag(slug, "outside-region", f"{label(i)} extends {_px(px)} px {side} {label(region)}; "
                                                  "fit it inside the region, or move or resize the region"))

    # decoration-overlap: bands and obstacles of the template layout
    for deco in decorations or []:
        kind = deco.get("kind")
        if kind not in ("band", "obstacle"):
            continue
        dbox = _bbox(deco)
        hit: set[int] = set()
        for i, el in enumerate(elements):
            if kind == "band" and el.get("kind") == "ph":
                continue
            if el.get("region") in hit:
                continue  # its region already reported for this decoration
            iw, ih = _intersection(box(i), dbox)
            if iw > tol and ih > tol:
                hit.add(i)
                out.append(_diag(slug, "decoration-overlap",
                                 f"{label(i)} covers the template's \"{deco.get('name', 'decoration')}\" "
                                 f"({kind}) by {_px(iw)}×{_px(ih)} px; move it clear of that box "
                                 "(template_html decorations)"))

    if len(out) > MAX_FINDINGS:
        rest = out[MAX_FINDINGS - 1:]
        out = out[:MAX_FINDINGS - 1]
        out.append({"slug": slug, "rule": rest[0]["rule"], "message": f"… and {len(rest)} more"})
    return out


__all__ = ["MAX_FINDINGS", "TOLERANCE_PX", "judge_slide"]
