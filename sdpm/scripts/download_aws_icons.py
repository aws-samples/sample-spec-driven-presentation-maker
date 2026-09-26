# SPDX-License-Identifier: MIT-0
"""Compatibility wrapper for installing official AWS Architecture Icons."""

import sys
from pathlib import Path

# Runs standalone (`python3 sdpm/scripts/download_*_icons.py`, also inside the CDK
# bundling container) as well as from an installed sdpm-skill.
_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from sdpm.knowledge.assets.download import (  # noqa: E402
    ASSET_PACKAGE_URL,
    AWS_ALIASES,
    _classify_type,
    _extract_category,
    _is_target_entry,
    _name_from_filename,
    source_main,
)

__all__ = [
    "ASSET_PACKAGE_URL",
    "AWS_ALIASES",
    "_classify_type",
    "_extract_category",
    "_is_target_entry",
    "_name_from_filename",
]


if __name__ == "__main__":
    source_main("aws")
