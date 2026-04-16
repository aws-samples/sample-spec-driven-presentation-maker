# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""spec-driven-presentation-maker Local MCP Server (Layer 2).

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

stdio transport for local MCP clients (Kiro CLI, Claude Desktop, VS Code, etc.).
Wraps the skill/ engine as MCP tools. All file I/O is local filesystem.

Usage:
    python server.py
    # or via MCP client config: {"command": "python", "args": ["mcp-local/server.py"]}
"""

import json
import sys
from pathlib import Path

# Add skill/ to sys.path so sdpm package is importable
_SKILL_DIR = Path(__file__).resolve().parent.parent / "skill"
sys.path.insert(0, str(_SKILL_DIR))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from tools import (  # noqa: E402
    init_presentation as _init_presentation,
    analyze_template as _analyze_template,
    generate_pptx as _generate_pptx,
    preview as _preview,
    measure as _measure,
    search_assets as _search_assets,
    list_asset_sources as _list_asset_sources,
    list_styles as _list_styles,
    read_examples as _read_examples,
    list_workflows as _list_workflows,
    read_workflows as _read_workflows,
    list_guides as _list_guides,
    read_guides as _read_guides,
    code_block as _code_block,
    pptx_to_json as _pptx_to_json,
)

# MCP Server Instructions — same content as start_presentation returns.
# Clients that support instructions (Claude Code, VS Code, Goose) get this automatically.
# Clients that don't will rely on start_presentation's tool description.
_INSTRUCTIONS = """spec-driven-presentation-maker: AI-powered PowerPoint generation from JSON.

## Architecture
- The agent edits workspace files via `run_python(deck_id=..., save=True)` using normal file I/O
- MCP tools handle: workflow guidance, initialization, PPTX generation, preview, references
- MCP tools do NOT handle: slide editing, spec writing (agent responsibility via run_python)

**Critical constraint:** Do NOT make any decisions about slide structure, content, design, or layout before loading the workflow. The workflow files contain the full process including briefing, outline, and art direction. Wait until the workflow is loaded and follow it step by step.

## Workflow: New Presentation

