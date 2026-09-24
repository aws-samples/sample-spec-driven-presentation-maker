# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""ACP-specific MCP server entry point.

Independent mcp instance with ACP-tailored tools:
- Common tools registered from tools.py (1-line each)
- Sandbox tools: run_python, run_style_python (shared via sandbox_tools.py)
- ACP-specific tools: hearing, read_attachment, import_attachment

Usage:
    uv run python server_acp.py
    # or in .kiro/agents/*.json: {"command": "uv", "args": ["run", "python", "server_acp.py"]}
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

import os  # noqa: E402
import sandbox_tools  # noqa: E402
from sdpm import tools  # noqa: E402
from sdpm.tools.attachment.contracts import (  # noqa: E402
    import_attachment as _import_attachment,
    read_attachment as _read_attachment,
)
from sdpm.tools.attachment.source import classify_source, validate_local_source  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402


_DECK_ROOT = Path(os.environ.get("SDPM_DECK_ROOT", Path.home() / "Documents" / "SDPM-Presentations")).resolve()
_RAW_ATTACHMENT_ROOT = _DECK_ROOT / ".attachments"


def read_attachment(
    source: Annotated[str, Field(description="Absolute path under the attachment home, or https:// URL.")],
    offset: Annotated[int, Field(description="UTF-8 byte offset into the text to start from.")] = 0,
    limit: Annotated[int, Field(description="Max bytes returned, 512–10240.")] = 10240,
) -> dict:
    """Read a user-supplied file or URL as paged, line-numbered text — PDF, DOCX, XLSX, PPTX,
    text, CSV, HTML, JSON — or image metadata. Pure read, nothing is stored.
    Formats and paging: read_guides(["attachments"]).
    """
    if classify_source(source) == "local_path":
        try:
            validate_local_source(source, allow_any_path=False, root=_RAW_ATTACHMENT_ROOT)
        except Exception as error:
            return {"error": {"code": getattr(error, "code", "VALIDATION_ERROR"), "message": str(error)}}
    return _read_attachment(source=source, offset=offset, limit=limit)


def import_attachment(
    source: Annotated[str, Field(description="Absolute path under the attachment home, or https:// URL.")],
    deck_id: Annotated[str, Field(description="Deck directory path.")],
    filename: Annotated[str, Field(description="Filename override; defaults to the source's name.")] = "",
) -> dict:
    """Import a file or URL into the deck's attachments/ so slides can use it: images
    (converted to PNG), PDF/DOCX/XLSX (text + images), PPTX (full deck structure), URLs.
    Idempotent per source. On IMPORT_INCOMPLETE call again with the same arguments.
    Bundle layout: read_guides(["attachments"]).
    """
    try:
        deck_path = Path(deck_id).resolve(strict=True)
        deck_path.relative_to(_DECK_ROOT)
        if classify_source(source) == "local_path":
            validate_local_source(source, allow_any_path=False, root=_RAW_ATTACHMENT_ROOT)
    except Exception as error:
        return {"error": {"code": getattr(error, "code", "VALIDATION_ERROR"), "message": str(error)}}
    return _import_attachment(source=source, deck_id=str(deck_path), filename=filename)

# ---------------------------------------------------------------------------
# MCP Server (independent instance — no instructions for ACP agents)
# ---------------------------------------------------------------------------

mcp = FastMCP("sdpm-acp")

# ---------------------------------------------------------------------------
# Common tools (1-line registration)
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
mcp.tool()(tools.list_styles)
mcp.tool()(tools.apply_style)
mcp.tool()(tools.read_guides)
mcp.tool()(tools.code_to_slide)
mcp.tool()(tools.grid)
mcp.tool()(tools.arch_diagram)
mcp.tool()(tools.diff_pptx)

# Attachment tools (stateless pipeline)
mcp.tool()(read_attachment)
mcp.tool()(import_attachment)

# Sandbox tools (shared)
mcp.tool()(sandbox_tools.run_python)
mcp.tool()(sandbox_tools.run_style_python)

# ---------------------------------------------------------------------------
# ACP-only tools
# ---------------------------------------------------------------------------


_Q_DESC = (
    'Question object: {"type": "single_select" | "multi_select" | "free_text", "text": str, '
    '"options": [str] (select types), "recommended": str | [str] (optional), '
    '"placeholder": str (free_text, optional)}.'
)
_Q = Annotated[dict | None, Field(description="Next question; same shape as q0.")]


@mcp.tool()
def hearing(
    inference: Annotated[str, Field(description="Your reasoning or hypothesis, shown above the questions.")],
    q0: Annotated[dict, Field(description=_Q_DESC)],
    q1: _Q = None,
    q2: _Q = None,
    q3: _Q = None,
    q4: _Q = None,
) -> str:
    """Show the user a card of up to five structured questions; the answers arrive in the
    user's next message. For more than five, call again after the reply.
    """
    return "Questions displayed to user. Wait for their response."


if __name__ == "__main__":
    mcp.run(transport="stdio")
