# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for apply_guides: the guides-only path that leaves art direction alone.

A deck made before these guides existed has no style name in deck.json, so
apply_style can only fail for it. These cases pin what apply_guides must not touch.
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sdpm.api import apply_guides
from sdpm.knowledge.reference import BUNDLED_STRUCTURES_DIR, BUNDLED_WRITINGS_DIR

# The deck.json fields a style owns. apply_guides must leave every one of them alone.
_STYLE_FIELDS = ("template", "defaultTextColor", "defaultBackground", "fonts", "slideSize")


@pytest.fixture
def deck(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """A deck with a frozen art direction, plus isolated guide stores."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    config_dir = tmp_path / "config" / "sdpm"
    config_dir.mkdir(parents=True)

    structures = tmp_path / "structure"
    structures.mkdir()
    (structures / "report-first.md").write_text("---\ndescription: Report\n---\n\n## Pick\n\nrules\n")
    monkeypatch.setenv("SDPM_STRUCTURES_DIR", f"{structures}{os.pathsep}{BUNDLED_STRUCTURES_DIR}")

    writings = tmp_path / "writing"
    writings.mkdir()
    (writings / "house.md").write_text("---\ndescription: House\n---\n\n## Words\n\nrules\n")
    monkeypatch.setenv("SDPM_WRITINGS_DIR", f"{writings}{os.pathsep}{BUNDLED_WRITINGS_DIR}")

    path = tmp_path / "deck"
    (path / "specs").mkdir(parents=True)
    art = path / "specs" / "art-direction.html"
    art.write_text("<style>:root { --color-text: #123456; }</style>", encoding="utf-8")
    # No "style" key: this is what a deck from before the change looks like.
    (path / "deck.json").write_text(
        json.dumps(
            {
                "template": "blank-light.pptx",
                "fonts": {"fullwidth": "Yu Gothic", "halfwidth": "Arial"},
                "defaultTextColor": "#111111",
                "slideSize": {"width": 1920, "height": 1080},
            }
        ),
        encoding="utf-8",
    )

    def write_state(**keys: object) -> None:
        from sdpm import config

        (config_dir / "state.json").write_text(json.dumps(keys))
        config.invalidate_cache()

    def read_deck() -> dict:
        return json.loads((path / "deck.json").read_text(encoding="utf-8"))

    def set_language(language: str) -> None:
        (path / "deck.json").write_text(json.dumps({**read_deck(), "language": language}), encoding="utf-8")

    write_state()
    return SimpleNamespace(
        path=path, art=art, write_state=write_state, read_deck=read_deck, set_language=set_language
    )


def test_a_deck_with_no_style_name_still_gets_its_guides(deck: SimpleNamespace) -> None:
    deck.set_language("ja")
    result = apply_guides(deck.path)
    assert result["status"] == "ok"
    assert (deck.path / "specs" / "structure.md").exists()
    assert (deck.path / "specs" / "writing.md").exists()


def test_apply_guides_leaves_the_art_direction_untouched(deck: SimpleNamespace) -> None:
    before_text = deck.art.read_text(encoding="utf-8")
    before_mtime = deck.art.stat().st_mtime_ns
    apply_guides(deck.path, structure="report-first")
    assert deck.art.read_text(encoding="utf-8") == before_text
    assert deck.art.stat().st_mtime_ns == before_mtime


def test_apply_guides_leaves_the_style_derived_fields_untouched(deck: SimpleNamespace) -> None:
    before = deck.read_deck()
    apply_guides(deck.path, structure="report-first")
    after = deck.read_deck()
    assert {k: after.get(k) for k in _STYLE_FIELDS} == {k: before.get(k) for k in _STYLE_FIELDS}
    assert "style" not in after, "apply_guides never invents a style name"


def test_changing_only_the_structure_rewrites_deck_json(deck: SimpleNamespace) -> None:
    apply_guides(deck.path, structure="report-first")
    result = apply_guides(deck.path, structure="by-audience")
    assert result["updated"] == {"structure": "by-audience"}
    assert deck.read_deck()["structure"] == "by-audience"


def test_translating_to_a_language_without_a_guide_removes_the_copy(deck: SimpleNamespace) -> None:
    """REQ-5.3: a copied specs/ must not carry the source language's wording rules."""
    deck.set_language("ja")
    apply_guides(deck.path)
    assert (deck.path / "specs" / "writing.md").exists()
    assert deck.read_deck()["writing"] == "ja"

    deck.set_language("en")
    result = apply_guides(deck.path)
    assert not (deck.path / "specs" / "writing.md").exists()
    assert "writing" not in deck.read_deck()
    assert result["writing"] == ""


def test_a_named_guide_that_does_not_exist_writes_nothing(deck: SimpleNamespace) -> None:
    result = apply_guides(deck.path, structure="nope")
    assert result["error"].startswith("Structure not found: nope.")
    assert not (deck.path / "specs" / "structure.md").exists()
    assert "structure" not in deck.read_deck()


# ---------------------------------------------------------------------------
# Translation re-resolves the derived deck's guides
# ---------------------------------------------------------------------------


def test_extraction_replaces_the_source_languages_writing_guide(
    deck: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """_copy_deck copytrees specs/, so without this an en sibling reads the ja rules."""
    import subprocess
    import sys

    deck.set_language("ja")
    apply_guides(deck.path, structure="report-first")
    assert (deck.path / "specs" / "writing.md").exists()
    assert deck.read_deck()["structure"] == "report-first"

    (deck.path / "slides").mkdir(exist_ok=True)
    (deck.path / "slides" / "intro.json").write_text(
        json.dumps({"id": "intro", "elements": [{"type": "textbox", "text": "継続率の推移"}]}),
        encoding="utf-8",
    )

    script = Path(__file__).resolve().parents[1] / "sdpm" / "scripts" / "translate_extract.py"
    done = subprocess.run(
        [sys.executable, str(script), str(deck.path), "--target-lang", "en"],
        capture_output=True, text=True, env={**os.environ},
    )
    assert done.returncode == 0, done.stderr

    sibling = deck.path.with_name(f"{deck.path.name}-en")
    sibling_deck = json.loads((sibling / "deck.json").read_text(encoding="utf-8"))
    assert sibling_deck["language"] == "en"
    assert not (sibling / "specs" / "writing.md").exists(), "the ja rules did not come along"
    assert "writing" not in sibling_deck
    assert (sibling / "specs" / "structure.md").exists(), "structure does not depend on language"
    # Only the writing guide depends on the language: re-resolving must not swap the
    # structure the source deck was actually written against for the default.
    assert sibling_deck["structure"] == "report-first"
    assert (sibling / "specs" / "structure.md").read_text(encoding="utf-8").endswith("rules\n")


def test_a_structure_guide_this_machine_lacks_does_not_veto_the_writing_fix(
    deck: SimpleNamespace, tmp_path: Path
) -> None:
    """A user's guides live in their config, not in the deck, so a deck can record a
    structure guide the machine running the translation does not have. apply_guides
    rejects the whole call for a name it cannot resolve, which would leave the sibling
    reading the source language's wording rules."""
    import subprocess
    import sys

    deck.set_language("ja")
    apply_guides(deck.path, structure="report-first")
    # The deck remembers a guide that is not in any store this run can see.
    (deck.path / "deck.json").write_text(
        json.dumps({**deck.read_deck(), "structure": "team-house"}), encoding="utf-8"
    )
    (deck.path / "slides").mkdir(exist_ok=True)
    (deck.path / "slides" / "intro.json").write_text(
        json.dumps({"id": "intro", "elements": [{"type": "textbox", "text": "継続率の推移"}]}),
        encoding="utf-8",
    )

    script = Path(__file__).resolve().parents[1] / "sdpm" / "scripts" / "translate_extract.py"
    done = subprocess.run(
        [sys.executable, str(script), str(deck.path), "--target-lang", "en"],
        capture_output=True, text=True, env={**os.environ},
    )
    assert done.returncode == 0, done.stderr
    assert "team-house" in done.stderr, "what happened to the structure guide is reported"

    sibling = deck.path.with_name(f"{deck.path.name}-en")
    sibling_deck = json.loads((sibling / "deck.json").read_text(encoding="utf-8"))
    assert not (sibling / "specs" / "writing.md").exists(), "the writing fix still happened"
    assert "writing" not in sibling_deck
    # The structure is left alone rather than replaced by the default: _copy_deck already
    # carried over the guide the deck was actually written against.
    assert sibling_deck["structure"] == "team-house"
    assert (sibling / "specs" / "structure.md").read_text(encoding="utf-8").endswith("rules\n")


def test_translating_into_japanese_gets_the_direction_guide(
    deck: SimpleNamespace, tmp_path: Path
) -> None:
    """en->ja is a translation job, so the sibling gets the guide about translating into
    Japanese, not the one about writing Japanese from scratch."""
    import subprocess
    import sys

    deck.set_language("en")
    (deck.path / "slides").mkdir(exist_ok=True)
    (deck.path / "slides" / "intro.json").write_text(
        json.dumps({"id": "intro", "elements": [{"type": "textbox", "text": "Retention over time"}]}),
        encoding="utf-8",
    )

    script = Path(__file__).resolve().parents[1] / "sdpm" / "scripts" / "translate_extract.py"
    done = subprocess.run(
        [sys.executable, str(script), str(deck.path), "--target-lang", "ja"],
        capture_output=True, text=True, env={**os.environ},
    )
    assert done.returncode == 0, done.stderr

    sibling = deck.path.with_name(f"{deck.path.name}-ja")
    sibling_deck = json.loads((sibling / "deck.json").read_text(encoding="utf-8"))
    assert sibling_deck["writing"] == "en2ja", "the direction guide, not plain ja"
    copied = (sibling / "specs" / "writing.md").read_text(encoding="utf-8")
    assert "原文" in copied
    assert "主張を書く" not in copied, "a translator does not choose the claim"


def test_the_direction_tier_is_skipped_for_a_deck_written_from_scratch(
    deck: SimpleNamespace,
) -> None:
    """No source language means no direction, so a Japanese deck gets the ja guide."""
    deck.set_language("ja")
    result = apply_guides(deck.path)
    assert result["writing"] == "ja"
    assert result["sources"]["writing"] == "unset"


def test_a_source_language_selects_the_direction_guide(deck: SimpleNamespace) -> None:
    result = apply_guides(deck.path, source_language="en")
    assert result["writing"] == ""  # the deck has no language yet

    deck.set_language("ja")
    result = apply_guides(deck.path, source_language="en")
    assert result["writing"] == "en2ja"
    assert result["sources"]["writing"] == "unset-direction"
