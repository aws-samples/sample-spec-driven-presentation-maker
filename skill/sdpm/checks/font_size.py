"""Font size token discipline check.

Verifies that every `fontSize` in a slide JSON corresponds to a `--fs-*`
token defined in the project's active style (specs/art-direction.html).

Per the Token Discipline rule (workflows/create-new-2-compose.md):
> Every fontSize in presentation.json must come from a token defined in
> the active style's :root. No ad-hoc values.

This check emits warnings only — it does not block generation. Builders
should resolve warnings before delivery.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

# Captures `--fs-name: 24pt;` style declarations under :root.
_FS_TOKEN_RE = re.compile(r"--fs-[\w-]+\s*:\s*(\d+)pt\s*;")


def parse_allowed_font_sizes(art_direction_path: Path) -> set[int]:
    """Extract allowed font sizes from `--fs-*` tokens in art-direction.html.

    Returns set of pt values. Empty set if file missing or no tokens found.
    """
    if not art_direction_path.exists():
        return set()

    text = art_direction_path.read_text(encoding="utf-8")
    return {int(m.group(1)) for m in _FS_TOKEN_RE.finditer(text)}


def _walk_font_sizes(node) -> Iterable[tuple[list[str], int]]:
    """Yield (path, fontSize) tuples found anywhere in a JSON-like structure.

    `path` is a list of keys/indices for diagnostic display.
    """
    if isinstance(node, dict):
        if "fontSize" in node and isinstance(node["fontSize"], (int, float)):
            yield ([], int(node["fontSize"]))
        for k, v in node.items():
            for sub_path, fs in _walk_font_sizes(v):
                yield ([str(k)] + sub_path, fs)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            for sub_path, fs in _walk_font_sizes(v):
                yield ([f"[{i}]"] + sub_path, fs)


def find_art_direction(json_path: Path) -> Path | None:
    """Locate `specs/art-direction.html` relative to the slide JSON.

    Looks in the JSON's directory and one level up.
    """
    candidates = [
        json_path.parent / "specs" / "art-direction.html",
        json_path.parent.parent / "specs" / "art-direction.html",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def check_font_size_tokens(
    slides_data: dict,
    json_path: Path,
) -> list[str]:
    """Check font sizes in slide JSON against allowed tokens.

    Returns list of warning messages. Empty list if no violations or
    art-direction.html not found (in which case the check is skipped).
    """
    art_direction = find_art_direction(json_path)
    if art_direction is None:
        return []  # Skip silently when no active style exists.

    allowed = parse_allowed_font_sizes(art_direction)
    if not allowed:
        return []  # Skip when style file has no --fs-* tokens.

    violations: dict[int, list[str]] = {}
    slides = slides_data.get("slides", [])
    for slide_idx, slide in enumerate(slides, start=1):
        for path, fs in _walk_font_sizes(slide):
            if fs not in allowed:
                location = f"page{slide_idx:02d}"
                if path:
                    location += " " + ".".join(path)
                violations.setdefault(fs, []).append(location)

    if not violations:
        return []

    allowed_str = ", ".join(f"{n}pt" for n in sorted(allowed))
    warnings = [
        f"fontSize token discipline: allowed sizes = [{allowed_str}] "
        f"(from {art_direction.relative_to(json_path.parent) if json_path.parent in art_direction.parents else art_direction.name})"
    ]
    for fs in sorted(violations):
        locs = violations[fs]
        sample = ", ".join(locs[:3])
        more = f" (+{len(locs) - 3} more)" if len(locs) > 3 else ""
        warnings.append(f"  {fs}pt → {len(locs)} occurrence(s): {sample}{more}")
    return warnings
