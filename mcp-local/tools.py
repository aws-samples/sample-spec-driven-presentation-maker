# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""spec-driven-presentation-maker Local MCP Tools (Layer 2).

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

Tool interface layer — defines signatures, docstrings, and delegates to Engine.
Each function is directly registrable via ``mcp.tool()(tools.xxx)``.
No AWS dependencies. No deck management (that's Layer 3).
"""

from pathlib import Path
from typing import Any

_SKILL_DIR = Path(__file__).resolve().parent.parent / "skill"
_REFERENCES_DIR = _SKILL_DIR / "references"


def init_presentation(name: str) -> dict[str, Any]:
    """Initialize a presentation workspace. Creates deck.json, slides/, and specs/.

    Call after briefing is complete, before building slides.

    Args:
        name: Presentation name (e.g. "lambda-overview").

    Returns:
        Dict with output_dir, deck_json path, and workspace file list.
    """
    from sdpm.api import init
    return init(name=name)


def analyze_template(template: str, layout: str = "") -> dict[str, Any]:
    """Analyze a PPTX template — extract layouts, theme colors, fonts.

    Args:
        template: Template name (e.g. "blank-dark") or full path.
        layout: Optional layout name for detailed placeholder info.

    Returns:
        Dict with layouts, theme_colors, fonts, and optional layout_detail.
    """
    from sdpm.analyzer import analyze_template as _analyze, get_layout_placeholders
    from sdpm.api import _find_template_in_dirs, get_templates_dirs

    if not template:
        raise FileNotFoundError("template is required.")

    path = Path(template)
    if not path.exists():
        found = _find_template_in_dirs(template, get_templates_dirs())
        if found is None:
            raise FileNotFoundError(f"Template not found: {template}")
        path = found

    result = _analyze(path)

    if layout:
        detail = get_layout_placeholders(path, layout)
        if detail:
            result["layout_detail"] = detail
        else:
            result["layout_detail_error"] = f"Layout not found: {layout}"

    return result


def generate_pptx(deck_id: str) -> dict[str, Any]:
    """Generate PPTX from deck workspace (deck.json + slides/*.json + outline.md).

    Args:
        deck_id: Deck directory path.

    Returns:
        Dict with output_path and slide summary.
    """
    from sdpm.api import generate
    from sdpm.assets import invalidate_manifest_cache
    invalidate_manifest_cache()
    return generate(
        json_path=deck_id,
        output_path=str(Path(deck_id) / "output.pptx"),
    )



def measure_slides(deck_id: str, slugs: list[str] | None = None) -> str:
    """Measure text bounding boxes in slides.

    Args:
        deck_id: Deck directory path.
        slugs: Optional list of slugs to measure. All if omitted.

    Returns:
        Measurement results as formatted string.
    """
    from sdpm.api import measure as _measure, parse_outline_slugs

    outline_path = Path(deck_id) / "specs" / "outline.md"
    all_slugs = parse_outline_slugs(outline_path) if outline_path.exists() else []
    pptx_slugs = [s for s in all_slugs if (Path(deck_id) / "slides" / f"{s}.json").exists()]

    pages: list[int] | None = None
    if slugs:
        slug_to_page = {s: i + 1 for i, s in enumerate(pptx_slugs)}
        pages = [slug_to_page[s] for s in slugs if s in slug_to_page]

    return _measure(json_path=deck_id, slides=pages)


def search_assets(
    query: str, limit: int = 20,
    source_filter: str = "", type_filter: str = "", theme_filter: str = "",
) -> dict[str, Any]:
    """Search assets (icons, images) by keyword.

    Args:
        query: Search keyword.
        limit: Max results (default 20).
        source_filter: Filter by source name.
        type_filter: Filter by asset type.
        theme_filter: Filter by theme (dark/light).

    Returns:
        Dict with query and results list.
    """
    from sdpm.assets import invalidate_manifest_cache, search_assets as _search
    invalidate_manifest_cache()
    return {
        "query": query,
        "results": _search(
            query, limit=limit,
            source_filter=source_filter or None,
            type_filter=type_filter or None,
            theme_filter=theme_filter or None,
        ),
    }


def list_asset_sources() -> dict[str, Any]:
    """List available asset sources (icon packs, image libraries).

    Returns:
        Dict with sources list.
    """
    from sdpm.assets import invalidate_manifest_cache, list_sources
    invalidate_manifest_cache()
    return {"sources": list_sources()}


def list_styles(include_all: bool = False) -> dict[str, Any]:
    """List available design styles for presentations.

    Searches user-local styles (~/.config/sdpm/styles/) and bundled styles.
    Default returns pinned + user styles only. Pass include_all=True for all.

    Returns:
        Dict with styles list (name, description, pinned, source).
    """
    from sdpm.api import get_styles_dirs, list_styles_filtered
    from sdpm.config import get_state
    styles_dirs = get_styles_dirs()
    pinned = get_state().get("pinned_styles", [])
    return {"styles": list_styles_filtered(styles_dirs, pinned, include_all)}


def apply_style(deck_id: str, style: str) -> dict[str, Any]:
    """Apply a named style to a deck's art-direction.

    Copies the style HTML to {deck_id}/specs/art-direction.html.

    Args:
        deck_id: Deck directory path.
        style: Style name (e.g. "elegant-dark").

    Returns:
        Dict with status, path, style. Or error key if not found.
    """
    from sdpm.api import apply_style as _apply_style
    return _apply_style(deck_dir=deck_id, style=style)


def list_templates() -> dict[str, Any]:
    """List available PPTX templates.

    Returns:
        Dict with templates list (name, source, description, fonts).
    """
    from sdpm.api import get_templates_dirs, list_templates_with_metadata
    from sdpm.config import get_state
    templates_dirs = get_templates_dirs()
    metadata = get_state().get("template_metadata", {})
    return {"templates": list_templates_with_metadata(templates_dirs, metadata)}


def read_examples(names: list[str]) -> dict[str, Any]:
    """Read design examples (components/patterns).

    Without specifier returns a listing of slide descriptions.

    Args:
        names: List of example names to read.

    Returns:
        Dict with documents list.
    """
    from sdpm.reference import read_docs
    return {"documents": read_docs(_REFERENCES_DIR / "examples", names)}


def list_workflows() -> dict[str, Any]:
    """List all workflow documents.

    Returns:
        Dict with items list (name, description).
    """
    from sdpm.reference import list_category
    return {"items": list_category(_REFERENCES_DIR / "workflows")}


def read_workflows(names: list[str]) -> dict[str, Any]:
    """Read workflow documents.

    Args:
        names: List of workflow names to read.

    Returns:
        Dict with documents list.
    """
    from sdpm.reference import read_docs
    return {"documents": read_docs(_REFERENCES_DIR / "workflows", names)}


def list_guides() -> dict[str, Any]:
    """List all guide documents.

    Returns:
        Dict with items list (name, description).
    """
    from sdpm.reference import list_category
    return {"items": list_category(_REFERENCES_DIR / "guides")}


def read_guides(names: list[str]) -> dict[str, Any]:
    """Read guide documents.

    Args:
        names: List of guide names to read.

    Returns:
        Dict with documents list.
    """
    from sdpm.reference import read_docs
    return {"documents": read_docs(_REFERENCES_DIR / "guides", names)}


def code_to_slide(
    deck_id: str, code: str, name: str,
    language: str = "python", theme: str = "dark",
    x: int = 0, y: int = 0, width: int = 800, height: int = 300,
) -> dict[str, Any]:
    """Generate a syntax-highlighted code block and save to deck/includes/{name}.json.

    Use the returned include_path in slide JSON as:
    {"type": "include", "src": "includes/{name}.json"}

    Args:
        deck_id: Deck directory path.
        code: Source code text.
        name: Basename for the includes file (without .json).
        language: Programming language for syntax highlighting.
        theme: Color theme ("dark" or "light").
        x: X position in pixels.
        y: Y position in pixels.
        width: Width in pixels.
        height: Height in pixels.

    Returns:
        Dict with include_path for use in slide JSON.
    """
    from sdpm.api import code_block as _code_block
    elements = _code_block(code=code, language=language, theme=theme, x=x, y=y, width=width, height=height)
    includes_dir = Path(deck_id) / "includes"
    includes_dir.mkdir(parents=True, exist_ok=True)
    include_path = includes_dir / f"{name}.json"
    import json
    include_path.write_text(json.dumps(elements, ensure_ascii=False), encoding="utf-8")
    return {
        "include_path": f"includes/{name}.json",
        "absolute_path": str(include_path),
        "element_count": len(elements),
    }


def grid(purpose: str, spec: str) -> dict[str, Any]:
    """Compute CSS Grid layout coordinates from a grid specification.

    Use before placing elements to calculate exact positions.

    Args:
        purpose: Brief description (e.g. '3-column icon layout'). Shown in UI.
        spec: JSON string with grid spec. Keys:
            area: {"x", "y", "w", "h"} (required)
            columns: track-list string, e.g. "1fr 2fr" (default "1fr")
            rows: track-list string (default "1fr")
            gap: str or int, e.g. "20" or "20 40" (row-gap col-gap)
            areas: 2D list of area names (optional)
            items: dict of item overrides (optional)

    Returns:
        Dict with named rectangles containing x, y, w, h coordinates.
    """
    import json
    from sdpm.layout.grid import compute_grid

    try:
        grid_spec = json.loads(spec)
    except (json.JSONDecodeError, TypeError) as e:
        return {"error": f"Invalid grid spec JSON: {e}"}
    return compute_grid(grid_spec)


def pptx_to_json(pptx_path: str) -> dict[str, Any]:
    """Convert an existing PPTX file to JSON representation.

    Args:
        pptx_path: Path to the PPTX file.

    Returns:
        Dict with slide data in JSON format.
    """
    from sdpm.converter import pptx_to_json as _convert
    path = Path(pptx_path)
    if not path.exists():
        raise FileNotFoundError(f"PPTX not found: {pptx_path}")
    return _convert(str(path))
