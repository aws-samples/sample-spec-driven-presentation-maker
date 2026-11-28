# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Which guides a call sees, which it is handed, and what the handed text looks like.

Selection is one predicate — the guide's tags intersect the call's tag set — applied to
listing and hand-over alike, so a guide tagged for one composer mode cannot be visible
in that mode while being invisible to the listing beside it.
"""

import inspect

import pytest

from sdpm.knowledge.reference import (
    always_guides,
    build_collection,
    join_guides,
    select_guides,
)

# The tag sets the entry tools carry (entry.py owns the mapping; these are the literals).
ORCHESTRATOR = {"orchestrator"}
COMPOSER_PPTX = {"composer", "composer-pptx"}
COMPOSER_HTML = {"composer", "composer-html"}
STYLE = {"style"}
TRANSLATE = {"translate"}


def entry(name: str, tags: str, always: bool = False, body: str = "") -> dict[str, str]:
    front = f"description: {name} does a thing.\ntags: {tags}"
    if always:
        front += "\nalways: true"
    return {"name": name, "location": f"/store/{name}.md", "text": f"---\n{front}\n---\n\n{body or name + ' body.'}\n"}


@pytest.fixture
def collection():
    """Three fixtures spanning the composer tags, plus one guide per other role."""
    return build_collection([("builtin", [
        entry("both-modes", "[composer]", always=True),
        entry("pptx-only", "[composer-pptx]", always=True),
        entry("html-only", "[composer-html]", always=True),
        entry("listed-only", "[composer]"),
        entry("orch", "[orchestrator]", always=True),
        entry("styled", "[style]", always=True),
        entry("translated", "[translate]", always=True),
        entry("managed", "[management]", always=True),
    ])])


def names(entries) -> list[str]:
    return [e["name"] for e in entries]


class TestSelectionPredicate:
    """REQ-3.2 / REQ-5.5: intersection, applied to both selectors."""

    def test_pptx_mode_sees_the_shared_and_the_pptx_guide(self, collection) -> None:
        assert names(select_guides(collection, COMPOSER_PPTX)) == ["both-modes", "listed-only", "pptx-only"]

    def test_html_mode_sees_the_shared_and_the_html_guide(self, collection) -> None:
        assert names(select_guides(collection, COMPOSER_HTML)) == ["both-modes", "html-only", "listed-only"]

    def test_pptx_mode_is_handed_the_shared_and_the_pptx_guide(self, collection) -> None:
        assert list(always_guides(collection, COMPOSER_PPTX)) == ["both-modes", "pptx-only"]

    def test_html_mode_is_handed_the_shared_and_the_html_guide(self, collection) -> None:
        assert list(always_guides(collection, COMPOSER_HTML)) == ["both-modes", "html-only"]

    def test_a_mode_specific_guide_is_invisible_to_the_other_mode(self, collection) -> None:
        assert "html-only" not in names(select_guides(collection, COMPOSER_PPTX))
        assert "pptx-only" not in names(select_guides(collection, COMPOSER_HTML))

    def test_listing_and_hand_over_agree_on_who_is_selected(self, collection) -> None:
        for tags in (ORCHESTRATOR, COMPOSER_PPTX, COMPOSER_HTML, STYLE, TRANSLATE):
            handed = set(always_guides(collection, tags))
            assert handed <= set(names(select_guides(collection, tags)))

    def test_empty_tag_set_selects_everything(self, collection) -> None:
        assert len(select_guides(collection, set())) == len(collection["valid"])

    def test_no_entry_tool_tag_set_reaches_a_management_only_guide(self, collection) -> None:
        for tags in (ORCHESTRATOR, COMPOSER_PPTX, COMPOSER_HTML, STYLE, TRANSLATE):
            assert "managed" not in names(select_guides(collection, tags))
            assert "managed" not in always_guides(collection, tags)

    def test_management_only_guide_is_reachable_without_a_role(self, collection) -> None:
        assert "managed" in names(select_guides(collection, set()))

    def test_a_guide_is_handed_over_under_every_tag_it_carries(self) -> None:
        # REQ-4.9: always has no per-tag variant.
        both = build_collection([("builtin", [entry("shared", "[composer-pptx, translate]", always=True)])])
        assert list(always_guides(both, COMPOSER_PPTX)) == ["shared"]
        assert list(always_guides(both, TRANSLATE)) == ["shared"]

    def test_a_guide_without_always_is_listed_but_not_handed_over(self, collection) -> None:
        assert "listed-only" in names(select_guides(collection, COMPOSER_PPTX))
        assert "listed-only" not in always_guides(collection, COMPOSER_PPTX)


class TestListingShape:
    def test_entry_carries_the_five_listing_fields(self, collection) -> None:
        shown = select_guides(collection, ORCHESTRATOR)[0]
        assert set(shown) == {"name", "description", "source", "tags", "always"}

    def test_listing_carries_no_body(self, collection) -> None:
        # The listing rides inside every start_* return; 31 bodies there would duplicate the prompt.
        assert all("body" not in e for e in select_guides(collection, set()))

    def test_listing_is_sorted_by_name(self, collection) -> None:
        shown = names(select_guides(collection, set()))
        assert shown == sorted(shown)


class TestJoin:
    def test_blocks_are_titled_and_ordered_by_name(self) -> None:
        joined = join_guides({"b": "Bee.\n", "a": "Ay.\n"})
        assert joined == "# Guide: a\n\nAy.\n\n# Guide: b\n\nBee.\n"

    def test_byte_identical_across_two_calls(self, collection) -> None:
        first = join_guides(always_guides(collection, COMPOSER_PPTX))
        second = join_guides(always_guides(collection, COMPOSER_PPTX))
        assert first.encode("utf-8") == second.encode("utf-8")

    def test_trailing_whitespace_does_not_change_the_result(self) -> None:
        assert join_guides({"a": "Ay."}) == join_guides({"a": "Ay.\n\n\n"})

    def test_empty_hand_over_joins_to_nothing(self) -> None:
        assert join_guides({}) == ""

    def test_neither_representation_carries_frontmatter(self, collection) -> None:
        handed = always_guides(collection, COMPOSER_PPTX)
        assert handed
        for body in handed.values():
            assert "description:" not in body
            assert "tags:" not in body
        assert "description:" not in join_guides(handed)


class TestNoLanguageInSelection:
    """REQ-3.6 / REQ-9.10: selection takes a collection and a tag set, nothing else."""

    @pytest.mark.parametrize("func", [select_guides, always_guides])
    def test_signature_takes_only_the_collection_and_the_tags(self, func) -> None:
        assert list(inspect.signature(func).parameters) == ["collection", "tags"]

    def test_no_selection_signature_mentions_language(self) -> None:
        for func in (select_guides, always_guides, join_guides):
            assert "lang" not in str(inspect.signature(func)).lower()
