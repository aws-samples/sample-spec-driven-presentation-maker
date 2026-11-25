# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for resolve_default: which guide or style is used, and why.

The decision table lives in the SPEC's design.md. These cases pin the four origins
and every notice, because apply_style and apply_guides both branch on them.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sdpm.knowledge.reference import (
    is_valid_scope,
    writing_scope,
    BUNDLED_STRUCTURES_DIR,
    BUNDLED_WRITINGS_DIR,
    resolve_default,
)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """A user-local config dir, with helpers to write state.json and guide files."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config_dir = tmp_path / "sdpm"
    config_dir.mkdir(parents=True)

    def write_state(**keys: object) -> None:
        from sdpm import config

        (config_dir / "state.json").write_text(json.dumps(keys))
        config.invalidate_cache()

    def add(kind: str, name: str, suffix: str = ".md") -> Path:
        d = config_dir / kind
        d.mkdir(exist_ok=True)
        f = d / f"{name}{suffix}"
        f.write_text(f"---\ndescription: {name}\n---\n")
        return f

    return SimpleNamespace(
        config_dir=config_dir,
        write_state=write_state,
        add=add,
        dirs=lambda kind: [config_dir / kind],
    )


# ---------------------------------------------------------------------------
# explicit (origin "argument")
# ---------------------------------------------------------------------------


def test_an_explicit_name_that_exists_wins(store: SimpleNamespace) -> None:
    store.add("structure", "scqa-first")
    store.write_state(default_structure="by-audience")
    name, origin, notices = resolve_default("structure", "scqa-first", store.dirs("structure"))
    assert (name, origin, notices) == ("scqa-first", "argument", [])


def test_an_explicit_name_that_does_not_exist_resolves_to_nothing(store: SimpleNamespace) -> None:
    """Origin argument with an empty name is the caller's cue to error (REQ-3.6)."""
    store.write_state()
    name, origin, notices = resolve_default("structure", "nope", store.dirs("structure"))
    assert name == ""
    assert origin == "argument"
    assert notices == []


# ---------------------------------------------------------------------------
# default_<kind> (origins "default" and "default-missing")
# ---------------------------------------------------------------------------


def test_a_configured_default_that_exists_is_used(store: SimpleNamespace) -> None:
    store.add("structure", "internal-report")
    store.write_state(default_structure="internal-report")
    name, origin, notices = resolve_default("structure", "", store.dirs("structure"))
    assert (name, origin, notices) == ("internal-report", "default", [])


def test_a_default_outside_the_pins_is_used_with_a_notice(store: SimpleNamespace) -> None:
    store.add("structure", "internal-report")
    store.add("structure", "scqa-first")
    store.write_state(default_structure="internal-report", pinned_structures=["scqa-first"])
    name, origin, notices = resolve_default("structure", "", store.dirs("structure"))
    assert (name, origin) == ("internal-report", "default")
    assert len(notices) == 1 and "internal-report" in notices[0]


def test_a_missing_structure_default_falls_back_to_the_bundled_one(store: SimpleNamespace) -> None:
    store.write_state(default_structure="deleted-one")
    dirs = [*store.dirs("structure"), BUNDLED_STRUCTURES_DIR]
    name, origin, notices = resolve_default("structure", "", dirs)
    assert (name, origin) == ("by-audience", "default-missing")
    assert len(notices) == 1 and "deleted-one" in notices[0]


def test_a_missing_style_default_resolves_to_nothing(store: SimpleNamespace) -> None:
    """There is no bundled style, so the caller has to error."""
    store.write_state(default_style="deleted-one")
    name, origin, notices = resolve_default("style", "", store.dirs("styles"))
    assert (name, origin) == ("", "default-missing")
    assert len(notices) == 1 and "deleted-one" in notices[0]


# ---------------------------------------------------------------------------
# no default set (origin "unset")
# ---------------------------------------------------------------------------


def test_no_default_falls_back_to_the_bundled_one_silently(store: SimpleNamespace) -> None:
    store.write_state()
    dirs = [*store.dirs("structure"), BUNDLED_STRUCTURES_DIR]
    assert resolve_default("structure", "", dirs) == ("by-audience", "unset", [])


# ---------------------------------------------------------------------------
# writing: the bundled fallback follows the deck's language
# ---------------------------------------------------------------------------


def test_a_language_without_a_bundled_guide_resolves_to_nothing_and_says_nothing(store: SimpleNamespace) -> None:
    """en is a stated language with no bundled guide — expected, so no notice."""
    store.write_state()
    dirs = [*store.dirs("writing"), BUNDLED_WRITINGS_DIR]
    assert resolve_default("writing", "", dirs, language="en") == ("", "unset", [])


