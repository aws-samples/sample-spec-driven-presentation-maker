# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Multi-source asset search and resolution.

Supports multiple asset sources (aws, material, etc.) under assets/{source}/.
Each source has its own manifest.json with a unified schema.

Backward compatible: `icons:{name}` searches all sources (fallback).
New format: `assets:{source}/{name}` searches a specific source.
"""

import json
import sys
from pathlib import Path
from typing import Optional

from sdpm.config import ASSETS_DIR, get_extra_sources
from sdpm.utils.svg import _recolor_svg  # noqa: F401 - re-exported for builder
_KNOWN_EXTS = (".svg", ".png", ".gif", ".jpg", ".jpeg")


def _strip_ext(name: str) -> str:
    """Remove known image extension from asset name if present."""
    for ext in _KNOWN_EXTS:
        if name.endswith(ext):
            return name[: -len(ext)]
    return name


def _load_extra_sources() -> list[dict]:
    """Load extra asset sources from config.

    Returns:
        List of extra source dicts with 'source', 'manifest', and optional 'files_dir' keys.
    """
    return get_extra_sources()


_EXTRA_SOURCES: list[dict] = _load_extra_sources()

# Legacy aliases for backward compatibility
ICON_DIR = ASSETS_DIR
ICON_LOCAL_DIR = ASSETS_DIR

# Cached merged manifest: list of dicts with "source" injected
_manifest_cache: Optional[list[dict]] = None


def _check_recolor_protected(cfg, item: dict) -> bool:
    """Check if an icon entry is recolor-protected based on config."""
    if cfg is True:
        return True
    if isinstance(cfg, dict):
        when = cfg.get("when", {})
        types = when.get("type", [])
        if types and item.get("type") in types:
            return True
    return False


def _load_manifest_file(
    manifest_path: Path,
    source_override: Optional[str],
    all_assets: list[dict],
    files_dir: Optional[Path] = None,
    recolor_protected=None,
) -> None:
    """Load a single manifest.json and append entries to all_assets.

    Args:
        manifest_path: Path to manifest.json.
        source_override: If set, use this as source name instead of manifest's own.
        all_assets: List to append loaded assets to (mutated in place).
        files_dir: Directory containing the actual files. Defaults to manifest's parent.
    """
    if not manifest_path.exists():
        return
    with open(manifest_path) as f:
        data = json.load(f)
    source = source_override or data.get("source", manifest_path.parent.name)
    resolved_dir = files_dir or manifest_path.parent
    recolor_cfg = recolor_protected or data.get("recolorProtected", False)
    for item in data.get("icons", []):
        item["_source"] = source
        item["_dir"] = resolved_dir
        item["_recolor_protected"] = _check_recolor_protected(recolor_cfg, item)
        all_assets.append(item)


def _load_manifests() -> list[dict]:
    """Load and merge all manifest.json files from all asset sources.

    Scans ASSETS_DIR/{source}/manifest.json and extra_sources from config.json.

    Returns:
        Merged list of asset entries with '_source' and '_dir' fields injected.
    """
    global _manifest_cache
    if _manifest_cache is not None:
        return _manifest_cache

    all_assets: list[dict] = []

    # Built-in: assets/{source}/manifest.json
    if ASSETS_DIR.exists():
        for manifest_path in sorted(ASSETS_DIR.glob("*/manifest.json")):
            _load_manifest_file(manifest_path, source_override=None, all_assets=all_assets)

    # Extra sources from config.json
    for entry in _EXTRA_SOURCES:
        manifest_path = Path(entry["manifest"]).expanduser()
        source_name = entry.get("source")
        files_dir = Path(entry["files_dir"]).expanduser() if "files_dir" in entry else None
        _load_manifest_file(
            manifest_path, source_override=source_name, all_assets=all_assets,
            files_dir=files_dir, recolor_protected=entry.get("recolorProtected"),
        )

    # Auto-detect legacy icons/ directory (sibling of assets/)
    legacy_icons = ASSETS_DIR.parent / "icons"
    legacy_manifest = legacy_icons / "manifest.json"
    if legacy_manifest.exists():
        _load_manifest_file(legacy_manifest, source_override="icons-legacy", all_assets=all_assets)

    _manifest_cache = all_assets
    return all_assets


def _assets_not_installed_error() -> None:
    """Print asset installation instructions and exit."""
    print("=" * 60, file=sys.stderr)
    print("CRITICAL: Assets not installed. Cannot continue.", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("", file=sys.stderr)
    print("Assets are required for slide generation.", file=sys.stderr)
    print("", file=sys.stderr)
    print("  Run: uv run python3 scripts/download_aws_icons.py", file=sys.stderr)
    print("  Run: uv run python3 scripts/download_material_icons.py", file=sys.stderr)
    print("", file=sys.stderr)
    print("Stop current work and ask the user which option to use.", file=sys.stderr)
    sys.exit(1)


def _find_by_manifest(source: str, name: str) -> Optional[Path]:
    """Find an asset file using manifest metadata.

    Looks up the manifest for the given source and resolves the file path
    using the 'file' field, which may contain subdirectory paths.

    Args:
        source: Source name (e.g. "aws", "material").
        name: Asset name without extension.

    Returns:
        Path if found via manifest, None otherwise.
    """
    manifests = _load_manifests()
    for item in manifests:
        if item.get("_source") != source:
            continue
        file_stem = item["file"].rsplit(".", 1)[0]
        if file_stem == name:
            path = item["_dir"] / item["file"]
            if path.exists():
                return path
    return None


def _find_file_in_dir(directory: Path, name: str) -> Optional[Path]:
    """Search for a file by name (without extension) in a directory.

    Args:
        directory: Directory to search in.
        name: File name without extension.

    Returns:
        Path if found, None otherwise.
    """
    for ext in [".svg", ".png", ".gif", ".jpg", ".jpeg"]:
        path = directory / f"{name}{ext}"
        if path.exists():
            return path
    return None


def check_asset_exists(ref: str, theme: str = "light") -> bool:
    """Check if an asset exists without raising error.

    Args:
        ref: Asset reference — `assets:source/name` or `icons:name` or bare name.
        theme: Theme hint (unused currently, reserved for future).

    Returns:
        True if asset file exists.
    """
    try:
        resolve_asset_path(ref, theme=theme)
        return True
    except FileNotFoundError:
        return False


# Backward-compatible aliases
check_icon_exists = check_asset_exists


def is_recolor_protected(ref: str) -> bool:
    """Check if an asset is recolor-protected (e.g. brand icons).

    Args:
        ref: Asset reference — `assets:source/name` or `icons:name`.

    Returns:
        True if the asset should not be recolored.
    """
    if ref.startswith("assets:"):
        name = _strip_ext(ref.split(":", 1)[1].split("/", 1)[-1])
    elif ref.startswith("icons:"):
        name = _strip_ext(ref.split(":", 1)[1])
    else:
        return False
    for item in _load_manifests():
        file_stem = item["file"].rsplit(".", 1)[0]
        if file_stem == name:
            return item.get("_recolor_protected", False)
    return False


def resolve_asset_path(ref: str, theme: str = "light") -> Path:
    """Resolve asset reference to file path.

    Supports:
        - `assets:source/name` — search specific source directory
        - `icons:name` — search all sources (backward compatible)
        - bare name — search all sources

    Args:
        ref: Asset reference string.
        theme: Theme hint (unused currently, reserved for future).

    Returns:
        Resolved file Path.

    Raises:
        FileNotFoundError: If asset not found in any source.
    """
    if ref.startswith("assets:"):
        # assets:aws/Arch_Amazon-S3 → search specific source
        remainder = ref.split(":", 1)[1]
        if "/" in remainder:
            source, name = remainder.split("/", 1)
            name = _strip_ext(name)
            result = _find_by_manifest(source, name)
            if result:
                return result
            # Fallback: direct file search in source dir
            source_dir = ASSETS_DIR / source
            if source_dir.exists():
                result = _find_file_in_dir(source_dir, name)
                if result:
                    return result
            raise FileNotFoundError(f"Asset not found: {ref}")
        else:
            # assets:name — no source specified, search all
            return _find_in_all_sources(_strip_ext(remainder))

    elif ref.startswith("icons:"):
        # icons:Arch_Amazon-S3 → search all sources (backward compat)
        name = _strip_ext(ref.split(":", 1)[1])
        return _find_in_all_sources(name)

    else:
        # Bare name
        return _find_in_all_sources(_strip_ext(ref))


def _find_in_all_sources(name: str) -> Path:
    """Search all asset sources for a file by name.

    First checks manifests (supports subdirectory paths in 'file' field),
    then falls back to direct file search in source directories.

    Args:
        name: File name without extension.

    Returns:
        Resolved file Path.

    Raises:
        FileNotFoundError: If not found in any source.
    """
    # Manifest-based lookup (handles subdirectory paths)
    manifests = _load_manifests()
    for item in manifests:
        file_stem = item["file"].rsplit(".", 1)[0]
        if file_stem == name:
            path = item["_dir"] / item["file"]
            if path.exists():
                return path

    # Fallback: direct file search
    search_dirs: list[Path] = []

    if ASSETS_DIR.exists():
        for source_dir in sorted(ASSETS_DIR.iterdir()):
            if source_dir.is_dir():
                search_dirs.append(source_dir)

    # Extra sources from config.json
    for entry in _EXTRA_SOURCES:
        if "files_dir" in entry:
            d = Path(entry["files_dir"]).expanduser()
        else:
            d = Path(entry["manifest"]).expanduser().parent
        if d.exists():
            search_dirs.append(d)

    # Legacy icons/ directory
    legacy_icons = ASSETS_DIR.parent / "icons"
    if legacy_icons.exists() and legacy_icons not in search_dirs:
        search_dirs.append(legacy_icons)

    if not search_dirs:
        _assets_not_installed_error()

    for directory in search_dirs:
        result = _find_file_in_dir(directory, name)
        if result:
            return result

    print(f"Error: Asset not found: {name}", file=sys.stderr)
    print(f"  Searched: {', '.join(str(d) for d in search_dirs)}", file=sys.stderr)
    print("", file=sys.stderr)
    print("Assets may be incomplete. Try:", file=sys.stderr)
    print("  uv run python3 scripts/download_aws_icons.py", file=sys.stderr)
    raise FileNotFoundError(f"Asset not found: {name}")


# Backward-compatible alias
resolve_icon_path = resolve_asset_path


def list_sources() -> list[dict]:
    """List all available asset sources with counts and descriptions.

    Returns:
        List of dicts with 'source', 'count', and 'description' keys, sorted by source name.
    """
    manifests = _load_manifests()
    counts: dict[str, int] = {}
    descriptions: dict[str, str] = {}
    for item in manifests:
        src = item.get("_source", "unknown")
        counts[src] = counts.get(src, 0) + 1
    # Load descriptions from manifest files
    if ASSETS_DIR.exists():
        for manifest_path in sorted(ASSETS_DIR.glob("*/manifest.json")):
            with open(manifest_path) as f:
                data = json.load(f)
            source = data.get("source", manifest_path.parent.name)
            if "description" in data:
                descriptions[source] = data["description"]
    for entry in _EXTRA_SOURCES:
        manifest_path = Path(entry["manifest"]).expanduser()
        if manifest_path.exists():
            with open(manifest_path) as f:
                data = json.load(f)
            source = entry.get("source") or data.get("source", manifest_path.parent.name)
            if "description" in data:
                descriptions[source] = data["description"]
    return [{"source": s, "count": c, "description": descriptions.get(s, "")} for s, c in sorted(counts.items())]


def search_assets(
    query: str,
    limit: int = 20,
    source_filter: Optional[str] = None,
    type_filter: Optional[str] = None,
    theme_filter: Optional[str] = None,
) -> list[dict]:
    """Search assets by keywords using merged manifests.

    Args:
        query: Search keyword(s), space-separated for multiple queries.
        limit: Maximum results per query term.
        source_filter: Filter by source (e.g. "aws", "material").
        type_filter: Filter by type (e.g. "service", "resource").
        theme_filter: Filter by theme ("dark" or "light").

    Returns:
        List of result dicts, each with 'query' and 'matches' keys.
    """
    manifests = _load_manifests()
    if not manifests:
        _assets_not_installed_error()

    queries = query.lower().split()
    all_results: list[dict] = []

    for q in queries:
        q_norm = q.replace(" ", "").replace("-", "").replace("_", "")
        matches: list[tuple[tuple[int, int], dict]] = []

        for asset in manifests:
            if source_filter and asset.get("_source") != source_filter:
                continue
            if type_filter and asset.get("type") != type_filter:
                continue
            if not type_filter and asset.get("type") == "shape":
                continue

            name_norm = asset["name"].lower().replace(" ", "").replace("-", "").replace("_", "")
            tags_norm = " ".join(asset.get("tags", [])).lower().replace(" ", "")

            if q_norm in name_norm or q_norm in tags_norm:
                if theme_filter:
                    file_lower = asset["file"].lower()
                    name_lower = asset["name"].lower()
                    has_light = "_light" in file_lower or " light" in name_lower
                    has_dark = "_dark" in file_lower or " dark" in name_lower
                    if theme_filter == "light" and has_dark and not has_light:
                        continue
                    if theme_filter == "dark" and has_light and not has_dark:
                        continue

                type_priority = 0 if asset.get("type") == "service" else 1
                score = (type_priority, len(asset["name"]))
                matches.append((score, asset))

        matches.sort(key=lambda x: (x[0], x[1]["name"]))

        result_items = []
        for _, asset in matches[:limit]:
            source = asset.get("_source", "unknown")
            ref = f"assets:{source}/{asset['file'].rsplit('.', 1)[0]}"
            ratio = asset.get("aspectRatio", 1)
            h = int(100 / ratio) if ratio and ratio > 0 else 100
            result_items.append({
                "name": asset["name"],
                "ref": ref,
                "source": source,
                "category": asset.get("category", ""),
                "type": asset.get("type", ""),
                "description": asset.get("description", ""),
                "size_hint": f"w:100 h:{h}" if h != 100 else "",
            })

        all_results.append({
            "query": q,
            "matches": result_items,
            "total": len(matches),
        })

    return all_results


def print_search_results(results: list[dict], limit: int = 20) -> None:
    """Print search results to stdout in human-readable format.

    Args:
        results: Output from search_assets().
        limit: Max results shown (for "and N more" message).
    """
    for result in results:
        print(f"# {result['query']}")
        for m in result["matches"]:
            label_parts = [m["source"]]
            if m["category"]:
                label_parts.append(m["category"])
            if m["type"]:
                label_parts.append(m["type"])
            label = f"{m['name']} [{'/'.join(label_parts)}]"
            size_str = f"  ({m['size_hint']})" if m["size_hint"] else ""
            print(f"  {label:<60}{size_str}")
            if m["description"]:
                print(f"    {m['description']}")
            print(f"    {m['ref']}")
        if result["total"] > limit:
            print(f"  ... and {result['total'] - limit} more")
        print()


# Backward-compatible alias
icon_search = search_assets
