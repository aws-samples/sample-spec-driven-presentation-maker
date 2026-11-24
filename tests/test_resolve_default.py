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


def test_a_configured_writing_default_ignores_the_language(store: SimpleNamespace) -> None:
    store.add("writing", "house")
    store.write_state(default_writing="house")
    dirs = [*store.dirs("writing"), BUNDLED_WRITINGS_DIR]
    assert resolve_default("writing", "", dirs, language="en") == ("house", "default", [])


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
