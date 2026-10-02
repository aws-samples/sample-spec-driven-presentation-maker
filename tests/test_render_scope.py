# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Which slides a deck-file change re-renders (compose + preview)."""

from sdpm.engine.schema import affected_slugs, with_override_bases

SLIDES = {
    "cover": {"elements": []},
    "code": {"elements": [{"type": "include", "src": "includes/snippet.json"}]},
    "demo-1": {"elements": []},
    "demo-2": {"override": "demo-1", "elements": []},
    "demo-3": {"override": "demo-2", "elements": []},
    "end": {"elements": []},
}


def test_slide_file_change_hits_that_slide():
    assert affected_slugs(["slides/cover.json"], SLIDES) == ["cover"]


def test_unrelated_paths_hit_nothing():
    assert affected_slugs(["specs/brief.md", "attachments/a.csv", "output.pptx"], SLIDES) == []


def test_slide_not_in_deck_is_ignored():
    assert affected_slugs(["slides/draft.json"], SLIDES) == []


def test_deck_wide_files_hit_every_slide():
    for path in ("deck.json", "presentation.json", "specs/outline.md"):
        assert affected_slugs([path], SLIDES) == list(SLIDES)


def test_include_change_hits_referencing_slides():
    assert affected_slugs(["includes/snippet.json"], SLIDES) == ["code"]
    assert affected_slugs(["includes/other.json"], SLIDES) == []


def test_override_children_follow_their_base_transitively():
    assert affected_slugs(["slides/demo-1.json"], SLIDES) == ["demo-1", "demo-2", "demo-3"]
    assert affected_slugs(["slides/demo-2.json"], SLIDES) == ["demo-2", "demo-3"]
    assert affected_slugs(["slides/demo-3.json"], SLIDES) == ["demo-3"]


def test_result_is_in_deck_order():
    assert affected_slugs(["slides/end.json", "slides/cover.json"], SLIDES) == ["cover", "end"]


def test_override_cycle_does_not_hang():
    slides = {"a": {"override": "b"}, "b": {"override": "a"}, "c": {}}
    assert affected_slugs(["slides/c.json"], slides) == ["c"]
    assert affected_slugs(["slides/a.json"], slides) == ["a", "b"]


def test_windows_and_dot_prefixed_paths():
    assert affected_slugs(["slides\\cover.json", "./slides/end.json"], SLIDES) == ["cover", "end"]


def test_with_override_bases_adds_the_chain():
    assert with_override_bases(["demo-3"], SLIDES) == ["demo-1", "demo-2", "demo-3"]
    assert with_override_bases(["cover"], SLIDES) == ["cover"]
    assert with_override_bases(["missing"], SLIDES) == []
