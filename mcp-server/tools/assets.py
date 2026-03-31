# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Asset search via Storage ABC — S3 manifest with multi-source support."""

import json
import time
from typing import Any

from storage import Storage

# In-memory cache: manifest_key → (data, timestamp)
_manifest_cache: dict[str, tuple[list[dict], float]] = {}
_CACHE_TTL: int = 3600


def _load_manifests(storage: Storage) -> list[tuple[str, list[dict]]]:
    """Load all asset manifests from S3.

    Args:
        storage: Storage backend instance.

    Returns:
        List of (source_name, entries) tuples.
    """
    cache_key = "all_manifests"
    cached = _manifest_cache.get(cache_key)
    if cached and (time.time() - cached[1]) < _CACHE_TTL:
        return cached[0]

    sources: list[tuple[str, list[dict]]] = []
    files = storage.list_files(prefix="assets/")
    manifest_keys = [f for f in files if f.endswith("/manifest.json")]

    for key in manifest_keys:
        # Extract source name: assets/{source}/manifest.json → {source}
        parts = key.split("/")
        if len(parts) >= 3:
            source_name = parts[1]
        else:
            source_name = "default"
        try:
            raw = storage.download_file(key=key)
            data = json.loads(raw)
            entries = data if isinstance(data, list) else data.get("assets", data.get("icons", []))
            if not isinstance(entries, list):
                continue
            # Tag each entry with source
            for entry in entries:
                entry["_source"] = source_name
            sources.append((source_name, entries))
        except Exception:
            continue

    _manifest_cache[cache_key] = (sources, time.time())
    return sources


def search_assets(
    query: str,
    storage: Storage,
    source_filter: str = "",
    limit: int = 20,
    type_filter: str = "",
    theme_filter: str = "",
) -> dict[str, Any]:
    """Search assets by keyword across all sources.

    Args:
        query: Search keywords, space-separated for multiple queries.
        storage: Storage backend instance.
        source_filter: Filter by source name (e.g. "aws", "material").
        limit: Maximum results per keyword.
        type_filter: Filter by type (e.g. "Architecture-Service").
        theme_filter: Filter by theme ("dark" or "light").

    Returns:
        Dict with query and results list.
    """
    sources = _load_manifests(storage)
    queries = query.lower().split()
    all_results: list[dict] = []

    for q in queries:
        q_norm = q.replace(" ", "").replace("-", "").replace("_", "")
        matches: list[tuple[int, dict]] = []

        for source_name, entries in sources:
            if source_filter and source_name != source_filter:
                continue
            for entry in entries:
                if type_filter and entry.get("type", "") != type_filter:
                    continue
                if theme_filter and entry.get("theme", "") != theme_filter:
                    continue
                name_norm = entry.get("name", "").lower().replace(" ", "").replace("-", "").replace("_", "")
                tags_norm = " ".join(entry.get("tags", [])).lower().replace(" ", "")
                if q_norm in name_norm or q_norm in tags_norm:
                    matches.append((len(entry.get("name", "")), entry))

        matches.sort(key=lambda x: x[0])
        for _, entry in matches[:limit]:
            result = {
                "name": entry.get("name", ""),
                "file": entry.get("file", ""),
                "source": entry.get("_source", ""),
                "tags": entry.get("tags", []),
            }
            all_results.append(result)

    return {"query": query, "results": all_results}


def list_asset_sources(storage: Storage) -> dict[str, Any]:
    """List available asset sources with counts.

    Args:
        storage: Storage backend instance.

    Returns:
        Dict with sources list.
    """
    sources = _load_manifests(storage)
    return {
        "sources": [
            {"name": name, "count": len(entries)}
            for name, entries in sources
        ]
    }
