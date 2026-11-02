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


# --- the GUI capture of the animation surface ------------------------------
@pytest.fixture(scope="module")
def gui_capture() -> dict:
    from scripts.animation_catalog.generate import load_gui_capture_evidence

    return load_gui_capture_evidence()


def test_the_gui_capture_covers_every_gui_addressable_animation_value(gui_capture):
    """76 values, each joined to its effect by the spid the driver verified."""
    # 76 from the 2026-11-01 batch plus the 7 Complex motion paths, which the
    # catalog had no key for until the Path Animation popup was read.
    assert len(gui_capture) == 83
    assert all("effect" in record for record in gui_capture.values())
    assert all(
        record["attributedSpid"] == record["shapeSpid"] for record in gui_capture.values()
    ), "a record joined to an effect on another shape"
    assert {key.split(".")[2] for key in gui_capture} == {
        "entrance", "exit", "emphasis", "motionPath",
    }


def test_every_captured_value_is_promoted_with_its_measured_behaviours(catalog, gui_capture):
    """The payload gap is closed by transcription, not by inference.

    Each promoted entry carries the behaviours **in document order with
    duplicates**, because 57 of the 76 effects repeat an element and a set keyed
    by element name cannot express them.
    """
    entries = {entry["key"]: entry for entry in catalog["guiItems"]}
    repeated = 0
    for key, record in gui_capture.items():
        ooxml = entries[key]["ooxml"]
        assert entries[key]["verification"] == "guiCapture", key
        assert "requiresCapture" not in ooxml and "gap" not in ooxml, key
        assert "unresolvedPayloads" not in ooxml, key
        measured = [behavior["element"] for behavior in record["effect"]["behaviors"]]
        assert [behavior["element"] for behavior in ooxml["behaviors"]] == measured, key
        assert ooxml["behaviorChildren"] == sorted(set(measured)), key
        if len(measured) != len(set(measured)):
            repeated += 1
    assert repeated == 57, "the ordered list is what these entries need"


def test_a_promoted_entry_states_the_duration_its_timings_belong_to(catalog, gui_capture):
    """And whether they can be scaled, which two of them cannot."""
    entries = {entry["key"]: entry for entry in catalog["guiItems"]}
    scalable = [
        key for key in gui_capture
        if entries[key]["ooxml"]["durationScaling"]["rule"] == "proportional"
    ]
    fixed = [
        key for key in gui_capture
        if entries[key]["ooxml"]["durationScaling"]["rule"] == "notScalable"
    ]
    assert len(scalable) + len(fixed) == 83
    assert sorted(fixed) == [
        "animation.gallery.emphasis.boldReveal",
        "animation.gallery.emphasis.transparency",
    ]
    for key in scalable:
        ooxml = entries[key]["ooxml"]
        assert isinstance(ooxml["measuredDurationMs"], int) and ooxml["measuredDurationMs"] > 0
        # The entry's own example asks for exactly what was measured, so
        # following the catalog reproduces the measured bytes.
        effect = entries[key]["semanticJson"]["animations"]["mainSequence"][0]
        assert effect["timing"]["durationMs"] == ooxml["measuredDurationMs"], key
        assert "1 ms" in ooxml["durationScaling"]["accuracy"]
    for key in fixed:
        assert entries[key]["ooxml"]["measuredDurationMs"] is None
        effect = entries[key]["semanticJson"]["animations"]["mainSequence"][0]
        assert effect["timing"]["durationMs"] is None


def test_the_capture_confirms_the_identifiers_rather_than_replacing_them(catalog, gui_capture):
    """71 agree with the catalog; the 5 motion paths had no presetId at all.

    Worth pinning because the first reading of this comparison was wrong: it
    read ``ooxml.attributes.presetID``, which animation entries do not carry,
    and reported all 76 as filling an empty field.
    """
    entries = {entry["key"]: entry for entry in catalog["guiItems"]}
    relations: dict[str, int] = {}
    for key in gui_capture:
        relation = entries[key]["capture"]["identifierRelation"]
        relations[relation] = relations.get(relation, 0) + 1
    # The 7 Complex paths join the 5 Basic ones in having had no catalogued
    # identifier at all: a motion path's presetID was never in the evidence the
    # catalog was built from, so every one of the 12 is a first measurement.
    assert relations == {"confirmsCatalogued": 71, "measuredWhereNoneWasRecorded": 12}


def test_the_measured_motion_paths_are_the_five_gallery_groups(catalog, gui_capture):
    entries = {entry["key"]: entry for entry in catalog["guiItems"]}
    lines = entries["animation.gallery.motionPath.lines"]["ooxml"]
    assert lines["presetId"] == 42 and lines["presetClass"] == "path"
    assert lines["behaviors"][0]["attributes"]["path"] == "M 0 0 L 0 0.25 E"
    assert lines["behaviors"][0]["attrNames"] == ["ppt_x", "ppt_y"]
    assert all(
        entries[f"animation.gallery.motionPath.{group}"]["ooxml"]["behaviors"][0]["element"]
        == "p:animMotion"
        for group in ("lines", "arcs", "turns", "shapes", "loops")
    )


# --- the fixtures are published, so they must name nobody -------------------
def test_no_captured_package_names_a_person():
    """Every `.pptx` fixture was saved by PowerPoint, which records who saved it.

    This repository is public. An audit before the first push found **all seven**
    committed packages carrying `cp:lastModifiedBy`, and two carrying
    `dc:creator`, with a maintainer's full name in both. The packages are
    evidence and are kept; the authorship metadata is not.

    This test is the guard, not the fix: a fixture added from a fresh capture
    arrives unscrubbed, so without it the name comes back on the next batch.
    Run `scripts/animation_catalog/scrub_evidence.py --write` to clear it.
    """
    from scripts.animation_catalog.scrub_evidence import (
        DEFAULT_ROOT,
        identities_in,
        packages,
    )

    found = packages(DEFAULT_ROOT)
    assert found, "no captured packages found, so this guard is checking nothing"
    carrying = {
        path.relative_to(REPO_ROOT).as_posix(): identities_in(path) for path in found
    }
    named = {path: fields for path, fields in carrying.items() if fields}
    assert not named, (
        "captured packages name a person; run "
        f"scripts/animation_catalog/scrub_evidence.py --write: {named}"
    )


