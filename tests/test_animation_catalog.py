# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Completeness, metadata and drift tests for the checked-in PowerPoint catalog."""

import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.animation_catalog.generate import (
    ALTERNATE_CONTENT,
    BASELINE_GENERATED_AT,
    BASELINE_VERSION,
    CANDIDATE_ENUM_CODES,
    CANDIDATE_ENUMS,
    CAPABILITY_LEVELS,
    DEFAULT_ORACLE,
    DEFAULT_ORACLE_EVIDENCE,
    DEFAULT_SDEF,
    FORBIDDEN_ORACLE_TOKENS,
    NATIVE,
    ORACLE_EVIDENCE_MERGED,
    ORACLE_EVIDENCE_PACKAGE,
    ORACLE_EVIDENCE_READBACK,
    ORACLE_RUN_TOKEN,
    ORACLE_VERIFICATION,
    REQUIRED_ORACLE_TOKENS,
    SEMANTIC,
    STATUSES,
    build_catalog,
    catalog_slide,
    check,
    dump,
    load_oracle_evidence,
    main,
    merge_oracle_readback,
    oracle_constant_call,
    oracle_findings,
    oracle_transition_form,
    parse_oracle_arrays,
    parse_oracle_package,
    read_oracle_readback,
    read_sdef,
    read_sdef_enum_codes,
    rewrite_oracle,
    split_oracle,
)
from sdpm.engine.timing import load_catalog, validate_catalog
from sdpm.engine.timing.model import validate_slide_motion

CATALOG_DIR = Path(__file__).resolve().parent.parent / "sdpm" / "references" / "catalogs"
REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = CATALOG_DIR / "powerpoint-gui-surface-16.113.1.json"
CATALOG_PATH = CATALOG_DIR / "powerpoint-animation-catalog.json"
GENERATOR_PATH = Path(__file__).resolve().parent.parent / "scripts" / "animation_catalog" / "generate.py"

MANIFEST_ITEM_FIELDS = ("control", "value", "surface", "sourceEvidence", "persisted", "verificationMethod")

#: The consent argument must appear nowhere that sdpm runs on its own. These
#: are the only files allowed to mention it: the oracle, the generator that
#: checks the oracle, the docs that tell a maintainer how to run it, and this
#: test file.
ORACLE_TOKEN_ALLOWED = {
    "scripts/animation_catalog/powerpoint.applescript",
    "scripts/animation_catalog/generate.py",
    "scripts/animation_catalog/README.md",
    "tests/test_animation_catalog.py",
}

#: Object-model shapes the first Task 3 draft used that the scripting
#: definition does not declare. None may come back.
ORACLE_WRONG_OBJECT_MODEL = (
    "set entry effect of theSlide to",
    "set entry effect of s to",
    "make new animation effect",
    "animation trigger type",
    "animation effects of main sequence",
    "main sequence of theSlide",
    "slide layout 7 of slide master",
    "top position:",
    "auto shape type:rounded rectangle",
)


@pytest.fixture(scope="module")
def oracle() -> str:
    return DEFAULT_ORACLE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


# --- the manifest is an independent, versioned expected universe ----------


def test_manifest_is_versioned_and_declares_the_candidate_universe(manifest):
    assert manifest["schemaVersion"] == 1
    assert manifest["manifestVersion"]
    assert manifest["baseline"]["version"] == "16.113.1"
    assert manifest["baseline"]["platform"] == "macOS"
    declared = {row["enum"]: row["expectedCount"] for row in manifest["candidateEnums"]}
    assert declared == dict(CANDIDATE_ENUMS)
    assert sum(declared.values()) == 435
    assert manifest["authoring"]["owner"].startswith("hand-maintained")


def test_every_manifest_item_carries_control_value_evidence_and_verification(manifest):
    assert manifest["items"], "the manifest must inventory GUI controls and values"
    for item in manifest["items"]:
        missing = [field for field in MANIFEST_ITEM_FIELDS if field not in item]
        assert not missing, f"{item['key']} is missing {missing}"
        assert isinstance(item["persisted"], bool)
        assert item["sourceEvidence"].strip()
        assert item["verificationMethod"].strip()
        assert item["status"] in STATUSES


def test_manifest_persistence_flag_agrees_with_the_expected_status(manifest):
    for item in manifest["items"]:
        assert item["persisted"] == (item["status"] == "accepted"), (
            f"{item['key']} is marked persisted={item['persisted']} but status={item['status']!r}"
        )


def test_manifest_accounts_for_every_candidate_exactly_once(manifest):
    keys = [row["key"] for row in manifest["candidates"]]
    assert len(keys) == len(set(keys)) == 435
    per_enum: dict[str, int] = {}
    for row in manifest["candidates"]:
        per_enum[row["enum"]] = per_enum.get(row["enum"], 0) + 1
        assert row["status"] in STATUSES
        assert row["code"].startswith("0x")
    assert per_enum == dict(CANDIDATE_ENUMS)


def test_manifest_records_supplementary_enums_rather_than_dropping_them(manifest):
    supplementary = {row["enum"]: row for row in manifest["supplementaryEnums"]}
    assert "MsoAnimEffectRestart" in supplementary
    assert "MsoAnimFilterEffectType" in supplementary
    for row in supplementary.values():
        assert row["disposition"]
        assert row["reason"].strip()


# --- required catalog provenance ------------------------------------------


def test_catalog_satisfies_the_frozen_loader_contract():
    assert validate_catalog(load_catalog(CATALOG_PATH))


def test_catalog_baseline_records_fixed_provenance(catalog, manifest):
    baseline = catalog["baseline"]
    assert baseline["application"] == "Microsoft PowerPoint"
    assert baseline["version"] == "16.113.1"
    assert baseline["platform"] == "macOS"
    assert baseline["generatedAt"] == BASELINE_GENERATED_AT
    assert baseline["guiManifest"] == f"{MANIFEST_PATH.name}@{manifest['manifestVersion']}"


def test_catalog_provenance_names_every_external_reference_without_vendoring(catalog):
    references = {row["id"]: row for row in catalog["provenance"]["references"]}
    assert references["office-kit/pptx"]["license"] == "MIT"
    assert references["office-kit/pptx"]["commit"] == "18b7e75cfa7fd1c6e9891ce1285a76c7889b644b"
    assert references["office-kit/pptx"]["fixtureCorpusFiles"] == 147
    assert references["ChristopherVR/ooxml"]["license"] == "Apache-2.0"
    assert references["ChristopherVR/ooxml"]["commit"] == "e269a0bb944062871e5bcd05856ce65570e2e137"
    for row in references.values():
        assert row["vendored"] is False
        assert row["url"]
        assert row["use"].strip()
    assert "-10004" in catalog["provenance"]["powerPointAutomation"]


def test_catalog_declares_the_supported_alternate_content_namespace_set(catalog):
    assert catalog["alternateContent"] == ALTERNATE_CONTENT
    requires = {row["requires"] for row in catalog["alternateContent"]["supported"]}
    assert requires == {"p14", "p15", "p159"}
    assert "document order" in catalog["alternateContent"]["choiceSelection"]


# --- one-to-one accounting ------------------------------------------------


def test_every_gui_item_and_candidate_has_exactly_one_status(catalog):
    for group in ("guiItems", "candidates"):
        keys = [entry["key"] for entry in catalog[group]]
        assert len(keys) == len(set(keys))
        for entry in catalog[group]:
            assert entry["status"] in STATUSES


def test_candidate_counts_match_the_sdef_enumeration_sizes(catalog):
    per_enum: dict[str, int] = {}
    for entry in catalog["candidates"]:
        per_enum[entry["enum"]] = per_enum.get(entry["enum"], 0) + 1
    assert per_enum == dict(CANDIDATE_ENUMS)
    assert catalog["summary"]["candidateTotal"] == 435
    assert sum(catalog["summary"]["candidateStatusCounts"].values()) == 435


def test_every_candidate_maps_to_a_known_gui_item(catalog):
    item_keys = {entry["key"] for entry in catalog["guiItems"]}
    for entry in catalog["candidates"]:
        assert entry["guiKey"] in item_keys, f"{entry['key']} points at {entry['guiKey']!r}"


