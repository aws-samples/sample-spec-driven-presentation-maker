# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Both local MCP servers start the icon-catalog install on launch; SDPM_AUTO_INSTALL_ASSETS=0 opts out."""

import importlib.util
import sys
from pathlib import Path

import pytest

_LOCAL = Path(__file__).resolve().parent.parent / "servers" / "local"


def _load(monkeypatch, filename: str):
    monkeypatch.syspath_prepend(str(_LOCAL))
    name = f"sdpm_local_auto_install_test_{filename.removesuffix('.py')}"
    spec = importlib.util.spec_from_file_location(name, _LOCAL / filename)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("filename", ["server.py", "server_acp.py"])
@pytest.mark.parametrize(("env", "installs"), [(None, True), ("1", True), ("0", False)])
def test_main_starts_asset_install_unless_opted_out(monkeypatch, filename, env, installs):
    module = _load(monkeypatch, filename)
    calls: list[str] = []
    monkeypatch.setattr(
        "sdpm.knowledge.assets.download.ensure_assets_installed_async", lambda: calls.append("install")
    )
    monkeypatch.setattr(module.mcp, "run", lambda **kwargs: calls.append(f"run:{kwargs.get('transport')}"))
    if env is None:
        monkeypatch.delenv("SDPM_AUTO_INSTALL_ASSETS", raising=False)
    else:
        monkeypatch.setenv("SDPM_AUTO_INSTALL_ASSETS", env)
    module.main()
    assert calls == (["install"] if installs else []) + ["run:stdio"]
