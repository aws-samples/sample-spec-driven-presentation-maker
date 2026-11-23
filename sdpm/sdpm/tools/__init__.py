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
from typing import Annotated, Any, Literal

from pydantic import Field

from sdpm.config import REFERENCES_DIR as _REFERENCES_DIR


def start_presentation() -> dict[str, Any]:
    """Start here for any slide work: a new deck, editing or importing a PPTX, restyling.
    Call it before any other sdpm tool; it returns the workflow to follow. To translate
    a deck, call start_translation instead."""
    from sdpm.entry import start_presentation as _start

    return _start()


def start_composing(
    deck_id: Annotated[str, Field(description='Deck directory path from your instruction.')] = "",
    assigned_slugs: Annotated[list[str] | None, Field(description='Slides you own; other composers write the rest in parallel.')] = None,
    mode: Annotated[Literal["pptx", "html"], Field(description='Mode from your instruction.')] = "pptx",
) -> dict[str, Any]:
    """Call this first when your instruction gives you a deck_id and assigned_slugs: you
    are a composer. Returns the composer workflow, the deck's specs and your slides.
    specs_ok=false: stop and report the errors."""
    from sdpm.entry import start_composing as _start

    return _start(deck_dir=deck_id or None, assigned_slugs=assigned_slugs, mode=mode)


def start_style(
    base: Annotated[str, Field(description='Style to start from; a bundled one when empty.')] = "",
) -> dict[str, Any]:
    """Call first to create or edit a reusable style. To restyle one deck, use
    start_presentation."""
    from sdpm.entry import start_style as _start

    return _start(base=base)


def start_translation(
    deck_id: Annotated[str, Field(description='Source deck directory path.')],
    language: Annotated[str, Field(description='Target language code or name; the new deck is <deck>-<language>.')],
) -> dict[str, Any]:
    """Call first to translate an existing deck into another language."""
    from sdpm.entry import start_translation as _start

    return _start(deck_dir=deck_id, language=language)


def init_deck_workspace(
    name: Annotated[str, Field(description='Short deck name, used in the folder name.')],
    output_format: Annotated[Literal["pptx", "html"], Field(description="html only when the user asks for an HTML deck.")] = "pptx",
) -> dict[str, Any]:
    """Create an empty deck. Call it at the step the start_presentation workflow names."""
    from sdpm.api import init
    from sdpm.entry import format_notes

    result = init(name=name, output_format=output_format)
    notes = format_notes(output_format)
    if notes:
        result["format_notes"] = notes
    return result


def check_specs(
    deck_id: Annotated[str, Field(description='Deck directory path.')],
    assigned_slugs: Annotated[list[str] | None, Field(description='Slugs you will dispatch.')] = None,
) -> dict[str, Any]:
    """Validate deck.json and specs/outline.md. Dispatch composers only when ok is true."""
    from sdpm.api import check_specs as _check_specs

    return _check_specs(deck_dir=deck_id, assigned_slugs=assigned_slugs)


def analyze_template(
    template: Annotated[str, Field(description='Template name or .pptx path.')],
    layout: Annotated[str, Field(description="Layout name, to also get its placeholders.")] = "",
) -> dict[str, Any]:
    """Layouts, theme colors, fonts and slide size of a PPTX template."""
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


def _is_html_deck(deck_id: str) -> bool:
    """True when deck.json says outputFormat html; unreadable or non-object deck.json → False.

    Raises ValueError when deck.json names an invalid outputFormat.
    """
    from sdpm.engine.schema import read_deck_format

    return read_deck_format(deck_id) == "html"


def generate_pptx(deck_id: Annotated[str, Field(description='Deck directory path.')]) -> dict[str, Any]:
    """Build output.pptx. run_python already rebuilds after each edit; call this only for
    an explicit full build."""
    if _is_html_deck(deck_id):
        return {
            "output_format": "html",
            "message": "This deck is an HTML deck: no PPTX is built. run_python rebuilds output.html after every change.",
        }
    from sdpm.api import generate
    from sdpm.knowledge.assets import invalidate_manifest_cache

    invalidate_manifest_cache()
    return generate(
        json_path=deck_id,
        output_path=str(Path(deck_id) / "output.pptx"),
    )