→ Read `read_workflows(["create-new-1-briefing"])` to start. Follow each file's Next Step from there.
"""

mcp = FastMCP(
    "spec-driven-presentation-maker",
    instructions=_INSTRUCTIONS,
)


@mcp.tool()
def init_presentation(name: str) -> str:
    """Initialize a presentation workspace. Call after Phase 1 hearing, before building slides.
    Creates output directory with empty presentation.json and specs/.

    Workflow equivalent: ``init {name}``

    Args:
        name: Presentation name (e.g. "lambda-overview").

    Returns:
        JSON with output_dir, json_path, and workspace file list.
    """
    return json.dumps(
        _init_presentation(name=name, template="", skill_dir=_SKILL_DIR),
        ensure_ascii=False,
    )


@mcp.tool()
def analyze_template(template_path: str, layout: str = "") -> str:
    """Analyze a PPTX template — extract layouts, theme colors, fonts.
    Call this to understand what layouts are available before building slides.

    Args:
        template_path: Template name (e.g. "sample_template_dark") or full path to .pptx file. Required.
        layout: Optional layout name or index to get detailed placeholder info (e.g. "タイトルのみ" or "5").

    Returns:
        JSON with layouts, theme colors, and font information.
    """
    if not template_path or not template_path.strip():
        return json.dumps({"error": "template_path is required"})
    return json.dumps(
        _analyze_template(template_path=template_path, layout=layout, skill_dir=_SKILL_DIR),
        ensure_ascii=False,
    )


@mcp.tool()
def generate_pptx(
    slides_json_path: str,
    output_path: str = "",
) -> str:
    """Generate PPTX from a JSON file. Call after building all slides.
    Template is auto-detected from presentation.json if init_presentation was used — no need to specify again.

    Args:
        slides_json_path: Path to the slides JSON file.
        output_path: Optional output path. Auto-generated if empty.

    Returns:
        JSON with output file path and slide summary.
    """
    return json.dumps(
        _generate_pptx(
            slides_json_path=slides_json_path, output_path=output_path, skill_dir=_SKILL_DIR
        ),
        ensure_ascii=False,
    )


@mcp.tool()
def get_preview(slides_json_path: str, pages: str = "", output_path: str = "") -> str:
    """Generate PNG previews from a slides JSON file.
    Requires LibreOffice and poppler-utils installed locally.

    Args:
        slides_json_path: Path to the slides JSON file.
        pages: Optional comma-separated page numbers (e.g. "1,3,5"). All pages if empty.
        output_path: Optional output directory path.

    Returns:
        JSON with generated PNG file paths.
    """
    return json.dumps(
        _preview(slides_json_path=slides_json_path, pages=pages, output_path=output_path),
        ensure_ascii=False,
    )


@mcp.tool()
def measure_slides(slides_json_path: str, pages: str = "") -> str:
    """Measure text bounding boxes for overflow detection.
    Generates SVG via LibreOffice and extracts bbox data.
    Requires LibreOffice installed locally.

    Args:
        slides_json_path: Path to the slides JSON file.
        pages: Optional comma-separated page numbers (e.g. "1,3,5"). All pages if empty.

    Returns:
        Measure report as text.
    """
    return _measure(slides_json_path=slides_json_path, pages=pages)


@mcp.tool()
def search_assets(
    query: str, limit: int = 20, source_filter: str = "", type_filter: str = "", theme_filter: str = ""
) -> str:
    """Search icons and assets by keyword. Use list_asset_sources to see available sources.
    Multiple keywords can be space-separated (e.g. "lambda s3 dynamodb") — each is searched independently.

    Args:
        query: Search keywords, space-separated for multiple queries (e.g. "lambda s3").
        limit: Maximum results to return per keyword.
        source_filter: Filter by source name (e.g. "aws", "material"). Use list_asset_sources to see options.
        type_filter: Filter by type (e.g. "Architecture-Service").
        theme_filter: Filter by theme ("dark" or "light").

    Returns:
        JSON with matching icons/assets and their paths.
    """
    return json.dumps(
        _search_assets(
            query=query,
            limit=limit,
            source_filter=source_filter,
            type_filter=type_filter,
            theme_filter=theme_filter,
            skill_dir=_SKILL_DIR,
        ),
        ensure_ascii=False,
    )


@mcp.tool()
def list_templates() -> str:
    """List all available PPTX templates with name.

    Returns:
        JSON with list of template names.
    """
    templates_dir = _SKILL_DIR / "templates"
    if not templates_dir.exists():
        return json.dumps({"templates": []})
    templates = sorted(t.stem for t in templates_dir.glob("*.pptx"))
    return json.dumps({"templates": templates})


@mcp.tool()
def list_asset_sources() -> str:
    """List available asset sources with counts and descriptions.

    Returns:
        JSON with list of sources (name, count, description).
    """
    return json.dumps(_list_asset_sources(skill_dir=_SKILL_DIR), ensure_ascii=False)


@mcp.tool()
def list_styles() -> str:
    """List available design styles for presentations.

    Workflow equivalent: ``examples styles``

    Returns:
        JSON with list of styles (name + description).
    """
    return json.dumps(_list_styles(skill_dir=_SKILL_DIR), ensure_ascii=False)


@mcp.tool()
def read_examples(names: list[str]) -> str:
    """Read design examples (components/patterns).
    Without page specifier returns a listing of slide descriptions.
    With page specifier returns full content.

    Workflow equivalent: ``examples {name}``

    Examples:
        read_examples(["patterns"]) → listing with page numbers
        read_examples(["patterns/3"]) → full content of page 3
        read_examples(["components/all"]) → all component pages

    Args:
        names: Example names, e.g. ["patterns", "patterns/3", "components/all"].

    Returns:
        JSON with document contents.
    """
    return json.dumps(_read_examples(names=names, skill_dir=_SKILL_DIR), ensure_ascii=False)


@mcp.tool()
def list_workflows() -> str:
    """List all available workflow documents (phase-by-phase instructions).

    Returns:
        JSON with list of workflows.
    """
    return json.dumps(_list_workflows(skill_dir=_SKILL_DIR), ensure_ascii=False)


@mcp.tool()
def read_workflows(names: list[str]) -> str:
    """Read one or more workflow documents. Use list_workflows first to find names.

    Args:
        names: Workflow names, e.g. ["create-new-2-compose", "slide-json-spec"]. Partial match supported.

    Returns:
        JSON with document contents.
    """
    return json.dumps(_read_workflows(names=names, skill_dir=_SKILL_DIR), ensure_ascii=False)


@mcp.tool()
def list_guides() -> str:
    """List all available guide documents (design rules, review checklists).

    Returns:
        JSON with list of guides.
    """
    return json.dumps(_list_guides(skill_dir=_SKILL_DIR), ensure_ascii=False)


@mcp.tool()
def read_guides(names: list[str]) -> str:
    """Read one or more guide documents. Use list_guides first to find names.

    Args:
        names: Guide names, e.g. ["design-rules"]. Partial match supported.

    Returns:
        JSON with document contents.
    """
    return json.dumps(_read_guides(names=names, skill_dir=_SKILL_DIR), ensure_ascii=False)


@mcp.tool()
def code_to_slide(
    code: str,
    language: str = "python",
    theme: str = "dark",
    x: int = 0,
    y: int = 0,
    width: int = 800,
    height: int = 300,
) -> str:
    """Generate slide elements JSON for a syntax-highlighted code block.

    Args:
        code: Source code text.
        language: Programming language for syntax highlighting.
        theme: Color theme ("dark" or "light").
        x: X position in pixels.
        y: Y position in pixels.
        width: Width in pixels.
        height: Height in pixels.

    Returns:
        JSON array of slide elements for the code block.
    """
    return json.dumps(
        _code_block(code=code, language=language, theme=theme, x=x, y=y, width=width, height=height),
        ensure_ascii=False,
    )


@mcp.tool()
def pptx_to_json(pptx_path: str) -> str:
    """Convert an existing PPTX file to JSON representation.
    Useful for editing existing presentations.

    Args:
        pptx_path: Path to the .pptx file.

    Returns:
        JSON representation of the PPTX slides.
    """
    return json.dumps(
        _pptx_to_json(pptx_path=pptx_path),
        ensure_ascii=False,
    )


@mcp.tool()
def run_python(code: str, deck_id: str = "", save: bool = False,
               measure_slides: list[str] | None = None, purpose: str = "") -> str:
    """Execute Python code in the deck workspace or for general computation.

    If deck_id is provided (as output_dir path), the code runs with cwd set to that directory.
    All workspace files are accessible via normal file I/O (open, read, write).

    **Always specify measure_slides when editing slides.** Runs validation after execution:
        - Text bbox measurement (overflow detection via LibreOffice SVG)

    Examples:
        Edit slides:   run_python(code="...", deck_id="/path/to/deck", save=True, measure_slides=["title"])
        Edit specs:    run_python(code="open('specs/brief.md','w').write('...')", deck_id="/path/to/deck", save=True)
        Compute:       run_python(code="print(2**100)")

    Args:
        code: Python code to execute.
        deck_id: Deck output_dir path. Optional.
        save: Unused in local mode (files are written directly). Kept for API compat.
        measure_slides: List of slide slugs to measure after execution. Requires deck_id.
        purpose: Brief description shown in UI.

    Returns:
        JSON string: {"output", "measure"?}
    """
    import os
    import subprocess
    import tempfile

    result: dict = {}

    # Determine working directory
    cwd = deck_id if deck_id and Path(deck_id).is_dir() else None

    # Execute code
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            proc = subprocess.run(
                [sys.executable, f.name],
                capture_output=True, text=True, timeout=120,
                cwd=cwd,
            )
            os.unlink(f.name)
        output = proc.stdout
        if proc.stderr:
            output += "\n" + proc.stderr
        result["output"] = output.strip()
    except subprocess.TimeoutExpired:
        result["output"] = "Error: execution timed out (120s)"
    except Exception as e:
        result["output"] = f"Error: {e}"

    # Post-processing: measure
    if cwd and measure_slides:
        try:
            json_path = str(Path(cwd) / "presentation.json")
            if Path(json_path).exists():
                pages = ",".join(measure_slides) if measure_slides else ""
                measure_result = _measure(slides_json_path=json_path, pages=pages)
                result["measure"] = measure_result
        except Exception as e:
            result["measure"] = f"Measure error: {e}"

    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def grid(spec: str, purpose: str = "") -> str:
    """Compute CSS Grid layout coordinates from a grid specification.
    Use before placing elements to calculate exact positions.

    Args:
        spec: JSON string with grid spec. Keys:
            area: {"x", "y", "w", "h"} (required)
            columns: track-list string, e.g. "1fr 2fr" (default "1fr")
            rows: track-list string (default "1fr")
            gap: str or int, e.g. "20" or "20 40" (row-gap col-gap)
            areas: 2D list of area names (optional)
            items: dict of item overrides (optional)
        purpose: Brief user-facing description (e.g. '3-column icon layout').
            Shown in the UI.

    Returns:
        JSON with named rectangles containing x, y, w, h coordinates.
    """
    from sdpm.layout.grid import compute_grid

    try:
        grid_spec = json.loads(spec)
    except (json.JSONDecodeError, TypeError) as e:
        return json.dumps({"error": f"Invalid grid spec JSON: {e}"})
    result = compute_grid(grid_spec)
    return json.dumps(result, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
