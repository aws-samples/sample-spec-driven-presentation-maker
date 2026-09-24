# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Short entry instructions served to MCP clients that surface them.

Not every client shows server instructions to the model; the entry tools'
own descriptions carry the same routing, so nothing depends on this text.
Set ``SDPM_DISABLE_INSTRUCTIONS=1`` to serve none (used to measure that).
"""

import os

INSTRUCTIONS = """spec-driven-presentation-maker: AI-powered PowerPoint generation from JSON.

Call the entry tool for the role first — it returns the role document and its inputs:
- Anything about slides (new deck, edit/import a PPTX, restyle): `start_presentation()`
- Write assigned slides for a deck: `start_composing(deck_id, assigned_slugs)`
- Create a reusable style guide: `start_style()`
- Translate an existing deck: `start_translation(deck_id, language)`

Deck files are written only through `run_python` (never with client-side file tools):
it validates the JSON, rebuilds the PPTX and, with `measure_slides`, renders previews.
"""


def instructions() -> str | None:
    """Instructions to hand to the MCP server, or None when disabled by environment."""
    if os.environ.get("SDPM_DISABLE_INSTRUCTIONS", "").lower() in ("1", "true", "yes"):
        return None
    return INSTRUCTIONS
