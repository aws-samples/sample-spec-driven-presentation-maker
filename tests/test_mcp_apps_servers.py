# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP Apps on both servers, through a real MCP client session (in memory).

The style gallery hangs on ``list_styles`` (``_meta.ui.resourceUri``); its view is a ``ui://``
resource and reads previews through the app-only ``app_action``. A client that does not declare
MCP Apps (``io.modelcontextprotocol/ui``, in initialize or in the request's ``_meta``) never sees
``app_action`` in ``tools/list`` and gets today's ``list_styles`` result unchanged. The remote
server is stateless HTTP and keeps no initialize params, so there only the per-request
declaration lists ``app_action``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import anyio
import pytest
from mcp import ClientSession, types
from mcp.shared.memory import create_client_server_memory_streams

from compose_fixture import BULLET, SLUGS, compose_files

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
    """Run ``calls(session)`` against the server in memory; return what it returns.

    A server with ``stateless_http`` (the remote) runs as it does in production: every HTTP
    request gets a fresh stateless session, so ``initialize`` goes to one session and
    ``calls`` run in another that never saw the client's initialize params.
    """
    low = server.mcp._mcp_server
    stateless = server.mcp.settings.stateless_http

    async def connect(work):
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as tg:
                tg.start_soon(lambda: low.run(*server_streams, low.create_initialization_options(), stateless=stateless))
                async with _Client(*client_streams, extensions=extensions) as session:
                    out = await work(session)
                tg.cancel_scope.cancel()
        return out

    async def run():
        if not stateless:
            async def both(session):
                await session.initialize()
                return await calls(session)

            return await connect(both)
        initialize_result = await connect(lambda session: session.initialize())

        async def fresh(session):
            session.initialize_result = initialize_result
            return await calls(session)

        return await connect(fresh)

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
    assert apps.APP_TOOL not in listed and apps.DECK_TOOL not in listed
    registered = {t.name for t in server.mcp._tool_manager.list_tools()}
    assert apps.UI_ONLY_TOOLS <= registered
    assert set(listed) == registered - apps.UI_ONLY_TOOLS
    for name, view in (("list_styles", apps.GALLERY), ("check_specs", apps.DECK_VIEWER)):
        uri = apps.view_uri(view)
        meta = listed[name].meta
        assert meta["ui"]["resourceUri"] == uri
        assert meta["ui/resourceUri"] == uri
    assert _listed(server, {"io.example/other": {}}).keys() == listed.keys()


def test_the_local_server_lists_twenty_tools(local) -> None:
    assert len(_listed(local)) == 20


@pytest.mark.parametrize(("which", "declaration"), [
    ("local", "initialize"), ("local", "per-request"), ("remote", "per-request"),
])
def test_a_client_with_mcp_apps_sees_the_app_tool(which, declaration, request) -> None:
    server = request.getfixturevalue(which)
    if declaration == "initialize":
        listed = _listed(server, _UI)
    else:
        listed = _listed(server, None, _PER_REQUEST)
    tool = listed[apps.APP_TOOL]
    assert tool.meta == {"ui": {"visibility": ["app"]}}
    props = tool.inputSchema["properties"]
    assert all(p.get("description") for p in props.values()), props
    actions = ["style_previews", "deck", "slide_preview", "submit_review", "outline_edit"]
    # Only the local server opens a deck's file or folder for the user.
    assert props["action"]["enum"] == actions + (["open"] if which == "local" else [])
    assert ("open:" in tool.description) == (which == "local")
    assert props["target"]["enum"] == ["file", "folder"]
    assert tool.inputSchema["required"] == ["action"]
    # Hosts check a view's arguments against inputSchema before passing the call on, and
    # Kiro Crew's gateway refuses a schema with anyOf/oneOf/allOf ("failing closed").
    assert not {"anyOf", "oneOf", "allOf"} & _keywords(tool.inputSchema)
    assert len(tool.description) <= 560

    show = listed[apps.DECK_TOOL]
    uri = apps.view_uri(apps.DECK_VIEWER)
    assert show.meta == {"ui": {"resourceUri": uri}, "ui/resourceUri": uri}
    assert len(show.description) <= 560
    assert show.inputSchema["required"] == ["deck_id"]
    assert show.inputSchema["properties"]["deck_id"]["description"]


def _keywords(schema) -> set[str]:
    if isinstance(schema, dict):
        return set(schema) | {k for v in schema.values() for k in _keywords(v)}
    if isinstance(schema, list):
        return {k for v in schema for k in _keywords(v)}
    return set()


def test_the_stateless_remote_lists_the_app_tool_only_per_request(remote) -> None:
    assert remote.mcp.settings.stateless_http
    for name in apps.UI_ONLY_TOOLS:
        assert name not in _listed(remote, _UI)
        assert name in _listed(remote, None, _PER_REQUEST)
        assert name in _listed(remote, _UI, _PER_REQUEST)


# --- initialize and resources ------------------------------------------------------------


def test_initialize_declares_the_extension(server) -> None:
    async def calls(session):
        return session.initialize_result

    caps = _session(server, None, calls).capabilities
    extensions = getattr(caps, "extensions", None) or (caps.model_extra or {}).get("extensions")
    assert extensions[apps.UI_EXTENSION]["mimeTypes"] == [apps.APP_MIME]


@pytest.mark.parametrize("view", [apps.GALLERY, apps.DECK_VIEWER])
def test_the_view_resources(server, view) -> None:
    uri = apps.view_uri(view)

    async def calls(session):
        return await session.list_resources(), await session.read_resource(uri)

    listed, read = _session(server, None, calls)
    entry = next(r for r in listed.resources if str(r.uri) == uri)
    assert entry.mimeType == apps.APP_MIME
    content = read.contents[0]
    assert content.mimeType == apps.APP_MIME
    assert content.meta == {"ui": {"prefersBorder": True}}
    assert content.text == apps.view_html(view)


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
    {"action": "style_previews"},
    {"names": ["report"]},
])
def test_app_action_refuses_bad_arguments(server, arguments, request) -> None:
    if server is request.getfixturevalue("remote"):
        request.getfixturevalue("remote_user")
    assert _call(server, apps.APP_TOOL, arguments).isError


