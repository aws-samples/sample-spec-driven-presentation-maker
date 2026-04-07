# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""spec-driven-presentation-maker Local MCP Tools (Layer 2).

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

Thin wrappers around sdpm high-level APIs for local filesystem usage.
No AWS dependencies. No deck management (that's Layer 3).
"""

import json
from pathlib import Path
from typing import Any


def init_presentation(name: str, template: str, skill_dir: Path) -> dict[str, Any]:
    """Create a presentation workspace."""
    from sdpm.api import init
    return init(name=name, template=template or None)


def analyze_template(template_path: str, skill_dir: Path, layout: str = "") -> dict[str, Any]:
    """Analyze a PPTX template to extract layouts, colors, fonts."""
    from sdpm.analyzer import analyze_template as _analyze, get_layout_placeholders

    if not template_path:
        raise FileNotFoundError("template_path is required.")

    path = Path(template_path)
    if not path.exists():
        path = skill_dir / "templates" / f"{template_path}.pptx"
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    result = _analyze(path)

    if layout:
        detail = get_layout_placeholders(path, layout)
        if detail:
            result["layout_detail"] = detail
        else:
            result["layout_detail_error"] = f"Layout not found: {layout}"

    return result


def generate_pptx(
    slides_json_path: str, skill_dir: Path,
    template: str = "", output_path: str = "",
) -> dict[str, Any]:
    """Generate PPTX from a JSON file with full post-processing."""
    from sdpm.api import generate
    return generate(
        json_path=slides_json_path,
        template=template or None,
        output_path=output_path or None,
    )


def preview(pptx_path: str, pages: str = "") -> dict[str, Any]:
    """Generate PNG previews of a PPTX file."""
    from sdpm.api import preview as _preview

    path = Path(pptx_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"PPTX not found: {pptx_path}")

    pages_list = [int(p.strip()) for p in pages.split(",") if p.strip()] if pages else None
    return _preview(pptx_path=path, pages=pages_list)


def search_assets(
    query: str, skill_dir: Path, limit: int = 20,
    source_filter: str = "", type_filter: str = "", theme_filter: str = "",
) -> dict[str, Any]:
    """Search assets by keyword."""
    from sdpm.assets import search_assets as _search
    return {
        "query": query,
        "results": _search(
            query, limit=limit,
            source_filter=source_filter or None,
            type_filter=type_filter or None,
            theme_filter=theme_filter or None,
        ),
    }


def list_asset_sources(skill_dir: Path) -> dict[str, Any]:
    """List available asset sources."""
    from sdpm.assets import list_sources
    return {"sources": list_sources()}


def list_styles(skill_dir: Path) -> dict[str, Any]:
    """List available design styles."""
    from sdpm.reference import list_styles as _list_styles
    styles_dir = skill_dir / "references" / "examples" / "styles"
    return {"styles": _list_styles(styles_dir)}


def read_examples(names: list[str], skill_dir: Path) -> dict[str, Any]:
    """Read design examples."""
    from sdpm.reference import read_docs
    return {"documents": read_docs(skill_dir / "references" / "examples", names)}


def list_workflows(skill_dir: Path) -> dict[str, Any]:
    """List all workflow documents."""
    from sdpm.reference import list_category
    return {"items": list_category(skill_dir / "references" / "workflows")}


def read_workflows(names: list[str], skill_dir: Path) -> dict[str, Any]:
    """Read workflow documents."""
    from sdpm.reference import read_docs
    return {"documents": read_docs(skill_dir / "references" / "workflows", names)}


def list_guides(skill_dir: Path) -> dict[str, Any]:
    """List all guide documents."""
    from sdpm.reference import list_category
    return {"items": list_category(skill_dir / "references" / "guides")}


def read_guides(names: list[str], skill_dir: Path) -> dict[str, Any]:
    """Read guide documents."""
    from sdpm.reference import read_docs
    return {"documents": read_docs(skill_dir / "references" / "guides", names)}


def code_block(
    code: str, language: str = "python", theme: str = "dark",
    x: int = 0, y: int = 0, width: int = 800, height: int = 300,
) -> list[dict[str, Any]]:
    """Generate slide elements for a syntax-highlighted code block."""
    from sdpm.api import code_block as _code_block
    return _code_block(code=code, language=language, theme=theme, x=x, y=y, width=width, height=height)


def pptx_to_json(pptx_path: str) -> dict[str, Any]:
    """Convert PPTX to JSON representation."""
    from sdpm.converter import pptx_to_json as _convert
    path = Path(pptx_path)
    if not path.exists():
        raise FileNotFoundError(f"PPTX not found: {pptx_path}")
    return _convert(str(path))
