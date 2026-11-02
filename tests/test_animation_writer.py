# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""OOXML generation tests for the object-animation timing writer.

Everything the writer emits has to come from the generated capability catalog.
These tests pin the structure (sequences, click/start groups, sequential start
delays, targets, build lists, behavior primitives), the identity contract
(unique ``p:cTn`` ids, stable effect IDs, resolved ``spid``s) and the honesty
contract: a catalog entry whose OOXML form or behavior payload is not
established must raise instead of being approximated, the writer never emits a
schema-invalid node, and the number of catalog entries it can and cannot
generate is counted here.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation
from pptx.util import Emu

from sdpm.engine.builder import PPTXBuilder
from sdpm.engine.timing import (
    SDPM_EFFECT_EXT_URI,
    TRANSITION_STRATEGIES,
    BehaviorPayloadGapError,
    CapabilityEntry,
    CapabilityGapError,
    CapabilityIndex,
    IdentityError,
    ShapeIdentityRegistry,
    TimingWriteError,
    TimingWriter,
    catalog_coverage,
    coverage_summary,
    effect_fingerprint,
    effect_identity,
    load_capability_index,
    preset_payload_gaps,
    read_identity_extension,
    refuse_unimplemented,
    write_slide_timing,
)
from sdpm.engine.timing.transition import build_transition
from sdpm.engine.timing.writer import capability_cache_info, default_catalog_path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "sdpm" / "templates" / "blank-dark.pptx"
CATALOG_PATH = REPO_ROOT / "sdpm" / "references" / "catalogs" / "powerpoint-animation-catalog.json"
NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "sdpm": "https://sdpm.dev/2026/identity",
}

#: Counted baseline of what the writers can generate from the checked-in
#: catalog, taken from :func:`catalog_coverage` — the one definition of
#: generated-versus-refused that this file, ``test_transition_writer.py`` and
#: the Task 8 acceptance harness all read. ``generated`` entries have an
#: established OOXML form; ``refused`` entries are capture-required and must
#: raise.
#:
#: The scripting-oracle capture under
#: ``tests/fixtures/animations/oracle-16.113.1`` moved 59 transition candidates
#: from refused to generated: ``flashbulb`` used to be written off a same-shaped
#: tile while its own enum→element mapping stayed open, and PowerPoint has now
#: written ``p14:flash`` for it directly.
#:
#: The GUI capture under
#: ``tests/fixtures/animations/gui-only/batch-2026-11-01-complete`` then moved
#: 113 more entries from refused to generated, and that is the animation side
#: opening up. It measured all 76 GUI-addressable animation values **with their
#: behaviour payloads**, which is what the 71 payload-refused gallery tiles were
#: missing: the native fixtures recorded *which* children a tile writes, never
#: what they say. **All 95 entrance, exit and emphasis tiles are now generated
#: and none is refused**, and ``payloadRefusals`` has no ``guiItems`` left in it.
#:
#: ``generatedDespiteGap`` is no longer empty, and it is not a regression. Each
#: of its 39 entries is an ``MsoAnimEffect`` candidate whose own enumerator →
#: OOXML mapping the dictionary could not establish (``add effect`` is not
#: implemented in 16.113.1), which resolves by ``presetClass`` + ``presetID`` to
#: a gallery tile the GUI capture measured. The test below checks that
#: resolution per entry rather than taking the list on trust.
CATALOG_COVERAGE = {
    "total": 667,
    "generated": {
        "total": 458,
        "guiItems": 218,
        "candidates": 240,
        "animation": 241,
        "transition": 217,
    },
    "refused": {
        "total": 209,
        "guiItems": 62,
        "candidates": 147,
        "animation": 206,
        "transition": 3,
    },
    "generatedDespiteGap": [
        f"MsoAnimEffect.animation type {name}"
        for name in (
            "bold flash", "bold reveal", "boomerang", "bounce", "brush on color",
            "brush on underline", "center revolve", "change fill color", "change font color",
            "change line color", "complementary color", "complementary color 2",
            "constrasting color", "credits", "darken", "desaturate", "expand", "flash bulb",
            "flicker", "flip", "float", "fly", "grow and turn", "grow shrink", "grow with color",
            "lighten", "peek", "pinwheel", "rise up", "spin", "spinner", "spiral", "stretch",
            "swivel", "teeter", "transparency", "wave", "whip", "zoom",
        )
    ],
    #: The two numbers Task 8 has to drive to zero, as slices of the same pass:
    #: refusals whose OOXML *mapping* was never captured, and refusals whose
    #: behavior *payload* was never captured. The payload slice is down from 121
    #: to 11 and holds no gallery tile at all — only enum candidates whose own
    #: mapping is open, so they resolve to no measured tile.
    "captureRequiredRefusals": 198,
    "payloadRefusals": {"total": 11, "guiItems": 0, "candidates": 11},
}

#: The gallery capture recorded which behavior children PowerPoint wrote, not
#: the values inside them, so only 24 of the 95 entrance/emphasis/exit tiles
#: can be reproduced. The other 71 record the unresolved payload in the
#: catalog and must be refused, never approximated.
#: Was 24 reproducible and 71 refused, with the refusals naming 92 unresolved
#: behaviour children. The GUI capture measured every one of those payloads, so
#: the whole gallery is reproducible and the dict is empty. It is kept rather
#: than deleted because a tile sliding back into "refused" is exactly the
#: regression worth noticing, and an empty expectation states that plainly.
GALLERY_PAYLOADS = {
    "tiles": 95,
    "reproducible": 95,
    "refused": 0,
    "unresolvedElements": {},
}

#: A fully captured entrance tile: presetID 10, ``p:animEffect`` filter "fade"
#: and the normative visibility ``p:set``. Tests that are about something else
#: use it so the carrier preset never becomes the reason a case fails.
WRITABLE_PRESET = {"category": "entrance", "effect": "fade"}


def _effect(effect_id="fx", element="hero", **patch):
    effect = {
        "id": effect_id,
        "target": {"element": element},
        "preset": {"category": "entrance", "effect": "fade"},
        "start": {"type": "onPageClick", "delayMs": 0},
        "timing": {"durationMs": 500},
        "afterEffect": {"type": "none"},
        "sound": None,
    }
    effect.update(patch)
    return effect


def _slide(elements=None, **patch):
    slide = {
        "id": "animated",
        "layout": "Blank",
        "elements": elements
        if elements is not None
        else [
            {"id": "hero", "type": "textbox", "text": "Hero", "x": 10, "y": 10, "width": 300, "height": 60},
            {"id": "aside", "type": "shape", "shape": "rect", "x": 10, "y": 120, "width": 200, "height": 80},
        ],
    }
    slide.update(patch)
    return slide


def _build(slide_def, *, animations=True, transitions=False):
    builder = PPTXBuilder(
        TEMPLATE,
        fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"},
        default_text_color="#FFFFFF",
        base_dir=REPO_ROOT,
        animations_enabled=animations,
        transitions_enabled=transitions,
    )
    slide = builder.add_slide(slide_def)
    return builder, slide


def _xml(slide):
    """Return the slide as a plain lxml tree (python-pptx pins its own nsmap)."""
    return etree.fromstring(etree.tostring(slide._element))


def _timing(slide):
    found = _xml(slide).findall("{%s}timing" % NS["p"])
    assert len(found) == 1, "exactly one timing representation per slide"
    return found[0]


@pytest.fixture(scope="module")
def index():
    return load_capability_index()


@pytest.fixture(scope="module")
def catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def coverage(index):
    """One shared generated/refused pass over every accepted catalog entry."""
    return catalog_coverage(index)


@pytest.fixture()
def patched_index(catalog):
    """Return a builder for an index whose catalog JSON has been edited.

    Several contracts are only provable against a catalog that differs from the
    checked-in one — a closed gap, a lost build token — so the fixture hands
    out a real :class:`CapabilityIndex` built from a mutated copy instead of
    reaching into index internals.
    """

    def build(mutate) -> CapabilityIndex:
        patched = copy.deepcopy(catalog)
        mutate(patched)
        return CapabilityIndex(patched)

    return build


def _entries(catalog, key):
    """Yield every catalog entry carrying one key, in both groups."""
    for group in ("guiItems", "candidates"):
        for entry in catalog[group]:
            if entry["key"] == key:
                yield entry


def _close_gap(key):
    """Return a mutation that removes one entry's recorded capture gap."""

    def mutate(catalog):
        found = False
        for entry in _entries(catalog, key):
            entry["ooxml"].pop("gap", None)
            entry["ooxml"].pop("requiresCapture", None)
            entry["capabilityLevel"] = "nativeTemplate"
            found = True
        assert found, f"no catalog entry {key!r} to close"

    return mutate


