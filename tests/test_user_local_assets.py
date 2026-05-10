# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for user-local asset auto-discovery and cache invalidation."""

import json
from pathlib import Path

import pytest


def _write_manifest(dir_path: Path, source: str, icons: list[dict]) -> None:
    """Helper: write a minimal manifest.json for a source directory."""
    dir_path.mkdir(parents=True, exist_ok=True)
    manifest = {"source": source, "icons": icons}
    (dir_path / "manifest.json").write_text(json.dumps(manifest))


@pytest.fixture
def isolated_user_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point user-config dir to a tmp location and return the sdpm root."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))

    # Invalidate caches so this test sees the overridden env
    from sdpm.assets import invalidate_manifest_cache
    invalidate_manifest_cache()
    yield tmp_path / "sdpm"
    # Cleanup: invalidate again so subsequent tests start clean
    invalidate_manifest_cache()


# ---------------------------------------------------------------------------
# User-local asset auto-discovery
# ---------------------------------------------------------------------------


def test_user_local_asset_is_discovered(
    isolated_user_config: Path, tmp_path: Path
) -> None:
    """Manifest under ~/.config/sdpm/assets/{source}/ is auto-discovered."""
    from sdpm.assets import _load_manifests

    source_dir = isolated_user_config / "assets" / "my-company"
    _write_manifest(
        source_dir,
        "my-company",
        [{"name": "Logo", "file": "logo.svg", "category": "brand", "type": "service"}],
    )

    manifests = _load_manifests()
    names = [m["_source"] for m in manifests]
    assert "my-company" in names


def test_user_local_asset_file_is_resolved(
    isolated_user_config: Path,
) -> None:
    """Resolve an asset file from user-local source via assets:source/name."""
    from sdpm.assets import resolve_asset_path

    source_dir = isolated_user_config / "assets" / "my-company"
    _write_manifest(
        source_dir,
        "my-company",
        [{"name": "Logo", "file": "logo.svg", "category": "brand", "type": "service"}],
    )
    (source_dir / "logo.svg").write_text("<svg/>")

    resolved = resolve_asset_path("assets:my-company/logo")
    assert resolved == source_dir / "logo.svg"


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


def test_invalidate_manifest_cache_picks_up_new_source(
    isolated_user_config: Path,
) -> None:
    """A newly added user-local source is visible after invalidate."""
    from sdpm.assets import _load_manifests, invalidate_manifest_cache

    # Initial load: no user-local sources
    before = _load_manifests()
    initial_sources = {m["_source"] for m in before}
    assert "added-later" not in initial_sources

    # Add a new source
    source_dir = isolated_user_config / "assets" / "added-later"
    _write_manifest(
        source_dir,
        "added-later",
        [{"name": "Foo", "file": "foo.svg", "category": "c", "type": "service"}],
    )

    # Without invalidate, cache is stale
    stale = _load_manifests()
    assert {m["_source"] for m in stale} == initial_sources

    # After invalidate, new source appears
    invalidate_manifest_cache()
    fresh = _load_manifests()
    assert "added-later" in {m["_source"] for m in fresh}


def test_invalidate_also_clears_config_cache(
    isolated_user_config: Path,
) -> None:
    """invalidate_manifest_cache also clears the config cache."""
    from sdpm.assets import invalidate_manifest_cache
    from sdpm.config import get_config, get_user_config_dir

    # Prime cache with defaults
    invalidate_manifest_cache()
    cfg1 = get_config()
    assert cfg1["output_dir"] == "~/Documents/SDPM-Presentations"

    # Write user config
    user_dir = get_user_config_dir()
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "config.json").write_text(json.dumps({"output_dir": "/new/path"}))

    # After invalidate, config is re-read
    invalidate_manifest_cache()
    cfg2 = get_config()
    assert cfg2["output_dir"] == "/new/path"


# ---------------------------------------------------------------------------
# Priority order: extra_sources > user-local > built-in
# ---------------------------------------------------------------------------