def test_an_odd_name_goes_to_missing_and_the_batch_still_renders(server, request) -> None:
    if server is request.getfixturevalue("remote"):
        request.getfixturevalue("remote_user")
    got = _previews(_call(server, apps.APP_TOOL, {"action": "style_previews", "names": ["../x", "report", "社内標準"]}))
    assert set(got["previews"]) == {"report"}
    assert got["missing"] == ["../x", "社内標準"]


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


# --- the deck viewer ---------------------------------------------------------------------

_SAMPLE = _ROOT / "tests" / "fixtures" / "style-sample-deck"
_DECK_JSON = {
    "template": "blank-dark",
    "fonts": {"fullwidth": "Noto Sans JP", "halfwidth": "Amazon Ember"},
    "defaultTextColor": "#A1B2C3",
    "slideSize": {"width": 1920, "height": 1080, "ptPerPx": 0.5},
}


def _png(size=(1280, 720), fmt="PNG") -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, format=fmt)
    return out.getvalue()


def _is_jpeg(data: str) -> bool:
    import base64

    return base64.b64decode(data)[:3] == b"\xff\xd8\xff"


def _slugs() -> list[str]:
    from sdpm.engine.schema import parse_outline_text

    return parse_outline_text((_SAMPLE / "outline.md").read_text(encoding="utf-8"))


@pytest.fixture
def local_deck(tmp_path: Path) -> Path:
    """A local deck: the sample specs, slides for all but the last slug, previews for two."""
    deck = tmp_path / "deck"
    (deck / "specs").mkdir(parents=True)
    for name in ("brief.md", "outline.md"):
        (deck / "specs" / name).write_bytes((_SAMPLE / name).read_bytes())
    (deck / "deck.json").write_text(json.dumps(_DECK_JSON), encoding="utf-8")
    slugs = _slugs()
    (deck / "slides").mkdir()
    for slug in slugs[:-1]:
        (deck / "slides" / f"{slug}.json").write_text("{}", encoding="utf-8")
    (deck / "preview").mkdir()
    for slug in slugs[:2]:
        (deck / "preview" / f"{slug}.png").write_bytes(_png())
    (deck / "reviews").mkdir()
    (deck / "reviews" / "old.json").write_text("{}", encoding="utf-8")
    return deck


