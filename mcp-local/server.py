# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""spec-driven-presentation-maker Local MCP Server (Layer 2).

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

stdio transport for local MCP clients (Claude Desktop, VS Code, Goose, etc.).
Wraps the skill/ engine as MCP tools. All file I/O is local filesystem.

Usage:
    python server.py
    # or via MCP client config: {"command": "python", "args": ["mcp-local/server.py"]}
"""

import sys
from pathlib import Path

# Add skill/ to sys.path so sdpm package is importable
_SKILL_DIR = Path(__file__).resolve().parent.parent / "skill"
sys.path.insert(0, str(_SKILL_DIR))

# Add project root to sys.path so shared/ package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sandbox_tools  # noqa: E402
import tools  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402
from upload_tools import import_attachment as _import_attachment  # noqa: E402

# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------

_INSTRUCTIONS = """spec-driven-presentation-maker: AI-powered PowerPoint generation from JSON.

**Critical constraint:** Do NOT make any decisions about slide structure, content, design, or layout before loading the workflow. The workflow files contain the full process including briefing, outline, and art direction. Wait until the workflow is loaded and follow it step by step.

**Present the options and ask which to do:**

A. New presentation — create slides from scratch
B. Edit existing PPTX — modify a provided file
C. Hand-edit sync — continue from a user-edited PPTX
D. Create style — build a reusable style guide

## Workflow A: New Presentation

When no existing PPTX is provided.
→ Read `read_workflows(["create-new-1-briefing"])` to start. Follow each file's Next Step from there.

## Workflow B: Edit Existing PPTX

When an existing PPTX is provided.
→ Read `read_workflows(["edit-existing"])` to start.

## Workflow C: Hand-Edit Sync

When the user hand-edits the generated PPTX in PowerPoint and then asks for further changes.
→ Read `read_workflows(["create-new-4-hand-edit-sync"])` to start.

## Workflow D: Create Style

When the user wants to create a new reusable style guide.
→ Read `read_workflows(["create-style"])` to start.
"""

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "spec-driven-presentation-maker",
    instructions=_INSTRUCTIONS,
)

# ---------------------------------------------------------------------------
# Common tools (1-line registration from tools.py)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# MCP-specific tools (overrides or additions)
# ---------------------------------------------------------------------------


@mcp.tool()
def import_attachment(source: str, deck_id: str, filename: str = "") -> str:
    """Import a file into the deck workspace for use in slides.

    source is either an uploadId or an HTTP(S) URL.
    - uploadId: copies pre-converted files from session storage to deck.
    - URL: downloads image and saves to deck.

    Args:
        source: Upload ID from [Attached: ...] message, or an HTTP(S) URL.
        deck_id: The deck directory path (must be initialized via init_presentation).
        filename: Optional output filename.

    Returns:
        JSON with saved file paths and image_mapping.
    """
    return _import_attachment(source=source, deck_id=deck_id, filename=filename)


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


if __name__ == "__main__":
    mcp.run(transport="stdio")
