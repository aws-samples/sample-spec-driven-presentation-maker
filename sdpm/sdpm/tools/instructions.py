# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Short entry instructions served to MCP clients that surface them.

Not every client shows server instructions to the model; the entry tools'
own descriptions carry the same routing, so nothing depends on this text.
Set ``SDPM_DISABLE_INSTRUCTIONS=1`` to serve none (used to measure that).
"""

import os

INSTRUCTIONS = """sdpm makes slide decks (PPTX or HTML). Start any slide work with \
start_presentation; it says what to do next. Read and write deck files only through \
run_python, never with your own file tools.
"""


def instructions() -> str | None:
    """Instructions to hand to the MCP server, or None when disabled by environment."""
    if os.environ.get("SDPM_DISABLE_INSTRUCTIONS", "").lower() in ("1", "true", "yes"):
        return None
    return INSTRUCTIONS
