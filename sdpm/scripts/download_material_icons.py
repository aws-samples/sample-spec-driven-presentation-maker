# SPDX-License-Identifier: MIT-0
"""Compatibility wrapper for installing official Material Symbols."""

from sdpm.knowledge.assets.download import (
    MATERIAL_CATEGORIES,
    MATERIAL_REPO_URL,
    MATERIAL_SVG_SUBDIR,
    _categorize,
    source_main,
)

__all__ = [
    "MATERIAL_CATEGORIES",
    "MATERIAL_REPO_URL",
    "MATERIAL_SVG_SUBDIR",
    "_categorize",
]


if __name__ == "__main__":
    source_main("material")
