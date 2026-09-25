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
from typing import Annotated, Any

from pydantic import Field

from sdpm.config import REFERENCES_DIR as _REFERENCES_DIR


def start_presentation() -> dict[str, Any]:
    """Start here for anything about slides — a new deck, editing or importing a PPTX,
    restyling a deck. Call it before any other sdpm tool.

    Returns the orchestrator role document (how to run the work end to end) plus what
    it needs first: available styles, PPTX templates, and the output directory.
    To translate an existing deck into another language, call start_translation instead.
    """
    from sdpm.entry import start_presentation as _start

    return _start()


def start_composing(
    deck_id: Annotated[str, Field(description='Deck directory path, as given in your instruction.')] = "",
    assigned_slugs: Annotated[list[str] | None, Field(description='The slugs you own. Other slides belong to other composers running in parallel.')] = None,
) -> dict[str, Any]:
    """Composer entry. You are a composer when your instruction gives you a deck_id and
    assigned_slugs — call this first with those values.

    Validates the specs, then returns the composer role document, the slide JSON spec,
    and everything the deck gives you: deck.json, brief, outline, art direction, template
    analysis, which slides exist, and the JSON of your assigned slides (plus any
    override-group head they inherit from, marked read-only). specs_ok=false with
    errors means stop and report.
    """
    from sdpm.entry import start_composing as _start

    return _start(deck_dir=deck_id or None, assigned_slugs=assigned_slugs)


def start_style(
    base: Annotated[str, Field(description='Existing style to use as the skeleton; a bundled default when omitted.')] = "",
) -> dict[str, Any]:
    """Call first when asked to create or edit a reusable style guide. (To restyle one
    deck, that is apply_style inside the start_presentation workflow.)

    Returns the style role document, the style catalogue, and one style's HTML to imitate.
    """
    from sdpm.entry import start_style as _start

    return _start(base=base)


def start_translation(
    deck_id: Annotated[str, Field(description='Source deck directory path.')],
    language: Annotated[str, Field(description='Target language code or name; becomes the -<lang> suffix of the sibling deck.')],
) -> dict[str, Any]:
    """Call first when asked to translate an existing deck into another language.

    Returns the translate role document, the slide JSON spec, and the source deck's shape
    (deck.json, existing slides, the sibling deck path the variant will use).
    """
    from sdpm.entry import start_translation as _start

    return _start(deck_dir=deck_id, language=language)


def init_deck_workspace(
    name: Annotated[str, Field(description='Presentation name, e.g. "lambda-overview".')],
) -> dict[str, Any]:
    """Create an empty deck workspace (deck.json, slides/, specs/). A step inside the
    orchestrator workflow — after the brief is agreed, before apply_style — not where a
    request starts; start_presentation is.
    """
    from sdpm.api import init

    return init(name=name)


def check_specs(
    deck_id: Annotated[str, Field(description='Deck directory path.')],
    assigned_slugs: Annotated[list[str] | None, Field(description='Slugs about to be dispatched; each must exist in the outline.')] = None,
) -> dict[str, Any]:
    """Validate deck.json and specs/outline.md before dispatching composers; ok=false means
    do not dispatch. Checks deck metadata, outline format and fields, TBD markers and the
    assigned slugs. Composers run the same check inside start_composing.
    """
    from sdpm.api import check_specs as _check_specs

    return _check_specs(deck_dir=deck_id, assigned_slugs=assigned_slugs)


