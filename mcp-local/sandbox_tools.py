# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Sandboxed Python execution tools — shared by server.py and server_acp.py.

These tools run user code in restricted subprocesses with optional
deck file I/O via sandbox functions. Not ACP-specific.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _rejection_message(violations: list[str], has_deck: bool) -> str:
    """Build an error message that helps the LLM rewrite rejected code."""
    lines = ["Code rejected by sandbox:"]
    lines.extend(f"  {v}" for v in violations)
    if has_deck:
        lines.append("")
        lines.append("Use sandbox functions instead:")
        lines.append("  read_json(path) → dict    write_json(path, data)")
        lines.append("  read_text(path) → str     write_text(path, text)")
        lines.append('  list_files(subdir=".") → list[str]')
        lines.append("")
        lines.append("Example:")
        lines.append('  data = read_json("slides/title.json")')
        lines.append('  data["elements"][0]["text"] = "New Title"')
        lines.append('  write_json("slides/title.json", data)')
    else:
        lines.append("")
        lines.append("Only print and built-in functions are available (no file I/O).")
    return "\n".join(lines)


def run_python(purpose: str, code: str, deck_id: str = "", save: bool = False,
               measure_slides: list[str] | None = None) -> str:
    """Execute Python code in a sandboxed environment.

    Code runs in a restricted subprocess. `import` statements and direct file
    access (`open()`) are NOT available. Use the provided sandbox functions instead.

    ## Sandbox functions (available when deck_id is provided)

        read_json(path)          → dict/list   Read a JSON file
        write_json(path, data)   → None        Write data as JSON
        read_text(path)          → str         Read a text file
        write_text(path, text)   → None        Write a text file
        list_files(subdir=".")   → list[str]   List filenames in a subdirectory

    All paths are relative to the deck directory (e.g. "slides/title.json").
    Access outside the deck directory is denied.

    ## Built-in functions available

    print, len, range, enumerate, sorted, isinstance, type, str, int, float,
    bool, list, dict, tuple, set, min, max, sum, abs, round, any, all, zip,
    map, filter, reversed

    ## When deck_id is NOT provided (general computation)

    Only print and built-in functions above are available.
    No file operations.

    ## Examples

        # Read and edit a slide
        data = read_json("slides/title.json")
        data["elements"][0]["text"] = "New Title"
        write_json("slides/title.json", data)

        # Write a spec file
        content = \"\"\"# Brief

Topic: AI-powered presentation tool
Audience: Developers
\"\"\"
        write_text("specs/brief.md", content)

        # Read deck metadata
        deck = read_json("deck.json")
        print(deck["template"])

        # Read a spec file
        outline = read_text("specs/outline.md")
        print(outline)

        # List slide files
        files = list_files("slides")
        print(files)

        # General computation (no deck_id)
        print(2 ** 100)

    **Always specify measure_slides when editing slides.**

    Args:
        purpose: Brief user-facing description of what this code does. Shown in UI.
        code: Python code to execute (no import statements allowed).
        deck_id: Deck output_dir path. Optional.
        save: When True, triggers PPTX build + preview + SVG compose after execution.
        measure_slides: Slide slugs to measure after execution (e.g. ["title", "feature-a"]).

    Returns:
        JSON: {"output", "measure"?, "pptx"?, "preview"?, "compose"?}
    """
    result: dict[str, Any] = {}
    cwd = deck_id if deck_id and Path(deck_id).is_dir() else None

    from sandbox import check_code, make_runner

    violations = check_code(code)
    if violations:
        result["output"] = _rejection_message(violations, has_deck=bool(cwd))
        return json.dumps(result, ensure_ascii=False)

    try:
        runner = make_runner(deck_id if cwd else "")
        args = [sys.executable, "-c", runner]
        if cwd:
            args.append(deck_id)
        proc = subprocess.run(
            args, input=code,
            capture_output=True, text=True, timeout=120, cwd=cwd,
        )
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

    deck_dir = Path(cwd)
    legacy_json = deck_dir / "presentation.json"
    deck_input = str(legacy_json) if legacy_json.exists() else str(deck_dir)

    # Lint outline.md
    outline_path = deck_dir / "specs" / "outline.md"
    if outline_path.exists() and outline_path.read_text(encoding="utf-8").strip():
        from sdpm.schema.lint_outline import lint_outline
        if lint_outline(outline_path.read_text(encoding="utf-8")):
            result.setdefault("warnings", {})["outline"] = (
                "outline.md format violation. "
                "Read workflow `create-new-1-outline` for the correct format."
            )

    # Lint and sanitize slide JSON
    from sdpm.schema.lint import lint_and_sanitize
    slides_dir = deck_dir / "slides"
    if slides_dir.is_dir():
        lint_diagnostics: list[dict] = []
        for slide_file in sorted(slides_dir.glob("*.json")):
            try:
                slide_data = json.loads(slide_file.read_text(encoding="utf-8"))
                cleaned, diags = lint_and_sanitize(slide_data)
                if diags:
                    slug = slide_file.stem
                    for d in diags:
                        d["slug"] = slug
                    lint_diagnostics.extend(diags)
                    slide_file.write_text(
                        json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
            except (json.JSONDecodeError, TypeError):
                pass
        if lint_diagnostics:
            errs = result.setdefault("errors", {})
            errs["lintDiagnostics"] = lint_diagnostics

    # Post-processing: build PPTX + SVG (compose/measure) + preview
    _lock_fp = None
    if save:
        if sys.platform != "win32":
            try:
                import fcntl
                lock_path = deck_dir / ".save.lock"
                lock_path.touch(exist_ok=True)
                _lock_fp = open(lock_path, "r+b")
                fcntl.flock(_lock_fp.fileno(), fcntl.LOCK_EX)
            except Exception:
                if _lock_fp:
                    _lock_fp.close()
                    _lock_fp = None

    if save:
        try:
            from sdpm.api import generate
            from sdpm.assets import invalidate_manifest_cache
            invalidate_manifest_cache()
            pptx_out = str(deck_dir / "output.pptx")
            build_result = generate(json_path=deck_input, output_path=pptx_out)
            result["pptx"] = build_result.get("output_path", pptx_out)
            # Store for later filtering by measure_slides
            _build_warnings = build_result.get("warnings", [])
            _build_lint = build_result.get("errors", {}).get("lintDiagnostics", [])
        except Exception as e:
            result["pptx_error"] = str(e)
            _build_warnings = []
            _build_lint = []

        import shutil
        svg_path: Path | None = None
        _svg_tmpdir: str | None = None
        pptx_slugs: list[str] = []
        try:
            from sdpm.preview import get_work_dir
            lo = shutil.which("soffice")
            if not lo:
                _lo_candidates = [
                    Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
                    Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
                ]
                for _c in _lo_candidates:
                    if _c.exists():
                        lo = str(_c)
                        break
            pptx_out = result.get("pptx", "")
            if lo and pptx_out:
                _svg_tmpdir = tempfile.mkdtemp(dir=get_work_dir(deck_dir))
                env = dict(os.environ)
                cmd = [lo, "--headless", "--convert-to", "svg", "--outdir", _svg_tmpdir]
                if sys.platform == "win32":
                    cmd.append(f"-env:UserInstallation=file:///{_svg_tmpdir.replace(os.sep, '/')}")
                else:
                    env["HOME"] = _svg_tmpdir
                cmd.append(pptx_out)
                subprocess.run(cmd, capture_output=True, timeout=120, env=env, stdin=subprocess.DEVNULL)
                svg_files = list(Path(_svg_tmpdir).glob("*.svg"))
                if svg_files:
                    svg_path = svg_files[0]
        except Exception as e:
            result["compose_error"] = str(e)

        # Compose: SVG → optimized JSON
        if svg_path:
            try:
                from compose import extract_optimized_defs, split_slide_components, count_slides
                from sdpm.api import parse_outline_slugs
                import time as _t
                import re as _re
                n = count_slides(svg_path)
                compose_dir = deck_dir / "compose"
                compose_dir.mkdir(exist_ok=True)
                epoch = int(_t.time())

                prev_by_slug: dict[str, Path] = {}
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

                (compose_dir / f"defs_{epoch}.json").write_text(
                    json.dumps(extract_optimized_defs(svg_path), ensure_ascii=False),
                    encoding="utf-8",
                )

                slugs = parse_outline_slugs(deck_dir / "specs" / "outline.md")
                pptx_slugs = [s for s in slugs if (deck_dir / "slides" / f"{s}.json").exists()]
                if not prev_by_slug:
                    target_slugs: set[str] = set(pptx_slugs)
                else:
                    target_slugs = set(measure_slides or [])

                composed = 0
                for sn in range(1, n):
                    idx = sn - 1
                    if idx >= len(pptx_slugs):
                        break
                    slug = pptx_slugs[idx]
                    if slug not in target_slugs:
                        continue
                    try:
                        comp_data = split_slide_components(svg_path, sn)
                        print(f"[compose] svg slide {sn} → slug {slug}", file=sys.stderr)
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

                for f in compose_dir.iterdir():
                    m = _re.match(r"^defs_(\d+)\.json$", f.name)
                    if m and int(m.group(1)) < epoch:
                        try:
                            f.unlink()
                        except Exception:
                            pass

                result["compose"] = f"{composed} slides composed"
                if n <= 2 and len(slugs) > 1:
                    result["compose_error"] = (
                        f"LibreOffice exported only {n - 1} slide(s) to SVG but outline has "
                        f"{len(slugs)} slides. Upgrade LibreOffice to 25.8.6+ (macOS multi-slide SVG fix)."
                    )
            except Exception as e:
                result["compose_error"] = str(e)

        # Measure
        if measure_slides and svg_path and pptx_slugs:
            try:
                from sdpm.preview.measure import measure_from_svg, format_measure_report
                slug_to_page = {s: i + 1 for i, s in enumerate(pptx_slugs)}
                page_to_slug = {v: k for k, v in slug_to_page.items()}
                slide_indices = [slug_to_page[s] for s in measure_slides if s in slug_to_page]
                if slide_indices:
                    results = measure_from_svg(svg_path, slide_indices)
                    result["measure"] = format_measure_report(results, page_to_slug=page_to_slug)
            except Exception as e:
                result["measure"] = f"Measure error: {e}"
        elif measure_slides and not svg_path:
            try:
                from sdpm.api import measure as _sdpm_measure
                result["measure"] = _sdpm_measure(json_path=deck_input, slides=list(measure_slides))
            except Exception as e:
                result["measure"] = f"Measure error: {e}"

        if _svg_tmpdir:
            shutil.rmtree(_svg_tmpdir, ignore_errors=True)

        # Preview: PDF → PNG
        try:
            from sdpm.api import preview as _preview
            preview_result = _preview(json_path=deck_input, output_path=str(deck_dir / "output.pptx"))
            if isinstance(preview_result, dict) and preview_result.get("files"):
                import shutil as _sh
                preview_dir = deck_dir / "preview"
                if preview_dir.exists():
                    _sh.rmtree(preview_dir)
                preview_dir.mkdir(exist_ok=True)
                for png_path in preview_result["files"]:
                    src = Path(png_path)
                    if src.exists():
                        _sh.copy2(src, preview_dir / src.name)
                _sh.rmtree(preview_result["preview_dir"], ignore_errors=True)

                # Return filtered preview paths + warnings for measure_slides slugs
                import re as _re2
                if measure_slides and pptx_slugs:
                    slug_to_page_num = {s: i + 1 for i, s in enumerate(pptx_slugs)}
                    target_pages = {slug_to_page_num[s] for s in measure_slides if s in slug_to_page_num}
                else:
                    target_pages = None  # return all

                # Filter preview files
                all_previews = sorted(preview_dir.iterdir())
                filtered_previews = []
                for f in all_previews:
                    if not f.name.endswith(".png"):
                        continue
                    m = _re2.match(r"^page(\d+)[-.]", f.name)
                    if m:
                        if target_pages is None or int(m.group(1)) in target_pages:
                            filtered_previews.append(str(f))
                result["preview_files"] = filtered_previews

                # Filter warnings
                if target_pages is not None:
                    page_pats = {f"page{p:02d}" for p in target_pages}
                    result["warnings"] = [w for w in _build_warnings if any(p in w for p in page_pats)]
                    result["lint_diagnostics"] = [d for d in _build_lint if any(p in str(d) for p in page_pats)]
                else:
                    if _build_warnings:
                        result["warnings"] = _build_warnings
                    if _build_lint:
                        result["lint_diagnostics"] = _build_lint
        except Exception as e:
            result["preview_error"] = str(e)

    elif measure_slides:
        try:
            from sdpm.api import measure as _sdpm_measure
            result["measure"] = _sdpm_measure(json_path=deck_input, slides=list(measure_slides))
        except Exception as e:
            result["measure"] = f"Measure error: {e}"

    if _lock_fp is not None:
        try:
            import fcntl as _fc
            _fc.flock(_lock_fp.fileno(), _fc.LOCK_UN)
            _lock_fp.close()
        except Exception:
            pass

    return json.dumps(result, ensure_ascii=False)


def run_style_python(purpose: str, code: str) -> str:
    """Execute Python code in a sandboxed environment for style creation.

    ## Sandbox functions

        read_style(name)         → str   Read an existing style HTML (builtin or user)
        write_style(name, html)  → None  Save HTML to user styles directory

    ## Rules

    - `name` is the file stem without .html (e.g. "corporate-executive", "style-20260505-1430")
    - No import statements or direct file access allowed
    - Use print() for computation output

    ## Examples

        # Read an existing style for reference
        html = read_style("corporate-executive")
        print(html[:200])

        # Create a new style
        html = '''<!DOCTYPE html>
        <html><head><title>My Custom Style</title></head>
        <body>...</body></html>'''
        write_style("style-20260505-1430", html)

        # Edit an existing user style
        html = read_style("style-20260505-1430")
        html = html.replace("old color", "new color")
        write_style("style-20260505-1430", html)

    Args:
        purpose: Brief user-facing description of what this code does. Shown in UI.
        code: Python code to execute (no import statements allowed).

    Returns:
        JSON: {"output", "saved"?}
    """
    from sandbox import check_code, make_style_runner

    result: dict[str, Any] = {}

    violations = check_code(code)
    if violations:
        lines = ["Code rejected by sandbox:"]
        lines.extend(f"  {v}" for v in violations)
        lines.append("")
        lines.append("Use sandbox functions instead:")
        lines.append("  read_style(name) → str       (read existing style HTML)")
        lines.append("  write_style(name, html) → None  (save to user styles)")
        result["output"] = "\n".join(lines)
        return json.dumps(result, ensure_ascii=False)

    from sdpm.config import get_user_config_dir
    from sdpm.api import get_styles_dirs

    user_styles_dir = str(get_user_config_dir() / "styles")
    styles_dirs_json = json.dumps([str(d) for d in get_styles_dirs()])

    try:
        runner = make_style_runner()
        proc = subprocess.run(
            [sys.executable, "-c", runner, user_styles_dir, styles_dirs_json],
            input=code, capture_output=True, text=True, timeout=120,
        )
        output = proc.stdout
        stderr = proc.stderr or ""

        save_lines = []
        other_stderr = []
        for line in stderr.splitlines():
            if line.startswith("__STYLE_SAVED__"):
                save_lines.append(line[len("__STYLE_SAVED__"):])
            else:
                other_stderr.append(line)

        if other_stderr:
            output += "\n" + "\n".join(other_stderr)
        result["output"] = output.strip()

        if save_lines:
            result["saved"] = json.loads(save_lines[-1])

    except subprocess.TimeoutExpired:
        result["output"] = "Error: execution timed out (120s)"
    except Exception as e:
        result["output"] = f"Error: {e}"

    return json.dumps(result, ensure_ascii=False)
