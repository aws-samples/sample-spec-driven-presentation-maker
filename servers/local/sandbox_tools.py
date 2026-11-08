# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Sandboxed Python execution tools — shared by server.py and server_acp.py.

These tools run user code in restricted subprocesses with optional
deck file I/O via sandbox functions. Not ACP-specific.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field


def _rejection_message(violations: list[str]) -> str:
    """Build an error message that helps the LLM rewrite rejected code."""
    lines = ["Code rejected by sandbox:"]
    lines.extend(f"  {v}" for v in violations)
    lines.append("")
    lines.append("Use sandbox functions instead:")
    lines.append("  read_json(path) → dict    write_json(path, data)")
    lines.append("  read_text(path) → str     write_text(path, text)")
    lines.append('  list_files(subdir=".") → list[str]  (folders end with "/")')
    return "\n".join(lines)


def _similar_decks(deck_id: str, limit: int = 5) -> list[str]:
    """Deck folders in the output directory named ``<name>`` or ``…-<name>`` (deck folders are
    ``YYYYMMDD-HHMM-<name>``), where ``<name>`` is the last part of *deck_id*; newest first."""
    name = Path(deck_id).name if deck_id else ""
    if not name:
        return []
    from sdpm.api import _get_output_base_dir

    try:
        root = _get_output_base_dir()
        found = [p for p in root.iterdir() if p.is_dir() and (p.name == name or p.name.endswith(f"-{name}"))]
    except OSError:
        return []
    return [str(p) for p in sorted(found, key=lambda p: p.name, reverse=True)[:limit]]


def _build_snapshot(deck_dir: Path) -> dict[str, tuple[int, int]]:
    """Snapshot (mtime_ns, size) of files that affect the built PPTX.

    Used to detect whether a run_python execution changed the deck, so the
    output.pptx artifact can be rebuilt automatically. specs/outline.md is
    included because slide order comes from the outline. HTML decks also
    watch slides/*.html, specs/art-direction.html and deck.css (output.html).
    """
    from sdpm.engine.schema import read_deck_format

    snap: dict[str, tuple[int, int]] = {}
    try:
        html_deck = read_deck_format(deck_dir) == "html"
    except ValueError:
        html_deck = False
    rels = ["deck.json", "presentation.json", "specs/outline.md"]
    globs = [("slides", "*.json"), ("includes", "*.json")]
    if html_deck:
        rels += ["specs/art-direction.html", "deck.css"]
        globs.append(("slides", "*.html"))
    for rel in rels:
        p = deck_dir / rel
        if p.is_file():
            st = p.stat()
            snap[rel] = (st.st_mtime_ns, st.st_size)
    for sub, pattern in globs:
        d = deck_dir / sub
        if d.is_dir():
            for p in d.glob(pattern):
                st = p.stat()
                snap[f"{sub}/{p.name}"] = (st.st_mtime_ns, st.st_size)
    return snap


def _refresh_html_deck(
    deck_dir: Path,
    pre_snap: dict[str, tuple[int, int]],
    measure_slides: list[str] | None,
    result: dict[str, Any],
) -> None:
    """HTML-deck post-processing: rebuild output.html, static checks, and the browser
    check (layout, JS errors, PNG previews) of the affected and measured slides.

    Runs when a watched file changed or measure_slides was given, and merges the
    sdpm.api.refresh_html result into ``result`` (warnings extend, other keys set).
    """
    post_snap = _build_snapshot(deck_dir)
    changed_paths = sorted(k for k in pre_snap.keys() | post_snap.keys() if pre_snap.get(k) != post_snap.get(k))
    if not changed_paths and not measure_slides:
        return
    from sdpm.api import refresh_html
    from sdpm.knowledge.assets import invalidate_manifest_cache

    invalidate_manifest_cache()
    refreshed = refresh_html(deck_dir, changed_paths, list(measure_slides) if measure_slides else None)
    refreshed.pop("script_external", None)  # the warnings already name these; it feeds the remote record
    warnings = refreshed.pop("warnings", [])
    if warnings:
        existing = result.get("warnings")
        if isinstance(existing, dict):  # the outline lint's {"outline": …}
            existing["html"] = warnings
        else:
            result.setdefault("warnings", []).extend(warnings)
    result.update(refreshed)


