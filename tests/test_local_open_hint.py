# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The Local stdio server names ``sdpm open <deck>`` when it creates or builds a deck.

Only with the Web UI installed (full profile, a built web-ui) and only for a client that did not
declare MCP Apps in initialize (``capabilities.extensions["io.modelcontextprotocol/ui"]``). The
field is a sentence for the user, added by a wrapper in servers/local/server.py; the tools'
schemas stay the contract's, server_acp.py (the Web UI's own agent) binds the contract functions
unwrapped, and no role document mentions the field (the result carries the hint alone).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, types
from mcp.shared.memory import create_client_server_memory_streams

from sdpm import tools
from sdpm.tools.apps import UI_EXTENSION

_ROOT = Path(__file__).resolve().parents[1]
_LOCAL = _ROOT / "servers" / "local"
_WORKFLOWS = _ROOT / "sdpm" / "references" / "workflows"
_NOTE = "To open this deck in the browser Web UI, run `sdpm open {}` in a terminal."
_APPS = {UI_EXTENSION: {"mimeTypes": ["text/html;profile=mcp-app"]}}


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def server():
    for p in (str(_LOCAL), str(_ROOT / "sdpm")):
        sys.path.insert(0, p)
    try:
        yield _load(_LOCAL / "server.py", "sdpm_local_server_open_hint_test")
    finally:
        for p in (str(_LOCAL), str(_ROOT / "sdpm")):
            sys.path.remove(p)


