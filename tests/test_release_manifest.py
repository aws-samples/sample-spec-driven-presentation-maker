# SPDX-License-Identifier: MIT-0
"""`scripts/release/manifest.py` — six manifests from one source, readable by the updater."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "release"))
sys.path.insert(0, str(ROOT / "servers" / "local"))
import checkout_update as cu  # noqa: E402
import manifest  # noqa: E402

CHANGELOG = """# Changelog

## [Unreleased]

## [9.9.9] - 2026-11-08

### Upgrading from 9.9.8

**Local installs (`sdpm update`).**

- **Follows releases.** `sdpm update --channel main` keeps following main.
"""


@pytest.fixture
def root(tmp_path):
    (tmp_path / "sdpm" / "sdpm").mkdir(parents=True)
    (tmp_path / "sdpm" / "sdpm" / "__init__.py").write_text('__version__ = "9.9.9"\n')
    (tmp_path / "servers" / "local").mkdir(parents=True)
    shutil.copy(str(ROOT / "servers" / "local" / "pyproject.toml"), str(tmp_path / "servers" / "local"))
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    return tmp_path


def test_six_manifests_that_the_updater_accepts(root, tmp_path):
    out = tmp_path / "out"
    assert manifest.main(["--tag", "v9.9.9", "--out", str(out), "--root", str(root), "--commit", "d" * 40]) == 0
    files = sorted(p.name for p in out.iterdir())
    assert files == sorted(cu.manifest_name(o, u) for o in manifest.OSES for u in manifest.USES)
    for os_name in manifest.OSES:
        for use in manifest.USES:
            data = json.loads((out / cu.manifest_name(os_name, use)).read_text())
            parsed = cu.parse_manifest(data, tag="v9.9.9", os_name=os_name, use=use)
            assert parsed["commit"] == "d" * 40 and parsed["min_launcher"] == 1
            names = {r["name"]: r for r in parsed["requires"]}
            assert names["python"]["min"] == "3.11" and names["node"]["profiles"] == ["full"]
            assert parsed["notes"] == ["Follows releases. `sdpm update --channel main` keeps following main."]


def test_a_version_that_is_not_the_tag_fails(root, tmp_path):
    with pytest.raises(SystemExit) as stop:
        manifest.main(["--tag", "v9.9.8", "--out", str(tmp_path / "out"), "--root", str(root), "--commit", "d" * 40])
    assert "9.9.9" in str(stop.value)
    with pytest.raises(SystemExit):
        manifest.main(["--tag", "v9.9.9-rc.1", "--out", str(tmp_path / "out"), "--root", str(root)])
