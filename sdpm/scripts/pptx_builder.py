#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""PPTX Builder CLI - backward compatible entry point.

All core logic lives in sdpm package.
This file provides the CLI interface only.
"""
import sys
from pathlib import Path

# Ensure sdpm package is importable
# Use .parent.parent without .resolve() to preserve symlink-based installations
# (e.g. chezmoi-managed skill directory) — .resolve() would follow the symlink
# and insert the upstream repo path, causing wrong templates/ directory lookup.
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import json

from sdpm.knowledge.assets import (  # noqa: F401
    ICON_DIR,
    ICON_LOCAL_DIR,
    check_asset_exists,
    check_icon_exists,
    print_search_results,
    resolve_asset_path,
    resolve_icon_path,
    search_assets,
)
from sdpm.engine.layout import (  # noqa: F401
    _group_member_ids,
    _layout_collect,
    _layout_route_connections,
    _layout_scale,
    _layout_translate,
    _seg_crosses_box,
    _segments_cross,
    box_to_elements,
    cancel_cross_axis_squash,
    measure_natural_child_sizes,
    optimize_order,
)
from sdpm.engine.layout.render import render_architecture
from sdpm.engine.preview.backend import _is_wsl
from sdpm.utils.effects import apply_effects  # noqa: F401
from sdpm.utils.image import apply_image_effects, resolve_image_path  # noqa: F401
from sdpm.utils.io import read_json, write_json
from sdpm.utils.svg import (  # noqa: F401
    _recolor_svg,
    add_svg_to_slide,
    generate_qr_svg,
    get_svg_dimensions,
)

# Re-export for backward compatibility (scripts that import from here)
from sdpm.utils.text import normalize_spacing, parse_styled_text  # noqa: F401


def _resolve_template(data, input_path):
    """Resolve template path: presentation.json "template" → templates/ lookup → error."""
    from sdpm.api import _find_template_in_dirs, get_templates_dirs

    if data.get("template"):
        base_dir = Path(input_path).parent if input_path and input_path != "-" else Path(".")
        template = base_dir / data["template"]
        if template.exists():
            return template, True
        found = _find_template_in_dirs(data["template"], get_templates_dirs())
        if found is not None:
            return found, True

    print("Error: No template specified. Set \"template\" in presentation JSON.", file=sys.stderr)
    sys.exit(1)


def cmd_generate(args):
    """Generate PPTX from JSON."""
    from sdpm.api import generate

    try:
        result = generate(
            json_path=args.input if args.input and args.input != "-" else None,
            output_path=args.output,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        if "Missing assets" in str(e):
            print("", file=sys.stderr)
            print("Run the following command to download assets:", file=sys.stderr)
            print("  python3 scripts/download_aws_icons.py", file=sys.stderr)
            print("  python3 scripts/download_material_icons.py", file=sys.stderr)
        sys.exit(1)

    print(f"Generated: {Path(result['output_path']).resolve()}")
    for line in result["slides"]:
        print(line)

    if result["warnings"]:
        # Section-aware grouping: each multi-line check returns a header followed
        # by bullet lines (indented with two leading spaces). Walk the list and
        # collect each header with its bullets.
        layout_warnings: list[str] = []
        font_warnings: list[str] = []
        overlay_warnings: list[str] = []
        other_warnings: list[str] = []

        current_section: list[str] | None = None
        for w in result["warnings"]:
            if w.startswith("page") and "offset" in w:
                layout_warnings.append(w)
                current_section = None
            elif w.startswith("fontSize token discipline"):
                current_section = font_warnings
            elif w.startswith("overlay textbox detected"):
                current_section = overlay_warnings
            elif w.startswith("  ") and current_section is not None:
                current_section.append(w)
            else:
                other_warnings.append(w)
                current_section = None

        if layout_warnings:
            print(f"⚠️  Layout bias detected ({len(layout_warnings)} slides):")
            for w in layout_warnings:
                print(f"  {w}")
            print("  → MUST FIX unless the layout type is intentionally asymmetric.")

        if font_warnings:
            print("⚠️  Font size token discipline violations:")
            for w in font_warnings:
                print(w if w.startswith("  ") else f"  {w}")
            print("  → Add the missing --fs-* token to specs/art-direction.html, or change the slide to use an existing token.")

        if overlay_warnings:
            print("⚠️  Overlay textbox detected:")
            for w in overlay_warnings:
                print(w if w.startswith("  ") else f"  {w}")
            print("  → Move the label into the shape's `text` property and delete the overlaying textbox.")

        for w in other_warnings:
            print(f"  {w}")


def cmd_preview(args):
    """Export slides as PNG images from JSON."""
    from sdpm.api import preview as api_preview

    pages_list = None
    if args.pages:
        pages_list = [int(p.strip()) for p in args.pages.split(",")]

    try:
        result = api_preview(
            json_path=args.input,
            pages=pages_list,
            grid=not args.no_grid,
            output_dir=args.output_dir,
        )
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    for path in result["files"]:
        print(f"Generated: {path}")
    if result["files"]:
        print(f"Preview: {result['preview_dir']}")





def cmd_measure(args):
    """Measure text bounding boxes from slides JSON."""
    from sdpm.api import measure

    slides_list = None
    if args.pages:
        slides_list = [int(p.strip()) for p in args.pages.split(",")]

    try:
        result = measure(
            json_path=args.input,
            slides=slides_list,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(result)


def cmd_search_assets(args):
    """Search assets (icons, images, etc.) by keywords."""
    results = search_assets(
        query=args.query,
        limit=args.limit,
        source_filter=args.source,
        type_filter=args.type,
        theme_filter=args.theme,
    )
    print_search_results(results, limit=args.limit)


# Backward-compatible alias


def cmd_list_asset_sources(args):
    """List available asset sources."""
    from sdpm.knowledge.assets import list_sources
    sources = list_sources()
    if not sources:
        print("No asset sources found.", file=sys.stderr)
        return
    for s in sources:
        desc = f"  {s['description']}" if s["description"] else ""
        print(f"  {s['source']:<20} {s['count']:>6} assets{desc}")


def cmd_list_templates(args):
    """List available PPTX templates with source and description.

    Includes user-local templates (via $SDPM_TEMPLATES_DIR or ~/.config/sdpm/templates/)
    in addition to the package-bundled ones. User-local templates shadow bundled
    templates with the same stem. Descriptions come from state.json user notes —
    the art-direction workflow instructs agents to consider them when selecting
    a template.
    """
    from sdpm.api import get_templates_dirs, list_templates_with_metadata
    from sdpm.config import get_state

    templates_dirs = get_templates_dirs()
    templates = list_templates_with_metadata(
        templates_dirs,
        get_state().get("template_metadata", {}),
    )
    if not templates:
        print("No templates found.", file=sys.stderr)
        return
    # Resolved path per stem (first match wins — same order as the engine).
    # Kept in the output because agents need it to locate user-local templates.
    paths: dict[str, Path] = {}
    for d in templates_dirs:
        if not d.exists():
            continue
        for t in sorted(d.glob("*.pptx")):
            paths.setdefault(t.stem, t)
    for t in templates:
        desc = f"  — {t['description']}" if t["description"] else ""
        print(f"  {t['name']:<24} [{t['source']}]  {paths[t['name']]}{desc}")


def cmd_search_patterns(args):
    """Search patterns by keywords."""
    from sdpm.knowledge.reference import search_patterns
    results = search_patterns(args.query, limit=args.limit)
    if not results:
        print("No matches found.")
        return
    for r in results:
        page = f"/{r['page']}" if r.get('page') else ""
        print(f"  {r['path']}{page}  {r['description']}")


def cmd_examples(args):
    """List or show design examples (components/patterns/styles)."""
    from sdpm.knowledge.reference import open_styles_gallery, read_docs

    examples_dir = Path(__file__).parent.parent / "references" / "examples"
    if not examples_dir.exists():
        print("Directory not found: references/examples", file=sys.stderr)
        return

    names = args.names
    if not names:
        print("Usage: examples <category> or <category/name>", file=sys.stderr)
        return

    for name in names:
        parts = name.split("/", 1)
        base = parts[0]
        sub = parts[1] if len(parts) > 1 else None

        # styles/ directory — searches user-local + bundled
        if base == "styles":
            from sdpm.api import get_styles_dirs
            from sdpm.knowledge.reference import list_styles_merged
            styles_dirs = get_styles_dirs()
            if sub is None:
                for s in list_styles_merged(styles_dirs):
                    print(f"  styles/{s['name']}  {s['description']}")
                if not args.no_browse:
                    open_styles_gallery(styles_dirs)
            else:
                from sdpm.api import _find_style_in_dirs
                src = _find_style_in_dirs(sub, styles_dirs)
                if src is None:
                    print(f"# Style not found: {sub}", file=sys.stderr)
                else:
                    print(f"# cp {src} specs/art-direction.html")
            continue

        # pptx files (components, patterns)
        query = f"{base}/{sub}" if sub else base
        try:
            docs = read_docs(examples_dir, [query])
            for doc in docs:
                print(doc["content"])
                print()
        except FileNotFoundError:
            print(f"# Not found: {base}", file=sys.stderr)
            cats = []
            for f in sorted(examples_dir.iterdir()):
                if f.suffix == ".pptx":
                    cats.append(f.stem)
                elif f.is_dir() and not f.name.startswith('.'):
                    cats.append(f"{f.name}/")
            print(f"# Available: {', '.join(cats)}", file=sys.stderr)


def cmd_workflows(args):
    """List or show workflow documents."""
    from sdpm.knowledge.reference import list_category, read_docs
    d = Path(__file__).parent.parent / "references" / "workflows"
    if not args.names:
        print("# Workflows")
        for item in list_category(d):
            print(f"  {item['name']:<36} {item['description']}")
    else:
        try:
            for doc in read_docs(d, args.names):
                print(doc["content"])
                print()
        except FileNotFoundError as e:
            print(f"# {e}", file=sys.stderr)


def cmd_guides(args):
    """List or show guide documents."""
    from sdpm.knowledge.reference import list_category, read_docs
    d = Path(__file__).parent.parent / "references" / "guides"
    if not args.names:
        print("# Guides")
        for item in list_category(d):
            print(f"  {item['name']:<36} {item['description']}")
    else:
        try:
            for doc in read_docs(d, args.names):
                print(doc["content"])
                print()
        except FileNotFoundError as e:
            print(f"# {e}", file=sys.stderr)


def _get_documents_dir():
    """Get output base directory from config, with WSL fallback."""
    try:
        from sdpm.config import get_output_dir
        return get_output_dir()
    except Exception:
        pass
    import subprocess
    if _is_wsl():
        try:
            result = subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
                ["/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "-Command",
                 "[Environment]::GetFolderPath('MyDocuments')"],
                capture_output=True, timeout=10)
            win_path = result.stdout.decode("cp932", errors="replace").strip()
            if win_path:
                wsl = subprocess.run(["wslpath", win_path], capture_output=True, text=True)  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
                if wsl.returncode == 0:
                    return Path(wsl.stdout.strip()) / "SDPM-Presentations"
        except Exception:
            pass
    return Path.home() / "Documents" / "SDPM-Presentations"


def cmd_init(args):
    from sdpm.api import init
    result = init(
        name=args.name or "",
        output_dir=args.output if hasattr(args, 'output') and args.output else None,
    )
    print(f"output_dir:  {result['output_dir']}")
    print(f"deck_json:   {result['deck_json']}")
    for f in result["workspace"]:
        if f.startswith("specs/"):
            print(f"specs:       {Path(result['output_dir']) / f}")
def cmd_code_block(args):
    """Generate elements JSON for a syntax-highlighted code block."""
    from sdpm.api import code_block

    if args.input == "-":
        import sys as _sys
        code = _sys.stdin.read()
    else:
        code = Path(args.input).read_text(encoding="utf-8")

    elements = code_block(
        code=code,
        language=args.language or "text",
        theme=args.theme or "dark",
        x=args.x or 0, y=args.y or 0,
        width=args.width or 800, height=args.height or 300,
        font_size=args.font_size or 12,
        show_label=not args.no_label,
    )

    output = {"elements": elements}
    out_str = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        write_json(Path(args.output), output)
        print(f"Written: {args.output}", file=__import__('sys').stderr)
    else:
        print(out_str)


def cmd_layout(args):
    """Layout engine: compute coordinates from logical structure JSON.

    Thin CLI wrapper around ``sdpm.engine.layout.render.render_architecture`` (the
    canonical pipeline). CLI output intentionally omits the ``metrics`` key so
    stdout stays byte-compatible with prior versions; use ``layout_qa.py`` for
    metrics.
    """
    if args.input == "-":
        import sys as _sys
        source = _sys.stdin.read()
    else:
        source = Path(args.input).read_text(encoding="utf-8")

    tree = json.loads(source)

    result = render_architecture(
        tree,
        x=args.x, y=args.y, width=args.width, height=args.height,
        theme=getattr(args, "theme", "dark"),
        include_metrics=False,
    )

    elements = result["elements"]
    bb = result["bbox"]
    warnings = result.get("warnings", [])

    output = {"elements": elements, "bbox": bb}
    if warnings:
        output["warnings"] = warnings

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(out_path, {"elements": elements})
        print(f"Generated: {out_path}")
        print(f"bbox: x={bb['x']} y={bb['y']} width={bb['width']} height={bb['height']}")
        for w in warnings:
            print(f"⚠️  {w}")
    else:
        print(json.dumps(output, indent=2, ensure_ascii=False))


def cmd_analyze_template(args):
    """Analyze a PPTX template: extract layouts, theme, and placeholder details."""
    from sdpm.engine.analyzer import analyze_template, get_layout_placeholders

    template_path = Path(args.input).resolve()
    if not template_path.exists():
        from sdpm.api import _find_template_in_dirs, get_templates_dirs

        found = _find_template_in_dirs(args.input, get_templates_dirs())
        if found is not None:
            template_path = found
        else:
            print(f"Error: File not found: {args.input}", file=sys.stderr)
            sys.exit(1)

    # --layout: show placeholder details for a specific layout
    if args.layout:
        detail = get_layout_placeholders(template_path, args.layout)
        if not detail:
            print(f"Layout not found: {args.layout}", file=sys.stderr)
            sys.exit(1)
        print(f"layout: {detail['name']}")
        if detail.get("notes"):
            print(f"notes: {detail['notes']}")
        print()
        print("placeholders:")
        for ph in detail["placeholders"]:
            idx = f'"{ph["idx"]}"'
            pos = f'({ph["x"]}, {ph["y"]})'
            size = f'{ph["width"]}x{ph["height"]}'
            fs = ph.get("fontSize")
            fs_str = f'{fs:g} pt ({fs * 2:g} px)' if fs else ""
            desc = ph.get("description", "")
            print(f"  {idx:<5} {pos:<14} {size:<10} {fs_str:<16} {desc}")
        return

    # Full analysis
    result = analyze_template(template_path)

    # Generate color usage and cache preview PNGs if not cached
    if not result["color_usage"]:
        import subprocess

        from sdpm.engine.analyzer import cache_color_usage, cache_preview_pngs, extract_color_usage_from_pngs
        from sdpm.engine.preview import export_pdf
        import tempfile as _tf
        preview_dir = Path(_tf.mkdtemp())
        try:
            pdf_path = preview_dir / "slides.pdf"
            if export_pdf(template_path, pdf_path):
                subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
                    ["pdftoppm", "-png", "-scale-to", "1280", str(pdf_path), str(preview_dir / "page")],
                    capture_output=True, text=True,
                )
                pdf_path.unlink(missing_ok=True)
        except Exception:
            pass
        usage = extract_color_usage_from_pngs(preview_dir)
        if usage:
            cache_color_usage(template_path, usage)
            result["color_usage"] = usage
        cache_preview_pngs(template_path, preview_dir)

    print(f"template: {template_path.name}")
    sz = result["slide_size"]
    print(f"slideSize: {sz['width']}x{sz['height']}")
    fonts = result.get("fonts", {})
    print("fonts:")
    print(f"  fullwidth: {fonts.get('fullwidth', 'N/A')}")
    print(f"  halfwidth: {fonts.get('halfwidth', 'N/A')}")

    print()
    print("themeColors:")
    for role, color in result["theme_colors"].items():
        print(f"  {role:<15} {color}")

    if result["color_usage"]:
        print()
        print("colorUsage:")
        top5 = result["color_usage"][:5]
        for c in top5:
            print(f"  {c['color']}  {c['percentage']:5.1f}%")
        rest = sum(c["percentage"] for c in result["color_usage"][5:])
        if rest > 0:
            print(f"  other    {rest:5.1f}%")

    print()
    print("layouts:")
    for layout in result["layouts"]:
        print(f'  "layout": "{layout["name"]}"')
        if layout.get("notes"):
            print(f"  {layout['notes']}")
        print()

    ts = result.get("table_styles", {})
    if ts.get("styles"):
        print("tableStyles:")
        for s in ts["styles"]:
            default_mark = " ★default" if s["name"] == ts.get("default") else ""
            print(f'  "{s["name"]}"{default_mark}')
            print(f'    {s["description"]}')
        print()


def cmd_image_size(args):
    """Show image dimensions and calculate size preserving aspect ratio."""
    from PIL import Image

    p = Path(args.input)
    if not p.is_file():
        print(f"Error: Not found: {p}", file=sys.stderr)
        sys.exit(1)

    try:
        img = Image.open(p)
        w, h = img.size
        ratio = w / h
        if args.width:
            calc_h = round(args.width / ratio)
            print(f"{w}x{h} → width={args.width}, height={calc_h}")
        elif args.height:
            calc_w = round(args.height * ratio)
            print(f"{w}x{h} → width={calc_w}, height={args.height}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_grid(args):
    """Compute CSS Grid layout coordinates."""
    from sdpm.engine.layout.grid import compute_grid

    if args.input == "-":
        spec = json.loads(sys.stdin.read())
    else:
        spec = read_json(Path(args.input))
    result = compute_grid(spec)
    if args.output:
        write_json(Path(args.output), result)
    else:
        print(json.dumps(result, indent=2))


def cmd_diff(args):
    """Compare two slide JSONs (or PPTXs) and show manual edit changes."""
    from sdpm.api import diff_report
    result = diff_report(args.baseline, args.edited)
    print(result["report"])


def main():
    parser = argparse.ArgumentParser(description="PPTX Builder")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_gen = subparsers.add_parser("generate", help="Generate PPTX from JSON")
    p_gen.add_argument("input", nargs="?", help="Input JSON file (or - for stdin)")
    p_gen.add_argument("-o", "--output", required=True, help="Output PPTX path")
    p_gen.add_argument("--keep-empty-placeholders", action="store_true", help="Keep empty placeholders visible")

    p_prev = subparsers.add_parser("preview", help="Export slides as PNG images")
    p_prev.add_argument("input", help="Input JSON file")
    p_prev.add_argument("-p", "--pages", help="Pages to export (e.g. 1,3,5)")
    p_prev.add_argument("--no-grid", action="store_true", help="Disable 5%% grid overlay")
    p_prev.add_argument(
        "-o", "--output-dir",
        help="Directory for the PNG files (e.g. {deck_dir}/preview). "
             "Default: a fresh temporary directory under _work/",
    )

    p_meas = subparsers.add_parser("measure", help="Measure text bounding boxes from slides JSON")
    p_meas.add_argument("input", help="Input JSON file")
    p_meas.add_argument("-p", "--pages", help="Slide numbers to measure (e.g. 1,3,5)")

    p_search = subparsers.add_parser("search-assets", help="Search assets (icons, images, etc.)")
    p_search.add_argument("query", help="Search keywords (space-separated)")
    p_search.add_argument("-n", "--limit", type=int, default=20, help="Max results (default: 20)")
    p_search.add_argument("-s", "--source", help="Filter by source (e.g. aws, material)")
    p_search.add_argument("-t", "--type", help="Filter by type (e.g. service, resource)")
    p_search.add_argument("--theme", choices=["light", "dark"], help="Filter by theme (light/dark)")

    # Backward-compatible alias removed (icon-search was alias for search-assets)

    subparsers.add_parser("list-asset-sources", help="List available asset sources")
    subparsers.add_parser("list-templates", help="List available PPTX templates")

    p_ex = subparsers.add_parser("examples", help="List or show design pattern/component examples")
    p_ex.add_argument("names", nargs="*", help="Example names to show (multiple allowed)")
    p_ex.add_argument("--no-browse", action="store_true", help="Don't open browser for styles")

    p_exs = subparsers.add_parser("search-patterns", help="Search patterns by keywords")
    p_exs.add_argument("query", help="Search keywords (space-separated)")
    p_exs.add_argument("-n", "--limit", type=int, default=5, help="Max results")

    p_wf = subparsers.add_parser("workflows", help="List or show workflow documents")
    p_wf.add_argument("names", nargs="*", help="Workflow names to show (multiple allowed)")

    p_gd = subparsers.add_parser("guides", help="List or show guide documents")
    p_gd.add_argument("names", nargs="*", help="Guide names to show (multiple allowed)")

    p_init = subparsers.add_parser("init", help="Initialize output directory with empty presentation JSON")
    p_init.add_argument("name", nargs="?", help="Presentation name (e.g. 'my-proposal')")
    p_init.add_argument("-o", "--output", help="Output directory (overrides default)")

    p_layout = subparsers.add_parser("layout", help="Compute layout coordinates from logical structure JSON")

    p_code = subparsers.add_parser("code-block", help="Generate elements JSON for syntax-highlighted code block")
    p_code.add_argument("input", help="Source code file (or - for stdin)")
    p_code.add_argument("-o", "--output", help="Output elements JSON file (default: stdout)")
    p_code.add_argument("--language", "-l", default="text", help="Language for highlighting (default: text)")
    p_code.add_argument("--x", type=int, default=0, help="X position (px)")
    p_code.add_argument("--y", type=int, default=0, help="Y position (px)")
    p_code.add_argument("--width", type=int, default=800, help="Width (px)")
    p_code.add_argument("--height", type=int, default=300, help="Height (px)")
    p_code.add_argument("--font-size", type=int, default=12, help="Font size (pt, default: 12)")
    p_code.add_argument("--font-family", default="Consolas", help="Font family (default: Consolas)")
    p_code.add_argument("--theme", choices=["dark", "light"], default="dark", help="Theme (default: dark)")
    p_code.add_argument("--no-label", action="store_true", help="Hide language label")
    p_layout.add_argument("input", help="Input JSON file (or - for stdin)")
    p_layout.add_argument("-o", "--output", help="Output elements JSON file (default: stdout)")
    p_layout.add_argument("--x", type=int, default=None, help="Target area X offset (px)")
    p_layout.add_argument("--y", type=int, default=None, help="Target area Y offset (px)")
    p_layout.add_argument("--width", type=int, default=None, help="Target area width (px)")
    p_layout.add_argument("--height", type=int, default=None, help="Target area height (px)")
    p_layout.add_argument("--theme", choices=["dark", "light"], default="dark", help="Theme for box text colors (default: dark)")

    p_diff = subparsers.add_parser("diff", help="Compare two decks/JSONs/PPTXs and show changes (for manual edit detection)")
    p_diff.add_argument("baseline", help="Baseline deck directory, slides JSON, or PPTX (original)")
    p_diff.add_argument("edited", help="Edited deck directory, slides JSON, or PPTX (manually edited)")

    p_analyze = subparsers.add_parser("analyze-template", help="Analyze PPTX template: extract layouts and theme")
    p_analyze.add_argument("input", help="Template PPTX file path")
    p_analyze.add_argument("--layout", help="Show placeholder details for a specific layout name")

    p_imgsize = subparsers.add_parser("image-size", help="Calculate image size preserving aspect ratio")
    p_imgsize.add_argument("input", help="Image file path")
    p_imgsize_group = p_imgsize.add_mutually_exclusive_group(required=True)
    p_imgsize_group.add_argument("--width", type=int, help="Target width → calculate height")
    p_imgsize_group.add_argument("--height", type=int, help="Target height → calculate width")

    p_grid = subparsers.add_parser("grid", help="Compute CSS Grid layout coordinates")
    p_grid.add_argument("input", help="Input JSON file (or - for stdin)")
    p_grid.add_argument("-o", "--output", help="Output JSON file (default: stdout)")

    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(args)
    elif args.command == "preview":
        cmd_preview(args)
    elif args.command == "measure":
        cmd_measure(args)
    elif args.command == "search-assets":
        cmd_search_assets(args)
    elif args.command == "list-asset-sources":
        cmd_list_asset_sources(args)
    elif args.command == "list-templates":
        cmd_list_templates(args)
    elif args.command == "examples":
        cmd_examples(args)
    elif args.command == "search-patterns":
        cmd_search_patterns(args)
    elif args.command == "workflows":
        cmd_workflows(args)
    elif args.command == "guides":
        cmd_guides(args)
    elif args.command == "init":
        cmd_init(args)
    elif args.command == "layout":
        cmd_layout(args)
    elif args.command == "code-block":
        cmd_code_block(args)
    elif args.command == "diff":
        cmd_diff(args)
    elif args.command == "analyze-template":
        cmd_analyze_template(args)
    elif args.command == "image-size":
        cmd_image_size(args)
    elif args.command == "grid":
        cmd_grid(args)

if __name__ == "__main__":
    main()
