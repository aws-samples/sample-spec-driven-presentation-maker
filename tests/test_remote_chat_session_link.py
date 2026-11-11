# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The remote server links a new deck to the chat that creates it (chatSessionId).

The browser's PATCH used to be the only writer; a closed tab left the deck without
its chat history. init_deck_workspace now stores the session itself, taken from the
Mcp-Session-Id header when that id belongs to the caller.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shared.session_owner import owner_prefix
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


def _meta(storage: MagicMock) -> dict:
    return storage.put_deck.call_args.kwargs["meta"]


def test_create_deck_stores_chat_session_id():
    storage = MagicMock()
    create_deck(name="n", user_id=SUB, storage=storage, chat_session_id=OWN)
    assert _meta(storage)["chatSessionId"] == OWN


@pytest.mark.parametrize("value", [None, ""])
def test_create_deck_without_session_has_no_chat_session_id(value):
    storage = MagicMock()
    create_deck(name="n", user_id=SUB, storage=storage, chat_session_id=value)
    assert "chatSessionId" not in _meta(storage)


def test_init_passes_chat_session_id_to_the_deck_record():
    storage = MagicMock()
    init_mod.init_deck_workspace(name="n", user_id=SUB, storage=storage, chat_session_id=OWN)
    assert _meta(storage)["chatSessionId"] == OWN


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


@pytest.mark.parametrize("header, expected", [
    (OWN, OWN),
    (f"{OWN}-g2", OWN),  # a composer group's id maps back to the chat
    (FOREIGN, None),     # another user's prefix is never written
    (UUID, None),        # un-prefixed ids are left to the browser's PATCH
])
def test_tool_links_only_the_callers_own_session(tool, header, expected):
    assert tool({"mcp-session-id": header})["chat_session_id"] == expected


def test_tool_without_session_header_writes_no_link(tool):
    assert tool({})["chat_session_id"] is None