@pytest.fixture()
def registry():
    """A registry holding the catalog's ``catalogTarget`` element."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    shape = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(914400), Emu(914400))
    registry = ShapeIdentityRegistry("catalog")
    registry.register("catalogTarget", [shape._element], source_path="elements[0]")
    return registry


# --- sequences, order and triggers ----------------------------------------


def test_main_sequence_nests_click_and_start_groups_in_order():
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect("first", "hero"),
                _effect("second", "aside", start={"type": "withPrevious", "delayMs": 0}),
                _effect("third", "hero", start={"type": "afterPrevious", "delayMs": 250}),
                _effect("fourth", "aside", start={"type": "onPageClick", "delayMs": 0}),
            ],
            "interactiveSequences": [],
        }
    )
    _, slide = _build(slide_def)
    timing = _timing(slide)
    main = timing.xpath(".//p:seq[p:cTn/@nodeType='mainSeq']", namespaces=NS)
    assert len(main) == 1
    click_groups = main[0].xpath("./p:cTn/p:childTnLst/p:par", namespaces=NS)
    assert len(click_groups) == 2, "onPageClick opens a new click group"
    assert [
        group.xpath("./p:cTn/p:stCondLst/p:cond/@delay", namespaces=NS)[0] for group in click_groups
    ] == ["indefinite", "indefinite"]

    first_group_starts = click_groups[0].xpath("./p:cTn/p:childTnLst/p:par", namespaces=NS)
    assert len(first_group_starts) == 2, "afterPrevious opens a new start group, withPrevious joins"
    assert len(first_group_starts[0].xpath("./p:cTn/p:childTnLst/p:par", namespaces=NS)) == 2

    node_types = timing.xpath(".//p:cTn[@presetID]/@nodeType", namespaces=NS)
    assert node_types == ["clickEffect", "withEffect", "afterEffect", "clickEffect"]
    delays = [
        node.xpath("./p:stCondLst/p:cond/@delay", namespaces=NS)[0]
        for node in timing.xpath(".//p:cTn[@presetID]", namespaces=NS)
    ]
    assert delays == ["0", "0", "250", "0"]


def _start_group_delays(timing):
    """Return the start-group delays of every click group, in order."""
    main = timing.xpath(".//p:seq[p:cTn/@nodeType='mainSeq']", namespaces=NS)[0]
    return [
        [
            group.xpath("./p:cTn/p:stCondLst/p:cond/@delay", namespaces=NS)[0]
            for group in click.xpath("./p:cTn/p:childTnLst/p:par", namespaces=NS)
        ]
        for click in main.xpath("./p:cTn/p:childTnLst/p:par", namespaces=NS)
    ]


def test_after_previous_starts_when_the_previous_effects_have_finished():
    """Sibling start groups share a parent begin time, so After Previous is
    only sequential when its group carries the cumulative offset: the longest
    ``delay + duration`` of everything that already ran in the click group."""
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect("first", "hero", timing={"durationMs": 600}),
                _effect(
                    "second",
                    "aside",
                    start={"type": "withPrevious", "delayMs": 100},
                    timing={"durationMs": 900},
                ),
                _effect(
                    "third",
                    "hero",
                    start={"type": "afterPrevious", "delayMs": 250},
                    timing={"durationMs": 400},
                ),
                _effect(
                    "fourth",
                    "aside",
                    start={"type": "afterPrevious", "delayMs": 0},
                    timing={"durationMs": 300},
                ),
            ],
            "interactiveSequences": [],
        }
    )
    _, slide = _build(slide_def)
    timing = _timing(slide)
    # group 1 ends at max(0+600, 100+900) = 1000; group 2 ends at 1000+250+400.
    assert _start_group_delays(timing) == [["0", "1000", "1650"]]
    assert timing.xpath(".//p:cTn[@presetID]/@nodeType", namespaces=NS) == [
        "clickEffect",
        "withEffect",
        "afterEffect",
        "afterEffect",
    ]


def test_with_previous_joins_the_running_start_group_instead_of_delaying_it():
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect("first", "hero", timing={"durationMs": 500}),
                _effect(
                    "second",
                    "aside",
                    start={"type": "withPrevious", "delayMs": 0},
                    timing={"durationMs": 500},
                ),
            ],
            "interactiveSequences": [],
        }
    )
    _, slide = _build(slide_def)
    timing = _timing(slide)
    assert _start_group_delays(timing) == [["0"]], "one start group holds both effects"
    start_group = timing.xpath(
        ".//p:seq/p:cTn/p:childTnLst/p:par/p:cTn/p:childTnLst/p:par", namespaces=NS
    )
    assert len(start_group) == 1
    assert len(start_group[0].xpath(".//p:cTn[@presetID]", namespaces=NS)) == 2


def test_a_new_click_group_restarts_the_cumulative_offset():
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect("first", "hero", timing={"durationMs": 800}),
                _effect("second", "aside", start={"type": "onPageClick", "delayMs": 0}, timing={"durationMs": 300}),
                _effect("third", "hero", start={"type": "afterPrevious", "delayMs": 0}, timing={"durationMs": 200}),
            ],
            "interactiveSequences": [],
        }
    )
    _, slide = _build(slide_def)
    assert _start_group_delays(_timing(slide)) == [["0"], ["0", "300"]]


def test_an_after_previous_first_effect_still_opens_a_click_group():
    """A sequence has to wait for its trigger, so nothing can precede it."""
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect("only", "hero", start={"type": "afterPrevious", "delayMs": 0}, timing={"durationMs": 500})
            ],
            "interactiveSequences": [],
        }
    )
    _, slide = _build(slide_def)
    timing = _timing(slide)
    assert _start_group_delays(timing) == [["0"]]
    assert timing.xpath(".//p:cTn[@presetID]/@nodeType", namespaces=NS) == ["afterEffect"]


def test_interactive_sequence_triggers_on_its_shape_and_follows_the_main_sequence():
    slide_def = _slide(
        animations={
            "mainSequence": [_effect("first", "hero")],
            "interactiveSequences": [
                {
                    "id": "details",
                    "trigger": {"type": "onShapeClick", "target": "aside", "delayMs": 0},
                    "effects": [_effect("on-click", "hero")],
                }
            ],
        }
    )
    builder, slide = _build(slide_def)
    timing = _timing(slide)
    sequences = timing.xpath(".//p:childTnLst/p:seq", namespaces=NS)
    assert [seq.xpath("./p:cTn/@nodeType", namespaces=NS)[0] for seq in sequences] == [
        "mainSeq",
        "interactiveSeq",
    ]
    main, interactive = sequences
    aside_spid = builder.identity_registries["animated"].resolve("aside")
    cond = interactive.xpath("./p:cTn/p:stCondLst/p:cond", namespaces=NS)[0]
    assert cond.get("evt") == "onClick"
    assert cond.xpath("./p:tgtEl/p:spTgt/@spid", namespaces=NS) == [str(aside_spid)]
    assert interactive.xpath("./p:cTn/p:endSync/p:rtn/@val", namespaces=NS) == ["all"]

    # The main sequence is driven by the slide's own previous/next clicks.
    assert main.xpath("./p:prevCondLst/p:cond/@evt", namespaces=NS) == ["onPrev"]
    assert main.xpath("./p:nextCondLst/p:cond/@evt", namespaces=NS) == ["onNext"]
    assert main.xpath("./p:prevCondLst/p:cond/p:tgtEl/p:sldTgt", namespaces=NS)
    assert main.xpath("./p:nextCondLst/p:cond/p:tgtEl/p:sldTgt", namespaces=NS)


def test_an_interactive_sequence_cancels_the_bubble_and_rearms_on_its_own_shape():
    """A trigger sequence is not part of the click-driven timeline: the click
    must not bubble up to the main sequence, and the sequence re-arms on the
    same shape rather than on a slide-level previous/next event."""
    slide_def = _slide(
        animations={
            "mainSequence": [_effect("first", "hero")],
            "interactiveSequences": [
                {
                    "id": "details",
                    "trigger": {"type": "onShapeClick", "target": "aside", "delayMs": 0},
                    "effects": [_effect("on-click", "hero")],
                }
            ],
        }
    )
    builder, slide = _build(slide_def)
    aside_spid = str(builder.identity_registries["animated"].resolve("aside"))
    interactive = _timing(slide).xpath(".//p:seq[p:cTn/@nodeType='interactiveSeq']", namespaces=NS)[0]
    assert interactive.xpath("./p:cTn/@evtFilter", namespaces=NS) == ["cancelBubble"]
    assert interactive.xpath("./p:prevCondLst", namespaces=NS) == []
    next_cond = interactive.xpath("./p:nextCondLst/p:cond", namespaces=NS)
    assert len(next_cond) == 1
    assert (next_cond[0].get("evt"), next_cond[0].get("delay")) == ("onClick", "0")
    assert next_cond[0].xpath("./p:tgtEl/p:spTgt/@spid", namespaces=NS) == [aside_spid]
    assert interactive.xpath(".//p:sldTgt", namespaces=NS) == [], "no slide target on a trigger sequence"


def test_the_interactive_trigger_delay_reaches_both_conditions():
    slide_def = _slide(
        animations={
            "mainSequence": [],
            "interactiveSequences": [
                {
                    "id": "details",
                    "trigger": {"type": "onShapeClick", "target": "aside", "delayMs": 400},
                    "effects": [_effect("on-click", "hero")],
                }
            ],
        }
    )
    _, slide = _build(slide_def)
    interactive = _timing(slide).xpath(".//p:seq[p:cTn/@nodeType='interactiveSeq']", namespaces=NS)[0]
    assert interactive.xpath("./p:cTn/p:stCondLst/p:cond/@delay", namespaces=NS) == ["400"]
    assert interactive.xpath("./p:nextCondLst/p:cond/@delay", namespaces=NS) == ["400"]


@pytest.mark.parametrize(
    "kind,node_type",
    [("onPageClick", "clickEffect"), ("withPrevious", "withEffect"), ("afterPrevious", "afterEffect")],
)
def test_every_catalogued_main_sequence_trigger_is_written(kind, node_type):
    slide_def = _slide(
        animations={
            "mainSequence": [_effect("fx", "hero", start={"type": kind, "delayMs": 100})],
            "interactiveSequences": [],
        }
    )
    _, slide = _build(slide_def)
    assert _timing(slide).xpath(".//p:cTn[@presetID]/@nodeType", namespaces=NS) == [node_type]


def test_no_trigger_is_refused_because_powerpoint_never_recorded_its_form():
    slide_def = _slide(
        animations={
            "mainSequence": [_effect("fx", "hero", start={"type": "none", "delayMs": 0})],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(CapabilityGapError) as error:
        _build(slide_def)
    assert error.value.key == "animation.start.none"
    assert "absence of a start condition" in str(error.value)


def test_an_unknown_start_type_lists_the_supported_triggers():
    slide_def = _slide(
        animations={
            "mainSequence": [_effect("fx", "hero", start={"type": "onHover", "delayMs": 0})],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(TimingWriteError) as error:
        _build(slide_def)
    assert "unknown start type 'onHover'" in str(error.value)
    assert "afterPrevious" in str(error.value)


def test_shape_click_in_the_main_sequence_is_rejected_with_the_fix():
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect("fx", "hero", start={"type": "onShapeClick", "delayMs": 0, "target": "aside"})
            ],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(TimingWriteError, match="interactiveSequences"):
        _build(slide_def)


def test_interactive_sequence_requires_a_shape_click_trigger():
    slide_def = _slide(
        animations={
            "mainSequence": [],
            "interactiveSequences": [
                {
                    "id": "bad",
                    "trigger": {"type": "onPageClick", "delayMs": 0},
                    "effects": [_effect("fx", "hero")],
                }
            ],
        }
    )
    with pytest.raises(TimingWriteError, match="onShapeClick"):
        _build(slide_def)


def _trigger_slide(effect_start, trigger_target="aside"):
    return _slide(
        animations={
            "mainSequence": [],
            "interactiveSequences": [
                {
                    "id": "details",
                    "trigger": {"type": "onShapeClick", "target": trigger_target, "delayMs": 0},
                    "effects": [_effect("on-click", "hero", start=effect_start)],
                }
            ],
        }
    )


def test_a_per_effect_shape_click_target_must_be_the_sequence_trigger():
    """One ``p:seq`` carries one shape-click condition, so an effect inside it
    has nowhere to put a second trigger shape. Writing the sequence anyway
    would silently play the effect on the wrong click."""
    slide_def = _trigger_slide({"type": "onShapeClick", "delayMs": 0, "target": "hero"})
    with pytest.raises(TimingWriteError) as error:
        _build(slide_def)
    message = str(error.value)
    assert "interactive:details[0].start.target 'hero'" in message
    assert "trigger target 'aside'" in message
    assert "own interactive sequence" in message


def test_a_per_effect_target_equal_to_the_sequence_trigger_is_written():
    builder, slide = _build(_trigger_slide({"type": "onShapeClick", "delayMs": 0, "target": "aside"}))
    aside = str(builder.identity_registries["animated"].resolve("aside"))
    timing = _timing(slide)
    interactive = timing.xpath(".//p:seq[p:cTn/@nodeType='interactiveSeq']", namespaces=NS)[0]
    assert interactive.xpath("./p:cTn/p:stCondLst/p:cond/p:tgtEl/p:spTgt/@spid", namespaces=NS) == [aside]
    assert timing.xpath(".//p:cTn[@presetID]/@nodeType", namespaces=NS) == ["clickEffect"]
    # The sequence carries exactly two click conditions — start and re-arm —
    # and no effect carries one of its own.
    conditions = interactive.xpath(".//p:cond[@evt='onClick']", namespaces=NS)
    assert len(conditions) == 2
    assert all(
        node.xpath("./p:tgtEl/p:spTgt/@spid", namespaces=NS) == [aside] for node in conditions
    )
    assert interactive.xpath(".//p:cTn[@presetID]//p:cond[@evt]", namespaces=NS) == []


def test_an_effect_without_a_target_uses_the_sequence_trigger():
    """Repeating the trigger target on every effect is optional; omitting it
    means the sequence's own trigger, not an unresolved one."""
    builder, slide = _build(_trigger_slide({"type": "onShapeClick", "delayMs": 0}))
    aside = str(builder.identity_registries["animated"].resolve("aside"))
    interactive = _timing(slide).xpath(".//p:seq[p:cTn/@nodeType='interactiveSeq']", namespaces=NS)[0]
    assert interactive.xpath(".//p:cond[@evt='onClick']/p:tgtEl/p:spTgt/@spid", namespaces=NS) == [
        aside,
        aside,
    ]


def test_a_second_trigger_shape_needs_a_second_sequence():
    """The fix the error names has to work: two trigger shapes are two
    interactive sequences, each with its own click condition."""
    builder, slide = _build(
        _slide(
            animations={
                "mainSequence": [],
                "interactiveSequences": [
                    {
                        "id": "first",
                        "trigger": {"type": "onShapeClick", "target": "aside", "delayMs": 0},
                        "effects": [_effect("one", "hero", start={"type": "onShapeClick", "target": "aside"})],
                    },
                    {
                        "id": "second",
                        "trigger": {"type": "onShapeClick", "target": "hero", "delayMs": 0},
                        "effects": [_effect("two", "aside", start={"type": "onShapeClick", "target": "hero"})],
                    },
                ],
            }
        )
    )
    registry = builder.identity_registries["animated"]
    sequences = _timing(slide).xpath(".//p:seq[p:cTn/@nodeType='interactiveSeq']", namespaces=NS)
    assert len(sequences) == 2
    triggers = [
        seq.xpath("./p:cTn/p:stCondLst/p:cond/p:tgtEl/p:spTgt/@spid", namespaces=NS)[0]
        for seq in sequences
    ]
    assert triggers == [str(registry.resolve("aside")), str(registry.resolve("hero"))]


def test_a_non_object_interactive_trigger_is_a_path_aware_error():
    slide_def = _slide(
        animations={
            "mainSequence": [],
            "interactiveSequences": [{"id": "details", "trigger": "aside", "effects": []}],
        }
    )
    with pytest.raises(TimingWriteError) as error:
        _build(slide_def)
    assert "animations.interactiveSequences[0].trigger must be an object" in str(error.value)


# --- timing values ---------------------------------------------------------


def test_timing_values_are_written_with_their_ooxml_scales():
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect(
                    "fx",
                    "hero",
                    preset={"category": "entrance", "effect": "blinds"},
                    timing={
                        "durationMs": 1200,
                        "repeatCount": 3,
                        "repeatDurationMs": 4000,
                        "autoReverse": True,
                        "acceleration": 0.2,
                        "deceleration": 0.3,
                        "restart": "whenNotActive",
                    },
                )
            ],
            "interactiveSequences": [],
        }
    )
    _, slide = _build(slide_def)
    ctn = _timing(slide).xpath(".//p:cTn[@presetID]", namespaces=NS)[0]
    assert ctn.get("repeatCount") == "3000"
    assert ctn.get("repeatDur") == "4000"
    assert ctn.get("autoRev") == "1"
    assert ctn.get("accel") == "20000"
    assert ctn.get("decel") == "30000"
    assert ctn.get("restart") == "whenNotActive"
    assert ctn.xpath("./p:childTnLst/p:animEffect/p:cBhvr/p:cTn/@dur", namespaces=NS) == ["1200"]


def test_repeat_count_one_stays_implicit():
    _, slide = _build(
        _slide(animations={"mainSequence": [_effect("fx", "hero", timing={"repeatCount": 1})], "interactiveSequences": []})
    )
    assert _timing(slide).xpath(".//p:cTn[@presetID]/@repeatCount", namespaces=NS) == []


def test_catalog_duration_default_is_used_when_json_omits_it():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect("fx", "hero", preset={"category": "entrance", "effect": "wedge"}, timing={})
                ],
                "interactiveSequences": [],
            }
        )
    )
    # The Wedge capture records a 2000 ms child duration.
    assert _timing(slide).xpath(
        ".//p:animEffect/p:cBhvr/p:cTn/@dur", namespaces=NS
    ) == ["2000"]


def test_after_effect_none_is_written_without_complaint():
    _, slide = _build(
        _slide(animations={"mainSequence": [_effect("fx", "hero", afterEffect={"type": "none"})], "interactiveSequences": []})
    )
    assert _timing(slide) is not None


#: Options the catalog accepts but this writer emits nothing for. Each one must
#: refuse unconditionally: a plain catalog lookup would start *passing* when
#: Task 8 closes the gap, and the setting would then be dropped in silence.
UNWRITTEN_OPTIONS = [
    ({"afterEffect": {"type": "dim"}}, "animation.afterAnimation.dim"),
    ({"afterEffect": {"type": "hide"}}, "animation.afterAnimation.hide"),
    ({"afterEffect": {"type": "hideOnNextClick"}}, "animation.afterAnimation.hideOnNextClick"),
    ({"afterEffect": {"type": "none", "color": "#808080"}}, "animation.afterAnimation.dimColor"),
    ({"timing": {"durationMs": 500, "rewind": True}}, "animation.timing.rewind"),
    ({"timing": {"durationMs": 500, "smoothStart": True}}, "animation.timing.smoothStart"),
    ({"timing": {"durationMs": 500, "smoothEnd": True}}, "animation.timing.smoothEnd"),
    ({"timing": {"durationMs": 500, "bounceEnd": 300}}, "animation.timing.bounceEnd"),
    (
        {"start": {"type": "withPrevious", "delayMs": 0, "bookmark": "cue1"}},
        "animation.media.bookmarkTrigger",
    ),
    ({"sound": {"src": "audio/click.wav", "mediaType": "audio/wav"}}, "animation.sound.effect"),
]


@pytest.mark.parametrize("patch,key", UNWRITTEN_OPTIONS)
def test_an_unwritten_option_is_refused_today(patch, key):
    slide_def = _slide(
        animations={"mainSequence": [_effect("fx", "hero", **patch)], "interactiveSequences": []}
    )
    with pytest.raises(CapabilityGapError) as error:
        _build(slide_def)
    assert error.value.key == key
    assert "refuses to approximate" in str(error.value)


@pytest.mark.parametrize("patch,key", UNWRITTEN_OPTIONS)
def test_an_unwritten_option_stays_refused_after_its_catalog_gap_closes(
    patch, key, registry, patched_index
):
    """Task 8 closes these catalog gaps one value at a time. Until the writer
    also learns the captured form, a closed gap must not turn the option into a
    silently dropped setting, so the refusal does not depend on the gap."""
    index = patched_index(_close_gap(key))
    assert index.entry(key).writable, "the fixture closed the catalog gap"
    writer = TimingWriter(registry, index=index, slide_slug="catalog")
    with pytest.raises(CapabilityGapError) as error:
        writer.build(
            {
                "mainSequence": [_effect("fx", "catalogTarget", **patch)],
                "interactiveSequences": [],
            }
        )
    assert error.value.key == key
    assert "not implemented by the writer" in str(error.value)
    assert "Implement it against the captured form" in str(error.value)