def test_manifest_and_catalog_agree_item_for_item(manifest, catalog):
    manifest_items = {row["key"]: row["status"] for row in manifest["items"]}
    catalog_items = {row["key"]: row["status"] for row in catalog["guiItems"]}
    assert manifest_items.keys() == catalog_items.keys()
    assert manifest_items == catalog_items

    manifest_candidates = {row["key"]: (row["status"], row["guiKey"]) for row in manifest["candidates"]}
    catalog_candidates = {row["key"]: (row["status"], row["guiKey"]) for row in catalog["candidates"]}
    assert manifest_candidates == catalog_candidates


def test_unaccepted_entries_always_carry_a_reason(catalog):
    for group in ("guiItems", "candidates"):
        for entry in catalog[group]:
            if entry["status"] != "accepted":
                assert entry["reason"].strip(), f"{entry['key']} has no reason"


# --- accepted entries are complete and honestly levelled ------------------


def test_accepted_entries_carry_a_capability_level_and_ooxml_metadata(catalog):
    for group in ("guiItems", "candidates"):
        for entry in catalog[group]:
            if entry["status"] != "accepted":
                continue
            assert entry["capabilityLevel"] in CAPABILITY_LEVELS, entry["key"]
            assert isinstance(entry["semanticJson"], dict) and entry["semanticJson"], entry["key"]
            assert isinstance(entry["ooxml"], dict) and entry["ooxml"], entry["key"]
            assert entry["evidence"]["source"].strip(), entry["key"]


def test_native_template_claims_name_a_pinned_fixture(catalog):
    for group in ("guiItems", "candidates"):
        for entry in catalog[group]:
            if entry.get("capabilityLevel") == NATIVE:
                assert entry["evidence"].get("fixture"), f"{entry['key']} claims a native template"


def test_unverified_mappings_are_flagged_rather_than_passed_off_as_verified(catalog):
    for group in ("guiItems", "candidates"):
        for entry in catalog[group]:
            if entry.get("capabilityLevel") != SEMANTIC:
                continue
            ooxml = entry["ooxml"]
            assert ooxml.get("gap") or ooxml.get("note"), f"{entry['key']} hides its gap"
            assert entry["verification"] == "powerPointReadBackRequired", entry["key"]


def test_every_accepted_semantic_json_validates_against_the_frozen_model(catalog):
    failures = []
    for group in ("guiItems", "candidates"):
        for entry in catalog[group]:
            if entry["status"] != "accepted":
                continue
            diagnostics = validate_slide_motion(catalog_slide(entry["semanticJson"]))
            if diagnostics:
                failures.append((entry["key"], [d.rule for d in diagnostics]))
    assert not failures


def _only_effect(semantic: dict) -> dict:
    """Return the single effect of a semantic fragment, wherever it lives."""
    animations = semantic["animations"]
    main = animations["mainSequence"]
    if main:
        return main[0]
    return animations["interactiveSequences"][0]["effects"][0]


def test_accepted_semantic_json_is_complete_not_just_a_name(catalog):
    for entry in catalog["candidates"]:
        if entry["status"] != "accepted":
            continue
        semantic = entry["semanticJson"]
        if "transition" in semantic:
            transition = semantic["transition"]
            assert set(transition) >= {"effect", "parameters", "durationMs", "advance", "sound"}
        else:
            effect = _only_effect(semantic)
            assert set(effect) >= {"id", "target", "start", "timing", "afterEffect", "sound"}
            assert set(effect["timing"]) >= {"durationMs", "repeatCount", "autoReverse", "restart"}


# --- specific requirements the catalog has to express ---------------------


def test_the_three_morph_variants_are_all_accepted(catalog):
    morph = {
        entry["enumerator"]: entry
        for entry in catalog["candidates"]
        if entry["enumerator"].startswith("entry effect morph")
    }
    assert set(morph) == {"entry effect morph by object", "entry effect morph by word", "entry effect morph by char"}
    for entry in morph.values():
        assert entry["status"] == "accepted"
        assert entry["ooxml"]["element"] == "p159:morph"
        assert entry["ooxml"]["requires"] == "p159"
        assert entry["ooxml"]["fallbackElement"] == "p:fade"
        assert entry["semanticJson"]["transition"]["parameters"]["variant"] in {"byObject", "byWord", "byChar"}


def test_no_transition_and_the_api_sentinel_are_not_supported_transitions(catalog):
    by_key = {entry["key"]: entry for entry in catalog["candidates"]}
    assert by_key["EPPEntryEffect.entry effect none"]["status"] == "nonPersisted"
    assert by_key["EPPEntryEffect.entry effect unset"]["status"] == "rejected"


def test_the_nine_behaviour_primitives_are_all_accounted(catalog):
    behaviours = {
        entry["key"].split(".", 1)[1]: entry
        for entry in catalog["candidates"]
        if entry["enum"] == "MsoAnimType"
    }
    assert len(behaviours) == 9
    assert behaviours["animation type none"]["status"] == "nonPersisted"
    elements = {
        entry["ooxml"]["element"]
        for entry in behaviours.values()
        if entry["status"] == "accepted"
    }
    assert elements == {
        "p:animMotion", "p:animClr", "p:animScale", "p:animRot",
        "p:anim", "p:cmd", "p:animEffect", "p:set",
    }


def test_entrance_exit_preset_ids_are_only_claimed_inside_the_corroborated_band(catalog):
    for entry in catalog["candidates"]:
        if entry["enum"] != "MsoAnimEffect" or entry["status"] != "accepted":
            continue
        ooxml = entry["ooxml"]
        if ooxml.get("presetClass") != ["entr", "exit"]:
            continue
        ordinal = int(entry["code"], 16) & 0xFF
        confident_max = catalog["provenance"]["entranceExitConfidentOrdinalMax"]
        if ooxml["presetId"] is None:
            assert ordinal > confident_max
            assert "divergence" in ooxml["gap"]
        else:
            assert ordinal <= confident_max
            assert ooxml["presetId"] == ordinal


def test_chart_and_text_builds_are_represented(catalog):
    levels = {
        entry["semanticJson"]["animations"]["mainSequence"][0].get("chart", {}).get("build")
        or entry["semanticJson"]["animations"]["mainSequence"][0].get("text", {}).get("level")
        for entry in catalog["candidates"]
        if entry["enum"] == "MsoAnimateByLevel"
    }
    assert {"chartAllAtOnce", "chartByCategory", "chartByCategoryElement", "chartBySeries",
            "chartBySeriesElement"} <= levels
    assert {"asOneObject", "byParagraphLevel1", "byParagraphLevel5"} <= levels


def test_every_trigger_type_is_accounted(catalog):
    entries = [entry for entry in catalog["candidates"] if entry["enum"] == "MsoAnimTriggerType"]
    triggers = set()
    for entry in entries:
        animations = entry["semanticJson"]["animations"]
        sequences = animations["interactiveSequences"]
        triggers.add(
            sequences[0]["trigger"]["type"] if sequences else _only_effect(entry["semanticJson"])["start"]["type"]
        )
    assert triggers == {"none", "onPageClick", "withPrevious", "afterPrevious", "onShapeClick"}
    # PowerPoint persists a shape-click trigger as an interactive sequence, so
    # the catalog value must carry that sequence rather than a main-sequence
    # effect whose start type no writer can place.
    shape_click = next(e for e in entries if e["enumerator"] == "on shape click")
    sequence = shape_click["semanticJson"]["animations"]["interactiveSequences"][0]
    assert shape_click["semanticJson"]["animations"]["mainSequence"] == []
    assert sequence["trigger"] == {"type": "onShapeClick", "target": "catalogTarget", "delayMs": 0}
    assert shape_click["ooxml"]["nodeType"] == "interactiveSeq"


