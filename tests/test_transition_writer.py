# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""OOXML generation tests for the slide-transition writer.

The writer must reproduce every transition the catalog accepts — standard
elements, the p14/p15/p159 extension families, Morph, directions, variants,
durations and advance conditions — in the AlternateContent form PowerPoint
reads, and must refuse an extension variant whose attribute values were never
captured instead of guessing them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from sdpm.engine.builder import PPTXBuilder
from sdpm.engine.timing import (
    TRANSITION_STRATEGIES,
    CapabilityGapError,
    TransitionWriteError,
    build_transition,
    catalog_coverage,
    load_capability_index,
    remove_transition,
    resolve_transition,
    write_slide_transition,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "sdpm" / "templates" / "blank-dark.pptx"
CATALOG_PATH = REPO_ROOT / "sdpm" / "references" / "catalogs" / "powerpoint-animation-catalog.json"
NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
    "p15": "http://schemas.microsoft.com/office/powerpoint/2012/main",
    "p159": "http://schemas.microsoft.com/office/powerpoint/2015/09/main",
}

#: Counted baseline of the transition surface the writer covers, taken from the
#: shared :func:`catalog_coverage` pass. 49 captured gallery tiles (48 effects
#: plus the non-persisted None tile), six standard ECMA-376 elements with no
#: tile, and the EPPEntryEffect variants. ``controls`` are the accepted
#: transition entries that modify a transition (duration, advance, sound,
#: Morph object matching) instead of choosing its element.
#: The scripting-oracle capture under
#: ``tests/fixtures/animations/oracle-16.113.1`` asked PowerPoint for every
#: EPPEntryEffect value and kept what it wrote, so no transition element entry
#: is capture-required any more: ``refused`` is 0 and the 60 refusals that were
#: split ``{"p14": 50, "p15": 9, "standard": 1}`` are now generated from their
#: own measurement. The two refused entries left on the transition side are the
#: sound controls, whose relationship form the capture does not contain.
TRANSITION_COVERAGE = {
    "galleryTiles": 49,
    "acceptedTiles": 48,
    # 214, not 213: the reversed Clock writes once the parameter set that
    # selects it is kept apart from the attributes it emits, which leaves no
    # refused transition element at all.
    "generated": 214,
    "refused": 0,
    "refusedByStrategy": {},
    "controls": 6,
    "controlStrategies": {"attribute", "shapeName", "relationship"},
    "refusedControls": {"transition.sound.effect", "transition.sound.loopUntilNext"},
}


@pytest.fixture(scope="module")
def index():
    return load_capability_index()


@pytest.fixture(scope="module")
def coverage(index):
    """One shared generated/refused pass over every accepted catalog entry."""
    return catalog_coverage(index)


@pytest.fixture(scope="module")
def catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _transition(effect, parameters=None, duration=None, advance=None, sound=None):
    return {
        "effect": effect,
        "parameters": parameters or {},
        "durationMs": duration,
        "advance": advance if advance is not None else {"onClick": True, "afterMs": None},
        "sound": sound,
    }


def _node(effect, **kwargs):
    node, report = build_transition(_transition(effect, **kwargs))
    return etree.fromstring(etree.tostring(node)), report


def _build(slide_def, *, transitions=True):
    builder = PPTXBuilder(
        TEMPLATE,
        fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"},
        default_text_color="#FFFFFF",
        animations_enabled=False,
        transitions_enabled=transitions,
    )
    slide = builder.add_slide(slide_def)
    return builder, etree.fromstring(etree.tostring(slide._element)), slide


def _slide(transition=None, **patch):
    slide = {
        "id": "entering",
        "layout": "Blank",
        "elements": [{"id": "hero", "type": "textbox", "text": "Hero", "x": 10, "y": 10, "width": 200, "height": 50}],
    }
    if transition is not None:
        slide["transition"] = transition
    slide.update(patch)
    return slide


# --- the captured gallery --------------------------------------------------


