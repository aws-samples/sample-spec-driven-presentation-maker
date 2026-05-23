# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP Server variant for clients that do NOT read Server Instructions.

Adds a `start_presentation` tool that returns the workflow instructions.
Clients that support Server Instructions should use server.py instead.

Usage:
    python server_with_instruction.py
"""

import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent.parent / "skill"
sys.path.insert(0, str(_SKILL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sandbox_tools  # noqa: E402
import tools  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402
from server import _INSTRUCTIONS  # noqa: E402
from upload_tools import import_attachment as _import_attachment  # noqa: E402

mcp = FastMCP("spec-driven-presentation-maker")

# Common tools
mcp.tool()(tools.init_presentation)
mcp.tool()(tools.analyze_template)
mcp.tool()(tools.generate_pptx)
mcp.tool()(tools.measure_slides)
mcp.tool()(tools.search_assets)
mcp.tool()(tools.list_asset_sources)
mcp.tool()(tools.list_templates)
mcp.tool()(tools.apply_style)
mcp.tool()(tools.read_examples)
mcp.tool()(tools.list_workflows)
mcp.tool()(tools.read_workflows)
mcp.tool()(tools.list_guides)
mcp.tool()(tools.read_guides)
mcp.tool()(tools.code_to_slide)
mcp.tool()(tools.grid)
mcp.tool()(tools.pptx_to_json)

# Sandbox tools (shared)
mcp.tool()(sandbox_tools.run_python)
mcp.tool()(sandbox_tools.run_style_python)


# MCP-specific: import_attachment
@mcp.tool()
def import_attachment(source: str, deck_id: str, filename: str = "") -> str:
    """Import a file into the deck workspace for use in slides.

    Args:
        source: Upload ID from [Attached: ...] message, or an HTTP(S) URL.
        deck_id: The deck directory path.
        filename: Optional output filename.

    Returns:
        JSON with saved file paths and image_mapping.
    """
    return _import_attachment(source=source, deck_id=deck_id, filename=filename)


# MCP-specific: browser-opening list_styles
@mcp.tool()
def list_styles(include_all: bool = False) -> dict:
    """List available design styles for presentations.

    Default returns pinned + user styles only. Pass include_all=True for all.
    Opens a visual gallery in the browser for selection.

    Returns:
        Dict with styles list (name, description, pinned, source).
    """
    from sdpm.api import get_styles_dirs
    from sdpm.reference import open_styles_gallery
    open_styles_gallery(get_styles_dirs())
    return tools.list_styles(include_all=include_all)


# Addition: start_presentation for non-Instructions clients
@mcp.tool()
def start_presentation() -> str:
    """REQUIRED FIRST STEP for creating any PowerPoint/presentation/slide deck.
    Call this before using any other tool when the user wants to create, edit, or modify slides.

    Returns the complete workflow options and step-by-step instructions.
    """
    return _INSTRUCTIONS


if __name__ == "__main__":
    mcp.run(transport="stdio")
