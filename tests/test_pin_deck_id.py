# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Composers cannot lose the deck: deck-scoped tool calls get the dispatched deck_id,
and a sandbox without a workspace refuses file writes."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[1]


def _load_message_hooks(monkeypatch):
    hooks = ModuleType("strands.hooks")
    for name in ("BeforeModelCallEvent", "BeforeToolCallEvent", "HookProvider", "HookRegistry"):
        setattr(hooks, name, type(name, (), {}))
    strands = ModuleType("strands")
    strands.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "strands", strands)
    monkeypatch.setitem(sys.modules, "strands.hooks", hooks)
    spec = importlib.util.spec_from_file_location("message_hooks_under_test", _ROOT / "agent" / "message_hooks.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_pin_deck_id_fills_missing_and_wrong_deck_id(monkeypatch) -> None:
    mh = _load_message_hooks(monkeypatch)
    call = {"name": "run_python", "input": {"code": "print(1)"}}
    assert mh.pin_deck_id(call, "abc12345") is True
    assert call["input"]["deck_id"] == "abc12345"

    call = {"name": "generate_pptx", "input": {"deck_id": "other"}}
    assert mh.pin_deck_id(call, "abc12345") is True
    assert call["input"]["deck_id"] == "abc12345"

    call = {"name": "get_preview", "input": {"deck_id": "abc12345", "slugs": ["a"]}}
    assert mh.pin_deck_id(call, "abc12345") is False


def test_pin_deck_id_leaves_other_tools_alone(monkeypatch) -> None:
    mh = _load_message_hooks(monkeypatch)
    call = {"name": "search_assets", "input": {"query": "lambda"}}
    assert mh.pin_deck_id(call, "abc12345") is False
    assert "deck_id" not in call["input"]


def test_sandbox_helpers_refuse_writes_without_workspace() -> None:
    spec = importlib.util.spec_from_file_location(
        "remote_sandbox_under_test", _ROOT / "servers" / "remote" / "tools" / "sandbox.py"
    )
    sandbox = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(sandbox)
    guarded = sandbox._HELPERS_PY + sandbox._NO_WORKSPACE_GUARD
    namespace: dict = {}
    exec(guarded, namespace)  # noqa: S102 — executing our own helper source
    import pytest

    with pytest.raises(RuntimeError, match="deck_id"):
        namespace["write_json"]("slides/x.json", {})
    with pytest.raises(RuntimeError, match="deck_id"):
        namespace["write_text"]("specs/brief.md", "x")
    assert callable(namespace["read_json"])  # reads stay available
