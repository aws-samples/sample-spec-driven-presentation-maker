# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""run_python always runs inside a deck workspace: a missing deck is a boundary error."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _local_sandbox_tools():
    for sub in ("servers/local",):
        p = str(_ROOT / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    import importlib

    return importlib.import_module("sandbox_tools")


def test_local_run_python_rejects_missing_deck(tmp_path: Path) -> None:
    tools = _local_sandbox_tools()
    result = json.loads(tools.run_python("calc", "print(1)", ""))
    assert "deck directory not found" in result["error"]
    result = json.loads(tools.run_python("calc", "print(1)", str(tmp_path / "nope")))
    assert "deck directory not found" in result["error"]
    assert "output" not in result


def test_local_run_python_runs_inside_existing_deck(tmp_path: Path) -> None:
    tools = _local_sandbox_tools()
    (tmp_path / "deck.json").write_text("{}")
    (tmp_path / "slides").mkdir()
    result = json.loads(tools.run_python("calc", "print(2 ** 10)", str(tmp_path)))
    assert result["output"].strip() == "1024"


def test_remote_run_python_rejects_missing_deck(monkeypatch) -> None:
    sys.path.insert(0, str(_ROOT / "servers" / "remote"))
    try:
        import server as remote_server  # noqa: PLC0415
    finally:
        sys.path.pop(0)
    result = json.loads(remote_server.run_python("calc", "print(1)", ""))
    assert "deck_id is required" in result["error"]