def _act(server, arguments, extensions=None) -> types.CallToolResult:
    return _call(server, apps.APP_TOOL, arguments, extensions)


def _ok(call: types.CallToolResult) -> dict:
    assert not call.isError, call.content
    return call.structuredContent


@pytest.mark.parametrize("extensions", [None, _UI])
def test_local_show_deck_and_the_deck_payload(local, local_deck, extensions) -> None:
    deck_id = str(local_deck)
    shown = _call(local, apps.DECK_TOOL, {"deck_id": deck_id}, extensions)
    assert _ok(shown) == {"deck_id": deck_id, "tab": "slides"}
    assert deck_id in shown.content[0].text

    got = _ok(_act(local, {"action": "deck", "deck_id": deck_id}, extensions))
    slugs = _slugs()
    assert [s["slug"] for s in got["slides"]] == slugs
    assert [s["built"] for s in got["slides"]] == [True] * (len(slugs) - 1) + [False]
    assert [s["preview"] is not None for s in got["slides"]] == [True, True] + [False] * (len(slugs) - 2)
    assert got["check"] == tools.check_specs(deck_id)
    assert got["check"]["ok"] is True
    assert got["brief"] == (_SAMPLE / "brief.md").read_text(encoding="utf-8")
    assert len([e for e in got["outline"] if e["type"] == "section"]) == 4


def test_local_slide_preview_is_a_jpeg(local, local_deck) -> None:
    slug = _slugs()[0]
    got = _ok(_act(local, {"action": "slide_preview", "deck_id": str(local_deck), "slug": slug}))
    assert got["available"] and got["kind"] == "image" and got["mimeType"] == "image/jpeg" and _is_jpeg(got["data"])
    assert _ok(_act(local, {"action": "slide_preview", "deck_id": str(local_deck), "slug": _slugs()[3]})) == {
        "slug": _slugs()[3], "available": False,
    }


