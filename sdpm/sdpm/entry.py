# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Role entry payloads — everything a role needs before its first real step.

Each ``start_*`` function returns the role document plus what that role always
reads at the start of its work, so a model gets its role and its inputs in one
call instead of six to eight. The payload is split in two:

- ``static`` — deck-independent (role document, slide spec). Identical across
  calls, so an outer agent may cache it (L4 places it in the system prompt).
- ``deck`` / role-specific keys — dynamic, per invocation.

Servers bind these through :mod:`sdpm.tools`; the remote server materialises
the deck from S3 into a temporary directory and calls the same functions.
Path-based on purpose: no transport or storage knowledge lives here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sdpm.config import REFERENCES_DIR

_WORKFLOWS_DIR = REFERENCES_DIR / "workflows"
_GUIDES_DIR = REFERENCES_DIR / "guides"

_DEFAULT_BASE_STYLE = "typographic"  # smallest bundled style that follows the full skeleton

# ``demo-1`` / ``demo-2`` / … form one override group; later slides inherit from
# the first (lowest number). Slugs without a ``-<n>`` suffix belong to no group.
_GROUP_MEMBER = re.compile(r"^(.+)-(\d+)$")

# Role documents and specs read once, keyed by (directory, name). None (the default)
# reads the files on every call, so editing a checkout under a running local server
# takes effect at once; a server whose references cannot change while it runs (the
# cloud image) turns the cache on with preload_references().
_reference_cache: dict[tuple[Path, str], str] | None = None


def _read_reference(directory: Path, name: str) -> str:
    from sdpm.knowledge.reference import read_docs

    cache = _reference_cache
    if cache is not None and (directory, name) in cache:
        return cache[(directory, name)]
    content = read_docs(directory, [name])[0]["content"]
    if cache is not None:
        cache[(directory, name)] = content
    return content


def preload_references() -> None:
    """Read every role document and spec the entry payloads use, and serve them from memory from now on.

    For a server whose bundled references cannot change for the life of its process.
    """
    global _reference_cache
    if _reference_cache is None:
        _reference_cache = {}
    for role in ("orchestrator", "composer", "composer-html", "style", "translate"):
        _workflow(role)
    for guide in ("slide-json-spec", "slide-html-spec", *_FORMAT_NOTES.values()):
        _read_reference(_GUIDES_DIR, guide)


def _workflow(role: str) -> str:
    return _read_reference(_WORKFLOWS_DIR, role)


def _slide_spec() -> str:
    return _read_reference(_GUIDES_DIR, "slide-json-spec")


# Orchestrator notes per deck format: the guide init_deck_workspace returns as
# ``format_notes``. PPTX has none — orchestrator.md covers it.
_FORMAT_NOTES = {"html": "html-deck"}


def format_notes(output_format: str) -> str | None:
    """What the orchestrator writes into the specs for this format; None when it needs nothing extra."""
    name = _FORMAT_NOTES.get(output_format)
    return _read_reference(_GUIDES_DIR, name) if name else None


def _read_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


_ART_DIRECTION = "specs/art-direction.html"


def _art_direction_toc(deck_path: Path) -> dict[str, Any] | None:
    """The composer's map of the deck's style; None when the deck has none.

    The style is the largest input a composer has, so it gets a table of contents
    instead of the file and reads the parts it needs. One line per ``style_toc``
    block (the ``<style>`` block, each ``.slide`` with the comments that describe
    it): ``"<start>-<end>: <comments>"``, 1-based and inclusive, the block's first
    text where it has no comments. An empty ``toc`` means the file has no such
    blocks; ``lines`` is its length either way.
    """
    html = _read_text(deck_path / _ART_DIRECTION)
    if html is None:
        return None
    from sdpm.api import style_toc

    toc = [f"{e['start']}-{e['end']}: {e.get('comment') or e['text']}" for e in style_toc(html)]
    return {"path": _ART_DIRECTION, "lines": len(html.splitlines()), "toc": toc}