def test_every_captured_gallery_tile_is_generated(catalog, index):
    tiles = [entry for entry in catalog["guiItems"] if entry["key"].startswith("transition.gallery.")]
    assert len(tiles) == TRANSITION_COVERAGE["galleryTiles"]
    accepted = [tile for tile in tiles if tile["status"] == "accepted"]
    assert len(accepted) == TRANSITION_COVERAGE["acceptedTiles"]
    strategies = set()
    for tile in accepted:
        node, report = build_transition(tile["semanticJson"]["transition"], index=index)
        assert etree.QName(node).localname in {"transition", "AlternateContent"}
        strategies.add(report["strategy"])
        xml = etree.tostring(node).decode()
        assert tile["ooxml"]["element"].split(":")[-1] in xml
    assert strategies == {"standard", "p14", "p15", "p159"}


def test_the_none_tile_is_represented_by_omitting_the_transition(catalog):
    none_tile = next(e for e in catalog["guiItems"] if e["key"] == "transition.gallery.none")
    assert none_tile["status"] == "nonPersisted"
    _, root, _slide_obj = _build(_slide())
    assert root.xpath(".//*[local-name()='transition']") == []


def test_standard_strategy_writes_a_direct_transition():
    node, report = _node("push", parameters={"dir": "u"}, duration=1000)
    assert etree.QName(node).localname == "transition"
    assert report["alternateContent"] is False
    assert node.xpath("./p:push/@dir", namespaces=NS) == ["u"]
    assert node.get("spd") == "slow"
    assert node.get("{%s}dur" % NS["p14"]) is None


@pytest.mark.parametrize(
    "effect,requires,element",
    [
        ("ripple", "p14", "p14:ripple"),
        ("honeycomb", "p14", "p14:honeycomb"),
        ("vortex", "p14", "p14:vortex"),
        ("prestige", "p15", "p15:prstTrans"),
        ("curtains", "p15", "p15:prstTrans"),
        ("morph", "p159", "p159:morph"),
    ],
)
def test_extension_strategies_use_alternate_content_with_a_fade_fallback(effect, requires, element):
    node, report = _node(effect)
    assert etree.QName(node).localname == "AlternateContent"
    assert report["requires"] == requires
    choice = node.xpath("./mc:Choice", namespaces=NS)
    assert len(choice) == 1 and choice[0].get("Requires") == requires
    prefix, local = element.split(":")
    assert choice[0].xpath(f"./p:transition/{prefix}:{local}", namespaces=NS)
    fallback = node.xpath("./mc:Fallback/p:transition/p:fade", namespaces=NS)
    assert len(fallback) == 1, "an unsupported viewer still gets a fade"
    assert report["fallbackElement"] == "p:fade"


def test_a_standard_effect_with_a_custom_duration_falls_back_to_itself():
    node, report = _node("push", parameters={"dir": "u"}, duration=2400)
    assert report["requires"] == "p14", "p14:dur is an extension attribute"
    assert report["requiresTokens"] == ["p14"]
    choice = node.xpath("./mc:Choice/p:transition", namespaces=NS)[0]
    assert choice.get("{%s}dur" % NS["p14"]) == "2400"
    fallback = node.xpath("./mc:Fallback/p:transition", namespaces=NS)[0]
    assert fallback.get("{%s}dur" % NS["p14"]) is None
    assert fallback.xpath("./p:push/@dir", namespaces=NS) == ["u"]


@pytest.mark.parametrize(
    "effect,expected",
    [
        ("ripple", ["p14"]),
        ("prestige", ["p14", "p15"]),
        ("morph", ["p14", "p159"]),
        ("push", ["p14"]),
    ],
)
def test_a_choice_requires_every_namespace_it_uses(effect, expected):
    """``@Requires`` is a prefix list: a Choice that carries both an extension
    element and the ``p14:dur`` attribute declares both namespaces, in the
    catalog's own namespace order."""
    node, report = _node(effect, duration=2400)
    assert report["requiresTokens"] == expected
    choice = node.xpath("./mc:Choice", namespaces=NS)[0]
    assert choice.get("Requires") == " ".join(expected)
    assert choice.xpath("./p:transition/@p14:dur", namespaces=NS) == ["2400"]


