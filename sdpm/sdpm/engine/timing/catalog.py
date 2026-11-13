# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Loading and structural validation for the generated PowerPoint catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

CATALOG_SCHEMA_VERSION = 1
ENTRY_STATUSES = frozenset({"accepted", "rejected", "nonPersisted", "outOfScope"})


class CatalogError(ValueError):
    """Raised when a checked-in capability catalog violates its contract."""


def _require(mapping: Mapping[str, Any], key: str, expected: type, path: str) -> Any:
    value = mapping.get(key)
    if not isinstance(value, expected):
        raise CatalogError(f"{path}.{key} must be {expected.__name__}")
    return value


def validate_catalog(data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate required provenance and one-to-one GUI/candidate accounting."""
    if data.get("schemaVersion") != CATALOG_SCHEMA_VERSION:
        raise CatalogError(f"schemaVersion must be {CATALOG_SCHEMA_VERSION}")
    baseline = _require(data, "baseline", dict, "catalog")
    for key in ("application", "version", "platform", "generatedAt", "guiManifest"):
        value = _require(baseline, key, str, "catalog.baseline")
        if not value.strip():
            raise CatalogError(f"catalog.baseline.{key} must not be empty")

    gui_items = _require(data, "guiItems", list, "catalog")
    candidates = _require(data, "candidates", list, "catalog")
    seen_gui: set[str] = set()
    for index, entry in enumerate(gui_items):
        if not isinstance(entry, Mapping):
            raise CatalogError(f"catalog.guiItems[{index}] must be object")
        key = _require(entry, "key", str, f"catalog.guiItems[{index}]")
        if key in seen_gui:
            raise CatalogError(f"duplicate GUI key {key!r}")
        seen_gui.add(key)
        status = entry.get("status")
        if status not in ENTRY_STATUSES:
            raise CatalogError(f"catalog.guiItems[{index}].status must be one of {sorted(ENTRY_STATUSES)}")
        if status != "accepted" and not isinstance(entry.get("reason"), str):
            raise CatalogError(f"catalog.guiItems[{index}].reason is required for {status}")
        if status == "accepted" and not isinstance(entry.get("semanticJson"), Mapping):
            raise CatalogError(f"catalog.guiItems[{index}].semanticJson is required for accepted entries")

    seen_candidates: set[str] = set()
    for index, entry in enumerate(candidates):
        if not isinstance(entry, Mapping):
            raise CatalogError(f"catalog.candidates[{index}] must be object")
        key = _require(entry, "key", str, f"catalog.candidates[{index}]")
        if key in seen_candidates:
            raise CatalogError(f"duplicate candidate key {key!r}")
        seen_candidates.add(key)
        gui_key = _require(entry, "guiKey", str, f"catalog.candidates[{index}]")
        if gui_key not in seen_gui:
            raise CatalogError(f"candidate {key!r} references unknown GUI key {gui_key!r}")
        status = entry.get("status")
        if status not in ENTRY_STATUSES:
            raise CatalogError(f"catalog.candidates[{index}].status must be one of {sorted(ENTRY_STATUSES)}")
        if status != "accepted" and not isinstance(entry.get("reason"), str):
            raise CatalogError(f"catalog.candidates[{index}].reason is required for {status}")
        if status == "accepted":
            if not isinstance(entry.get("semanticJson"), Mapping):
                raise CatalogError(f"catalog.candidates[{index}].semanticJson is required for accepted entries")
            if not isinstance(entry.get("ooxml"), Mapping):
                raise CatalogError(f"catalog.candidates[{index}].ooxml is required for accepted entries")
    return dict(data)


def load_catalog(path: str | Path) -> dict[str, Any]:
    """Load and validate a generated catalog JSON file."""
    catalog_path = Path(path)
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogError(f"cannot load catalog {catalog_path}: {error}") from error
    if not isinstance(data, Mapping):
        raise CatalogError("catalog root must be an object")
    return validate_catalog(data)
