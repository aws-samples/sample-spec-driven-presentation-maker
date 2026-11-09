# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP Apps on both servers, through a real MCP client session (in memory).

The style gallery hangs on ``list_styles`` (``_meta.ui.resourceUri``); its view is a ``ui://``
resource and reads previews through the app-only ``app_action``. A client that does not declare
MCP Apps (``io.modelcontextprotocol/ui``, in initialize or in the request's ``_meta``) never sees
``app_action`` in ``tools/list`` and gets today's ``list_styles`` result unchanged.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import anyio
import pytest
from mcp import ClientSession, types
from mcp.shared.memory import create_client_server_memory_streams

from sdpm import tools
from sdpm.knowledge.reference import BUNDLED_STYLES_DIR
from sdpm.tools import apps

_ROOT = Path(__file__).resolve().parents[1]
_LOCAL = _ROOT / "servers" / "local"
_REMOTE = _ROOT / "servers" / "remote"
_UI = {apps.UI_EXTENSION: {"mimeTypes": [apps.APP_MIME]}}
_PER_REQUEST = types.PaginatedRequestParams(
    _meta={apps.CLIENT_CAPABILITIES_META: {"extensions": _UI}},
)


def _load(name: str, path: Path, extra_paths: list[Path]):
    added = [str(p) for p in extra_paths if str(p) not in sys.path]
    for p in reversed(added):
        sys.path.insert(0, p)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for p in added:
            sys.path.remove(p)


@pytest.fixture(scope="module")
def local():
    return _load("sdpm_local_server_apps_test", _LOCAL / "server.py", [_LOCAL, _ROOT / "sdpm"])


@pytest.fixture(scope="module")
def remote():
    pytest.importorskip("boto3")
    env = {
        "DECKS_TABLE": "decks-test", "PPTX_BUCKET": "pptx-test", "RESOURCE_BUCKET": "resource-test",
        "AWS_DEFAULT_REGION": "ap-northeast-1",
    }
    with patch.dict("os.environ", env), patch("boto3.client", lambda *a, **k: MagicMock()):
        return _load("sdpm_remote_server_apps_test", _REMOTE / "server.py", [_ROOT, _REMOTE, _ROOT / "sdpm"])


@pytest.fixture(params=["local", "remote"])
def server(request):
    return request.getfixturevalue(request.param)


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    monkeypatch.delenv("SDPM_STYLES_DIR", raising=False)
    return tmp_path


class _Client(ClientSession):
    """A client whose initialize declares ``extensions`` (what an MCP Apps host sends)."""

    def __init__(self, *args, extensions: dict | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._extensions = extensions
        self.initialize_result: types.InitializeResult | None = None

    async def initialize(self) -> types.InitializeResult:
        extra = {"extensions": self._extensions} if self._extensions is not None else {}
        self.initialize_result = await self.send_request(
            types.ClientRequest(types.InitializeRequest(params=types.InitializeRequestParams(
                protocolVersion=types.LATEST_PROTOCOL_VERSION,
                capabilities=types.ClientCapabilities(**extra),
                clientInfo=types.Implementation(name="apps-test", version="1"),
            ))),
            types.InitializeResult,
        )
        await self.send_notification(types.ClientNotification(types.InitializedNotification()))
        return self.initialize_result


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


def _listed(server, extensions=None, params=None) -> dict[str, types.Tool]:
    async def calls(session):
        return (await session.list_tools(params=params)).tools

    return {t.name: t for t in _session(server, extensions, calls)}


def _call(server, name, arguments, extensions=None) -> types.CallToolResult:
    async def calls(session):
        return await session.call_tool(name, arguments)

    return _session(server, extensions, calls)


# --- tools/list --------------------------------------------------------------------------


def test_a_client_without_mcp_apps_sees_no_app_tool(server) -> None:
    listed = _listed(server)
    assert apps.APP_TOOL not in listed
    registered = {t.name for t in server.mcp._tool_manager.list_tools()}
    assert set(listed) == registered - {apps.APP_TOOL}
    uri = apps.view_uri(apps.GALLERY)
    meta = listed["list_styles"].meta
    assert meta["ui"]["resourceUri"] == uri
    assert meta["ui/resourceUri"] == uri
    assert _listed(server, {"io.example/other": {}}).keys() == listed.keys()


def test_the_local_server_lists_twenty_tools(local) -> None:
    assert len(_listed(local)) == 20


@pytest.mark.parametrize("declaration", ["initialize", "per-request"])
def test_a_client_with_mcp_apps_sees_the_app_tool(server, declaration) -> None:
    if declaration == "initialize":
        listed = _listed(server, _UI)
    else:
        listed = _listed(server, None, _PER_REQUEST)
    tool = listed[apps.APP_TOOL]
    assert tool.meta == {"ui": {"visibility": ["app"]}}
    props = tool.inputSchema["properties"]
    assert all(p.get("description") for p in props.values()), props
    action = props["action"]
    assert action.get("enum", [action.get("const")]) == ["style_previews"]  # one value: pydantic writes const
    assert tool.inputSchema["required"] == ["action"]


# --- initialize and resources ------------------------------------------------------------


def test_initialize_declares_the_extension(server) -> None:
    async def calls(session):
        return session.initialize_result

    caps = _session(server, None, calls).capabilities
    extensions = getattr(caps, "extensions", None) or (caps.model_extra or {}).get("extensions")
    assert extensions[apps.UI_EXTENSION]["mimeTypes"] == [apps.APP_MIME]


def test_the_gallery_resource(server) -> None:
    uri = apps.view_uri(apps.GALLERY)

    async def calls(session):
        return await session.list_resources(), await session.read_resource(uri)

    listed, read = _session(server, None, calls)
    entry = next(r for r in listed.resources if str(r.uri) == uri)
    assert entry.mimeType == apps.APP_MIME
    content = read.contents[0]
    assert content.mimeType == apps.APP_MIME
    assert content.meta == {"ui": {"prefersBorder": True}}
    assert content.text == apps.view_html(apps.GALLERY)


# --- app_action --------------------------------------------------------------------------


@pytest.fixture
def remote_user(remote, monkeypatch: pytest.MonkeyPatch):
    """The remote server with a signed-in user and a fake S3 holding one user style."""

    class Storage:
        objects: dict[str, bytes] = {}
        _s3 = object()

        def download_file_from_pptx_bucket(self, key: str) -> bytes:
            return self.objects[key]

        def list_user_styles(self, user_id: str) -> list[dict]:
            return [{"name": "mine", "description": "mine — a user style", "source": "user"}]

        def get_style_pins(self, user_id: str) -> list[str]:
            return ["report"]

    storage = Storage()
    monkeypatch.setattr(remote, "_storage", storage)
    monkeypatch.setattr(remote, "_get_user_id", lambda: "u1")
    icons = []
    monkeypatch.setattr(remote.user_library, "load_catalog_icons", lambda s3, bucket, ids: icons.append((s3, bucket, set(ids))) or {})
    return storage, icons


def _previews(call: types.CallToolResult) -> dict:
    assert not call.isError, call.content
    assert call.content[0].text.endswith("style previews")
    return call.structuredContent


@pytest.mark.parametrize("extensions", [None, _UI])
def test_style_previews(server, extensions, request) -> None:
    if server is request.getfixturevalue("remote"):
        request.getfixturevalue("remote_user")
    call = _call(server, apps.APP_TOOL, {"action": "style_previews", "names": ["report", "bento"]}, extensions)
    got = _previews(call)
    assert got["missing"] == []
    for name in ("report", "bento"):
        html = (BUNDLED_STYLES_DIR / f"{name}.html").read_text(encoding="utf-8")
        assert len(got["previews"][name]["slides"]) == html.count('<div class="slide')
    assert call.content[0].text == "2 style previews"


@pytest.mark.parametrize("arguments", [
    {"action": "nope", "names": ["report"]},
    {"action": "style_previews", "names": ["report"] * 7},
    {"action": "style_previews", "names": ["../x"]},
    {"action": "style_previews"},
    {"names": ["report"]},
])
def test_app_action_refuses_bad_arguments(server, arguments, request) -> None:
    if server is request.getfixturevalue("remote"):
        request.getfixturevalue("remote_user")
    assert _call(server, apps.APP_TOOL, arguments).isError


def test_remote_previews_read_the_users_style_first(remote, remote_user) -> None:
    storage, icons = remote_user
    from shared import user_library

    mine = '<html><head><style>.mine{}</style></head><body><div class="slide">only one</div></body></html>'
    storage.objects = {user_library.user_style_key("u1", "report"): mine.encode()}
    got = _previews(_call(remote, apps.APP_TOOL, {"action": "style_previews", "names": ["report", "bento", "gone"]}))
    assert got["previews"]["report"]["slides"] == ['<div class="slide">only one']
    bento = (BUNDLED_STYLES_DIR / "bento.html").read_text(encoding="utf-8")
    assert len(got["previews"]["bento"]["slides"]) == bento.count('<div class="slide')
    assert got["missing"] == ["gone"]
    for s3, bucket, _ in icons:
        assert s3 is storage._s3 and bucket == remote._resource_bucket


def test_remote_previews_need_a_signed_in_user(remote) -> None:
    call = _call(remote, apps.APP_TOOL, {"action": "style_previews", "names": ["report"]})
    assert call.isError


# --- list_styles stays today's result ---------------------------------------------------


@pytest.mark.parametrize("include_all", [False, True])
def test_local_list_styles_is_the_contracts_result(local, include_all) -> None:
    call = _call(local, "list_styles", {"include_all": include_all})
    assert not call.isError
    expected = tools.list_styles(include_all=include_all)
    assert call.structuredContent == expected
    assert json.loads(call.content[0].text) == expected


def test_remote_list_styles_is_the_same_json_text(remote, remote_user) -> None:
    storage, _ = remote_user
    call = _call(remote, "list_styles", {})
    assert not call.isError
    from tools import reference

    expected = json.dumps(reference.list_styles(storage=storage, user_id="u1"), ensure_ascii=False)
    assert call.content[0].text == expected