def analyze_template(
    template: Annotated[str, Field(description='Template name (e.g. "blank-dark") or path to a .pptx.')],
    layout: Annotated[str, Field(description="A layout name, to also get that layout's placeholders.")] = "",
) -> dict[str, Any]:
    """Layouts, theme colors, fonts and slide size of a PPTX template. slide_size.ptPerPx
    belongs in deck.json slideSize (arch_diagram reads it).
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


def generate_pptx(deck_id: Annotated[str, Field(description='Deck directory path.')]) -> dict[str, Any]:
    """Build output.pptx from the deck workspace (deck.json + slides/*.json). run_python
    already rebuilds after edits; use this for an explicit full build.
    """
    from sdpm.api import generate
    from sdpm.knowledge.assets import invalidate_manifest_cache

    invalidate_manifest_cache()
    return generate(
        json_path=deck_id,
        output_path=str(Path(deck_id) / "output.pptx"),
    )


def search_assets(
    query: Annotated[str, Field(description='Keyword. Empty string lists the available sources instead.')] = "",
    limit: Annotated[int, Field(description='Max results.')] = 20,
    source_filter: Annotated[str, Field(description='Only this source (icon pack / image library).')] = "",
    type_filter: Annotated[str, Field(description='Only this asset type.')] = "",
    theme_filter: Annotated[str, Field(description='dark or light.')] = "",
) -> dict[str, Any]:
    """Search icons and images by keyword. With an empty query, lists the available sources
    (icon packs, image libraries) with counts, types and themes.
    """
    from sdpm.knowledge.assets import (
        AssetsNotInstalledError,
        invalidate_manifest_cache,
        list_sources,
        search_assets as _search,
    )
    from sdpm.knowledge.assets.download import install_status

    invalidate_manifest_cache()

    try:
        if not query.strip():
            sources = list_sources()
            if not sources:
                raise AssetsNotInstalledError()
            return {"query": "", "sources": sources}
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
    except AssetsNotInstalledError as error:
        status = install_status()
        if status["state"] == "running":
            hint = "Icon catalogs are being installed in the background; retry in a moment."
        else:
            hint = f"Icon catalogs are not installed. Run: {error.install_command}"
        return {
            "query": query,
            "results": [],
            "sources": [],
            "assets_installed": False,
            "install_status": status,
            "error": hint,
        }


def list_styles(
    include_all: Annotated[bool, Field(description='Include styles hidden by the pin filter.')] = False,
) -> dict[str, Any]:
    """List design styles — pinned and user styles by default, everything with
    include_all. Names go to apply_style. start_presentation and start_style already
    return this list.
    """
    from sdpm.api import get_styles_dirs, list_styles_listing
    from sdpm.config import get_state

    styles_dirs = get_styles_dirs()
    pinned = get_state().get("pinned_styles", [])
    return list_styles_listing(styles_dirs, pinned, include_all)


def apply_style(
    deck_id: Annotated[str, Field(description='Deck directory path.')],
    style: Annotated[str, Field(description='Style name, e.g. "report".')],
    template: Annotated[str, Field(description='Template name, with or without .pptx.')] = "",
) -> dict[str, Any]:
    """Apply a style (and optionally a template) to a deck: writes specs/art-direction.html
    and completes deck.json (template, defaultTextColor, fonts, slideSize). Returns what
    was written, which fields changed and where each value came from — fix anything
    wrong in deck.json with run_python — and style_toc, a line-numbered map of the
    style file for reading the parts you need with run_python read_text.
    """
    from sdpm.api import apply_style as _apply_style

    return _apply_style(deck_dir=deck_id, style=style, template=template)


def list_templates() -> dict[str, Any]:
    """List available PPTX templates (name, source, description, fonts).
    start_presentation already returns this list.
    """
    from sdpm.api import get_templates_dirs, list_templates_with_metadata
    from sdpm.config import get_state

    templates_dirs = get_templates_dirs()
    metadata = get_state().get("template_metadata", {})
    return {"templates": list_templates_with_metadata(templates_dirs, metadata)}


def read_guides(
    names: Annotated[list[str], Field(description='Guide names to read.')],
) -> dict[str, Any]:
    """Read guide documents."""
    from sdpm.knowledge.reference import read_docs

    return {"documents": read_docs(_REFERENCES_DIR / "guides", names)}


def code_to_slide(
    deck_id: Annotated[str, Field(description='Deck directory path.')],
    code: Annotated[str, Field(description='Source code text.')],
    name: Annotated[str, Field(description='Basename of the includes file, without .json.')],
    language: Annotated[str, Field(description='Language for syntax highlighting.')] = "python",
    theme: Annotated[str, Field(description='dark or light.')] = "dark",
    x: Annotated[int, Field(description='Left edge in px.')] = 0,
    y: Annotated[int, Field(description='Top edge in px.')] = 0,
    width: Annotated[int, Field(description='Width in px.')] = 800,
    height: Annotated[int, Field(description='Height in px.')] = 300,
) -> dict[str, Any]:
    """Render source code as a syntax-highlighted block saved to deck/includes/<name>.json.
    Reference it from a slide as {"type": "include", "src": "includes/<name>.json"}.
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


def grid(
    purpose: Annotated[str, Field(description='One line on what the layout is for (shown in the UI).')],
    spec: Annotated[str, Field(description='JSON string: {"area": {x,y,w,h}, "columns", "rows", "gap", "areas"?, "items"?} — syntax in the grid guide.')],
) -> dict[str, Any]:
    """Compute exact x/y/w/h for a row × column layout from a CSS-Grid style spec; use it
    instead of hand-placing rectangular arrangements. Syntax and examples:
    read_guides(["grid"]).
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
    spec: Annotated[str, Field(description='Logical-structure JSON: direction, iconSize, children (nodes/groups), connections — schema in the arch-layout-engine guide.')],
    x: Annotated[int, Field(description='Target area left edge in px.')] = 100,
    y: Annotated[int, Field(description='Target area top edge in px.')] = 180,
    width: Annotated[int, Field(description='Target area width in px (diagram is scaled to fit).')] = 1720,
    height: Annotated[int, Field(description='Target area height in px.')] = 800,
    theme: Annotated[str, Field(description='dark or light — box-node text colors.')] = "dark",
    pt_per_px: Annotated[float, Field(description='deck.json slideSize.ptPerPx (16:9 = 0.5, 4:3 = 0.375).')] = 0.5,
) -> dict[str, Any]:
    """Auto-layout an architecture or flow diagram: you describe groups, nodes and
    connections; the engine places nodes, routes arrows and returns slide elements plus
    layout metrics and warnings (0 crossings / pierces = clean). Schema and technique:
    read_guides(["arch-layout-engine", "arch-elements"]).
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


def _guide_names() -> list[str]:
    from sdpm.knowledge.reference import list_category

    return [item["name"] for item in list_category(_REFERENCES_DIR / "guides")]


# The guide catalogue is small and bundled, so it rides in the tool description
# instead of costing a list call.
read_guides.__doc__ = (
    "Read guide documents — focused references to load when a slide or step calls for one. "
    "Guides: " + ", ".join(_guide_names()) + "."
)
