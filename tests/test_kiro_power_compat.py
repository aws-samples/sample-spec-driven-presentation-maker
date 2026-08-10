# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Layer 2 — Kiro Power compatibility.

Kiro loads Agent Plugins packages as Powers, but its authoring rules are
stricter than the portable standard: ``author`` and ``keywords`` are optional
in Agent Plugins 1.0.0 and required by Kiro, and Kiro treats ``keywords`` as
*activation triggers* rather than as search metadata.

That difference is invisible to a schema check — a manifest can be perfectly
valid 1.0.0 and still be rejected by Kiro — so it gets its own layer.
"""

import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_PLUGIN_JSON = _REPO / "plugin.json"

# Required by Kiro's Power authoring rules (a superset of Agent Plugins 1.0.0).
_KIRO_REQUIRED = ("$schema", "name", "version", "description", "author", "keywords")

# Words a user actually says when they want slides. Kiro matches keywords to
# decide whether to surface the Power, so these are behaviour, not metadata.
_EXPECTED_TRIGGERS = ("presentation", "slides", "powerpoint", "pptx")
_EXPECTED_JA_TRIGGERS = ("スライド", "プレゼン")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(_PLUGIN_JSON.read_text(encoding="utf-8"))


@pytest.mark.parametrize("field", _KIRO_REQUIRED)
def test_kiro_required_field_is_present(manifest, field):
    assert field in manifest, (
        f"Kiro requires '{field}' in a Power manifest even though Agent Plugins "
        "1.0.0 treats it as optional"
    )


def test_author_has_a_name(manifest):
    assert manifest["author"].get("name")


def test_description_is_a_usable_sentence(manifest):
    # Shown on the install surface and used for matching; a stub is a bug.
    assert len(manifest["description"]) >= 40


class TestActivationKeywords:
    def test_is_a_non_empty_list(self, manifest):
        assert isinstance(manifest["keywords"], list)
        assert manifest["keywords"]

    @pytest.mark.parametrize("trigger", _EXPECTED_TRIGGERS)
    def test_covers_english_triggers(self, manifest, trigger):
        assert trigger in manifest["keywords"]

    @pytest.mark.parametrize("trigger", _EXPECTED_JA_TRIGGERS)
    def test_covers_japanese_triggers(self, manifest, trigger):
        # The personas and the workflow menu are bilingual, so activation has
        # to work for Japanese prompts too.
        assert trigger in manifest["keywords"]

    def test_has_no_duplicates(self, manifest):
        keywords = manifest["keywords"]
        assert len(keywords) == len(set(keywords))

    def test_keywords_are_single_terms(self, manifest):
        # Trigger matching works on terms; a sentence never matches.
        for keyword in manifest["keywords"]:
            assert len(keyword.split()) == 1, f"keyword is not a single term: {keyword!r}"


class TestSkillsAreDiscoverable:
    def test_skills_live_at_the_standard_location(self):
        # Kiro reads plugin skills from <plugin>/skills/<name>/SKILL.md, the
        # same layout as its standalone ~/.kiro/skills/ directory.
        skills = sorted(p.name for p in (_REPO / "skills").iterdir() if (p / "SKILL.md").is_file())
        assert skills, "no skills found under skills/"
        assert all(name.startswith("sdpm-") for name in skills)
