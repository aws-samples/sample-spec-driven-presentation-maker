# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The two bundled templates share their layouts' placeholder prompt text."""

from pptx import Presentation

from sdpm.config import TEMPLATES_DIR


def _prompts(name: str) -> list[list[str]]:
    prs = Presentation(str(TEMPLATES_DIR / f"{name}.pptx"))
    return [
        [ph.text_frame.text for ph in layout.placeholders if ph.has_text_frame]
        for layout in prs.slide_layouts
    ]


def test_blank_light_prompts_match_blank_dark() -> None:
    assert _prompts("blank-light") == _prompts("blank-dark")
