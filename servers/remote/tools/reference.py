# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Remote-specific style listing — merges bundled styles with user styles on S3.

Reference documents (workflows / guides / examples) are served by the shared
tool contract (:mod:`sdpm.tools`) from bundled data baked into the image.
Only user styles are infrastructure-dependent (S3 + DynamoDB pins).
"""

from typing import Any

from shared.user_library import merge_styles
from storage import Storage


def list_styles(storage: Storage, user_id: str = "", include_all: bool = False) -> dict[str, Any]:
    """List available design styles with pin/source metadata.

    Combines bundled styles (references/examples/styles/, baked into the
    image) and user styles (user-styles/{user_id}/ on S3), one entry per name:
    a user style replaces the bundled style of the same name (the same rule as
    Local and the Web UI). Uses Engine build_styles_listing() for filtering.

    Args:
        storage: Storage backend instance.
        user_id: User ID for fetching user styles and pins. Empty = builtin only.
        include_all: If True, return all styles. If False, return pinned + user only
                     (falls back to all if no pins exist).

    Returns:
        Dict with styles list (name, description, pinned, source). When the pin
        filter hid some styles, also other_styles (names) and a hint.
    """
    from sdpm.knowledge.reference import (
        BUNDLED_STYLES_DIR,
        build_styles_listing,
        list_styles as _list_bundled_styles,
    )

    # 1. Builtin styles from bundled data
    builtin_styles = [
        {**s, "source": "builtin"} for s in _list_bundled_styles(BUNDLED_STYLES_DIR)
    ]

    # 2. User styles and pins (pptx bucket + DDB)
    user_styles: list[dict] = []
    pinned_names: list[str] = []
    if user_id:
        user_styles = storage.list_user_styles(user_id)
        pinned_names = storage.get_style_pins(user_id)

    # 3. Build payload via Engine (filter + hidden-style names/hint)
    return build_styles_listing(merge_styles(user_styles, builtin_styles), pinned_names, include_all)
