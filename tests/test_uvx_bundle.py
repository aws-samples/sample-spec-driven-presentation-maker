# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Distribution tests for the clone-free uvx server bundle."""

from __future__ import annotations

import io
import json
import os
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, check=True)


@pytest.fixture(scope="module")
def built_wheels(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    output = tmp_path_factory.mktemp("uvx-wheels")
    sdpm_output = output / "sdpm"
    local_output = output / "local"
    sdpm_output.mkdir()
    local_output.mkdir()

    # Deliberately build the default sdist + wheel pair. The wheel is built
    # from the generated sdist, which catches bundle paths that only work in
    # a repository checkout.
    _run("uv", "build", "--out-dir", str(sdpm_output), str(ROOT / "sdpm"))
    _run("uv", "build", "--wheel", "--out-dir", str(local_output), str(ROOT / "servers" / "local"))

    assert next(sdpm_output.glob("*.tar.gz")).is_file()
    return next(sdpm_output.glob("*.whl")), next(local_output.glob("*.whl"))


def test_sdpm_wheel_bundles_runtime_data_and_shared(
    built_wheels: tuple[Path, Path], tmp_path: Path,
) -> None:
    sdpm_wheel, _ = built_wheels
    venv = tmp_path / "venv"
    _run("uv", "venv", "--python", os.fspath(Path(os.sys.executable)), str(venv))
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    _run("uv", "pip", "install", "--python", str(python), "--no-deps", str(sdpm_wheel))

    cache_root = tmp_path / "cache"
    config_root = tmp_path / "config"
    home_root = tmp_path / "home"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("SDPM_SKILL_ROOT", None)
    env["HOME"] = str(home_root)
    env["XDG_CONFIG_HOME"] = str(config_root)
    env["XDG_CACHE_HOME"] = str(cache_root)

    probe = tmp_path / "probe.py"
    probe.write_text(
        """
import contextlib
import io
import json
import shutil

import sdpm.config as config
import shared
from sdpm.knowledge.assets import invalidate_manifest_cache, resolve_asset_path, search_assets

install_dir = config.assets_install_dir()
source_dir = install_dir / "test"
source_dir.mkdir(parents=True)
(source_dir / "cloud-test.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
(source_dir / "manifest.json").write_text(json.dumps({
    "source": "test",
    "icons": [{
        "name": "Cloud Test",
        "file": "cloud-test.svg",
        "tags": ["aws"],
        "category": "test",
        "type": "service",
        "aspectRatio": 1,
    }],
}))
invalidate_manifest_cache()
matches = search_assets("aws")[0]["matches"]
asset_path = resolve_asset_path(matches[0]["ref"])
asset_file = asset_path.is_file()

shutil.rmtree(install_dir)
invalidate_manifest_cache()
stderr = io.StringIO()
with contextlib.redirect_stderr(stderr):
    try:
        search_assets("aws")
    except SystemExit as error:
        missing_exit = error.code
    else:
        missing_exit = None

print(json.dumps({
    "references": config.REFERENCES_DIR.is_dir(),
    "templates": config.TEMPLATES_DIR.is_dir(),
    "assets": config.ASSETS_DIR.is_dir(),
    "asset_install_dir": str(install_dir),
    "asset_search": bool(matches),
    "asset_file": asset_file,
    "missing_exit": missing_exit,
    "missing_message": stderr.getvalue(),
    "bundled": config.SKILL_ROOT.name == "_data",
    "cache": str(config.CACHE_DIR),
}))
""",
        encoding="utf-8",
    )
    result = _run(str(python), str(probe), cwd=tmp_path, env=env)
    paths = json.loads(result.stdout)
    assert paths == {
        "references": True,
        "templates": True,
        "assets": True,
        "asset_install_dir": str(config_root / "sdpm" / "assets"),
        "asset_search": True,
        "asset_file": True,
        "missing_exit": 1,
        "missing_message": paths["missing_message"],
        "bundled": True,
        "cache": str(cache_root / "sdpm"),
    }
    assert "sdpm-install-assets" in paths["missing_message"]
    assert "scripts/download_aws_icons.py" not in paths["missing_message"]

    with ZipFile(sdpm_wheel) as archive:
        names = archive.namelist()
    assert any(name.startswith("shared/") for name in names)
    assert "sdpm/_data/assets/.bundle-marker" in names
    assert not any(name.startswith("sdpm/_data/assets/builtin/") for name in names)
    assert not any(name.startswith("sdpm/_data/assets/") and name.endswith(".svg") for name in names)
    assert not any(name.endswith("config.example.json") for name in names)
    assert not any(name.endswith(".DS_Store") for name in names)


def test_local_server_wheel_exposes_console_scripts(
    built_wheels: tuple[Path, Path], tmp_path: Path,
) -> None:
    sdpm_wheel, local_wheel = built_wheels
    with ZipFile(local_wheel) as archive:
        names = archive.namelist()
        entry_points_name = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        entry_points = archive.read(entry_points_name).decode()

    assert "sdpm-mcp = server:main" in entry_points
    assert "sdpm-install-assets = sdpm.knowledge.assets.download:main" in entry_points
    for module in ("server.py", "sandbox.py", "sandbox_tools.py"):
        assert module in names

    venv = tmp_path / "venv"
    _run("uv", "venv", "--python", os.fspath(Path(os.sys.executable)), str(venv))
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    _run(
        "uv", "pip", "install", "--python", str(python), "--no-deps",
        str(sdpm_wheel), str(local_wheel),
    )
    scripts_dir = python.parent
    installer = scripts_dir / ("sdpm-install-assets.exe" if os.name == "nt" else "sdpm-install-assets")
    result = _run(str(installer), "--help", cwd=tmp_path)
    assert "--sources" in result.stdout
    assert "aws,material" in result.stdout


def test_install_assets_writes_mocked_aws_zip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from sdpm.knowledge.assets import download

    archive_data = io.BytesIO()
    member = "Architecture-Service-Icons_01302026/Arch_Compute/48/Arch_AWS-Lambda_48.svg"
    with ZipFile(archive_data, "w") as archive:
        archive.writestr(member, "<svg xmlns='http://www.w3.org/2000/svg'/>")
    archive_data.seek(0)
    monkeypatch.setattr(download, "urlopen", lambda _url: archive_data)

    result = download.install_assets(["aws"], dest=tmp_path / "assets")

    source_result = result["sources"][0]
    assert result["destination"] == str(tmp_path / "assets")
    assert source_result["source"] == "aws"
    assert source_result["count"] == 1
    assert (tmp_path / "assets" / "aws" / "Arch_AWS-Lambda_48.svg").is_file()
    manifest = json.loads((tmp_path / "assets" / "aws" / "manifest.json").read_text())
    assert manifest["source"] == "aws"
    assert manifest["recolorProtected"] is True
    assert manifest["icons"][0]["name"] == "AWS Lambda"
