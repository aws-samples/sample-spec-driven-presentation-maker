# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The user-guides documentation quotes the engine's own numbers and vocabulary.

A reader follows these docs instead of reading the parser, so a number that drifts here
is worse than no number: it describes a cap that is not the cap. The guide size cap moved
once already, which is what this guards.
"""

from pathlib import Path

import pytest

from sdpm.knowledge.reference import (
    GUIDE_DESCRIPTION_MAX,
    GUIDE_MAX_BYTES,
    TAGS,
)

_ROOT = Path(__file__).resolve().parents[1]
_GUIDES_DOC = _ROOT / "docs" / "en" / "custom-template.md"
_ARCHITECTURE = _ROOT / "docs" / "en" / "architecture.md"

# Every cause guide_meta can report, in the order it checks them (its own docstring).
_CATEGORIES = (
    "name", "frontmatter", "unknown-key", "description", "tags", "tag-value", "always", "size",
)


@pytest.fixture(scope="module")
def section() -> str:
    text = _GUIDES_DOC.read_text(encoding="utf-8")
    assert "### User-local guides" in text, "the user-guides section is gone"
    return text.split("### User-local guides")[1].split("\n### ")[0]


@pytest.fixture(scope="module")
def flat(section) -> str:
    """The section with its line wrapping collapsed, for asserting on a sentence."""
    return " ".join(section.split())


class TestItSitsBesideItsSiblings:
    def test_it_is_in_the_file_that_documents_user_styles_and_templates(self) -> None:
        text = _GUIDES_DOC.read_text(encoding="utf-8")
        for sibling in ("### User-local styles", "#### User-local templates"):
            assert sibling in text

    def test_it_gives_the_same_three_step_search_order(self, section) -> None:
        assert "$SDPM_GUIDES_DIR" in section
        assert "<user-config>/guides/" in section
        assert "sdpm/references/guides/" in section

    def test_it_names_both_platforms_config_directory(self, section) -> None:
        assert "~/.config/sdpm/guides/" in section
        assert "%APPDATA%/sdpm/guides/" in section


class TestItQuotesTheEngineNotAGuess:
    def test_the_size_cap_is_the_engine_number(self, section) -> None:
        assert f"{GUIDE_MAX_BYTES:,} bytes" in section

    def test_the_description_cap_is_the_engine_number(self, section) -> None:
        assert f"{GUIDE_DESCRIPTION_MAX} characters" in section

    def test_every_tag_in_the_vocabulary_is_listed(self, section) -> None:
        assert [tag for tag in TAGS if f"`{tag}`" not in section] == []

    def test_no_tag_outside_the_vocabulary_is_offered(self, section) -> None:
        # A tag the docs invent would be reported as tag-value by the parser.
        table = section.split("| `tags` |")[1].split("|\n")[0]
        for word in ("reviewer", "author", "layout", "deck"):
            assert f"`{word}`" not in table

    def test_every_refusal_cause_is_named(self, section) -> None:
        assert [name for name in _CATEGORIES if f"`{name}`" not in section] == []


class TestItExplainsWhatNothingElseWill:
    def test_it_says_an_unknown_key_is_an_error_here(self, flat) -> None:
        # The opposite of what a reader coming from Claude Code skills expects.
        assert "unrecognised key is an error, not ignored" in flat

    def test_it_says_what_the_description_decides(self, flat) -> None:
        assert "when to read it" in flat

    def test_it_says_what_always_does(self, section) -> None:
        assert "must_read" in section

    def test_it_covers_the_lossy_shadow_warning(self, flat) -> None:
        assert "`warnings`" in flat
        assert "drops its `always` or one of its tags" in flat

    def test_it_sends_the_reader_to_the_authoring_guide_for_the_rest(self, section) -> None:
        assert "writing-a-guide" in section

    def test_it_has_a_not_being_read_checklist(self, section) -> None:
        assert "If your guide is not being read" in section


class TestTheToolTableCarriesBothGuideTools:
    def test_list_guides_sits_next_to_read_guides(self) -> None:
        text = _ARCHITECTURE.read_text(encoding="utf-8")
        assert "| `list_guides` |" in text
        assert "| `read_guides` |" in text
        assert text.index("| `list_guides` |") < text.index("| `read_guides` |")
