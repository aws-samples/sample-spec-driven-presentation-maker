# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The one morph rule that cannot be checked inside a single slide.

A ``morphId`` only does something if the **adjacent** slide carries the same
string, and that slide is a different file. Every other morph rule — character
set, uniqueness — is validated per slide by the identity validator, which by
construction cannot see the other half.

That half is what parallel composition breaks: one composer owns slide 3,
another owns slide 4, neither reads the other's draft, and a one-character
divergence builds cleanly while PowerPoint silently falls back to its own
matching. These tests pin that it is caught, and — just as important — that a
deck which uses no Morph hears nothing.
"""

from __future__ import annotations

import pytest

from sdpm.engine.checks import check_morph_pairing
from sdpm.engine.checks.morph_pairing import morph_pairing_summary

MORPH = {"effect": "morph", "parameters": {"variant": "byObject"}}


def _slide(slug, *morph_ids, transition=None, placeholder_morph=None):
    slide = {
        "id": slug,
        "elements": [
            {"type": "shape", "id": f"shape-{index}", "morphId": morph_id}
            for index, morph_id in enumerate(morph_ids)
        ],
    }
    if transition is not None:
        slide["transition"] = transition
    if placeholder_morph is not None:
        slide["placeholders"] = {"0": {"text": "Title", "morphId": placeholder_morph}}
    return slide


def _deck(*slides):
    return {"slides": list(slides)}


# --- silence, which is the common case --------------------------------------
@pytest.mark.parametrize(
    "deck,why",
    [
        ({}, "no slides at all"),
        (_deck(_slide("a"), _slide("b")), "an ordinary deck with no motion"),
        (
            _deck(_slide("a", "card"), _slide("b", "card", transition=MORPH)),
            "a correctly paired Morph",
        ),
        (
            _deck(_slide("a"), _slide("b", transition=MORPH)),
            "Morph with no morphId at all, which is the documented fallback to "
            "PowerPoint's own matching and not an error",
        ),
        (
            _deck(
                _slide("a", "card"),
                _slide("b", "card", transition=MORPH),
                _slide("c", "card", transition=MORPH),
            ),
            "a chain where each slide pairs with the next",
        ),
    ],
    ids=["empty", "no-motion", "paired", "morph-without-ids", "chain"],
)
def test_it_says_nothing_when_there_is_nothing_to_say(deck, why):
    assert check_morph_pairing(deck) == [], why


def test_a_deck_with_no_morph_costs_nothing_to_check():
    """Animations are off by default, so the overwhelmingly common deck must not
    pay for this check. It returns before looking at a single element."""
    deck = _deck(*[_slide(f"s{index}") for index in range(200)])
    assert check_morph_pairing(deck) == []


# --- the failure it exists for ---------------------------------------------
def test_the_one_character_divergence_two_composers_cannot_see():
    """Reported from **both** sides, each naming the other's near miss.

    Either author can fix it, and neither can see the other's file, so the
    message has to carry the string they do not have.
    """
    found = check_morph_pairing(
        _deck(
            _slide("pricing", "pricing-card"),
            _slide("detail", "price-card", transition=MORPH),
        )
    )
    assert len(found) == 2
    # Anchored at the start, because each warning also *names* the other slide
    # as the partner it failed to pair with — a substring match picks the wrong
    # line, which is how this test first failed.
    from_pricing = next(line for line in found if line.startswith("slide 'pricing'"))
    from_detail = next(line for line in found if line.startswith("slide 'detail'"))
    assert "'pricing-card' pairs with nothing on slide 'detail'" in from_pricing
    assert "['price-card']" in from_pricing, "it names the near miss on the other side"
    assert "'price-card' pairs with nothing on slide 'pricing'" in from_detail
    assert "['pricing-card']" in from_detail


def test_a_half_written_pair_is_caught():
    found = check_morph_pairing(
        _deck(_slide("a"), _slide("b", "card", transition=MORPH))
    )
    assert len(found) == 1
    assert "pairs with nothing on slide 'a'" in found[0]
    assert "['none']" in found[0], "there is nothing on the other side to suggest"


def test_a_partly_paired_slide_reports_only_the_unpaired_id():
    """One good pairing does not excuse the others: an id that matches nothing
    does nothing, whatever its neighbours do."""
    found = check_morph_pairing(
        _deck(
            _slide("a", "card", "logo"),
            _slide("b", "card", "logoo", transition=MORPH),
        )
    )
    assert len(found) == 2
    assert all("'card'" not in line for line in found), "the paired id is not mentioned"
    assert any("'logo' pairs with nothing" in line for line in found)
    assert any("'logoo' pairs with nothing" in line for line in found)


def test_morph_ids_with_no_morph_transition_anywhere_are_reported():
    """The other way to end up with nothing: the ids pair but nobody morphs."""
    found = check_morph_pairing(_deck(_slide("a", "card"), _slide("b", "card")))
    assert len(found) == 2
    assert all("does nothing" in line for line in found)
    assert all("no adjacent slide has a Morph transition" in line for line in found)
    assert all('"effect": "morph"' in line for line in found), "it names the fix"


def test_a_morph_on_the_first_slide_says_what_is_wrong_with_it():
    """Slide 1 has nothing before it, so its morphIds cannot pair backwards."""
    found = check_morph_pairing(_deck(_slide("a", "card", transition=MORPH)))
    assert len(found) == 1
    assert "nothing to morph from" in found[0]


def test_a_placeholder_can_carry_a_morph_identity():
    """Scoped exactly as the identity validator scopes it: elements plus
    placeholders. A title that morphs is a normal thing to want."""
    found = check_morph_pairing(
        _deck(
            _slide("a", placeholder_morph="heading"),
            _slide("b", placeholder_morph="headng", transition=MORPH),
        )
    )
    assert len(found) == 2
    assert any("placeholders['0'].morphId 'heading'" in line for line in found)
    assert any("placeholders['0'].morphId 'headng'" in line for line in found)


def test_a_slide_without_a_slug_is_named_by_its_position():
    found = check_morph_pairing(
        _deck({"elements": [{"type": "shape", "morphId": "card"}]}, {"elements": []})
    )
    assert len(found) == 1
    assert "slide 1" in found[0]


def test_the_summary_reports_the_pairing_as_data():
    summary = morph_pairing_summary(
        _deck(_slide("a", "card"), _slide("b", "card", transition=MORPH))
    )
    assert summary["slides"] == [
        {"slide": "slide 'a'", "morphTransition": False, "morphIds": ["card"]},
        {"slide": "slide 'b'", "morphTransition": True, "morphIds": ["card"]},
    ]
    assert summary["warnings"] == []


# --- the gate that keeps it honest for a parallel composer ------------------
REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


def _deck_dir(tmp_path, *, with_typo: bool):
    """A two-slide deck where slide 2 morphs from slide 1."""
    import json

    deck = tmp_path / "deck"
    (deck / "slides").mkdir(parents=True)
    (deck / "specs").mkdir()
    (deck / "deck.json").write_text(
        json.dumps(
            {
                "template": str(REPO_ROOT / "sdpm/templates/blank-dark.pptx"),
                "fonts": {"fullwidth": "Meiryo", "halfwidth": "Arial"},
                "defaultTextColor": "#FFFFFF",
                "transitions": {"enabled": True},
            }
        )
    )
    (deck / "specs/outline.md").write_text("- [one] first\n- [two] second\n")
    box = {"type": "shape", "shape": "rectangle", "x": 100, "y": 200, "width": 300, "height": 120}
    (deck / "slides/one.json").write_text(
        json.dumps({"id": "one", "layout": "Blank", "elements": [{**box, "id": "card", "morphId": "pricing-card"}]})
    )
    (deck / "slides/two.json").write_text(
        json.dumps(
            {
                "id": "two",
                "layout": "Blank",
                "transition": {"effect": "morph", "parameters": {"variant": "byObject"}},
                "elements": [
                    {**box, "id": "card", "morphId": "price-card" if with_typo else "pricing-card"}
                ],
            }
        )
    )
    return deck


def _warnings(deck, tmp_path, *, only_slugs=None, name="out.pptx"):
    from sdpm.api import generate

    result = generate(
        json_path=str(deck),
        output_path=str(tmp_path / name),
        only_slugs=only_slugs,
        transition_mode="on",
    )
    return [line for line in result["warnings"] if "morphId" in line]


def test_a_full_build_reports_the_divergence(tmp_path):
    deck = _deck_dir(tmp_path, with_typo=True)
    found = _warnings(deck, tmp_path)
    assert len(found) == 2, found
    assert any("'pricing-card' pairs with nothing" in line for line in found)


def test_a_correct_deck_builds_without_the_warning(tmp_path):
    deck = _deck_dir(tmp_path, with_typo=False)
    assert _warnings(deck, tmp_path) == []


def test_a_partial_build_does_not_accuse_a_correct_deck(tmp_path):
    """The gate that matters most, because it protects the parallel case itself.

    A composer verifying only its own slides builds with `only_slugs`, so the
    neighbouring slide is not in the assembly at all. Judging pairing there
    would tell every composer of a **correct** deck that its morphId is broken —
    the check would fire hardest exactly where it is least able to see. So a
    partial build stays silent and pairing is judged on the full assembly.
    """
    deck = _deck_dir(tmp_path, with_typo=False)
    assert _warnings(deck, tmp_path, only_slugs={"two"}, name="partial-ok.pptx") == []

    # And it stays silent even when the deck really is broken, which is the
    # honest cost of not being able to see the other half.
    broken = _deck_dir(tmp_path / "broken", with_typo=True)
    assert _warnings(broken, tmp_path, only_slugs={"two"}, name="partial-bad.pptx") == []
    # The same deck, assembled whole, does report it.
    assert len(_warnings(broken, tmp_path, name="whole-bad.pptx")) == 2