def test_an_unsupported_namespace_is_rejected_token_by_token(index):
    """The supported-set check is per token, so an extra prefix cannot ride
    along inside a joined string."""
    import copy

    patched = copy.copy(index)
    patched.items = dict(index.items)
    patched.candidates = dict(index.candidates)
    patched.alternate_content = {
        **index.alternate_content,
        "supported": [row for row in index.alternate_content["supported"] if row["requires"] != "p14"],
    }
    with pytest.raises(TransitionWriteError) as error:
        build_transition(
            _transition("morph", parameters={"variant": "byObject"}, duration=2400), index=patched
        )
    message = str(error.value)
    assert "does not contain ['p14']" in message, "the unsupported token is named on its own"
    assert "'p159'" in message, "the supported token is still part of the request"


def test_the_captured_legacy_speed_bucket_is_written_in_both_branches():
    node, _report = _node("fade", duration=700)
    for branch in node.xpath(".//p:transition", namespaces=NS):
        assert branch.get("spd") == "med"


def test_the_default_duration_keeps_the_captured_form():
    node, report = _node("push", parameters={"dir": "u"}, duration=1000)
    assert report["durationMs"] is None, "slow == 1000 ms, so the capture needs no p14:dur"
    assert etree.QName(node).localname == "transition"


def test_an_omitted_duration_writes_only_the_bucket():
    node, report = _node("wipe")
    assert report["durationMs"] is None
    assert node.get("spd") == "slow"


@pytest.mark.parametrize("duration", [0, -5, "fast", True])
def test_an_invalid_duration_is_rejected(duration):
    with pytest.raises(TransitionWriteError, match="positive number"):
        build_transition(_transition("fade", duration=duration))


# --- directions and variants ----------------------------------------------


@pytest.mark.parametrize(
    "effect,parameters,xpath,expected",
    [
        ("push", {"dir": "l"}, "./p:push/@dir", "l"),
        ("push", {"dir": "r"}, "./p:push/@dir", "r"),
        ("push", {"dir": "d"}, "./p:push/@dir", "d"),
        ("wipe", {"dir": "u"}, "./p:wipe/@dir", "u"),
        ("cover", {"dir": "rd"}, "./p:cover/@dir", "rd"),
        ("uncover", {"dir": "lu"}, "./p:pull/@dir", "lu"),
        ("blinds", {"dir": "horz"}, "./p:blinds/@dir", "horz"),
        ("checker", {"dir": "vert"}, "./p:checker/@dir", "vert"),
        ("comb", {"dir": "vert"}, "./p:comb/@dir", "vert"),
        ("randomBar", {"dir": "horz"}, "./p:randomBar/@dir", "horz"),
        ("clock", {"spokes": "8"}, "./p:wheel/@spokes", "8"),
        ("strips", {"dir": "ru"}, "./p:strips/@dir", "ru"),
        ("cut", {"thruBlk": "1"}, "./p:cut/@thruBlk", "1"),
    ],
)
def test_catalogued_directions_and_variants_are_written(effect, parameters, xpath, expected):
    node, _report = _node(effect, parameters=parameters)
    transitions = node.xpath(".//p:transition", namespaces=NS) or [node]
    values = transitions[0].xpath(xpath, namespaces=NS)
    assert values == [expected]


def test_split_carries_both_orientation_and_direction():
    node, _report = _node("split", parameters={"orient": "horz", "dir": "out"})
    split = (node.xpath(".//p:transition", namespaces=NS) or [node])[0].xpath("./p:split", namespaces=NS)[0]
    assert (split.get("orient"), split.get("dir")) == ("horz", "out")


def test_page_curl_single_and_double_are_distinguishable_values(index, catalog):
    """Both Page Curl variants are now written, and they stay distinguishable.

    The single-page variant used to be refused as capture-required; the
    scripting-oracle capture asked PowerPoint for ``entry effect page curl
    single left`` and it wrote ``prst="pageCurlSingle"``, so the entry is
    generated from that measurement instead of raising.
    """
    node, report = _node("pageCurl")
    assert node.xpath(".//p15:prstTrans/@prst", namespaces=NS) == ["pageCurlDouble"]
    single, _report = build_transition(
        _transition("pageCurl", parameters={"prst": "pageCurlSingle"}), index=index
    )
    assert single.xpath(".//p15:prstTrans/@prst", namespaces=NS) == ["pageCurlSingle"]
    entry = next(
        row for row in catalog["candidates"]
        if row["key"] == "EPPEntryEffect.entry effect page curl single left"
    )
    assert entry["ooxml"]["attributes"] == {"prst": "pageCurlSingle"}
    assert entry["verification"] == "scriptingOracleCapture"


