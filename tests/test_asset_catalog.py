# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Asset catalog search, resolution and source listing on an isolated catalog.

``sdpm.knowledge.assets`` merges manifests from four places (config
``extra_sources``, user-local, built-in, legacy ``icons/``). Every test here
replaces all four with a tmp catalog, so results do not depend on whether the
real icon packs are downloaded on the machine running the tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import sdpm.knowledge.assets as assets


def _manifest(dir_path: Path, icons: list[dict], **extra) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / "manifest.json"
    path.write_text(json.dumps({"icons": icons, **extra}))
    return path


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    """Built-in dir with two sources, empty user dir, no extra sources."""
    builtin = tmp_path / "skill" / "assets"
    aws = builtin / "aws"
    _manifest(aws, [
        {"name": "AWS Lambda", "file": "lambda.svg", "type": "service", "category": "compute",
         "tags": ["serverless", "function"], "description": "Run code"},
        {"name": "Lambda Function", "file": "res/lambda-fn.svg", "type": "resource", "tags": ["serverless"]},
        {"name": "Amazon S3", "file": "s3.svg", "type": "service", "tags": ["object storage"],
         "aspectRatio": 2},
        {"name": "Arrow", "file": "arrow.svg", "type": "shape"},
        {"name": "Logo Light", "file": "logo_light.svg"},
        {"name": "Logo Dark", "file": "logo_dark.svg"},
    ], source="aws", description="AWS icons", recolorProtected={"when": {"type": ["service"]}})
    for f in ("lambda.svg", "s3.svg", "arrow.svg", "logo_light.svg", "logo_dark.svg"):
        (aws / f).write_text("<svg/>")
    (aws / "res").mkdir()
    (aws / "res" / "lambda-fn.svg").write_text("<svg/>")
    (aws / "orphan.png").write_bytes(b"png")  # on disk, not in the manifest

    material = builtin / "material"
    _manifest(material, [{"name": "Person", "file": "person.svg", "tags": ["user"]}])
    (material / "person.svg").write_text("<svg/>")

    user_dir = tmp_path / "user"
    extra: list[dict] = []
    monkeypatch.setattr(assets, "ASSETS_DIR", builtin)
    monkeypatch.setattr(assets, "get_user_config_dir", lambda: user_dir)
    monkeypatch.setattr(assets, "get_extra_sources", lambda: extra)
    monkeypatch.setattr(assets, "_manifest_cache", None)
    yield {"builtin": builtin, "user": user_dir, "extra": extra, "tmp": tmp_path}
    assets._manifest_cache = None


def _refs(result):
    return [m["ref"] for m in result["matches"]]


# ---------------------------------------------------------------------------
# search_assets
# ---------------------------------------------------------------------------

class TestSearch:
    def test_services_rank_before_resources(self, catalog):
        [res] = assets.search_assets("lambda")
        assert _refs(res) == ["assets:aws/lambda", "assets:aws/res/lambda-fn"]
        assert res["total"] == 2
        top = res["matches"][0]
        assert (top["category"], top["type"], top["description"]) == ("compute", "service", "Run code")

    def test_tag_match_and_normalised_query(self, catalog):
        [res] = assets.search_assets("object-storage")
        assert _refs(res) == ["assets:aws/s3"]
        assert res["matches"][0]["size_hint"] == "w:100 h:50"

    def test_multiple_queries_give_one_result_each(self, catalog):
        out = assets.search_assets("lambda person")
        assert [r["query"] for r in out] == ["lambda", "person"]
        assert _refs(out[1]) == ["assets:material/person"]

    def test_shapes_only_with_type_filter(self, catalog):
        assert assets.search_assets("arrow")[0]["matches"] == []
        assert _refs(assets.search_assets("arrow", type_filter="shape")[0]) == ["assets:aws/arrow"]

    def test_source_filter(self, catalog):
        assert assets.search_assets("person", source_filter="aws")[0]["matches"] == []

    def test_theme_filter(self, catalog):
        assert _refs(assets.search_assets("logo", theme_filter="light")[0]) == ["assets:aws/logo_light"]
        assert _refs(assets.search_assets("logo", theme_filter="dark")[0]) == ["assets:aws/logo_dark"]

    def test_limit_keeps_total(self, catalog):
        [res] = assets.search_assets("serverless", limit=1)
        assert len(res["matches"]) == 1 and res["total"] == 2

    def test_no_catalog_raises(self, catalog, monkeypatch):
        monkeypatch.setattr(assets, "ASSETS_DIR", catalog["tmp"] / "none")
        monkeypatch.setattr(assets, "_manifest_cache", None)
        assert assets.assets_installed() is False
        with pytest.raises(assets.AssetsNotInstalledError) as exc:
            assets.search_assets("x")
        assert exc.value.install_command in str(exc.value)

    def test_print_search_results(self, catalog, capsys):
        assets.print_search_results(assets.search_assets("serverless", limit=1), limit=1)
        out = capsys.readouterr().out
        assert "# serverless" in out
        assert "AWS Lambda [aws/compute/service]" in out
        assert "Run code" in out and "assets:aws/lambda" in out
        assert "... and 1 more" in out


