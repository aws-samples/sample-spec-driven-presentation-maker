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

import os
import sys
from pathlib import Path

# Prefer checkout sources only when this file is running from the repository.
# Installed wheels resolve sdpm and shared from their normal site-packages paths.
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
_SKILL_DIR = _REPO_ROOT / "sdpm"
if (_SKILL_DIR / "sdpm" / "config.py").is_file():
    sys.path.insert(0, str(_SKILL_DIR))
    sys.path.insert(0, str(_REPO_ROOT))

import functools  # noqa: E402
import inspect  # noqa: E402

import deck_access  # noqa: E402
import sandbox_tools  # noqa: E402
import sdpm_command  # noqa: E402
from mcp.server.mcpserver import Context, MCPServer  # noqa: E402

from sdpm import tools  # noqa: E402
from sdpm.tools import tool_errors  # noqa: E402
from sdpm.tools.apps.binding import caller_declared  # noqa: E402
from sdpm.tools.attachment.contracts import read_attachment, import_attachment  # noqa: E402
from sdpm.tools.instructions import instructions  # noqa: E402

mcp = MCPServer(
    "spec-driven-presentation-maker",
    instructions=instructions(),
)
tool_errors.install(mcp)

# ---------------------------------------------------------------------------
# Local-environment fact: the `sdpm open` hint
# ---------------------------------------------------------------------------

# The result field carrying a sentence for the agent to pass to the user: the command that
# opens the deck in the browser Web UI. The sentence says what it is, so no role document
# mentions it.
OPEN_HINT_FIELD = "note_for_user"
_CHECKOUT = _REPO_ROOT


def _result_deck(result: dict) -> Path | None:
    """The deck a result created (``output_dir``) or built into (``output_path``); None for a
    result that did neither, such as generate_pptx declining an HTML deck."""
    if result.get("output_dir"):
        return Path(result["output_dir"])
    if result.get("output_path"):
        return Path(result["output_path"]).parent
    return None


def _with_open_hint(fn):
    """``fn`` with ``note_for_user`` (how to open the deck with ``sdpm open``) added to its
    result when it created or built a deck, the Web UI is installed here and the client did
    not declare MCP Apps (it would show the deck itself). The deck must sit in the root
    ``sdpm open`` searches (``sdpm_command.deck_root``). Same name, docstring and signature,
    so the tool's schema is the contract's; the one added parameter is the request ``Context``,
    which MCPServer injects and leaves out of the schema."""

    @functools.wraps(fn)
    def bound(*args, ctx: Context | None = None, **kwargs):
        result = fn(*args, **kwargs)
        if not isinstance(result, dict) or "error" in result:
            return result
        deck = _result_deck(result)
        declared = ctx is not None and caller_declared(ctx.request_context)
        if not deck or declared or not sdpm_command.webui_installed_at(_CHECKOUT):
            return result
        hint = sdpm_command.open_hint(deck, sdpm_command.deck_root())
        if hint:
            result[OPEN_HINT_FIELD] = f"To open this deck in the browser Web UI, run `{hint}` in a terminal."
        return result

    signature = inspect.signature(fn)
    context = inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=Context | None)
    bound.__signature__ = signature.replace(parameters=[*signature.parameters.values(), context])
    bound.__annotations__ = {**fn.__annotations__, "ctx": Context | None}
    return bound


# ---------------------------------------------------------------------------
# Contract tools (1-line registration from sdpm.tools)
# ---------------------------------------------------------------------------

mcp.tool()(tools.start_presentation)
mcp.tool()(tools.start_composing)
mcp.tool()(tools.start_style)
mcp.tool()(tools.start_translation)
mcp.tool()(_with_open_hint(tools.init_deck_workspace))
mcp.tool()(tools.check_specs)
mcp.tool()(tools.analyze_template)
mcp.tool()(_with_open_hint(tools.generate_pptx))
mcp.tool()(tools.search_assets)
mcp.tool()(tools.list_templates)
mcp.tool()(tools.list_styles)
mcp.tool()(tools.apply_style)
mcp.tool()(tools.read_guides)
mcp.tool()(tools.describe_effects)
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

# MCP Apps: the style gallery on list_styles, the deck viewer on check_specs and show_deck
# (the deck directory read through deck_access), and the app-only tool the views call
from sdpm.tools import apps as _apps  # noqa: E402

_apps.register(mcp, deck=deck_access.ACCESS)


def main() -> None:
    """Run the local MCP server over stdio."""
    # A clone-free (uvx) setup has no icon catalogs on first start; fetch them in the
    # background so registering the server is the whole setup. SDPM_AUTO_INSTALL_ASSETS=0
    # opts out (offline hosts, tests).
    if os.environ.get("SDPM_AUTO_INSTALL_ASSETS", "1") != "0":
        from sdpm.knowledge.assets.download import ensure_assets_installed_async
        ensure_assets_installed_async()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
