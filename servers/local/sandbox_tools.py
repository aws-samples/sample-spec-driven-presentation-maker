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


def _build_snapshot(deck_dir: Path) -> dict[str, tuple[int, int]]:
    """Snapshot (mtime_ns, size) of files that affect the built PPTX.

    Used to detect whether a run_python execution changed the deck, so the
    output.pptx artifact can be rebuilt automatically. specs/outline.md is
    included because slide order comes from the outline.
    """
    snap: dict[str, tuple[int, int]] = {}
    for rel in ("deck.json", "presentation.json", "specs/outline.md"):
        p = deck_dir / rel
        if p.is_file():
            st = p.stat()
            snap[rel] = (st.st_mtime_ns, st.st_size)
    for sub in ("slides", "includes"):
        d = deck_dir / sub
        if d.is_dir():
            for p in d.glob("*.json"):
                st = p.stat()
                snap[f"{sub}/{p.name}"] = (st.st_mtime_ns, st.st_size)
    return snap


def run_python(purpose: str, code: str, deck_id: str = "",
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

    ## Persistence & build (no flags needed)

    - File writes always persist — anything written via write_json/write_text
      is saved immediately. There is no "unsaved" state.
    - output.pptx rebuilds automatically whenever the deck changed
      (deck.json / slides/ / includes/ / specs/outline.md).
    - measure_slides triggers the expensive verification pass (render + text
      overflow measurement + preview PNGs) for the given slugs only.

    Args:
        purpose: Brief user-facing description of what this code does. Shown in UI.
        code: Python code to execute (no import statements allowed).
        deck_id: Deck output_dir path. Optional.
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

    pre_snap = _build_snapshot(Path(cwd)) if cwd else {}

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
        from sdpm.engine.schema.lint_outline import lint_outline
        if lint_outline(outline_path.read_text(encoding="utf-8")):
            result.setdefault("warnings", {})["outline"] = (
                "outline.md format violation. "
                "Read workflow `create-new-1-outline` for the correct format."
            )

    # Lint and sanitize slide JSON
    from sdpm.engine.schema.lint import lint_and_sanitize
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
                    # Rewrite only when sanitization changed the content —
                    # unconditional rewrites would bump mtime every call and
                    # falsely mark the deck as changed (auto-rebuild churn).
                    if cleaned != slide_data:
                        slide_file.write_text(
                            json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8",
                        )
            except (json.JSONDecodeError, TypeError):
                pass
        if lint_diagnostics:
            errs = result.setdefault("errors", {})
            errs["lintDiagnostics"] = lint_diagnostics

    # Post-processing: build PPTX + iso measure/compose/preview (lockless).
    # output.pptx is a derived artifact — it follows deck changes automatically.
    # measure_slides additionally triggers the expensive verification pass.
    deck_changed = _build_snapshot(deck_dir) != pre_snap
    if deck_changed or measure_slides:
        import shutil

        from sdpm.api import generate, parse_outline_slugs
        from sdpm.knowledge.assets import invalidate_manifest_cache
        from sdpm.engine.preview import get_work_dir

        invalidate_manifest_cache()
        _build_warnings: list[str] = []
        _build_lint: list[dict] = []

        # 1) Full-deck output.pptx — no lock needed (python-pptx write is ~0.2s)
        try:
            pptx_out = str(deck_dir / "output.pptx")
            build_result = generate(json_path=deck_input, output_path=pptx_out)
            result["pptx"] = build_result.get("output_path", pptx_out)
            _build_warnings = build_result.get("warnings", [])
            _build_lint = build_result.get("errors", {}).get("lintDiagnostics", [])
        except Exception as e:
            result["pptx_error"] = str(e)

        # 2) iso.pptx path: compose + measure + preview for measure_slides only
        if measure_slides:
            outline_slugs = parse_outline_slugs(deck_dir / "specs" / "outline.md")
            measure_set = set(measure_slides)
            pptx_slugs = [
                s for s in outline_slugs
                if s in measure_set and (deck_dir / "slides" / f"{s}.json").exists()
            ]

            work_root = get_work_dir(deck_dir)
            iso_dir = Path(tempfile.mkdtemp(prefix="measure-", dir=work_root))
            try:
                # Build iso.pptx containing only the target slugs
                iso_pptx = iso_dir / "iso.pptx"
                generate(
                    json_path=deck_input,
                    output_path=str(iso_pptx),
                    only_slugs=set(measure_slides),
                )

                # Export SVG from iso.pptx
                svg_path: Path | None = None
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

                if lo:
                    env = dict(os.environ)
                    svg_outdir = str(iso_dir / "svg")
                    Path(svg_outdir).mkdir()
                    cmd = [lo, "--headless", "--convert-to", "svg", "--outdir", svg_outdir]
                    if sys.platform == "win32":
                        cmd.append(f"-env:UserInstallation=file:///{svg_outdir.replace(os.sep, '/')}")
                    else:
                        env["HOME"] = svg_outdir
                    cmd.append(str(iso_pptx))
                    subprocess.run(cmd, capture_output=True, timeout=120, env=env, stdin=subprocess.DEVNULL)
                    svg_files = list(Path(svg_outdir).glob("*.svg"))
                    if svg_files:
                        svg_path = svg_files[0]

                # --- Compose: SVG → optimized JSON ---
                if svg_path:
                    try:
                        from compose import extract_optimized_defs, split_slide_components, count_slides
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
                                slug_name, ep = m.group(1), int(m.group(2))
                                cur = prev_by_slug.get(slug_name)
                                if not cur or int(_re.search(r"_(\d+)\.json$", cur.name).group(1)) < ep:
                                    prev_by_slug[slug_name] = f

                        def _mk(c: dict) -> str:
                            b = c.get("bbox")
                            return f"{c['class']}|{b['x']},{b['y']},{b['w']},{b['h']}" if b else f"{c['class']}|none"

                        def _fp(c: dict) -> str:
                            return f"{c['class']}|{c.get('text', '')}"

                        (compose_dir / f"defs_{epoch}.json").write_text(
                            json.dumps(extract_optimized_defs(svg_path), ensure_ascii=False),
                            encoding="utf-8",
                        )

                        target_slugs = set(measure_slides)
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
                        if n <= 2 and len(outline_slugs) > 1:
                            result["compose_error"] = (
                                f"LibreOffice exported only {n - 1} slide(s) to SVG but outline has "
                                f"{len(outline_slugs)} slides. Upgrade LibreOffice to 25.8.6+ (macOS multi-slide SVG fix)."
                            )
                    except Exception as e:
                        result["compose_error"] = str(e)

                # --- Measure ---
                if svg_path and pptx_slugs:
                    try:
                        from sdpm.engine.preview.measure import measure_from_svg, format_measure_report
                        slug_to_page = {s: i + 1 for i, s in enumerate(pptx_slugs)}
                        page_to_slug = {v: k for k, v in slug_to_page.items()}
                        slide_indices = [slug_to_page[s] for s in measure_slides if s in slug_to_page]
                        if slide_indices:
                            results = measure_from_svg(svg_path, slide_indices)
                            try:
                                from sdpm.engine.preview.judge import judge_from_svg
                                judgments = judge_from_svg(svg_path, slide_indices)
                            except Exception:
                                judgments = None  # best-effort: never break measure
                            result["measure"] = format_measure_report(
                                results, page_to_slug=page_to_slug, judgments=judgments
                            )
                    except Exception as e:
                        result["measure"] = f"Measure error: {e}"
                elif not svg_path:
                    try:
                        from sdpm.api import measure as _sdpm_measure
                        result["measure"] = _sdpm_measure(json_path=deck_input, slides=list(measure_slides))
                    except Exception as e:
                        result["measure"] = f"Measure error: {e}"

                # --- Preview: PDF → PNG (slug-named) ---
                if iso_pptx.exists():
                    try:
                        from sdpm.engine.preview import export_pdf
                        preview_dir = deck_dir / "preview"
                        preview_dir.mkdir(exist_ok=True)

                        pdf_path = iso_dir / "slides.pdf"
                        if export_pdf(iso_pptx, pdf_path, work_dir=iso_dir):
                            png_outdir = iso_dir / "pngs"
                            png_outdir.mkdir()
                            cmd_png = ["pdftoppm", "-png", "-scale-to", "1280", str(pdf_path), str(png_outdir / "page")]
                            subprocess.run(cmd_png, capture_output=True, text=True, stdin=subprocess.DEVNULL)

                            # pdftoppm zero-pads the page number to the width of
                            # the largest page index, so a 1-9 page export is
                            # "page-1.png" (no padding), 10-99 is "page-01.png",
                            # etc. Try every plausible width instead of assuming
                            # one — the old code only tried 6/2/3 and silently
                            # produced an empty preview list for <10-page decks.
                            filtered_previews = []
                            missing = []
                            for idx_p, slug in enumerate(pptx_slugs):
                                n_p = idx_p + 1
                                src_png = None
                                for width in (1, 2, 3, 4, 6):
                                    cand = png_outdir / f"page-{n_p:0{width}d}.png"
                                    if cand.exists():
                                        src_png = cand
                                        break
                                if src_png:
                                    dst = preview_dir / f"{slug}.png"
                                    shutil.copy2(src_png, dst)
                                    filtered_previews.append(str(dst))
                                else:
                                    missing.append(slug)
                            result["preview_files"] = filtered_previews
                            if missing:
                                # Surface the silent gap instead of returning [].
                                produced = sorted(p.name for p in png_outdir.glob("*.png"))
                                result["preview_error"] = (
                                    f"No PNG matched slugs {missing}; "
                                    f"pdftoppm produced {produced}"
                                )
                    except Exception as e:
                        result["preview_error"] = str(e)

                # Filter warnings/lint to measured slugs
                if _build_warnings or _build_lint:
                    slug_to_page_full = {}
                    all_slugs = [s for s in outline_slugs if (deck_dir / "slides" / f"{s}.json").exists()]
                    for i, s in enumerate(all_slugs):
                        slug_to_page_full[s] = i + 1
                    target_pages = {slug_to_page_full[s] for s in measure_slides if s in slug_to_page_full}
                    page_pats = {f"page{p:02d}" for p in target_pages}
                    result["warnings"] = [w for w in _build_warnings if any(p in w for p in page_pats)]
                    result["lint_diagnostics"] = [d for d in _build_lint if any(p in str(d) for p in page_pats)]

            finally:
                shutil.rmtree(iso_dir, ignore_errors=True)

        else:
            # Deck changed without measure_slides: output.pptx only,
            # skip compose/measure/preview
            if _build_warnings:
                result["warnings"] = _build_warnings
            if _build_lint:
                result["lint_diagnostics"] = _build_lint

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
