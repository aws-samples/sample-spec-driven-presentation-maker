# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""``_comment`` on a typed element is an annotation, not a comment-only entry.

Regression: the builder used to skip *every* element carrying ``_comment``.
A layout pass that annotated its frame elements
(``{"type": "textbox", "_comment": "frame: slide title", ...}``) shipped a
deck with no titles, edge bars or rules — silently. The spec says the key may
be used inside elements and is ignored; only entries without a ``type``
(section markers, layout regions) are comment-only.
"""

from pathlib import Path

from sdpm.engine.diff import slide_similarity
from sdpm.engine.schema import is_comment_element
from sdpm.engine.schema.lint import lint


def _template() -> Path:
    return Path(__file__).parent.parent / "sdpm" / "templates" / "blank-dark.pptx"


TYPED_WITH_COMMENT = {
    "type": "textbox", "_comment": "frame: slide title",
    "x": 144, "y": 72, "width": 1440, "height": 160, "fontSize": 32,
    "text": "資料作成の時間の多くは見た目の作業に消えている",
}
REGION = {"_comment": "region: body", "x": 192, "y": 336, "w": 1632, "h": 224}
MARKER = {"_comment": "--- section ---"}


def test_is_comment_element_needs_comment_and_no_type():
    assert is_comment_element(REGION)
    assert is_comment_element(MARKER)
    assert not is_comment_element(TYPED_WITH_COMMENT)
    assert not is_comment_element({"type": "textbox", "text": "x"})
    assert not is_comment_element("not a dict")


def test_builder_emits_typed_element_that_carries_comment():
    from sdpm.engine.builder import PPTXBuilder

    b = PPTXBuilder(str(_template()), fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"},
                    default_text_color="#FFFFFF")
    b.add_slide({
        "layout": "Blank",
        "elements": [
            MARKER,
            {"type": "shape", "shape": "rectangle", "_comment": "frame: edge bar",
             "x": 0, "y": 0, "width": 40, "height": 1080, "fill": "#AD5CFF"},
            TYPED_WITH_COMMENT,
            REGION,
        ],
    })
    slide = b.prs.slides[0]
    texts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text]
    # edge bar + title built; marker and region produce nothing
    assert len(list(slide.shapes)) == 2
    assert TYPED_WITH_COMMENT["text"] in texts


def test_lint_checks_typed_element_that_carries_comment():
    bad = dict(TYPED_WITH_COMMENT, fontSize="huge")  # invalid on purpose
    diags = lint([{"layout": "Blank", "elements": [MARKER, REGION, bad]}])
    assert any(d["element"] == 2 and d["rule"] == "invalid-fontSize" for d in diags), diags
    # comment-only entries are still exempt
    assert not any(d["element"] in (0, 1) for d in diags), diags


def test_diff_counts_typed_element_that_carries_comment():
    with_title = {"layout": "Blank", "elements": [REGION, TYPED_WITH_COMMENT]}
    without_title = {"layout": "Blank", "elements": [REGION]}
    same = {"layout": "Blank", "elements": [REGION, dict(TYPED_WITH_COMMENT)]}
    assert slide_similarity(with_title, same) > slide_similarity(with_title, without_title)
