# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Validate `{"type": "include", "src": ...}` references before a build.

The builder silently skips an include whose file is missing or empty, so a
whole diagram can vanish from a slide with no error. This check surfaces that
as a warning at config-resolution time.
"""

import json
from pathlib import Path


def check_includes(slides_data: dict, base_dir: Path) -> list[str]:
    """Check every include element's src resolves to a non-empty element list.

    Returns a list of warning lines (empty if all includes are fine). ``src`` is
    resolved relative to ``base_dir`` (the deck directory), matching the
    builder's own resolution.
    """
    slides = slides_data.get("slides", [])
    findings: list[str] = []

    for slide_idx, slide in enumerate(slides, start=1):
        elements = slide.get("elements") or []
        if not isinstance(elements, list):
            continue
        slug = slide.get("id", "")
        location = f"page{slide_idx:02d}({slug})" if slug else f"page{slide_idx:02d}"
        for e_idx, elem in enumerate(elements):
            if not isinstance(elem, dict) or elem.get("type") != "include":
                continue
            src = elem.get("src", "")
            if not src:
                findings.append(f"  {location} element[{e_idx}]: include has no `src`.")
                continue
            path = Path(src) if Path(src).is_absolute() else base_dir / src
            if not path.exists():
                findings.append(
                    f"  {location} element[{e_idx}]: include src \"{src}\" not found "
                    f"(resolved to {path}) — the referenced content will be MISSING."
                )
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError) as exc:
                findings.append(
                    f"  {location} element[{e_idx}]: include src \"{src}\" is invalid JSON ({exc})."
                )
                continue
            inc_elements = data if isinstance(data, list) else data.get("elements", [])
            if not inc_elements:
                findings.append(
                    f"  {location} element[{e_idx}]: include src \"{src}\" expands to 0 "
                    f"elements — expected a non-empty array or {{\"elements\": [...]}}."
                )

    if not findings:
        return []
    header = (
        f"Include problems ({len(findings)}): a referenced file is missing/empty, "
        f"so its content will silently NOT render. Fix the src path or the file."
    )
    return [header, *findings]
