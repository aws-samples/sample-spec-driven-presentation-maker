# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Which slides a set of deck-file changes can alter the rendering of.

Servers use this to decide which slides get fresh live-preview data
(compose JSON) and preview images after ``run_python``, independent of the
slugs the agent asked to measure — an edit the agent forgot to measure must
still reach the Web UI.
"""

import json
from collections.abc import Iterable, Mapping

# Deck-wide inputs: template, fonts, colours, slide order / page numbers.
_DECK_WIDE = frozenset({"deck.json", "presentation.json", "specs/outline.md"})


def _slide_path_slug(path: str) -> str | None:
    if path.startswith("slides/") and path.endswith(".json") and path.count("/") == 1:
        return path[len("slides/"):-len(".json")]
    return None


def affected_slugs(changed_paths: Iterable[str], slides: Mapping[str, dict]) -> list[str]:
    """Return the slugs whose rendering the changed files can alter.

    Args:
        changed_paths: Deck-relative paths that changed (``slides/a.json``,
            ``includes/code.json``, ``deck.json`` ...). Other paths are ignored.
        slides: ``slug -> slide JSON`` (overrides unresolved) in deck order.

    Returns:
        Affected slugs in deck order:
        - ``deck.json`` / ``presentation.json`` / ``specs/outline.md`` → every slide
        - ``slides/<slug>.json`` → that slide
        - ``includes/<name>.json`` → every slide that references it
        - plus, transitively, every slide that inherits from an affected one
          via ``"override"``
    """
    changed = [p.replace("\\", "/").removeprefix("./") for p in changed_paths]
    if any(p in _DECK_WIDE for p in changed):
        return list(slides)

    hit: set[str] = set()
    includes = [p for p in changed if p.startswith("includes/")]
    serialized: dict[str, str] = {}
    for path in changed:
        slug = _slide_path_slug(path)
        if slug is not None and slug in slides:
            hit.add(slug)
    if includes:
        for slug, slide in slides.items():
            text = serialized.setdefault(slug, json.dumps(slide, ensure_ascii=False))
            if any(inc in text for inc in includes):
                hit.add(slug)

    # Override inheritance: a slide changes when anything up its chain changes.
    def inherits_hit(slug: str) -> bool:
        seen: set[str] = set()
        cur = slides.get(slug, {}).get("override")
        while isinstance(cur, str) and cur not in seen:
            if cur in hit:
                return True
            seen.add(cur)
            cur = slides.get(cur, {}).get("override")
        return False

    return [s for s in slides if s in hit or inherits_hit(s)]


def with_override_bases(slugs: Iterable[str], slides: Mapping[str, dict]) -> list[str]:
    """Return ``slugs`` plus every slide they inherit from via ``"override"``, in deck order.

    A partial build (only some slugs) needs the override bases present, or the
    builder cannot resolve the inheritance chain.
    """
    keep: set[str] = set()
    for slug in slugs:
        cur: object = slug
        while isinstance(cur, str) and cur in slides and cur not in keep:
            keep.add(cur)
            cur = slides[cur].get("override")
    return [s for s in slides if s in keep]