def test_transition_gallery_covers_all_49_captured_tiles(catalog):
    tiles = [entry for entry in catalog["guiItems"] if entry["key"].startswith("transition.gallery.")]
    assert len(tiles) == 49
    accepted = [tile for tile in tiles if tile["status"] == "accepted"]
    assert len(accepted) == 48
    assert all(tile["capabilityLevel"] == NATIVE for tile in accepted)


def test_animation_gallery_covers_all_95_captured_tiles(catalog):
    tiles = [
        entry for entry in catalog["guiItems"]
        if entry["key"].startswith(("animation.gallery.entrance.", "animation.gallery.exit.",
                                    "animation.gallery.emphasis."))
    ]
    assert len(tiles) == 95
    assert all(tile["status"] == "accepted" and tile["capabilityLevel"] == NATIVE for tile in tiles)


# --- drift and runtime independence ---------------------------------------


def test_check_passes_without_the_local_scripting_definition(manifest, catalog):
    assert check(manifest, catalog, None) == []


def test_check_detects_a_dropped_candidate(manifest, catalog):
    broken = dict(catalog)
    broken["candidates"] = catalog["candidates"][1:]
    findings = check(manifest, broken, None)
    assert any("missing from the catalog" in finding for finding in findings)


def test_check_detects_status_drift(manifest, catalog):
    broken = json.loads(json.dumps(catalog))
    broken["guiItems"][0]["status"] = "outOfScope"
    broken["guiItems"][0]["reason"] = "injected"
    findings = check(manifest, broken, None)
    assert any("status drift" in finding for finding in findings)


def test_check_detects_a_missing_timestamp_and_manifest_link(manifest, catalog):
    broken = json.loads(json.dumps(catalog))
    broken["baseline"]["generatedAt"] = "2020-01-01T00:00:00Z"
    broken["baseline"]["guiManifest"] = ""
    findings = check(manifest, broken, None)
    assert any("generatedAt drifted" in finding for finding in findings)
    assert any("guiManifest is missing" in finding for finding in findings)


def test_check_detects_an_accepted_entry_without_semantic_json(manifest, catalog):
    broken = json.loads(json.dumps(catalog))
    target = next(entry for entry in broken["candidates"] if entry["status"] == "accepted")
    target["semanticJson"] = {}
    target["ooxml"] = {}
    findings = check(manifest, broken, None)
    assert any("without semanticJson" in finding for finding in findings)
    assert any("without ooxml metadata" in finding for finding in findings)


def test_generator_does_not_reach_the_network_or_spawn_processes():
    source = GENERATOR_PATH.read_text(encoding="utf-8")
    for forbidden in ("import socket", "import subprocess", "import urllib", "import requests",
                      "import http", "osascript", "applescript("):
        assert forbidden not in source, f"generate.py must not use {forbidden}"


@pytest.mark.skipif(not DEFAULT_SDEF.exists(), reason="PowerPoint 16.113.1 is not installed")
def test_local_scripting_definition_matches_the_checked_in_universe(manifest, catalog):
    sdef_enums = read_sdef(DEFAULT_SDEF)
    assert {name: len(values) for name, values in sdef_enums.items()} == dict(CANDIDATE_ENUMS)
    assert check(manifest, catalog, sdef_enums) == []


@pytest.mark.skipif(not DEFAULT_SDEF.exists(), reason="PowerPoint 16.113.1 is not installed")
def test_regeneration_is_byte_deterministic(manifest):
    sdef_enums = read_sdef(DEFAULT_SDEF)
    first = dump(build_catalog(manifest, sdef_enums))
    second = dump(build_catalog(manifest, sdef_enums))
    assert first == second
    assert first == CATALOG_PATH.read_text(encoding="utf-8")


# --- the AppleScript oracle ------------------------------------------------


def test_oracle_candidate_arrays_account_for_every_sdef_candidate(oracle):
    _head, region, _tail = split_oracle(oracle)
    arrays = parse_oracle_arrays(region)
    assert set(arrays) == set(CANDIDATE_ENUMS), "every required enumeration needs generated arrays"
    for enum_name, expected_count in CANDIDATE_ENUMS.items():
        group = arrays[enum_name]
        assert set(group) == {"constants", "names", "codes"}, enum_name
        for kind, values in group.items():
            assert len(values) == expected_count, f"{enum_name} {kind} has {len(values)} entries"
    assert sum(len(arrays[name]["constants"]) for name in CANDIDATE_ENUMS) == 435
    # The two enumerations the task calls out explicitly.
    assert len(arrays["MsoAnimEffect"]["constants"]) == 150
    assert len(arrays["EPPEntryEffect"]["constants"]) == 207
    # Each constant names its own candidate by code - the enumeration's type
    # code plus the enumerator's own - so a record can never report a name that
    # a different constant applied. Position i of all three arrays is the same
    # candidate.
    for enum_name in CANDIDATE_ENUMS:
        codes = arrays[enum_name]["codes"]
        assert all(code.startswith("0x") for code in codes), enum_name
        assert arrays[enum_name]["constants"] == [
            oracle_constant_call(enum_name, code) for code in codes
        ], enum_name
        assert len(set(arrays[enum_name]["constants"])) == len(set(codes)), enum_name


def test_oracle_has_no_empty_array_and_no_name_to_constant_placeholder(oracle):
    for token in FORBIDDEN_ORACLE_TOKENS:
        assert token not in oracle, f"the oracle still carries {token!r}"
    # The first draft shipped `transitionCandidates()` returning {} and two
    # mappers that raised on every name.
    assert "transitionCandidates" not in oracle
    assert "animationCandidates" not in oracle
    assert "entryEffectConstant" not in oracle
    assert "animEffectConstant" not in oracle
    assert not re.search(r"return\s*\{\s*\}", oracle)
    assert not re.search(r"^\s*error \"map ", oracle, re.MULTILINE)
    _head, region, _tail = split_oracle(oracle)
    arrays = parse_oracle_arrays(region)
    for enum_name, group in arrays.items():
        for kind, values in group.items():
            assert values, f"{enum_name} {kind} array is empty"


def test_oracle_uses_the_object_model_the_sdef_declares(oracle):
    for token in REQUIRED_ORACLE_TOKENS:
        assert token in oracle, f"the oracle is missing {token!r}"
    for token in ORACLE_WRONG_OBJECT_MODEL:
        assert token not in oracle, f"the oracle fell back to {token!r}, which the sdef does not declare"
    # The transition is a property of the slide's own transition object, and
    # animations go through the slide's timeline, not the slide itself.
    assert oracle.count("slide show transition of theSlide") >= 2
    assert "main sequence of timeline of theSlide" in oracle
    assert "add effect (main sequence of timeline of theSlide) for theShape" in oracle
    # Values with no readable dictionary property are deferred to the package.
    assert "p:timing//p:cTn/@nodeType and p:cond/@evt" in oracle
    assert "p:timing//p:cTn/@afterEffect" in oracle
    assert "--parse-oracle" in oracle


def test_oracle_addresses_powerpoint_only_after_explicit_consent(oracle):
    assert f'property kRunToken : "{ORACLE_RUN_TOKEN}"' in oracle
    guard = oracle.index("if (item 2 of argList) is not kRunToken then")
    assert guard < oracle.index('tell application "Microsoft PowerPoint"'), (
        "every PowerPoint terminology block must sit after the consent check"
    )
    assert guard < oracle.index("my captureCatalog(")
    # Only the capture path activates PowerPoint, and only once.
    assert oracle.count("\t\tactivate\n") == 1
    assert oracle.index("on captureCatalog(") < oracle.index("\t\tactivate\n")
    # No scheduled or runtime surface may pass the consent argument.
    suffixes = {".py", ".md", ".yml", ".yaml", ".sh", ".json", ".applescript", ".ps1", ".toml"}
    roots = [REPO_ROOT / name for name in
             ("scripts", "sdpm", "servers", "agent", "api", "shared", "tests", ".github", "infra", "docs")]
    paths = [path for root in roots if root.is_dir() for path in root.rglob("*")]
    paths += [path for path in REPO_ROOT.glob("*") if path.is_file()]
    users = set()
    for path in paths:
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix not in suffixes and path.name not in {"Makefile", "buildspec.yml"}:
            continue
        if ORACLE_RUN_TOKEN in path.read_text(encoding="utf-8", errors="ignore"):
            users.add(path.relative_to(REPO_ROOT).as_posix())
    assert users <= ORACLE_TOKEN_ALLOWED, f"unexpected callers of {ORACLE_RUN_TOKEN}: {users - ORACLE_TOKEN_ALLOWED}"