def test_a_dim_colour_is_refused_whichever_after_effect_carries_it(registry, patched_index):
    """The colour is refused on its own account, so it cannot slip through a
    combination whose type happens to be allowed."""
    index = patched_index(_close_gap("animation.afterAnimation.dim"))
    writer = TimingWriter(registry, index=index, slide_slug="catalog")
    with pytest.raises(CapabilityGapError) as error:
        writer.build(
            {
                "mainSequence": [
                    _effect("fx", "catalogTarget", afterEffect={"type": "dim", "color": "#808080"})
                ],
                "interactiveSequences": [],
            }
        )
    # The type is checked first and is itself unimplemented; with both gaps
    # closed the colour is still the second refusal rather than a dropped field.
    assert error.value.key == "animation.afterAnimation.dim"
    both = patched_index(
        lambda catalog: (
            _close_gap("animation.afterAnimation.dim")(catalog),
            _close_gap("animation.afterAnimation.dimColor")(catalog),
        )
    )
    with pytest.raises(CapabilityGapError) as error:
        TimingWriter(registry, index=both, slide_slug="catalog").build(
            {
                "mainSequence": [
                    _effect("fx", "catalogTarget", afterEffect={"type": "none", "color": "#808080"})
                ],
                "interactiveSequences": [],
            }
        )
    assert error.value.key == "animation.afterAnimation.dimColor"


def test_no_unwritten_option_reaches_the_package(registry, patched_index):
    """With every one of these gaps closed, a slide asking for them still
    produces no timing at all — the refusal happens before anything is
    attached."""
    def mutate(catalog):
        for _patch, key in UNWRITTEN_OPTIONS:
            _close_gap(key)(catalog)

    index = patched_index(mutate)
    for patch, key in UNWRITTEN_OPTIONS:
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        shape = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(914400), Emu(914400))
        local = ShapeIdentityRegistry("catalog")
        local.register("catalogTarget", [shape._element], source_path="elements[0]")
        with pytest.raises(CapabilityGapError):
            write_slide_timing(
                slide._element,
                {
                    "id": "catalog",
                    "animations": {
                        "mainSequence": [_effect("fx", "catalogTarget", **patch)],
                        "interactiveSequences": [],
                    },
                },
                local,
                index=index,
            )
        assert slide._element.xpath(".//*[local-name()='timing']") == []
    assert registry is not None


def test_a_direction_is_written_rather_than_refused():
    """This test used to assert the opposite, and the reason it flipped matters.

    A direction persists as the preset's ``presetSubtype``, and no capture had
    recorded anything but each tile's default one — so asking for a direction
    was refused, because writing it would have emitted the default and dropped
    the request. The 2026-11-02 effect-option capture measured all 133 values,
    so the direction is now transcribed, and the assertion is the subtype
    itself.
    """
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect(
                    "fx",
                    "hero",
                    preset={
                        "category": "entrance",
                        "effect": "flyIn",
                        "options": {"direction": "fromRight"},
                    },
                )
            ],
            "interactiveSequences": [],
        }
    )
    _builder, slide = _build(slide_def)
    timing = _timing(slide)
    subtypes = [
        ctn.get("presetSubtype")
        for ctn in timing.iter()
        if etree.QName(ctn).localname == "cTn" and ctn.get("presetID") is not None
    ]
    assert subtypes == ["2"], subtypes
    # And the motion itself says "from the right", independently of the number:
    # ppt_x runs from beyond the right edge to the shape's own position.
    values = [
        node.get("val")
        for node in timing.iter()
        if etree.QName(node).localname == "strVal"
    ]
    assert "1+#ppt_w/2" in values, values


def test_a_retired_scripting_direction_name_is_refused_with_its_catalog_gap():
    """``variant`` validated against these 45 names, so they are what a reader will try.

    ``left`` is one of them and is not a Fly In direction label, so the plain
    "not a measured value" error would not explain why a name that used to be
    accepted no longer is. The refusal quotes the enumerator's own gap.
    """
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect(
                    "fx",
                    "hero",
                    preset={
                        "category": "entrance",
                        "effect": "flyIn",
                        "options": {"direction": "left"},
                    },
                )
            ],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(CapabilityGapError) as error:
        _build(slide_def)
    assert error.value.key == "animation.effectOptions.direction.left"
    assert "not sdpm's input vocabulary" in str(error.value)


def test_a_non_null_variant_is_refused_and_points_at_options():
    """The field is gone, and a document still setting it must hear so.

    Ignoring a non-null ``variant`` would write the tile's default direction
    while the document asked for another one, which is the exact failure the
    old unconditional refusal existed to prevent.
    """
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect(
                    "fx", "hero",
                    preset={"category": "entrance", "effect": "flyIn", "variant": "left"},
                )
            ],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(TimingWriteError, match="no longer a field"):
        _build(slide_def)


def test_unknown_option_value_lists_what_the_effect_offers():
    """Per effect, not a global list: Fly In's directions are not Stretch's."""
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect(
                    "fx",
                    "hero",
                    preset={
                        "category": "entrance",
                        "effect": "flyIn",
                        "options": {"direction": "sideways"},
                    },
                )
            ],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(TimingWriteError, match="is not a measured value") as error:
        _build(slide_def)
    assert "fromTopRight" in str(error.value)


def test_unknown_effect_lists_the_supported_effects():
    slide_def = _slide(
        animations={
            "mainSequence": [_effect("fx", "hero", preset={"category": "entrance", "effect": "teleport"})],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(TimingWriteError, match="unknown entrance animation effect"):
        _build(slide_def)


def test_a_motion_path_preset_writes_the_path_powerpoint_wrote():
    """Measured, not re-derived. This test used to assert the opposite.

    Every motion-path preset was capture-required because PowerPoint stores a
    preset path as literal path data and no available capture contained it. The
    2026-11-01 GUI capture does, so the writer now transcribes the measured
    geometry — and the assertion is the path string itself, because a Bézier
    that is close is wrong.
    """
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect(
                    "fx", "hero",
                    preset={"category": "motionPath", "effect": "arcs"},
                    timing={"durationMs": 2000},
                )
            ],
            "interactiveSequences": [],
        }
    )
    _, slide = _build(slide_def)
    motions = _timing(slide).findall(".//{%s}animMotion" % NS["p"])
    assert len(motions) == 1
    assert motions[0].get("path") == (
        "M 0 0 L 0.067 0.04 C 0.081 0.049 0.102 0.054 0.124 0.054 "
        "C 0.149 0.054 0.169 0.049 0.183 0.04 L 0.25 0 E"
    )
    assert motions[0].get("origin") == "layout"
    assert motions[0].get("pathEditMode") == "relative"
    names = [node.text for node in motions[0].findall(".//{%s}attrName" % NS["p"])]
    assert names == ["ppt_x", "ppt_y"]


# --- presets and behaviors -------------------------------------------------


def test_captured_preset_identity_and_behavior_children_are_reproduced():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect("fx", "hero", preset={"category": "entrance", "effect": "blinds"})
                ],
                "interactiveSequences": [],
            }
        )
    )
    ctn = _timing(slide).xpath(".//p:cTn[@presetID]", namespaces=NS)[0]
    assert (ctn.get("presetID"), ctn.get("presetClass"), ctn.get("presetSubtype")) == ("3", "entr", "10")
    children = [etree.QName(node).localname for node in ctn.xpath("./p:childTnLst/*", namespaces=NS)]
    # The order PowerPoint wrote, not the alphabetical one. Blinds was outside
    # the gallery capture's plan, so this used to be synthesised from the
    # distinct `behaviorChildren` names and came out sorted. The tile's own
    # default option measured `p:set` first, and a setting's default leaves the
    # effect at the tile's default, so those behaviours were lifted into it.
    assert children == ["set", "animEffect"]
    anim_effect = ctn.xpath("./p:childTnLst/p:animEffect", namespaces=NS)[0]
    assert anim_effect.get("filter") == "blinds(horizontal)"
    assert anim_effect.get("transition") == "in"
    assert ctn.xpath(".//p:set/p:cBhvr/p:attrNameLst/p:attrName/text()", namespaces=NS) == [
        "style.visibility"
    ]
    assert ctn.xpath(".//p:set/p:to/p:strVal/@val", namespaces=NS) == ["visible"]


def test_an_entrance_makes_the_shape_visible_at_the_effect_start():
    """The visibility change is a 1 ms discrete state change held by
    ``fill="hold"``, not a duration-less node: ``CT_TLCommonBehaviorData``
    always carries a ``p:cTn``, and the catalog records the timing rule."""
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect(
                        "fx",
                        "hero",
                        preset={"category": "entrance", "effect": "fade"},
                        timing={"durationMs": 500},
                    )
                ],
                "interactiveSequences": [],
            }
        )
    )
    behavior = _timing(slide).xpath(".//p:set/p:cBhvr/p:cTn", namespaces=NS)[0]
    assert behavior.get("dur") == "1"
    assert behavior.get("fill") == "hold"
    assert behavior.xpath("./p:stCondLst/p:cond/@delay", namespaces=NS) == ["0"]


def test_an_exit_hides_the_shape_in_the_last_millisecond_of_its_duration():
    """An exit must stay visible while its filter runs, so the hide instant
    comes from the active duration rather than from the effect start."""
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect(
                        "fx",
                        "hero",
                        preset={"category": "exit", "effect": "wipe"},
                        timing={"durationMs": 500},
                    )
                ],
                "interactiveSequences": [],
            }
        )
    )
    timing = _timing(slide)
    behavior = timing.xpath(".//p:set/p:cBhvr/p:cTn", namespaces=NS)[0]
    assert behavior.get("dur") == "1"
    assert behavior.get("fill") == "hold"
    assert behavior.xpath("./p:stCondLst/p:cond/@delay", namespaces=NS) == ["499"]
    assert timing.xpath(".//p:animEffect/p:cBhvr/p:cTn/@dur", namespaces=NS) == ["500"]


def test_the_visibility_timing_rule_comes_from_the_catalog(index):
    rule = index.behavior_payloads["resolved"]["p:set"]["behaviorTiming"]
    assert (rule["durMs"], rule["fill"], rule["entranceDelayMs"], rule["exitDelayOffsetMs"]) == (
        1,
        "hold",
        0,
        -1,
    )


def test_an_exit_preset_without_a_resolvable_duration_is_rejected():
    """Nothing is written when the hide instant cannot be derived.

    An exit effect built from the catalog's general rules has to work out where
    the visibility ``p:set`` ends, and only a duration tells it. Three exit
    tiles still record none — Fade, Dissolve Out and Wedge — because the gallery
    capture skipped them and they offer no Effect Options to take measured
    behaviours from.

    This used to name Wipe (Exit), which no longer qualifies: Wipe offers a
    Direction, so its default value's measured behaviours are the tile's own and
    were lifted into it. Eight exit tiles were fixed that way, which is why the
    example moved rather than the assertion.
    """
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect("fx", "hero", preset={"category": "exit", "effect": "fade"}, timing={})
            ],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(TimingWriteError, match="needs an explicit timing.durationMs"):
        _build(slide_def)


def test_exit_presets_hide_the_shape_and_run_the_filter_outward():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [_effect("fx", "hero", preset={"category": "exit", "effect": "wipe"})],
                "interactiveSequences": [],
            }
        )
    )
    ctn = _timing(slide).xpath(".//p:cTn[@presetID]", namespaces=NS)[0]
    assert ctn.get("presetClass") == "exit"
    assert ctn.xpath("./p:childTnLst/p:animEffect/@transition", namespaces=NS) == ["out"]
    assert ctn.xpath(".//p:set/p:to/p:strVal/@val", namespaces=NS) == ["hidden"]


def test_media_play_preset_writes_the_captured_command():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect("fx", "hero", preset={"category": "media", "effect": "mediaPlay"})
                ],
                "interactiveSequences": [],
            }
        )
    )
    ctn = _timing(slide).xpath(".//p:cTn[@presetID]", namespaces=NS)[0]
    assert ctn.get("presetClass") == "mediacall"
    cmd = ctn.xpath("./p:childTnLst/p:cmd", namespaces=NS)[0]
    assert (cmd.get("type"), cmd.get("cmd")) == ("call", "playFrom(0.0)")


def test_a_presets_measured_payload_is_transcribed_rather_than_approximated():
    """Fly In's ``p:anim`` has no ``p:to`` at all: its payload is a keyframe list.

    This test used to assert the preset was refused, because the native capture
    recorded *which* children Fly In writes and not what they say. The GUI
    capture says: two ``p:anim`` of ``calcmode="lin" valueType="num"``,
    ``additive="base"`` on the carrier, each with a ``p:tavLst`` of two
    keyframes holding ``#ppt_x`` and ``#ppt_y``. A writer that synthesised a
    ``p:to`` here would have produced a plausible animation that is not this one.
    """
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect("fx", "hero", preset={"category": "entrance", "effect": "flyIn"})
            ],
            "interactiveSequences": [],
        }
    )
    _, slide = _build(slide_def)
    timing = _timing(slide)
    anims = timing.findall(".//{%s}anim" % NS["p"])
    assert len(anims) == 2
    assert [node.get("valueType") for node in anims] == ["num", "num"]
    carriers = [node.find("{%s}cBhvr" % NS["p"]) for node in anims]
    assert [node.get("additive") for node in carriers] == ["base", "base"]
    assert [
        [inner.text for inner in node.findall(".//{%s}attrName" % NS["p"])] for node in anims
    ] == [["ppt_x"], ["ppt_y"]]
    keyframes = anims[0].findall(".//{%s}tav" % NS["p"])
    assert [node.get("tm") for node in keyframes] == ["0", "100000"]
    assert [
        node.find(".//{%s}strVal" % NS["p"]).get("val") for node in keyframes
    ] == ["#ppt_x", "#ppt_x"]


def test_a_longer_duration_scales_every_measured_behaviour_in_proportion():
    """Measured: Duration 0.50 → 1.00 doubled all five of Wave's behaviours.

    The motion went 250 → 500 and the four rotations 125 → 250 at delays 0,
    250, 500 and 750, while ``@path`` and ``@by`` did not move at all. Those
    are the numbers PowerPoint wrote, so they are the numbers asserted.
    """
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect(
                    "fx", "hero",
                    preset={"category": "emphasis", "effect": "wave"},
                    timing={"durationMs": 1000},
                )
            ],
            "interactiveSequences": [],
        }
    )
    _, slide = _build(slide_def)
    timing = _timing(slide)
    motion = timing.find(".//{%s}animMotion" % NS["p"])
    assert motion.find("{%s}cBhvr/{%s}cTn" % (NS["p"], NS["p"])).get("dur") == "500"
    assert motion.get("path") == "M 0.0 0.0 L 0.0 -0.07213", "geometry does not scale"
    rotations = timing.findall(".//{%s}animRot" % NS["p"])
    assert [node.get("by") for node in rotations] == [
        "1500000", "-1500000", "-1500000", "1500000",
    ]
    carriers = [node.find("{%s}cBhvr/{%s}cTn" % (NS["p"], NS["p"])) for node in rotations]
    assert [node.get("dur") for node in carriers] == ["250"] * 4
    assert [
        node.find(".//{%s}cond" % NS["p"]).get("delay") for node in carriers
    ] == ["0", "250", "500", "750"]


