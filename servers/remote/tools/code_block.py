# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Code block generation — saves syntax-highlighted code as include file in S3.

Element construction lives in ``sdpm.api.code_block`` (shared with the local server and
the CLI); this module only adds the S3 persistence.
"""

import json

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
    from sdpm.api import code_block

    elements = code_block(
        code=code, language=language, theme=theme, x=x, y=y, width=width, height=height,
    )

    # Save to S3 includes/
    include_path = f"includes/{name}.json"
    key = f"decks/{deck_id}/{include_path}"
    body = json.dumps(elements, ensure_ascii=False, indent=2).encode("utf-8")
    storage.upload_file(key=key, data=body, content_type="application/json")

    return {"include_path": include_path}
