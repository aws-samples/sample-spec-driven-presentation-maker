# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The style gallery's previews (``app_action`` with ``action="style_previews"``).

Pure: the server passes in how styles and icons are read (local files, or S3 on the remote).
"""

from collections.abc import Callable, Mapping
from typing import Any

from sdpm.knowledge.assets.style_icons import IconLoader, inline_style_icons_many
from sdpm.knowledge.reference import style_display_parts

# Names per call: one call's result stays small (a style is 30-60 KB of display copy).
MAX_NAMES = 6

StyleReader = Callable[[list[str]], Mapping[str, str]]


def style_previews(names: Any, read_styles: StyleReader, load_icons: IconLoader | None = None) -> dict[str, Any]:
    """Display copies of styles, cut into ``{head, prelude, slides}`` with their icons drawn in.

    Returns ``{"previews": {name: parts}, "missing": [names not read]}``. A bad argument
    fails the call: ``ValueError`` for anything but a list of 1 to ``MAX_NAMES`` strings. A
    bad item only goes to ``missing``: the reader leaves out names it does not accept, so one
    odd name never costs the rest of the batch its previews.
    """
    if not isinstance(names, list) or not names or len(names) > MAX_NAMES:
        raise ValueError(f"names must be a list of 1 to {MAX_NAMES} style names")
    if not all(isinstance(n, str) for n in names):
        raise ValueError("names must be strings")
    wanted = list(dict.fromkeys(names))
    found = read_styles(wanted)
    read = [n for n in wanted if isinstance(found.get(n), str)]
    shown = inline_style_icons_many([found[n] for n in read], load_icons)
    return {
        "previews": {n: style_display_parts(html) for n, html in zip(read, shown)},
        "missing": [n for n in wanted if n not in read],
    }
