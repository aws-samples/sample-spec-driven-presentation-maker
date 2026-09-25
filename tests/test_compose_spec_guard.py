# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for compose_slides specification validation guard."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys

import pytest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock


def _stub_module(monkeypatch, name: str, **attributes) -> ModuleType:
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _load_composer(monkeypatch):
    def tool_decorator(**_kwargs):
        return lambda function: function

    strands = _stub_module(monkeypatch, "strands", Agent=object, tool=tool_decorator)
    strands.__path__ = []
    _stub_module(
        monkeypatch,
        "strands.hooks.events",
        AfterInvocationEvent=type("AfterInvocationEvent", (), {}),
        AfterToolCallEvent=type("AfterToolCallEvent", (), {}),
        BeforeToolCallEvent=type("BeforeToolCallEvent", (), {}),
    )
    _stub_module(monkeypatch, "strands.hooks").__path__ = []
    _stub_module(monkeypatch, "strands.types.tools", ToolContext=object)
    _stub_module(monkeypatch, "strands.types").__path__ = []
    _stub_module(monkeypatch, "composition", resolve_parts=lambda *_args, **_kwargs: ("", []))
    _stub_module(
        monkeypatch,
        "cost_logger",
        log_slides_composed=lambda **_kwargs: None,
        log_usage=lambda **_kwargs: None,
    )
    _stub_module(monkeypatch, "message_hooks", LiftToolResultImages=object)
    _stub_module(monkeypatch, "modes", MODES={})
    _stub_module(
        monkeypatch,
        "resilience",
        call_tool_with_retry=lambda client, **kwargs: client.call_tool_sync(**kwargs),
    )

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "composer_spec_guard_under_test",
        root / "agent" / "modes" / "composer.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_compose_slides_rejects_invalid_specs_before_dispatch(monkeypatch) -> None:
    composer = _load_composer(monkeypatch)
    client = MagicMock()
    client.call_tool_sync.return_value = {
        "status": "success",
        "content": [
            {
                "text": json.dumps(
                    {
                        "ok": False,
                        "errors": ["deck.json template is empty"],
                        "warnings": ["outline.md contains [TBD]"],
                        "slugs": ["intro", "detail"],
                    }
                )
            }
        ],
    }
    compose_slides = composer.make_compose_slides([client], model=object())
    tool_context = SimpleNamespace(tool_use={"toolUseId": "parent-1"})

    async def collect() -> list:
        return [
            item
            async for item in compose_slides(
                deck_id="deck-1",
                slide_groups=[
                    {"slugs": ["intro"], "instruction": "Layout pass."},
                    {"slugs": ["detail"], "instruction": "Compose content."},
                ],
                tool_context=tool_context,
            )
        ]

    outputs = asyncio.run(collect())

    assert len(outputs) == 1
    assert json.loads(outputs[0]) == {
        "status": "error",
        "errors": ["deck.json template is empty"],
        "warnings": ["outline.md contains [TBD]"],
        "instruction": (
            "Cannot compose: fix the listed spec problems, then call compose_slides again."
        ),
    }
    client.call_tool_sync.assert_called_once()
    call = client.call_tool_sync.call_args.kwargs
    assert call["name"] == "check_specs"
    assert call["arguments"] == {
        "deck_id": "deck-1",
        "assigned_slugs": ["intro", "detail"],
    }


class _ContractClient:
    """Dispatches call_tool_sync to the real sdpm.tools contract."""

    def call_tool_sync(self, tool_use_id: str, name: str, arguments: dict):
        del tool_use_id
        from sdpm import tools as contract

        result = getattr(contract, name)(**arguments)
        return {"status": "success", "content": [{"text": json.dumps(result, ensure_ascii=False)}]}


def _deck_with_specs(tmp_path: Path) -> str:
    from sdpm import tools as contract

    deck_dir = contract.init_deck_workspace(str(tmp_path / "deck"))["output_dir"]
    contract.apply_style(deck_dir, style="typographic", template="blank-dark")
    (Path(deck_dir) / "specs" / "brief.md").write_text("# Brief\n", encoding="utf-8")
    (Path(deck_dir) / "specs" / "outline.md").write_text(
        "# D\n\n## S\n- [a] A\n  - body: b\n  - visual: v\n  - evidence: e\n", encoding="utf-8",
    )
    return deck_dir


def test_composer_opening_replays_start_composing(monkeypatch, tmp_path: Path) -> None:
    """compose_slides seeds each composer's history with its own start_composing call."""
    composer = _load_composer(monkeypatch)
    deck_dir = _deck_with_specs(tmp_path)

    deck = composer._start_composing(_ContractClient(), deck_dir, ["a"])
    assert deck["specs_ok"] is True and deck["assigned_slugs"] == ["a"]

    replay = composer._replay_start_composing(deck_dir, ["a"], deck)
    assert [m["role"] for m in replay] == ["assistant", "user"]
    tool_use = replay[0]["content"][1]["toolUse"]
    assert tool_use["name"] == "start_composing"
    assert tool_use["input"] == {"deck_id": deck_dir, "assigned_slugs": ["a"]}
    result = replay[1]["content"][0]["toolResult"]
    assert result["toolUseId"] == tool_use["toolUseId"]
    assert json.loads(result["content"][0]["text"])["deck"]["outline"].startswith("# D")


def test_composer_start_rejects_broken_specs(monkeypatch, tmp_path: Path) -> None:
    composer = _load_composer(monkeypatch)
    from sdpm import tools as contract

    deck_dir = contract.init_deck_workspace(str(tmp_path / "deck"))["output_dir"]
    with pytest.raises(RuntimeError, match="specs rejected"):
        composer._start_composing(_ContractClient(), deck_dir, ["a"])


def test_composer_no_longer_prefetches_by_hand() -> None:
    src = (Path(__file__).resolve().parents[1] / "agent" / "modes" / "composer.py").read_text(encoding="utf-8")
    assert "_prefetch_deck_specs" not in src
    assert "read_workflows" not in src
    assert "analyze_template" not in src  # comes back inside start_composing's payload
