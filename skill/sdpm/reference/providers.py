# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Reference data providers."""
from pathlib import Path


class ReferenceProvider:
    """Abstract interface for reference data access."""
    def list_items(self, ref_type: str) -> list[dict]:
        raise NotImplementedError

    def get_item(self, ref_type: str, name: str) -> dict | None:
        raise NotImplementedError


class FileProvider(ReferenceProvider):
    """SKILL版: read from local filesystem."""

    # type -> subdirectory mapping
    TYPE_MAP = {
        "example": "examples",
        "workflow": "workflows",
        "guide": "guides",
    }

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def list_items(self, ref_type: str = None) -> list[dict]:
        from sdpm.reference import _get_description
        items = []
        if ref_type and ref_type in self.TYPE_MAP:
            subdir = self.base_dir / self.TYPE_MAP[ref_type]
            if subdir.exists():
                seen = set()
                for f in sorted(subdir.rglob("*")):
                    if f.suffix in (".md", ".pptx") and f.stem not in seen:
                        seen.add(f.stem)
                        desc = _get_description(f)
                        items.append({"name": f.stem, "type": ref_type, "description": desc})
            return items
        # All types
        for t in self.TYPE_MAP:
            items.extend(self.list_items(t))
        return items

    def get_item(self, ref_type: str, name: str) -> dict | None:
        if ref_type in self.TYPE_MAP:
            subdir = self.base_dir / self.TYPE_MAP[ref_type]
            for ext in (".md", ".pptx"):
                candidates = list(subdir.rglob(f"{name}{ext}"))
                if candidates:
                    return {"name": name, "type": ref_type, "content": candidates[0].read_text(encoding="utf-8") if ext == ".md" else f"[pptx] {candidates[0]}"}
        return None
