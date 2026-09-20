# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Extract live-preview layout regions from slide element annotations."""

import math
import re

_REGION_COMMENT = re.compile(r"^region:\s*(.+)$", re.IGNORECASE)


def _region_name(comment: object) -> str | None:
    """Return the normalized region name encoded by an element comment."""
    if not isinstance(comment, str):
        return None
    value = comment.strip()
    if value.lower() == "content region":
        return "content"
    match = _REGION_COMMENT.fullmatch(value)
    if not match:
        return None
    name = match.group(1).strip()
    return name or None


def _is_number(value: object) -> bool:
    """Accept finite JSON numbers, excluding booleans."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def extract_regions(slide: dict) -> list[dict]:
    """Extract valid 1920-based layout regions from a slide definition.

    Regions are ordinary slide elements annotated with ``_comment`` set to
    ``region: <name>``. The legacy shorthand ``content region`` maps to the
    name ``content``. Malformed annotations and non-numeric bounds are ignored.
    """
    if not isinstance(slide, dict):
        return []
    elements = slide.get("elements")
    if not isinstance(elements, list):
        return []

    regions: list[dict] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        name = _region_name(element.get("_comment"))
        width = element.get("w", element.get("width"))
        height = element.get("h", element.get("height"))
        bounds = (element.get("x"), element.get("y"), width, height)
        if name is None or not all(_is_number(value) for value in bounds):
            continue
        x, y, w, h = bounds
        regions.append({"name": name, "x": x, "y": y, "w": w, "h": h})
    return regions
