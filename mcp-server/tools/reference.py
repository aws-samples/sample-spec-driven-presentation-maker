# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Remote-specific style listing — merges bundled styles with user styles on S3.

Reference documents (workflows / guides / examples) are served by the shared
tool contract (:mod:`sdpm.tools`) from bundled data baked into the image.
Only user styles are infrastructure-dependent (S3 + DynamoDB pins).
"""

import re
from typing import Any

from storage import Storage


def list_styles(storage: Storage, user_id: str = "", include_all: bool = False) -> dict[str, Any]:
    """List available design styles with pin/source metadata.

    Combines bundled styles (references/examples/styles/, baked into the
    image) and user styles (user-styles/{user_id}/ on S3). Uses Engine
    filter_styles() for filtering.

    Args:
        storage: Storage backend instance.
        user_id: User ID for fetching user styles and pins. Empty = builtin only.
        include_all: If True, return all styles. If False, return pinned + user only
                     (falls back to all if no pins exist).

    Returns:
        Dict with styles list (name, description, pinned, source).
    """
    from sdpm.knowledge.reference import (
        BUNDLED_STYLES_DIR,
        filter_styles,
        list_styles as _list_bundled_styles,
    )

    # 1. Builtin styles from bundled data
    builtin_styles = [
        {**s, "source": "builtin"} for s in _list_bundled_styles(BUNDLED_STYLES_DIR)
    ]

    # 2. User styles from pptx bucket
    user_styles: list[dict[str, str]] = []
    if user_id:
        user_prefix = f"user-styles/{user_id}/"
        user_files = storage.list_files(prefix=user_prefix, bucket=storage.pptx_bucket)
        for f in user_files:
            if not f.endswith(".html"):
                continue
            name = f.removeprefix(user_prefix).removesuffix(".html")
            description = ""
            try:
                content = storage.download_file_from_pptx_bucket(key=f).decode("utf-8")
                m = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
                if m:
                    description = m.group(1).strip()
            except Exception:
                pass
            user_styles.append({"name": name, "description": description, "source": "user"})

    # 3. Get pins
    pinned_names: list[str] = []
    if user_id:
        pinned_names = storage.get_style_pins(user_id)

    # 4. Filter via Engine
    all_styles = user_styles + builtin_styles
    filtered = filter_styles(all_styles, pinned_names, include_all)
    return {"styles": filtered}