def _styles() -> list[dict]:
    from sdpm.api import get_styles_dirs, list_styles_filtered
    from sdpm.config import get_state

    # Every style, with its pin flag: a style author draws on the whole catalogue.
    return list_styles_filtered(get_styles_dirs(), get_state().get("pinned_styles", []), include_all=True)


def _templates() -> list[dict]:
    from sdpm.api import get_templates_dirs, list_templates_with_metadata
    from sdpm.config import get_builtin_template_notes, get_state

    return list_templates_with_metadata(
        get_templates_dirs(), get_state().get("template_metadata", {}), get_builtin_template_notes()
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def start_presentation(
    *,
    templates: list[dict] | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Orchestrator entry: role document + the environment it always asks about first.

    The styles come from ``list_styles``, which the orchestrator calls when it picks
    one. Keyword overrides let a server whose templates live elsewhere (S3) supply
    its own list; the local filesystem is the default.
    """
    if templates is None:
        templates = _templates()
    if output_dir is None:
        from sdpm.api import _get_output_base_dir

        output_dir = str(_get_output_base_dir())
    return {
        "static": {"workflow": _workflow("orchestrator")},
        "templates": templates,
        "output_dir": output_dir,
    }


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


def _group_of(slug: str) -> tuple[str, int] | None:
    m = _GROUP_MEMBER.match(slug)
    return (m.group(1), int(m.group(2))) if m else None


def _group_heads(present: list[str], assigned: set[str]) -> set[str]:
    """Group heads that an assigned slide inherits from but that are not assigned."""
    by_group: dict[str, list[tuple[int, str]]] = {}
    for slug in present:
        g = _group_of(slug)
        if g:
            by_group.setdefault(g[0], []).append((g[1], slug))
    heads: set[str] = set()
    for slug in assigned:
        g = _group_of(slug)
        if not g or len(by_group.get(g[0], [])) < 2:
            continue
        head = min(by_group[g[0]])[1]
        if head != slug and head not in assigned:
            heads.add(head)
    return heads


def _template_analysis(deck_json: dict) -> dict | None:
    template = deck_json.get("template") or ""
    if not template:
        return None
    from sdpm.api import _find_template_in_dirs, get_templates_dirs
    from sdpm.engine.analyzer import analyze_template

    path = Path(template)
    if not path.exists():
        found = _find_template_in_dirs(template, get_templates_dirs())
        if found is None:
            return None
        path = found
    try:
        return analyze_template(path)
    except Exception:  # analysis is an aid, never a blocker
        return None


_TEMPLATE_HTML_KEYS = ("slideSize", "ptScale", "fonts", "themeColors", "ground")


def _template_html(deck_json: dict, deck_path: Path) -> dict | None:
    """``template_html_view`` of the deck's template; None when it has none or it cannot be resolved."""
    if not deck_json.get("template"):
        return None
    from sdpm.api import _resolve_template, get_templates_dirs

    try:
        path, _ = _resolve_template(deck_json, deck_path, get_templates_dirs())
    except Exception:
        return None
    return template_html_view(path)


def template_html_view(template_path: str | Path, *, cache_root: str | Path | None = None) -> dict | None:
    """The HTML composer's view of a template: template.json, curated layouts only.

    All layouts when the template curates none. ``decorations_status`` reports, in
    the preview-unavailable shape, that the decoration artwork cannot be rendered
    (LibreOffice / poppler missing and no bundled or cached SVGs); None otherwise.
    ``cache_root`` overrides the template-conversion cache directory. An aid, never
    a blocker: any failure returns None.
    """
    from sdpm.engine.html.decorations import decoration_tools_status
    from sdpm.engine.html.template import decorations_complete, load_template_html

    try:
        converted = load_template_html(Path(template_path), decorations=False, cache_root=cache_root)
    except Exception:
        return None
    info = converted.info
    layouts = list(info.get("layouts", []))
    view: dict[str, Any] = {key: info.get(key) for key in _TEMPLATE_HTML_KEYS}
    view["layouts"] = [layout for layout in layouts if layout.get("curated")] or layouts
    rendered = decorations_complete(info, converted.dir / "layouts")
    view["decorations_status"] = None if rendered else decoration_tools_status()
    return view


_COMPOSER_MODES = ("pptx", "html")


def _composer_static(mode: str) -> dict[str, str]:
    if mode == "html":
        return {"workflow": _workflow("composer-html"), "slide_spec": _read_reference(_GUIDES_DIR, "slide-html-spec")}
    return {"workflow": _workflow("composer"), "slide_spec": _slide_spec()}


def _existing_slides(slides_dir: Path, present: list[str], assigned: list[str], suffix: str) -> dict[str, dict]:
    """Assigned slides' text keyed by slug, plus read-only override-group heads."""
    assigned_set = set(assigned)
    wanted = [s for s in present if s in assigned_set]
    heads = _group_heads(present, assigned_set)
    existing: dict[str, dict] = {}
    for slug in wanted + sorted(heads):
        entry: dict[str, Any] = {suffix: (slides_dir / f"{slug}.{suffix}").read_text(encoding="utf-8")}
        if slug in heads:
            entry["readonly"] = True
        existing[slug] = entry
    return existing


def start_composing(
    deck_dir: str | Path | None = None,
    assigned_slugs: list[str] | None = None,
    *,
    deck_id: str | None = None,
    template_analysis: dict | None = None,
    template_html: dict | None = None,
    mode: str = "pptx",
) -> dict[str, Any]:
    """Composer entry.

    Without ``deck_dir`` returns only ``static`` (role document + slide spec for
    ``mode``). With a deck, validates the specs first; when they fail, returns
    ``{"specs_ok": False, "errors": [...]}`` and nothing else — a composer must
    not start from broken specs. Otherwise returns ``static`` plus ``deck``:
    the specs (the style as ``art_direction_toc``, a table of contents of
    specs/art-direction.html the composer reads parts of), deck.json, template
    analysis, and the assigned slides' JSON (with read-only override-group heads
    the assigned slides inherit from). ``static.slide_spec`` is the core of the
    slide format; the rest is in guides it names.

    ``mode`` is the composer mode the spawner chose: ``"pptx"`` (slide JSON) or
    ``"html"`` (slide HTML). ``static`` depends only on the mode. A mode that does
    not match deck.json ``outputFormat`` returns ``specs_ok`` false with the deck's
    format as ``mode``. In html mode the deck part carries the slides' HTML, the
    deck-root ``deck.css`` (``deck_css``, None when absent) and ``template_html``
    instead of ``template_analysis``.

    ``deck_id`` labels the payload when ``deck_dir`` is a materialised copy of a deck
    that lives elsewhere; ``template_analysis`` likewise lets such a server supply the
    analysis of a template the local filesystem cannot see (``template_html`` is the
    html-mode counterpart, a ``template_html_view`` result).
    """
    if mode not in _COMPOSER_MODES:
        return {"specs_ok": False, "errors": ['mode must be "pptx" or "html"'], "warnings": []}
    static = _composer_static(mode)
    if deck_dir is None or str(deck_dir) == "":
        return {"static": static}

    from sdpm.api import check_specs
    from sdpm.engine.schema import deck_output_format

    assigned = list(assigned_slugs or [])
    deck_path = Path(deck_dir)
    verdict = check_specs(deck_path, assigned or None)
    if not verdict.get("ok"):
        return {"specs_ok": False, "errors": verdict.get("errors", []), "warnings": verdict.get("warnings", [])}

    deck_json = json.loads((deck_path / "deck.json").read_text(encoding="utf-8"))
    try:
        fmt = deck_output_format(deck_json)
    except ValueError as exc:
        return {"specs_ok": False, "errors": [str(exc)], "warnings": verdict.get("warnings", [])}
    if fmt != mode:
        return {
            "specs_ok": False,
            "errors": [f'deck outputFormat is {fmt}; call start_composing(deck_id, assigned_slugs, mode="{fmt}")'],
            "warnings": verdict.get("warnings", []),
            "mode": fmt,
        }

    specs = deck_path / "specs"
    slides_dir = deck_path / "slides"
    suffix = "html" if mode == "html" else "json"
    present = sorted(p.stem for p in slides_dir.glob(f"*.{suffix}")) if slides_dir.is_dir() else []
    existing = _existing_slides(slides_dir, present, assigned, suffix)

    if mode == "html":
        return {
            "static": static,
            "deck": {
                "deck_id": deck_id or str(deck_path),
                "deck": deck_json,
                "brief": _read_text(specs / "brief.md"),
                "outline": _read_text(specs / "outline.md"),
                "art_direction_toc": _art_direction_toc(deck_path),
                "deck_css": _read_text(deck_path / "deck.css"),
                "template_html": template_html if template_html is not None else _template_html(deck_json, deck_path),
                "assigned_slugs": assigned,
                "slides_present": present,
                "existing_slides": existing,
                "specs_ok": True,
                "warnings": verdict.get("warnings", []),
            },
        }

    return {
        "static": static,
        "deck": {
            "deck_id": deck_id or str(deck_path),
            "deck": deck_json,
            "brief": _read_text(specs / "brief.md"),
            "outline": _read_text(specs / "outline.md"),
            "art_direction_toc": _art_direction_toc(deck_path),
            "template_analysis": template_analysis if template_analysis is not None else _template_analysis(deck_json),
            "assigned_slugs": assigned,
            "slides_present": present,
            "existing_slides": existing,
            "specs_ok": True,
            "warnings": verdict.get("warnings", []),
        },
    }


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------


def start_style(
    base: str = "",
    *,
    styles: list[dict] | None = None,
    base_html: str | None = None,
) -> dict[str, Any]:
    """Style entry: role document, the style catalogue, and one bundled style to imitate.

    Keyword overrides serve a server whose styles live elsewhere (S3).
    """
    name = base or _DEFAULT_BASE_STYLE
    if styles is None:
        styles = _styles()
    if base_html is None:
        from sdpm.api import _find_style_in_dirs, get_styles_dirs

        path = _find_style_in_dirs(name, get_styles_dirs())
        if path is None:
            raise FileNotFoundError(f"Style not found: {name}")
        base_html = path.read_text(encoding="utf-8")
    return {
        "static": {"workflow": _workflow("style")},
        "styles": styles,
        "base": {"name": name, "html": base_html},
    }


# ---------------------------------------------------------------------------
# Translate
# ---------------------------------------------------------------------------


def start_translation(deck_dir: str | Path, language: str) -> dict[str, Any]:
    """Translate entry: role document, slide spec, and the source deck's shape."""
    deck_path = Path(deck_dir)
    deck_json_path = deck_path / "deck.json"
    if not deck_json_path.is_file():
        raise FileNotFoundError(f"Not an sdpm deck (deck.json missing): {deck_path}")
    from sdpm.engine.schema import deck_output_format

    deck_json = json.loads(deck_json_path.read_text(encoding="utf-8"))
    if deck_output_format(deck_json) == "html":
        raise ValueError("start_translation supports PPTX decks only; this deck has outputFormat html")
    slides_dir = deck_path / "slides"
    present = sorted(p.stem for p in slides_dir.glob("*.json")) if slides_dir.is_dir() else []
    sibling = deck_path.with_name(f"{deck_path.name}-{language}")
    return {
        "static": {"workflow": _workflow("translate"), "slide_spec": _slide_spec()},
        "deck": {
            "deck_id": str(deck_path),
            "deck": deck_json,
            "slides_present": present,
            "language": language,
            "sibling": str(sibling),
            "sibling_exists": sibling.exists(),
        },
    }
