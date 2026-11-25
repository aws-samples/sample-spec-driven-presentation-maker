# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for correspondence facts: what the machine reports, and what it refuses to decide.

The point of this module is that it reaches no verdict, so the first thing pinned
here is the absence of one. The definitions it implements are in the SPEC's design.md.
"""

from __future__ import annotations

import pytest

from sdpm.engine.checks.correspondence import (
    correspondence_facts,
    count_visible_characters,
    count_visible_words,
)


def region(name: str, x: float, y: float, w: float, h: float) -> dict:
    return {"_comment": f"region: {name}", "x": x, "y": y, "w": w, "h": h}


def textbox(text: str, x: float, y: float, w: float = 100, h: float = 50) -> dict:
    return {"type": "textbox", "text": text, "x": x, "y": y, "w": w, "h": h}


def deck(*elements: dict) -> dict:
    return {"slides": [{"id": "demo", "elements": list(elements)}]}


def only_slide(result: dict) -> dict:
    return result["slides"][0]


# ---------------------------------------------------------------------------
# the five facts, and the absence of a verdict
# ---------------------------------------------------------------------------


def test_every_slide_carries_every_fact() -> None:
    facts = only_slide(correspondence_facts(deck(region("body", 0, 0, 500, 300), textbox("hi", 10, 10))))
    assert set(facts) == {
        "slide",
        "visible_words",
        "visible_characters",
        "outside_regions",
        "region_sizes_by_prefix",
        "stacked_region_groups",
        "repeated_text",
    }


def test_the_facts_hold_no_boolean_and_no_verdict() -> None:
    """REQ-11.2: the reviewer decides. A machine verdict would be unoverridable."""
    result = correspondence_facts(
        deck(
            region("col-1", 0, 0, 520, 300),
            region("col-2", 520, 0, 600, 300),
            textbox("same", 10, 10),
            textbox("same", 530, 10),
            textbox("out", 400, 10, 200, 50),
        ),
        art_direction="<!-- Density: 40 -->",
    )

    forbidden = {"pass", "fail", "verdict", "ok"}
    found_booleans: list[str] = []
    found_keys: list[str] = []

    def walk(value: object, path: str) -> None:
        if isinstance(value, bool):
            found_booleans.append(path)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key in forbidden:
                    found_keys.append(f"{path}.{key}")
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(result, "facts")
    assert not found_booleans, found_booleans
    assert not found_keys, found_keys


# ---------------------------------------------------------------------------
# region sizes by prefix
# ---------------------------------------------------------------------------


def test_regions_sharing_a_prefix_report_both_sizes() -> None:
    facts = only_slide(
        correspondence_facts(deck(region("col-1", 0, 0, 520, 300), region("col-2", 520, 0, 600, 300)))
    )
    sizes = facts["region_sizes_by_prefix"]["col"]
    assert [entry["w"] for entry in sizes] == [520, 600]


def test_a_region_whose_name_does_not_end_in_a_number_joins_no_prefix_group() -> None:
    facts = only_slide(
        correspondence_facts(
            deck(region("media", 0, 0, 400, 300), region("col-1", 400, 0, 200, 300), region("col-2", 600, 0, 200, 300))
        )
    )
    assert set(facts["region_sizes_by_prefix"]) == {"col"}


# ---------------------------------------------------------------------------
# repeated text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("copies", "reported"), [(1, False), (2, True), (3, True)])
def test_a_string_is_reported_once_it_appears_twice(copies: int, reported: bool) -> None:
    boxes = [textbox("継続率", 10 + 200 * n, 10) for n in range(copies)]
    regions = [region(f"col-{n + 1}", 200 * n, 0, 200, 300) for n in range(copies)]
    facts = only_slide(correspondence_facts(deck(*regions, *boxes)))
    repeated = facts["repeated_text"]
    assert bool(repeated) is reported
    if reported:
        assert len(repeated[0]["regions"]) == copies


# ---------------------------------------------------------------------------
# elements outside their region
# ---------------------------------------------------------------------------


def test_an_element_past_its_regions_edge_reports_how_far() -> None:
    facts = only_slide(
        correspondence_facts(deck(region("body", 0, 0, 500, 300), textbox("wide", 300, 10, 240, 50)))
    )
    (outside,) = facts["outside_regions"]
    assert outside["region"] == "body"
    assert outside["overflow"] == {"right": 40}


def test_an_element_inside_its_region_is_not_reported() -> None:
    facts = only_slide(
        correspondence_facts(deck(region("body", 0, 0, 500, 300), textbox("fits", 10, 10)))
    )
    assert facts["outside_regions"] == []


# ---------------------------------------------------------------------------
# stacked region groups
# ---------------------------------------------------------------------------


def test_rows_of_regions_report_how_many_each_holds() -> None:
    top = [region(f"top-{n + 1}", 200 * n, 0, 190, 200) for n in range(5)]
    bottom = [region(f"bottom-{n + 1}", 300 * n, 400, 290, 200) for n in range(3)]
    facts = only_slide(correspondence_facts(deck(*top, *bottom)))
    assert [group["regions"] for group in facts["stacked_region_groups"]] == [5, 3]


# ---------------------------------------------------------------------------
# visible words and the style's density
# ---------------------------------------------------------------------------


def test_a_style_without_a_density_marker_reports_no_limit() -> None:
    result = correspondence_facts(deck(textbox("three visible words", 0, 0)), art_direction="<style></style>")
    assert result["density_limit"] is None
    assert only_slide(result)["visible_words"] == 3


def test_the_density_marker_is_reported_beside_the_counts() -> None:
    result = correspondence_facts(deck(textbox("two words", 0, 0)), art_direction="<!-- Density: 40 -->")
    assert result["density_limit"] == 40


def test_the_word_count_matches_the_style_contracts_rule() -> None:
    """The style contract and a slide must mean the same thing by "a word"."""
    assert count_visible_words("<p>95%&nbsp;of  users</p>") == 3
    assert count_visible_words("") == 0


# ---------------------------------------------------------------------------
# PPTX only
# ---------------------------------------------------------------------------


def test_an_html_deck_gets_no_facts_and_is_told_why() -> None:
    """REQ-11.9: an HTML deck's regions are attributes in its slide HTML, not JSON."""
    result = correspondence_facts({"outputFormat": "html", "slides": [{"id": "demo", "elements": []}]})
    assert result["slides"] == []
    assert "PPTX" in result["note"]