def test_a_captured_extension_variant_is_written_and_an_uncaptured_one_is_still_refused(index, catalog):
    """Vortex Left was the catalog's example of a refused extension variant.

    The capture closed it: PowerPoint wrote a bare ``<p14:vortex/>`` for the
    enumerator, with ``dir`` left at its default, so the variant is written
    rather than approximated. The refusal path itself is unchanged, and the
    transition surface still has entries on it - the sound controls, whose
    relationship form no capture contains.
    """
    node, _report = build_transition(_transition("vortex", parameters={"dir": "l"}), index=index)
    assert node.xpath(".//p14:vortex/@dir", namespaces=NS) == ["l"]
    entry = next(
        row for row in catalog["candidates"] if row["key"] == "EPPEntryEffect.entry effect vortex left"
    )
    assert entry["verification"] == "scriptingOracleCapture"
    assert entry["capture"]["attributes"] == {}, "PowerPoint wrote no attributes for this value"

    with pytest.raises(CapabilityGapError) as error:
        build_transition(
            _transition("fade", duration=700, sound={"src": "audio/chime.wav", "mediaType": "audio/wav"}),
            index=index,
        )
    assert error.value.key == "transition.sound.effect"
    assert "refuses to approximate" in str(error.value)


def test_an_unsupported_parameter_lists_the_supported_sets():
    with pytest.raises(TransitionWriteError) as error:
        build_transition(_transition("push", parameters={"dir": "diagonal"}))
    assert "does not support parameters" in str(error.value)
    assert "dir" in str(error.value)


def test_an_unknown_effect_lists_the_catalogued_effects():
    with pytest.raises(TransitionWriteError) as error:
        build_transition(_transition("teleport"))
    assert "unknown transition effect 'teleport'" in str(error.value)
    assert "morph" in str(error.value)


def test_a_missing_effect_is_rejected():
    with pytest.raises(TransitionWriteError, match="transition.effect is required"):
        build_transition({"parameters": {}})


def test_the_gallery_tile_wins_over_a_same_named_standard_element(index):
    """The Zoom tile is p14:warp; ECMA-376's unused p:zoom must not shadow it."""
    entry, attrs = resolve_transition(index, _transition("zoom", parameters={"dir": "in"}))
    assert entry.ooxml["element"] == "p14:warp"
    assert attrs == {"dir": "in"}


def test_standard_only_elements_without_a_tile_still_generate(catalog, index):
    standard_only = [
        entry for entry in catalog["guiItems"] if entry["key"].startswith("transition.standardElement.")
    ]
    assert len(standard_only) == 6
    for entry in standard_only:
        node, report = build_transition(entry["semanticJson"]["transition"], index=index)
        if entry["key"].endswith(".zoom"):
            # Documented name collision: the GUI "Zoom" tile is p14:warp, so
            # the captured tile owns the effect name.
            assert report["strategy"] == "p14"
            continue
        assert report["strategy"] == "standard"
        assert etree.tostring(node).decode().count("<p:") >= 1


# --- advance conditions and sound -----------------------------------------


def test_advance_on_click_is_the_default_and_stays_implicit():
    node, _report = _node("fade", duration=700, advance={"onClick": True, "afterMs": None})
    assert node.xpath(".//p:transition/@advClick", namespaces=NS) == []


def test_advance_after_time_and_click_off_are_written():
    node, _report = _node("fade", duration=700, advance={"onClick": False, "afterMs": 3000})
    for branch in node.xpath(".//p:transition", namespaces=NS):
        assert branch.get("advClick") == "0"
        assert branch.get("advTm") == "3000"


def test_a_negative_advance_time_is_rejected():
    with pytest.raises(TransitionWriteError, match="non-negative"):
        build_transition(_transition("fade", duration=700, advance={"onClick": True, "afterMs": -1}))


def test_transition_sound_is_refused_until_its_relationship_form_is_captured(index):
    with pytest.raises(CapabilityGapError) as error:
        build_transition(
            _transition("fade", duration=700, sound={"src": "audio/chime.wav", "mediaType": "audio/wav"}),
            index=index,
        )
    assert error.value.key == "transition.sound.effect"