def test_oracle_check_is_clean_and_catches_every_kind_of_drift(oracle):
    assert oracle_findings(oracle) == []

    emptied = re.sub(r"on msoAnimTypeConstants\(\)\n.*?\nend msoAnimTypeConstants",
                     "on msoAnimTypeConstants()\n\treturn {}\nend msoAnimTypeConstants", oracle, flags=re.DOTALL)
    findings = oracle_findings(emptied)
    assert any("unfinished-work token" in finding for finding in findings)
    assert any("MsoAnimType constants array has 0 entries" in finding for finding in findings)

    wrong_model = oracle.replace("entry effect of slide show transition of theSlide", "entry effect of theSlide")
    assert any("required object-model construct" in finding for finding in oracle_findings(wrong_model))

    ungated = oracle.replace(ORACLE_RUN_TOKEN, "--yolo")
    assert any("does not gate PowerPoint" in finding for finding in oracle_findings(ungated))

    assert any("marker" in finding for finding in oracle_findings("-- no generated region here"))


@pytest.mark.skipif(not DEFAULT_SDEF.exists(), reason="PowerPoint 16.113.1 is not installed")
def test_oracle_candidate_names_and_codes_match_the_local_sdef(oracle):
    sdef_enums = read_sdef(DEFAULT_SDEF)
    _head, region, _tail = split_oracle(oracle)
    arrays = parse_oracle_arrays(region)
    checked = 0
    enum_codes = read_sdef_enum_codes(DEFAULT_SDEF)
    assert enum_codes == CANDIDATE_ENUM_CODES, "the oracle names every candidate with its enumeration's code"
    for enum_name, values in sdef_enums.items():
        names = [name for name, _ in values]
        codes = [code for _, code in values]
        assert arrays[enum_name]["names"] == names, enum_name
        assert arrays[enum_name]["constants"] == [
            oracle_constant_call(enum_name, code) for code in codes
        ], enum_name
        assert arrays[enum_name]["codes"] == codes, enum_name
        checked += len(names)
    assert checked == 435
    assert oracle_findings(oracle, sdef_enums) == []

    dropped = oracle.replace('"0x01020001", \u00ac\n\t\t', "", 1)
    findings = oracle_findings(dropped, sdef_enums)
    assert any("missing 1 sdef value" in finding for finding in findings)


@pytest.mark.skipif(not DEFAULT_SDEF.exists(), reason="PowerPoint 16.113.1 is not installed")
def test_oracle_candidate_arrays_regenerate_byte_for_byte(oracle):
    sdef_enums = read_sdef(DEFAULT_SDEF)
    first = rewrite_oracle(oracle, sdef_enums)
    second = rewrite_oracle(first, sdef_enums)
    assert first == second
    assert first == oracle, "run generate.py --write: the checked-in oracle is not the generated one"


