# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Every published name this release removes is recorded with what replaces it.

Three published surfaces change at once — two payload keys, a tool's return shape and a
guide's name — and a caller only finds out from the CHANGELOG. So the entry is checked
rather than trusted: each removal has to appear beside its replacement in `## [Unreleased]`.
"""

from pathlib import Path

import pytest

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


@pytest.fixture(scope="module")
def unreleased() -> str:
    """The `## [Unreleased]` section, up to the next `## ` heading."""
    text = CHANGELOG.read_text(encoding="utf-8")
    start = text.index("## [Unreleased]")
    rest = text[start + len("## [Unreleased]"):]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


class TestRemovalsAreRecorded:
    @pytest.mark.parametrize("removed", ["static.slide_spec", "static.deck_spec"])
    def test_both_payload_keys(self, unreleased: str, removed: str) -> None:
        assert removed in unreleased

    def test_their_replacement(self, unreleased: str) -> None:
        assert "must_read" in unreleased
        assert "read_guides(must_read)" in unreleased

    def test_the_tools_old_and_new_return_shapes(self, unreleased: str) -> None:
        assert '{"documents": [{"name", "content"}]}' in unreleased
        assert '{"guides_text": str}' in unreleased

    def test_the_removed_guide_name_and_its_replacement(self, unreleased: str) -> None:
        assert "storytelling-vocabulary" in unreleased
        assert "story-line" in unreleased

    def test_the_deleted_guide(self, unreleased: str) -> None:
        assert "`setup` is deleted" in unreleased

    def test_the_guide_that_is_kept_is_said_to_be_kept(self, unreleased: str) -> None:
        # writing-ja was the other rename candidate; its name does not change.
        assert "`writing-ja` keeps its name" in unreleased

    def test_each_removal_is_marked_breaking(self, unreleased: str) -> None:
        assert unreleased.count("**Breaking:") == 3


class TestTheFeatureIsRecorded:
    def test_the_collection_is_described(self, unreleased: str) -> None:
        assert "one collection" in unreleased
        assert "list_guides" in unreleased

    def test_the_new_guides_are_named(self, unreleased: str) -> None:
        assert "`verify`" in unreleased
        assert "`writing-a-guide`" in unreleased

    def test_the_tag_vocabulary_is_listed(self, unreleased: str) -> None:
        from sdpm.knowledge.reference import TAGS

        assert [tag for tag in TAGS if f"`{tag}`" not in unreleased] == []


class TestNoStaleDescriptionSurvives:
    def test_nothing_still_says_start_presentation_returns_the_deck_spec(self, unreleased: str) -> None:
        # The deck-json-spec entry of this same section described the key this release removes.
        assert "returns it as `static.deck_spec`" not in unreleased

    def test_every_mention_of_a_removed_key_says_it_is_gone(self, unreleased: str) -> None:
        # "no longer returns static.slide_spec" is the only shape allowed; a line that names
        # the key as something a caller still gets would be describing the old release.
        mentions = [
            line for line in unreleased.splitlines()
            if "static.slide_spec" in line or "static.deck_spec" in line
        ]
        assert mentions, "the removal has to be recorded at all"
        for line in mentions:
            assert "no longer" in line or "removed" in line, line
