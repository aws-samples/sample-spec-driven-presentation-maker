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


def read_attachment(source: str, offset: int = 0, limit: int = 10240) -> dict:
    """Read an ACP attachment; local paths must come from the raw attachment home."""
    if classify_source(source) == "local_path":
        try:
            validate_local_source(source, allow_any_path=False, root=_RAW_ATTACHMENT_ROOT)
        except Exception as error:
            return {"error": {"code": getattr(error, "code", "VALIDATION_ERROR"), "message": str(error)}}
    return _read_attachment(source=source, offset=offset, limit=limit)


def import_attachment(source: str, deck_id: str, filename: str = "") -> dict:
    """Import into an ACP deck while keeping raw sources and decks under DECK_ROOT."""
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

mcp.tool()(tools.init_presentation)
mcp.tool()(tools.analyze_template)
mcp.tool()(tools.generate_pptx)
mcp.tool()(tools.search_assets)
mcp.tool()(tools.list_templates)
mcp.tool()(tools.list_styles)
mcp.tool()(tools.apply_style)
mcp.tool()(tools.read_examples)
mcp.tool()(tools.list_workflows)
mcp.tool()(tools.read_workflows)
mcp.tool()(tools.list_guides)
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


@mcp.tool()
def hearing(
    inference: str,
    q0: dict,
    q1: dict | None = None,
    q2: dict | None = None,
    q3: dict | None = None,
    q4: dict | None = None,
) -> str:
    """Present structured questions to the user via a rich UI card.

    ALWAYS use this tool when you need the user to make a choice or
    judgment — not just for initial interviews but also for mid-workflow
    decisions, confirmations with options, and next-step selections.
    Only skip this tool for simple yes/no confirmations.

    Always include your reasoning or hypothesis in the inference field
    to help the user think — never ask blank questions.
    Limit to 5 questions per call. If you need more, call again after
    the user responds.

    Args:
        inference: Your reasoning or hypothesis to share with the user.
            This is displayed prominently above the questions to provide
            context and stimulate the user's thinking.
        q0: First question object with keys:
            - type (str): "single_select", "multi_select", or "free_text"
            - text (str): The question text
            - options (list[str], optional): Choices for select types
            - recommended (str or list[str], optional): Suggested choice(s)
            - placeholder (str, optional): Hint text for free_text type
        q1: Second question (optional, same schema as q0).
        q2: Third question (optional, same schema as q0).
        q3: Fourth question (optional, same schema as q0).
        q4: Fifth question (optional, same schema as q0).

    Returns:
        Confirmation that the questions were displayed. Wait for the
        user's response in the next message.
    """
    return "Questions displayed to user. Wait for their response."


if __name__ == "__main__":
    mcp.run(transport="stdio")
