# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Morph identity and variant generation.

Task 1 proved the package contract: Microsoft's ``!!`` Selection Pane naming
convention forces deterministic object correspondence, and PowerPoint persists
Morph as ``mc:AlternateContent/mc:Choice[@Requires='p159']`` with a
``p159:morph`` option and a ``p:fade`` fallback. These tests hold the generic
writer to that contract, prove all three variants, and prove that the identity
never overwrites accessibility text or allows an ambiguous same-slide match.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation

from sdpm.engine.builder import PPTXBuilder
from sdpm.engine.timing import (
    MORPH_NAME_PREFIX,
    IdentityError,
    build_transition,
    load_capability_index,
    morph_id_from_shape_name,
    morph_shape_name,
    read_identity_extension,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "sdpm" / "templates" / "blank-dark.pptx"
SPIKE_MANIFEST = REPO_ROOT / "tests" / "fixtures" / "animations" / "morph-spike" / "manifest.json"
CATALOG_PATH = REPO_ROOT / "sdpm" / "references" / "catalogs" / "powerpoint-animation-catalog.json"
NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
    "p159": "http://schemas.microsoft.com/office/powerpoint/2015/09/main",
}
VARIANTS = ("byObject", "byWord", "byChar")


def _element(element_id, morph_id=None, *, x=10, text="Hero", **patch):
    value = {"id": element_id, "type": "shape", "shape": "rect", "x": x, "y": 10,
             "width": 200, "height": 100, "text": text}
    if morph_id is not None:
        value["morphId"] = morph_id
    value.update(patch)
    return value


def _slide(slug, elements, transition=None):
    slide = {"id": slug, "layout": "Blank", "elements": elements}
    if transition is not None:
        slide["transition"] = transition
    return slide


def _builder(**kwargs):
    return PPTXBuilder(
        TEMPLATE,
        fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"},
        default_text_color="#FFFFFF",
        transitions_enabled=kwargs.pop("transitions", True),
        animations_enabled=kwargs.pop("animations", False),
    )


def _xml(slide):
    return etree.fromstring(etree.tostring(slide._element))


def _morph(variant, duration=2000):
    return {
        "effect": "morph",
        "parameters": {"variant": variant},
        "durationMs": duration,
        "advance": {"onClick": True, "afterMs": None},
        "sound": None,
    }


# --- the name convention ---------------------------------------------------


def test_the_forced_name_matches_the_documented_convention():
    assert morph_shape_name("hero") == "!!sdpm-morph-hero"
    assert morph_shape_name("hero").startswith(MORPH_NAME_PREFIX)
    assert morph_id_from_shape_name("!!sdpm-morph-hero") == "hero"
    assert morph_id_from_shape_name("Rectangle 3") is None


