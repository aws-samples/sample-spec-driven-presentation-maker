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

    If deck_id is provided, the code runs with cwd set to that directory.
    All workspace files are accessible via normal file I/O.

    **Always specify measure_slides when editing slides.**

    Args:
        code: Python code to execute.
        deck_id: Deck output_dir path. Optional.
        save: When True, triggers PPTX build + preview after execution.
        measure_slides: Slide slugs to measure after execution.
        purpose: Brief description shown in UI.

    Returns:
        JSON: {"output", "measure"?, "pptx"?, "preview"?}
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

    # Post-processing: measure
    if cwd and measure_slides:
        try:
            json_path = str(Path(cwd) / "presentation.json")
            if Path(json_path).exists():
                pages = ",".join(measure_slides) if measure_slides else ""
                result["measure"] = _measure(slides_json_path=json_path, pages=pages)
        except Exception as e:
            result["measure"] = f"Measure error: {e}"

    # Post-processing: build PPTX + preview (when save=True)
    if cwd and save:
        json_path = str(Path(cwd) / "presentation.json")
        if Path(json_path).exists():
            try:
                build_result = _generate_pptx(
                    slides_json_path=json_path, output_path="", skill_dir=_SKILL_DIR
                )
                result["pptx"] = build_result.get("output_path", "")
            except Exception as e:
                result["pptx_error"] = str(e)

            try:
                preview_result = _preview(slides_json_path=json_path, pages="", output_path="")
                if isinstance(preview_result, dict) and preview_result.get("files"):
                    import shutil
                    preview_dir = Path(cwd) / "preview"
                    preview_dir.mkdir(exist_ok=True)
                    for png_path in preview_result["files"]:
                        src = Path(png_path)
                        if src.exists():
                            shutil.copy2(src, preview_dir / src.name)
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
                            svg_path = svg_files[0]
                            n = count_slides(svg_path)
                            compose_dir = Path(cwd) / "compose"
                            compose_dir.mkdir(exist_ok=True)
                            (compose_dir / "defs.json").write_text(
                                json.dumps(extract_optimized_defs(svg_path), ensure_ascii=False),
                                encoding="utf-8",
                            )
                            composed = 0
                            for sn in range(1, n):  # skip DummySlide at index 0
                                try:
                                    comp = split_slide_components(svg_path, sn)
                                    (compose_dir / f"slide_{sn}.json").write_text(
                                        json.dumps(comp, ensure_ascii=False), encoding="utf-8"
                                    )
                                    composed += 1
                                except Exception:
                                    pass
                            result["compose"] = f"{composed} slides composed"
            except Exception as e:
                result["compose_error"] = str(e)

    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="stdio")
