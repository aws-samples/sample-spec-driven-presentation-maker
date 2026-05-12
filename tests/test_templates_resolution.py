# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for template directory resolution in sdpm.api."""

import os
from pathlib import Path

import pytest

from sdpm.api import _find_template_in_dirs, _resolve_template, get_templates_dirs


@pytest.fixture
def temp_template_dir(tmp_path: Path) -> Path:
    d = tmp_path / "templates"
    d.mkdir()
    (d / "foo.pptx").write_bytes(b"dummy")
    return d


def test_templates_dir_includes_bundled() -> None:
    dirs = get_templates_dirs()
    bundled = Path(__file__).resolve().parent.parent / "skill" / "templates"
    assert bundled in dirs


def test_templates_dir_respects_env(monkeypatch: pytest.MonkeyPatch, temp_template_dir: Path) -> None:
    monkeypatch.setenv("SDPM_TEMPLATES_DIR", str(temp_template_dir))
    dirs = get_templates_dirs()
    assert dirs[0] == temp_template_dir


def test_templates_dir_supports_multiple_env_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    monkeypatch.setenv("SDPM_TEMPLATES_DIR", f"{d1}{os.pathsep}{d2}")
    dirs = get_templates_dirs()
    assert dirs[0] == d1
    assert dirs[1] == d2


def test_find_template_in_dirs_first_match_wins(tmp_path: Path) -> None:
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    (d1 / "shared.pptx").write_bytes(b"d1")
    (d2 / "shared.pptx").write_bytes(b"d2")
    found = _find_template_in_dirs("shared", [d1, d2])
    assert found == d1 / "shared.pptx"


def test_find_template_accepts_name_with_or_without_extension(temp_template_dir: Path) -> None:
    assert _find_template_in_dirs("foo", [temp_template_dir]) == temp_template_dir / "foo.pptx"
    assert _find_template_in_dirs("foo.pptx", [temp_template_dir]) == temp_template_dir / "foo.pptx"


def test_find_template_returns_none_when_missing(tmp_path: Path) -> None:
    assert _find_template_in_dirs("missing", [tmp_path]) is None


def test_resolve_template_falls_back_to_templates_dirs(temp_template_dir: Path, tmp_path: Path) -> None:
    data = {"template": "foo.pptx"}
    input_path = tmp_path / "presentation.json"
    template_file, custom = _resolve_template(data, str(input_path), [temp_template_dir])
    assert template_file == temp_template_dir / "foo.pptx"
    assert custom is True


def test_resolve_template_raises_when_not_found(tmp_path: Path) -> None:
    data = {"template": "missing.pptx"}
    input_path = tmp_path / "presentation.json"
    with pytest.raises(FileNotFoundError, match="No template specified"):
        _resolve_template(data, str(input_path), [tmp_path])


# ── list_templates_with_metadata ──


from sdpm.api import list_templates_with_metadata, analyze_and_store_template


def test_list_templates_with_metadata_source_detection(tmp_path: Path) -> None:
    user_dir = tmp_path / "user"
    bundled_dir = tmp_path / "bundled"
    user_dir.mkdir()
    bundled_dir.mkdir()
    (user_dir / "custom.pptx").write_bytes(b"dummy")
    (bundled_dir / "builtin.pptx").write_bytes(b"dummy")

    metadata = {"custom": {"description": "My template", "theme_colors": {}, "fonts": {}, "layout_count": 3}}
    result = list_templates_with_metadata([user_dir, bundled_dir], metadata)

    assert len(result) == 2
    custom = next(r for r in result if r["name"] == "custom")
    builtin = next(r for r in result if r["name"] == "builtin")
    assert custom["source"] == "user"
    assert custom["description"] == "My template"
    assert custom["layout_count"] == 3
    assert builtin["source"] == "builtin"
    assert builtin["description"] == ""


def test_list_templates_with_metadata_user_shadows_builtin(tmp_path: Path) -> None:
    user_dir = tmp_path / "user"
    bundled_dir = tmp_path / "bundled"
    user_dir.mkdir()
    bundled_dir.mkdir()
    (user_dir / "shared.pptx").write_bytes(b"user-ver")
    (bundled_dir / "shared.pptx").write_bytes(b"bundled-ver")

    result = list_templates_with_metadata([user_dir, bundled_dir], {})
    assert len(result) == 1
    assert result[0]["source"] == "user"


def test_analyze_and_store_template() -> None:
    template_path = Path(__file__).parent.parent / "skill" / "templates" / "blank-dark.pptx"
    if not template_path.exists():
        pytest.skip("blank-dark.pptx not available")

    result = analyze_and_store_template(template_path, description="Dark theme")
    assert result["name"] == "blank-dark"
    assert result["description"] == "Dark theme"
    assert isinstance(result["theme_colors"], dict)
    assert isinstance(result["fonts"], dict)
    assert result["layout_count"] > 0
    assert len(result["layouts"]) == result["layout_count"]
