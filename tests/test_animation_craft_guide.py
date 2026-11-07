# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The craft guide: catalogued, reachable, and honest about its sources.

The mechanical guide (`animations.md`) and this one are a pair: one says what is
authorable, the other says what is worth authoring. Nothing stops them drifting
apart except a test, so these check the join rather than the prose. The guide's
advice is deliberately recommendation-shaped, so none of these assert an
imperative — they assert that the thing exists, is discoverable, and declares
which of its claims carry outside authority.
"""

import re
from pathlib import Path

import pytest

from sdpm import tools as contract

GUIDES = Path(__file__).parents[1] / "sdpm" / "references" / "guides"
NAME = "animation-craft"


@pytest.fixture(scope="module")
def craft():
    return (GUIDES / f"{NAME}.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def mechanics():
    return (GUIDES / "animations.md").read_text(encoding="utf-8")


class TestItIsReachable:
    def test_the_guide_file_exists(self):
        assert (GUIDES / f"{NAME}.md").is_file()

    def test_it_rides_in_the_read_guides_catalogue(self):
        """`_guide_names()` enumerates the directory, so a new guide is listed
        without touching the tool description — this pins that it stayed true."""
        assert NAME in contract.read_guides.__doc__

    def test_read_guides_serves_it(self):
        result = contract.read_guides([NAME])
        assert len(result["documents"]) == 1
        assert result["documents"][0]["content"].strip()

    def test_the_mechanical_guide_points_at_it(self, mechanics):
        assert f'read_guides(["{NAME}"])' in mechanics

    def test_it_points_back_at_the_mechanical_guide(self, craft):
        assert 'read_guides(["animations"])' in craft


class TestItSeparatesCitedFromDerived:
    """The guide mixes published findings with numbers measured only here. A
    reader has to be able to tell which is which, so the derived claims say so
    in the text rather than borrowing the authority of the citations around
    them."""

    def test_the_duration_rule_this_repo_invented_is_marked_as_derived(self, craft):
        # the feedback-vs-content split contradicts the interface-design
        # numbers it sits next to, and has no source
        section = craft[craft.index("### The adjustment this repo makes"):]
        head = section[: section.index("\n## ")]
        assert "Not cited" in head
        assert "derived" in head

    def test_the_stagger_intervals_are_marked_as_measured_here(self, craft):
        assert "Measured in this repository, not cited" in craft

    def test_the_closing_note_names_both_derived_sections(self, craft):
        note = craft[craft.index("## Sources"):]
        assert "no external authority" in note

    def test_it_declares_that_sources_are_paraphrased(self, craft):
        """Licensing: the guide summarises rather than quoting, and says so."""
        note = craft[craft.index("## Sources"):]
        assert "rephrased for compliance" in note


class TestTheSourcesAreTheOnesChosen:
    """Vendor blogs and content farms were rejected during research in favour of
    design systems, standards bodies, the vendor of the target application, and
    peer-reviewed work. That choice is the guide's main claim to being worth
    reading, so it is pinned."""

    @pytest.mark.parametrize("domain", [
        "material.io",
        "nngroup.com",
        "w3.org",
        "support.microsoft.com",
        "doi.org",
    ])
    def test_each_chosen_source_is_cited(self, craft, domain):
        assert domain in craft

    def test_every_link_is_a_markdown_link_rather_than_a_bare_url(self, craft):
        """A bare URL in a guide is not clickable in every surface that renders
        it, and the research tooling requires attribution as a link."""
        bare = re.findall(r"(?<!\()\bhttps?://\S+", craft)
        # links inside markdown syntax are preceded by '(' and excluded above
        assert bare == [], f"bare URLs: {bare}"

    def test_no_link_points_at_a_paywalled_copy_of_a_paper(self, craft):
        """Mayer is cited by DOI; a scraped copy surfaced in research and was
        deliberately not used."""
        assert "scribd" not in craft.lower()
        assert "researchgate" not in craft.lower()


class TestItCoversTheDecisionsAnAuthorFaces:
    @pytest.mark.parametrize("topic", [
        "## What motion is for",
        "## Duration",
        "## Easing",
        "## Choreography",
        "## Pacing the build",
        "## Morph",
        "## Motion is never the only carrier",
    ])
    def test_the_section_is_present(self, craft, topic):
        assert topic in craft

    @pytest.mark.parametrize("field", [
        "timing.durationMs",
        "timing.acceleration",
        "timing.deceleration",
        "start.delayMs",
        "onPageClick",
        "withPrevious",
        "morphId",
        "afterEffect",
    ])
    def test_advice_lands_on_a_real_json_field(self, craft, field):
        """Craft advice that does not name the field it changes is unactionable:
        each recommendation has to reach something an author can set."""
        assert field in craft

    def test_it_records_that_morphid_is_powerpoints_own_pairing_mechanism(self, craft):
        """Microsoft's documented `!!`-prefixed same-name scheme is what morphId
        writes. That equivalence is the fact that makes morphId trustworthy, and
        it is not written down anywhere else in the repo."""
        assert "exclamation" in craft
        assert "`morphId`" in craft

    def test_the_accessibility_section_is_not_softened_into_a_suggestion(self, craft):
        """The guide is recommendations throughout, with one exception: motion
        being optional for the audience is a requirement, and the guide has to
        keep saying so even though its register is otherwise advisory."""
        section = craft[craft.index("## Motion is never the only carrier"):]
        body = section[: section.index("\n## ")]
        assert "hard requirement" in body
        assert "2.3.3" in body

    def test_it_carries_the_defects_this_tooling_actually_produced(self, craft):
        """The anti-patterns are the five found by storyboard frames in this
        repo, not a generic list of bad practice."""
        section = craft[craft.index("## Patterns that went wrong"):]
        body = section[: section.index("\n## ")]
        for defect in ("hideOnNextClick", "afterEffect: hide", "dim", "entrance"):
            assert defect in body


class TestItServesBothRegisters:
    """The guide's first draft was restrained-presentation only, and its own
    numbers would have rejected the cinematic decks in this repository. The
    register table is what reconciles them, so these pin that it stayed."""

    def test_it_makes_the_author_pick_a_register(self, craft):
        assert "## Pick a register first" in craft

    @pytest.mark.parametrize("register", ["presenter", "cinematic"])
    def test_both_registers_are_named(self, craft, register):
        assert f"`{register}`" in craft

    def test_the_register_is_defined_by_who_controls_the_pace(self, craft):
        """Named after the mechanism rather than a vibe: every other difference
        in the table follows from who sets the pace."""
        section = craft[craft.index("## Pick a register first"):]
        body = section[: section.index("\n## ")]
        assert "who controls the pace" in body
        assert "transition.advance.afterMs" in body

    def test_it_warns_against_mixing_registers_in_one_deck(self, craft):
        section = craft[craft.index("## Pick a register first"):]
        assert "Mixed registers" in section[: section.index("\n## ")]

    def test_it_reinterprets_the_storyboard_warning_per_register(self, craft):
        """"ends with something off screen" is a defect in one register and
        expected in the other; the guide has to say which."""
        section = craft[craft.index("## Pick a register first"):]
        body = section[: section.index("\n## ")]
        assert "off" in body and "screen" in body
        assert "cinematic" in body

    def test_the_accessibility_requirement_covers_the_cinematic_register_too(self, craft):
        """A deck that plays itself is the easiest place to assume motion is
        guaranteed. It is not."""
        section = craft[craft.index("## Motion is never the only carrier"):]
        body = section[: section.index("\n## ")]
        assert "cinematic" in body


class TestTheRecipes:
    """Terse on purpose — an agent reads this inline, so each recipe is one row.
    Every one was verified by building a deck and reading it back; the values
    here are the measured ones, not plausible-looking defaults."""

    def test_there_is_a_recipe_section(self, craft):
        assert "## Recipes" in craft

    def test_it_says_the_recipes_were_verified(self, craft):
        section = craft[craft.index("## Recipes"):]
        assert "reading back" in section[: section.index("\n## ")]

    @pytest.mark.parametrize("recipe", [
        "settle into place",
        "overshoot",
        "anticipation",
        "follow-through",
        "two directions at once",
        "camera move",
        "ambient loop",
    ])
    def test_the_recipe_is_listed(self, craft, recipe):
        assert recipe in craft

    def test_anticipation_is_one_path_rather_than_two_chained_effects(self, craft):
        """Measured: a single multi-segment path whose first leg reverses
        survives verbatim into the package and round-trips, so the recipe does
        not need two effects."""
        assert "M 0 0 L -0.012 0 L 0.25 0 E" in craft

    def test_bounce_end_is_given_as_a_range_and_scoped_to_paths(self, craft):
        """Measured: 0.3 is accepted and writes bounceEnd="30000", so it is a
        free fraction, not the single 0.5 first captured. It is also motion-path
        only — an entrance publishes the control but reads disabled."""
        section = craft[craft.index("## Recipes"):]
        row = next(line for line in section.splitlines() if "overshoot" in line)
        assert "0–1" in row
        assert "paths only" in row


class TestTheEasingTranslation:
    """PowerPoint has no bézier easing, so published curve values cannot be
    ported. The mapping to acceleration/deceleration is the part of this guide
    that exists nowhere else."""

    def test_it_states_that_bezier_easing_is_unavailable(self, craft):
        section = craft[craft.index("## Easing"):]
        body = section[: section.index("\n## ")]
        assert "no bézier easing" in body or "no bezier easing" in body

    @pytest.mark.parametrize("intent", ["ease-out", "ease-in", "ease-in-out"])
    def test_each_web_easing_intent_has_an_sdpm_equivalent(self, craft, intent):
        section = craft[craft.index("## Easing"):]
        assert intent in section[: section.index("\n## ")]

    def test_it_admits_what_cannot_be_expressed(self, craft):
        """Spring and overshoot have no easing equivalent. Saying so is more
        useful than offering an approximation that does not look like one."""
        section = craft[craft.index("## Easing"):]
        body = section[: section.index("\n## ")]
        assert "not expressible" in body
        assert "does not exist here" in body

    def test_the_half_duration_figure_is_sourced_to_powerpoints_own_control(self, craft):
        """0.5 is what Smooth Start/Smooth End record, measured this session —
        not a number chosen because it looked round."""
        section = craft[craft.index("## Easing"):]
        assert "Smooth Start" in section[: section.index("\n## ")]


class TestTextInMotion:
    def test_there_is_a_section_on_animating_text(self, craft):
        assert "## Text in motion" in craft

    def test_it_states_the_readability_constraint(self, craft):
        """Text differs from a shape: a reader must not have to wait for motion
        to finish before the words can be read."""
        section = craft[craft.index("## Text in motion"):]
        body = section[: section.index("\n## ")]
        assert "readable in its final state" in body

    def test_it_rules_out_per_character_motion_on_body_copy(self, craft):
        section = craft[craft.index("## Text in motion"):]
        assert "per-character" in section[: section.index("\n## ")]
