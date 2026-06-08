# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for sdpm.schema.lint_outline."""

from sdpm.schema.lint_outline import lint_outline


class TestBasicOutline:
    def test_valid_skeleton(self):
        text = (
            "- [title] Audience knows the topic\n"
            "- [big-picture] Audience sees the overview\n"
        )
        assert lint_outline(text) == []

    def test_no_slides(self):
        text = "Just some free text without any slide entries\n"
        diags = lint_outline(text)
        assert len(diags) == 1
        assert diags[0]["rule"] == "no-slides"

    def test_free_text_with_slides(self):
        text = (
            "Some intro text\n"
            "- [title] First slide\n"
            "Random notes here\n"
            "- [closing] Last slide\n"
        )
        assert lint_outline(text) == []

    def test_duplicate_slug(self):
        text = (
            "- [title] First\n"
            "- [title] Second\n"
        )
        diags = lint_outline(text)
        assert any(d["rule"] == "slug-duplicate" for d in diags)

    def test_invalid_slug(self):
        text = "- [Title_Case] Bad slug\n"
        diags = lint_outline(text)
        assert any(d["rule"] == "slug-pattern" for d in diags)

    def test_headers_and_blanks_ignored(self):
        text = "# Outline\n\n- [title] Topic\n\n"
        assert lint_outline(text) == []


class TestDetailedOutline:
    def test_sub_items_valid(self):
        text = (
            "- [title] Audience knows the topic\n"
            "  - what_to_say: The key point\n"
            "  - evidence: Data supporting the claim\n"
            "  - what_to_show: Screenshot of the feature\n"
            "  - notes: Anticipated questions\n"
        )
        assert lint_outline(text) == []

    def test_partial_sub_items(self):
        text = (
            "- [title] Audience knows the topic\n"
            "  - what_to_say: Only this one\n"
            "- [next] Another slide\n"
        )
        assert lint_outline(text) == []

    def test_mixed_skeleton_and_detailed(self):
        text = (
            "- [title] Audience knows the topic\n"
            "  - what_to_say: Key point\n"
            "- [overview] No details here\n"
            "- [deep-dive] Has details\n"
            "  - evidence: Some data [TBD]\n"
        )
        assert lint_outline(text) == []

    def test_tab_indented_sub_items(self):
        text = (
            "- [title] Topic\n"
            "\t- what_to_say: Key point\n"
        )
        assert lint_outline(text) == []
