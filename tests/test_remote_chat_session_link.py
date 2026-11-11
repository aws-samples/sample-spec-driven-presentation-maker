# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A new deck keeps a link to the chat that created it, without the browser's PATCH.

The MCP server records only a fact of its own transport: the ``Mcp-Session-Id``
of the request that created the deck (``createdInMcpSession``). The API, which
knows how the agent and the Web UI name sessions, reads that as the deck's chat
session when the browser's ``chatSessionId`` never arrived.
"""

from __future__ import annotations

import importlib.util
import os
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shared.session_owner import owner_prefix
from test_api_reviews import _Event, index  # noqa: F401  (index is a fixture)
from tools import init as init_mod
from tools.deck import create_deck

_ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault("DECKS_TABLE", "test-table")
os.environ.setdefault("PPTX_BUCKET", "test-pptx")
os.environ.setdefault("RESOURCE_BUCKET", "test-resource")

_spec = importlib.util.spec_from_file_location("remote_server_chat_link_under_test", _ROOT / "servers" / "remote" / "server.py")
remote_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remote_server)

SUB = "user-1"
UUID = "0f8c6a4e-2b1d-4c3e-9a7f-5d6e7f8a9b0c"
OWN = f"{owner_prefix(SUB)}-{UUID}"
FOREIGN = f"{owner_prefix('user-2')}-{UUID}"


# --- MCP server: records the creating MCP session as sent -------------------


def _meta(storage: MagicMock) -> dict:
    return storage.put_deck.call_args.kwargs["meta"]


def test_create_deck_records_the_mcp_session():
    storage = MagicMock()
    create_deck(name="n", user_id=SUB, storage=storage, mcp_session_id=OWN)
    meta = _meta(storage)
    assert meta["createdInMcpSession"] == OWN
    assert "chatSessionId" not in meta  # the chat link is the client side's field


@pytest.mark.parametrize("value", [None, ""])
def test_create_deck_without_session_records_nothing(value):
    storage = MagicMock()
    create_deck(name="n", user_id=SUB, storage=storage, mcp_session_id=value)
    assert "createdInMcpSession" not in _meta(storage)


def test_init_passes_the_mcp_session_to_the_deck_record():
    storage = MagicMock()
    init_mod.init_deck_workspace(name="n", user_id=SUB, storage=storage, mcp_session_id=OWN)
    assert _meta(storage)["createdInMcpSession"] == OWN


@pytest.fixture()
def tool(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(remote_server, "_get_user_id", lambda: SUB)
    monkeypatch.setattr(remote_server.init_mod, "init_deck_workspace", lambda **kw: seen.update(kw) or {"deckId": "x"})

    def call(headers: dict) -> dict:
        token = remote_server._current_request_headers.set(headers)
        try:
            remote_server.init_deck_workspace(name="n")
        finally:
            remote_server._current_request_headers.reset(token)
        return seen

    return call


@pytest.mark.parametrize("header", [OWN, f"{OWN}-g2", UUID, "claude-ai-session"])
def test_tool_records_the_header_unchanged(tool, header):
    assert tool({"mcp-session-id": header})["mcp_session_id"] == header


@pytest.mark.parametrize("headers", [{}, {"mcp-session-id": ""}, {"mcp-session-id": "x" * 257}])
def test_tool_records_nothing_without_a_usable_header(tool, headers):
    assert tool(headers)["mcp_session_id"] is None


# --- API: reads the record as the deck's chat session -----------------------


@pytest.mark.parametrize("deck, expected", [
    ({"chatSessionId": "linked", "createdInMcpSession": OWN, "createdBy": SUB}, "linked"),
    ({"createdInMcpSession": OWN, "createdBy": SUB}, OWN),
    ({"createdInMcpSession": FOREIGN, "createdBy": SUB}, None),  # not the owner's id
    ({"createdInMcpSession": UUID, "createdBy": SUB}, None),     # another client's MCP session
    ({"createdInMcpSession": OWN}, None),
    ({}, None),
])
def test_api_chat_session_id(index, deck, expected):  # noqa: F811
    assert index._chat_session_id(deck) == expected


class _FakeTable:
    def __init__(self, items):
        self.items = items
        self.kwargs: dict = {}

    def query(self, **kwargs):
        self.kwargs = kwargs
        return {"Items": self.items}


class _FakeMemory:
    def __init__(self):
        self.calls: list[dict] = []

    def list_events(self, **params):
        self.calls.append(params)
        return {"events": []}


def _get_chat(index, monkeypatch, items, session_id):  # noqa: F811
    memory = _FakeMemory()
    monkeypatch.setenv("MEMORY_ID", "mem-1")
    monkeypatch.setattr(index, "table", _FakeTable(items))
    monkeypatch.setattr(index, "boto3", types.SimpleNamespace(client=lambda name: memory))
    index.app.current_event = _Event(SUB)
    return index.get_chat(session_id), memory


def test_get_chat_reads_history_of_a_deck_without_the_browser_link(index, monkeypatch):  # noqa: F811
    _, memory = _get_chat(index, monkeypatch, [{"createdInMcpSession": OWN, "createdBy": SUB}], OWN)
    assert [c["sessionId"] for c in memory.calls] == [OWN]


def test_get_chat_refuses_a_session_that_is_not_the_decks_chat(index, monkeypatch):  # noqa: F811
    result, memory = _get_chat(index, monkeypatch, [{"createdInMcpSession": UUID, "createdBy": SUB}], UUID)
    assert result == {"messages": []}
    assert memory.calls == []
