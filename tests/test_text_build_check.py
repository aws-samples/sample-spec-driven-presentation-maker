"""The text-build check: a sequence/level pair, and attribute-free values.

Every expectation here was measured by generating a package and reading it
back (see the module docstring of sdpm.engine.checks.text_build); these tests
pin the warning, not the OOXML.
"""

from sdpm.engine.checks.text_build import (
    check_text_build,
    text_build_summary,
)


def _deck(*text_blocks, slide_id="probe"):
    """A deck whose one slide carries one effect per given text block."""
    return {
        "slides": [
            {
                "id": slide_id,
                "animations": {
                    "mainSequence": [
                        {
                            "id": f"reveal-{index}",
                            "target": {"element": "body"},
                            "preset": {"category": "entrance", "effect": "fade"},
                            "text": block,
                        }
                        for index, block in enumerate(text_blocks)
                    ],
                    "interactiveSequences": [],
                },
            }
        ]
    }


class TestTheCheckStaysQuiet:
    def test_a_deck_with_no_slides_says_nothing(self):
        assert check_text_build({}) == []
        assert check_text_build({"slides": []}) == []

    def test_a_deck_with_no_animations_says_nothing(self):
        assert check_text_build({"slides": [{"id": "plain", "elements": []}]}) == []

    def test_an_effect_with_no_text_block_says_nothing(self):
        deck = _deck()
        deck["slides"][0]["animations"]["mainSequence"] = [
            {"id": "plain", "target": {"element": "body"},
             "preset": {"category": "entrance", "effect": "fade"}}
        ]
        assert check_text_build(deck) == []

    def test_a_sequence_on_its_own_round_trips_so_it_is_not_warned(self):
        assert check_text_build(_deck({"sequence": "byParagraph"})) == []

    def test_a_level_on_its_own_round_trips_so_it_is_not_warned(self):
        assert check_text_build(_deck({"level": "byParagraphLevel2"})) == []

    def test_a_unit_on_its_own_is_not_this_check_s_business(self):
        assert check_text_build(
            _deck({"unit": "byWord", "interItemDelayPercent": 10})
        ) == []

    def test_a_non_mapping_text_block_is_ignored_rather_than_crashing(self):
        assert check_text_build(_deck("byParagraph")) == []


class TestThePair:
    def test_setting_both_sequence_and_level_warns_once(self):
        warnings = check_text_build(
            _deck({"sequence": "byParagraph", "level": "byParagraphLevel1"})
        )
        assert len(warnings) == 1
        assert "text.sequence 'byParagraph'" in warnings[0]
        assert "text.level 'byParagraphLevel1'" in warnings[0]

    def test_the_warning_does_not_predict_which_field_survives(self):
        """Measured: byParagraph+level keeps the level, allAtOnce+allParagraph
        keeps the sequence, asOneObject+asOneObject keeps neither. A warning
        naming a winner would be wrong for two of the three."""
        warning = check_text_build(
            _deck({"sequence": "byParagraph", "level": "byParagraphLevel1"})
        )[0]
        assert "which one depends on the values" in warning
        assert "only text.level survives" not in warning

    def test_the_warning_names_the_slide_the_effect_and_the_json_path(self):
        warning = check_text_build(
            _deck({"sequence": "allAtOnce", "level": "allParagraphLevels"},
                  slide_id="pricing")
        )[0]
        assert "slide 'pricing'" in warning
        assert "effect 'reveal-0'" in warning
        assert "animations.mainSequence[0].text" in warning

    def test_an_unnamed_effect_falls_back_to_its_path(self):
        deck = _deck({"sequence": "byParagraph", "level": "byParagraphLevel1"})
        del deck["slides"][0]["animations"]["mainSequence"][0]["id"]
        warning = check_text_build(deck)[0]
        assert "animations.mainSequence[0]" in warning

    def test_an_unnamed_slide_falls_back_to_its_position(self):
        deck = _deck({"sequence": "byParagraph", "level": "byParagraphLevel1"})
        del deck["slides"][0]["id"]
        assert "slide 1" in check_text_build(deck)[0]

    def test_each_offending_effect_is_reported_separately(self):
        warnings = check_text_build(
            _deck({"sequence": "byParagraph", "level": "byParagraphLevel1"},
                  {"level": "byParagraphLevel2"},
                  {"sequence": "allAtOnce", "level": "allParagraphLevels"})
        )
        assert len(warnings) == 2
        assert "'reveal-0'" in warnings[0]
        assert "'reveal-2'" in warnings[1]


class TestAnAttributeFreeValue:
    def test_as_one_object_as_a_sequence_warns_that_the_text_block_is_lost(self):
        warnings = check_text_build(_deck({"sequence": "asOneObject"}))
        assert len(warnings) == 1
        assert "records no p:bldP attributes" in warnings[0]
        assert "text block will be absent" in warnings[0]

    def test_as_one_object_as_a_level_warns_the_same_way(self):
        warnings = check_text_build(_deck({"level": "asOneObject"}))
        assert len(warnings) == 1
        assert "text.level 'asOneObject'" in warnings[0]

    def test_the_warning_says_the_animation_still_plays(self):
        """The package is correct — only the round-trip loses it — so the
        warning must not read as though the deck is broken."""
        assert "The animation still plays as asked" in (
            check_text_build(_deck({"sequence": "asOneObject"}))[0]
        )

    def test_as_one_object_on_both_fields_warns_for_the_pair_and_for_each(self):
        warnings = check_text_build(
            _deck({"sequence": "asOneObject", "level": "asOneObject"})
        )
        assert len(warnings) == 3


class TestInteractiveSequences:
    def test_an_effect_inside_an_interactive_sequence_is_checked_too(self):
        deck = {
            "slides": [{
                "id": "probe",
                "animations": {
                    "mainSequence": [],
                    "interactiveSequences": [{
                        "id": "on-click",
                        "trigger": {"type": "onShapeClick", "target": "hero"},
                        "effects": [{
                            "id": "deep",
                            "target": {"element": "body"},
                            "text": {"sequence": "byParagraph",
                                     "level": "byParagraphLevel1"},
                        }],
                    }],
                },
            }]
        }
        warnings = check_text_build(deck)
        assert len(warnings) == 1
        assert "animations.interactiveSequences[0].effects[0].text" in warnings[0]

    def test_a_malformed_sequence_is_skipped_rather_than_crashing(self):
        deck = {"slides": [{"id": "probe", "animations": {
            "mainSequence": [], "interactiveSequences": ["nonsense", None]}}]}
        assert check_text_build(deck) == []


class TestTheSummary:
    def test_the_summary_inventories_every_text_build_with_its_warnings(self):
        summary = text_build_summary(
            _deck({"sequence": "byParagraph", "level": "byParagraphLevel1"},
                  {"unit": "byWord", "interItemDelayPercent": 10})
        )
        assert len(summary["slides"]) == 1
        builds = summary["slides"][0]["textBuilds"]
        assert len(builds) == 2
        assert builds[0]["sequence"] == "byParagraph"
        assert builds[0]["level"] == "byParagraphLevel1"
        assert builds[1]["unit"] == "byWord"
        assert len(summary["warnings"]) == 1

    def test_the_summary_of_a_clean_deck_lists_no_warnings(self):
        summary = text_build_summary(_deck({"level": "byParagraphLevel1"}))
        assert summary["warnings"] == []
        assert summary["slides"][0]["textBuilds"][0]["level"] == "byParagraphLevel1"
