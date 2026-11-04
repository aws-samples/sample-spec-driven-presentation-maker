# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP write fence (servers/remote/storage/write_fence.py).

A stopped agent turn's in-flight calls kept writing on dev: run_python put 4 slides
1.7 s after a cancel, and generate_pptx's background previews landed 1.5 s after a
StopRuntimeSession. With the fence, a request that carries a generation at or below the
deck's fence writes nothing; a newer generation writes; a request without one behaves
as before. The deck record update is conditional on the fence, so a write that passed
the check cannot repoint the deck after the fence moved.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from mcp.shared.memory import create_connected_server_and_client_session

from storage import write_fence
from storage.aws import AwsStorage

_ROOT = Path(__file__).resolve().parents[1]
_SERVER = _ROOT / "servers" / "remote" / "server.py"

os.environ.setdefault("DECKS_TABLE", "test-table")
os.environ.setdefault("PPTX_BUCKET", "test-pptx")
os.environ.setdefault("RESOURCE_BUCKET", "test-resource")

_spec = importlib.util.spec_from_file_location("remote_server_write_fence_under_test", _SERVER)
remote_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remote_server)

USER = "u1"
DECK = "d1"
KEY = ("USER#u1", "DECK#d1")


class FakeTable:
    """The deck table: GetItem, and UpdateItem with the SET/REMOVE and condition forms
    AwsStorage.update_deck and write_fence.advance send."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict] = {}
        self.gets = 0
        self.before_update = None  # hook: runs right before an update is applied (races)

    def get_item(self, Key, **kwargs):
        self.gets += 1
        item = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": dict(item)} if item is not None else {}

    def update_item(self, Key, UpdateExpression, ConditionExpression=None, ExpressionAttributeNames=None,
                    ExpressionAttributeValues=None, ReturnValues=None):
        if self.before_update is not None:
            hook, self.before_update = self.before_update, None
            hook()
        names = ExpressionAttributeNames or {}
        values = ExpressionAttributeValues or {}
        k = (Key["PK"], Key["SK"])
        item = self.items.get(k)
        if ConditionExpression:
            fence = (item or {}).get(write_fence.FENCE_ATTR)
            ok = fence is None or fence < values[":wf_gen"]
            if ConditionExpression.startswith("attribute_exists(PK)"):
                ok = ok and item is not None
            if not ok:
                raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")
        item = self.items.setdefault(k, {"PK": k[0], "SK": k[1]})
        old = {}
        for clause in re.findall(r"(SET|REMOVE) (.*?)(?= REMOVE | SET |$)", UpdateExpression):
            verb, body = clause
            for part in body.split(","):
                part = part.strip()
                if verb == "SET":
                    name, value = (s.strip() for s in part.split("="))
                    name = names.get(name, name)
                    if name in item:
                        old[name] = item[name]
                    item[name] = values[value]
                else:
                    name = names.get(part, part)
                    if name in item:
                        old[name] = item.pop(name)
        return {"Attributes": old}


class FakeS3:
    class exceptions:  # noqa: N801 - mirrors the boto3 client attribute
        class NoSuchKey(Exception):
            pass

    def __init__(self) -> None:
        self.writes: list[tuple[str, str]] = []

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.writes.append(("put", Key))

    def delete_object(self, Bucket, Key):
        self.writes.append(("delete", Key))

    def delete_objects(self, Bucket, Delete):
        self.writes.extend(("delete", o["Key"]) for o in Delete["Objects"])


@pytest.fixture()
def store():
    table, s3 = FakeTable(), FakeS3()
    table.items[KEY] = {"PK": KEY[0], "SK": KEY[1], "name": "deck"}
    return AwsStorage(table=table, s3_client=s3, pptx_bucket="pptx", resource_bucket="res"), table, s3


def _fenced(generation: int):
    return write_fence.bind(write_fence.Fence(generation=generation, user_id=USER, deck_id=DECK))


def _write_everything(storage: AwsStorage) -> None:
    storage.upload_file(key=f"decks/{DECK}/slides/a.json", data=b"{}")
    storage.put_slide_json(DECK, "b", {})
    storage.put_deck_json(DECK, {})
    storage._s3.delete_object(Bucket="pptx", Key=f"previews/{DECK}/old.webp")  # the direct deletes
    storage.delete_object_keys([f"previews/{DECK}/x.webp"])


# --- The fence at the storage choke point ---


def test_without_a_generation_every_write_goes_through(store):
    storage, table, s3 = store
    table.items[KEY][write_fence.FENCE_ATTR] = 10**30  # even a fenced deck: not this request's business
    _write_everything(storage)
    storage.update_deck(DECK, USER, {"updatedAt": "t"})
    assert len(s3.writes) == 5
    assert table.items[KEY]["updatedAt"] == "t"
    assert table.gets == 0


def test_a_current_generation_writes(store):
    storage, table, s3 = store
    table.items[KEY][write_fence.FENCE_ATTR] = 100
    token = _fenced(101)
    try:
        _write_everything(storage)
        old = storage.update_deck(DECK, USER, {"pptxS3Key": "pptx/d1/new.pptx"})
    finally:
        write_fence.reset(token)
    assert len(s3.writes) == 5
    assert table.items[KEY]["pptxS3Key"] == "pptx/d1/new.pptx"
    assert old == {}


def test_a_deck_never_fenced_accepts_any_generation(store):
    storage, _, s3 = store
    token = _fenced(1)
    try:
        storage.upload_file(key=f"decks/{DECK}/x", data=b"")
    finally:
        write_fence.reset(token)
    assert s3.writes == [("put", f"decks/{DECK}/x")]


@pytest.mark.parametrize("generation", [99, 100])
def test_a_stopped_generation_writes_nothing(store, generation):
    storage, table, s3 = store
    table.items[KEY][write_fence.FENCE_ATTR] = 100
    token = _fenced(generation)
    try:
        with pytest.raises(write_fence.StaleTurn, match="Cancelled"):
            storage.upload_file(key=f"decks/{DECK}/slides/a.json", data=b"{}")
        # Every later write of the request is skipped too, without another read.
        gets = table.gets
        for write in (
            lambda: storage.put_slide_json(DECK, "b", {}),
            lambda: storage._s3.delete_object(Bucket="pptx", Key="previews/d1/old.webp"),
            lambda: storage.delete_object_keys(["previews/d1/x.webp"]),
            lambda: storage.update_deck(DECK, USER, {"thumbnailS3Key": "previews/d1/t.webp"}),
        ):
            with pytest.raises(write_fence.StaleTurn):
                write()
        assert table.gets == gets
    finally:
        write_fence.reset(token)
    assert s3.writes == []
    assert "thumbnailS3Key" not in table.items[KEY]


def test_the_deck_update_cannot_race_the_fence(store):
    storage, table, s3 = store
    table.items[KEY][write_fence.FENCE_ATTR] = 100
    token = _fenced(101)
    try:
        storage.upload_file(key="pptx/d1/new.pptx", data=b"")  # passed the check: generation 101 is current
        # The turn is stopped between the check and the record update.
        table.before_update = lambda: write_fence.advance(table, USER, DECK, 101)
        with pytest.raises(write_fence.StaleTurn):
            storage.update_deck(DECK, USER, {"pptxS3Key": "pptx/d1/new.pptx", "updatedAt": "t"})
        with pytest.raises(write_fence.StaleTurn):  # and the rest of the request stops writing
            storage._s3.delete_object(Bucket="pptx", Key="pptx/d1/old.pptx")
    finally:
        write_fence.reset(token)
    assert "pptxS3Key" not in table.items[KEY]
    assert s3.writes == [("put", "pptx/d1/new.pptx")]


def test_the_fence_only_moves_forward_and_only_on_the_owners_deck():
    table = FakeTable()
    table.items[KEY] = {"PK": KEY[0], "SK": KEY[1]}
    assert write_fence.advance(table, USER, DECK, 200) is True
    assert write_fence.advance(table, USER, DECK, 150) is False
    assert write_fence.advance(table, USER, DECK, 200) is False
    assert table.items[KEY][write_fence.FENCE_ATTR] == 200
    # Another user's sub names a different item: nothing exists there, nothing is created.
    assert write_fence.advance(table, "u2", DECK, 300) is False
    assert ("USER#u2", "DECK#d1") not in table.items


@pytest.mark.parametrize("meta, expected", [
    (None, None),
    ({}, None),
    ({"sdpm/generation": 5}, 5),
    ({"sdpm/generation": "5"}, None),
    ({"sdpm/generation": True}, None),
    ({"sdpm/generation": 0}, None),
    ({"sdpm/generation": time.time_ns() + 10**15}, None),  # from the future (~12 days)
])
def test_generation_from_meta(meta, expected):
    assert write_fence.generation_from_meta(meta) == expected


def test_threads_the_request_starts_keep_its_fence(store, monkeypatch):
    storage, table, s3 = store
    table.items[KEY][write_fence.FENCE_ATTR] = 100
    import server_utils
    from tools import html_deck

    seen: list = []
    done = threading.Event()

    def background():
        seen.append(write_fence.current())
        done.set()

    def webp(*args, **kwargs):
        background()

    monkeypatch.setattr(server_utils, "_generate_webp_background", webp)
    token = _fenced(50)
    try:
        remote_server._run_in_background(background, name="t")  # run_python's compose + previews
        assert done.wait(5)
        done.clear()
        server_utils.schedule_webp_background(DECK, Path("x"), Path("y"), storage, [])  # generate_pptx's previews
        assert done.wait(5)
        # html_deck's upload pool: the stale uploads are skipped (and reported as failed).
        files = {"a": Path(__file__), "b": Path(__file__)}
        assert html_deck._upload_all(DECK, files, lambda slug: f"previews/{DECK}/{slug}.html", "text/html", storage) == {}
    finally:
        write_fence.reset(token)
    assert [f.generation for f in seen] == [50, 50]
    assert s3.writes == []


# --- Through the MCP server ---


def _call(tool: str, arguments: dict, meta: dict | None):
    async def run():
        async with create_connected_server_and_client_session(remote_server.mcp) as session:
            return await session.call_tool(tool, arguments, meta=meta)

    return asyncio.run(run())


@pytest.fixture()
def served(store):
    storage, table, s3 = store
    with (
        patch.object(remote_server, "_storage", storage),
        patch.object(remote_server, "_get_user_id", return_value=USER),
        patch.object(remote_server, "_check_deck_access", return_value=None),
    ):
        yield table, s3


_CODE = {"deck_id": DECK, "code": "print(1)", "name": "snippet"}


def test_a_stopped_turns_call_is_cancelled_and_writes_nothing(served):
    table, s3 = served
    table.items[KEY][write_fence.FENCE_ATTR] = 100
    result = _call("code_to_slide", _CODE, {"sdpm/generation": 100})
    assert result.isError
    assert "Cancelled" in result.content[0].text
    assert s3.writes == []


def test_a_current_turns_call_writes(served):
    table, s3 = served
    table.items[KEY][write_fence.FENCE_ATTR] = 100
    result = _call("code_to_slide", _CODE, {"sdpm/generation": 101})
    assert not result.isError, result.content[0].text
    assert s3.writes == [("put", f"decks/{DECK}/includes/snippet.json")]


def test_a_call_without_a_generation_writes_as_before(served):
    table, s3 = served
    table.items[KEY][write_fence.FENCE_ATTR] = 10**30
    result = _call("code_to_slide", _CODE, None)
    assert not result.isError, result.content[0].text
    assert s3.writes == [("put", f"decks/{DECK}/includes/snippet.json")]


def test_fence_turn_fences_the_callers_decks_with_the_requests_generation(served):
    table, _ = served
    result = _call("fence_turn", {"deck_ids": [DECK, DECK, "not-mine"]}, {"sdpm/generation": 300})
    assert json.loads(result.content[0].text) == {"generation": 300, "fenced": [DECK], "unchanged": ["not-mine"]}
    assert table.items[KEY][write_fence.FENCE_ATTR] == 300
    # The call it fenced: the same generation now writes nothing.
    assert _call("code_to_slide", _CODE, {"sdpm/generation": 300}).isError


def test_fence_turn_needs_a_generation(served):
    table, _ = served
    result = _call("fence_turn", {"deck_ids": [DECK]}, None)
    assert "error" in json.loads(result.content[0].text)
    assert write_fence.FENCE_ATTR not in table.items[KEY]


def test_the_generation_survives_strands_mcpclient_over_stateless_http(served):
    """The agent's path: Strands MCPClient with a client-level meta, streamable HTTP, the
    server's stateless_http FastMCP app. (The AgentCore proxy forwards the JSON-RPC body,
    _meta included; dev verification covers that hop.)"""
    import uvicorn
    from mcp.client.streamable_http import streamablehttp_client
    from strands.tools.mcp import MCPClient

    table, s3 = served
    table.items[KEY][write_fence.FENCE_ATTR] = 100
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(remote_server.mcp.streamable_http_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 20
        while not server.started:
            assert time.time() < deadline, "server did not start"
            time.sleep(0.05)
        for generation, written in ((100, False), (101, True)):
            s3.writes.clear()
            client = MCPClient(lambda: streamablehttp_client(f"http://127.0.0.1:{port}/mcp"),
                               meta={"sdpm/generation": generation})
            with client:
                result = client.call_tool_sync(tool_use_id="t1", name="code_to_slide", arguments=_CODE)
            assert (result["status"] == "success") is written, result
            assert bool(s3.writes) is written
    finally:
        server.should_exit = True
        thread.join(10)