def test_the_scrub_empties_the_identity_and_leaves_the_evidence(tmp_path):
    """Scrubbing must not touch the OOXML the capture measured.

    A scrub that changed more than authorship would quietly corrupt a
    measurement, which is worse than the leak it fixes — so the effects are
    counted before and after, and the identity is checked gone.
    """
    import shutil

    from scripts.animation_catalog.generate import parse_gui_capture_package
    from scripts.animation_catalog.scrub_evidence import identities_in, scrub

    source = (
        REPO_ROOT / "tests" / "fixtures" / "animations" / "gui-only"
        / "batch-2026-11-01-complete" / "powerpoint-oracle.pptx"
    )
    package = tmp_path / "copy.pptx"
    shutil.copy2(source, package)
    before = parse_gui_capture_package(package)

    # Put an identity back, so the scrub has something to remove even though the
    # committed fixture is already clean.
    import re
    import zipfile

    with zipfile.ZipFile(package) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as out:
        for info, blob in entries:
            if info.filename == "docProps/core.xml":
                blob = re.sub(
                    r"<cp:lastModifiedBy></cp:lastModifiedBy>",
                    "<cp:lastModifiedBy>Someone Real</cp:lastModifiedBy>",
                    blob.decode("utf-8"),
                ).encode("utf-8")
            out.writestr(info, blob)
    assert identities_in(package) == {"cp:lastModifiedBy": "Someone Real"}

    removed = scrub(package)
    assert removed == {"cp:lastModifiedBy": "Someone Real"}
    assert identities_in(package) == {}
    after = parse_gui_capture_package(package)
    assert set(after) == set(before), "the scrub changed which shapes carry effects"
    assert after == before, "the scrub changed a measured effect"

# --- an effect option must be measured, not defaulted ----------------------
def test_every_effect_option_is_measured_and_no_two_values_agree():
    """All 133 effect-option values are measured, and each is distinguishable.

    A press inside PowerPoint's `Effect Options` window is intermittent: it
    reaches the control and the application does not always act on it, leaving
    the effect at its default. The capture could not tell that apart from a
    value that genuinely equals the default, so three values read wrong for a
    while — `flyIn` From Right as `presetSubtype` 4 (From Bottom's),
    `stretch` From Top as 10 (Across's), and `transparency` 25% as
    `opacity: 0.5` (50%'s).

    Two values of one setting cannot produce the same OOXML, so a collision is
    the signal. This is the guard against a defaulted reading reaching the
    catalog, which is the only place the error would be invisible.
    """
    from scripts.animation_catalog.effect_options_merge import (
        DEFAULT_PLAN,
        DEFAULT_RESOLVED,
        build,
    )

    captures = [path for path in DEFAULT_RESOLVED if path.exists()]
    assert captures, "no effect-option captures found, so this guard checks nothing"
    document = build(DEFAULT_PLAN, captures)

    assert document["missing"] == [], (
        "effect-option values were planned but never measured; re-capture them with "
        "--only and --verify-change"
    )
    assert document["collisions"] == [], (
        "two values of one setting produced identical OOXML, so at least one press did "
        f"not take: {document['collisions']}"
    )
    assert document["counts"]["measured"] == document["counts"]["planned"] == 133


def test_the_merge_rejects_a_value_equal_to_its_sibling():
    """The collision check has to fail when a press did not take.

    Asserting only on the clean fixtures would pass just as well if the check
    were `return []`, so this feeds it a known-bad pair: one value rewritten to
    carry its sibling's OOXML, which is exactly what a press that did not take
    leaves behind.
    """
    from scripts.animation_catalog.effect_options_merge import collisions

    fly_in = {
        "effectKey": "animation.gallery.entrance.flyIn",
        "setting": "Direction",
        "effectAttributes": {"presetID": "2", "presetSubtype": "4"},
        "behaviors": [{"element": "p:anim", "attrNames": ["ppt_y"]}],
    }
    merged = {
        "fromBottom": {**fly_in, "value": "From Bottom"},
        # The defaulted reading: a different direction, identical OOXML.
        "fromRight": {**fly_in, "value": "From Right"},
        # A different setting of the same effect must not be dragged in.
        "across": {
            **fly_in,
            "effectKey": "animation.gallery.entrance.stretch",
            "value": "Across",
        },
    }
    found = collisions(merged)
    assert len(found) == 1, found
    assert found[0]["values"] == ["From Bottom", "From Right"]
    assert found[0]["effectKey"] == "animation.gallery.entrance.flyIn"


def test_spin_direction_is_measured_even_though_its_subtype_does_not_move():
    """Some settings live in the behaviours, so the check cannot read presets alone.

    `Spin`'s Clockwise and Counterclockwise both carry `presetSubtype 0` and
    differ only in the sign of `p:animRot/@by`. A collision check comparing
    preset attributes would call this pair a failed press when it is measured
    correctly, which is why the signature covers the behaviours too.
    """
    from scripts.animation_catalog.effect_options_merge import (
        DEFAULT_PLAN,
        DEFAULT_RESOLVED,
        build,
    )

    document = build(DEFAULT_PLAN, [p for p in DEFAULT_RESOLVED if p.exists()])
    spin = {
        target["value"]: target
        for target in document["targets"]
        if target["effectKey"] == "animation.gallery.emphasis.spin"
        and target["setting"] == "Direction"
    }
    assert set(spin) == {"Clockwise", "Counterclockwise"}
    subtypes = {t["effectAttributes"].get("presetSubtype") for t in spin.values()}
    assert subtypes == {"0"}, f"expected the subtype not to carry direction, got {subtypes}"

    def rotation(target):
        return [
            behaviour["attributes"]["by"]
            for behaviour in target["behaviors"]
            if behaviour["element"] == "p:animRot"
        ]

    assert rotation(spin["Clockwise"]) == ["21600000"]
    assert rotation(spin["Counterclockwise"]) == ["-21600000"]