def test_an_unspaced_script_is_measurable_by_characters() -> None:
    """A Japanese slide counts a couple of words against a density of 45, so the word
    count alone can never show it is full."""
    japanese = "聞き手は背景をすでに知っているので、答えから始める"
    english = "The audience already knows the background, so lead with the answer"

    ja = only_slide(correspondence_facts(deck(textbox(japanese, 0, 0))))
    en = only_slide(correspondence_facts(deck(textbox(english, 0, 0))))

    assert ja["visible_words"] < en["visible_words"] / 4, "the word count collapses"
    assert ja["visible_characters"] >= en["visible_characters"] / 3, "the character count does not"
    assert ja["visible_characters"] == 25


def test_the_character_count_ignores_whitespace_and_tags() -> None:
    assert count_visible_characters("<p>two  words</p>") == 8
    assert count_visible_characters("   ") == 0


def test_an_element_in_no_region_at_all_is_reported() -> None:
    """The worst placement error: _owning_region returns None, and skipping it made the
    slide read as clean."""
    facts = only_slide(
        correspondence_facts(deck(region("body", 0, 0, 400, 300), textbox("adrift", 1200, 900)))
    )
    (outside,) = facts["outside_regions"]
    assert outside["region"] is None
    assert outside["overflow"] == {}
    assert outside["element"]["type"] == "textbox"


def test_a_slide_with_no_regions_reports_no_placement_errors() -> None:
    """Nothing to be outside of, so every element is where it was put."""
    facts = only_slide(correspondence_facts(deck(textbox("free", 10, 10))))
    assert facts["outside_regions"] == []


def test_the_styles_own_samples_give_a_script_independent_reference() -> None:
    """density_limit counts words, so it says nothing usable about Japanese. The style's
    samples are the same content drawn as the style intends."""
    from sdpm.engine.checks.correspondence import density_sample_characters

    art = (
        "<!-- Density: 45 -->\n<body>"
        '<div class="slide"><p>one two</p></div>'
        '<div class="slide"><p>three four five six</p></div>'
        "</body>"
    )
    result = correspondence_facts(deck(textbox("x", 0, 0)), art_direction=art)
    assert result["density_sample_characters"] == 17, "the fullest sample, not the first"
    assert density_sample_characters("<body>no slides here</body>") is None
