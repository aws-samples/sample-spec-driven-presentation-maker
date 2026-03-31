# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Code block generation — saves syntax-highlighted code as include file in S3."""

import json
from typing import Any

from storage import Storage


def code_block_to_include(
    deck_id: str,
    code: str,
    name: str,
    storage: Storage,
    language: str = "python",
    theme: str = "dark",
    x: int = 0,
    y: int = 0,
    width: int = 800,
    height: int = 300,
) -> dict[str, str]:
    """Generate code block elements and save to S3 as an include file.

    Args:
        deck_id: Deck identifier (for S3 path).
        code: Source code text.
        name: Include file name (without extension).
        storage: Storage backend instance.
        language: Programming language for syntax highlighting.
        theme: Color theme ("dark" or "light").
        x: X position in pixels.
        y: Y position in pixels.
        width: Width in pixels.
        height: Height in pixels.

    Returns:
        Dict with include_path for use in presentation.json.
    """
    from sdpm.utils.text import highlight_code
    from sdpm.builder.constants import CODE_COLORS

    colors = CODE_COLORS.get(theme, CODE_COLORS["dark"])
    label_height = 22

    elements: list[dict[str, Any]] = [
        {
            "type": "shape",
            "shape_type": "rectangle",
            "x": x, "y": y, "width": width, "height": height,
            "fill": colors["bg"],
            "corner_radius": 8,
        },
        {
            "type": "shape",
            "shape_type": "rectangle",
            "x": x, "y": y, "width": width, "height": label_height,
            "fill": colors["label_bg"],
            "corner_radius": 8,
        },
        {
            "type": "textbox",
            "x": x + 8, "y": y + 2,
            "width": width - 16, "height": label_height - 4,
            "text": [{"text": language, "font_size": 9, "color": colors["label_fg"]}],
        },
    ]

    spans = highlight_code(code, language, theme)
    elements.append({
        "type": "textbox",
        "x": x + 12, "y": y + label_height + 4,
        "width": width - 24, "height": height - label_height - 8,
        "text": spans,
    })

    # Save to S3 includes/
    include_path = f"includes/{name}.json"
    key = f"decks/{deck_id}/{include_path}"
    body = json.dumps(elements, ensure_ascii=False, indent=2).encode("utf-8")
    storage.upload_file(key=key, data=body, content_type="application/json")

    return {"include_path": include_path}
