# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for set_default: stating a standing choice of style, structure or writing guide.

Setting, switching and clearing are one operation, so they are tested as one.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sdpm.api import set_default
from sdpm.knowledge.reference import (
    BUNDLED_STRUCTURES_DIR,
    BUNDLED_WRITINGS_DIR,
    resolve_default,
)


@pytest.fixture
def stores(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """One guide and one style of each kind the user could point a default at."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    config_dir = tmp_path / "config" / "sdpm"
    config_dir.mkdir(parents=True)

    styles = tmp_path / "styles"
    styles.mkdir()
    (styles / "plain.html").write_text("<html><head><title>Plain</title></head></html>")
    (styles / "other.html").write_text("<html><head><title>Other</title></head></html>")
    monkeypatch.setenv("SDPM_STYLES_DIR", str(styles))

    structures = tmp_path / "structure"
    structures.mkdir()
    (structures / "report-first.md").write_text("---\ndescription: Report\n---\n")
    monkeypatch.setenv("SDPM_STRUCTURES_DIR", f"{structures}{os.pathsep}{BUNDLED_STRUCTURES_DIR}")

    writings = tmp_path / "writing"
    writings.mkdir()
    (writings / "house.md").write_text("---\ndescription: House\n---\n")
    monkeypatch.setenv("SDPM_WRITINGS_DIR", f"{writings}{os.pathsep}{BUNDLED_WRITINGS_DIR}")

    state_path = config_dir / "state.json"

    def write_state(**keys: object) -> None:
        from sdpm import config

        state_path.write_text(json.dumps(keys))
        config.invalidate_cache()

    def read_state() -> dict:
        return json.loads(state_path.read_text()) if state_path.exists() else {}

    def dirs(kind: str) -> list[Path]:
        from sdpm.api import get_structures_dirs, get_styles_dirs, get_writings_dirs

        return {
            "style": get_styles_dirs, "structure": get_structures_dirs, "writing": get_writings_dirs
        }[kind]()

    write_state()
    return SimpleNamespace(write_state=write_state, read_state=read_state, dirs=dirs, path=state_path)


@pytest.mark.parametrize(
    ("kind", "name"), [("style", "plain"), ("structure", "report-first"), ("writing", "house")]
)
def test_each_kind_records_its_own_default(stores: SimpleNamespace, kind: str, name: str) -> None:
    result = set_default(kind, name)
    assert result["default"] == name
    assert stores.read_state()[f"default_{kind}"] == name


def test_a_name_that_does_not_exist_changes_nothing(stores: SimpleNamespace) -> None:
    before = stores.read_state()
    result = set_default("structure", "nope")
    assert result["error"].startswith("Structure not found: nope.")
    assert stores.read_state() == before


def test_a_default_outside_the_pins_is_accepted_with_a_notice(stores: SimpleNamespace) -> None:
    stores.write_state(pinned_styles=["other"])
    result = set_default("style", "plain")
    assert result["default"] == "plain"
    assert len(result["notices"]) == 1 and "plain" in result["notices"][0]


def test_a_default_says_nothing_when_nothing_is_pinned(stores: SimpleNamespace) -> None:
    result = set_default("style", "plain")
    assert result["notices"] == []


def test_passing_another_name_switches_the_default(stores: SimpleNamespace) -> None:
    set_default("style", "plain")
    set_default("style", "other")
    assert stores.read_state()["default_style"] == "other"


def test_an_empty_name_clears_the_default(stores: SimpleNamespace) -> None:
    """Clearing checks nothing, and resolution goes back to behaving as if unset."""
    set_default("structure", "report-first")
    assert resolve_default("structure", "", stores.dirs("structure"))[1] == "default"

    result = set_default("structure", "")
    assert result["default"] == ""
    assert stores.read_state()["default_structure"] == ""
    assert resolve_default("structure", "", stores.dirs("structure"))[1] == "unset"


def test_an_unknown_kind_is_rejected(stores: SimpleNamespace) -> None:
    result = set_default("template", "blank-light")
    assert "kind must be one of" in result["error"]
    assert stores.read_state() == {}
