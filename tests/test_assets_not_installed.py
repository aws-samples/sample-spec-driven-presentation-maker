# SPDX-License-Identifier: MIT-0
"""A missing icon catalog must never take the MCP server down.

The core raises ``AssetsNotInstalledError``; the tool contract turns it into a
structured response; the local server installs the catalogs in the background
so a clone-free setup needs no separate step.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import sdpm.config as config
from sdpm import tools
from sdpm.knowledge import assets
from sdpm.knowledge.assets import download


@pytest.fixture
def no_assets(tmp_path, monkeypatch):
    """Point every discovery location at empty directories."""
    monkeypatch.setattr(assets, "ASSETS_DIR", tmp_path / "bundled")
    monkeypatch.setattr(assets, "get_user_config_dir", lambda: tmp_path / "user")
    monkeypatch.setattr(assets, "get_extra_sources", lambda: [])
    monkeypatch.setattr(assets, "assets_install_dir", lambda: tmp_path / "user" / "assets")
    monkeypatch.setattr(config, "ASSETS_DIR", tmp_path / "bundled")
    assets.invalidate_manifest_cache()
    yield tmp_path
    assets.invalidate_manifest_cache()


def test_core_raises_instead_of_exiting(no_assets):
    with pytest.raises(assets.AssetsNotInstalledError) as excinfo:
        assets.search_assets("cloud")
    assert "sdpm-install-assets" in excinfo.value.install_command
    with pytest.raises(assets.AssetsNotInstalledError):
        assets.resolve_asset_path("icons:cloud")
    assert assets.assets_installed() is False


def test_tool_reports_missing_catalog(no_assets, monkeypatch):
    monkeypatch.setattr(download, "_background", {"state": "idle", "error": None, "thread": None})
    result = tools.search_assets("cloud")
    assert result["results"] == []
    assert result["assets_installed"] is False
    assert "sdpm-install-assets" in result["error"]
    # Empty query (list sources) takes the same path.
    assert tools.search_assets("")["assets_installed"] is False


def test_tool_reports_background_install_in_progress(no_assets, monkeypatch):
    monkeypatch.setattr(download, "_background", {"state": "running", "error": None, "thread": None})
    result = tools.search_assets("cloud")
    assert result["install_status"]["state"] == "running"
    assert "retry" in result["error"]


def test_ensure_assets_installed_async_runs_once_and_reports(no_assets, monkeypatch):
    monkeypatch.setattr(download, "_background", {"state": "idle", "error": None, "thread": None})
    calls: list[list[str]] = []

    def fake_install(sources, dest=None):
        calls.append(list(sources))
        target = no_assets / "user" / "assets" / "aws"
        target.mkdir(parents=True)
        (target / "manifest.json").write_text(json.dumps({
            "source": "aws",
            "icons": [{"name": "cloud", "file": "cloud.svg", "tags": [], "category": "c", "type": "service"}],
        }))
        return {"destination": str(dest), "sources": []}

    monkeypatch.setattr(download, "install_assets", fake_install)
    assert download.ensure_assets_installed_async() is True
    download._background["thread"].join(timeout=10)
    assert download.install_status() == {"state": "done", "error": None}
    assert calls == [list(download.SUPPORTED_SOURCES)]
    # Catalog now present: a second call is a no-op.
    assert download.ensure_assets_installed_async() is False
    assert calls == [list(download.SUPPORTED_SOURCES)]


def test_ensure_assets_installed_async_failure_is_reported_not_raised(no_assets, monkeypatch):
    monkeypatch.setattr(download, "_background", {"state": "idle", "error": None, "thread": None})

    def boom(sources, dest=None):
        raise OSError("offline")

    monkeypatch.setattr(download, "install_assets", boom)
    assert download.ensure_assets_installed_async() is True
    download._background["thread"].join(timeout=10)
    assert download.install_status() == {"state": "failed", "error": "offline"}
    result = tools.search_assets("cloud")
    assert result["assets_installed"] is False
    assert result["install_status"]["state"] == "failed"


def test_ensure_assets_installed_async_skips_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_background", {"state": "idle", "error": None, "thread": None})
    called = []
    monkeypatch.setattr(download, "install_assets", lambda *a, **k: called.append(1))
    assert Path(config.ASSETS_DIR, "aws", "manifest.json").exists(), "dev checkout has catalogs"
    assert download.ensure_assets_installed_async() is False
    assert called == []


def test_write_atomic_replaces_whole_file(tmp_path):
    target = tmp_path / "manifest.json"
    target.write_text("old")
    download._write_atomic(target, "new")
    assert target.read_text() == "new"
    assert not target.with_suffix(".json.tmp").exists()