# --- package placement and switches ---------------------------------------


def test_the_transition_is_inserted_before_timing_and_ext_lst():
    slide_def = _slide(
        _transition("fade", duration=700),
        animations={
            "mainSequence": [
                {
                    "id": "fx",
                    "target": {"element": "hero"},
                    "preset": {"category": "entrance", "effect": "fade", "variant": None},
                    "start": {"type": "onPageClick", "delayMs": 0},
                    "timing": {"durationMs": 500},
                    "afterEffect": {"type": "none"},
                    "sound": None,
                }
            ],
            "interactiveSequences": [],
        },
    )
    builder = PPTXBuilder(
        TEMPLATE,
        fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"},
        default_text_color="#FFFFFF",
        animations_enabled=True,
        transitions_enabled=True,
    )
    slide = builder.add_slide(slide_def)
    order = [etree.QName(child).localname for child in etree.fromstring(etree.tostring(slide._element))]
    assert order == ["cSld", "clrMapOvr", "AlternateContent", "timing"]


def test_a_direct_transition_is_also_placed_before_timing():
    _, root, _slide_obj = _build(_slide(_transition("push", parameters={"dir": "u"})))
    order = [etree.QName(child).localname for child in root]
    assert order.index("transition") == len(order) - 1
    assert "timing" not in order


def test_transitions_disabled_emits_nothing():
    _, root, _slide_obj = _build(_slide(_transition("morph", parameters={"variant": "byObject"})), transitions=False)
    assert root.xpath(".//*[local-name()='transition']") == []


def test_writing_a_transition_replaces_any_existing_one():
    builder, _root, slide = _build(_slide(_transition("fade", duration=700)))
    report = write_slide_transition(
        slide._element, _transition("push", parameters={"dir": "u"}), slide_slug="entering"
    )
    assert report["removed"] == 1
    root = etree.fromstring(etree.tostring(slide._element))
    assert len(root.xpath(".//*[local-name()='transition']")) == 1
    assert root.xpath(".//p:push/@dir", namespaces=NS) == ["u"]


def test_removing_a_transition_leaves_one_slide_clean():
    builder, _root, slide = _build(_slide(_transition("fade", duration=700)))
    assert remove_transition(slide._element) == 1
    assert remove_transition(slide._element) == 0


def _wrapper(*children: str) -> etree._Element:
    return etree.fromstring(
        '<mc:AlternateContent xmlns:mc="%s" xmlns:p="%s" xmlns:p14="%s">'
        '<mc:Choice Requires="p14">%s</mc:Choice>'
        "</mc:AlternateContent>" % (NS["mc"], NS["p"], NS["p14"], "".join(children))
    )


def test_only_a_transition_only_wrapper_is_removed():
    """A wrapper is replaceable only when every branch child is a transition."""
    _builder, _root, slide = _build(_slide())
    slide._element.append(_wrapper("<p:transition><p:fade/></p:transition>"))
    assert remove_transition(slide._element) == 1
    assert slide._element.xpath("./*[local-name()='AlternateContent']") == []


def test_a_mixed_wrapper_is_refused_instead_of_silently_deleted():
    """Removing an ``mc:AlternateContent`` because a transition sits somewhere
    inside it would also delete the timing sharing the same wrapper, so the
    writer raises rather than losing the other representation."""
    _builder, _root, slide = _build(_slide())
    slide._element.append(
        _wrapper("<p:transition><p:fade/></p:transition>", "<p:timing><p:tnLst/></p:timing>")
    )
    with pytest.raises(TransitionWriteError) as error:
        remove_transition(slide._element)
    assert "will not delete the other content" in str(error.value)
    assert "timing" in str(error.value)
    # Nothing was removed.
    assert len(slide._element.xpath(".//*[local-name()='timing']")) == 1
    assert len(slide._element.xpath(".//*[local-name()='transition']")) == 1


def test_sibling_single_purpose_wrappers_are_removed_independently():
    _builder, _root, slide = _build(_slide())
    slide._element.append(_wrapper("<p:transition><p:fade/></p:transition>"))
    slide._element.append(_wrapper("<p:timing><p:tnLst/></p:timing>"))
    assert remove_transition(slide._element) == 1
    assert len(slide._element.xpath(".//*[local-name()='timing']")) == 1


