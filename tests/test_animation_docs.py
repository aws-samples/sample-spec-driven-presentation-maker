# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The optional `animations` guide: discoverable, complete against the engine, and
conditionally loaded so ordinary composer context does not grow.

Every expectation here is **derived** from the engine and the generated capability
catalog rather than from a list copied into the test, so the contract growing (a new
validated field, a preset whose PowerPoint capture closes, a refusal that lifts) fails
these tests until the guide says so too.
"""

import ast
import re
from pathlib import Path

import pytest

from sdpm import tools as contract
from sdpm.engine.timing import model
from sdpm.engine.timing.writer import (
    CHART_BUILD,
    SMARTART_BUILD,
    TEXT_LEVEL_BUILD,
    TEXT_SEQUENCE_BUILD,
    CapabilityGapError,
    TimingWriteError,
    load_capability_index,
)
from sdpm.knowledge.reference import list_category

_ROOT = Path(__file__).resolve().parents[1]
_REFERENCES = _ROOT / "sdpm" / "references"
_GUIDES = _REFERENCES / "guides"
_WORKFLOWS = _REFERENCES / "workflows"

_GUIDE_NAME = "animations"
_GUIDE_PATH = _GUIDES / f"{_GUIDE_NAME}.md"
_SPEC_PATH = _GUIDES / "slide-json-spec.md"

#: The only motion field names the always-loaded slide spec may mention. Everything
#: else the engine validates belongs in the optional guide, so a field added to the
#: contract lands in the forbidden set by default.
_SPEC_MAY_NAME = frozenset(
    {"animations", "transitions", "transition", "enabled", "id", "morphId", "elements", "placeholders"}
)

#: Catalog key prefixes that name a gallery tile or an effect direction. Those are
#: enumerated as tables/prose in the guide rather than key by key.
_BULK_KEY_PREFIXES = (
    "animation.gallery.",
    "transition.gallery.",
    "transition.standardElement.",
    "animation.effectOptions.direction.",
)


@pytest.fixture(scope="module")
def guide() -> str:
    return _GUIDE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index():
    return load_capability_index()


def _public_json_fields() -> set[str]:
    """Return the public JSON field names ``model.py`` validates.

    ``model.py`` is the frozen public contract (the writer's own docstring says so),
    so its ``.get("field")`` lookups and the key tuples it iterates are the field
    list, read out of the source instead of retyped here.
    """
    tree = ast.parse(_ROOT.joinpath("sdpm/sdpm/engine/timing/model.py").read_text(encoding="utf-8"))
    identifier = re.compile(r"^_?[a-z][A-Za-z0-9]*$")
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            names.add(node.args[0].value)
        if isinstance(node, (ast.Tuple, ast.List)):
            names.update(
                element.value
                for element in node.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            )
    return {name for name in names if identifier.match(name)}


def _validated_vocabulary() -> dict[str, frozenset[str]]:
    """Return every enumeration the model validates a public value against."""
    return {
        name: value
        for name, value in vars(model).items()
        if isinstance(value, frozenset) and name.isupper() and all(isinstance(v, str) for v in value)
    }


def _writable_presets(index) -> dict[str, set[str]]:
    """Return the preset names the writer can actually generate, per category."""
    writable: dict[str, set[str]] = {}
    for category in sorted(model.ANIMATION_CATEGORIES):
        names = set()
        for name in index.preset_names(category):
            try:
                index.preset(category, name)
            except (CapabilityGapError, TimingWriteError):
                continue
            names.add(name)
        writable[category] = names
    return writable


def _table_row_tokens(text: str, first_cell: str) -> set[str]:
    """Return the backticked tokens of the markdown table row keyed by ``first_cell``."""
    pattern = re.compile(r"^\|\s*`" + re.escape(first_cell) + r"`\s*\|(.*)\|\s*$", re.MULTILINE)
    match = pattern.search(text)
    assert match, f"the guide has no table row for `{first_cell}`"
    return set(re.findall(r"`([^`]+)`", match.group(1)))


def _first_column_tokens(text: str, heading: str) -> set[str]:
    """Return the backticked first-column token of every row under one heading."""
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    section = text[start : end if end != -1 else len(text)]
    return {
        match.group(1)
        for match in re.finditer(r"^\|\s*`([^`]+)`\s*\|", section, re.MULTILINE)
    }


# --- discoverability --------------------------------------------------------
class TestDiscoverable:
    """The guide is reached exactly like every other guide: no new mechanism."""

    def test_read_guides_serves_it(self):
        result = contract.read_guides([_GUIDE_NAME])
        assert len(result["documents"]) == 1
        document = result["documents"][0]
        assert document["name"] == _GUIDE_NAME
        assert document["content"].strip()
        # Frontmatter is stripped by the same reader path as the other guides.
        assert not document["content"].lstrip().startswith("---")
        assert "animations.mainSequence" in document["content"] or "mainSequence" in document["content"]

    def test_the_catalogue_in_the_tool_description_names_it(self):
        assert _GUIDE_NAME in contract.read_guides.__doc__

    def test_the_category_listing_carries_a_description(self):
        items = {item["name"]: item["description"] for item in list_category(_GUIDES)}
        assert _GUIDE_NAME in items
        assert items[_GUIDE_NAME].strip()


# --- completeness against the engine ---------------------------------------
class TestCompleteAgainstTheEngine:
    """The guide documents the contract the engine actually enforces."""

    def test_every_public_json_field_is_documented(self, guide):
        missing = sorted(field for field in _public_json_fields() if field not in guide)
        assert not missing, f"undocumented public JSON fields: {missing}"

    @pytest.mark.parametrize("name", sorted(_validated_vocabulary()))
    def test_every_validated_value_is_documented(self, guide, name):
        missing = sorted(value for value in _validated_vocabulary()[name] if value not in guide)
        assert not missing, f"{name} values missing from the guide: {missing}"

    def test_the_xml_limits_are_documented(self, guide):
        assert str(model.MAX_TIMING_XML_DEPTH) in guide
        assert f"{model.MAX_TIMING_XML_ELEMENTS:,}" in guide

    def test_the_preset_table_matches_what_the_writer_can_generate(self, guide, index):
        writable = _writable_presets(index)
        for category, names in writable.items():
            documented = _table_row_tokens(guide, category)
            assert documented == names, (
                f"category {category!r}: guide lists {sorted(documented)}, "
                f"writer can generate {sorted(names)}"
            )

    def test_every_transition_effect_is_listed(self, guide, index):
        documented = _first_column_tokens(guide, "### Transition effects and their option sets")
        assert documented == set(index.transition_slugs())

    def test_every_build_value_is_documented(self, guide, index):
        for family in (TEXT_SEQUENCE_BUILD, TEXT_LEVEL_BUILD, CHART_BUILD, SMARTART_BUILD):
            name, element, child = family
            values = index.build_values(name, element=element, child=child)
            missing = sorted(value for value in values if value not in guide)
            assert not missing, f"{name} ({element}) build values missing: {missing}"

    def test_every_refused_capability_is_named_with_its_key(self, guide, index):
        entries = {**index.items, **index.candidates}
        refused = sorted(
            key
            for key, entry in entries.items()
            if entry.status == "accepted"
            and not entry.writable
            and re.match(r"^(animation|transition)\.", key)
            and not key.startswith(_BULK_KEY_PREFIXES)
        )
        assert refused, "the catalog records no refused control keys; this test needs rethinking"
        missing = [key for key in refused if key not in guide]
        assert not missing, f"refused capabilities not disclosed in the guide: {missing}"
        # The 45 directions are disclosed as a family rather than key by key.
        assert "animation.effectOptions.direction." in guide


# --- the rules the requirements put on the guide ----------------------------
class TestGuideRules:
    """REQ-8.1 / REQ-8.2 content the guide has to carry as a rule, not a footnote."""

    def test_static_comprehensibility_is_a_rule(self, guide):
        heading = next(
            (line for line in guide.splitlines() if line.startswith("## ") and "motion off" in line),
            None,
        )
        assert heading, "the guide has no top-level rule section about motion being off"
        section = guide[guide.index(heading) : guide.index("\n## ", guide.index(heading) + len(heading))]
        assert "only" in section and "PDF" in section and "print" in section

    def test_it_explains_the_switches_and_the_override_precedence(self, guide):
        for token in ("animations.enabled", "transitions.enabled", "inherit", "independent"):
            assert token in guide
        assert "caller override" in guide

    def test_it_explains_raw_preservation_and_morph(self, guide):
        for token in ("_rawTiming", "_rawTransition", "animations/manifest.json", "IMPORT_LIMIT_EXCEEDED"):
            assert token in guide
        assert "## `animations`" in guide and "### Morph" in guide


# --- the always-loaded spec stays a pointer ---------------------------------
@pytest.fixture(scope="module")
def section() -> str:
    """The slide spec's motion section — everything it is allowed to say."""
    text = _SPEC_PATH.read_text(encoding="utf-8")
    start = text.index("## Animations and Transitions")
    return text[start : text.index("\n## ", start + 4)]


@pytest.fixture(scope="module")
def composer() -> str:
    return (_WORKFLOWS / "composer.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def orchestrator() -> str:
    return (_WORKFLOWS / "orchestrator.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def import_guide() -> str:
    return (_GUIDES / "import-pptx.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sync_guide() -> str:
    return (_GUIDES / "hand-edit-sync.md").read_text(encoding="utf-8")


class TestSpecOnlyPoints:
    """Ordinary composer context must not grow (REQ-1.1)."""

    def test_it_points_at_the_optional_guide(self, section):
        assert 'read_guides(["animations"])' in section

    def test_the_pointer_stays_short(self, section):
        lines = [line for line in section.strip().splitlines() if line.strip()]
        assert len(lines) <= 12, f"the pointer grew to {len(lines)} lines"

    def test_it_carries_no_detail_table(self, section):
        assert "|---" not in section and "```" not in section

    def test_it_names_no_field_that_belongs_to_the_guide(self, section):
        leaked = sorted(
            field
            for field in _public_json_fields() - _SPEC_MAY_NAME
            if re.search(rf"`{re.escape(field)}", section)
        )
        assert not leaked, f"the slide-spec pointer names optional-guide fields: {leaked}"

    def test_it_states_the_off_requirement(self, section):
        assert "motion off" in section


# --- conditional loading ----------------------------------------------------
class TestConditionalLoading:
    """A composer with neither switch on and no motion field never loads the guide."""

    def test_composer_loads_it_only_on_a_stated_condition(self, composer):
        assert 'read_guides(["animations"])' in composer
        for token in ("animations.enabled", "transitions.enabled", "existing_slides", "morphId"):
            assert token in composer
        assert "only when" in composer
        assert "do not load" in composer

    def test_composer_requires_the_slide_to_work_with_motion_off(self, composer):
        assert "disabled" in composer
        assert "only in an" in composer

    def test_composer_does_not_own_the_switches(self, composer):
        assert "deck.json" in composer and "orchestrator" in composer

    def test_orchestrator_decides_the_switches(self, orchestrator):
        for token in ("animations.enabled", "transitions.enabled", "deck.json", "inherit"):
            assert token in orchestrator
        assert 'read_guides(["animations"])' in orchestrator


# --- import and hand-edit sync ---------------------------------------------
class TestImportAndSyncGuides:
    """REQ-8.3: semantic extraction, raw fallback, sidecars, switches, verification."""

    def test_import_covers_extraction_fallback_and_switches(self, import_guide):
        for token in (
            "_rawTiming",
            "_rawTransition",
            "animations/manifest.json",
            "animations.enabled",
            "transitions.enabled",
            "SHA-256",
            'read_guides(["animations"])',
        ):
            assert token in import_guide, token

    def test_import_states_switch_derivation_and_preservation(self, import_guide):
        assert "derive" in import_guide and "preserve" in import_guide.lower()

    def test_import_requires_verification_after_the_build(self, import_guide):
        assert "Verification" in import_guide

    def test_sync_reflects_powerpoint_added_motion_back_into_json(self, sync_guide):
        for token in ("mainSequence", "interactiveSequences", "morphId", "target.element", "_rawTiming"):
            assert token in sync_guide, token

    def test_sync_preserves_an_explicit_switch(self, sync_guide):
        assert "animations" in sync_guide and "transitions" in sync_guide
        assert "preserve" in sync_guide.lower() and "Derive a switch only when" in sync_guide