def test_the_visibility_toggle_is_exempt_from_the_scaling_and_recomputed():
    """Measured: Fly Out hides the shape at 499 ms of 500 and at 999 of 1000.

    Scaling 499 would give 998. It is 999, so the delay is recomputed from the
    effect duration rather than scaled, and the 1 ms duration does not scale at
    all — it stayed 1 while every animated behaviour doubled.
    """
    def build(duration):
        slide_def = _slide(
            animations={
                "mainSequence": [
                    _effect(
                        "fx", "hero",
                        preset={"category": "exit", "effect": "flyOut"},
                        timing={"durationMs": duration},
                    )
                ],
                "interactiveSequences": [],
            }
        )
        _, slide = _build(slide_def)
        node = _timing(slide).find(".//{%s}set" % NS["p"])
        ctn = node.find("{%s}cBhvr/{%s}cTn" % (NS["p"], NS["p"]))
        return ctn.get("dur"), ctn.find(".//{%s}cond" % NS["p"]).get("delay")

    assert build(500) == ("1", "499")
    assert build(1000) == ("1", "999"), "998 would be the scaled value, and it is not what PowerPoint writes"


def test_an_effect_with_no_numeric_duration_refuses_one_rather_than_ignoring_it():
    """Bold Reveal's Duration reads ``Auto`` and its behaviour is ``indefinite``.

    There is nothing to scale from, so a caller's explicit duration cannot be
    honoured. Refusing says so; ignoring it would drop the request silently.
    """
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect(
                    "fx", "hero",
                    preset={"category": "emphasis", "effect": "boldReveal"},
                    timing={"durationMs": 1000},
                )
            ],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(TimingWriteError, match="no scalable duration"):
        _build(slide_def)


def test_an_effect_with_no_numeric_duration_writes_its_measured_form():
    """Omit the duration and the measured form is written as it stands."""
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect(
                    "fx", "hero",
                    preset={"category": "emphasis", "effect": "boldReveal"},
                    timing={"durationMs": None},
                )
            ],
            "interactiveSequences": [],
        }
    )
    _, slide = _build(slide_def)
    ctn = _timing(slide).find(".//{%s}set/{%s}cBhvr/{%s}cTn" % (NS["p"], NS["p"], NS["p"]))
    assert ctn.get("dur") == "indefinite"


def test_an_emphasis_set_writes_the_font_attribute_the_capture_names():
    """The attribute name this entry was refused for not knowing, now measured.

    ``BEHAVIOR_PAYLOADS`` says of the emphasis ``p:set`` children that they
    "set a font attribute whose name is not captured, so those tiles are
    refused". Underline's is ``style.textDecorationUnderline``, set to the
    string ``true``.
    """
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect("fx", "hero", preset={"category": "emphasis", "effect": "underline"})
            ],
            "interactiveSequences": [],
        }
    )
    _, slide = _build(slide_def)
    sets = _timing(slide).findall(".//{%s}set" % NS["p"])
    assert len(sets) == 1
    names = [node.text for node in sets[0].findall(".//{%s}attrName" % NS["p"])]
    assert names == ["style.textDecorationUnderline"]
    assert sets[0].find(".//{%s}strVal" % NS["p"]).get("val") == "true"


def test_the_writer_refuses_an_unresolved_payload_even_without_a_catalog_gap(registry, index):
    """Defence in depth: if a catalog regeneration ever dropped the recorded
    gap, the writer still refuses rather than emitting a payload-free node."""
    import copy

    patched = copy.copy(index)
    patched.items = dict(index.items)
    gapless = CapabilityEntry(
        key="animation.gallery.entrance.flyIn",
        status="accepted",
        level="nativeTemplate",
        # The recorded gap and unresolvedPayloads are gone; the behavior
        # children are not.
        ooxml={
            "strategy": "preset",
            "element": "p:cTn",
            "presetClass": "entr",
            "presetId": 2,
            "presetSubtype": 4,
            "behaviorChildren": ["p:anim", "p:set"],
            "observedChildDurationMs": 500,
        },
        semantic={},
        group="guiItems",
    )
    patched.items["animation.gallery.entrance.flyIn"] = gapless
    assert gapless.writable, "the fixture has no catalog gap left"

    writer = TimingWriter(registry, index=patched, slide_slug="catalog")
    with pytest.raises(BehaviorPayloadGapError) as error:
        writer.build(
            {
                "mainSequence": [
                    _effect(
                        "fx",
                        "catalogTarget",
                        preset={"category": "entrance", "effect": "flyIn"},
                    )
                ],
                "interactiveSequences": [],
            }
        )
    assert error.value.elements == ("p:anim",)


def test_the_payload_gate_names_every_unresolved_child_at_once(index):
    """The gate is a pure function over the catalog, so a preset with two
    unresolved children reports both instead of stopping at the first."""
    payloads = index.behavior_payloads
    entry = index.items["animation.gallery.entrance.blinds"]
    assert preset_payload_gaps(entry, "entrance", payloads) == ()
    assert [name for name, _ in preset_payload_gaps(entry, "emphasis", payloads)] == ["p:set"]

    invented = CapabilityEntry(
        key="synthetic",
        status="accepted",
        level="nativeTemplate",
        ooxml={"behaviorChildren": ["p:animClr", "p:animScale", "p:animEffect"]},
        semantic={},
        group="guiItems",
    )
    gaps = preset_payload_gaps(invented, "entrance", payloads)
    assert [name for name, _ in gaps] == ["p:animClr", "p:animScale", "p:animEffect"]
    assert all(reason for _, reason in gaps)
    with pytest.raises(BehaviorPayloadGapError) as error:
        raise BehaviorPayloadGapError(invented.key, gaps)
    assert error.value.elements == ("p:animClr", "p:animScale", "p:animEffect")


def test_a_preset_with_no_captured_behavior_children_is_refused(index):
    empty = CapabilityEntry(
        key="synthetic.empty", status="accepted", level="presetMapping",
        ooxml={}, semantic={}, group="guiItems",
    )
    gaps = preset_payload_gaps(empty, "entrance", index.behavior_payloads)
    assert [name for name, _ in gaps] == ["-"]
    assert "no behavior children" in gaps[0][1]


BEHAVIORS = [
    ({"type": "motion", "path": "M 0 0 L 0.5 0.25 E", "pathEditMode": "relative", "origin": "layout"}, "animMotion"),
    ({"type": "color", "to": "#FF8800"}, "animClr"),
    ({"type": "scale", "to": {"x": 1.5, "y": 1.5}}, "animScale"),
    ({"type": "rotation", "by": 360}, "animRot"),
    ({"type": "property", "attrName": "ppt_x", "to": "0.75", "calcMode": "lin", "valueType": "num"}, "anim"),
    ({"type": "command", "command": "playFrom", "value": "0.0"}, "cmd"),
    ({"type": "filter", "filter": "fade", "transition": "in"}, "animEffect"),
    ({"type": "set", "attrName": "style.visibility", "to": "visible"}, "set"),
]


@pytest.mark.parametrize("behavior,tag", BEHAVIORS)
def test_each_behavior_primitive_writes_its_element_with_explicit_payload(behavior, tag):
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [_effect("fx", "hero", preset=None, behaviors=[behavior])],
                "interactiveSequences": [],
            }
        )
    )
    timing = _timing(slide)
    nodes = timing.xpath(f".//p:cTn[@nodeType='clickEffect']/p:childTnLst/p:{tag}", namespaces=NS)
    assert len(nodes) == 1
    node = nodes[0]
    assert node.xpath("./p:cBhvr/p:tgtEl/p:spTgt/@spid", namespaces=NS)
    if tag == "animMotion":
        assert node.get("path") == "M 0 0 L 0.5 0.25 E"
        assert node.get("pathEditMode") == "relative"
    if tag == "animClr":
        assert node.xpath("./p:to/a:srgbClr/@val", namespaces=NS) == ["FF8800"]
    if tag == "animScale":
        to = node.xpath("./p:to", namespaces=NS)[0]
        assert (to.get("x"), to.get("y")) == ("150000", "150000")
    if tag == "animRot":
        assert node.get("by") == str(360 * 60000)
    if tag == "anim":
        assert node.get("calcmode") == "lin"
        assert node.xpath("./p:cBhvr/p:attrNameLst/p:attrName/text()", namespaces=NS) == ["ppt_x"]
    if tag == "cmd":
        assert node.get("cmd") == "playFrom(0.0)"
    if tag == "set":
        assert node.xpath("./p:to/p:strVal/@val", namespaces=NS) == ["visible"]


def test_an_effect_whose_only_behavior_is_the_no_op_is_rejected():
    """``p:childTnLst`` is ``CT_TimeNodeList`` and needs at least one child.
    The explicit no-op persists nothing, so an effect made only of no-ops has
    to be rejected rather than written as an empty, schema-invalid list."""
    slide_def = _slide(
        animations={
            "mainSequence": [_effect("fx", "hero", preset=None, behaviors=[{"type": "none"}])],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(TimingWriteError) as error:
        _build(slide_def)
    assert "only the explicit no-op" in str(error.value)
    assert "CT_TimeNodeList" in str(error.value)


def test_a_no_op_beside_a_real_behavior_contributes_nothing_and_is_allowed():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect(
                        "fx",
                        "hero",
                        preset=None,
                        behaviors=[
                            {"type": "none"},
                            {"type": "set", "attrName": "style.visibility", "to": "visible"},
                        ],
                    )
                ],
                "interactiveSequences": [],
            }
        )
    )
    effect = _timing(slide).xpath(".//p:cTn[@nodeType='clickEffect']", namespaces=NS)[0]
    children = [etree.QName(node).localname for node in effect.xpath("./p:childTnLst/*", namespaces=NS)]
    assert children == ["set"]


def test_no_generated_child_time_node_list_is_ever_empty():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect("one", "hero"),
                    _effect("two", "aside", start={"type": "afterPrevious", "delayMs": 0}),
                ],
                "interactiveSequences": [
                    {
                        "id": "seq",
                        "trigger": {"type": "onShapeClick", "target": "aside", "delayMs": 0},
                        "effects": [_effect("three", "hero")],
                    }
                ],
            }
        )
    )
    lists = _timing(slide).xpath(".//p:childTnLst", namespaces=NS)
    assert lists and all(len(node) > 0 for node in lists)


def test_nine_behavior_primitives_are_all_modelled():
    from sdpm.engine.timing import BEHAVIOR_ELEMENTS

    assert len(BEHAVIOR_ELEMENTS) == 9
    assert BEHAVIOR_ELEMENTS["none"] is None
    assert set(filter(None, BEHAVIOR_ELEMENTS.values())) == {
        "p:animMotion",
        "p:animClr",
        "p:animScale",
        "p:animRot",
        "p:anim",
        "p:cmd",
        "p:animEffect",
        "p:set",
    }


def test_preset_and_behaviors_are_mutually_exclusive():
    slide_def = _slide(
        animations={
            "mainSequence": [_effect("fx", "hero", behaviors=[{"type": "set"}])],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(TimingWriteError, match="exactly one of preset or behaviors"):
        _build(slide_def)


def _behaviors(*behaviors):
    return _slide(
        animations={
            "mainSequence": [_effect("fx", "hero", preset=None, behaviors=list(behaviors))],
            "interactiveSequences": [],
        }
    )


#: ``model.py`` is the frozen Task 2 contract and validates only the behavior
#: ``type``, so these OOXML vocabularies are enforced at the writer boundary.
INVALID_BEHAVIOR_VALUES = [
    ({"type": "command", "command": "playFrom", "value": "0.0", "commandType": "invoke"}, "commandType"),
    ({"type": "motion", "path": "M 0 0 L 1 0 E", "origin": "slide"}, "origin"),
    ({"type": "motion", "path": "M 0 0 L 1 0 E", "pathEditMode": "absolute"}, "pathEditMode"),
    ({"type": "property", "attrName": "ppt_x", "to": "0.5", "calcMode": "linear"}, "calcMode"),
    ({"type": "property", "attrName": "ppt_x", "to": "0.5", "valueType": "float"}, "valueType"),
    ({"type": "filter", "filter": "fade", "transition": "inward"}, "transition"),
]


@pytest.mark.parametrize("behavior,attribute", INVALID_BEHAVIOR_VALUES)
def test_an_out_of_enum_behavior_attribute_is_a_path_aware_error(behavior, attribute):
    with pytest.raises(TimingWriteError) as error:
        _build(_behaviors(behavior))
    message = str(error.value)
    assert f"mainSequence[0].behaviors[0].{attribute}" in message
    assert "is not an OOXML value" in message
    assert "allowed:" in message


@pytest.mark.parametrize(
    "behavior,needle",
    [
        ({"type": "motion"}, "a motion path"),
        ({"type": "color"}, "a target colour"),
        ({"type": "scale"}, "target scale factors"),
        ({"type": "rotation"}, "an angle"),
        ({"type": "property", "attrName": "ppt_x"}, "a value"),
        ({"type": "command"}, "a command"),
        ({"type": "filter"}, "a filter or transition"),
        ({"type": "set", "attrName": "style.visibility"}, "a target value"),
    ],
)
def test_a_behavior_without_a_payload_is_rejected_instead_of_emitted_empty(behavior, needle):
    with pytest.raises(TimingWriteError) as error:
        _build(_behaviors(behavior))
    assert needle in str(error.value)
    assert "mainSequence[0].behaviors[0]" in str(error.value)


@pytest.mark.parametrize("behavior", [{"type": "set", "to": "visible"}, {"type": "property", "to": "0.5"}])
def test_a_behavior_that_needs_an_attribute_name_must_carry_one(behavior):
    with pytest.raises(TimingWriteError) as error:
        _build(_behaviors(behavior))
    assert "mainSequence[0].behaviors[0].attrName" in str(error.value)


@pytest.mark.parametrize("colour", ["red", "#FFF", "#1234567", "0xFF8800"])
def test_a_colour_behavior_requires_a_six_digit_srgb_value(colour):
    with pytest.raises(TimingWriteError, match="sRGB hex colour"):
        _build(_behaviors({"type": "color", "to": colour}))


def test_a_scale_behavior_requires_an_object_payload():
    with pytest.raises(TimingWriteError, match="x and y scale factors"):
        _build(_behaviors({"type": "scale", "to": 1.5}))


def test_motion_rotation_is_normalized_to_sixtythousandths_of_a_degree():
    """``p:animMotion/@rAng`` is ST_Angle like every other DrawingML angle, so
    a JSON degree value has to be scaled the same way ``p:animRot`` is."""
    _, slide = _build(
        _behaviors({"type": "motion", "path": "M 0 0 L 0.5 0 E", "rotationAngle": 90})
    )
    motion = _timing(slide).xpath(".//p:animMotion", namespaces=NS)[0]
    assert motion.get("rAng") == str(90 * 60000)


def test_every_catalogued_command_type_is_accepted():
    for command_type in ("evt", "call", "verb"):
        _, slide = _build(
            _behaviors({"type": "command", "command": "playFrom", "value": "0.0",
                        "commandType": command_type})
        )
        assert _timing(slide).xpath(".//p:cmd/@type", namespaces=NS) == [command_type]


# --- text, paragraph, chart and SmartArt builds ----------------------------


def test_text_unit_and_inter_item_delay_write_an_iterate_node():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect("fx", "hero", text={"unit": "byWord", "interItemDelayPercent": 10})
                ],
                "interactiveSequences": [],
            }
        )
    )
    effect = _timing(slide).xpath(".//p:cTn[@presetID]", namespaces=NS)[0]
    children = [etree.QName(node).localname for node in effect]
    assert children == ["stCondLst", "iterate", "childTnLst"], "schema child order"
    iterate = effect.xpath("./p:iterate", namespaces=NS)[0]
    assert iterate.get("type") == "wd"
    assert iterate.xpath("./p:tmPct/@val", namespaces=NS) == ["10000"]