def search_assets(
    query: Annotated[str, Field(description='Keyword; empty lists the sources.')] = "",
    limit: Annotated[int, Field(description='Max results.')] = 20,
    source_filter: Annotated[str, Field(description='Only this source.')] = "",
    type_filter: Annotated[str, Field(description='Only this asset type.')] = "",
    theme_filter: Annotated[str, Field(description='dark or light.')] = "",
) -> dict[str, Any]:
    """Search icons and images. An empty query lists the sources with their types and
    themes."""
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
    include_all: Annotated[bool, Field(description='Describe every style, not only the pinned and the user\'s own.')] = False,
) -> dict[str, Any]:
    """List design styles to choose one for apply_style."""
    from sdpm.api import get_styles_dirs, list_styles_listing
    from sdpm.config import get_state

    styles_dirs = get_styles_dirs()
    pinned = get_state().get("pinned_styles", [])
    return list_styles_listing(styles_dirs, pinned, include_all)


def apply_style(
    deck_id: Annotated[str, Field(description='Deck directory path.')],
    style: Annotated[str, Field(description='Style name from list_styles.')],
    template: Annotated[str, Field(description='Template name.')] = "",
) -> dict[str, Any]:
    """Apply a style, and optionally a template, to a deck: writes specs/art-direction.html
    and fills deck.json."""
    from sdpm.api import apply_style as _apply_style

    return _apply_style(deck_dir=deck_id, style=style, template=template)


def list_templates() -> dict[str, Any]:
    """List PPTX templates. start_presentation already returns this list."""
    from sdpm.api import get_templates_dirs, list_templates_with_metadata
    from sdpm.config import get_builtin_template_notes, get_state

    templates_dirs = get_templates_dirs()
    metadata = get_state().get("template_metadata", {})
    return {"templates": list_templates_with_metadata(templates_dirs, metadata, get_builtin_template_notes())}


def read_guides(
    names: Annotated[list[str], Field(description='Guide names.')],
) -> dict[str, Any]:
    """Read guide documents."""
    from sdpm.knowledge.reference import read_docs

    return {"documents": read_docs(_REFERENCES_DIR / "guides", names)}


def code_to_slide(
    deck_id: Annotated[str, Field(description='Deck directory path.')],
    code: Annotated[str, Field(description='Source code.')],
    name: Annotated[str, Field(description='File name without .json.')],
    language: Annotated[str, Field(description='Language for highlighting.')] = "python",
    theme: Annotated[str, Field(description='dark or light.')] = "dark",
    x: Annotated[int, Field(description='Left edge, px.')] = 0,
    y: Annotated[int, Field(description='Top edge, px.')] = 0,
    width: Annotated[int, Field(description='Width, px.')] = 800,
    height: Annotated[int, Field(description='Height, px.')] = 300,
) -> dict[str, Any]:
    """Save code as a syntax-highlighted block in includes/<name>.json. Put it on a slide
    as {"type": "include", "src": "includes/<name>.json"}."""
    if _is_html_deck(deck_id):
        return {"error": "code_to_slide emits PPTX elements; in HTML decks write <pre><code> instead."}
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
    spec: Annotated[str, Field(description='JSON: area {x,y,w,h}, columns, rows, gap; optional areas, items.')],
) -> dict[str, Any]:
    """Compute exact x/y/w/h for rows and columns from a CSS-Grid-like spec, instead of
    placing boxes by hand. Syntax: read_guides(["grid"])."""
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
    spec: Annotated[str, Field(description='Diagram JSON: direction, iconSize, children, connections.')],
    x: Annotated[int, Field(description='Area left edge, px.')] = 100,
    y: Annotated[int, Field(description='Area top edge, px.')] = 180,
    width: Annotated[int, Field(description='Area width, px; the diagram scales to fit.')] = 1720,
    height: Annotated[int, Field(description='Area height, px.')] = 800,
    theme: Annotated[str, Field(description='Slide background, dark or light.')] = "dark",
    pt_per_px: Annotated[float, Field(description='deck.json slideSize.ptPerPx.')] = 0.5,
) -> dict[str, Any]:
    """Lay out an architecture or flow diagram from groups, nodes and connections; returns
    placed slide elements and layout warnings. Schema:
    read_guides(["arch-layout-engine", "arch-elements"])."""
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
read_guides.__doc__ = "Read guides by name: " + ", ".join(_guide_names()) + "."