def test_a_configured_writing_default_applies_to_its_own_language(store: SimpleNamespace) -> None:
    """The table is keyed by scope, so a Japanese default cannot reach an English deck."""
    store.add("writing", "house")
    store.write_state(default_writing={"ja": "house"})
    dirs = [*store.dirs("writing"), BUNDLED_WRITINGS_DIR]
    assert resolve_default("writing", "", dirs, language="ja") == ("house", "default", [])
    assert resolve_default("writing", "", dirs, language="en") == ("", "unset", [])


def test_an_absent_language_resolves_to_nothing_and_says_so(store: SimpleNamespace) -> None:
    """REQ-5.8: no language means nobody wrote one, which is a defect worth reporting."""
    store.write_state()
    dirs = [*store.dirs("writing"), BUNDLED_WRITINGS_DIR]
    name, origin, notices = resolve_default("writing", "", dirs)
    assert (name, origin) == ("", "unset")
    assert len(notices) == 1 and "language" in notices[0]


def test_a_regional_language_tag_matches_on_its_primary_subtag(store: SimpleNamespace) -> None:
    store.write_state()
    dirs = [*store.dirs("writing"), BUNDLED_WRITINGS_DIR]
    assert resolve_default("writing", "", dirs, language="ja-JP") == ("ja", "unset", [])


# ---------------------------------------------------------------------------
# writing: the direction tier, and the defect that made it necessary
# ---------------------------------------------------------------------------


def test_a_japanese_default_does_not_reach_an_english_deck(store: SimpleNamespace) -> None:
    """The defect the cumulative review found: default_writing held one name with no
    language, so a user who works in Japanese got Japanese rules on an English deck —
    and not only when translating."""
    store.write_state(default_writing={"ja": "house-ja"})
    store.add("writing", "house-ja")
    dirs = [*store.dirs("writing"), BUNDLED_WRITINGS_DIR]

    assert resolve_default("writing", "", dirs, language="en") == ("", "unset", [])
    assert resolve_default("writing", "", dirs, language="ja") == ("house-ja", "default", [])


def test_the_users_direction_guide_wins_when_translating(store: SimpleNamespace) -> None:
    store.write_state(default_writing={"ja": "house-ja", "en2ja": "house-en2ja"})
    store.add("writing", "house-ja")
    store.add("writing", "house-en2ja")
    dirs = [*store.dirs("writing"), BUNDLED_WRITINGS_DIR]

    assert resolve_default(
        "writing", "", dirs, language="ja", source_language="en"
    ) == ("house-en2ja", "default-direction", [])


def test_the_bundled_direction_guide_is_used_when_nothing_is_set(store: SimpleNamespace) -> None:
    store.write_state()
    dirs = [*store.dirs("writing"), BUNDLED_WRITINGS_DIR]
    name, origin, notices = resolve_default(
        "writing", "", dirs, language="ja", source_language="en"
    )
    assert (name, origin, notices) == ("en2ja", "unset-direction", [])


def test_without_a_source_language_the_direction_tier_is_skipped(store: SimpleNamespace) -> None:
    """A deck written from scratch has no direction, so its resolution is unchanged."""
    store.write_state(default_writing={"en2ja": "house-en2ja"})
    store.add("writing", "house-en2ja")
    dirs = [*store.dirs("writing"), BUNDLED_WRITINGS_DIR]

    assert resolve_default("writing", "", dirs, language="ja") == ("ja", "unset", [])


def test_a_direction_with_no_guide_falls_through_to_the_language(store: SimpleNamespace) -> None:
    store.write_state()
    dirs = [*store.dirs("writing"), BUNDLED_WRITINGS_DIR]
    # ja2en: no direction guide, and no en guide either.
    assert resolve_default("writing", "", dirs, language="en", source_language="ja") == (
        "", "unset", [],
    )


def test_a_regional_tag_is_normalised_on_both_halves(store: SimpleNamespace) -> None:
    store.write_state()
    dirs = [*store.dirs("writing"), BUNDLED_WRITINGS_DIR]
    assert resolve_default(
        "writing", "", dirs, language="ja-JP", source_language="en-US"
    )[0] == "en2ja"


@pytest.mark.parametrize("scope", ["ja", "en", "en2ja", "ja2en", "fil2ja"])
def test_a_scope_is_a_language_or_a_direction(scope: str) -> None:
    assert is_valid_scope(scope)


@pytest.mark.parametrize("scope", ["en-ja", "EN2JA", "2ja", "en2", "", "en2ja2ko", "english"])
def test_anything_else_is_not_a_scope(scope: str) -> None:
    assert not is_valid_scope(scope)


def test_a_direction_scope_is_built_from_both_tags() -> None:
    assert writing_scope("ja-JP", "en-US") == "en2ja"
    assert writing_scope("ja") == "ja"
    assert writing_scope("ja", "") == "ja"
    assert writing_scope("") == ""
