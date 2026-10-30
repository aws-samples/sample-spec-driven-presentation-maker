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
    CANDIDATE_ENUMS,
    CAPABILITY_LEVELS,
    DEFAULT_ORACLE,
    DEFAULT_SDEF,
    FORBIDDEN_ORACLE_TOKENS,
    NATIVE,
    ORACLE_RUN_TOKEN,
    REQUIRED_ORACLE_TOKENS,
    SEMANTIC,
    STATUSES,
    build_catalog,
    catalog_slide,
    check,
    dump,
    main,
    merge_oracle_readback,
    oracle_findings,
    parse_oracle_arrays,
    parse_oracle_package,
    read_oracle_readback,
    read_sdef,
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


def test_accepted_semantic_json_is_complete_not_just_a_name(catalog):
    for entry in catalog["candidates"]:
        if entry["status"] != "accepted":
            continue
        semantic = entry["semanticJson"]
        if "transition" in semantic:
            transition = semantic["transition"]
            assert set(transition) >= {"effect", "parameters", "durationMs", "advance", "sound"}
        else:
            effect = semantic["animations"]["mainSequence"][0]
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
    triggers = {
        entry["semanticJson"]["animations"]["mainSequence"][0]["start"]["type"]
        for entry in catalog["candidates"]
        if entry["enum"] == "MsoAnimTriggerType"
    }
    assert triggers == {"none", "onPageClick", "withPrevious", "afterPrevious", "onShapeClick"}


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
    # Each constant is the enumerator itself, so a record can never report a
    # name that a different constant applied.
    for enum_name in CANDIDATE_ENUMS:
        assert arrays[enum_name]["constants"] == arrays[enum_name]["names"], enum_name
        assert all(code.startswith("0x") for code in arrays[enum_name]["codes"]), enum_name


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
    for enum_name, values in sdef_enums.items():
        names = [name for name, _ in values]
        codes = [code for _, code in values]
        assert arrays[enum_name]["names"] == names, enum_name
        assert arrays[enum_name]["constants"] == names, enum_name
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
