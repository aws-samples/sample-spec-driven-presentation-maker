# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""sdpm.engine.schema slug grammars and the outline.md parser."""

import pytest

from sdpm.api import parse_outline_slugs
from sdpm.engine.schema import OUTLINE_SLUG_RE, SLUG_RE, parse_outline_text, validate_specs
from sdpm.engine.schema.lint_outline import lint_outline


@pytest.mark.parametrize("slug", ["intro", "demo-1", "2024", "-intro", "a--b", "intro-"])
def test_outline_grammar_accepts(slug):
    assert OUTLINE_SLUG_RE.fullmatch(slug)


@pytest.mark.parametrize("slug", ["", "Intro", "my_slide", "slide_01", "a/b", "a.b", "intro\n"])
def test_outline_grammar_rejects(slug):
    assert not OUTLINE_SLUG_RE.fullmatch(slug)


@pytest.mark.parametrize("slug", ["intro", "demo-1", "my_slide", "slide_01", "a_-b"])
def test_artifact_grammar_accepts(slug):
    assert SLUG_RE.fullmatch(slug)


@pytest.mark.parametrize("slug", ["", "-intro", "_intro", "Intro", "a/b", "../x", "intro\n"])
def test_artifact_grammar_rejects(slug):
    assert not SLUG_RE.fullmatch(slug)


def test_parse_outline_text_reads_slide_lines_in_order():
    text = "\n".join([
        "# Deck",
        "- [intro] Opening",
        "  - body: x",
        "- [demo-1] Demo",
        "-[tight] No space after the dash",
        "- [bare]",
        "- [my_slide] Not an outline slug",
        "- [Upper] Not an outline slug",
        "  - [nested] Indented lines are not slides",
        "* [star] Not a dash",
    ])
    assert parse_outline_text(text) == ["intro", "demo-1", "tight", "bare"]


def test_parse_outline_slugs_reads_the_file(tmp_path):
    path = tmp_path / "outline.md"
    assert parse_outline_slugs(path) == []
    path.write_text("- [intro] a\n- [end] b\n", encoding="utf-8")
    assert parse_outline_slugs(path) == ["intro", "end"]


def test_lint_and_validate_use_the_outline_grammar():
    text = "- [intro] a\n- [my_slide] b\n- [-dash] c\n"
    assert lint_outline(text) == [{"line": 2, "rule": "slug-pattern"}]
    assert validate_specs({}, text)["slugs"] == ["intro", "-dash"]