def test_by_character_uses_the_catalogued_iterate_type():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect("fx", "hero", text={"unit": "byCharacter", "interItemDelayPercent": 10})
                ],
                "interactiveSequences": [],
            }
        )
    )
    assert _timing(slide).xpath(".//p:iterate/@type", namespaces=NS) == ["lt"]


def test_a_text_unit_without_an_interval_is_rejected():
    """``CT_TLIterateData`` is a choice of exactly one ``p:tmAbs`` or
    ``p:tmPct``, and the capture records no default interval, so an interval
    must be supplied rather than guessed or silently dropped."""
    slide_def = _slide(
        animations={
            "mainSequence": [_effect("fx", "hero", text={"unit": "byWord"})],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(TimingWriteError) as error:
        _build(slide_def)
    assert "interItemDelayPercent is required" in str(error.value)
    assert "CT_TLIterateData" in str(error.value)


def test_every_generated_iterate_node_carries_an_interval():
    for unit in ("byWord", "byCharacter", "byParagraph"):
        _, slide = _build(
            _slide(
                animations={
                    "mainSequence": [
                        _effect("fx", "hero", text={"unit": unit, "interItemDelayPercent": 25})
                    ],
                    "interactiveSequences": [],
                }
            )
        )
        for node in _timing(slide).xpath(".//p:iterate", namespaces=NS):
            assert node.xpath("./p:tmPct|./p:tmAbs", namespaces=NS), unit


def test_by_paragraph_needs_no_iterate_node():
    _, slide = _build(
        _slide(animations={"mainSequence": [_effect("fx", "hero", text={"unit": "byParagraph"})], "interactiveSequences": []})
    )
    assert _timing(slide).xpath(".//p:iterate", namespaces=NS) == []


def test_paragraph_build_level_sequence_and_reverse_order_reach_the_build_list():
    builder, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect(
                        "fx",
                        "hero",
                        text={
                            "sequence": "byParagraph",
                            "level": "byParagraphLevel2",
                            "reverseOrder": True,
                            "animateBackground": True,
                        },
                    )
                ],
                "interactiveSequences": [],
            }
        )
    )
    spid = builder.identity_registries["animated"].resolve("hero")
    bld = _timing(slide).xpath(".//p:bldLst/p:bldP", namespaces=NS)[0]
    assert bld.get("spid") == str(spid)
    assert bld.get("grpId") == "0"
    assert bld.get("build") == "p"
    assert bld.get("bldLvl") == "2"
    assert bld.get("rev") == "1"
    assert bld.get("animBg") == "1"


def test_animate_background_can_be_switched_off():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [_effect("fx", "hero", text={"animateBackground": False})],
                "interactiveSequences": [],
            }
        )
    )
    assert _timing(slide).xpath(".//p:bldLst/p:bldP/@animBg", namespaces=NS) == []


def test_paragraph_range_targets_use_a_text_element_target():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect("fx", "hero", target={"element": "hero", "paragraphRange": {"start": 1, "end": 2}})
                ],
                "interactiveSequences": [],
            }
        )
    )
    p_rg = _timing(slide).xpath(".//p:spTgt/p:txEl/p:pRg", namespaces=NS)[0]
    assert (p_rg.get("st"), p_rg.get("end")) == ("1", "2")


def test_chart_build_writes_bld_graphic_with_its_chart_child():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [_effect("fx", "hero", chart={"build": "chartByCategory"})],
                "interactiveSequences": [],
            }
        )
    )
    timing = _timing(slide)
    bld = timing.xpath(".//p:bldLst/p:bldGraphic", namespaces=NS)[0]
    assert bld.xpath("./p:bldSub/a:bldChart/@bld", namespaces=NS) == ["category"]
    assert timing.xpath(".//p:bldLst/p:bldP", namespaces=NS) == [], (
        "p:bldLst keys a build by spid+grpId, so a chart build must not also emit a paragraph build"
    )


def test_smart_art_build_writes_bld_dgm():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [_effect("fx", "hero", smartArt={"build": "oneByOne"})],
                "interactiveSequences": [],
            }
        )
    )
    timing = _timing(slide)
    assert timing.xpath(".//p:bldLst/p:bldDgm/@bld", namespaces=NS) == ["one"]
    assert timing.xpath(".//p:bldLst/p:bldP", namespaces=NS) == []


def test_one_build_per_shape_and_group_is_enforced():
    builds = _timing(
        _build(
            _slide(
                animations={
                    "mainSequence": [_effect("fx", "hero", chart={"build": "chartByCategory"})],
                    "interactiveSequences": [],
                }
            )
        )[1]
    ).xpath(".//p:bldLst/*", namespaces=NS)
    keys = [(node.get("spid"), node.get("grpId")) for node in builds]
    assert len(keys) == len(set(keys)) == 1


@pytest.mark.parametrize(
    "patch,needle",
    [
        ({"chart": {"build": "chartByCategory"}, "text": {"unit": "byParagraph"}}, "paragraph text options"),
        ({"smartArt": {"build": "oneByOne"}, "text": {"animateBackground": True}}, "paragraph text options"),
        (
            {"chart": {"build": "chartByCategory"}, "smartArt": {"build": "oneByOne"}},
            "both a chart and a SmartArt build",
        ),
    ],
)
def test_contradictory_build_requests_are_rejected(patch, needle):
    slide_def = _slide(
        animations={
            "mainSequence": [_effect("fx", "hero", **patch)],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(TimingWriteError) as error:
        _build(slide_def)
    assert needle in str(error.value)


def test_one_build_entry_per_shape_and_group():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect("one", "hero"),
                    _effect("two", "hero", start={"type": "afterPrevious", "delayMs": 0}),
                    _effect("three", "aside", start={"type": "afterPrevious", "delayMs": 0}),
                ],
                "interactiveSequences": [],
            }
        )
    )
    timing = _timing(slide)
    builds = timing.xpath(".//p:bldLst/p:bldP", namespaces=NS)
    pairs = [(node.get("spid"), node.get("grpId")) for node in builds]
    assert len(pairs) == len(set(pairs)) == 3
    grp_ids = timing.xpath(".//p:cTn[@presetID]/@grpId", namespaces=NS)
    assert grp_ids == ["0", "1", "0"], "a second animation on one shape gets the next group id"


# --- build values come from the catalog, per build element -----------------

#: The catalog keeps the chart builds and the paragraph levels in one family
#: (``animation.textOptions.level``) but writes them into different elements.
CHART_BUILDS = (
    "chartAllAtOnce",
    "chartByCategory",
    "chartByCategoryElement",
    "chartBySeries",
    "chartBySeriesElement",
)
PARAGRAPH_LEVELS = (
    "allParagraphLevels",
    "asOneObject",
    "byParagraphLevel1",
    "byParagraphLevel2",
    "byParagraphLevel3",
    "byParagraphLevel4",
    "byParagraphLevel5",
)


def test_the_catalog_separates_chart_builds_from_paragraph_levels(index):
    """Both controls share the ``animation.textOptions.level`` family, so the
    element has to be part of the lookup: ``byParagraphLevel2`` writes
    ``p:bldP/@build="p"``, which is not an ST_AnimationChartBuildType value."""
    family = "animation.textOptions.level"
    assert index.build_values(family, element="p:bldGraphic", child="p:bldSub/a:bldChart") == CHART_BUILDS
    assert index.build_values(family, element="p:bldP") == PARAGRAPH_LEVELS
    assert index.build_values("animation.smartArt.build", element="p:bldDgm") == (
        "allAtOnce",
        "asOneObject",
        "byBranchOneByOne",
        "byLevelAtOnce",
        "byLevelOneByOne",
        "oneByOne",
    )
    assert index.build_entry(family, "byParagraphLevel2", element="p:bldGraphic") is None


def _chart_slide(value):
    return _slide(
        animations={
            "mainSequence": [_effect("fx", "hero", chart={"build": value})],
            "interactiveSequences": [],
        }
    )


@pytest.mark.parametrize("value", PARAGRAPH_LEVELS)
def test_a_paragraph_level_is_not_a_chart_build(value):
    """The bug this closes: a paragraph value resolved inside the shared family
    and its ``p:bldP`` token (or an empty one) was written into
    ``a:bldChart/@bld``."""
    with pytest.raises(TimingWriteError) as error:
        _build(_chart_slide(value))
    message = str(error.value)
    assert f"mainSequence[0].chart.build {value!r} is not a catalogued p:bldGraphic build value" in message
    assert ", ".join(CHART_BUILDS) in message, "the error lists the values that are allowed"


@pytest.mark.parametrize("value", ["", "   ", 2, True, ["chartByCategory"], {"build": "chartBySeries"}])
def test_an_unusable_chart_build_value_is_rejected(value):
    with pytest.raises(TimingWriteError, match="is not a catalogued p:bldGraphic build value"):
        _build(_chart_slide(value))


@pytest.mark.parametrize("value", CHART_BUILDS)
def test_every_catalogued_chart_build_writes_its_recorded_token(value, index):
    _, slide = _build(_chart_slide(value))
    expected = index.entry(f"animation.textOptions.level.{value}").ooxml["value"]
    bld = _timing(slide).xpath(".//p:bldLst/p:bldGraphic", namespaces=NS)[0]
    assert bld.xpath("./p:bldSub/a:bldChart/@bld", namespaces=NS) == [expected]
    assert expected.strip(), "an empty build token is never written"


@pytest.mark.parametrize(
    "value",
    # ``asOneObject`` is a catalogued SmartArt build in its own right, so only
    # the values that belong to another element are rejected here.
    [*CHART_BUILDS, *(level for level in PARAGRAPH_LEVELS if level != "asOneObject"), "", "unknown"],
)
def test_a_chart_or_paragraph_value_is_not_a_smart_art_build(value):
    slide_def = _slide(
        animations={
            "mainSequence": [_effect("fx", "hero", smartArt={"build": value})],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(TimingWriteError, match="is not a catalogued p:bldDgm build value"):
        _build(slide_def)


def test_a_blank_catalog_build_token_is_refused_instead_of_written(registry, patched_index):
    """A catalog regeneration that lost the recorded ``bld`` token must not
    produce ``a:bldChart bld=""``; PowerPoint would ask the user to repair the
    package."""

    def mutate(catalog):
        for entry in _entries(catalog, "animation.textOptions.level.chartByCategory"):
            entry["ooxml"]["value"] = "  "

    index = patched_index(mutate)
    writer = TimingWriter(registry, index=index, slide_slug="catalog")
    with pytest.raises(TimingWriteError) as error:
        writer.build(
            {
                "mainSequence": [_effect("fx", "catalogTarget", chart={"build": "chartByCategory"})],
                "interactiveSequences": [],
            }
        )
    assert "records no 'bld' build token" in str(error.value)
    assert "mainSequence[0].chart.build" in str(error.value)


def test_a_build_value_resolving_to_another_element_is_refused(registry, patched_index):
    """Defence in depth: the allowed-value list and the key lookup are two
    reads of the catalog. If a regeneration made them disagree, the writer must
    refuse rather than write one build element's value into another."""

    def mutate(catalog):
        duplicate = copy.deepcopy(
            next(_entries(catalog, "animation.smartArt.build.oneByOne"))
        )
        duplicate["ooxml"]["element"] = "p:bldP"
        catalog["guiItems"].append(duplicate)

    index = patched_index(mutate)
    writer = TimingWriter(registry, index=index, slide_slug="catalog")
    with pytest.raises(TimingWriteError) as error:
        writer.build(
            {
                "mainSequence": [_effect("fx", "catalogTarget", smartArt={"build": "oneByOne"})],
                "interactiveSequences": [],
            }
        )
    message = str(error.value)
    assert "records 'p:bldP'" in message and "rather than 'p:bldDgm'" in message
    assert "will not write one build element's value into another" in message


# --- the paragraph build follows the capture, not a default ---------------


def test_the_capture_records_a_build_list_only_for_shape_level_tiles(index, catalog):
    """``p:bldP/@animBg=1`` is recorded for all 95 entrance, emphasis and exit
    tiles. The media and motion-path tiles record no build list at all, so
    there is no evidence for attaching a paragraph build to them."""
    recorded, missing = [], []
    for entry in catalog["guiItems"]:
        if not entry["key"].startswith("animation.gallery."):
            continue
        category = entry["key"].split(".")[2]
        if "buildList" in entry["ooxml"]:
            assert entry["ooxml"]["buildList"] == "p:bldP/@animBg=1"
            recorded.append(category)
        else:
            missing.append(category)
    assert len(recorded) == 95 and set(recorded) == {"entrance", "emphasis", "exit"}
    assert sorted(missing) == ["media"] * 3 + ["motionPath"] * 6
    assert index.entry("animation.gallery.entrance.fade").ooxml["buildList"] == "p:bldP/@animBg=1"


def test_a_shape_level_preset_writes_the_captured_paragraph_build():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [_effect("fx", "hero")],
                "interactiveSequences": [],
            }
        )
    )
    bld = _timing(slide).xpath(".//p:bldLst/p:bldP", namespaces=NS)
    assert len(bld) == 1 and bld[0].get("animBg") == "1"


def test_a_media_preset_gets_no_invented_paragraph_build():
    """The Play tile records no build list, so none is written. Inventing one
    would attach a text build to a shape PowerPoint never attached one to."""
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect("fx", "hero", preset={"category": "media", "effect": "mediaPlay"})
                ],
                "interactiveSequences": [],
            }
        )
    )
    timing = _timing(slide)
    assert timing.xpath(".//p:bldLst", namespaces=NS) == []
    assert timing.xpath(".//p:cmd/@cmd", namespaces=NS) == ["playFrom(0.0)"], "the effect still writes"


