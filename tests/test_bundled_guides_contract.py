# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""What the bundled guide collection is, asserted by equality rather than by sampling.

Tags decide which role is handed which guide, so a tag added or dropped by accident
changes a prompt silently. The map below is the contract: a guide may be added only by
adding its row here, which is the point at which somebody has to think about its tags.

The content assertions are structural — a section exists, a condition is stated. What a
guide actually says is judged by a person; HUMAN_REVIEW records who and against what.
"""

from pathlib import Path

import pytest

from sdpm.knowledge.reference import TAGS, guide_meta, is_guide_name

GUIDES_DIR = Path(__file__).parents[1] / "sdpm" / "references" / "guides"

# REQ-7.8. name -> (tags, always)
BUNDLED = {
    "arch-elements": (["composer"], False),
    "arch-layout-engine": (["composer"], False),
    "attachments": (["orchestrator"], False),
    "aws-design": (["composer"], False),
    "chart-area": (["composer-pptx"], False),
    "chart-bar": (["composer-pptx"], False),
    "chart-line": (["composer-pptx"], False),
    "chart-pie": (["composer-pptx"], False),
    "chart-radar": (["composer-pptx"], False),
    "deck-json-spec": (["orchestrator"], True),
    "design-review-guide": (["orchestrator"], False),
    "design-rules": (["composer"], False),
    "design-vocabulary": (["orchestrator"], False),
    "freeform": (["composer-pptx"], False),
    "grid": (["composer", "style"], False),
    "hand-edit-sync": (["orchestrator", "management"], False),
    "html-deck": (["orchestrator"], False),
    "import-pptx": (["orchestrator", "style", "translate", "management"], False),
    "slide-html-scripts": (["composer-html"], False),
    "slide-html-spec": (["composer-html"], True),
    "slide-json-effects": (["composer-pptx"], False),
    "slide-json-elements": (["composer-pptx"], False),
    "slide-json-media": (["composer-pptx"], False),
    "slide-json-spec": (["composer-pptx", "translate"], True),
    "source-material-guide": (["orchestrator"], False),
    "story-line": (["orchestrator"], True),
    "table": (["composer"], False),
    "verify": (["composer"], True),
    "visual-forms": (["composer", "style"], False),
    "writing-a-guide": (["management", "orchestrator"], False),
    "writing-ja": (["orchestrator", "composer"], False),
}

# REQ-9.6. The content of a rewritten or newly authored guide is read by a person; these
# rows say by whom, against what, and where the receipt goes. A row with a blank field is
# a row nobody can act on, so the test below rejects one.
HUMAN_REVIEW = {
    "story-line": {
        "reviewer": "the maintainer who writes decks with sdpm",
        "criterion": "pick a backbone for a deck you have already written, using only the five "
                     "families and their When clauses",
        "passes_when": "the family you reach matches the structure that deck actually used, and no "
                       "second family reads as equally right",
        "receipt": "notes.md ## Code Review Ledger",
    },
    "verify": {
        "reviewer": "the maintainer, against a slide an sdpm composer already produced",
        "criterion": "walk the asserts table and the text rules over that slide",
        "passes_when": "every rule is decidable by looking at the slide, and at least one real "
                       "defect in the deck's history would have been caught",
        "receipt": "notes.md ## Code Review Ledger",
    },
    "writing-a-guide": {
        "reviewer": "someone who has not written an sdpm guide before",
        "criterion": "write a valid guide of their own from this document alone, without reading "
                     "the frontmatter parser or another guide's source",
        "passes_when": "the guide they produce is valid on the first attempt and its tags are the "
                       "ones a reviewer would have chosen",
        "receipt": "notes.md ## Code Review Ledger",
    },
    "source-material-guide": {
        "reviewer": "the maintainer, with a real PPTX to reuse material from",
        "criterion": "follow the document against the current deck workspace",
        "passes_when": "every path and tool it names exists and does what it says, and the reuse "
                       "decision reaches a composer",
        "receipt": "notes.md ## Code Review Ledger",
    },
    "writing-ja": {
        "reviewer": "a Japanese-speaking maintainer",
        "criterion": "read the description alone and decide whether a given deck needs this guide",
        "passes_when": "the decision is reached from the first clause, with no code consulted",
        "receipt": "notes.md ## Code Review Ledger",
    },
}


@pytest.fixture(scope="module")
def metas() -> dict[str, dict]:
    return {p.stem: guide_meta(p.stem, p.read_text(encoding="utf-8")) for p in sorted(GUIDES_DIR.glob("*.md"))}


def body(name: str) -> str:
    return (GUIDES_DIR / f"{name}.md").read_text(encoding="utf-8")


class TestTheCollection:
    def test_the_bundled_guides_are_exactly_these(self, metas) -> None:
        assert sorted(metas) == sorted(BUNDLED)

    def test_every_guide_is_valid(self, metas) -> None:
        assert {n: m["category"] for n, m in metas.items() if "category" in m} == {}

    def test_tags_are_exactly_the_contract(self, metas) -> None:
        assert {n: m["tags"] for n, m in metas.items()} == {n: tags for n, (tags, _) in BUNDLED.items()}

    def test_always_is_exactly_the_contract(self, metas) -> None:
        assert {n: m["always"] for n, m in metas.items()} == {n: always for n, (_, always) in BUNDLED.items()}

    def test_five_guides_are_handed_over_automatically(self, metas) -> None:
        assert sorted(n for n, m in metas.items() if m["always"]) == [
            "deck-json-spec",
            "slide-html-spec",
            "slide-json-spec",
            "story-line",
            "verify",
        ]

    def test_management_holds_exactly_three(self, metas) -> None:
        assert sorted(n for n, m in metas.items() if "management" in m["tags"]) == [
            "hand-edit-sync",
            "import-pptx",
            "writing-a-guide",
        ]

    def test_every_tag_is_in_the_vocabulary(self, metas) -> None:
        assert {tag for m in metas.values() for tag in m["tags"]} <= set(TAGS)

    def test_every_name_is_usable_as_a_name_and_a_payload_key(self, metas) -> None:
        assert [n for n in metas if not is_guide_name(n)] == []

    def test_the_dead_frontmatter_keys_are_gone(self) -> None:
        offenders = [
            p.stem
            for p in GUIDES_DIR.glob("*.md")
            for line in p.read_text(encoding="utf-8").splitlines()[:8]
            if line.startswith(("category:", "name:"))
        ]
        assert offenders == []

    def test_every_description_is_one_non_empty_line(self, metas) -> None:
        assert [n for n, m in metas.items() if not m["description"].strip()] == []

    def test_setup_is_gone(self, metas) -> None:
        assert "setup" not in metas

    def test_storytelling_vocabulary_is_gone(self, metas) -> None:
        assert "storytelling-vocabulary" not in metas


class TestStoryLine:
    """REQ-7.4: the backbones and their audience conditions open the guide."""

    FAMILIES = [
        "### Conclusion-First",
        "### Persuasion Sequence",
        "### Contrast / Vision",
        "### Narrative Arc",
        "### Logical Grouping",
    ]
    VOCABULARY = ["### Narrative Technique", "### Rhetorical Device", "### Slide Technique", "### Data Storytelling"]

    def test_the_five_families_are_there(self) -> None:
        text = body("story-line")
        assert [f for f in self.FAMILIES if f not in text] == []

    def test_each_family_states_its_audience_condition(self) -> None:
        text = body("story-line")
        for family in self.FAMILIES:
            section = text[text.index(family):]
            section = section[: section.find("###", len(family))]
            assert "**When**:" in section, family

    def test_the_families_come_before_the_vocabulary(self) -> None:
        text = body("story-line")
        assert max(text.index(f) for f in self.FAMILIES) < min(text.index(v) for v in self.VOCABULARY)

    def test_the_vocabulary_is_retained(self) -> None:
        text = body("story-line")
        assert [v for v in self.VOCABULARY if v not in text] == []
        # A sample from each retained group, so a wholesale deletion cannot pass.
        for term in ("sparkline", "anaphora", "cold-open", "small-multiples"):
            assert term in text

    SECTIONS = [
        "## Who you are writing for",
        "## Pick one backbone",
        "## How many slides",
        "## The opening",
        "## Check the outline against these, in this order",
        "## What you left out",
        "## Shape the slides inside it",
    ]

    def test_the_sections_are_in_the_order_the_work_happens(self) -> None:
        text = body("story-line")
        positions = [text.find(s) for s in self.SECTIONS]
        assert -1 not in positions, [s for s, i in zip(self.SECTIONS, positions) if i == -1]
        assert positions == sorted(positions)

    def test_it_says_to_expect_less_of_the_audience_than_the_brief_implies(self) -> None:
        section = body("story-line").split("## Who you are writing for")[1].split("\n## ")[0]
        for gap in ("Knowledge", "Foresight", "Comprehension", "Attention", "Motivation", "Condition"):
            assert f"**{gap}.**" in section, gap
        assert "least attentive" in section

    def test_the_slide_count_has_both_bounds(self) -> None:
        section = body("story-line").split("## How many slides")[1].split("\n## ")[0]
        assert "30 seconds" in section  # the floor
        for band in ("1–1.5 min", "1–2 min", "1.5–3 min"):
            assert band in section, band

    def test_the_opening_carries_the_point_on_its_own(self) -> None:
        section = body("story-line").split("## The opening")[1].split("\n## ")[0]
        assert "on its own" in section
        assert "two stages" in section

    def test_the_outline_checks_are_ordered_and_say_why(self) -> None:
        section = body("story-line").split("## Check the outline against these, in this order")[1].split("\n## ")[0]
        assert "a failure high on the list is not fixed by" in section
        for n, phrase in enumerate(
            ["Does it fit the time?", "Is what the brief asked for in here?",
             "Does each slide follow from the one before it?", "Is it concrete?",
             "Is the difficulty right?", "Is the tension managed?"], start=1):
            assert f"{n}. **{phrase}**" in section, phrase
        # The consistency check carries the sequence rule it belongs to.
        assert "the immediately preceding slide alone" in section
        assert "sawtooth" in section

    def test_the_unused_material_has_four_destinations(self) -> None:
        section = body("story-line").split("## What you left out")[1].split("\n## ")[0]
        assert "four things to do with it" in section
        assert section.count("\n- **") == 4

    def test_it_prescribes_no_particular_slide_to_place_or_omit(self) -> None:
        # Deliberately left out: a rule against a table-of-contents slide or a closing
        # "thank you" slide, and a dedicated breather slide. Which slides exist is the
        # deck's business, not this guide's.
        text = body("story-line")
        for omitted in ("table of contents", "Thank you"):
            assert omitted not in text, omitted


class TestVerify:
    """REQ-7.9: it says why these rules outlive the style that was applied."""

    def test_it_opens_with_the_replaceability_statement(self) -> None:
        opening = body("verify").split("##")[0]
        assert "can be replaced" in opening
        assert "cannot be replaced" in opening

    def test_it_covers_both_families(self) -> None:
        text = body("verify")
        assert "## What the drawing asserts" in text
        assert "## Whether the text is true" in text

    def test_the_form_rules_name_what_each_element_encodes(self) -> None:
        text = body("verify")
        for element in ("arrow", "axis", "Colour", "icon"):
            assert element in text
        assert "asserts" in text

    def test_every_form_rule_is_conditional_on_encoding_something(self) -> None:
        # The line this guide must not cross: a slide that encodes nothing with its shapes
        # breaks none of these, and how decorated a deck is belongs to the style.
        section = body("verify").split("## What the drawing asserts")[1].split("\n## ")[0]
        assert "only when the slide is using that element to encode" in section
        assert "the shape is free" in section

    def test_it_states_that_it_is_deliberately_short(self) -> None:
        opening = body("verify").split("##")[0]
        assert "short list on purpose" in opening
        assert "design-rules" in opening and "visual-forms" in opening

    def test_it_carries_no_rule_about_density_or_decoration(self) -> None:
        # Those are preferences; a style that wants more decoration is not wrong.
        text = body("verify")
        for preference in ("asserts nothing is noise", "worth adding", "Remove it."):
            assert preference not in text

    def test_the_claim_rule_does_not_assume_the_style_puts_it_in_the_headline(self) -> None:
        # writing-ja: a style may make the headline a topic and a lead line the claim.
        text = body("verify")
        assert "Whatever carries the slide's claim" in text
        assert "the style decides which" in text

    def test_the_text_rules_cover_numbers_quotes_and_gaps(self) -> None:
        text = body("verify")
        assert "Numbers come from the evidence" in text
        assert "verbatim" in text
        assert "[TBD]" in text


class TestWritingAGuide:
    """REQ-6.2: one named section per topic, and the Japanese case worked through."""

    SECTIONS = [
        "## When one guide should become two",
        "## Which tags to set",
        "## When always is justified",
        "## Naming a guide, and its one line",
        "## Bringing in a document you already have",
        "## Saying when to read it",
    ]

    def test_every_topic_has_its_own_section(self) -> None:
        text = body("writing-a-guide")
        assert [s for s in self.SECTIONS if s not in text] == []

    def test_the_frontmatter_grammar_is_documented(self) -> None:
        text = body("writing-a-guide")
        for key in ("description", "tags", "always"):
            assert key in text
        assert "64 KiB" in text

    def test_every_tag_in_the_vocabulary_is_explained(self) -> None:
        text = body("writing-a-guide")
        assert [tag for tag in TAGS if f"`{tag}`" not in text] == []

    def test_it_says_roughly_how_many_always_guides_a_role_should_carry(self) -> None:
        section = body("writing-a-guide").split("## When always is justified")[1].split("\n## ")[0]
        assert "two to five" in section

    def test_it_sends_the_author_to_the_roles_existing_mandatory_set(self) -> None:
        # Nothing in code compares two always guides, so the author has to look.
        section = body("writing-a-guide").split("## When always is justified")[1].split("\n## ")[0]
        assert "list_guides(" in section
        assert "Nothing checks this for you" in section
        assert "30,000" in section  # the limit the sum has to stay under

    def test_it_says_how_to_turn_an_existing_document_into_guides(self) -> None:
        section = body("writing-a-guide").split("## Bringing in a document you already have")[1].split("\n## ")[0]
        assert "who would read it and when" in section  # the split test
        assert "every tag it could be called under" in section
        for dropped in ("Instructions about the other tool", "restate what sdpm already does", "own preamble"):
            assert dropped in section

    def test_the_japanese_deck_case_is_worked_through(self) -> None:
        section = body("writing-a-guide").split("## Saying when to read it")[1]
        assert "writing-ja" in section
        assert "Japanese" in section
        # Both rejected alternatives are named, which is what makes it worked through.
        assert "always: true` is wrong" in section
        assert "in code is also wrong" in section


class TestSourceMaterialGuide:
    """REQ-7.3: the current deck workspace, and the subject kept."""

    def test_the_retired_locations_are_gone(self) -> None:
        text = body("source-material-guide")
        assert "/tmp/sdpm" not in text
        assert "Phase 1" not in text

    def test_it_names_the_import_bundle(self) -> None:
        text = body("source-material-guide")
        assert "import_attachment" in text
        assert "bundlePath" in text

    def test_it_keeps_its_subject(self) -> None:
        text = body("source-material-guide")
        assert "material for a new deck" in text
        assert "import-pptx" in text  # the other branch, named so the reader can tell them apart

    def test_colours_still_never_carry_over(self) -> None:
        text = body("source-material-guide")
        assert "fontColor" in text
        assert "design-rules" in text


class TestWritingJa:
    """REQ-7.7: the condition that selects it leads the description."""

    def test_the_condition_is_the_first_clause(self, metas) -> None:
        assert metas["writing-ja"]["description"].startswith("Read when the deck's language is Japanese")

    def test_it_is_not_handed_over_automatically(self, metas) -> None:
        # An English deck would otherwise carry Japanese typography rules in its prompt.
        assert metas["writing-ja"]["always"] is False

    def test_line_breaks_are_one_of_the_topics_the_description_lists(self, metas) -> None:
        assert "where a line may break" in metas["writing-ja"]["description"]

    def test_it_has_a_section_on_where_a_line_may_break(self) -> None:
        assert "## 改行" in body("writing-ja")

    def test_kinsoku_is_attributed_to_the_builder_not_to_the_author(self) -> None:
        # formatting.py sets lang="ja-JP" on every CJK run, so a rule telling the author to keep
        # 、。）」 off a line start would be work nobody needs to do.
        section = body("writing-ja").split("## 改行")[1]
        assert "禁則処理" in section
        assert "組み上げる側が行う" in section

    def test_a_manual_break_goes_on_a_clause_boundary(self) -> None:
        section = body("writing-ja").split("## 改行")[1]
        assert "文節の切れ目" in section
        for inside in ("語の途中", "カタカナ語の途中", "数値と単位の間", "製品名の中"):
            assert inside in section

    def test_it_rules_out_a_one_or_two_character_last_line(self) -> None:
        section = body("writing-ja").split("## 改行")[1]
        assert "最後の行に 1〜2 字だけ残さない" in section

    def test_a_manual_break_is_sent_to_be_measured(self) -> None:
        # The break is tied to the font size and the box width it was written against.
        section = body("writing-ja").split("## 改行")[1]
        assert "measure_slides" in section
        assert "文字の大きさと枠の幅" in section


class TestHumanReviewChecklist:
    """The checklist is itself checked: a row with a missing field helps nobody."""

    def test_it_covers_every_rewritten_or_authored_guide(self) -> None:
        assert sorted(HUMAN_REVIEW) == [
            "source-material-guide",
            "story-line",
            "verify",
            "writing-a-guide",
            "writing-ja",
        ]

    @pytest.mark.parametrize("name", sorted(HUMAN_REVIEW))
    def test_each_row_names_a_reviewer_a_criterion_a_pass_condition_and_a_receipt(self, name) -> None:
        row = HUMAN_REVIEW[name]
        assert sorted(row) == ["criterion", "passes_when", "receipt", "reviewer"]
        assert [k for k, v in row.items() if not v.strip()] == []
        assert row["receipt"] == "notes.md ## Code Review Ledger"

    def test_every_reviewed_guide_is_a_bundled_guide(self) -> None:
        assert set(HUMAN_REVIEW) <= set(BUNDLED)
