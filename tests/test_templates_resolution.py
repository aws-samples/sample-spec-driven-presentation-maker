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
    bundled = Path(__file__).resolve().parent.parent / "sdpm" / "templates"
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


def test_list_templates_with_metadata_builtin_note_from_notes(tmp_path: Path) -> None:
    """Builtin descriptions come from builtin_notes; the cache still feeds the analysis fields."""
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    (bundled_dir / "blank-dark.pptx").write_bytes(b"dummy")

    metadata = {
        "builtin:blank-dark": {"description": "Stale cache note", "layout_count": 7},
        "blank-dark": {"description": "Legacy entry", "layout_count": 1},
    }
    result = list_templates_with_metadata([bundled_dir], metadata, {"blank-dark": "User note"})
    assert result[0]["description"] == "User note"
    assert result[0]["layout_count"] == 7

    assert list_templates_with_metadata([bundled_dir], metadata)[0]["description"] == ""


def test_list_templates_with_metadata_builtin_note_not_used_for_user(tmp_path: Path) -> None:
    """A same-named user template keeps its own note, not the builtin's."""
    user_dir = tmp_path / "user"
    bundled_dir = tmp_path / "bundled"
    user_dir.mkdir()
    bundled_dir.mkdir()
    (user_dir / "shared.pptx").write_bytes(b"user-ver")
    (bundled_dir / "shared.pptx").write_bytes(b"bundled-ver")

    metadata = {"shared": {"description": "User template note"}}
    result = list_templates_with_metadata([user_dir, bundled_dir], metadata, {"shared": "Builtin note"})

    assert len(result) == 1
    assert result[0]["source"] == "user"
    assert result[0]["description"] == "User template note"


# ── get_builtin_template_notes (state.json) ──


def _write_state(config_home: Path, state: dict) -> Path:
    import json

    path = config_home / "sdpm" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))
    return path


def test_builtin_notes_migrate_from_legacy_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Legacy notes move out of template_metadata["builtin:<name>"] once, keeping the cache.

    A legacy note wins over the new section: after the move only a <= 0.17 install
    writes there, so it is the newer edit.
    """
    import json

    from sdpm.config import get_builtin_template_notes

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("sys.platform", "linux")
    path = _write_state(tmp_path, {
        "pinned_styles": ["report"],
        "builtin_template_notes": {"edited": "Moved note", "kept": "Kept note"},
        "template_metadata": {
            "builtin:blank-dark": {"description": " Old note ", "layout_count": 7},
            "builtin:edited": {"description": "Edited by an older install"},
            "builtin:empty": {"description": ""},
            "my-brand": {"description": "User template note"},
        },
    })

    assert get_builtin_template_notes() == {"edited": "Edited by an older install", "kept": "Kept note", "blank-dark": "Old note"}

    state = json.loads(path.read_text())
    assert state["builtin_template_notes"] == {"edited": "Edited by an older install", "kept": "Kept note", "blank-dark": "Old note"}
    assert state["template_metadata"] == {
        "builtin:blank-dark": {"layout_count": 7},
        "builtin:edited": {},
        "builtin:empty": {},
        "my-brand": {"description": "User template note"},
    }
    assert state["pinned_styles"] == ["report"]
    assert [p.name for p in path.parent.iterdir()] == ["state.json"]  # no temp file left behind
    # Second read: nothing left to migrate, same result.
    assert get_builtin_template_notes() == {"edited": "Edited by an older install", "kept": "Kept note", "blank-dark": "Old note"}


def test_builtin_notes_read_only_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When state.json cannot be rewritten, the notes are still returned and the file is untouched."""
    from sdpm.config import get_builtin_template_notes

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("sys.platform", "linux")
    path = _write_state(tmp_path, {"template_metadata": {"builtin:blank-dark": {"description": "Old note"}}})
    before = path.read_text()

    def _deny(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("read-only")

    monkeypatch.setattr("sdpm.config._write_state", _deny)
    assert get_builtin_template_notes() == {"blank-dark": "Old note"}
    assert path.read_text() == before


def test_builtin_notes_missing_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from sdpm.config import get_builtin_template_notes

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("sys.platform", "linux")
    assert get_builtin_template_notes() == {}
    assert not (tmp_path / "sdpm" / "state.json").exists()


def test_analyze_and_store_template() -> None:
    template_path = Path(__file__).parent.parent / "sdpm" / "templates" / "blank-dark.pptx"
    if not template_path.exists():
        pytest.skip("blank-dark.pptx not available")

    result = analyze_and_store_template(template_path, description="Dark theme")
    assert result["name"] == "blank-dark"
    assert result["description"] == "Dark theme"
    assert isinstance(result["theme_colors"], dict)
    assert isinstance(result["fonts"], dict)
    assert result["layout_count"] > 0
    assert len(result["layouts"]) == result["layout_count"]
    # slide_size must be present (regression: was previously omitted)
    assert "slide_size" in result
    assert "width" in result["slide_size"]
    assert "height" in result["slide_size"]
    assert result["slide_size"]["width"] > 0
    assert result["slide_size"]["height"] > 0