# --- preset.options: the measured Effect Options values -------------------
def _options_slide(preset):
    """Write one preset onto the catalog slide and return (node, re-imported motion)."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts" / "animation_catalog"))
    import accept as acceptance

    from sdpm.engine.timing import CATALOG_TARGET_ID, TimingWriter, load_capability_index
    from sdpm.engine.timing.reader import read_slide_motion

    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    slide, registry, _spids = acceptance.catalog_slide()
    node = TimingWriter(registry, index=index, slide_slug="catalog").build(
        {
            "mainSequence": [
                {
                    "id": "e1",
                    "target": {"element": CATALOG_TARGET_ID},
                    "preset": preset,
                    "start": {"type": "onPageClick", "delayMs": 0},
                }
            ],
            "interactiveSequences": [],
        }
    )
    slide.append(node)
    return node, read_slide_motion(slide, slide_slug="catalog", index=index)


def _written_subtype(node):
    import lxml.etree as etree

    for ctn in node.iter():
        if etree.QName(ctn).localname == "cTn" and ctn.get("presetID") is not None:
            return ctn.get("presetSubtype")
    return None


def _payloads(node, element):
    import lxml.etree as etree

    local = element.split(":")[-1]
    return [
        n.get("by") or n.get("prLst") or n.get("filter") or ""
        for n in node.iter()
        if etree.QName(n).localname == local
    ]


def test_every_measured_effect_option_writes_the_bytes_it_measured():
    """All 133 values write, and each writes its own measured presetSubtype.

    This is the claim `preset.options` makes, and it is the one worth guarding:
    the failure it prevents is the writer emitting the tile's **default** while
    accepting a request for something else, which is what `preset.variant` did
    before it was removed and what three of the captures themselves did before
    the verify gate.
    """
    from sdpm.engine.timing import load_capability_index

    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    checked = 0
    wrong: list[str] = []
    for entry in sorted(index.items.values(), key=lambda e: e.key):
        options = entry.ooxml.get("effectOptions")
        if not options:
            continue
        semantic = (
            (entry.semantic.get("animations") or {}).get("mainSequence") or [{}]
        )[0].get("preset") or {}
        for setting, option in sorted(options.items()):
            for value, measured in sorted((option.get("values") or {}).items()):
                node, _motion = _options_slide(
                    {
                        "category": semantic.get("category"),
                        "effect": semantic.get("effect"),
                        "options": {setting: value},
                    }
                )
                got = _written_subtype(node)
                if str(measured.get("presetSubtype")) != str(got):
                    wrong.append(
                        f"{entry.key} {setting}={value}: wrote presetSubtype {got}, "
                        f"measured {measured.get('presetSubtype')}"
                    )
                checked += 1
    assert not wrong, wrong
    assert checked == 133, f"expected the 133 measured options, walked {checked}"


def test_an_option_whose_subtype_identifies_it_reads_back_as_itself():
    """A non-default option must survive JSON -> PPTX -> JSON.

    Fly In's `From Right` is `presetSubtype` 2 and, before this, no catalog
    entry claimed subtype 2 at all — so the reader rejected the effect outright
    and dropped the whole slide's animations to the raw fallback. The option
    tokens in the reverse index are what fixed that, which is why reading back
    is asserted and not only writing.
    """
    for value in ("fromRight", "fromTop", "fromLeft", "fromTopRight", "fromBottomLeft"):
        _node, motion = _options_slide(
            {"category": "entrance", "effect": "flyIn", "options": {"direction": value}}
        )
        effects = (motion.animations or {}).get("mainSequence") or []
        assert effects, f"{value} produced no importable effect"
        assert effects[0]["preset"].get("options") == {"direction": value}


def test_the_default_option_and_no_option_both_read_back_without_options():
    """`options` is omitted, not nulled, when the effect is at its default.

    Otherwise JSON written without options would not equal the JSON read back
    from it, and every existing preset entry would stop round-tripping.
    """
    from sdpm.engine.timing import load_capability_index

    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    default = index.items["animation.gallery.entrance.flyIn"].ooxml["effectOptions"][
        "direction"
    ]["default"]
    assert default == "fromBottom"
    for preset in (
        {"category": "entrance", "effect": "flyIn"},
        {"category": "entrance", "effect": "flyIn", "options": {"direction": default}},
    ):
        _node, motion = _options_slide(preset)
        effects = (motion.animations or {}).get("mainSequence") or []
        assert effects
        assert "options" not in effects[0]["preset"]


def test_a_setting_carried_only_by_behaviours_still_writes_the_right_bytes():
    """Spin's direction is the sign of `p:animRot/@by`, not a subtype.

    Both its values carry `presetSubtype` 0, so an overlay that applied only
    the subtype would write Clockwise for both. 9 of the 37 measured groups are
    like this, which is why the overlay replaces the behaviours too.
    """
    for value, want in (("clockwise", "21600000"), ("counterclockwise", "-21600000")):
        node, _motion = _options_slide(
            {"category": "emphasis", "effect": "spin", "options": {"direction": value}}
        )
        assert _written_subtype(node) == "0"
        assert want in _payloads(node, "p:animRot"), _payloads(node, "p:animRot")
    for value, want in (
        ("quarterSpin", "5400000"),
        ("halfSpin", "10800000"),
        ("twoSpins", "43200000"),
    ):
        node, _motion = _options_slide(
            {"category": "emphasis", "effect": "spin", "options": {"amount": value}}
        )
        assert want in _payloads(node, "p:animRot")


def test_options_refuses_what_it_cannot_measure():
    """Each refusal, including the two that are easy to get wrong.

    `variant` is refused rather than ignored, because a document that still
    sets it is asking for a direction that would silently become the default.
    Two settings at once are refused because each value was measured with the
    other setting left at its default: composing Spin's sign from one and its
    magnitude from the other would emit bytes PowerPoint was never seen to
    write.
    """
    from sdpm.engine.timing import CapabilityGapError, MotionWriteError

    with pytest.raises(MotionWriteError, match="no longer a field"):
        _options_slide({"category": "entrance", "effect": "flyIn", "variant": "right"})
    # A null one asked for nothing. The catalog's own examples all spelled it
    # that way, so failing it would break documents written against them to
    # report a field they are not using.
    _node, motion = _options_slide(
        {"category": "entrance", "effect": "flyIn", "variant": None}
    )
    effects = (motion.animations or {}).get("mainSequence") or []
    assert effects and "variant" not in effects[0]["preset"]
    with pytest.raises(MotionWriteError, match="is not a setting"):
        _options_slide(
            {"category": "entrance", "effect": "flyIn", "options": {"spokes": "spoke1"}}
        )
    with pytest.raises(MotionWriteError, match="is not a measured value"):
        _options_slide(
            {"category": "entrance", "effect": "flyIn", "options": {"direction": "sideways"}}
        )
    with pytest.raises(MotionWriteError, match="offers no effect options"):
        _options_slide(
            {"category": "entrance", "effect": "appear", "options": {"direction": "fromRight"}}
        )
    with pytest.raises(CapabilityGapError, match="not measured"):
        _options_slide(
            {
                "category": "emphasis",
                "effect": "spin",
                "options": {"direction": "counterclockwise", "amount": "twoSpins"},
            }
        )


def test_a_retired_scripting_direction_name_is_refused_with_the_reason():
    """The 45 `MsoAnimDirection` names were `variant`'s vocabulary, so they will be tried.

    `right` is one of them and is not a Fly In direction label, so the plain
    "not a measured value" error would leave a reader guessing. The refusal
    quotes the enumerator's own catalog gap instead.
    """
    from sdpm.engine.timing import CapabilityGapError

    with pytest.raises(CapabilityGapError, match="not sdpm's input vocabulary"):
        _options_slide(
            {"category": "entrance", "effect": "flyIn", "options": {"direction": "right"}}
        )


def test_every_measured_effect_option_reads_back_as_itself():
    """All 133 round-trip, which needs two different ways of recognising one.

    87 of them change `presetSubtype` and are found by it. The other 46 do not:
    Spin's two directions are both subtype 0, Grow/Shrink's amounts differ only
    in `p:animScale/p:by`, Transparency's in `p:animEffect/@prLst`. Those are
    found by comparing the behaviours, which is exact rather than approximate
    because the writer transcribes them.

    A value equal to its effect's default reads back **without** `options`, and
    that counts as a round-trip: it is the same JSON that was written.
    """
    from sdpm.engine.timing import load_capability_index

    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    explicit = 0
    as_default = 0
    failures: list[str] = []
    for entry in sorted(index.items.values(), key=lambda e: e.key):
        options = entry.ooxml.get("effectOptions")
        if not options:
            continue
        semantic = (
            (entry.semantic.get("animations") or {}).get("mainSequence") or [{}]
        )[0].get("preset") or {}
        for setting, option in sorted(options.items()):
            for value in sorted((option.get("values") or {})):
                _node, motion = _options_slide(
                    {
                        "category": semantic.get("category"),
                        "effect": semantic.get("effect"),
                        "options": {setting: value},
                    }
                )
                effects = (motion.animations or {}).get("mainSequence") or []
                if not effects:
                    failures.append(f"{entry.key} {setting}={value}: did not import at all")
                    continue
                got = effects[0]["preset"].get("options")
                if got == {setting: value}:
                    explicit += 1
                elif got is None and value == option.get("default"):
                    as_default += 1
                else:
                    failures.append(f"{entry.key} {setting}={value}: read {got}")
    assert not failures, failures
    assert explicit + as_default == 133, (explicit, as_default)
    assert as_default == 37, f"one default per setting, got {as_default}"


def test_an_option_only_the_behaviours_identify_reads_back():
    """The cases the subtype cannot distinguish, named individually.

    Each of these pairs carries one `presetSubtype` across both values, so
    before the behaviour comparison they imported as the effect's default and
    the asked-for value was lost.
    """
    for preset, option in (
        ({"category": "emphasis", "effect": "spin"}, {"direction": "counterclockwise"}),
        ({"category": "emphasis", "effect": "spin"}, {"amount": "twoSpins"}),
        ({"category": "emphasis", "effect": "growShrink"}, {"direction": "vertical"}),
        ({"category": "emphasis", "effect": "growShrink"}, {"amount": "tiny"}),
        ({"category": "emphasis", "effect": "transparency"}, {"amount": "percent25"}),
        ({"category": "entrance", "effect": "floatIn"}, {"direction": "floatDown"}),
        ({"category": "exit", "effect": "floatOut"}, {"direction": "floatUp"}),
        ({"category": "entrance", "effect": "shape"}, {"shapes": "diamond"}),
        ({"category": "exit", "effect": "shape"}, {"shapes": "plus"}),
    ):
        _node, motion = _options_slide({**preset, "options": option})
        effects = (motion.animations or {}).get("mainSequence") or []
        assert effects, f"{preset} {option} did not import"
        assert effects[0]["preset"].get("options") == option, (
            f"{preset} {option} read {effects[0]['preset'].get('options')}"
        )


def test_an_effect_asked_for_without_options_never_reads_back_with_them():
    """The behaviour comparison must not label a plain effect.

    A setting's default has the same bytes as the effect alone, so registering
    it for comparison would make every plain preset read back carrying an
    option it was not asked for — and the 248 invertible catalog entries would
    stop round-tripping. The default is excluded for exactly that reason, and
    this is the guard.
    """
    from sdpm.engine.timing import MotionWriteError, load_capability_index

    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    labelled: list[str] = []
    checked = 0
    for entry in sorted(index.items.values(), key=lambda e: e.key):
        if not entry.ooxml.get("effectOptions"):
            continue
        semantic = (
            (entry.semantic.get("animations") or {}).get("mainSequence") or [{}]
        )[0].get("preset") or {}
        try:
            _node, motion = _options_slide(
                {"category": semantic.get("category"), "effect": semantic.get("effect")}
            )
        except MotionWriteError:
            # Eight exit tiles need an explicit duration to derive the
            # visibility delay. Unrelated to options, and covered by accept.py
            # through the catalog's own examples, which carry one.
            continue
        effects = (motion.animations or {}).get("mainSequence") or []
        checked += 1
        if effects and effects[0]["preset"].get("options") is not None:
            labelled.append(f"{entry.key}: read {effects[0]['preset']['options']}")
    assert not labelled, labelled
    assert checked >= 17, f"only {checked} plain forms were exercised"


def test_shape_takes_its_default_from_its_sibling_setting():
    """Circle is derived from measurement, not assumed.

    `Shape` has no measured behaviours of its own and all four of its shapes
    carry the tile's subtype, because the shape lives in
    `p:animEffect/@filter`. So neither the signature nor the subtype rule can
    say which is the default. Its `Direction` default did resolve, and pressing
    a setting's default leaves the effect at the tile's default — so
    `direction=in`'s bytes are the tile's bytes, and they are `circle(in)`.
    """
    from sdpm.engine.timing import load_capability_index

    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    for key, direction in (
        ("animation.gallery.entrance.shape", "in"),
        ("animation.gallery.exit.shape", "out"),
    ):
        options = index.items[key].ooxml["effectOptions"]
        assert options["direction"]["default"] == direction
        shapes = options["shapes"]
        assert shapes["default"] == "circle"
        assert shapes["defaultResolvedBy"] == "siblingSetting"
        # The derivation itself: the sibling default and circle are the same bytes.
        reference = options["direction"]["values"][direction]["behaviors"]
        assert [
            b.get("attributes", {}).get("filter") for b in reference
        ] == [
            b.get("attributes", {}).get("filter")
            for b in shapes["values"]["circle"]["behaviors"]
        ]
    # And every setting now has a default, so nothing is left unresolvable.
    unresolved = [
        f"{entry.key} {setting}"
        for entry in index.items.values()
        for setting, option in (entry.ooxml.get("effectOptions") or {}).items()
        if option.get("default") is None
    ]
    assert not unresolved, unresolved


def test_an_entry_no_json_can_ask_for_is_not_counted_as_awaiting_capture():
    """The capture-required total has to be able to reach zero.

    The 45 `MsoAnimDirection` enumerators, in both the item and candidate
    groups, record a scripting name that no sdpm JSON can ask for: a direction
    is measured per effect and written as `preset.options.direction`, and the
    enumerator name does not identify a `presetSubtype`. Counting them as
    "awaiting a PowerPoint read-back" asserts the opposite of their own
    recorded gap, and it made the total permanently non-zero — so it stopped
    measuring anything.
    """
    from sdpm.engine.timing import load_capability_index
    from sdpm.engine.timing.writer import catalog_coverage

    catalog = json.loads(
        (REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json").read_text()
    )
    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    records = catalog_coverage(index, catalog=catalog)
    flagged = {record.key for record in records if record.no_sdpm_input}
    assert len(flagged) == 90, sorted(flagged)[:5]
    assert all(
        key.startswith("MsoAnimDirection.")
        or key.startswith("animation.effectOptions.direction.")
        for key in flagged
    ), sorted(flagged)[:5]
    # Every one is still refused by the writer: not an input is not the same as
    # writable, and an entry that started generating would be writing the
    # tile's default direction while claiming to be a specific one.
    assert all(
        record.outcome == "refused" for record in records if record.no_sdpm_input
    )


def test_reversibility_is_measured_rather_than_looked_up():
    """An entry round-trips if its own JSON comes back, whatever key the reader used.

    This was membership in the reader's reverse index, which maps each OOXML
    form to exactly **one** preferred key — so `MsoAnimEffect.animation type
    fly` counted as one-way because `animation.gallery.entrance.flyIn` is the
    form's inverse target, even though writing the enumerator's own example and
    reading it back produced byte-identical JSON. 143 of the 210 one-way
    entries were that.

    The weaker-looking definition cannot hide a failure, and that is the point:
    an entry is only counted reversible when its JSON actually comes back
    equal, *or* when the index names it as the inverse target — in which case
    an unequal read is reported as a partial round-trip instead of vanishing.
    """
    import subprocess

    result = subprocess.run(
        [sys.executable, "scripts/animation_catalog/accept.py", "--all", "--json"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    report = json.loads(result.stdout)

    round_trip = report["roundTrip"]
    assert round_trip["invertibleEntries"] == round_trip["equal"], (
        "an entry counted invertible did not come back equal, which the "
        f"partialRoundTrip gap should have caught: {round_trip}"
    )
    assert round_trip["invertibleEntries"] >= 391, round_trip
    assert report["gaps"]["partialRoundTrip"]["count"] == 0

    # The remaining one-way entries are real reader gaps, not aliases: every one
    # is a form the reader does not invert at all.
    one_way = report["gaps"]["oneWayOnly"]["keys"]
    assert len(one_way) == 67, (len(one_way), one_way[:5])
    assert not any(key.startswith("EPPEntryEffect.") for key in one_way), (
        "transition enumerators corroborate a gallery tile and round-trip; "
        "none should be left counted one-way"
    )


def test_the_gate_counts_only_what_can_be_closed():
    """Every blocker has to name something an action would change.

    `noSdpmInput` is reported and deliberately not gated: it counts entries
    nothing can close, so gating on it would make the gate unpassable by
    design and the blocker list would stop being a to-do list.
    """
    import subprocess

    result = subprocess.run(
        [sys.executable, "scripts/animation_catalog/accept.py", "--all", "--json"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    report = json.loads(result.stdout)
    blockers = " ".join(report["gate"]["blockers"])
    assert "noSdpmInput" not in blockers, report["gate"]["blockers"]
    assert report["gaps"]["noSdpmInput"]["count"] == 90
    assert report["gaps"]["noSdpmInput"]["closes"].startswith("nothing")


def test_an_effect_this_build_cannot_apply_is_not_counted_as_awaiting_capture():
    """`captureRequired` has to list only what a capture here could record.

    Most `MsoAnimEffect` enumerators name Windows-era effects — `bean path`,
    `light speed`, `zip` — that PowerPoint for Mac cannot apply at all. On
    Windows the full list is reached through Add Animation; this build has no
    such control, so its galleries and the Path Animation popup are the whole
    set. Counting them as awaiting a read-back claimed a capture would close
    them, and kept the total from ever reaching zero.

    The classification is **derived** from the two committed readings, not
    hardcoded, so an effect that appears in a future build stops being marked
    on the next regeneration.
    """
    from scripts.animation_catalog.generate import applicable_effect_labels
    from sdpm.engine.timing import load_capability_index
    from sdpm.engine.timing.writer import catalog_coverage

    catalog_path = REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    catalog = json.loads(catalog_path.read_text())
    records = catalog_coverage(load_capability_index(catalog_path), catalog=catalog)

    marked = {record.key for record in records if record.platform_unavailable}
    assert marked, "nothing was marked, so this guard checks nothing"
    assert all(key.startswith("MsoAnimEffect.animation type ") for key in marked), sorted(marked)[:5]

    # Every marked entry names an effect no gallery offers, and carries both the
    # reading it came from and the published corroboration.
    labels = applicable_effect_labels()
    assert labels, "the platform inventory is missing, so the marking cannot be checked"
    by_key = {e["key"]: e for e in catalog["guiItems"] + catalog["candidates"]}
    import re as _re

    for key in sorted(marked):
        label = key.removeprefix("MsoAnimEffect.animation type ").removesuffix(" path")
        assert _re.sub(r"[^a-z0-9]", "", label.lower()) not in labels, (
            f"{key} was marked unavailable but {label!r} is in this build's galleries"
        )
        block = by_key[key]["platformUnavailable"]
        assert block["platform"] == "macOS"
        assert len(block["corroboration"]) == 2
        assert block["readFrom"]

    # And the effects the galleries *do* offer are never marked, however
    # unusual their names: shimmer, stretchy and wave are reachable here.
    for reachable in ("shimmer", "stretchy", "wave path"):
        assert f"MsoAnimEffect.animation type {reachable}" not in marked, reachable


def test_the_platform_inventory_records_the_whole_path_animation_popup():
    """The reading that decides 63 motion-path entries has to be reproducible.

    It used to be an ad-hoc accessibility read in a terminal, which no later
    reader could repeat. `discover_platform_inventory.py` performs it, and this
    asserts the committed result still describes the popup it claims to.
    """
    inventory = json.loads(
        (
            REPO_ROOT
            / "tests/fixtures/animations/gui-only/platform-inventory-2026-11-02"
            / "platform-inventory.json"
        ).read_text()
    )
    assert inventory["platform"] == "macOS"
    assert inventory["version"] == "16.113.1"
    assert inventory["counts"]["items"] == 16
    labels = {item["label"] for item in inventory["galleries"][0]["items"]}
    # Custom needs a drawn path; Basic is measured; Complex is reachable and
    # has no catalog key at all, which is the gap this reading exposed.
    assert {"Draw Curve", "Draw Freeform", "Draw Line", "Draw Scribble"} <= labels
    assert {"Arcs", "Lines", "Loops", "Shapes", "Turns"} <= labels
    assert {
        "Bounce", "Inverted Shape", "Special Curve", "Special Shape",
        "Spiral", "Star", "Waves",
    } <= labels
    assert "More Motion Paths..." not in labels and "More Motion Paths…" not in labels
    assert len(inventory["noMoreEffectsRoute"]["corroboration"]) == 2


def test_the_pane_settings_reading_records_a_route_with_no_dialog():
    """The after-effect, sound and timing settings are not behind a dialog here.

    The capture plan for those 11 values was written from the Windows
    documentation: open the Animation Pane, **double-click** the effect, pick
    the **Effect** or **Timing** tab. Two things are wrong with that on this
    build. There is no such dialog — the settings are inline in the Animation
    Pane as disclosure sections. And a double-click is not something this driver
    can deliver, since it presses semantically and posts no mouse events, so a
    plan requiring one is unreachable rather than merely slow.

    So the surface is asserted from a committed reading, not from the plan.
    """
    settings = json.loads(
        (
            REPO_ROOT
            / "tests/fixtures/animations/gui-only/pane-settings-2026-11-02"
            / "pane-settings.json"
        ).read_text()
    )
    assert settings["platform"] == "macOS"
    assert settings["version"] == "16.113.1"

    structure = settings["structure"]["motionPathOnRectangle"]
    sections = {section["name"]: section for section in structure["sections"]}
    assert set(sections) == {"Effect Options", "Timing", "Text Animations", "Triggers"}
    # Every section answers a press, which is what makes the route reachable at
    # all. If one ever stops offering Expand, the plan needs rewriting again.
    for name, section in sections.items():
        assert "Expand" in section["actions"], f"{name} offers no Expand"

    # Two timing settings are ON by default, so for those it is the *cleared*
    # state that has to be captured — the opposite of every other value in this
    # feature. Losing this would send a capture run after the wrong halves.
    assert structure["defaultsOn"] == ["Smooth End", "Smooth Start"]
    checkboxes = {box["label"] for box in structure["checkboxes"]}
    assert {"Smooth Start", "Smooth End", "Bounce End", "Rewind when done playing"} <= checkboxes

    popups = {popup["label"]: popup for popup in settings["popups"].values()}
    assert not [p for p in popups.values() if p["error"]], "a popup read failed"

    after = popups["After animation: "]
    labels = {item["label"] for item in after["items"]}
    assert after["current"] == "Don't Dim"
    # Eight *scheme* swatches, so a dim records a theme reference; More Colors
    # is the arbitrary-RGB route. Both forms need capturing to tell them apart.
    swatches = [item for item in after["items"] if item["label"].endswith("Scheme Color")]
    assert len(swatches) == 8
    assert {"More Colors...", "Hide After Animation", "Hide on Next Mouse Click"} <= labels

    sounds = {item["label"] for item in popups["Sound:"]["items"]}
    assert {"[No Sound]", "[Stop Previous Sound]", "Other Sound..."} <= sounds
    assert len(sounds) == 22

    starts = [item["label"] for item in popups["Start:"]["items"]]
    assert starts == ["On Click", "With Previous", "After Previous"]

    repeats = {item["label"] for item in popups["Repeat:"]["items"]}
    assert {"(none)", "Custom:", "Until Next Click", "Until End of Slide"} <= repeats

    # Property is selection-dependent, which is why it is keyed by selection
    # above: a SmartArt graphic offers something else entirely.
    assert {item["label"] for item in popups["Property:"]["items"]} == {
        "Not Anchored",
        "Anchored to Object",
    }


def test_the_complex_motion_paths_are_measured_and_writable():
    """Seven paths this build applies, which the catalog had no key for.

    The Path Animation popup offers Custom (4 drawn), Basic (5, measured
    2026-11-01) and **Complex** (7). The catalog knew the first nine and not the
    last seven, and nobody noticed because it was tracking 65 Windows-only path
    enumerators this build cannot apply — reading the popup is what separated
    the two.

    The assertion is the geometry, because a Bézier that is close is wrong.
    """
    from sdpm.engine.timing import load_capability_index

    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    measured = {
        "bounce": 41,
        "invertedShape": 34,
        "specialCurve": 28,
        "specialShape": 31,
        "spiral": 55,
        "star": 16,
        "waves": 48,
    }
    for slug, preset_id in measured.items():
        entry = index.items[f"animation.gallery.motionPath.{slug}"]
        ooxml = entry.ooxml
        assert ooxml["presetId"] == preset_id, slug
        assert ooxml["measuredDurationMs"] == 2000, slug
        assert entry.writable, f"{slug} is still refused"
        motion = [b for b in ooxml["behaviors"] if b["element"] == "p:animMotion"]
        assert len(motion) == 1, slug
        attrs = motion[0]["attributes"]
        assert attrs["origin"] == "layout" and attrs["pathEditMode"] == "relative", slug
        # Transcribed, not re-derived: the literal path data PowerPoint wrote.
        assert attrs["path"].startswith("M 0 0"), slug
        assert len(attrs["path"]) > 100, f"{slug} path looks truncated: {attrs['path']!r}"
        assert entry.ooxml.get("requiresCapture") is None, slug

    # Star is a closed polygon, which is the one path short enough to assert whole.
    star = index.items["animation.gallery.motionPath.star"].ooxml["behaviors"][0]
    assert star["attributes"]["path"] == (
        "M 0 0 L 0.091 -0.034 L 0.125 -0.125 L 0.158 -0.034 L 0.249 0 "
        "L 0.158 0.034 L 0.125 0.125 L 0.091 0.034 L 0 0 Z"
    )


def test_every_path_the_popup_offers_has_a_catalog_key():
    """The gap that hid the Complex group must not be able to reopen.

    A path in the popup with no catalog key is invisible: nothing refuses it,
    nothing plans it, and no count goes up when it is missing. The inventory is
    read from the live UI, so a group a future build adds fails here instead.
    `Draw *` is excluded because a drawn path has no deterministic value.
    """
    import re

    from sdpm.engine.timing import load_capability_index

    inventory = json.loads(
        (
            REPO_ROOT
            / "tests/fixtures/animations/gui-only/platform-inventory-2026-11-02"
            / "platform-inventory.json"
        ).read_text()
    )
    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    have = {
        re.sub(r"[^a-z0-9]", "", key.rsplit(".", 1)[-1].lower())
        for key in index.items
        if key.startswith("animation.gallery.motionPath.")
    }
    offered = [
        label for label in inventory["labels"] if not label.startswith("Draw")
    ]
    assert len(offered) == 12, offered
    missing = [
        label
        for label in offered
        if re.sub(r"[^a-z0-9]", "", label.lower()) not in have
    ]
    assert not missing, f"the Path Animation popup offers paths the catalog has no key for: {missing}"


def test_the_manifest_no_longer_claims_a_dialog_this_build_lacks():
    """The four `More ... Effects` entries described a surface that is not there.

    They named `Add Animation ▸ More … Effects…` as their control, and
    PowerPoint for Mac has no Add Animation control at all. A manifest entry
    that points at a surface nobody can open is worse than silence: it reads as
    checkable.
    """
    manifest = json.loads(
        (REPO_ROOT / "sdpm/references/catalogs/powerpoint-gui-surface-16.113.1.json").read_text()
    )
    more = [i for i in manifest["items"] if i["key"].startswith("animation.moreEffects.")]
    assert len(more) == 4
    for item in more:
        assert item["surface"] == "absent on macOS", item["key"]
        assert "not present in this build" in item["control"], item["key"]
        assert "no Add Animation control" in item["sourceEvidence"], item["key"]
        assert item["status"] == "nonPersisted", item["key"]


# --- describe_effects: what an effect does, derived not written -------------
def test_the_guide_table_matches_what_the_catalog_measured():
    """The routing table is derived, so it must not drift from the catalog.

    It exists because a name does not say what moves, and a reader who has to
    try effects to find out pays a deck per guess. Hand-maintaining it would
    reintroduce exactly the gap it closes: an effect whose behaviours changed
    would keep its old description.
    """
    from sdpm.engine.timing import load_capability_index
    from sdpm.engine.timing.describe import axis_table

    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    guide = (REPO_ROOT / "sdpm/references/guides/animations.md").read_text()
    rows = axis_table(index)
    assert rows, "nothing was derived, so this guard checks nothing"
    for label, effects in rows:
        line = f"| {label} | {', '.join(effects)} |"
        assert line in guide, f"the guide does not carry the derived row: {line}"

    # Cheap enough to keep in a guide that is read every time: the whole table
    # is about 300 tokens, against about 9,000 for every expression.
    size = sum(len(f"| {label} | {', '.join(effects)} |") for label, effects in rows)
    assert size < 2000, f"the routing table has grown to {size} characters"


def test_no_effect_name_appears_in_two_rows_of_the_table():
    """A lookup table that sends a reader to the wrong effect is worse than none.

    `bounce` is an entrance effect that moves and resizes, and a motion path
    that follows a curve. A name is qualified only when it lands in different
    rows, so `blinds` — the same thing as both entrance and exit — stays bare
    and does not cost a third of the table.
    """
    from collections import Counter

    from sdpm.engine.timing import load_capability_index
    from sdpm.engine.timing.describe import axis_table

    index = load_capability_index(
        REPO_ROOT / "sdpm/references/catalogs/powerpoint-animation-catalog.json"
    )
    rows = axis_table(index)
    counts = Counter(name for _label, names in rows for name in names)
    assert [name for name, n in counts.items() if n > 1] == []
    qualified = {name for name, _ in counts.items() if "." in name}
    assert qualified == {"entrance.bounce", "exit.bounce", "motionPath.bounce"}, qualified


def test_describe_effects_says_what_was_measured_and_nothing_else():
    """The expression is a transcription, so the values in it are the measured ones."""
    from sdpm.tools import describe_effects

    table = describe_effects()
    assert len(table["changes"]) == len(
        {row["changes"] for row in table["changes"]}
    ), "a label appears twice"
    assert any(row["changes"] == "moves" and "flyIn" in row["effects"] for row in table["changes"])

    fly_in = describe_effects(effect="flyIn")["effects"]
    assert len(fly_in) == 1
    described = fly_in[0]
    assert described["category"] == "entrance"
    assert described["changes"] == ["moves"]
    assert described["durationMs"] == 500
    # `1+#ppt_w/2` is the idiom a caller would not guess, which is the whole
    # reason the expression is worth returning.
    assert "1+#ppt_w/2" in described["options"]["direction"]["values"]["fromRight"]
    assert described["options"]["direction"]["default"] == "fromBottom"
    assert len(described["options"]["direction"]["values"]) == 8

    # A setting carried only by the behaviours still shows its difference.
    spin = describe_effects(effect="spin")["effects"][0]
    assert "-21600000" in spin["options"]["direction"]["values"]["counterclockwise"]
    assert "21600000" in spin["options"]["direction"]["values"]["clockwise"]
    assert spin["optionsNote"], "the unmeasured combinations are not reported"

    # A path is transcribed rather than summarised.
    star = describe_effects(category="motionPath", effect="star")["effects"][0]
    assert "M 0 0 L 0.091 -0.034" in star["expression"]

    assert describe_effects(effect="teleport")["effects"] == []


def test_describe_effects_stays_small_enough_to_call_per_effect():
    """The two layers exist because they cost different amounts.

    Shipping every expression would add about 9,000 tokens to a guide read on
    every deck. The table is about 300 and one effect about 320, so choosing
    costs the table and verifying costs only the effects actually considered.
    """
    import json

    from sdpm.tools import describe_effects

    assert len(json.dumps(describe_effects())) < 4000
    for effect in ("flyIn", "spin", "growShrink", "wave"):
        one = json.dumps(describe_effects(effect=effect))
        assert len(one) < 6000, f"{effect} describes to {len(one)} characters"


def test_the_guide_says_to_prefer_a_preset_over_composing_behaviours():
    """The two forms are not interchangeable, and the guide has to say which to use.

    A composed `behaviors` list carries no `presetID`: PowerPoint does not name
    it, its Effect Options do not apply, and sdpm's own reader imports it as
    raw. That is 16 of the one-way entries. The guide recorded that behaviours
    are not invertible without ever saying to prefer a preset.
    """
    guide = (REPO_ROOT / "sdpm/references/guides/animations.md").read_text()
    assert "Prefer a `preset`" in guide
    for token in (
        "carries no `presetID`",
        "imports as\nraw",
        "unverified",
        "import_attachment",
    ):
        assert token in guide, token
