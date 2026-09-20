# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""sdpm.tools — MCP tool contract (single definition for all servers).

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

Tool interface layer — defines names, signatures, docstrings, and delegates
to the engine (:mod:`sdpm.engine`) and knowledge (:mod:`sdpm.knowledge`)
layers. Each function is directly registrable via ``mcp.tool()(tools.xxx)``.

Filesystem-workspace based: ``deck_id`` is a local directory path. Servers
whose decks live elsewhere (e.g. S3) materialize a workspace first, or bind
their own infrastructure-specific variants.
"""

from pathlib import Path
from typing import Any

from sdpm.config import REFERENCES_DIR as _REFERENCES_DIR


def init_presentation(name: str) -> dict[str, Any]:
    """Initialize a presentation workspace. Creates deck.json, slides/, and specs/.

    Call after briefing is complete, before applying a template and style with
    apply_style and building slides.

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
        Dict with layouts, theme_colors, fonts, slide_size, and optional layout_detail.
        slide_size is {"width": 1920, "height": H, "ptPerPx": P} where H depends on
        the template's aspect ratio (e.g. 1080 for 16:9, 1440 for 4:3). Width is
        always 1920px. ptPerPx is the pt-to-px conversion ratio (0.5 for 16:9,
        0.375 for 4:3) — copy it into deck.json slideSize for arch_diagram to use.
    """
    from sdpm.engine.analyzer import analyze_template as _analyze, get_layout_placeholders
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
    from sdpm.knowledge.assets import invalidate_manifest_cache

    invalidate_manifest_cache()
    return generate(
        json_path=deck_id,
        output_path=str(Path(deck_id) / "output.pptx"),
    )


def search_assets(
    query: str = "",
    limit: int = 20,
    source_filter: str = "",
    type_filter: str = "",
    theme_filter: str = "",
) -> dict[str, Any]:
    """Search assets (icons, images) by keyword, or discover available sources.

    Discovery mode: call with query="" (empty string) to get a listing of all
    available asset sources with their item counts — useful for understanding
    what icon packs and image libraries are available before searching.

    Args:
        query: Search keyword. Empty string triggers discovery mode.
        limit: Max results (default 20). Ignored in discovery mode.
        source_filter: Filter by source name.
        type_filter: Filter by asset type.
        theme_filter: Filter by theme (dark/light).

    Returns:
        Dict with query and results list. In discovery mode, returns
        {query: "", sources: [{name, count, types, themes}]}.
    """
    from sdpm.knowledge.assets import invalidate_manifest_cache, search_assets as _search, list_sources

    invalidate_manifest_cache()

    if not query.strip():
        return {"query": "", "sources": list_sources()}

    return {
        "query": query,
        "results": _search(
            query,
            limit=limit,
            source_filter=source_filter or None,
            type_filter=type_filter or None,
            theme_filter=theme_filter or None,
        ),
    }


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


def apply_style(
    deck_id: str,
    style: str,
    template: str = "",
) -> dict[str, Any]:
    """Apply a named style and optional template to a deck.

    Writes specs/art-direction.html and completes deck.json (template, defaultTextColor, fonts, slideSize).

    Args:
        deck_id: Deck directory path.
        style: Style name (e.g. "elegant-dark").
        template: Optional template name, with or without the .pptx extension.

    Returns:
        Dict with status, path, style, changed deck.json fields under updated, and
        missing — deck.json fields the style/template could not fill (e.g. defaultTextColor
        when the style has no --color-text); set them yourself before composing.
    """
    from sdpm.api import apply_style as _apply_style

    return _apply_style(deck_dir=deck_id, style=style, template=template)


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
    """Read design examples (components and styles).

    Names: "components/all" (the component vocabulary) or "styles/<style-name>".

    Args:
        names: List of example names to read.

    Returns:
        Dict with documents list.
    """
    from sdpm.knowledge.reference import read_docs

    return {"documents": read_docs(_REFERENCES_DIR / "examples", names)}


def list_workflows() -> dict[str, Any]:
    """List all role workflow and presentation specification documents.

    Returns:
        Dict with items list (name, description).
    """
    from sdpm.knowledge.reference import list_category

    items = list_category(_REFERENCES_DIR / "workflows")
    seen = {item["name"] for item in items}
    items.extend(item for item in list_category(_REFERENCES_DIR / "spec") if item["name"] not in seen)
    return {"items": items}


def read_workflows(names: list[str]) -> dict[str, Any]:
    """Read role workflows and presentation specifications.

    To create slides, read orchestrator first.

    - orchestrator: build a deck from material or dialogue.
    - composer: write assigned slides from approved specs.
    - style: create a reusable style guide.
    - translate: derive a translated deck.

    Args:
        names: List of workflow or specification names to read.

    Returns:
        Dict with documents list.
    """
    from sdpm.knowledge.reference import read_docs

    documents = []
    directories = (_REFERENCES_DIR / "workflows", _REFERENCES_DIR / "spec")
    for name in names:
        errors = []
        for directory in directories:
            try:
                documents.extend(read_docs(directory, [name]))
                break
            except FileNotFoundError as error:
                errors.append(error)
        else:
            raise errors[0]
    return {"documents": documents}


def list_guides() -> dict[str, Any]:
    """List all guide documents.

    Returns:
        Dict with items list (name, description).
    """
    from sdpm.knowledge.reference import list_category

    return {"items": list_category(_REFERENCES_DIR / "guides")}


def read_guides(names: list[str]) -> dict[str, Any]:
    """Read guide documents.

    Args:
        names: List of guide names to read.

    Returns:
        Dict with documents list.
    """
    from sdpm.knowledge.reference import read_docs

    return {"documents": read_docs(_REFERENCES_DIR / "guides", names)}


def code_to_slide(
    deck_id: str,
    code: str,
    name: str,
    language: str = "python",
    theme: str = "dark",
    x: int = 0,
    y: int = 0,
    width: int = 800,
    height: int = 300,
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
            columns: track-list string, e.g. "1fr 2fr" (default "1fr").
                Supported syntax: fr, px, %, repeat(n, X), or bare integer.
                auto and minmax() are NOT supported.
            rows: track-list string (default "1fr"). Same syntax as columns.
            gap: str or int, e.g. "20" or "20 40" (row-gap col-gap)
            areas: 2D list of area names (optional)
            items: dict of item overrides (optional)

    Returns:
        Dict with named rectangles containing x, y, w, h coordinates,
        or {"error": "..."} if the spec is invalid.
    """
    import json
    from sdpm.engine.layout.grid import compute_grid

    try:
        grid_spec = json.loads(spec)
    except (json.JSONDecodeError, TypeError) as e:
        return {"error": f"Invalid grid spec JSON: {e}"}
    try:
        return compute_grid(grid_spec)
    except (ValueError, KeyError) as e:
        return {"error": str(e)}