def test_a_transition_sound_stays_refused_even_if_its_catalog_gap_closes(index):
    """The refusal is unconditional: a transition sound needs an audio part and
    a package relationship the writer does not create, so closing the catalog
    gap alone must not turn the setting into a silently dropped one."""
    entry = index.items["transition.sound.effect"]
    assert entry.gap, "the catalog still records the capture gap"
    with pytest.raises(CapabilityGapError) as error:
        build_transition(
            _transition("fade", duration=700, sound={"src": "a/x.wav", "mediaType": "audio/wav", "loop": True}),
            index=index,
        )
    assert error.value.key == "transition.sound.loopUntilNext"
    from sdpm.engine.timing.writer import refuse_unimplemented

    with pytest.raises(CapabilityGapError) as unimplemented:
        refuse_unimplemented(index, "transition.duration", "a sound", "no relationship writer exists")
    assert "not implemented by the writer" in str(unimplemented.value)


def test_only_the_supported_namespace_set_is_emitted(index):
    supported = {row["requires"] for row in index.alternate_content["supported"]}
    assert supported == {"p14", "p15", "p159"}
    for slug in index.transition_slugs():
        for entry in index.transition_variants(slug):
            if entry.writable and entry.ooxml.get("requires"):
                assert entry.ooxml["requires"] in supported


# --- catalog coverage accounting ------------------------------------------


def test_catalog_transition_coverage_is_counted(coverage, index):
    """The counts come from :func:`catalog_coverage`, the one definition of
    generated-versus-refused shared with the animation writer tests, filtered
    to the entries that choose a transition element."""
    transitions = [
        record
        for record in coverage
        if record.kind == "transition" and record.strategy in TRANSITION_STRATEGIES
    ]
    generated = [record for record in transitions if record.generated]
    refused = [record for record in transitions if record.refused]
    assert [record.key for record in transitions if record.outcome == "error"] == []
    assert len(generated) == TRANSITION_COVERAGE["generated"]
    assert len(refused) == TRANSITION_COVERAGE["refused"]
    by_strategy: dict[str, int] = {}
    for record in refused:
        assert record.has_gap, f"{record.key} was refused without a recorded gap"
        assert index.entry(record.key).gap
        by_strategy[record.strategy] = by_strategy.get(record.strategy, 0) + 1
    assert by_strategy == TRANSITION_COVERAGE["refusedByStrategy"]
    # Wheel Reverse used to be the single refused standard element, and now no
    # transition element is refused. The catalog had guessed a `reverse`
    # attribute on `p:wheel`; the scripting-oracle capture shows PowerPoint
    # writing `p14:wheelReverse`, where "reverse" is the element *name*. That
    # is not a capture gap and never was — it is that selecting and writing
    # were held as one attribute set. They are two now, so the measured form is
    # reachable from a parameter set.
    assert [record.key for record in refused if record.strategy == "standard"] == []
    wheel_reverse = index.entry("EPPEntryEffect.entry effect wheel reverse 1 spoke")
    assert wheel_reverse.writable
    assert wheel_reverse.ooxml["element"] == "p14:wheelReverse"
    assert wheel_reverse.attributes() == {"spokes": "1"}
    assert wheel_reverse.selector_attributes() == {"spokes": "1", "reverse": "1"}
    assert wheel_reverse.selects_by_element_name


def test_transition_controls_are_counted_in_the_same_pass(coverage):
    """The duration, advance, sound and Morph-matching entries also carry a
    transition fragment. They are counted as transitions by the shared pass and
    separated by strategy, not dropped by a filter that only one test knows
    about."""
    controls = [
        record
        for record in coverage
        if record.kind == "transition" and record.strategy not in TRANSITION_STRATEGIES
    ]
    assert {record.strategy for record in controls} == TRANSITION_COVERAGE["controlStrategies"]
    assert len(controls) == TRANSITION_COVERAGE["controls"]
    refused = {record.key for record in controls if record.refused}
    assert refused == TRANSITION_COVERAGE["refusedControls"]
    assert [record.key for record in controls if record.outcome == "error"] == []