def run_python(
    purpose: Annotated[str, Field(description='One line on what this code does (shown in the UI).')],
    code: Annotated[str, Field(description='Python code; no import statements.')],
    deck_id: Annotated[str, Field(description='Deck directory path.')],
    measure_slides: Annotated[list[str] | None, Field(description='Slugs to measure for text overflow after the code ran — the ones you edited.')] = None,
) -> str:
    """Run Python inside the deck directory — the way to read and write deck files
    (deck.json, specs/, slides/, includes/). No import or open(); helpers:
    read_json(path), write_json(path, data), read_text(path), write_text(path, text),
    list_files(subdir=".") (folders end with "/"). Writes persist; output.pptx (output.html for HTML decks)
    rebuilds and changed slides are re-rendered and previewed when deck.json, slides/,
    includes/ or specs/outline.md changed. measure_slides measures text overflow on those
    slugs and previews them; HTML decks get static checks plus browser layout / JS checks
    and PNG previews when Chrome or Edge is available.
    """
    result: dict[str, Any] = {}
    if not deck_id or not Path(deck_id).is_dir():
        result["error"] = (
            f"deck directory not found: {deck_id!r}. run_python runs inside a deck "
            "workspace — pass the output_dir returned by init_deck_workspace."
        )
        similar = _similar_decks(deck_id)
        if similar:
            result["error"] += " Decks with that name: " + ", ".join(similar)
        return json.dumps(result, ensure_ascii=False)
    cwd = deck_id

    from sandbox import check_code, make_runner

    violations = check_code(code)
    if violations:
        result["output"] = _rejection_message(violations)
        return json.dumps(result, ensure_ascii=False)

    pre_snap = _build_snapshot(Path(cwd))

    try:
        runner = make_runner(deck_id)
        args = [sys.executable, "-c", runner, deck_id]
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

    # Lint outline.md
    outline_path = deck_dir / "specs" / "outline.md"
    if outline_path.exists() and outline_path.read_text(encoding="utf-8").strip():
        from sdpm.engine.schema.lint_outline import lint_outline
        if lint_outline(outline_path.read_text(encoding="utf-8")):
            result.setdefault("warnings", {})["outline"] = (
                "outline.md format violation. "
                "Read workflow `orchestrator` for the outline format."
            )

    from sdpm.engine.schema import read_deck_format

    try:
        deck_format = read_deck_format(deck_dir)
    except ValueError as e:
        # An explicit invalid outputFormat stops the build: no PPTX is produced.
        result.setdefault("errors", {})["outputFormat"] = str(e)
        return json.dumps(result, ensure_ascii=False)
    if deck_format == "html":
        _refresh_html_deck(deck_dir, pre_snap, measure_slides, result)
        return json.dumps(result, ensure_ascii=False)

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

    # Post-processing (sdpm.api.refresh_pptx): output.pptx follows deck changes,
    # and so do live-preview data (compose/) and preview images — every slide the
    # change can alter is rendered, measured or not. measure_slides adds its slugs
    # to the render set and is the only trigger for measurement.
    post_snap = _build_snapshot(deck_dir)
    changed_paths = sorted(k for k in pre_snap.keys() | post_snap.keys() if pre_snap.get(k) != post_snap.get(k))
    if changed_paths or measure_slides:
        from sdpm.api import refresh_pptx
        from sdpm.knowledge.assets import invalidate_manifest_cache

        invalidate_manifest_cache()
        with refresh_pptx(deck_dir, changed_paths, measure_slides) as refresh:
            refresh.merge_into(result)
            if refresh.pptx_path is not None:
                result["pptx"] = str(refresh.pptx_path)
            if refresh.render_slugs:
                _write_compose(deck_dir, refresh, result)
                _write_previews(deck_dir, refresh, result)
            if refresh.render_error:
                # The automatic re-render never fails the tool call: the writes
                # are persisted and output.pptx is already rebuilt.
                result["render_error"] = refresh.render_error

    return json.dumps(result, ensure_ascii=False)


def _write_compose(deck_dir: Path, refresh: Any, result: dict[str, Any]) -> None:
    """Write the refresh's compose payloads to compose/<slug>_<epoch>.json and
    compose/defs_<epoch>.json; older files of the written slugs and older defs go."""
    from shared.artifact_keys import COMPOSE_DEFS, compose_key, latest_compose_keys, superseded_compose_keys

    compose_dir = deck_dir / "compose"
    names = [f.name for f in compose_dir.iterdir()] if compose_dir.is_dir() else []
    latest = latest_compose_keys(names)
    previous: dict[str, dict] = {}
    for slug in refresh.compose_slugs:
        if slug in latest:
            try:
                previous[slug] = json.loads((compose_dir / latest[slug]).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
    composed = refresh.compose(previous)
    if composed.defs is not None:
        epoch = int(time.time())
        compose_dir.mkdir(exist_ok=True)
        (compose_dir / compose_key("", COMPOSE_DEFS, epoch)).write_text(
            json.dumps(composed.defs, ensure_ascii=False), encoding="utf-8")
        for slug, payload in composed.slides.items():
            (compose_dir / compose_key("", slug, epoch)).write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        for name in superseded_compose_keys(names, "", (COMPOSE_DEFS, *composed.slides), epoch):
            (compose_dir / name).unlink(missing_ok=True)
        result["compose"] = f"{len(composed.slides)} slides composed"
    if composed.error or composed.shortfall:
        result["compose_error"] = composed.error or composed.shortfall


def _write_previews(deck_dir: Path, refresh: Any, result: dict[str, Any]) -> None:
    """Copy the refresh's PNGs to preview/<slug>.png (render_slugs, deck order)."""
    import shutil

    shots = refresh.previews(scale_to=1280)
    if shots.error:
        result["preview_error"] = shots.error
    if not shots.rendered:
        return
    preview_dir = deck_dir / "preview"
    preview_dir.mkdir(exist_ok=True)
    files = []
    for slug, png in shots.files.items():
        dst = preview_dir / f"{slug}.png"
        shutil.copy2(png, dst)
        files.append(str(dst))
    result["preview_files"] = files
    if shots.missing:
        # Surface the silent gap instead of returning [].
        result["preview_error"] = f"No PNG matched slugs {shots.missing}; pdftoppm produced {shots.produced}"


def run_style_python(
    purpose: Annotated[str, Field(description='One line on what this code does (shown in the UI).')],
    code: Annotated[str, Field(description='Python code; no import statements.')],
) -> str:
    """Run Python for style authoring. Helpers: read_style(name) returns an existing style's
    HTML (bundled or user); write_style(name, html) saves to the user style store
    (name = file stem, no .html). No import or file access; print() for output.
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
