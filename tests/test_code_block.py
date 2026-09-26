# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""code_block: element margins are px (builder converts px -> EMU), not EMU.

Regression for the "one character per line" rendering: margins of 50000 were written as
if they were EMU, but the builder reads ``marginLeft`` etc. as px, so the text area
collapsed to nothing.
"""

import json

from sdpm.api import code_block

CODE = "def hello(name):\n    print(f'Hello, {name}!')\n"
MARGIN_KEYS = ("marginLeft", "marginTop", "marginRight", "marginBottom")


def test_code_body_margins_fit_inside_box():
    label, body = code_block(CODE, "python", width=800, height=300)
    assert body["marginLeft"] + body["marginRight"] < body["width"]
    assert body["marginTop"] + body["marginBottom"] < body["height"]
    assert all(body[k] <= 16 for k in MARGIN_KEYS)
    assert label["marginLeft"] <= 16


def test_code_body_uses_monospace_font():
    _, body = code_block(CODE, "python")
    assert body["fontFamily"] == "Courier New"


def test_show_label_false_only_returns_body():
    (body,) = code_block(CODE, "python", show_label=False)
    assert body["fill"] and "def" in body["text"]


def test_remote_include_delegates_to_api():
    from tools.code_block import code_block_to_include

    uploaded: dict = {}

    class _Storage:
        def upload_file(self, key, data, content_type):
            uploaded.update(key=key, data=data, content_type=content_type)

    result = code_block_to_include(
        deck_id="d1", code=CODE, name="snippet", storage=_Storage(),
        language="python", theme="dark", x=10, y=20, width=600, height=200,
    )

    assert result == {"include_path": "includes/snippet.json"}
    assert uploaded["key"] == "decks/d1/includes/snippet.json"
    assert uploaded["content_type"] == "application/json"
    assert json.loads(uploaded["data"]) == code_block(
        CODE, "python", theme="dark", x=10, y=20, width=600, height=200,
    )