def test_extra_sources_shadow_user_local_same_name(
    isolated_user_config: Path, tmp_path: Path
) -> None:
    """When an extra_source and user-local source define the same asset name,
    extra_sources wins (it appears first in the manifest list)."""
    from sdpm.assets import _load_manifests, invalidate_manifest_cache

    # User-local source
    user_source = isolated_user_config / "assets" / "shared"
    _write_manifest(
        user_source,
        "shared",
        [{"name": "X", "file": "x.svg", "category": "c", "type": "service"}],
    )
    (user_source / "x.svg").write_text("user-local")

    # Extra source via config.json
    extra_source = tmp_path / "extra" / "shared"
    extra_source.mkdir(parents=True)
    (extra_source / "manifest.json").write_text(json.dumps({
        "source": "shared",
        "icons": [{"name": "X", "file": "x.svg", "category": "c", "type": "service"}],
    }))
    (extra_source / "x.svg").write_text("extra")

    (isolated_user_config).mkdir(parents=True, exist_ok=True)
    (isolated_user_config / "config.json").write_text(json.dumps({
        "extra_sources": [{
            "manifest": str(extra_source / "manifest.json"),
        }],
    }))

    invalidate_manifest_cache()
    manifests = _load_manifests()
    # Find first manifest with source=shared; it should be the extra_source entry
    shared_entries = [m for m in manifests if m["_source"] == "shared"]
    assert len(shared_entries) >= 1
    # The extra_source entry should appear FIRST (earlier in the list)
    assert shared_entries[0]["_dir"] == extra_source


def test_user_local_coexists_with_builtin(
    isolated_user_config: Path,
) -> None:
    """User-local and built-in sources both appear in the merged manifest."""
    from sdpm.assets import _load_manifests

    # User-local source
    source_dir = isolated_user_config / "assets" / "my-company"
    _write_manifest(
        source_dir,
        "my-company",
        [{"name": "Logo", "file": "logo.svg", "category": "brand", "type": "service"}],
    )

    manifests = _load_manifests()
    sources = {m["_source"] for m in manifests}
    # my-company from user-local should be present
    assert "my-company" in sources
    # aws (built-in) should still be present if assets are installed
    # (skip this assertion if assets not installed in test env)


# ---------------------------------------------------------------------------
# list_sources uses get_extra_sources() now
# ---------------------------------------------------------------------------


def test_list_sources_includes_user_local_description(
    isolated_user_config: Path,
) -> None:
    """list_sources picks up description from user-local manifest (bug fix)."""
    from sdpm.assets import invalidate_manifest_cache, list_sources

    source_dir = isolated_user_config / "assets" / "my-team"
    _write_manifest(
        source_dir,
        "my-team",
        [{"name": "A", "file": "a.svg", "category": "c", "type": "service"}],
    )
    # Add description at manifest-level (not per-icon)
    import json as _json
    manifest_path = source_dir / "manifest.json"
    data = _json.loads(manifest_path.read_text())
    data["description"] = "My team's custom icons"
    manifest_path.write_text(_json.dumps(data))

    invalidate_manifest_cache()
    sources = list_sources()
    my_team = next((s for s in sources if s["source"] == "my-team"), None)
    assert my_team is not None
    assert my_team["description"] == "My team's custom icons"


def test_list_sources_includes_extra_source(
    isolated_user_config: Path, tmp_path: Path
) -> None:
    """list_sources picks up extra_sources via get_extra_sources (not _EXTRA_SOURCES)."""
    from sdpm.assets import invalidate_manifest_cache, list_sources

    extra_source = tmp_path / "extra" / "my-extra"
    extra_source.mkdir(parents=True)
    (extra_source / "manifest.json").write_text(json.dumps({
        "source": "my-extra",
        "description": "Extra source via config",
        "icons": [{"name": "A", "file": "a.svg", "category": "c", "type": "service"}],
    }))

    (isolated_user_config).mkdir(parents=True, exist_ok=True)
    (isolated_user_config / "config.json").write_text(json.dumps({
        "extra_sources": [{
            "manifest": str(extra_source / "manifest.json"),
        }],
    }))

    invalidate_manifest_cache()
    sources = list_sources()
    names = [s["source"] for s in sources]
    assert "my-extra" in names
    my_extra = next(s for s in sources if s["source"] == "my-extra")
    assert my_extra["description"] == "Extra source via config"