def test_an_explicit_behavior_list_gets_no_invented_paragraph_build():
    """A ``behaviors`` effect has no catalog entry and therefore no recorded
    build list."""
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect(
                        "fx",
                        "hero",
                        preset=None,
                        behaviors=[{"type": "color", "to": "#FF8800"}],
                    )
                ],
                "interactiveSequences": [],
            }
        )
    )
    assert _timing(slide).xpath(".//p:bldLst", namespaces=NS) == []


def test_an_explicit_request_still_animates_the_attached_shape():
    """``text.animateBackground`` is the author's own answer and overrides the
    absence of catalog evidence for that preset."""
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect(
                        "fx",
                        "hero",
                        preset={"category": "media", "effect": "mediaPlay"},
                        text={"animateBackground": True},
                    )
                ],
                "interactiveSequences": [],
            }
        )
    )
    assert _timing(slide).xpath(".//p:bldLst/p:bldP/@animBg", namespaces=NS) == ["1"]


def test_every_generated_paragraph_build_is_backed_by_the_capture(coverage, index, registry):
    """Property over the whole gallery: a ``p:bldP`` appears exactly when the
    catalog entry records one."""
    checked = 0
    for record in coverage:
        if not (record.generated and record.key.startswith("animation.gallery.")):
            continue
        entry = index.entry(record.key)
        timing = TimingWriter(registry, index=index, slide_slug="catalog").build(
            entry.semantic["animations"]
        )
        builds = timing.findall("{%s}bldLst/{%s}bldP" % (NS["p"], NS["p"]))
        assert bool(builds) is ("buildList" in entry.ooxml), record.key
        assert [node.get("animBg") for node in builds] == (["1"] if builds else [])
        checked += 1
    assert checked >= 25, "the gallery slice must stay covered"


# --- a text sequence and level cannot contradict each other ---------------


def _text_slide(**text):
    return _slide(
        animations={
            "mainSequence": [_effect("fx", "hero", text=text)],
            "interactiveSequences": [],
        }
    )


@pytest.mark.parametrize(
    "sequence,level",
    [
        ("asOneObject", "byParagraphLevel2"),
        ("asOneObject", "allParagraphLevels"),
        ("byParagraph", "allParagraphLevels"),
        ("byParagraph", "asOneObject"),
        ("allAtOnce", "byParagraphLevel1"),
        ("allAtOnce", "asOneObject"),
    ],
)
def test_a_contradicting_text_sequence_and_level_are_rejected(sequence, level):
    """One shape and group has one ``p:bldP`` and one ``@build`` value, so the
    writer cannot honour both requests. Merging them silently kept whichever
    was applied last."""
    with pytest.raises(TimingWriteError) as error:
        _build(_text_slide(sequence=sequence, level=level))
    message = str(error.value)
    assert f"mainSequence[0].text.sequence {sequence!r}" in message
    assert f"mainSequence[0].text.level {level!r}" in message
    assert "contradict each other" in message


@pytest.mark.parametrize(
    "sequence,level,build,bld_lvl",
    [
        ("byParagraph", "byParagraphLevel2", "p", "2"),
        ("byParagraph", "byParagraphLevel5", "p", "5"),
        ("allAtOnce", "allParagraphLevels", "allAtOnce", None),
        ("asOneObject", "asOneObject", None, None),
    ],
)
def test_an_agreeing_text_sequence_and_level_write_one_build(sequence, level, build, bld_lvl):
    """A level that refines its sequence agrees: ``byParagraphLevel2`` only
    adds ``@bldLvl`` to the ``build="p"`` the sequence already asks for."""
    _, slide = _build(_text_slide(sequence=sequence, level=level))
    builds = _timing(slide).xpath(".//p:bldLst/p:bldP", namespaces=NS)
    assert len(builds) == 1
    assert builds[0].get("build") == build
    assert builds[0].get("bldLvl") == bld_lvl


@pytest.mark.parametrize("field,value", [("sequence", "byParagraphs"), ("level", "byParagraphLevel6")])
def test_an_unknown_text_build_value_lists_the_catalogued_ones(field, value):
    with pytest.raises(TimingWriteError) as error:
        _build(_text_slide(**{field: value}))
    assert f"mainSequence[0].text.{field} {value!r} is not a catalogued p:bldP build value" in str(
        error.value
    )


@pytest.mark.parametrize("value", CHART_BUILDS)
def test_a_chart_build_is_not_a_paragraph_level(value):
    """The same guard in the other direction: a chart value must not reach
    ``p:bldP``."""
    with pytest.raises(TimingWriteError, match="is not a catalogued p:bldP build value"):
        _build(_text_slide(level=value))


# --- malformed effect fields are path-aware errors ------------------------


@pytest.mark.parametrize("field", ["target", "start", "timing", "afterEffect", "text", "chart", "smartArt"])
@pytest.mark.parametrize("value", [["byParagraph"], "byParagraph", 3])
def test_a_non_object_effect_field_is_a_path_aware_error(field, value):
    """``model.py`` validates the deck before a build, but the writer is its own
    boundary: a malformed field has to name its JSON path instead of raising a
    bare AttributeError or ValueError from the first field access."""
    slide_def = _slide(
        animations={
            "mainSequence": [_effect("fx", "hero", **{field: value})],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(TimingWriteError) as error:
        _build(slide_def)
    assert f"slide 'animated': mainSequence[0].{field} must be an object" in str(error.value)
    assert type(value).__name__ in str(error.value)


@pytest.mark.parametrize("field", ["text", "chart", "smartArt", "start", "afterEffect", "timing"])
def test_a_null_effect_field_means_not_requested(field):
    """``null`` is how the public JSON spells "no value", so it must keep
    building rather than become an error."""
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [_effect("fx", "hero", **{field: None})],
                "interactiveSequences": [],
            }
        )
    )
    assert _timing(slide).xpath(".//p:cTn[@presetID]", namespaces=NS)


# --- identity, ids and schema order ---------------------------------------


def test_every_ctn_id_is_unique_and_the_root_is_the_time_root():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [_effect("one", "hero"), _effect("two", "aside")],
                "interactiveSequences": [
                    {
                        "id": "seq",
                        "trigger": {"type": "onShapeClick", "target": "aside", "delayMs": 0},
                        "effects": [_effect("three", "hero")],
                    }
                ],
            }
        )
    )
    timing = _timing(slide)
    ids = timing.xpath(".//p:cTn/@id", namespaces=NS)
    assert len(ids) == len(set(ids))
    assert ids[0] == "1"
    root = timing.xpath("./p:tnLst/p:par/p:cTn", namespaces=NS)[0]
    assert (root.get("nodeType"), root.get("dur"), root.get("restart")) == ("tmRoot", "indefinite", "never")


def test_every_generated_node_uses_a_declared_ooxml_namespace():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect("chart", "hero", chart={"build": "chartByCategory"}),
                    _effect(
                        "text",
                        "aside",
                        start={"type": "withPrevious", "delayMs": 0},
                        text={"unit": "byWord", "interItemDelayPercent": 10},
                    ),
                ],
                "interactiveSequences": [],
            }
        )
    )
    timing = _timing(slide)
    namespaces = {etree.QName(node).namespace for node in timing.iter() if isinstance(node.tag, str)}
    assert namespaces == {NS["p"], NS["a"], NS["sdpm"]}
    assert etree.QName(timing).namespace == NS["p"]
    assert timing.xpath(".//a:bldChart", namespaces=NS), "DrawingML children keep the a: namespace"


def test_timing_is_inserted_before_ext_lst_and_after_the_transition():
    slide_def = _slide(
        transition={"effect": "fade", "parameters": {}, "durationMs": 700},
        animations={"mainSequence": [_effect("fx", "hero")], "interactiveSequences": []},
    )
    _, slide = _build(slide_def, transitions=True)
    order = [etree.QName(child).localname for child in _xml(slide)]
    assert order.index("AlternateContent") < order.index("timing")
    assert order[-1] == "timing"


def test_effect_ids_survive_in_a_preserved_extension():
    _, slide = _build(
        _slide(
            animations={
                "mainSequence": [_effect("show-hero", "hero"), _effect("show-aside", "aside")],
                "interactiveSequences": [],
            }
        )
    )
    timing = _timing(slide)
    ext = timing.xpath("./p:extLst/p:ext", namespaces=NS)[0]
    assert ext.get("uri") == SDPM_EFFECT_EXT_URI
    recorded = ext.xpath(".//sdpm:effect", namespaces=NS)
    assert [node.get("id") for node in recorded] == ["show-hero", "show-aside"]
    ctn_ids = set(timing.xpath(".//p:cTn[@presetID]/@id", namespaces=NS))
    assert {node.get("cTn") for node in recorded} == ctn_ids


def test_missing_effect_id_falls_back_to_the_documented_fingerprint(registry, index):
    effect = _effect("fx", "catalogTarget")
    effect.pop("id")
    writer = TimingWriter(registry, index=index, slide_slug="catalog")
    writer.build({"mainSequence": [effect], "interactiveSequences": []})
    expected = effect_fingerprint(
        sequence="mainSequence", target="catalogTarget", effect=effect, ordinal=0
    )
    assert [effect_id for effect_id, _ in writer.effect_ids] == [expected]
    assert expected == effect_fingerprint(
        sequence="mainSequence", target="catalogTarget", effect=dict(effect), ordinal=0
    )
    assert expected != effect_fingerprint(
        sequence="mainSequence", target="catalogTarget", effect=effect, ordinal=1
    )


# --- the fallback ordinal counts identical effects, not positions ----------


def _anonymous(target="catalogTarget", **patch):
    """Return an effect with no explicit ``id``, so the fallback ID is used."""
    effect = _effect("unused", target, **patch)
    effect.pop("id")
    return effect


def _registry_with(*logical_ids):
    """Return a registry holding one detached shape per logical id."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    registry = ShapeIdentityRegistry("catalog")
    for ordinal, logical_id in enumerate(logical_ids):
        shape = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(914400), Emu(914400))
        registry.register(logical_id, [shape._element], source_path=f"elements[{ordinal}]")
    return registry


def _fallback_ids(index, registry, effects):
    """Return the effect IDs the writer assigned to one main sequence."""
    writer = TimingWriter(registry, index=index, slide_slug="catalog")
    writer.build({"mainSequence": list(effects), "interactiveSequences": []})
    return [effect_id for effect_id, _ in writer.effect_ids]


def test_effect_identity_ignores_position_timing_and_trigger():
    """The identity answers one question: is this effect indistinguishable
    from that one? Position, delay and duration are not part of it."""
    first = _anonymous(start={"type": "onPageClick", "delayMs": 0}, timing={"durationMs": 500})
    second = _anonymous(start={"type": "afterPrevious", "delayMs": 250}, timing={"durationMs": 900})
    identity = dict(sequence="mainSequence", target="catalogTarget")
    assert effect_identity(effect=first, **identity) == effect_identity(effect=second, **identity)
    other_target = effect_identity(sequence="mainSequence", target="aside", effect=first)
    other_preset = effect_identity(
        **identity,
        effect=_anonymous(preset={"category": "entrance", "effect": "blinds"}),
    )
    other_sequence = effect_identity(
        sequence="interactive:details", target="catalogTarget", effect=first
    )
    assert len({effect_identity(effect=first, **identity), other_target, other_preset, other_sequence}) == 4


def test_identical_effects_are_numbered_within_their_own_group(registry, index):
    ids = _fallback_ids(index, registry, [_anonymous(), _anonymous(), _anonymous()])
    assert len(set(ids)) == 3, "three indistinguishable effects still get three IDs"
    assert ids == [
        effect_fingerprint(
            sequence="mainSequence", target="catalogTarget", effect=_anonymous(), ordinal=ordinal
        )
        for ordinal in (0, 1, 2)
    ]


def test_inserting_a_different_effect_does_not_renumber_the_following_ids(registry, index):
    """The ordinal is per identical-effect group, so an unrelated insertion
    leaves every other ID untouched — which is what makes the diff by stable ID
    usable after an edit."""
    before = _fallback_ids(index, registry, [_anonymous(), _anonymous()])
    different = _anonymous(preset={"category": "entrance", "effect": "blinds"})
    after = _fallback_ids(index, registry, [different, _anonymous(), _anonymous()])
    assert after[1:] == before
    assert after[0] not in before

    # The same holds for an insertion in the middle and for a different target.
    middle = _fallback_ids(index, registry, [_anonymous(), different, _anonymous()])
    assert [middle[0], middle[2]] == before
    pair = _registry_with("catalogTarget", "secondTarget")
    other_target = _fallback_ids(
        index, pair, [_anonymous(), _anonymous(target="secondTarget")]
    )
    assert other_target[0] == before[0] and other_target[1] not in before


def test_adding_an_identical_effect_changes_only_its_own_id(registry, index):
    before = _fallback_ids(index, registry, [_anonymous(), _anonymous()])
    after = _fallback_ids(index, registry, [_anonymous(), _anonymous(), _anonymous()])
    assert after[: len(before)] == before, "the existing duplicates keep their IDs"
    assert after[-1] not in before, "only the new duplicate gets a new ID"


def test_an_explicit_id_still_consumes_its_group_ordinal(registry, index):
    """The ordinal describes the timeline, not which effects happen to carry an
    explicit ``id``: the import side derives it from the same effect order."""
    named = _effect("show-hero", "catalogTarget")
    anonymous = _anonymous()
    ids = _fallback_ids(index, registry, [named, anonymous])
    assert ids[0] == "show-hero"
    assert ids[1] == effect_fingerprint(
        sequence="mainSequence", target="catalogTarget", effect=anonymous, ordinal=1
    )


def test_main_and_interactive_sequences_number_independently(registry, index):
    writer = TimingWriter(registry, index=index, slide_slug="catalog")
    writer.build(
        {
            "mainSequence": [_anonymous()],
            "interactiveSequences": [
                {
                    "id": "details",
                    "trigger": {"type": "onShapeClick", "target": "catalogTarget", "delayMs": 0},
                    "effects": [_anonymous()],
                }
            ],
        }
    )
    ids = [effect_id for effect_id, _ in writer.effect_ids]
    assert len(set(ids)) == 2
    assert ids[0] == effect_fingerprint(
        sequence="mainSequence", target="catalogTarget", effect=_anonymous(), ordinal=0
    )
    assert ids[1] == effect_fingerprint(
        sequence="interactive:details", target="catalogTarget", effect=_anonymous(), ordinal=0
    )


def test_generated_shapes_carry_recoverable_identity_without_touching_accessibility():
    elements = [
        {
            "id": "hero",
            "type": "textbox",
            "text": "Hero",
            "x": 10,
            "y": 10,
            "width": 300,
            "height": 60,
            "altText": "a hero banner",
        }
    ]
    builder, slide = _build(_slide(elements=elements, animations={"mainSequence": [_effect("fx", "hero")], "interactiveSequences": []}))
    spid = builder.identity_registries["animated"].resolve("hero")
    root = _xml(slide)
    node = root.xpath(f".//p:cNvPr[@id='{spid}']", namespaces=NS)[0]
    assert read_identity_extension(node.getparent().getparent()) == {"element": "hero"}
    assert node.get("title") in (None, "")
    assert node.get("descr") in (None, "")


def test_identity_metadata_leaves_existing_accessibility_text_untouched():
    """``@title`` and ``@descr`` are user accessibility text. The identity
    extension and the Morph ``!!`` name must leave both exactly as they were,
    which is only provable against real values."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    shape = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(914400), Emu(914400))
    props = next(shape._element.iter("{%s}cNvPr" % NS["p"]))
    props.set("title", "Quarterly revenue chart")
    props.set("descr", "Bar chart: revenue grew 12% quarter over quarter.")
    original_name = props.get("name")

    registry = ShapeIdentityRegistry("a11y")
    registry.register("hero", [shape._element], source_path="elements[0]", morph_id="heroShape")

    assert props.get("title") == "Quarterly revenue chart"
    assert props.get("descr") == "Bar chart: revenue grew 12% quarter over quarter."
    assert read_identity_extension(shape._element) == {"element": "hero", "morph": "heroShape"}
    # Morph correspondence is the one field that does change, and only it.
    assert props.get("name") == "!!sdpm-morph-heroShape" != original_name