@pytest.mark.skipif(sys.platform != "darwin", reason="osacompile is macOS only")
@pytest.mark.skipif(not DEFAULT_SDEF.exists(), reason="PowerPoint 16.113.1 is not installed")
@pytest.mark.skipif(shutil.which("osacompile") is None, reason="osacompile is unavailable")
def test_oracle_compiles_without_launching_powerpoint(tmp_path):
    compiled = tmp_path / "powerpoint-oracle.scpt"
    result = subprocess.run(
        [shutil.which("osacompile"), "-o", str(compiled), str(DEFAULT_ORACLE)],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert compiled.exists() and compiled.stat().st_size > 0
    # Compiling resolves the terminology out of the application bundle. Round
    # tripping it proves the constants are real enumerators rather than
    # identifiers the compiler happened to tolerate.
    decompiler = shutil.which("osadecompile")
    if decompiler:
        source = subprocess.run(
            [decompiler, str(compiled)], capture_output=True, text=True, timeout=180, check=False,
        )
        assert source.returncode == 0, source.stderr
        assert "entry effect of slide show transition of theSlide" in source.stdout
        assert "add effect (main sequence of timeline of theSlide)" in source.stdout
        assert "entry effect morph by object" in source.stdout
        assert "animation type 4 point star path" in source.stdout


#: The six MsoAnimDirection/MsoAnimAfterEffect terms a generated array may not
#: carry, and what each one does when it is evaluated as a bare term. Four are
#: PowerPoint property names, so the compiler builds a property reference and
#: evaluating it raises -1728 - that is what aborted the 2026-10-31 capture.
#: Two compile to a constant of a different enumeration altogether, which is
#: worse: nothing fails, the probe applies a text-orientation value, and the
#: record names the direction that was asked for.
AMBIGUOUS_ORACLE_TERMS = {
    "top": "propertyReference",
    "font bold": "propertyReference",
    "font italic": "propertyReference",
    "dim": "propertyReference",
    "horizontal": "otherEnumeration",
    "vertical": "otherEnumeration",
}


def _run_applescript(tmp_path: Path, source: str, name: str = "probe") -> str:
    """Compile and run one AppleScript, returning its stdout.

    Nothing here addresses PowerPoint: a ``using terms from`` block is resolved
    at compile time out of the application bundle, and the values it produces
    are local constants. No Apple Event is sent, so this cannot launch
    PowerPoint and does not need the Automation grant.
    """
    script = tmp_path / f"{name}.applescript"
    compiled = tmp_path / f"{name}.scpt"
    script.write_text(source, encoding="utf-8")
    built = subprocess.run(
        [shutil.which("osacompile"), "-o", str(compiled), str(script)],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run(
        [shutil.which("osascript"), str(compiled)], capture_output=True, text=True, timeout=300, check=False,
    )
    assert ran.returncode == 0, ran.stderr
    return ran.stdout


def _oracle_handler(oracle: str, name: str) -> str:
    match = re.search(rf"^on {name}\(.*?\nend {name}$", oracle, re.MULTILINE | re.DOTALL)
    assert match, f"the oracle has no {name} handler"
    return match.group(0)


@pytest.mark.skipif(sys.platform != "darwin", reason="osacompile is macOS only")
@pytest.mark.skipif(not DEFAULT_SDEF.exists(), reason="PowerPoint 16.113.1 is not installed")
@pytest.mark.skipif(shutil.which("osacompile") is None, reason="osacompile is unavailable")
@pytest.mark.skipif(shutil.which("osascript") is None, reason="osascript is unavailable")
def test_every_generated_constant_is_the_value_its_name_claims(oracle, tmp_path):
    """Run the shipped arrays through the shipped handler and compare each
    constant with the enumerator term it stands for.

    This is the contract that makes naming candidates by code safe: the
    constant ``enumConstant`` builds has to be the same value the term names,
    or the oracle would apply something other than what its record says. It
    holds for every candidate whose term is unambiguous; the six that are not
    are the reason the arrays carry codes at all, and they are asserted
    separately below.
    """
    sdef_enums = read_sdef(DEFAULT_SDEF)
    _head, region, _tail = split_oracle(oracle)
    arrays = parse_oracle_arrays(region)
    lines = [_oracle_handler(oracle, "enumConstant"), _oracle_handler(oracle, "hexDigit"),
             "set zzAcc to {}", 'using terms from application "Microsoft PowerPoint"']
    order: list[tuple[str, str]] = []
    for enum_name in CANDIDATE_ENUMS:
        for (name, _code), call in zip(sdef_enums[enum_name], arrays[enum_name]["constants"]):
            order.append((enum_name, name))
            lines += ["\ttry", f"\t\tset end of zzAcc to (({call}) is ({name}))",
                      "\ton error zzT number zzN", '\t\tset end of zzAcc to ("ERR " & zzN)', "\tend try"]
    lines += ["end using terms from", "set AppleScript's text item delimiters to \"|\"",
              "return zzAcc as text"]
    results = _run_applescript(tmp_path, "\n".join(lines) + "\n", "constants").rstrip("\n").split("|")

    assert len(results) == 435
    unequal = {name: value for (_enum, name), value in zip(order, results) if value != "true"}
    assert set(unequal) == set(AMBIGUOUS_ORACLE_TERMS), (
        "a generated constant is not the value its own name claims"
    )
    for name, value in unequal.items():
        if AMBIGUOUS_ORACLE_TERMS[name] == "propertyReference":
            assert value.startswith("ERR"), name
        else:
            assert value == "false", name


@pytest.mark.skipif(sys.platform != "darwin", reason="osacompile is macOS only")
@pytest.mark.skipif(not DEFAULT_SDEF.exists(), reason="PowerPoint 16.113.1 is not installed")
@pytest.mark.skipif(shutil.which("osacompile") is None, reason="osacompile is unavailable")
@pytest.mark.skipif(shutil.which("osascript") is None, reason="osascript is unavailable")
def test_a_bare_enumerator_term_is_ambiguous_which_is_why_codes_are_generated(oracle, tmp_path):
    """Establish the defect the generated codes remove, rather than asserting
    it from the commit message.

    ``top``, ``font bold``, ``font italic`` and ``dim`` compile to property
    references and raise -1728 when evaluated - one of them aborted a whole
    capture run. ``horizontal`` and ``vertical`` compile to a constant of the
    ``TxOr`` enumeration instead of ``AnDi``, so a probe would silently apply a
    text orientation. No generated array may carry a bare term.
    """
    lines = ["set zzAcc to {}", 'using terms from application "Microsoft PowerPoint"']
    for term in AMBIGUOUS_ORACLE_TERMS:
        lines += ["\ttry", f"\t\tset end of zzAcc to (({term}) as text)",
                  "\ton error zzT number zzN", '\t\tset end of zzAcc to ("ERR " & zzN)', "\tend try"]
    lines += ["end using terms from", "set AppleScript's text item delimiters to \"|\"",
              "return zzAcc as text"]
    results = _run_applescript(tmp_path, "\n".join(lines) + "\n", "ambiguous").rstrip("\n").split("|")

    for term, value in zip(AMBIGUOUS_ORACLE_TERMS, results):
        if AMBIGUOUS_ORACLE_TERMS[term] == "propertyReference":
            assert value.startswith("ERR"), f"{term} no longer resolves to a PowerPoint property"
        else:
            assert "TxOr" in value, f"{term} no longer resolves to the wrong enumeration: {value}"
    _head, region, _tail = split_oracle(oracle)
    for term in AMBIGUOUS_ORACLE_TERMS:
        assert f'"{term}"' in region, f"{term} must still be carried as a name"
        assert f", {term},"  not in region and f"{{{term}," not in region, (
            f"{term} is back in a generated array as a bare term"
        )


def test_the_oracle_names_constants_by_code_and_not_by_term(oracle):
    """No generated array may hold an AppleScript term, and the handler that
    turns a code into a constant has to be the one in the oracle."""
    _head, region, _tail = split_oracle(oracle)
    assert "using terms from" not in region, (
        "a generated array with terminology in it is resolving names at compile time again"
    )
    assert region.count("my enumConstant(\"") == 435
    assert "on enumConstant(typedCode)" in oracle
    assert "on hexDigit(theChar)" in oracle
    # The constant is built from the code, through AppleScript's raw constant
    # syntax. A «data ...» literal would compile but would not compare equal to
    # a value PowerPoint reports back, so valueIndex would never match it.
    assert "run script (\"\u00abconstant \"" in oracle
    handler = _oracle_handler(oracle, "enumConstant")
    assert "\u00abdata " not in handler and "\u00abdata " not in region


def test_oracle_findings_catch_a_constant_that_is_not_its_own_code(oracle):
    """The drift check the one-to-one name comparison used to provide."""
    swapped = oracle.replace(
        oracle_constant_call("EPPEntryEffect", "0x00f60f55"),
        oracle_constant_call("EPPEntryEffect", "0x00f60f56"),
        1,
    )
    assert any(
        "constants are not each the code of their own candidate" in finding
        for finding in oracle_findings(swapped)
    )
    without_handler = oracle.replace("on enumConstant(typedCode)", "on enumConstantUnused(typedCode)")
    assert any("has no 'on enumConstant(typedCode)' handler" in finding
               for finding in oracle_findings(without_handler))


def test_one_failed_probe_cannot_discard_the_whole_run(oracle):
    """Containment, probe by probe, with the package written as it goes.

    A capture run is expensive and partially valuable: the 2026-10-31 run
    applied 357 candidates and then lost all of them when the fourth probe
    raised before ``savePackage``. Every probe now runs inside ``runProbe``,
    which records a failure as a record and carries on, the package is written
    after each probe, and ``savePackage`` is reached whatever happened.
    """
    capture = oracle[oracle.index("on captureCatalog("):oracle.index("end captureCatalog")]
    for probe in ("probeTransitions", "probeAnimations", "probeDirections", "probeTriggers",
                  "probeBuildLevels", "probeTextUnits", "probeBehaviors", "probeAfterEffects"):
        assert f'"{probe}"' in capture, f"{probe} is not dispatched through runProbe"
        assert f"my {probe}(" not in capture, (
            f"{probe} is still called straight from captureCatalog, outside the containment"
        )
    assert "my runProbe(readbackPath, probe, packagePath, contents of probeName)" in capture
    assert "my savePackage(readbackPath, probe, packagePath)" in capture
    # A failure is a record, not an abort: runProbe emits one either way.
    contained = oracle[oracle.index("on runProbe("):oracle.index("end runProbe")]
    assert "on error errText number errNum" in contained
    assert 'my kv("record", "probe")' in contained
    assert "my saveSnapshot(readbackPath, probe, packagePath, probeName)" in contained
    snapshot = oracle[oracle.index("on saveSnapshot("):oracle.index("end saveSnapshot")]
    assert "save probe in (POSIX file packagePath) as save as Open XML presentation" in snapshot
    assert "on error errText number errNum" in snapshot
    # savePackage's own failure leaves the last snapshot analysable.
    saver = oracle[oracle.index("on savePackage("):oracle.index("end savePackage")]
    assert 'my kv("record", "saveFailure")' in saver


# --- the Python half: OOXML analysis of the saved package ------------------

_SLIDE_NS = (
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main" '
    'xmlns:p159="http://schemas.microsoft.com/office/powerpoint/2015/09/main"'
)

_TRANSITION_SLIDE = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld {_SLIDE_NS}><p:cSld><p:spTree/></p:cSld>
  <mc:AlternateContent>
    <mc:Choice Requires="p159">
      <p:transition spd="slow" p14:dur="2000"><p159:morph option="byObject"/></p:transition>
    </mc:Choice>
    <mc:Fallback>
      <p:transition spd="slow"><p:fade/></p:transition>
    </mc:Fallback>
  </mc:AlternateContent>
</p:sld>"""

_TIMING_SLIDE = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld {_SLIDE_NS}><p:cSld><p:spTree/></p:cSld>
  <p:timing><p:tnLst><p:par>
    <p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst><p:par>
      <p:cTn id="2" presetID="2" presetClass="entr" presetSubtype="4" fill="hold"
             nodeType="clickEffect" afterEffect="1">
        <p:stCondLst><p:cond delay="0" evt="onClick"/></p:stCondLst>
        <p:childTnLst>
          <p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn dur="500"/></p:cBhvr></p:animEffect>
          <p:animMotion origin="layout" path="M 0 0 L 0.1 0.1 E" pathEditMode="relative"/>
        </p:childTnLst>
      </p:cTn>
    </p:par></p:childTnLst></p:cTn>
  </p:par></p:tnLst>
  <p:bldLst><p:bldP spid="2" grpId="0" build="p"/></p:bldLst></p:timing>
</p:sld>"""


def _oracle_output(tmp_path: Path, readback: list[dict] | None = None) -> Path:
    out_dir = tmp_path / "oracle-out"
    out_dir.mkdir()
    with zipfile.ZipFile(out_dir / "powerpoint-oracle.pptx", "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", _TRANSITION_SLIDE)
        archive.writestr("ppt/slides/slide2.xml", _TIMING_SLIDE)
        archive.writestr("ppt/presentation.xml", f"<p:presentation {_SLIDE_NS}/>")
    if readback is not None:
        lines = [json.dumps(record) for record in readback]
        (out_dir / "powerpoint-readback.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_dir


def test_package_analysis_recovers_what_the_dictionary_cannot_report(tmp_path):
    parsed = parse_oracle_package(_oracle_output(tmp_path) / "powerpoint-oracle.pptx")
    assert parsed["slideCount"] == 2
    assert set(parsed["slides"]) == {"1", "2"}

    choice, fallback = parsed["slides"]["1"]["transition"]
    assert choice["element"] == "p:transition"
    assert choice["alternateContentBranch"] == "Choice"
    assert choice["requires"] == "p159"
    assert choice["attributes"] == {"p14:dur": "2000", "spd": "slow"}
    assert choice["effects"] == [{"element": "p159:morph", "attributes": {"option": "byObject"}}]
    assert fallback["alternateContentBranch"] == "Fallback"
    assert fallback["effects"] == [{"element": "p:fade", "attributes": {}}]

    timing = parsed["slides"]["2"]["timing"]
    presets = [node for node in timing if node["attributes"].get("presetID")]
    assert len(presets) == 1
    preset = presets[0]
    assert preset["attributes"]["presetClass"] == "entr"
    assert preset["attributes"]["presetSubtype"] == "4"
    assert preset["attributes"]["nodeType"] == "clickEffect"
    assert preset["attributes"]["afterEffect"] == "1"
    assert preset["behaviorChildren"] == ["p:animEffect", "p:animMotion"]
    assert any(node["attributes"].get("evt") == "onClick" for node in timing)
    assert any(node["attributes"].get("path") == "M 0 0 L 0.1 0.1 E" for node in timing)
    assert any(node["element"] == "p:bldP" and node["attributes"]["build"] == "p" for node in timing)
    # A wrapper p:cTn with no preset or trigger attribute is noise, not evidence.
    assert all(node["attributes"].get("dur") != "500" for node in timing)


def test_package_analysis_joins_the_readback_and_flags_the_unresolved(tmp_path, capsys):
    readback = [
        {"record": "application", "version": "16.113.1"},
        {"record": "transition", "enum": "EPPEntryEffect", "enumerator": "entry effect morph by object",
         "code": "0x00f60f8d", "slideIndex": 1, "applied": "entry effect morph by object",
         "rejected": False, "resolvedBy": "dictionaryReadBack"},
        {"record": "trigger", "enum": "MsoAnimTriggerType", "enumerator": "on page click",
         "code": "0x01000001", "slideIndex": 2, "applied": None, "rejected": False,
         "resolvedBy": "ooxmlParse"},
        {"record": "afterEffect", "enum": "MsoAnimAfterEffect", "enumerator": "dim", "code": "0x00ff0001",
         "slideIndex": 99, "applied": None, "rejected": False, "resolvedBy": "ooxmlParse"},
    ]
    out_dir = _oracle_output(tmp_path, readback)
    records = read_oracle_readback(out_dir / "powerpoint-readback.jsonl")
    assert len(records) == 4

    merged = merge_oracle_readback(records, parse_oracle_package(out_dir / "powerpoint-oracle.pptx"))
    assert merged["candidateRecords"] == 3, "the application banner carries no enum and is not a candidate"
    by_key = {entry["key"]: entry for entry in merged["candidates"]}
    assert by_key["EPPEntryEffect.entry effect morph by object"]["ooxml"]["transition"][0]["requires"] == "p159"
    trigger = by_key["MsoAnimTriggerType.on page click"]
    assert trigger["dictionaryApplied"] is None and trigger["resolvedBy"] == "ooxmlParse"
    assert any(node["attributes"].get("nodeType") == "clickEffect" for node in trigger["ooxml"]["timing"])
    assert merged["unresolvedCandidates"] == ["MsoAnimAfterEffect.dim"]

    assert main(["--parse-oracle", str(out_dir)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["candidateRecords"] == 3
    assert printed["unresolvedCandidates"] == ["MsoAnimAfterEffect.dim"]


def test_readback_keeps_an_unparsable_line_visible(tmp_path):
    path = tmp_path / "powerpoint-readback.jsonl"
    path.write_text('{"record":"application"}\n\nnot json\n', encoding="utf-8")
    records = read_oracle_readback(path)
    assert len(records) == 2
    assert records[1]["record"] == "unparsed" and records[1]["line"] == 3


# --- the CLI contract -----------------------------------------------------


def test_check_without_the_oracle_is_still_a_complete_structural_check(manifest, catalog):
    assert check(manifest, catalog, None, None) == []
    assert check(manifest, catalog, None, DEFAULT_ORACLE.read_text(encoding="utf-8")) == []


@pytest.mark.skipif(not DEFAULT_SDEF.exists(), reason="PowerPoint 16.113.1 is not installed")
def test_check_require_sdef_inspects_the_oracle_and_fails_on_drift(tmp_path, capsys):
    assert main(["--check", "--require-sdef"]) == 0
    assert capsys.readouterr().out.strip().endswith("OK")

    broken = tmp_path / "powerpoint.applescript"
    broken.write_text(
        DEFAULT_ORACLE.read_text(encoding="utf-8").replace('"entry effect appear"', '"entry effect wrong"', 1),
        encoding="utf-8",
    )
    assert main(["--check", "--require-sdef", "--oracle", str(broken)]) == 1
    printed = capsys.readouterr().out
    assert "not in the local sdef" in printed
    assert "deterministic regeneration" in printed

    missing = tmp_path / "absent.applescript"
    assert main(["--check", "--require-sdef", "--oracle", str(missing)]) == 1
    assert "no oracle script at" in capsys.readouterr().err


# --- the captured scripting oracle, folded into the catalog ----------------
#
# Every expectation below is derived from the checked-in capture rather than
# copied out of it, so changing the evidence changes the test.


@pytest.fixture(scope="module")
def evidence() -> dict:
    return load_oracle_evidence()


@pytest.fixture(scope="module")
def captured(evidence) -> dict:
    """The candidates PowerPoint wrote a transition for, keyed by catalog key."""
    return {
        key: form
        for key, record in evidence.items()
        if (form := oracle_transition_form(record)) is not None
    }


def test_the_capture_is_a_checked_in_generator_input(evidence):
    """``--write`` reads the capture from the fixture directory, so a promoted
    entry is derived from evidence in the repository and ``--check`` fails when
    the two drift apart. All three artefacts are present."""
    for name in (ORACLE_EVIDENCE_MERGED, ORACLE_EVIDENCE_PACKAGE, ORACLE_EVIDENCE_READBACK):
        assert (DEFAULT_ORACLE_EVIDENCE / name).is_file(), name
    assert len(evidence) == 357
    assert {record["enum"] for record in evidence.values()} == {"EPPEntryEffect", "MsoAnimEffect"}


def test_the_merged_evidence_is_the_join_of_the_two_artefacts_beside_it(evidence):
    """The file ``--write`` reads is reproducible from the package and the
    read-back, so the generator input cannot drift from the capture itself."""
    rebuilt = merge_oracle_readback(
        read_oracle_readback(DEFAULT_ORACLE_EVIDENCE / ORACLE_EVIDENCE_READBACK),
        parse_oracle_package(DEFAULT_ORACLE_EVIDENCE / ORACLE_EVIDENCE_PACKAGE),
    )
    checked_in = json.loads(
        (DEFAULT_ORACLE_EVIDENCE / ORACLE_EVIDENCE_MERGED).read_text(encoding="utf-8")
    )
    assert rebuilt == checked_in
    assert rebuilt["slideCount"] == 357


def test_every_captured_transition_is_promoted_and_names_its_evidence(catalog, captured):
    """A promoted entry no longer asks for a read-back that has happened: it
    carries the measured element, drops the capture-required gap, and names the
    package, the read-back, the version and the slide it came from."""
    promoted = [
        entry for entry in catalog["candidates"] if entry.get("verification") == ORACLE_VERIFICATION
    ]
    # Every captured candidate whose entry is an accepted mapping is promoted,
    # except the one whose measured element sdpm cannot select from a parameter
    # set (asserted on its own below). The rest of the captured candidates are
    # the legacy values the catalog holds as outOfScope.
    expected = {
        key for key in captured
        if next(e for e in catalog["candidates"] if e["key"] == key)["status"] == "accepted"
    }
    not_authorable = {
        entry["key"] for entry in catalog["candidates"]
        if entry.get("capture", {}).get("attributeRelation") == "measuredButNotAuthorable"
    }
    assert not_authorable == {"EPPEntryEffect.entry effect wheel reverse 1 spoke"}
    assert {entry["key"] for entry in promoted} == expected - not_authorable
    assert len(promoted) == 156
    for entry in promoted:
        form = captured[entry["key"]]
        ooxml = entry["ooxml"]
        assert ooxml["element"] == form["element"], entry["key"]
        assert "requiresCapture" not in ooxml, entry["key"]
        assert "gap" not in ooxml, entry["key"]
        assert entry["capabilityLevel"] == NATIVE, entry["key"]
        assert entry["evidence"]["fixture"].endswith(ORACLE_EVIDENCE_PACKAGE), entry["key"]
        assert entry["evidence"]["capturedApplicationVersion"] == BASELINE_VERSION, entry["key"]
        capture = entry["capture"]
        assert capture["outcome"] == "transitionWritten", entry["key"]
        assert capture["attributes"] == form["attributes"], entry["key"]
        assert capture["transitionAttributes"] == form["transitionAttributes"], entry["key"]
        assert capture["fallbackElement"] == form["fallbackElement"], entry["key"]
        assert capture["readBack"].endswith(ORACLE_EVIDENCE_READBACK), entry["key"]
        assert capture["slideIndex"] == entry["evidence"]["slideIndex"], entry["key"]


def test_a_promoted_attribute_set_is_the_captured_one_or_states_what_was_left_out(catalog, captured):
    """Attributes are resolved one at a time. A value the capture wrote is the
    value the catalog carries. An attribute the capture left out keeps its
    explicit form - that is what still distinguishes one direction from another
    - and the entry says which attributes those are, so nothing claims to be
    measured that was not."""
    relations: dict[str, int] = {}
    for entry in catalog["candidates"]:
        if entry.get("verification") != ORACLE_VERIFICATION:
            continue
        form, capture, attributes = captured[entry["key"]], entry["capture"], entry["ooxml"]["attributes"]
        relations[capture["attributeRelation"]] = relations.get(capture["attributeRelation"], 0) + 1
        kept = capture.get("keptAttributes", {})
        for name, value in form["attributes"].items():
            assert attributes[name] == value, f"{entry['key']} {name} is not the captured value"
        assert set(attributes) == set(form["attributes"]) | set(kept), entry["key"]
        for name, value in kept.items():
            assert name not in form["attributes"], entry["key"]
            assert attributes[name] == value, entry["key"]
            assert capture["keptAttributesNote"], entry["key"]
        for name, change in capture.get("correctedAttributes", {}).items():
            assert change["captured"] == form["attributes"][name], entry["key"]
            assert change["catalogued"] != change["captured"], entry["key"]
    assert relations == {
        "agrees": 126,
        "keepsOmittedDefaults": 15,
        "correctsValues": 12,
        "correctsValuesAndKeepsOmittedDefaults": 3,
    }


def test_a_kept_attribute_is_never_another_captured_value_s_own_form(catalog, captured):
    """An omitted attribute can only be a restatement of a default while no
    other value of the same element was measured with that exact form.
    ``airplane right`` was written without ``invX``, and ``airplane left`` *was*
    written with ``invX="1"``, so keeping it would give two values one form."""
    measured: dict[str, set[frozenset]] = {}
    for form in captured.values():
        measured.setdefault(form["element"], set()).add(frozenset(form["attributes"].items()))
    conflicts = []
    for entry in catalog["candidates"]:
        if entry.get("verification") != ORACLE_VERIFICATION:
            continue
        ooxml, capture = entry["ooxml"], entry["capture"]
        if capture.get("keptAttributes"):
            assert frozenset(ooxml["attributes"].items()) not in measured[ooxml["element"]], entry["key"]
        if "attributeConflict" in capture:
            conflicts.append(entry["key"])
            assert ooxml["attributes"] == captured[entry["key"]]["attributes"], entry["key"]
    assert conflicts == [
        "EPPEntryEffect.entry effect airplane right",
        "EPPEntryEffect.entry effect glitter hexagon right",
        "EPPEntryEffect.entry effect origami right",
        "EPPEntryEffect.entry effect wind right",
    ]


def test_the_capture_corrects_the_mappings_the_catalog_had_inferred_from_names(catalog, captured):
    """The catalog had read a direction off the enumerator's name. PowerPoint
    disagrees for 16 values, and the measurement wins."""
    corrected = {
        entry["key"]: entry["capture"]["correctedAttributes"]
        for entry in catalog["candidates"]
        if entry.get("capture", {}).get("correctedAttributes")
    }
    assert len(corrected) == 15
    assert corrected["EPPEntryEffect.entry effect cube right"] == {
        "dir": {"catalogued": "r", "captured": "u"}
    }
    assert corrected["EPPEntryEffect.entry effect cube up"] == {
        "dir": {"catalogued": "u", "captured": "r"}
    }

def test_a_measured_form_sdpm_cannot_select_is_recorded_and_still_refused(catalog, captured):
    """The one value whose element itself was wrong, and which the measurement
    does not make authorable.

    The catalog had the reversed Clock variant as a ``reverse`` attribute on
    the standard ``p:wheel``. PowerPoint writes ``<p14:wheelReverse
    spokes="1"/>``: "reverse" is the element name, and no attribute carries it.
    sdpm's transition JSON selects a value by its parameters, so the measured
    form cannot be reached from one - promoting it would either emit an
    attribute the element does not have or collapse the value onto the plain
    Clock tile, which writes a different element. The entry records the
    measurement and stays refused, which is a different gap from a missing
    capture and says so.
    """
    key = "EPPEntryEffect.entry effect wheel reverse 1 spoke"
    wheel = next(entry for entry in catalog["candidates"] if entry["key"] == key)
    assert wheel["capture"]["attributeRelation"] == "measuredButNotAuthorable"
    assert wheel["capture"]["element"] == captured[key]["element"] == "p14:wheelReverse"
    assert wheel["capture"]["attributes"] == captured[key]["attributes"] == {"spokes": "1"}
    assert "semantic model that can select an element" in wheel["capture"]["notPromoted"]
    # Not promoted: the mapping the writer would use is untouched, the entry is
    # still refused, and its gap names the measurement instead of asking for
    # the read-back that has already happened.
    assert wheel["ooxml"]["element"] == "p:wheel"
    assert wheel["ooxml"]["attributes"] == {"spokes": "1", "reverse": "1"}
    assert "requiresCapture" not in wheel["ooxml"]
    assert "p14:wheelReverse" in wheel["ooxml"]["gap"]
    assert wheel["capabilityLevel"] == SEMANTIC
    assert wheel["verification"] == "powerPointReadBackRequired"


def test_a_promoted_entry_keeps_its_semantic_json_in_step_with_its_ooxml(catalog):
    """The semantic parameters are the ones the writer will emit, and no
    transition entry claims a default duration its own ooxml does not record.
    That second rule is the one the gallery tiles' ``durationMs: 500`` broke."""
    for entry in catalog["candidates"]:
        transition = (entry.get("semanticJson") or {}).get("transition")
        if not isinstance(transition, dict) or "element" not in (entry.get("ooxml") or {}):
            continue
        ooxml = entry["ooxml"]
        if entry["key"].startswith("EPPEntryEffect.") and "attributes" in ooxml:
            expected = dict(ooxml["attributes"])
            if transition["effect"] == "morph":
                expected = {"variant": expected["option"]}
            assert transition["parameters"] == expected, entry["key"]
        if ooxml.get("defaultDurationMs") is not None:
            assert transition["durationMs"] == ooxml["defaultDurationMs"], entry["key"]
        else:
            assert ooxml.get("durationEvidence"), (
                f"{entry['key']} records no default duration and does not say so"
            )


def test_the_capture_does_not_establish_a_per_effect_default_duration(catalog, captured):
    """The probe set each slide's entry effect and nothing else, so the
    duration it read back is the one the script-created probe slide already
    held: all 160 captured transitions carry the same ``p14:dur``, while the
    native tile captures record 22 different defaults, and Box is 1600 in both
    the tile capture and the Transitions ribbon. The capture is recorded as the
    probe-context duration and ``defaultDurationMs`` is left alone."""
    durations = {form["transitionAttributes"].get("p14:dur") for form in captured.values()}
    speeds = {form["transitionAttributes"].get("spd") for form in captured.values()}
    assert durations == {"2000"} and speeds == {"slow"}, (
        "a per-effect duration would vary between effects"
    )
    oracle = catalog["provenance"]["scriptingOracle"]
    assert oracle["transitionDurationObserved"] == ["2000"]
    assert "not the effect's own default" in oracle["transitionDurationEvidence"]
    box = next(e for e in catalog["candidates"] if e["key"] == "EPPEntryEffect.entry effect box down")
    assert box["ooxml"]["defaultDurationMs"] == 1600
    assert box["semanticJson"]["transition"]["durationMs"] == 1600
    assert box["capture"]["transitionAttributes"]["p14:dur"] == "2000"
    defaults = {
        entry["ooxml"].get("defaultDurationMs")
        for entry in catalog["candidates"]
        if entry.get("ooxml", {}).get("defaultDurationMs")
    }
    assert len(defaults) > 1 and 2000 in defaults


def test_every_rejection_is_recorded_with_the_reason_powerpoint_gave(catalog, evidence):
    """A refused candidate is probed evidence, not an unprobed one, and the two
    refusal families are classified rather than left looking like gaps."""
    rejected = {key for key, record in evidence.items() if record["rejected"]}
    assert len(rejected) == 196
    entries = {entry["key"]: entry for entry in catalog["candidates"]}
    animation, legacy = [], []
    for key in rejected:
        capture = entries[key]["capture"]
        assert capture["outcome"] == "rejectedByPowerPoint", key
        assert capture["error"] == evidence[key]["error"], key
        assert capture["error"].strip(), key
        (animation if key.startswith("MsoAnimEffect.") else legacy).append(key)
    assert len(animation) == 150 and len(legacy) == 46
    # The animation half captured nothing at all, for one reason.
    assert {
        "doesn\u2019t understand the \u201cadd effect\u201d message" in entries[key]["capture"]["error"]
        for key in animation
    } == {True}
    assert all(not entries[key]["capture"].get("element") for key in animation)
    assert {entries[key]["capture"]["classification"] for key in animation} == {
        "the dictionary does not implement add effect on main sequence in this build, so no animation value "
        "could be applied at all; this says nothing about the value's OOXML mapping"
    }
    # A refused entry effect mostly confirms a classification the catalog
    # already carried: the 0x00f60d** per-shape band and the 'unset' sentinel.
    unsurprising = [key for key in legacy if entries[key]["status"] in ("outOfScope", "rejected")]
    assert len(unsurprising) == 43
    assert {entries[key]["guiKey"] for key in unsurprising} == {
        "animation.legacyShapeEntryEffect", "transition.gallery.none"
    }
    # Three refusals do contradict the catalog, which accepts a p14:flash
    # mapping for values PowerPoint will not set. The refusal is evidence about
    # the enumerator rather than about the element, so the entry records the
    # contradiction instead of resolving it in either direction.
    contradicting = sorted(key for key in legacy if entries[key]["status"] == "accepted")
    assert contradicting == [
        "EPPEntryEffect.entry effect flash once fast",
        "EPPEntryEffect.entry effect flash once medium",
        "EPPEntryEffect.entry effect flash once slow",
    ]
    for key in contradicting:
        assert entries[key]["ooxml"]["element"] == "p14:flash"
        assert "contradictsAcceptedMapping" in entries[key]["capture"]
        assert "computer-use.md" in entries[key]["capture"]["contradictsAcceptedMapping"]


def test_the_capture_confirms_that_none_persists_nothing(catalog, evidence):
    """The one candidate PowerPoint accepted without writing anything. The
    catalog already said so; now it is measured."""
    silent = [key for key, record in evidence.items()
              if not record["rejected"] and oracle_transition_form(record) is None]
    assert silent == ["EPPEntryEffect.entry effect none"]
    entry = next(e for e in catalog["candidates"] if e["key"] == silent[0])
    assert entry["status"] == "nonPersisted"
    assert entry["capture"]["outcome"] == "appliedWithoutPersistedForm"


def test_a_value_powerpoint_substituted_says_so(catalog, evidence):
    """``entry effect appear`` is applied as ``entry effect cut``, so its
    written form belongs to Cut. An entry whose read-back names a different
    value records that rather than claiming the form as its own."""
    coerced = {
        key for key, record in evidence.items()
        if record["dictionaryApplied"] not in (None, record["enumerator"])
    }
    entries = {entry["key"]: entry for entry in catalog["candidates"]}
    assert "EPPEntryEffect.entry effect appear" in coerced
    for key in coerced:
        assert entries[key]["capture"]["coercedByPowerPoint"], key
        assert entries[key]["capture"]["dictionaryApplied"] == evidence[key]["dictionaryApplied"], key


def test_the_enumerations_the_capture_never_reached_claim_nothing(catalog, evidence):
    """The run aborted before six of the eight enumerations, and the catalog
    says which, instead of leaving their entries looking probed."""
    oracle = catalog["provenance"]["scriptingOracle"]
    assert oracle["probedEnumerations"] == ["EPPEntryEffect", "MsoAnimEffect"]
    assert set(oracle["unprobedEnumerations"]) == set(CANDIDATE_ENUMS) - {"EPPEntryEffect", "MsoAnimEffect"}
    for entry in catalog["candidates"]:
        if entry["enum"] in oracle["unprobedEnumerations"]:
            assert "capture" not in entry, entry["key"]
        else:
            assert entry["key"] in evidence
            assert "capture" in entry, entry["key"]


def test_the_catalog_no_longer_says_powerpoint_was_never_driven(catalog):
    """The provenance used to say the oracle had never been executed. It has."""
    automation = catalog["provenance"]["powerPointAutomation"]
    assert "never executed" not in automation
    assert "-10004" in automation, "the sandbox still cannot drive PowerPoint, and that still matters"
    assert ORACLE_VERIFICATION in automation
    assert "VBA is not used" in automation
    summary = catalog["summary"]["scriptingOracleCapture"]
    assert summary == {
        "probed": 357,
        "transitionWritten": 160,
        "rejectedByPowerPoint": 196,
        "appliedWithoutPersistedForm": 1,
        "promoted": 156,
    }


def test_check_detects_a_catalog_that_drifts_from_the_capture(manifest, catalog):
    """``--check`` compares the catalog against a regeneration that reads the
    capture, so editing a promoted value by hand fails."""
    broken = json.loads(json.dumps(catalog))
    target = next(
        entry for entry in broken["candidates"] if entry.get("verification") == ORACLE_VERIFICATION
    )
    target["ooxml"]["attributes"] = {"dir": "nonsense"}
    sdef_enums = read_sdef(DEFAULT_SDEF) if DEFAULT_SDEF.exists() else None
    if sdef_enums is None:
        pytest.skip("PowerPoint 16.113.1 is not installed")
    assert any("deterministic regeneration" in finding for finding in check(manifest, broken, sdef_enums))