def arch_diagram(
    spec: str,
    x: int = 100,
    y: int = 180,
    width: int = 1720,
    height: int = 800,
    theme: str = "dark",
    pt_per_px: float = 0.5,
) -> dict[str, Any]:
    """Auto-layout an architecture/flow diagram from a logical-structure JSON.

    You describe what connects to what; the engine places nodes, routes orthogonal
    arrows and returns placed slide elements. The JSON schema is in the guide
    `arch-layout-engine` (read_guides).

    Args:
        spec: JSON string. Top-level keys: `direction` ("horizontal"/"vertical"),
            `iconSize`, `children` (nested nodes/groups), `connections`
            (`{from, to, label?, fan?}`). A `targetArea` object inside the JSON
            overrides x/y/width/height.
        x: Target area X offset in px.
        y: Target area Y offset in px.
        width: Target area width in px (the diagram is scaled to fit).
        height: Target area height in px.
        theme: "dark" or "light" — box-node text colors.
        pt_per_px: deck.json `slideSize.ptPerPx` (16:9 = 0.5, 4:3 = 0.375). The
            text-height estimate assumes 16:9 when omitted.

    Returns:
        Dict with:
          - `elements`: sdpm element array — place in a slide directly, or write to a
            file and reference with `{"type": "include", "src": "..."}`.
          - `bbox`: final bounding box after scale-to-fit.
          - `warnings`: layout defects in words; absent when clean.
          - `metrics`: `crossings` / `pierces` / `group_pierces` are 0 for a clean
            diagram; `overflow` > 0 means the layout spills off the target box;
            `score` is the judge's lexicographic tuple (lower is better).
    """
    import json
    from sdpm.engine.layout.render import render_architecture

    try:
        tree = json.loads(spec)
    except (json.JSONDecodeError, TypeError) as e:
        return {"error": f"Invalid diagram spec JSON: {e}"}
    return render_architecture(
        tree,
        x=x,
        y=y,
        width=width,
        height=height,
        theme=theme,
        include_metrics=True,
        pt_per_px=pt_per_px,
    )


def diff_pptx(baseline: str, edited: str) -> dict[str, Any]:
    """Compare a deck with a hand-edited PPTX and report the changes.

    Use for hand-edit sync (guide `hand-edit-sync`): the user edited the generated PPTX
    in PowerPoint and asks for further changes. Apply the reported hand-edits
    to the deck's slide JSON before editing/regenerating — otherwise they are
    lost on the next generate_pptx.

    Args:
        baseline: Deck directory (deck.json + slides/), slides JSON, or PPTX.
        edited: The hand-edited PPTX (or deck directory / slides JSON).

    Returns:
        Dict with has_diff (bool) and report (per-slide changed / added /
        removed elements and properties).
    """
    from sdpm.api import diff_report

    for p in (baseline, edited):
        if not Path(p).exists():
            raise FileNotFoundError(f"Not found: {p}")
    return diff_report(baseline, edited)
