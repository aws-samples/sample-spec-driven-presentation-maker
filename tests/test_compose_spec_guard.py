# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for compose_slides specification validation guard."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
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
                    {"slugs": ["intro"], "instruction": "Scaffold pass."},
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
