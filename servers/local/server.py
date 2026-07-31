# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""spec-driven-presentation-maker Local MCP Server (Layer 2).

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

stdio transport for local MCP clients (Claude Desktop, VS Code, Goose, etc.).
Thin bind of the shared tool contract (:mod:`sdpm.tools`) — all file I/O is
local filesystem. Workflow instructions are exposed both as MCP Server
Instructions and via the ``start_presentation`` tool, so clients that do not
read Server Instructions work too.

Usage:
    python server.py
    # or via MCP client config: {"command": "python", "args": ["servers/local/server.py"]}
"""

import sys
from pathlib import Path

# Add sdpm/ (skill root) to sys.path so sdpm package is importable
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SKILL_DIR = _REPO_ROOT / "sdpm"
sys.path.insert(0, str(_SKILL_DIR))

# Add project root to sys.path so shared/ package is importable
sys.path.insert(0, str(_REPO_ROOT))

import sandbox_tools  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402
from upload_tools import import_attachment as _import_attachment  # noqa: E402
from upload_tools import upload_file as _upload_file  # noqa: E402

from sdpm import tools  # noqa: E402
from sdpm.tools.instructions import INSTRUCTIONS  # noqa: E402

mcp = FastMCP(
    "spec-driven-presentation-maker",
    instructions=INSTRUCTIONS,
)

# ---------------------------------------------------------------------------
# Contract tools (1-line registration from sdpm.tools)
# ---------------------------------------------------------------------------

mcp.tool()(tools.start_presentation)
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
mcp.tool()(tools.arch_diagram)
mcp.tool()(tools.pptx_to_json)
mcp.tool()(tools.diff_pptx)

# Sandbox tools (local-process sandbox)
mcp.tool()(sandbox_tools.run_python)
mcp.tool()(sandbox_tools.run_style_python)


# ---------------------------------------------------------------------------
# Local-transport specific tools (session handling, browser UI)
# ---------------------------------------------------------------------------


@mcp.tool()
def upload_file(file_path: str, filename: str = "") -> str:
    """Convert and stage a local file for deck import.

    For PPTX: converts the file into a deck structure (deck.json +
    slides/*.json + images/ + placeholder template) and returns an
    `uploadId` plus `guideInstruction` — follow that instruction
    (typically `read_guides(["import-pptx"])`), then import into a deck
    via `import_attachment(source=uploadId, deck_id=...)`.

    Other file types (images, documents) are converted/staged the same
    way for later `import_attachment`.

    Args:
        file_path: Absolute path to the source file.
        filename: Original filename (defaults to basename of file_path).

    Returns:
        JSON with {uploadId, fileName, fileType, status, warnings?} and,
        for PPTX converted to deck structure, additionally
        {guide, guideInstruction, suggestedName, slideCount, themeHints}.
    """
    return _upload_file(session_id="mcp-local", file_path=file_path, filename=filename)


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
    from sdpm.knowledge.reference import open_styles_gallery
    open_styles_gallery(get_styles_dirs())
    return tools.list_styles(include_all=include_all)


if __name__ == "__main__":
    mcp.run(transport="stdio")
