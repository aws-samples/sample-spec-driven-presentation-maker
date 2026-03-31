# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Default values for element fields, shared by builder and converter."""

# Preferred key order for element dicts
KEY_ORDER = [
    "type", "shape", "preset", "connectorType", "elbowStart",
    "x1", "y1", "x2", "y2",
    "x", "y", "width", "height",
    "adjustments", "rotation", "flipH", "flipV",
    "fill", "gradient", "opacity", "line", "lineWidth", "lineGradient", "dashStyle",
    "arrowStart", "arrowEnd", "points", "path",
    "text", "paragraphs", "items", "src",
    "fontSize", "fontColor", "align", "verticalAlign",
    "label", "labelPosition", "link",
    "marginLeft", "marginTop", "marginRight", "marginBottom",
]

_KEY_ORDER_MAP = {k: i for i, k in enumerate(KEY_ORDER)}


def sort_element_keys(elem: dict) -> dict:
    """Sort element dict keys in preferred order."""
    fallback = len(KEY_ORDER)
    return dict(sorted(elem.items(), key=lambda kv: _KEY_ORDER_MAP.get(kv[0], fallback)))

ELEMENT_DEFAULTS = {
    "textbox": {
        "fill": "none",
        "line": "none",
        "align": "left",
        "rotation": 0,
        "flipH": False,
        "flipV": False,
    },
    "shape": {
        "fill": "none",
        "line": "none",
        "lineWidth": 1,
        "rotation": 0,
        "flipH": False,
        "flipV": False,
    },
    "freeform": {
        "fill": "none",
        "line": "none",
        "rotation": 0,
        "flipH": False,
        "flipV": False,
    },
    "line": {
        "preset": "line",
        "connectorType": "straight",
        "elbowStart": "horizontal",
        "lineWidth": 1.25,
    },
    "image": {
        "rotation": 0,
        "flipH": False,
        "flipV": False,
    },
    "table": {
        "rotation": 0,
    },
    "chart": {
        "rotation": 0,
    },
    "group": {
        "rotation": 0,
    },
}

GRADIENT_DEFAULTS = {
    "rotWithShape": True,
    "type": "linear",
}

# Paragraph-level keys that are internal formatting (not user-facing)
PARAGRAPH_INTERNAL_KEYS = frozenset({"buFont", "marL", "indent"})