def test_identity_metadata_without_a_morph_id_changes_no_shape_attribute():
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    shape = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(914400), Emu(914400))
    props = next(shape._element.iter("{%s}cNvPr" % NS["p"]))
    props.set("title", "Agenda")
    props.set("descr", "The three topics of this session.")
    before = dict(props.attrib)

    registry = ShapeIdentityRegistry("a11y")
    registry.register("hero", [shape._element], source_path="elements[0]")

    assert dict(props.attrib) == before, "identity lives in a:extLst, not in cNvPr attributes"
    assert read_identity_extension(shape._element) == {"element": "hero"}


def test_unknown_target_names_the_slide_and_the_known_ids():
    slide_def = _slide(
        animations={"mainSequence": [_effect("fx", "ghost")], "interactiveSequences": []}
    )
    with pytest.raises(TimingWriteError) as error:
        _build(slide_def)
    assert "unknown animation target 'ghost'" in str(error.value)
    assert "hero" in str(error.value)


def test_duplicate_logical_ids_after_expansion_are_rejected():
    elements = [
        {"id": "hero", "type": "textbox", "text": "A", "x": 1, "y": 1, "width": 100, "height": 30},
        {"id": "hero", "type": "textbox", "text": "B", "x": 1, "y": 40, "width": 100, "height": 30},
    ]
    with pytest.raises(IdentityError, match="duplicate element id 'hero'"):
        _build(_slide(elements=elements))


def test_a_removed_empty_placeholder_target_fails_before_output():
    slide_def = {
        "id": "animated",
        "layout": "Title and Content",
        "placeholders": {"0": {"text": "", "id": "title"}},
        "elements": [],
        "animations": {"mainSequence": [_effect("fx", "title")], "interactiveSequences": []},
    }
    with pytest.raises(TimingWriteError, match="produced no shape"):
        _build(slide_def)


def test_a_filled_placeholder_target_resolves_to_its_real_shape():
    """The other half of the documented order: identity is registered before
    filling, so a placeholder that survives still resolves to its own spid."""
    slide_def = {
        "id": "animated",
        "layout": "Title and Content",
        "placeholders": {"0": {"text": "Agenda", "id": "title"}},
        "elements": [],
        "animations": {"mainSequence": [_effect("fx", "title")], "interactiveSequences": []},
    }
    builder, slide = _build(slide_def)
    target = builder.identity_registries["animated"].target("title")
    assert target.kind == "placeholder"
    root = _xml(slide)
    assert root.xpath(f".//p:cNvPr[@id='{target.spid}']", namespaces=NS)
    assert _timing(slide).xpath(".//p:spTgt/@spid", namespaces=NS) == [str(target.spid)] * len(
        _timing(slide).xpath(".//p:spTgt", namespaces=NS)
    )


def test_multi_shape_elements_animate_their_primary_shape(tmp_path):
    """Primary target rule: the first root shape the builder appended wins."""
    from PIL import Image

    Image.new("RGB", (8, 8), "white").save(tmp_path / "pic.png")
    elements = [
        {
            "id": "diagram",
            "type": "image",
            "src": "pic.png",
            "label": "Labelled",
            "x": 10,
            "y": 10,
            "width": 200,
            "height": 120,
        }
    ]
    builder = PPTXBuilder(
        TEMPLATE,
        fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"},
        default_text_color="#FFFFFF",
        base_dir=tmp_path,
        animations_enabled=True,
    )
    slide = builder.add_slide(
        _slide(
            elements=elements,
            animations={"mainSequence": [_effect("fx", "diagram")], "interactiveSequences": []},
        )
    )
    target = builder.identity_registries["animated"].target("diagram")
    assert target.extra_spids, "the labelled image creates a picture plus a label textbox"
    assert target.spid < min(target.extra_spids), "the primary shape is created first"
    timing = _timing(slide)
    assert timing.xpath(".//p:spTgt/@spid", namespaces=NS) == [str(target.spid)] * len(
        timing.xpath(".//p:spTgt", namespaces=NS)
    )
    assert timing.xpath(".//p:bldLst/p:bldP/@spid", namespaces=NS) == [str(target.spid)]


def test_animations_disabled_writes_no_object_timing():
    slide_def = _slide(
        animations={"mainSequence": [_effect("fx", "hero")], "interactiveSequences": []}
    )
    _, slide = _build(slide_def, animations=False)
    assert _xml(slide).findall("{%s}timing" % NS["p"]) == []


def test_non_animated_slides_are_untouched():
    from sdpm.engine.timing import SDPM_IDENTITY_EXT_URI

    _, slide = _build(_slide(), animations=False, transitions=False)
    root = _xml(slide)
    assert root.findall("{%s}timing" % NS["p"]) == []
    assert root.xpath(".//*[local-name()='transition']") == []
    assert root.xpath(f".//a:ext[@uri='{SDPM_IDENTITY_EXT_URI}']", namespaces=NS) == []


# --- catalog coverage accounting -------------------------------------------


def test_every_accepted_catalog_entry_is_generated_or_explicitly_refused(coverage):
    summary = coverage_summary(coverage)
    assert summary["errors"] == [], "a non-capability failure is a writer defect"
    assert summary["total"] == CATALOG_COVERAGE["total"]
    assert summary["generated"] == CATALOG_COVERAGE["generated"]
    assert summary["refused"] == CATALOG_COVERAGE["refused"]
    assert summary["refusedWithoutGap"] == [], "nothing is refused without a recorded gap"
    assert summary["generatedDespiteGap"] == CATALOG_COVERAGE["generatedDespiteGap"]
    refusals = [record for record in coverage if record.refused]
    assert refusals, "the refusal path must stay exercised"
    assert all(record.gap_key for record in refusals), "every refusal names a catalog key"


def test_the_coverage_counts_have_a_single_definition(coverage):
    """``catalog_coverage`` is the only place that decides what counts as
    generated or refused. Every number in this file and in
    ``test_transition_writer.py`` is a slice of these records, so the two files
    cannot drift into two different answers."""
    summary = coverage_summary(coverage)
    for outcome in ("generated", "refused"):
        counts = summary[outcome]
        assert counts["guiItems"] + counts["candidates"] == counts["total"]
        assert counts["animation"] + counts["transition"] == counts["total"]
    assert summary["generated"]["total"] + summary["refused"]["total"] == summary["total"]
    assert len(coverage) == summary["total"]
    assert {record.outcome for record in coverage} == {"generated", "refused"}


def test_the_task_eight_gate_numbers_come_from_the_same_pass(coverage, index):
    """The release gate counts "capture-required refusals" and "unresolved
    native behavior payloads" separately. Both are slices of these records, so
    the gate cannot be read against a second, slightly different count.

    A refusal carries ``elements`` exactly when the entry's OOXML form *is*
    established but the values inside its behavior children are not; every
    other refusal is a missing mapping.
    """
    refused = [record for record in coverage if record.refused]
    payload = [record for record in refused if record.elements]
    mapping = [record for record in refused if not record.elements]
    assert len(refused) == CATALOG_COVERAGE["refused"]["total"]
    assert len(mapping) == CATALOG_COVERAGE["captureRequiredRefusals"]
    assert len(payload) == CATALOG_COVERAGE["payloadRefusals"]["total"]
    for group, expected in CATALOG_COVERAGE["payloadRefusals"].items():
        if group == "total":
            continue
        assert len([record for record in payload if record.group == group]) == expected
    # Every payload refusal names the unresolved children recorded by the
    # entry it resolved to, which for an enum candidate is the gallery tile it
    # mirrors rather than the candidate itself.
    assert all(
        record.elements == index.entry(record.gap_key).unresolved_payloads for record in payload
    )
    assert all(not index.entry(record.gap_key).unresolved_payloads for record in mapping)


def test_the_transition_slice_splits_into_elements_and_controls(coverage):
    """The transition entries that *choose* an element and the ones that only
    *modify* one (duration, advance, sound, Morph matching) are separated by
    their catalog strategy inside the shared pass, not by a filter that only
    one test knows about."""
    transitions = [record for record in coverage if record.kind == "transition"]
    elements = [record for record in transitions if record.strategy in TRANSITION_STRATEGIES]
    controls = [record for record in transitions if record.strategy not in TRANSITION_STRATEGIES]
    assert len(elements) + len(controls) == len(transitions)
    assert len(elements) == 214 and len(controls) == 6
    assert {record.strategy for record in controls} == {"attribute", "shapeName", "relationship"}


def test_entries_generated_despite_their_own_gap_resolve_to_a_captured_equivalent(coverage, index):
    """An entry written despite its own gap must land on a gap-free catalog
    entry, not a guess. There are none left: ``flashbulb`` was the only one,
    and the scripting-oracle capture closed its gap by writing ``p14:flash``
    for the enumerator itself, so the entry now stands on its own measurement
    instead of on the tile that happened to share its shape."""
    flashbulb = index.entry("EPPEntryEffect.entry effect flashbulb")
    assert flashbulb.gap in (None, "")
    assert flashbulb.ooxml["element"] == "p14:flash"
    assert [record.key for record in coverage if record.key == flashbulb.key and record.has_gap] == []
    checked = []
    for record in coverage:
        if not (record.generated and record.has_gap):
            continue
        semantic = index.entry(record.key).semantic
        if "transition" in semantic:
            _node, report = build_transition(semantic["transition"], index=index)
            resolved = index.entry(report["catalogKey"])
        else:
            preset = semantic["animations"]["mainSequence"][0]["preset"]
            resolved = index.preset(preset["category"], preset["effect"])
        assert resolved is not None and resolved.writable, record.key
        assert resolved.key != record.key, record.key
        assert resolved.level in {"nativeTemplate", "presetMapping"}, record.key
        checked.append(record.key)
    assert checked == CATALOG_COVERAGE["generatedDespiteGap"]


def test_the_unresolved_behavior_payload_surface_is_counted_and_refused(coverage, index):
    """All 95 gallery tiles are reproducible, and this test used to say 24 were.

    The native fixtures listed which behaviour children PowerPoint wrote and not
    what they said, so 71 tiles recorded an unresolved payload and were refused.
    The 2026-11-01 GUI capture measured all of them from the package PowerPoint
    saved, so none is refused and no tile names an unresolved child.

    ``behavior_payloads`` still lists ``p:anim`` and friends as unresolved, and
    that is not a contradiction: it is the **general** rule for an entry with no
    measured behaviours of its own, which is what the 11 remaining enum
    candidates fall back on.
    """
    tiles = [
        record
        for record in coverage
        if record.key.startswith(
            ("animation.gallery.entrance.", "animation.gallery.exit.", "animation.gallery.emphasis.")
        )
    ]
    reproducible = [record for record in tiles if record.generated]
    refused = [record for record in tiles if record.refused]
    elements: dict[str, int] = {}
    for record in refused:
        unresolved = index.entry(record.key).unresolved_payloads
        assert record.gap_key == record.key
        assert record.elements == unresolved
        for tag in unresolved:
            elements[tag] = elements.get(tag, 0) + 1
    assert [record.key for record in reproducible if index.entry(record.key).unresolved_payloads] == []
    assert len(reproducible) == GALLERY_PAYLOADS["reproducible"]
    assert len(refused) == GALLERY_PAYLOADS["refused"]
    assert len(tiles) == GALLERY_PAYLOADS["tiles"]
    assert elements == GALLERY_PAYLOADS["unresolvedElements"]
    payloads = index.behavior_payloads
    assert set(payloads["resolved"]) == {"p:set", "p:animEffect", "p:cmd"}
    assert set(payloads["unresolved"]) == {"p:anim", "p:animMotion", "p:animScale", "p:animRot", "p:animClr"}
    assert payloads["capabilityLevel"] == "presetMapping"
    assert payloads["verification"] == "powerPointReadBackRequired"
    assert "only when every behavior child it records appears under resolved" in payloads["writerRule"]


def test_no_refused_preset_leaves_a_partial_node_behind(registry, index):
    """A refusal happens before anything is attached to the slide, so a
    half-written behavior can never reach the package.

    No catalog entry reaches this path any more: the GUI capture measured all
    95 gallery tiles, and the 11 enum candidates that still record an
    unresolved payload resolve by preset identity to one of those measured
    tiles, so writing their semantic JSON succeeds. The mechanism is still
    there and still has to be covered — an entry can go back to being
    payload-refused — so it is exercised against a fabricated entry rather than
    against a catalog key that no longer refuses, which would have made this
    test pass by writing something.
    """
    import copy

    patched = copy.copy(index)
    patched.items = dict(index.items)
    patched.items["animation.gallery.entrance.flyIn"] = CapabilityEntry(
        key="animation.gallery.entrance.flyIn",
        status="accepted",
        level="nativeTemplate",
        ooxml={
            "strategy": "preset",
            "element": "p:cTn",
            "presetClass": "entr",
            "presetId": 2,
            "presetSubtype": 4,
            # The measured behaviours are gone, which is what a payload refusal
            # is: the children are known and their values are not.
            "behaviorChildren": ["p:anim", "p:set"],
            "unresolvedPayloads": ["p:anim"],
            "requiresCapture": True,
            "gap": "the value payload of p:anim is not captured",
        },
        semantic={},
        group="guiItems",
    )
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    shape = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(914400), Emu(914400))
    local = ShapeIdentityRegistry("catalog")
    local.register("hero", [shape._element], source_path="elements[0]")
    with pytest.raises(CapabilityGapError):
        write_slide_timing(
            slide._element,
            {
                "id": "catalog",
                "animations": {
                    "mainSequence": [
                        _effect("fx", "hero", preset={
                            "category": "entrance", "effect": "flyIn", "variant": None,
                        })
                    ],
                    "interactiveSequences": [],
                },
            },
            local,
            index=patched,
        )
    assert slide._element.xpath(".//*[local-name()='timing']") == []