def _compose_into(folder: Path, slugs: list[str]) -> None:
    """The fixture's compose payloads under the deck's slugs, plus an older payload that loses."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in compose_files().items():
        stem = name.rsplit("_", 1)[0]
        target = stem if stem == "defs" else slugs[SLUGS.index(stem)]
        (folder / f"{target}_100.json").write_bytes(data)
    (folder / f"{slugs[0]}_99.json").write_text("stale", encoding="utf-8")


def _assert_svg(got: dict, fixture_slug: str, stamp: str) -> None:
    compose = json.loads(compose_files()[f"{fixture_slug}_100.json"])
    assert got["available"] and got["kind"] == "svg" and got["stamp"] == stamp
    assert got["components"] == [c["svg"] for c in compose["components"]]
    assert got["bgSvg"] == compose["bgSvg"] and "data" not in got


def test_local_slide_preview_is_the_compose_svg(local, local_deck) -> None:
    slugs = _slugs()
    _compose_into(local_deck / "compose", slugs)
    deck_id = str(local_deck)
    listed = _ok(_act(local, {"action": "deck", "deck_id": deck_id}))["slides"]
    assert [s["preview"] for s in listed[:3]] == [f"{slugs[0]}_100.json", f"{slugs[1]}_100.json", None]
    first = _ok(_act(local, {"action": "slide_preview", "deck_id": deck_id, "slug": slugs[0]}))
    _assert_svg(first, "cover", f"{slugs[0]}_100.json")
    second = _ok(_act(local, {"action": "slide_preview", "deck_id": deck_id, "slug": slugs[1]}))
    _assert_svg(second, "points", f"{slugs[1]}_100.json")
    assert f'id="{BULLET}"' in second["defs"]
    # No compose for this slug, and no image either.
    assert _ok(_act(local, {"action": "slide_preview", "deck_id": deck_id, "slug": slugs[2]}))["available"] is False


def test_local_compose_reads_stay_in_the_compose_folder(local, local_deck) -> None:
    access = local.deck_access.ACCESS
    (local_deck / "compose").mkdir()
    (local_deck / "compose" / "x_1.json").write_text("{}", encoding="utf-8")
    assert access.read_compose(str(local_deck), "x_1.json") == b"{}"
    for name in ("../deck_1.json", "..\\deck_1.json", "sub/x_1.json", "deck.json", "x_1.json.bak"):
        assert access.read_compose(str(local_deck), name) is None, name
    assert access.compose(str(local_deck / "nowhere")) == {}


def test_local_submit_review_writes_the_review_file(local, local_deck) -> None:
    from shared.review import REVIEW_ID_RE

    slug = _slugs()[1]
    review = {"note": "tighter", "comments": [{"name": "A", "slide": slug, "rect": [10, 20, 300, 200], "text": "bigger"}]}
    got = _ok(_act(local, {"action": "submit_review", "deck_id": str(local_deck), "review": review}))
    assert REVIEW_ID_RE.fullmatch(got["id"])
    assert got["message"].startswith(f"[review:{got['id']}]")
    files = sorted(p.name for p in (local_deck / "reviews").iterdir())
    assert files == [f"{got['id']}.json"]
    saved = json.loads((local_deck / "reviews" / files[0]).read_text(encoding="utf-8"))
    assert saved["comments"] == review["comments"] and saved["note"] == "tighter"


def test_local_submit_review_refuses_an_unbuilt_slide(local, local_deck) -> None:
    review = {"note": None, "comments": [{"name": "A", "slide": _slugs()[-1], "rect": [0, 0, 10, 10], "text": "x"}]}
    assert _act(local, {"action": "submit_review", "deck_id": str(local_deck), "review": review}).isError
    assert (local_deck / "reviews" / "old.json").exists()


def test_local_outline_edit_returns_a_diff_and_writes_nothing(local, local_deck) -> None:
    path = local_deck / "specs" / "outline.md"
    before = path.read_bytes()
    base = before.decode("utf-8")
    slug = _slugs()[2]
    line = next(x for x in base.splitlines() if x.startswith(f"- [{slug}]"))
    text = base.replace(line, f"- [{slug}] A sharper message")
    got = _ok(_act(local, {"action": "outline_edit", "deck_id": str(local_deck), "base": base, "text": text}))
    assert "```diff" in got["message"]
    assert f"\n-{line}\n+- [{slug}] A sharper message\n" in got["message"]
    assert path.read_bytes() == before


@pytest.mark.parametrize("arguments", [
    {"action": "deck", "deck_id": "/nowhere/at/all"},
    {"action": "deck"},
    {"action": "slide_preview", "deck_id": "DECK", "slug": "../x"},
    {"action": "submit_review", "deck_id": "DECK", "review": {"comments": []}},
    {"action": "outline_edit", "deck_id": "DECK", "base": "a", "text": "a"},
])
def test_local_deck_actions_refuse_bad_arguments(local, local_deck, arguments) -> None:
    arguments = {k: (str(local_deck) if v == "DECK" else v) for k, v in arguments.items()}
    assert _act(local, arguments).isError


def test_local_show_deck_needs_a_deck(local, tmp_path) -> None:
    assert _call(local, apps.DECK_TOOL, {"deck_id": str(tmp_path / "none")}).isError


def test_local_check_specs_result_is_unchanged(local, local_deck) -> None:
    call = _call(local, "check_specs", {"deck_id": str(local_deck)})
    assert _ok(call) == tools.check_specs(str(local_deck))


# --- open: the deck's built file or its folder (local only) ------------------------------


@pytest.fixture
def launched(local, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """The OS opener stubbed out: what it would have started (argv), and nothing starts."""
    started: list[list[str]] = []

    def popen(argv, **kwargs):
        assert isinstance(argv, list) and not kwargs.get("shell")
        assert kwargs["stdout"] is fake.DEVNULL  # the MCP stream stays ours
        started.append(argv)

    fake = SimpleNamespace(Popen=popen, DEVNULL=object())
    access = local.deck_access
    monkeypatch.setattr(access, "subprocess", fake)
    monkeypatch.setattr(access, "shutil", SimpleNamespace(which=lambda name: f"/usr/bin/{name}"))
    monkeypatch.setattr(access.os, "startfile", lambda path: started.append([path]), raising=False)
    return started


@pytest.fixture
def root_deck(local_deck: Path) -> Path:
    """The local deck moved into the (isolated) deck root, where ``open`` serves it."""
    target = Path(os.environ["SDPM_DECK_ROOT"]) / "20261110-deck"
    shutil.move(str(local_deck), target)
    return target


def _real(path: Path) -> str:
    return os.path.realpath(path)


@pytest.mark.parametrize(("fmt", "built"), [("pptx", "output.pptx"), ("html", "output.html")])
def test_local_open_file_opens_the_built_output(local, root_deck, launched, fmt, built) -> None:
    if fmt == "html":
        (root_deck / "deck.json").write_text(json.dumps({**_DECK_JSON, "outputFormat": "html"}), encoding="utf-8")
        (root_deck / "output.pptx").write_bytes(b"stale")  # not the HTML deck's output
    (root_deck / built).write_bytes(b"built")
    deck_id = str(root_deck)
    assert _ok(_act(local, {"action": "deck", "deck_id": deck_id}))["open"] == {"file": True, "folder": True}
    got = _ok(_act(local, {"action": "open", "deck_id": deck_id, "target": "file"}))
    assert got == {"target": "file", "name": built}
    assert [argv[-1] for argv in launched] == [_real(root_deck / built)]


def test_local_open_folder_opens_the_deck_folder(local, root_deck, launched) -> None:
    got = _ok(_act(local, {"action": "open", "deck_id": str(root_deck), "target": "folder"}))
    assert got == {"target": "folder", "name": root_deck.name}
    assert [argv[-1] for argv in launched] == [_real(root_deck)]


def test_local_open_file_needs_a_built_output(local, root_deck, launched) -> None:
    deck_id = str(root_deck)
    assert _ok(_act(local, {"action": "deck", "deck_id": deck_id}))["open"] == {"file": False, "folder": True}
    call = _act(local, {"action": "open", "deck_id": deck_id, "target": "file"})
    assert call.isError and "no built file yet" in call.content[0].text
    assert launched == []


@pytest.fixture
def outside_deck(root_deck: Path, tmp_path: Path) -> Path:
    """A built deck that is not in the deck root."""
    outside = tmp_path / "outside"
    (outside / "specs").mkdir(parents=True)
    for name in ("deck.json", "specs/brief.md", "specs/outline.md"):
        (outside / name).write_bytes((root_deck / name).read_bytes())
    (outside / "output.pptx").write_bytes(b"built")
    return outside


def test_local_open_refuses_a_deck_outside_the_deck_root(local, root_deck, outside_deck, launched) -> None:
    root = root_deck.parent
    assert _ok(_act(local, {"action": "deck", "deck_id": str(outside_deck)}))["open"] == {"file": False, "folder": False}
    climbed = root / ".." / outside_deck.parent.name / outside_deck.name  # a path out of the root
    assert climbed.resolve() == outside_deck.resolve()
    for deck_id in (str(outside_deck), str(climbed), str(root), str(root / "missing")):
        for target in ("file", "folder"):
            assert _act(local, {"action": "open", "deck_id": deck_id, "target": target}).isError, (deck_id, target)
    assert launched == []


def test_local_open_refuses_links_out_of_the_root(local, root_deck, outside_deck, launched) -> None:
    link = root_deck.parent / "linked-deck"
    try:
        link.symlink_to(outside_deck, target_is_directory=True)
        (root_deck / "output.pptx").symlink_to(outside_deck / "output.pptx")
    except OSError:
        pytest.skip("this user cannot create symlinks")
    for target in ("file", "folder"):
        assert _act(local, {"action": "open", "deck_id": str(link), "target": target}).isError, target
    assert _ok(_act(local, {"action": "deck", "deck_id": str(root_deck)}))["open"] == {"file": False, "folder": True}
    assert _act(local, {"action": "open", "deck_id": str(root_deck), "target": "file"}).isError
    assert launched == []


def test_local_open_refuses_a_bad_target(local, root_deck, launched) -> None:
    for target in ("deck.json", "../x", ""):
        assert _act(local, {"action": "open", "deck_id": str(root_deck), "target": target}).isError
    assert launched == []


def test_local_open_without_xdg_open_says_so(local, root_deck, launched, monkeypatch) -> None:
    if os.name == "nt":
        pytest.skip("Windows opens files with os.startfile")
    monkeypatch.setattr(local.deck_access, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(local.deck_access, "shutil", SimpleNamespace(which=lambda name: None))
    call = _act(local, {"action": "open", "deck_id": str(root_deck), "target": "folder"})
    assert call.isError and "xdg-open" in call.content[0].text
    assert launched == []


# --- the deck viewer on the remote server ------------------------------------------------


@pytest.fixture
def remote_deck(remote, monkeypatch: pytest.MonkeyPatch):
    """The remote server over a fake S3 deck ``d1``; the permission checks are recorded."""
    slugs = _slugs()
    objects: dict[str, bytes] = {
        "decks/d1/deck.json": json.dumps(_DECK_JSON).encode(),
        "decks/d1/specs/brief.md": (_SAMPLE / "brief.md").read_bytes(),
        "decks/d1/specs/outline.md": (_SAMPLE / "outline.md").read_bytes(),
        f"previews/d1/{slugs[0]}_100.webp": _png((1920, 1080), "WEBP"),
        "decks/d1/reviews/x.json": b"{}",
    }
    for slug in slugs[:-1]:
        objects[f"decks/d1/slides/{slug}.json"] = b"{}"

    class Storage:
        pptx_bucket = "pptx-test"
        table = object()

        def __init__(self) -> None:
            self.objects = objects
            self.deleted: list[str] = []
            self.written: list[str] = []

        def download_file_from_pptx_bucket(self, key: str) -> bytes:
            return self.objects[key]

        def get_deck_json(self, deck_id: str) -> dict:
            return json.loads(self.objects[f"decks/{deck_id}/deck.json"])

        def list_files(self, prefix: str, bucket: str = "") -> list[str]:
            assert bucket == self.pptx_bucket
            return sorted(k for k in self.objects if k.startswith(prefix))

        def delete_files(self, prefix: str, bucket: str = "") -> int:
            self.deleted.append(prefix)
            gone = [k for k in self.objects if k.startswith(prefix)]
            for k in gone:
                del self.objects[k]
            return len(gone)

        def upload_file_if_absent(self, key: str, data: bytes, content_type: str = "", **_: Any) -> bool:
            if key in self.objects:
                return False
            self.written.append(key)
            self.objects[key] = data
            return True

    storage = Storage()
    checks: list[tuple[str, str]] = []

    def check(deck_id: str, action: str = "read") -> None:
        checks.append((deck_id, action))
        if deck_id != "d1":
            raise ValueError("Access denied: not shared")

    monkeypatch.setattr(remote, "_storage", storage)
    monkeypatch.setattr(remote, "_check_deck_access", check)
    monkeypatch.setattr(remote, "_get_user_id", lambda: "u1")
    return storage, checks


@pytest.mark.parametrize("extensions", [None, _UI])
def test_remote_show_deck_and_the_deck_payload(remote, remote_deck, extensions) -> None:
    storage, checks = remote_deck
    assert _ok(_call(remote, apps.DECK_TOOL, {"deck_id": "d1"}, extensions)) == {"deck_id": "d1", "tab": "slides"}
    got = _ok(_act(remote, {"action": "deck", "deck_id": "d1"}, extensions))
    slugs = _slugs()
    assert [s["slug"] for s in got["slides"]] == slugs
    assert got["slides"][0]["preview"] == f"previews/d1/{slugs[0]}_100.webp"
    assert [s["built"] for s in got["slides"]][-2:] == [True, False]
    assert got["check"]["ok"] is True
    assert got["preview_environment"] is None
    assert checks == [("d1", "read"), ("d1", "read")]


def test_remote_slide_preview_is_a_jpeg_of_the_webp(remote, remote_deck) -> None:
    got = _ok(_act(remote, {"action": "slide_preview", "deck_id": "d1", "slug": _slugs()[0]}))
    assert got["available"] and got["kind"] == "image" and _is_jpeg(got["data"])


def test_remote_slide_preview_is_the_compose_svg(remote, remote_deck, tmp_path) -> None:
    storage, checks = remote_deck
    slugs = _slugs()
    _compose_into(tmp_path, slugs)
    for p in tmp_path.iterdir():
        storage.objects[f"decks/d1/compose/{p.name}"] = p.read_bytes()
    storage.objects["decks/d2/compose/x_1.json"] = b"{}"
    listed = _ok(_act(remote, {"action": "deck", "deck_id": "d1"}))["slides"]
    assert listed[1]["preview"] == f"decks/d1/compose/{slugs[1]}_100.json"
    got = _ok(_act(remote, {"action": "slide_preview", "deck_id": "d1", "slug": slugs[1]}))
    _assert_svg(got, "points", f"decks/d1/compose/{slugs[1]}_100.json")
    assert f'id="{BULLET}"' in got["defs"]
    assert checks == [("d1", "read"), ("d1", "read")]


def test_remote_compose_reads_stay_under_the_decks_prefix(remote, remote_deck) -> None:
    storage, _ = remote_deck
    storage.objects["decks/d2/compose/x_1.json"] = b"{}"
    storage.objects["decks/d1/compose/sub/x_1.json"] = b"{}"
    access = remote._deck_access.make(lambda: storage, lambda deck_id, action: None)
    assert access.read_compose("d1", "decks/d2/compose/x_1.json") is None
    assert access.read_compose("d1", "decks/d1/compose/sub/x_1.json") is None
    assert access.read_compose("d1", "decks/d1/compose/missing_1.json") is None
    assert access.compose("d1") == {}


def test_remote_submit_review(remote, remote_deck) -> None:
    from shared.review import build_review_message, validate_review_submission

    storage, checks = remote_deck
    slug = _slugs()[0]
    review = {"note": None, "comments": [{"name": "A", "slide": slug, "rect": [0, 0, 100, 100], "text": "red"}]}
    got = _ok(_act(remote, {"action": "submit_review", "deck_id": "d1", "review": review}))
    assert checks == [("d1", "edit_slide")]
    assert storage.deleted == ["decks/d1/reviews/"]
    assert storage.written == [f"decks/d1/reviews/{got['id']}.json"]
    assert "decks/d1/reviews/x.json" not in storage.objects
    normalized, _ = validate_review_submission(review, (1920, 1080), lambda s: True)
    assert got["message"] == build_review_message(got["id"], normalized)


@pytest.mark.parametrize("arguments", [
    {"action": "deck", "deck_id": "other"},
    {"action": "slide_preview", "deck_id": "other", "slug": "cover"},
    {"action": "outline_edit", "deck_id": "other", "base": "a", "text": "b"},
])
def test_remote_deck_actions_need_permission(remote, remote_deck, arguments) -> None:
    assert _act(remote, arguments).isError
    assert _call(remote, apps.DECK_TOOL, {"deck_id": "other"}).isError


def test_remote_check_specs_result_is_unchanged(remote, remote_deck) -> None:
    call = _call(remote, "check_specs", {"deck_id": "d1"})
    assert not call.isError
    assert json.loads(call.content[0].text) == json.loads(remote.check_specs("d1"))


def test_remote_offers_no_open(remote, remote_deck) -> None:
    """The viewer hides its open buttons (``open`` None) and the action is not in the schema."""
    _, checks = remote_deck
    assert _ok(_act(remote, {"action": "deck", "deck_id": "d1"}))["open"] is None
    for target in ("file", "folder"):
        assert _act(remote, {"action": "open", "deck_id": "d1", "target": target}).isError
    assert checks == [("d1", "read")]
