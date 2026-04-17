# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""ACP-specific MCP server entry point (thick version).

Extends the base server.py with tools needed for the desktop app (ACP bridge):
- run_python: subprocess execution + PPTX build + preview + SVG compose
- list_styles override: no browser opening

Usage:
    uv run python server_acp.py
    # or in .kiro/agents/*.json: {"command": "uv", "args": ["run", "--directory", "mcp-local", "python", "server_acp.py"]}
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Import the base server — registers all standard tools on `mcp`
from server import mcp, _SKILL_DIR  # noqa: F401
from tools import (  # noqa: E402
    generate_pptx as _generate_pptx,
    preview as _preview,
    measure as _measure,
)

# ---------------------------------------------------------------------------
# Override instructions for ACP (desktop app) usage
# ---------------------------------------------------------------------------
_ACP_INSTRUCTIONS = """spec-driven-presentation-maker: AI-powered PowerPoint generation from JSON.

## Architecture
- The agent edits workspace files via `run_python(deck_id=..., save=True)` using normal file I/O
- MCP tools handle: workflow guidance, initialization, PPTX generation, preview, references
- MCP tools do NOT handle: slide editing, spec writing (agent responsibility via run_python)

**Critical constraint:** Do NOT make any decisions about slide structure, content, design, or layout before loading the workflow. The workflow files contain the full process including briefing, outline, and art direction. Wait until the workflow is loaded and follow it step by step.

## Workflow: New Presentation

→ Read `read_workflows(["create-new-1-briefing"])` to start. Follow each file's Next Step from there.
"""

mcp._mcp_server.instructions = _ACP_INSTRUCTIONS

# ---------------------------------------------------------------------------
# Override list_styles: no browser opening in ACP mode
# ---------------------------------------------------------------------------
# Remove the base version and re-register without open_styles_gallery
mcp._tool_manager._tools.pop("list_styles", None)


