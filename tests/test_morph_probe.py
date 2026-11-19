# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Focused package spike for deterministic PowerPoint Morph identity."""

import json
from pathlib import Path

import pytest

from scripts.animation_catalog.morph_probe import (
    MORPH_NAME,
    MORPH_OPTIONS,
    build_probe,
    morph_name,
    morph_transition_xml,
    validate_slide_morph_ids,
    verify_package,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "animations" / "morph-spike"


def test_forced_morph_name_uses_documented_prefix():
    assert morph_name("hero") == MORPH_NAME
    with pytest.raises(ValueError, match="must not include"):
        morph_name("!!hero")
    with pytest.raises(ValueError, match="non-empty"):
        morph_name("")


def test_duplicate_morph_id_on_one_slide_is_rejected():
    with pytest.raises(ValueError, match="duplicate morphId"):
        validate_slide_morph_ids(["hero", "hero"])
    validate_slide_morph_ids(["hero", "detail"])


@pytest.mark.parametrize("option", MORPH_OPTIONS)
def test_morph_transition_requires_explicit_supported_option(option):
    xml = morph_transition_xml(option, 800)
    assert f'option="{option}"' in xml
    assert 'Requires="p159"' in xml
    assert "<p:fade/>" in xml


def test_morph_transition_rejects_unknown_option_and_duration():
    with pytest.raises(ValueError, match="unsupported Morph option"):
        morph_transition_xml("byName")
    with pytest.raises(ValueError, match="positive integer"):
        morph_transition_xml("byObject", 0)


def test_generated_probe_has_all_variants_and_valid_order(tmp_path):
    path = build_probe(tmp_path / "morph-probe.pptx")
    assert verify_package(path) == {
        "slides": 4,
        "options": ["byObject", "byWord", "byChar"],
        "forcedName": MORPH_NAME,
    }


def test_manifest_records_correspondence_and_forbidden_outcome():
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text())
    assert manifest["identity"]["powerPointName"] == MORPH_NAME
    assert manifest["identity"]["sameSlideDuplicates"] == "invalid"
    assert [pair["option"] for pair in manifest["pairs"]] == list(MORPH_OPTIONS)
    assert all(pair["source"]["name"] == pair["destination"]["name"] for pair in manifest["pairs"])
    assert all("cross-fade" in pair["forbidden"] for pair in manifest["pairs"])
    assert manifest["transition"]["choiceRequires"] == "p159"
    assert manifest["transition"]["fallback"] == "fade"