# ---------------------------------------------------------------------------
# resolve_asset_path / check / recolor protection
# ---------------------------------------------------------------------------

class TestResolve:
    @pytest.mark.parametrize("ref", [
        "assets:aws/lambda", "assets:aws/lambda.svg", "icons:lambda", "lambda", "assets:lambda",
    ])
    def test_ref_spellings(self, catalog, ref):
        assert assets.resolve_asset_path(ref) == catalog["builtin"] / "aws" / "lambda.svg"

    def test_manifest_subdirectory(self, catalog):
        assert assets.resolve_asset_path("assets:aws/res/lambda-fn") == \
            catalog["builtin"] / "aws" / "res" / "lambda-fn.svg"

    def test_file_outside_manifest_found_by_directory_scan(self, catalog):
        assert assets.resolve_asset_path("assets:aws/orphan") == catalog["builtin"] / "aws" / "orphan.png"
        assert assets.resolve_asset_path("orphan") == catalog["builtin"] / "aws" / "orphan.png"

    def test_unknown_asset(self, catalog, capsys):
        with pytest.raises(FileNotFoundError):
            assets.resolve_asset_path("assets:aws/nope")
        with pytest.raises(FileNotFoundError):
            assets.resolve_asset_path("assets:missing-source/nope")
        with pytest.raises(FileNotFoundError):
            assets.resolve_asset_path("icons:nope")
        assert "Asset not found: nope" in capsys.readouterr().err
        assert assets.check_asset_exists("icons:nope") is False
        assert assets.check_asset_exists("icons:lambda") is True

    def test_nothing_installed_raises_install_hint(self, catalog, monkeypatch):
        monkeypatch.setattr(assets, "ASSETS_DIR", catalog["tmp"] / "none")
        monkeypatch.setattr(assets, "_manifest_cache", None)
        with pytest.raises(assets.AssetsNotInstalledError):
            assets.resolve_asset_path("icons:lambda")

    def test_recolor_protection_by_type(self, catalog):
        assert assets.is_recolor_protected("assets:aws/lambda") is True
        assert assets.is_recolor_protected("icons:lambda-fn") is False  # resource type
        assert assets.is_recolor_protected("assets:aws/nope") is False
        assert assets.is_recolor_protected("lambda") is False  # bare names are never protected

    def test_recolor_protection_flag(self):
        assert assets._check_recolor_protected(True, {}) is True
        assert assets._check_recolor_protected(False, {"type": "service"}) is False
        assert assets._check_recolor_protected({"when": {}}, {"type": "service"}) is False


# ---------------------------------------------------------------------------
# Source priority and listing
# ---------------------------------------------------------------------------

class TestSources:
    def test_extra_source_wins_and_is_listed(self, catalog):
        files = catalog["tmp"] / "corp-files"
        files.mkdir()
        (files / "lambda.svg").write_text("<svg id='corp'/>")
        manifest = _manifest(catalog["tmp"] / "corp-meta",
                             [{"name": "Corp Lambda", "file": "lambda.svg"}],
                             description="Corporate")
        catalog["extra"].append({"manifest": str(manifest), "source": "corp",
                                 "files_dir": str(files), "recolorProtected": True})
        assert assets.resolve_asset_path("icons:lambda") == files / "lambda.svg"
        assert assets.is_recolor_protected("icons:lambda") is True
        listed = {s["source"]: s for s in assets.list_sources()}
        assert listed["corp"] == {"source": "corp", "count": 1, "description": "Corporate"}
        assert listed["aws"]["description"] == "AWS icons"
        assert listed["material"] == {"source": "material", "count": 1, "description": ""}

    def test_extra_source_files_found_without_manifest_entry(self, catalog):
        meta = catalog["tmp"] / "corp2"
        manifest = _manifest(meta, [])
        (meta / "badge.png").write_bytes(b"png")
        catalog["extra"].append({"manifest": str(manifest)})
        assert assets.resolve_asset_path("badge") == meta / "badge.png"

    def test_user_local_source_description_and_scan(self, catalog):
        user_src = catalog["user"] / "assets" / "mine"
        _manifest(user_src, [{"name": "Mine", "file": "mine.svg"}], description="My icons")
        (user_src / "loose.svg").write_text("<svg/>")
        listed = {s["source"]: s for s in assets.list_sources()}
        assert listed["mine"]["description"] == "My icons"
        assert assets.resolve_asset_path("loose") == user_src / "loose.svg"

    def test_legacy_icons_directory(self, catalog):
        legacy = catalog["builtin"].parent / "icons"
        _manifest(legacy, [{"name": "Old", "file": "old.svg"}])
        (legacy / "old.svg").write_text("<svg/>")
        (legacy / "older.png").write_bytes(b"png")
        assert {s["source"] for s in assets.list_sources()} >= {"icons-legacy"}
        assert assets.resolve_asset_path("icons:old") == legacy / "old.svg"
        assert assets.resolve_asset_path("older") == legacy / "older.png"

    def test_manifests_are_cached_until_invalidated(self, catalog):
        first = assets._load_manifests()
        assert assets._load_manifests() is first
