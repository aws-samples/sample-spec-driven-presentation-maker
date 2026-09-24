# SPDX-License-Identifier: MIT-0
"""Compatibility wrapper for installing official AWS Architecture Icons."""

from sdpm.knowledge.assets.download import (
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
