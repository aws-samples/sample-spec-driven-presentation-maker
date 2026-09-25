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


def _read_reference(directory: Path, name: str) -> str:
    from sdpm.knowledge.reference import read_docs

    return read_docs(directory, [name])[0]["content"]


def _workflow(role: str) -> str:
    return _read_reference(_WORKFLOWS_DIR, role)


def _slide_spec() -> str:
    return _read_reference(_GUIDES_DIR, "slide-json-spec")


def _read_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _styles_and_templates() -> tuple[list[dict], list[dict]]:
    from sdpm.api import (
        get_styles_dirs,
        get_templates_dirs,
        list_styles_filtered,
        list_templates_with_metadata,
    )
    from sdpm.config import get_state

    state = get_state()
    # Every style, with its pin flag: the pin filter is a gallery concern, the
    # orchestrator should know the whole catalogue when it picks.
    styles = list_styles_filtered(get_styles_dirs(), state.get("pinned_styles", []), include_all=True)
    templates = list_templates_with_metadata(get_templates_dirs(), state.get("template_metadata", {}))
    return styles, templates


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def start_presentation(
    *,
    styles: list[dict] | None = None,
    templates: list[dict] | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Orchestrator entry: role document + the environment it always asks about first.

    Keyword overrides let a server whose styles/templates live elsewhere (S3) supply
    its own lists; the local filesystem is the default.
    """
    if styles is None or templates is None:
        fs_styles, fs_templates = _styles_and_templates()
        styles = fs_styles if styles is None else styles
        templates = fs_templates if templates is None else templates
    if output_dir is None:
        from sdpm.api import _get_output_base_dir

        output_dir = str(_get_output_base_dir())
    return {
        "static": {"workflow": _workflow("orchestrator")},
        "styles": styles,
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


def start_composing(
    deck_dir: str | Path | None = None,
    assigned_slugs: list[str] | None = None,
    *,
    deck_id: str | None = None,
    template_analysis: dict | None = None,
) -> dict[str, Any]:
    """Composer entry.

    Without ``deck_dir`` returns only ``static`` (role document + slide spec).
    With a deck, validates the specs first; when they fail, returns
    ``{"specs_ok": False, "errors": [...]}`` and nothing else — a composer must
    not start from broken specs. Otherwise returns ``static`` plus ``deck``:
    the specs, deck.json, template analysis, and the assigned slides' JSON
    (with read-only override-group heads the assigned slides inherit from).

    ``deck_id`` labels the payload when ``deck_dir`` is a materialised copy of a deck
    that lives elsewhere; ``template_analysis`` likewise lets such a server supply the
    analysis of a template the local filesystem cannot see.
    """
    static = {"workflow": _workflow("composer"), "slide_spec": _slide_spec()}
    if deck_dir is None or str(deck_dir) == "":
        return {"static": static}

    from sdpm.api import check_specs

    assigned = list(assigned_slugs or [])
    deck_path = Path(deck_dir)
    verdict = check_specs(deck_path, assigned or None)
    if not verdict.get("ok"):
        return {"specs_ok": False, "errors": verdict.get("errors", []), "warnings": verdict.get("warnings", [])}

    deck_json = json.loads((deck_path / "deck.json").read_text(encoding="utf-8"))
    specs = deck_path / "specs"
    slides_dir = deck_path / "slides"
    present = sorted(p.stem for p in slides_dir.glob("*.json")) if slides_dir.is_dir() else []

    assigned_set = set(assigned)
    wanted = [s for s in present if s in assigned_set]
    heads = _group_heads(present, assigned_set)
    existing: dict[str, dict] = {}
    for slug in wanted + sorted(heads):
        entry: dict[str, Any] = {"json": (slides_dir / f"{slug}.json").read_text(encoding="utf-8")}
        if slug in heads:
            entry["readonly"] = True
        existing[slug] = entry

    return {
        "static": static,
        "deck": {
            "deck_id": deck_id or str(deck_path),
            "deck": deck_json,
            "brief": _read_text(specs / "brief.md"),
            "outline": _read_text(specs / "outline.md"),
            "art_direction": _read_text(specs / "art-direction.html"),
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
        styles, _ = _styles_and_templates()
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
    slides_dir = deck_path / "slides"
    present = sorted(p.stem for p in slides_dir.glob("*.json")) if slides_dir.is_dir() else []
    sibling = deck_path.with_name(f"{deck_path.name}-{language}")
    return {
        "static": {"workflow": _workflow("translate"), "slide_spec": _slide_spec()},
        "deck": {
            "deck_id": str(deck_path),
            "deck": json.loads(deck_json_path.read_text(encoding="utf-8")),
            "slides_present": present,
            "language": language,
            "sibling": str(sibling),
            "sibling_exists": sibling.exists(),
        },
    }
