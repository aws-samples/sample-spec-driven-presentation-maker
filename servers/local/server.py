# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""spec-driven-presentation-maker Local MCP Server (Layer 2).

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

stdio transport for local MCP clients (Claude Desktop, VS Code, Goose, etc.).
Thin bind of the shared tool contract (:mod:`sdpm.tools`) — all file I/O is
local filesystem. Workflow discovery is exposed through MCP Server Instructions;
role documents are delivered by the shared ``start_*`` entry tools.

Usage:
    python server.py
    # or via MCP client config: {"command": "python", "args": ["servers/local/server.py"]}
"""

import sys
from pathlib import Path
from typing import Annotated

from pydantic import Field

# Add sdpm/ (skill root) to sys.path so sdpm package is importable
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SKILL_DIR = _REPO_ROOT / "sdpm"
sys.path.insert(0, str(_SKILL_DIR))

# Add project root to sys.path so shared/ package is importable
sys.path.insert(0, str(_REPO_ROOT))

import sandbox_tools  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

from sdpm import tools  # noqa: E402
from sdpm.tools.attachment.contracts import read_attachment, import_attachment  # noqa: E402
from sdpm.tools.instructions import instructions  # noqa: E402

mcp = FastMCP(
    "spec-driven-presentation-maker",
    instructions=instructions(),
)

# ---------------------------------------------------------------------------
# Contract tools (1-line registration from sdpm.tools)
# ---------------------------------------------------------------------------

mcp.tool()(tools.start_presentation)
mcp.tool()(tools.start_composing)
mcp.tool()(tools.start_style)
mcp.tool()(tools.start_translation)
mcp.tool()(tools.init_deck_workspace)
mcp.tool()(tools.check_specs)
mcp.tool()(tools.analyze_template)
mcp.tool()(tools.generate_pptx)
mcp.tool()(tools.search_assets)
mcp.tool()(tools.list_templates)
mcp.tool()(tools.apply_style)
mcp.tool()(tools.read_guides)
mcp.tool()(tools.code_to_slide)
mcp.tool()(tools.grid)
mcp.tool()(tools.arch_diagram)

# User-invoked entry points (slash commands / prompt menu): vibe, spec, style, translate
from sdpm.tools import prompts as _prompts  # noqa: E402

_prompts.register(mcp)

# Attachment tools (stateless pipeline)
mcp.tool()(read_attachment)
mcp.tool()(import_attachment)

# Sandbox tools (local-process sandbox)
mcp.tool()(sandbox_tools.run_python)
mcp.tool()(sandbox_tools.run_style_python)


# ---------------------------------------------------------------------------
# Local-transport specific tools (browser style gallery)
# ---------------------------------------------------------------------------


@mcp.tool()
@mcp.tool()
def list_styles(
    include_all: Annotated[bool, Field(description='Include styles hidden by the pin filter.')] = False,
) -> dict:
    """List design styles — pinned and user styles by default, everything with
    include_all — and open the visual gallery in the browser. Names go to apply_style.
    start_presentation and start_style already return this list.
    """
    from sdpm.api import get_styles_dirs
    from sdpm.knowledge.reference import open_styles_gallery
    open_styles_gallery(get_styles_dirs())
    return tools.list_styles(include_all=include_all)


if __name__ == "__main__":
    mcp.run(transport="stdio")