def test_every_accepted_animation_preset_resolves_to_a_captured_identifier(index):
    """Every gallery tile has a captured presetID and class. Writability is
    exactly the absence of a recorded unresolved payload: nothing is refused
    without a catalog reason, and nothing with one is written."""
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    gallery = [
        entry
        for entry in catalog["guiItems"]
        if entry["key"].startswith(("animation.gallery.entrance.", "animation.gallery.exit.", "animation.gallery.emphasis."))
    ]
    assert len(gallery) == GALLERY_PAYLOADS["tiles"]
    for entry in gallery:
        preset = entry["semanticJson"]["animations"]["mainSequence"][0]["preset"]
        resolved = index.entry(entry["key"])
        assert resolved.ooxml["presetId"] is not None
        assert resolved.ooxml["presetClass"] in {"entr", "exit", "emph"}
        assert resolved.writable is not bool(entry["ooxml"].get("unresolvedPayloads"))
        if resolved.writable:
            assert index.preset(preset["category"], preset["effect"]).key == entry["key"]
        else:
            with pytest.raises(CapabilityGapError):
                index.preset(preset["category"], preset["effect"])


# --- the catalog index -----------------------------------------------------


def test_the_catalog_is_parsed_once_and_indexed_for_lookup():
    before = capability_cache_info()
    index = load_capability_index()
    for _ in range(200):
        load_capability_index().preset("entrance", "fade")
    after = capability_cache_info()
    assert after.misses == before.misses or after.misses == before.misses + 1
    assert after.hits >= before.hits + 200
    # Indexed, not scanned: the lookup maps are built once at construction.
    assert len(index.items) == 293
    assert len(index.candidates) == 435
    assert index.entry("animation.gallery.entrance.fade") is index.items["animation.gallery.entrance.fade"]
    assert default_catalog_path().stat().st_size > 1_000_000


def test_the_writer_never_calls_powerpoint_or_the_network():
    sources = [
        (REPO_ROOT / "sdpm/sdpm/engine/timing/writer.py").read_text(encoding="utf-8"),
        (REPO_ROOT / "sdpm/sdpm/engine/timing/transition.py").read_text(encoding="utf-8"),
        (REPO_ROOT / "sdpm/sdpm/engine/timing/identity.py").read_text(encoding="utf-8"),
    ]
    for source in sources:
        for forbidden in (
            "import socket",
            "import subprocess",
            "import urllib",
            "import requests",
            "osascript",
            "AppleScript",
            "applescript",
        ):
            assert forbidden not in source


def test_the_writer_does_not_use_destructive_python_pptx_timing_helpers():
    sources = list((REPO_ROOT / "sdpm" / "sdpm" / "engine" / "timing").glob("*.py"))
    sources.append(REPO_ROOT / "sdpm" / "sdpm" / "engine" / "builder" / "__init__.py")
    for path in sources:
        text = path.read_text(encoding="utf-8")
        # Call sites only: the module docstrings name the helper to explain why
        # it is avoided.
        for destructive in ("get_or_add_childTnLst(", "get_or_add_timing(", "_add_childTnLst("):
            assert destructive not in text, f"{path.name} calls {destructive}"


def test_write_slide_timing_reports_what_it_wrote(registry, index):
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    shape = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(914400), Emu(914400))
    registry = ShapeIdentityRegistry("report")
    registry.register("hero", [shape._element], source_path="elements[0]")
    report = write_slide_timing(
        slide._element,
        {"id": "report", "animations": {"mainSequence": [_effect("fx", "hero")], "interactiveSequences": []}},
        registry,
        index=index,
    )
    assert report["timing"] is True
    assert report["effects"] == 1
    assert report["effectIds"] == ["fx"]
    assert report["mediaNodes"] == 0
    assert report["maxCTnId"] >= 5
    assert "gaps" not in report, "a capability gap raises; it is never reported as a warning"


def test_a_slide_without_animations_never_parses_the_catalog(monkeypatch):
    """An ordinary deck must not pay for the 1.2 MB capability catalog."""
    from sdpm.engine.timing import writer as writer_module

    def explode():  # pragma: no cover - the point is that it is never called
        raise AssertionError("the catalog was parsed for a non-animated slide")

    monkeypatch.setattr(writer_module, "load_capability_index", explode)
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    report = write_slide_timing(
        slide._element, {"id": "plain"}, ShapeIdentityRegistry("plain"), animations_enabled=False
    )
    assert report["timing"] is False
    assert report["catalogLoaded"] is False


def test_the_writer_loads_the_catalog_only_when_it_needs_a_value(index):
    writer = TimingWriter(ShapeIdentityRegistry("plain"), slide_slug="plain")
    assert writer.catalog_loaded is False
    assert writer.build(None) is None
    assert writer.catalog_loaded is False, "an empty timeline needs no catalog lookup"
    assert index is not None


def test_an_unimplemented_feature_stays_refused_after_its_catalog_gap_closes(index):
    """``animation.sequence.main`` has no catalog gap at all, yet
    :func:`refuse_unimplemented` still refuses: closing a gap must not silently
    enable a feature whose writer support does not exist."""
    assert index.items["animation.sequence.main"].writable
    with pytest.raises(CapabilityGapError) as error:
        refuse_unimplemented(index, "animation.sequence.main", "a feature", "the writer cannot do it")
    assert error.value.key == "animation.sequence.main"
    assert "not implemented by the writer" in str(error.value)
    assert "refuses to approximate" in str(error.value)


def test_effect_sound_is_refused_because_no_relationship_is_created(index):
    slide_def = _slide(
        animations={
            "mainSequence": [
                _effect("fx", "hero", sound={"src": "audio/click.wav", "mediaType": "audio/wav"})
            ],
            "interactiveSequences": [],
        }
    )
    with pytest.raises(CapabilityGapError) as error:
        _build(slide_def)
    assert error.value.key == "animation.sound.effect"
    assert index is not None


def test_slides_without_an_id_get_their_own_identity_registry():
    """Keying every unnamed slide as "" would discard the earlier registry and
    with it every animation target the earlier slide resolved."""
    builder = PPTXBuilder(
        TEMPLATE,
        fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"},
        default_text_color="#FFFFFF",
        base_dir=REPO_ROOT,
        animations_enabled=True,
    )
    for _ in range(2):
        builder.add_slide(
            {
                "layout": "Blank",
                "elements": [
                    {"id": "hero", "type": "textbox", "text": "Hero", "x": 10, "y": 10,
                     "width": 200, "height": 50}
                ],
                "animations": {"mainSequence": [_effect("fx", "hero")], "interactiveSequences": []},
            }
        )
    assert len(builder.identity_registries) == 2
    assert len({id(value) for value in builder.identity_registries.values()}) == 2
    assert all("hero" in value for value in builder.identity_registries.values())


def test_repeated_slide_slugs_each_keep_their_registry():
    builder = PPTXBuilder(
        TEMPLATE,
        fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"},
        default_text_color="#FFFFFF",
        base_dir=REPO_ROOT,
        animations_enabled=True,
    )
    for _ in range(2):
        builder.add_slide(_slide(animations={"mainSequence": [_effect("fx", "hero")], "interactiveSequences": []}))
    assert len(builder.identity_registries) == 2
    assert "animated" in builder.identity_registries


# --- the API facade passes the resolved switches to the builder ------------


def _deck(tmp_path, *, animations=None, transitions=None):
    deck = tmp_path / "deck"
    (deck / "slides").mkdir(parents=True)
    (deck / "specs").mkdir()
    config = {
        "template": "blank-dark.pptx",
        "fonts": {"fullwidth": "Meiryo", "halfwidth": "Arial"},
        "defaultTextColor": "#FFFFFF",
    }
    if animations is not None:
        config["animations"] = {"enabled": animations}
    if transitions is not None:
        config["transitions"] = {"enabled": transitions}
    (deck / "deck.json").write_text(json.dumps(config), encoding="utf-8")
    (deck / "specs" / "outline.md").write_text("- [motion] Motion\n", encoding="utf-8")
    (deck / "slides" / "motion.json").write_text(
        json.dumps(
            {
                "layout": "Blank",
                "elements": [
                    {"id": "hero", "type": "textbox", "text": "Hero", "x": 100, "y": 100,
                     "width": 800, "height": 80, "fontSize": 28}
                ],
                "transition": {"effect": "fade", "parameters": {}, "durationMs": 700},
                "animations": {"mainSequence": [_effect("fx", "hero")], "interactiveSequences": []},
            }
        ),
        encoding="utf-8",
    )
    return deck


def _package_slide(path):
    from pptx import Presentation as _Presentation

    slide = list(_Presentation(str(path)).slides)[0]
    return etree.fromstring(etree.tostring(slide._element))


@pytest.mark.parametrize(
    "animations,transitions,expect_timing,expect_transition",
    [(True, True, True, True), (True, False, True, False), (False, True, False, True), (False, False, False, False)],
)
def test_build_config_switches_reach_the_builder(tmp_path, animations, transitions, expect_timing, expect_transition):
    from sdpm.api import _resolve_config, generate

    deck = _deck(tmp_path, animations=animations, transitions=transitions)
    config = _resolve_config(deck)
    assert (config.animations_enabled, config.transitions_enabled) == (animations, transitions)
    result = generate(deck, output_path=tmp_path / f"deck-{animations}-{transitions}.pptx")
    root = _package_slide(result["output_path"])
    assert bool(root.findall("{%s}timing" % NS["p"])) is expect_timing
    assert bool(root.xpath(".//*[local-name()='transition']")) is expect_transition


def test_a_deck_without_switches_still_builds_as_before(tmp_path):
    from sdpm.api import generate

    deck = _deck(tmp_path)
    result = generate(deck, output_path=tmp_path / "legacy.pptx")
    root = _package_slide(result["output_path"])
    assert root.findall("{%s}timing" % NS["p"]) == []
    assert root.xpath(".//*[local-name()='transition']") == []


def test_caller_overrides_beat_the_deck_switches(tmp_path):
    from sdpm.api import generate

    deck = _deck(tmp_path, animations=False, transitions=False)
    on = generate(deck, output_path=tmp_path / "on.pptx", animation_mode="on", transition_mode="on")
    root = _package_slide(on["output_path"])
    assert root.findall("{%s}timing" % NS["p"])
    assert root.xpath(".//*[local-name()='transition']")

    deck = _deck(tmp_path / "second", animations=True, transitions=True)
    off = generate(deck, output_path=tmp_path / "off.pptx", animation_mode="off", transition_mode="off")
    root = _package_slide(off["output_path"])
    assert root.findall("{%s}timing" % NS["p"]) == []
    assert root.xpath(".//*[local-name()='transition']") == []


def test_generate_fails_on_a_capability_gap_instead_of_warning(tmp_path):
    """A gap must stop generation, not land in ``result["warnings"]`` beside a
    package that quietly lost the requested effect."""
    from sdpm.api import generate

    deck = _deck(tmp_path, animations=True, transitions=False)
    slide = json.loads((deck / "slides" / "motion.json").read_text(encoding="utf-8"))
    # Was Fly In, which the GUI capture measured and the writer now emits. A
    # custom motion path is still capture-required — its geometry comes from the
    # author, not from a preset — so it is what the refusal is tested through.
    slide["animations"]["mainSequence"][0]["preset"] = {
        "category": "motionPath",
        "effect": "custom",
        "variant": None,
    }
    (deck / "slides" / "motion.json").write_text(json.dumps(slide), encoding="utf-8")
    output = tmp_path / "gapped.pptx"
    with pytest.raises(CapabilityGapError) as error:
        generate(deck, output_path=output)
    assert error.value.key == "animation.gallery.motionPath.custom"
    assert not output.exists(), "no package is published for a refused effect"


def test_generate_succeeds_for_a_fully_captured_effect(tmp_path):
    from sdpm.api import generate

    deck = _deck(tmp_path, animations=True, transitions=True)
    result = generate(deck, output_path=tmp_path / "captured.pptx")
    assert result["warnings"] == [] or all("animation" not in w for w in result["warnings"])
    root = _package_slide(result["output_path"])
    timing = root.findall("{%s}timing" % NS["p"])
    assert len(timing) == 1
    assert timing[0].xpath(".//p:animEffect/@filter", namespaces=NS) == ["fade"]


def test_an_exit_tile_needs_no_duration_whether_or_not_an_option_is_asked_for():
    """One effect must not have two requirements decided by an unrelated field.

    Wipe (Exit) rejected a plain write while **the same effect with an option**
    wrote happily: the option supplied measured behaviours and the plain form
    had to synthesise them, and only the synthesised path needs a duration to
    place the visibility `p:set`. So whether `timing.durationMs` was required
    depended on whether `options` happened to be present.

    Eight exit tiles behaved that way. Nothing new had to be measured to fix
    it, because pressing a setting's default leaves the effect at the tile's
    default — so the default option's behaviours **are** the tile's, and were
    lifted into it.
    """
    for preset in (
        {"category": "exit", "effect": "wipe"},
        {"category": "exit", "effect": "wipe", "options": {"direction": "fromLeft"}},
        {"category": "exit", "effect": "blinds"},
        {"category": "exit", "effect": "wheel", "options": {"spokes": "spokes4"}},
    ):
        _builder, slide = _build(
            _slide(
                animations={
                    "mainSequence": [_effect("fx", "hero", preset=preset, timing={})],
                    "interactiveSequences": [],
                }
            )
        )
        hidden = _timing(slide).xpath(".//p:set/p:to/p:strVal/@val", namespaces=NS)
        assert hidden == ["hidden"], f"{preset} wrote {hidden}"


def test_a_lifted_tile_keeps_the_duration_its_option_was_measured_at():
    """A lifted tile becomes scalable, which is half the point of lifting it.

    Before, these tiles recorded no `measuredDurationMs`, so asking for a
    duration was refused as unscalable. The option the behaviours came from was
    captured at a known duration, and that duration comes with them.
    """
    _builder, slide = _build(
        _slide(
            animations={
                "mainSequence": [
                    _effect(
                        "fx", "hero",
                        preset={"category": "exit", "effect": "wipe"},
                        timing={"durationMs": 1000},
                    )
                ],
                "interactiveSequences": [],
            }
        )
    )
    # Measured at 500 ms, asked for 1000, so the animated behaviour doubles
    # while the visibility `p:set` keeps its 1 ms and has its delay recomputed.
    durations = _timing(slide).xpath(
        ".//p:animEffect/p:cBhvr/p:cTn/@dur", namespaces=NS
    )
    assert durations == ["1000"], durations