class _Client(ClientSession):
    """A client whose initialize declares ``extensions`` (what an MCP Apps host sends)."""

    def __init__(self, *args, extensions: dict | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._extensions = extensions

    async def initialize(self) -> types.InitializeResult:
        extra = {"extensions": self._extensions} if self._extensions is not None else {}
        result = await self.send_request(
            types.ClientRequest(types.InitializeRequest(params=types.InitializeRequestParams(
                protocolVersion=types.LATEST_PROTOCOL_VERSION,
                capabilities=types.ClientCapabilities(**extra),
                clientInfo=types.Implementation(name="open-hint-test", version="1"),
            ))),
            types.InitializeResult,
        )
        await self.send_notification(types.ClientNotification(types.InitializedNotification()))
        return result


def _session(server, extensions, calls):
    """Run ``calls(session)`` against the server in memory; return what it returns."""

    async def run():
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            low = server.mcp._mcp_server
            async with anyio.create_task_group() as tg:
                tg.start_soon(lambda: low.run(*server_streams, low.create_initialization_options()))
                async with _Client(*client_streams, extensions=extensions) as session:
                    await session.initialize()
                    out = await calls(session)
                tg.cancel_scope.cancel()
        return out

    return asyncio.run(run())


def _result(call: types.CallToolResult) -> dict:
    assert not call.isError, call.content
    return call.structuredContent if call.structuredContent is not None else json.loads(call.content[0].text)


@pytest.fixture
def local(server, tmp_path, monkeypatch):
    """A deck root, and a checkout next to state.json with the Web UI built (full profile)."""
    root = tmp_path / "decks"
    root.mkdir()
    monkeypatch.setenv("SDPM_DECK_ROOT", str(root))
    checkout = tmp_path / "home" / "checkout"
    (checkout / "web-ui" / "build").mkdir(parents=True)
    (tmp_path / "home" / "state.json").write_text(json.dumps({"profile": "full"}))
    monkeypatch.setattr(server, "_CHECKOUT", checkout)
    # generate_pptx reloads the asset catalogs under this test's config dir; restore the cache.
    from sdpm.knowledge import assets

    monkeypatch.setattr(assets, "_manifest_cache", assets._manifest_cache)
    return root


def _create_and_build(server, extensions):
    """Create a pptx deck on the bundled template and build it, and create an HTML deck and ask
    for its PPTX (declined); return the three results."""

    async def calls(session):
        made = _result(await session.call_tool("init_deck_workspace", {"name": "hint"}))
        deck_json = Path(made["output_dir"]) / "deck.json"
        deck_json.write_text(json.dumps({**json.loads(deck_json.read_text()), "template": "blank-dark"}))
        built = _result(await session.call_tool("generate_pptx", {"deck_id": made["output_dir"]}))
        html = _result(await session.call_tool("init_deck_workspace", {"name": "page", "output_format": "html"}))
        declined = _result(await session.call_tool("generate_pptx", {"deck_id": html["output_dir"]}))
        return made, built, declined

    return _session(server, extensions, calls)


def test_a_client_without_mcp_apps_gets_the_command(server, local):
    made, built, declined = _create_and_build(server, None)
    deck = Path(made["output_dir"])
    assert deck.parent == local
    assert made[server.OPEN_HINT_FIELD] == _NOTE.format(deck.name)
    assert built[server.OPEN_HINT_FIELD] == _NOTE.format(deck.name)
    # generate_pptx declining an HTML deck built nothing, so it names no command.
    assert declined["output_format"] == "html" and server.OPEN_HINT_FIELD not in declined
    # Another extension is not MCP Apps.
    made, _, _ = _create_and_build(server, {"io.example/other": {}})
    assert server.OPEN_HINT_FIELD in made


def test_a_client_with_mcp_apps_gets_no_command(server, local):
    made, built, _ = _create_and_build(server, _APPS)
    assert server.OPEN_HINT_FIELD not in made and server.OPEN_HINT_FIELD not in built
    made, _, _ = _create_and_build(server, {UI_EXTENSION: {}})
    assert server.OPEN_HINT_FIELD not in made


def test_no_command_without_the_web_ui(server, local, tmp_path):
    (tmp_path / "home" / "state.json").write_text(json.dumps({"profile": "mcp"}))
    made, built, _ = _create_and_build(server, None)
    assert server.OPEN_HINT_FIELD not in made and server.OPEN_HINT_FIELD not in built
    (tmp_path / "home" / "state.json").write_text(json.dumps({"profile": "full"}))
    (server._CHECKOUT / "web-ui" / "build").rmdir()
    made, _, _ = _create_and_build(server, None)
    assert server.OPEN_HINT_FIELD not in made


def test_the_command_follows_the_root_sdpm_open_searches(server, local, tmp_path, monkeypatch):
    # The engine's root and sdpm open's can differ (WSL with an unreadable config.json); the
    # hint names a deck only when it sits where sdpm open looks.
    deck = local / "my-deck"
    deck.mkdir()
    (deck / "deck.json").write_text("{}")
    wrapped = server._with_open_hint(lambda: {"output_dir": str(deck)})
    assert wrapped()[server.OPEN_HINT_FIELD] == _NOTE.format("my-deck")
    monkeypatch.setattr(server.sdpm_command, "deck_root", lambda: tmp_path / "elsewhere")
    assert server.OPEN_HINT_FIELD not in wrapped()


def test_no_command_for_a_deck_outside_the_root_or_a_failed_build(server, local, tmp_path):
    outside = tmp_path / "outside"
    from sdpm.api import init

    init(name="x", output_dir=str(outside))  # a pptx deck with no template: its build fails

    async def calls(session):
        failed = await session.call_tool("generate_pptx", {"deck_id": str(outside)})
        return failed

    failed = _session(server, None, calls)
    assert failed.isError
    assert server.OPEN_HINT_FIELD not in json.dumps([c.model_dump() for c in failed.content])

    wrapped = server._with_open_hint(lambda deck_id: {"output_dir": deck_id})
    assert server.OPEN_HINT_FIELD not in wrapped(deck_id=str(outside))
    assert server._with_open_hint(lambda: {"error": "x", "output_dir": str(local)})() == {"error": "x", "output_dir": str(local)}


def test_the_wrapped_tools_keep_the_contract_schema(server):
    from mcp.server.fastmcp import FastMCP

    listed = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert len(listed) == 20
    for fn in (tools.init_deck_workspace, tools.generate_pptx):
        reference = FastMCP("reference")
        reference.tool()(fn)
        expected = asyncio.run(reference.list_tools())[0]
        assert listed[fn.__name__].model_dump() == expected.model_dump()


def test_the_web_uis_own_server_binds_the_contract_unwrapped():
    text = (_LOCAL / "server_acp.py").read_text(encoding="utf-8")
    assert "_with_open_hint" not in text and "OPEN_HINT_FIELD" not in text


def test_no_role_document_mentions_the_hint(server):
    for doc in _WORKFLOWS.glob("*.md"):
        text = doc.read_text(encoding="utf-8")
        assert server.OPEN_HINT_FIELD not in text and "sdpm open" not in text, doc.name
