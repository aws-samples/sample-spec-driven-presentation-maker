# SPDX-License-Identifier: MIT-0
"""Compatibility wrapper for installing official Material Symbols."""

import sys
from pathlib import Path

# Runs standalone (`python3 sdpm/scripts/download_*_icons.py`, also inside the CDK
# bundling container) as well as from an installed sdpm-skill.
_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from sdpm.knowledge.assets.download import (  # noqa: E402
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
