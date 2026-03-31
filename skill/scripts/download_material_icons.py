# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Download Material Symbols (Google) and generate manifest.json.

Downloads SVGs from the marella/material-symbols GitHub repository,
extracts to assets/material/, and generates a unified manifest.json.

Requires: git (for sparse checkout)

Usage:
    uv run python3 scripts/download_material_icons.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_URL = "https://github.com/marella/material-symbols.git"
SVG_SUBDIR = "svg/400/outlined"  # weight 400, outlined style
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "material"

# Category mapping based on Material Symbols categories
# See: https://fonts.google.com/icons
MATERIAL_CATEGORIES: dict[str, list[str]] = {
    "action": ["search", "home", "settings", "delete", "done", "info", "check_circle",
               "visibility", "favorite", "bookmark", "lock", "thumb_up", "build",
               "code", "bug_report", "schedule", "trending_up", "analytics",
               "dashboard", "receipt", "assignment", "launch", "open_in_new",
               "power_settings_new", "shopping_cart", "account_balance"],
    "communication": ["email", "chat", "phone", "message", "forum", "call",
                       "contact_mail", "contact_phone", "notifications"],
    "content": ["add", "remove", "create", "save", "send", "link", "flag",
                "filter_list", "sort", "copy", "paste", "undo", "redo"],
    "navigation": ["arrow_back", "arrow_forward", "arrow_upward", "arrow_downward",
                    "chevron_left", "chevron_right", "expand_more", "expand_less",
                    "menu", "close", "refresh", "fullscreen", "more_vert", "more_horiz"],
    "file": ["folder", "file", "upload", "download", "cloud", "cloud_upload",
             "cloud_download", "attach_file", "description"],
    "hardware": ["computer", "phone_android", "phone_iphone", "tablet", "tv",
                 "keyboard", "mouse", "memory", "storage", "dns", "router"],
    "social": ["person", "group", "people", "share", "public", "school",
               "work", "business", "engineering"],
    "alert": ["warning", "error", "notification_important"],
    "editor": ["format_bold", "format_italic", "format_list_bulleted",
               "format_list_numbered", "title", "table_chart"],
    "maps": ["place", "map", "directions", "local_shipping", "flight", "hotel"],
}

# Reverse lookup: icon name → category
_ICON_TO_CATEGORY: dict[str, str] = {}
for cat, icons in MATERIAL_CATEGORIES.items():
    for icon in icons:
        _ICON_TO_CATEGORY[icon] = cat


def _categorize(name: str) -> str:
    """Determine category for a Material Symbol icon.

    Args:
        name: Icon name (e.g. "search", "arrow_back").

    Returns:
        Category string.
    """
    return _ICON_TO_CATEGORY.get(name, "general")


def _generate_tags(name: str, category: str) -> list[str]:
    """Generate search tags for a Material Symbol icon.

    Args:
        name: Icon name.
        category: Icon category.

    Returns:
        List of search tags.
    """
    tags = [category]
    # Add individual words from name
    for word in name.replace("_", " ").split():
        if len(word) > 1 and word not in tags:
            tags.append(word)
    return tags


def main() -> None:
    """Download Material Symbols SVGs and generate manifest."""
    print("Downloading Material Symbols (outlined, weight 400)...", file=sys.stderr)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        repo_dir = tmp_path / "material-symbols"

        # Sparse checkout — only svg/400/outlined
        print("  Cloning (sparse)...", file=sys.stderr)
        subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            ["git", "clone", "--depth=1", "--filter=blob:none", "--sparse", REPO_URL, str(repo_dir)],
            check=True,
            capture_output=True,
        )
        subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            ["git", "sparse-checkout", "set", SVG_SUBDIR],
            cwd=str(repo_dir),
            check=True,
            capture_output=True,
        )

        svg_dir = repo_dir / SVG_SUBDIR
        if not svg_dir.exists():
            print(f"  Error: {SVG_SUBDIR} not found in repo", file=sys.stderr)
            sys.exit(1)

        ASSETS_DIR.mkdir(parents=True, exist_ok=True)

        icons: list[dict] = []
        extracted = 0

        for svg_file in sorted(svg_dir.glob("*.svg")):
            name = svg_file.stem
            category = _categorize(name)
            tags = _generate_tags(name, category)

            # Copy SVG
            dest = ASSETS_DIR / svg_file.name
            shutil.copy2(svg_file, dest)
            extracted += 1

            display_name = name.replace("_", " ").title()
            icons.append({
                "name": display_name,
                "file": svg_file.name,
                "tags": tags,
                "category": category,
                "type": "outlined",
                "aspectRatio": 1,
            })

    # Sort by category then name
    icons.sort(key=lambda x: (x["category"], x["name"]))

    manifest = {
        "source": "material",
        "description": "Material Symbols by Google — general-purpose icons for UI and presentations (Apache 2.0)",
        "icons": icons,
    }

    manifest_path = ASSETS_DIR / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"  Extracted: {extracted} SVG icons", file=sys.stderr)
    print(f"  Manifest: {manifest_path} ({len(icons)} entries)", file=sys.stderr)
    print("  Done!", file=sys.stderr)


if __name__ == "__main__":
    main()