@mcp.tool()
def list_styles() -> str:
    """List available design styles for presentations.

    Returns:
        JSON with list of styles (name + description).
    """
    from sdpm.reference import list_styles as _list_styles
    styles_dir = _SKILL_DIR / "references" / "examples" / "styles"
    return json.dumps({"styles": _list_styles(styles_dir)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Override tools to match mcp-server (Web) signatures for subagent-branch parity.
# ACP uses deck_id = filesystem path (vs Web's UUID).
# ---------------------------------------------------------------------------
for _name in ("generate_pptx", "get_preview", "code_to_slide", "pptx_to_json", "analyze_template"):
    mcp._tool_manager._tools.pop(_name, None)


@mcp.tool()
def generate_pptx(deck_id: str) -> str:
    """Generate PPTX from deck workspace (deck.json + slides/*.json + outline.md).

    Args:
        deck_id: Deck directory path.

    Returns:
        JSON with output_path and slide summary.
    """
    from tools import generate_pptx as _gen
    return json.dumps(
        _gen(slides_json_path=deck_id, output_path=str(Path(deck_id) / "output.pptx"), skill_dir=_SKILL_DIR),
        ensure_ascii=False,
    )


@mcp.tool()
def get_preview(deck_id: str, slide_numbers: list[int] | None = None) -> str:
    """Generate PNG previews of slides.

    Args:
        deck_id: Deck directory path.
        slide_numbers: 1-based slide numbers to preview. None/empty for all.

    Returns:
        JSON with generated PNG file paths.
    """
    from tools import preview as _prev
    pages = ",".join(str(n) for n in (slide_numbers or []))
    pptx_out = str(Path(deck_id) / "output.pptx")
    return json.dumps(_prev(slides_json_path=deck_id, pages=pages, output_path=pptx_out), ensure_ascii=False)


@mcp.tool()
def code_to_slide(
    deck_id: str, code: str, name: str,
    language: str = "python", theme: str = "dark",
    x: int = 0, y: int = 0, width: int = 800, height: int = 300,
) -> str:
    """Generate a code block JSON and save to deck/includes/{name}.json.

    Use the returned include_path in slide JSON as ``{"type": "include", "src": "includes/{name}.json"}``.

    Args:
        deck_id: Deck directory path.
        code: Source code text.
        name: Basename for the includes file (without .json extension).
        language: Programming language for syntax highlighting.
        theme: Color theme ("dark" or "light").
        x: X position in pixels.
        y: Y position in pixels.
        width: Width in pixels.
        height: Height in pixels.

    Returns:
        JSON with include_path for use in slide JSON.
    """
    from tools import code_block as _code
    elements = _code(code=code, language=language, theme=theme, x=x, y=y, width=width, height=height)
    includes_dir = Path(deck_id) / "includes"
    includes_dir.mkdir(parents=True, exist_ok=True)
    include_path = includes_dir / f"{name}.json"
    include_path.write_text(json.dumps(elements, ensure_ascii=False), encoding="utf-8")
    return json.dumps({
        "include_path": f"includes/{name}.json",
        "absolute_path": str(include_path),
        "element_count": len(elements),
    }, ensure_ascii=False)


@mcp.tool()
def pptx_to_json(pptx_path: str) -> str:
    """Convert an existing PPTX file to JSON representation.

    Args:
        pptx_path: Local path to the .pptx file.

    Returns:
        JSON representation of the PPTX slides.
    """
    from tools import pptx_to_json as _conv
    return json.dumps(_conv(pptx_path=pptx_path), ensure_ascii=False)


@mcp.tool()
def analyze_template(template: str, layout: str = "") -> str:
    """Analyze a PPTX template — extract layouts, theme colors, fonts.

    Args:
        template: Template name (e.g. "sample_template_dark") or full path.
        layout: Optional layout name/index for detailed placeholder info.

    Returns:
        JSON with layouts, theme colors, fonts, and optional layout_detail.
    """
    from tools import analyze_template as _at
    return json.dumps(
        _at(template_path=template, layout=layout, skill_dir=_SKILL_DIR),
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Override init_presentation for subagent-branch deck format (deck.json + slides/)
# ---------------------------------------------------------------------------
mcp._tool_manager._tools.pop("init_presentation", None)


@mcp.tool()
def init_presentation(name: str, template: str = "") -> str:
    """Initialize a presentation workspace (deck.json + slides/ + specs/ format).

    Creates:
        deck.json             — metadata (template, fonts, defaultTextColor)
        slides/               — empty directory for slides/{slug}.json
        specs/brief.md        — empty
        specs/outline.md      — empty
        specs/art-direction.html — empty

    Args:
        name: Presentation name (used in directory name).
        template: Optional template name (e.g. "blank-dark") or path.

    Returns:
        JSON with output_dir, deck_json path, template info.
    """
    from datetime import datetime
    from sdpm.analyzer import extract_fonts

    base_dir = Path.home() / "Documents" / "SDPM-Presentations"
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    dir_name = f"{ts}-{name}" if name else ts
    out_dir = base_dir / dir_name
    out_dir.mkdir(parents=True, exist_ok=True)

    deck_data: dict = {}
    if template:
        templates_dir = _SKILL_DIR / "templates"
        template_src = Path(template).expanduser()
        if not template_src.exists():
            candidate = templates_dir / (template if template.endswith(".pptx") else f"{template}.pptx")
            if candidate.exists():
                template_src = candidate
        if template_src.exists():
            deck_data["template"] = template_src.name
            try:
                deck_data["fonts"] = extract_fonts(template_src.resolve())
            except Exception:
                pass

    (out_dir / "deck.json").write_text(json.dumps(deck_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "slides").mkdir(exist_ok=True)
    specs_dir = out_dir / "specs"
    specs_dir.mkdir(exist_ok=True)
    for fname in ("brief.md", "outline.md", "art-direction.html"):
        (specs_dir / fname).touch()

    return json.dumps({
        "output_dir": str(out_dir),
        "deck_json": str(out_dir / "deck.json"),
        "template": deck_data.get("template", ""),
        "fonts": deck_data.get("fonts", {}),
        "workspace": ["deck.json", "slides/", "specs/brief.md", "specs/outline.md", "specs/art-direction.html"],
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# ACP-only tools
# ---------------------------------------------------------------------------
@mcp.tool()
def apply_style(deck_id: str, style: str) -> str:
    """Copy a style HTML file to the deck's specs/art-direction.html.

    Args:
        deck_id: Deck output_dir path.
        style: Style name (e.g. "elegant-dark").

    Returns:
        JSON with status and the copied file path.
    """
    import shutil
    styles_dir = _SKILL_DIR / "references" / "examples" / "styles"
    src = styles_dir / f"{style}.html"
    if not src.exists():
        return json.dumps({"error": f"Style not found: {style}. Available: {[s.stem for s in styles_dir.glob('*.html')]}"})
    deck_path = Path(deck_id)
    if not deck_path.is_dir():
        return json.dumps({"error": f"Deck directory not found: {deck_id}"})
    dest = deck_path / "specs" / "art-direction.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return json.dumps({"status": "ok", "path": str(dest), "style": style})


@mcp.tool()
def run_python(code: str, deck_id: str = "", save: bool = False,
               measure_slides: list[str] | None = None, purpose: str = "") -> str:
    """Execute Python code in the deck workspace or for general computation.

    If deck_id is provided (as output_dir path), the code runs with cwd set
    to that directory. Deck structure:
        deck.json           — metadata (template, fonts, defaultTextColor)
        specs/outline.md    — slide order (``- [slug] Message``)
        slides/{slug}.json  — per-slide data
        includes/           — code blocks, images
    Legacy decks with presentation.json are also supported.

    **Always specify measure_slides when editing slides.**

    Args:
        code: Python code to execute.
        deck_id: Deck output_dir path. Optional.
        save: When True, triggers PPTX build + preview + SVG compose after execution.
        measure_slides: Slide slugs to measure after execution (e.g. ["title", "feature-a"]).
        purpose: Brief description shown in UI.

    Returns:
        JSON: {"output", "measure"?, "pptx"?, "preview"?, "compose"?}
    """
    result: dict = {}
    cwd = deck_id if deck_id and Path(deck_id).is_dir() else None

    # Execute code
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            proc = subprocess.run(
                [sys.executable, f.name],
                capture_output=True, text=True, timeout=120, cwd=cwd,
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

    if not cwd:
        return json.dumps(result, ensure_ascii=False)

    # Determine deck input path: directory (new format) or presentation.json (legacy)
    deck_dir = Path(cwd)
    legacy_json = deck_dir / "presentation.json"
    # sdpm.api accepts a directory (new format) or a .json file (legacy)
    deck_input = str(legacy_json) if legacy_json.exists() else str(deck_dir)

    # Build slug → page number mapping from outline.md (for slug-based measure_slides)
    def _slug_to_page() -> dict[str, int]:
        from sdpm.api import parse_outline_slugs
        slugs = parse_outline_slugs(deck_dir / "specs" / "outline.md")
        return {slug: i + 1 for i, slug in enumerate(slugs)}

    # Post-processing: measure
    if measure_slides:
        try:
            # Call sdpm.api.measure directly with slug list — it resolves slug→page
            # and reports using slug names via format_measure_report(page_to_slug=...)
            from sdpm.api import measure as _sdpm_measure
            result["measure"] = _sdpm_measure(json_path=deck_input, slides=list(measure_slides))
        except Exception as e:
            result["measure"] = f"Measure error: {e}"

    # Post-processing: build PPTX + preview + SVG compose (when save=True)
    if save:
        try:
            # Force output.pptx inside deck dir (sdpm.api default goes to parent for directory input)
            pptx_out = str(deck_dir / "output.pptx")
            build_result = _generate_pptx(
                slides_json_path=deck_input, output_path=pptx_out, skill_dir=_SKILL_DIR
            )
            result["pptx"] = build_result.get("output_path", pptx_out)
        except Exception as e:
            result["pptx_error"] = str(e)

        try:
            # preview API writes PNGs to /tmp/pptx-preview (fixed path).
            # Clear first to avoid stale files from other decks.
            import shutil as _shutil
            _tmp_preview = Path("/tmp/pptx-preview")
            if _tmp_preview.exists():
                _shutil.rmtree(_tmp_preview, ignore_errors=True)
            preview_result = _preview(slides_json_path=deck_input, pages="", output_path=str(deck_dir / "output.pptx"))
            if isinstance(preview_result, dict) and preview_result.get("files"):
                preview_dir = deck_dir / "preview"
                # Clear deck's preview dir so page count always matches current build
                if preview_dir.exists():
                    _shutil.rmtree(preview_dir)
                preview_dir.mkdir(exist_ok=True)
                for png_path in preview_result["files"]:
                    src = Path(png_path)
                    if src.exists():
                        _shutil.copy2(src, preview_dir / src.name)
                result["preview"] = f"{len(preview_result['files'])} PNGs"
        except Exception as e:
            result["preview_error"] = str(e)

        # SVG compose for WebUI animation (requires LibreOffice 25.8.6+)
        try:
            import shutil as _sh
            lo = _sh.which("soffice") or (
                "/Applications/LibreOffice.app/Contents/MacOS/soffice"
                if Path("/Applications/LibreOffice.app/Contents/MacOS/soffice").exists()
                else None
            )
            pptx_out = result.get("pptx", "")
            if lo and pptx_out:
                with tempfile.TemporaryDirectory() as tmpdir:
                    env = dict(os.environ)
                    env["HOME"] = tmpdir
                    subprocess.run(
                        [lo, "--headless", "--convert-to", "svg", "--outdir", tmpdir, pptx_out],
                        capture_output=True, timeout=120, env=env,
                    )
                    svg_files = list(Path(tmpdir).glob("*.svg"))
                    if svg_files:
                        from compose import extract_optimized_defs, split_slide_components, count_slides
                        from sdpm.api import parse_outline_slugs
                        import time as _t
                        import re as _re
                        svg_path = svg_files[0]
                        n = count_slides(svg_path)
                        compose_dir = deck_dir / "compose"
                        compose_dir.mkdir(exist_ok=True)
                        epoch = int(_t.time())

                        # Index previous compose by slug → latest epoch path
                        prev_by_slug: dict[str, Path] = {}
                        if compose_dir.exists():
                            for f in compose_dir.iterdir():
                                m = _re.match(r"^(.+)_(\d+)\.json$", f.name)
                                if m and not f.name.startswith("defs_"):
                                    slug, ep = m.group(1), int(m.group(2))
                                    cur = prev_by_slug.get(slug)
                                    if not cur or int(_re.search(r"_(\d+)\.json$", cur.name).group(1)) < ep:
                                        prev_by_slug[slug] = f

                        def _mk(c: dict) -> str:
                            b = c.get("bbox")
                            return f"{c['class']}|{b['x']},{b['y']},{b['w']},{b['h']}" if b else f"{c['class']}|none"

                        def _fp(c: dict) -> str:
                            return f"{c['class']}|{c.get('text', '')}"

                        # Write defs_{epoch}.json
                        (compose_dir / f"defs_{epoch}.json").write_text(
                            json.dumps(extract_optimized_defs(svg_path), ensure_ascii=False),
                            encoding="utf-8",
                        )

                        # Determine which slugs to regenerate:
                        # - measure_slides (edited this turn) always
                        # - any slug without existing compose (first build / new slides)
                        # - slides/*.json modified since the newest prior compose epoch
                        # - if no prior compose at all, regen ALL
                        slugs = parse_outline_slugs(deck_dir / "specs" / "outline.md")
                        target_slugs: set[str] = set(measure_slides or [])
                        # Add slugs without existing compose
                        target_slugs |= {s for s in slugs if s not in prev_by_slug}
                        # Add slugs whose slides/*.json was modified after prior compose
                        if prev_by_slug:
                            for slug in slugs:
                                prev_f = prev_by_slug.get(slug)
                                slide_f = deck_dir / "slides" / f"{slug}.json"
                                if slide_f.exists() and prev_f:
                                    try:
                                        if slide_f.stat().st_mtime > prev_f.stat().st_mtime:
                                            target_slugs.add(slug)
                                    except OSError:
                                        pass
                        # First build (no prior compose) → regen all
                        if not prev_by_slug:
                            target_slugs = set(slugs)

                        composed = 0
                        for sn in range(1, n):  # skip DummySlide at index 0
                            idx = sn - 1
                            if idx >= len(slugs):
                                break
                            slug = slugs[idx]
                            if slug not in target_slugs:
                                continue
                            try:
                                comp_data = split_slide_components(svg_path, sn)
                                # Diff against previous compose for this slug
                                prev_file = prev_by_slug.get(slug)
                                if prev_file and prev_file.exists():
                                    try:
                                        prev_comps = json.loads(prev_file.read_text(encoding="utf-8")).get("components", [])
                                        prev_map = {_mk(c): _fp(c) for c in prev_comps}
                                        for c in comp_data["components"]:
                                            k = _mk(c)
                                            c["changed"] = k not in prev_map or prev_map[k] != _fp(c)
                                    except Exception:
                                        for c in comp_data["components"]:
                                            c["changed"] = True
                                else:
                                    for c in comp_data["components"]:
                                        c["changed"] = True
                                (compose_dir / f"{slug}_{epoch}.json").write_text(
                                    json.dumps(comp_data, ensure_ascii=False), encoding="utf-8"
                                )
                                composed += 1
                            except Exception:
                                pass

                        # Cleanup old defs (keep only newest)
                        for f in compose_dir.iterdir():
                            m = _re.match(r"^defs_(\d+)\.json$", f.name)
                            if m and int(m.group(1)) < epoch:
                                try: f.unlink()
                                except Exception: pass

                        result["compose"] = f"{composed} slides composed"
                        if n <= 2 and len(slugs) > 1:
                            result["compose_error"] = (
                                f"LibreOffice exported only {n - 1} slide(s) to SVG but outline has "
                                f"{len(slugs)} slides. Upgrade LibreOffice to 25.8.6+ (macOS multi-slide SVG fix)."
                            )
        except Exception as e:
            result["compose_error"] = str(e)

    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="stdio")