def test_the_convention_agrees_with_the_task_one_spike():
    manifest = json.loads(SPIKE_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["identity"]["powerPointName"] == morph_shape_name(manifest["identity"]["jsonMorphId"])
    assert manifest["identity"]["sameSlideDuplicates"] == "invalid"
    assert manifest["transition"]["choiceRequires"] == "p159"
    assert manifest["transition"]["fallback"] == "fade"


@pytest.mark.parametrize("bad", ["", "   ", None, 42])
def test_an_unusable_morph_id_is_rejected(bad):
    with pytest.raises(IdentityError):
        morph_shape_name(bad)


def test_a_morph_id_must_not_repeat_powerpoints_prefix():
    with pytest.raises(IdentityError, match="must not include"):
        morph_shape_name("!!hero")


# --- the three variants ----------------------------------------------------


@pytest.mark.parametrize("variant", VARIANTS)
def test_every_morph_variant_is_generated_in_the_p159_choice(variant):
    builder = _builder()
    slide = builder.add_slide(
        _slide("destination", [_element("hero", "hero")], _morph(variant))
    )
    root = _xml(slide)
    alternate = root.xpath("./mc:AlternateContent", namespaces=NS)
    assert len(alternate) == 1
    # The Choice carries p159:morph *and* p14:dur, so it requires both.
    choice = alternate[0].xpath("./mc:Choice[@Requires='p14 p159']", namespaces=NS)
    assert len(choice) == 1
    morph = choice[0].xpath("./p:transition/p159:morph", namespaces=NS)
    assert [node.get("option") for node in morph] == [variant]
    assert choice[0].xpath("./p:transition/@p14:dur", namespaces=NS) == ["2000"]
    assert alternate[0].xpath("./mc:Fallback/p:transition/p:fade", namespaces=NS)
    assert builder.transition_reports[-1]["capabilityLevel"] in {"nativeTemplate", "presetMapping"}


def test_a_morph_choice_declares_every_namespace_it_uses():
    """``mc:Choice/@Requires`` is a prefix *list*. A Morph Choice that also
    carries a millisecond duration uses ``p159:morph`` and ``p14:dur``, so
    naming only the element's own namespace would leave a p159-aware reader
    with an undeclared p14 attribute."""
    node, report = build_transition(_morph("byObject", 2000))
    assert report["requiresTokens"] == ["p14", "p159"]
    assert report["requires"] == "p14 p159"
    choice = node.xpath("./mc:Choice", namespaces=NS)[0]
    assert sorted(choice.get("Requires").split()) == ["p14", "p159"]
    assert choice.xpath("./p:transition/@p14:dur", namespaces=NS) == ["2000"]
    assert choice.xpath("./p:transition/p159:morph", namespaces=NS)
    # Every token is a namespace the catalog records support for.
    supported = {row["requires"] for row in load_capability_index().alternate_content["supported"]}
    assert set(report["requiresTokens"]) <= supported


def test_a_morph_without_a_duration_requires_only_its_own_namespace():
    """The extra prefix is a consequence of the duration, not of Morph."""
    transition = _morph("byObject")
    transition["durationMs"] = None
    node, report = build_transition(transition)
    assert report["requiresTokens"] == ["p159"]
    assert node.xpath("./mc:Choice/@Requires", namespaces=NS) == ["p159"]
    assert node.xpath(".//p:transition/@p14:dur", namespaces=NS) == []


def test_the_morph_default_duration_needs_no_duration_namespace():
    """2000 ms is the captured Morph default, but the captured legacy bucket
    (``spd="slow"``) is 1000 ms, so the duration is still explicit."""
    index = load_capability_index()
    entry = index.entry("transition.gallery.morph")
    assert (entry.ooxml["defaultDurationMs"], entry.ooxml["legacySpeed"]) == (2000, "slow")
    _node, report = build_transition(_morph("byObject", 2000))
    assert report["durationMs"] == 2000
    assert "p14" in report["requiresTokens"]


@pytest.mark.parametrize("variant", VARIANTS)
def test_each_variant_resolves_to_its_own_catalog_entry(variant):
    _node, report = build_transition(_morph(variant))
    entry = load_capability_index().entry(report["catalogKey"])
    assert entry.semantic["transition"]["parameters"]["variant"] == variant
    assert entry.ooxml["element"] == "p159:morph"
    assert entry.ooxml["requires"] == "p159"


def test_an_unknown_morph_variant_is_rejected():
    from sdpm.engine.timing import TransitionWriteError

    with pytest.raises(TransitionWriteError, match="does not support parameters"):
        build_transition(_morph("byName"))


def test_the_catalog_accepts_exactly_the_three_variants():
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    variants = {
        entry["semanticJson"]["transition"]["parameters"]["variant"]
        for entry in catalog["candidates"]
        if entry["enumerator"].startswith("entry effect morph")
    }
    assert variants == set(VARIANTS)


# --- identity on the shapes ------------------------------------------------


def test_the_morph_id_renames_the_shape_without_touching_accessibility():
    builder = _builder()
    slide = builder.add_slide(
        _slide(
            "source",
            [_element("hero", "hero", altText="A hero shape"), _element("plain", None, x=400)],
        )
    )
    root = _xml(slide)
    names = root.xpath(".//p:cNvPr/@name", namespaces=NS)
    assert "!!sdpm-morph-hero" in names
    morphed = root.xpath(".//p:cNvPr[@name='!!sdpm-morph-hero']", namespaces=NS)[0]
    assert morphed.get("title") in (None, "")
    # A shape without morphId keeps whatever name python-pptx generated.
    assert not any(name.startswith(MORPH_NAME_PREFIX) for name in names if name != "!!sdpm-morph-hero")


def test_the_morph_name_replaces_only_the_name_not_the_accessibility_text():
    """``@name`` is the Morph correspondence surface; ``@title`` and ``@descr``
    are user accessibility text and must survive the rename untouched."""
    from sdpm.engine.timing import ShapeIdentityRegistry

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    shape = slide.shapes.add_textbox(0, 0, 914400, 914400)
    props = next(shape._element.iter("{%s}cNvPr" % NS["p"]))
    props.set("title", "Revenue tile")
    props.set("descr", "A rounded tile that moves across the two slides.")

    registry = ShapeIdentityRegistry("source")
    registry.register("hero", [shape._element], source_path="elements[0]", morph_id="hero")

    assert props.get("name") == "!!sdpm-morph-hero"
    assert props.get("title") == "Revenue tile"
    assert props.get("descr") == "A rounded tile that moves across the two slides."
    assert read_identity_extension(shape._element) == {"element": "hero", "morph": "hero"}


def test_the_logical_id_and_the_morph_id_are_separate_surfaces():
    builder = _builder(animations=True)
    slide = builder.add_slide(_slide("source", [_element("hero", "heroShape")]))
    root = _xml(slide)
    props = root.xpath(".//p:cNvPr[@name='!!sdpm-morph-heroShape']", namespaces=NS)[0]
    identity = read_identity_extension(props.getparent().getparent())
    assert identity == {"element": "hero", "morph": "heroShape"}


def test_a_duplicate_morph_id_on_one_slide_is_rejected():
    builder = _builder()
    with pytest.raises(IdentityError, match="duplicate morphId 'hero'"):
        builder.add_slide(
            _slide("source", [_element("a", "hero"), _element("b", "hero", x=400)])
        )


def test_the_same_morph_id_on_different_slides_is_the_matching_contract():
    builder = _builder()
    source = builder.add_slide(_slide("source", [_element("hero", "hero", x=10)]))
    destination = builder.add_slide(
        _slide("destination", [_element("hero", "hero", x=400)], _morph("byObject"))
    )
    for slide in (source, destination):
        assert "!!sdpm-morph-hero" in _xml(slide).xpath(".//p:cNvPr/@name", namespaces=NS)
    assert builder.identity_registries["source"].morph_names() == {"!!sdpm-morph-hero": "elements[0]"}
    assert builder.identity_registries["destination"].morph_names() == {"!!sdpm-morph-hero": "elements[0]"}
    # The source slide carries no transition: a transition describes its own
    # slide's entry, so only the destination has one.
    assert _xml(source).xpath(".//*[local-name()='transition']") == []
    assert _xml(destination).xpath(".//*[local-name()='transition']")


def test_morph_without_a_morph_id_invents_no_match():
    builder = _builder()
    slide = builder.add_slide(_slide("destination", [_element("hero")], _morph("byObject")))
    names = _xml(slide).xpath(".//p:cNvPr/@name", namespaces=NS)
    assert not any(name.startswith(MORPH_NAME_PREFIX) for name in names)
    assert _xml(slide).xpath(".//p159:morph/@option", namespaces=NS) == ["byObject"]


def test_morph_identity_is_not_written_when_transitions_are_disabled():
    builder = _builder(transitions=False, animations=False)
    slide = builder.add_slide(_slide("source", [_element("hero", "hero")]))
    names = _xml(slide).xpath(".//p:cNvPr/@name", namespaces=NS)
    assert not any(name.startswith(MORPH_NAME_PREFIX) for name in names)


# --- the saved package -----------------------------------------------------


def test_the_saved_package_keeps_one_transition_in_schema_order(tmp_path):
    builder = _builder()
    builder.add_slide(_slide("source", [_element("hero", "hero", x=10)]))
    builder.add_slide(_slide("destination", [_element("hero", "hero", x=500)], _morph("byWord", 800)))
    out = tmp_path / "morph.pptx"
    builder.save(out)

    reopened = Presentation(str(out))
    slides = list(reopened.slides)
    assert len(slides) == 2
    source, destination = (etree.fromstring(etree.tostring(s._element)) for s in slides)
    assert source.xpath(".//*[local-name()='transition']") == []
    children = [etree.QName(child).localname for child in destination]
    assert children == ["cSld", "clrMapOvr", "AlternateContent"]
    assert destination.xpath(".//p159:morph/@option", namespaces=NS) == ["byWord"]
    assert destination.xpath(".//mc:Fallback/p:transition/p:fade", namespaces=NS)
    assert destination.xpath(".//p:cNvPr[@name='!!sdpm-morph-hero']", namespaces=NS)
    # Exactly one effective representation survived the save.
    assert len(destination.xpath(".//*[local-name()='transition']")) == 2  # Choice + Fallback
    assert len(destination.xpath("./mc:AlternateContent", namespaces=NS)) == 1


def test_the_morph_identity_survives_a_save_and_reload(tmp_path):
    builder = _builder(animations=True)
    builder.add_slide(_slide("source", [_element("hero", "hero")]))
    out = tmp_path / "identity.pptx"
    builder.save(out)
    reopened = Presentation(str(out))
    root = etree.fromstring(etree.tostring(list(reopened.slides)[0]._element))
    props = root.xpath(".//p:cNvPr[@name='!!sdpm-morph-hero']", namespaces=NS)
    assert len(props) == 1
    assert read_identity_extension(props[0].getparent().getparent()) == {
        "element": "hero",
        "morph": "hero",
    }
