# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The caller's user id never reaches the agent through the remote MCP tools.

The tools run through a real MCP client session with a sentinel user id. Storage
must be read under ``uploads/<sentinel>/…`` (the key is derived from the caller),
while nothing the agent receives (content, structured content, errors) contains
the sentinel.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

_ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault("DECKS_TABLE", "test-table")
os.environ.setdefault("PPTX_BUCKET", "test-pptx")
os.environ.setdefault("RESOURCE_BUCKET", "test-resource")

_spec = importlib.util.spec_from_file_location("remote_server_user_id_under_test", _ROOT / "servers" / "remote" / "server.py")
remote_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remote_server)

SENTINEL = "u-SENTINEL-7f3a"
OTHER = "u-OTHER-2b9c"
UPLOAD = "123e4567-e89b-12d3-a456-426614174000"
HANDLE = f"uploads/{UPLOAD}/report.txt"
KEY = f"uploads/{SENTINEL}/{UPLOAD}/report.txt"


class _Storage:
    """Uploads by S3 key plus the cache and bundle writes the attachment tools make."""

    def __init__(self, uploads: dict[str, tuple[bytes, str]] | None = None) -> None:
        self.uploads = uploads or {}
        self.objects: dict[str, bytes] = {}
        self.checksums: dict[str, str] = {}
        self.read_keys: list[str] = []

    def head_object(self, key: str) -> dict:
        self.read_keys.append(key)
        if key in self.objects:
            return {"ContentLength": len(self.objects[key]), "ChecksumSHA256": self.checksums.get(key)}
        if key in self.uploads:
            data, content_type = self.uploads[key]
            return {"ContentLength": len(data), "ContentType": content_type, "ETag": '"etag"'}
        raise KeyError(f"NoSuchKey: {key}")  # like an S3 error, it names the key

    def download_file_from_pptx_bucket(self, key: str) -> bytes:
        self.read_keys.append(key)
        if key in self.objects:
            return self.objects[key]
        if key in self.uploads:
            return self.uploads[key][0]
        raise KeyError(f"NoSuchKey: {key}")

    def upload_file_if_absent(self, key, data, _content_type, checksum, _tagging) -> bool:
        if key in self.objects:
            return False
        self.objects[key] = data
        self.checksums[key] = checksum
        return True

    def upload_file(self, key, data, content_type="", tagging="") -> None:
        self.objects[key] = data

    def list_object_metadata(self, prefix, max_objects=1000) -> list:
        return []

    def delete_object_keys(self, keys) -> None:
        for key in keys:
            self.objects.pop(key, None)


@pytest.fixture(autouse=True)
def _fresh_local_stage_cache():
    """The remote stage cache keeps a local projection per user; start each test cold."""
    for user in (SENTINEL, OTHER):
        digest = hashlib.sha256(user.encode("utf-8")).hexdigest()
        shutil.rmtree(Path(tempfile.gettempdir()) / "sdpm-attachment-cache" / digest, ignore_errors=True)
    yield


def _call(storage: _Storage, tool: str, arguments: dict, user: str = SENTINEL):
    async def run():
        async with create_connected_server_and_client_session(remote_server.mcp) as session:
            return await session.call_tool(tool, arguments)

    with (
        patch.object(remote_server, "_storage", storage),
        patch.object(remote_server, "_get_user_id", return_value=user),
        patch.object(remote_server, "_check_deck_access", lambda *a, **k: None),
    ):
        return asyncio.run(run())


def _seen_by_agent(result) -> str:
    return json.dumps([c.model_dump(mode="json") for c in result.content]) + json.dumps(result.structuredContent)


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), (200, 40, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


# --- read_attachment ----------------------------------------------------------


@pytest.mark.parametrize("source", [HANDLE, KEY], ids=["handle", "previous-form"])
def test_read_text_uses_caller_key_and_returns_the_handle(source):
    storage = _Storage({KEY: (b"hello\nworld\n", "text/plain")})

    result = _call(storage, "read_attachment", {"source": source})

    assert not result.isError, result.content[0].text
    assert result.structuredContent["header"]["source"] == HANDLE
    assert "hello" in result.structuredContent["body"]
    assert KEY in storage.read_keys
    assert SENTINEL not in _seen_by_agent(result)


def test_read_image_uses_caller_key_and_returns_the_handle():
    key = f"uploads/{SENTINEL}/{UPLOAD}/photo.png"
    storage = _Storage({key: (_png(), "image/png")})

    result = _call(storage, "read_attachment", {"source": f"uploads/{UPLOAD}/photo.png"})

    assert not result.isError, result.content[0].text
    assert result.structuredContent["kind"] == "image"
    assert result.structuredContent["source"] == f"uploads/{UPLOAD}/photo.png"
    assert key in storage.read_keys
    assert SENTINEL not in _seen_by_agent(result)


def test_read_another_users_handle_reads_only_the_callers_prefix():
    """A handle names an upload of the caller; another user's upload cannot be reached."""
    storage = _Storage({f"uploads/{OTHER}/{UPLOAD}/report.txt": (b"secret\n", "text/plain")})

    result = _call(storage, "read_attachment", {"source": HANDLE})

    assert result.structuredContent["code"] == "SOURCE_NOT_FOUND"
    assert storage.read_keys == [KEY]
    seen = _seen_by_agent(result)
    assert SENTINEL not in seen and "secret" not in seen


def test_read_previous_form_of_another_user_is_denied_without_ids():
    storage = _Storage()

    result = _call(storage, "read_attachment", {"source": f"uploads/{OTHER}/{UPLOAD}/report.txt"})

    assert result.structuredContent["code"] == "SOURCE_ACCESS_DENIED"
    assert storage.read_keys == []
    seen = _seen_by_agent(result)
    assert SENTINEL not in seen and OTHER not in seen


def test_read_storage_failure_does_not_name_the_key():
    class _Failing(_Storage):
        def download_file_from_pptx_bucket(self, key):
            if key.startswith("attachment-cache/"):
                raise RuntimeError(f"AccessDenied on arn:aws:s3:::bucket/{key}")
            return super().download_file_from_pptx_bucket(key)

        def upload_file_if_absent(self, key, *args):
            raise RuntimeError(f"AccessDenied on arn:aws:s3:::bucket/{key}")

    result = _call(_Failing({KEY: (b"hello\n", "text/plain")}), "read_attachment", {"source": HANDLE})

    assert result.isError
    assert "attachment-cache/v1/<user>/" in result.content[0].text
    assert SENTINEL not in _seen_by_agent(result)


# --- import_attachment --------------------------------------------------------


def test_import_success_then_reuse():
    storage = _Storage({KEY: (b"hello\nworld\n", "text/plain")})

    first = _call(storage, "import_attachment", {"source": HANDLE, "deck_id": "d1"})
    again = _call(storage, "import_attachment", {"source": KEY, "deck_id": "d1"})

    first_body = json.loads(first.content[0].text)
    again_body = json.loads(again.content[0].text)
    assert first_body["reused"] is False and first_body["bundlePath"].startswith("attachments/imports/")
    assert again_body["reused"] is True and again_body["importKey"] == first_body["importKey"]
    assert KEY in storage.read_keys
    assert SENTINEL not in _seen_by_agent(first) + _seen_by_agent(again)


def test_import_source_not_found():
    storage = _Storage()

    result = _call(storage, "import_attachment", {"source": HANDLE, "deck_id": "d1"})

    assert json.loads(result.content[0].text)["code"] == "SOURCE_NOT_FOUND"
    assert KEY in storage.read_keys
    assert SENTINEL not in _seen_by_agent(result)


def test_import_access_denied():
    storage = _Storage()

    result = _call(storage, "import_attachment", {"source": f"uploads/{OTHER}/{UPLOAD}/report.txt", "deck_id": "d1"})

    assert json.loads(result.content[0].text)["code"] == "SOURCE_ACCESS_DENIED"
    assert not any(key.startswith("uploads/") for key in storage.read_keys)
    seen = _seen_by_agent(result)
    assert SENTINEL not in seen and OTHER not in seen


def test_import_incomplete():
    storage = _Storage({KEY: (b"hello\nworld\n", "text/plain")})

    with patch("sdpm.tools.attachment.pipeline.IMPORT_DEADLINE_S", 0):
        result = _call(storage, "import_attachment", {"source": HANDLE, "deck_id": "d1"})

    assert json.loads(result.content[0].text)["code"] == "IMPORT_INCOMPLETE"
    assert KEY in storage.read_keys
    assert SENTINEL not in _seen_by_agent(result)


def test_import_conversion_failure_is_reported_without_the_key():
    class _Failing(_Storage):
        def upload_file_if_absent(self, key, *args):
            raise RuntimeError(f"AccessDenied on arn:aws:s3:::bucket/{key}")

    result = _call(_Failing({KEY: (b"hello\n", "text/plain")}), "import_attachment", {"source": HANDLE, "deck_id": "d1"})

    body = json.loads(result.content[0].text)
    assert body["code"] == "IMPORT_CONVERSION_FAILED" and "AccessDenied" in body["message"]
    assert SENTINEL not in _seen_by_agent(result)


def test_import_unexpected_failure_does_not_name_the_key():
    from sdpm.tools.attachment.fetcher import FetchResult

    class _Failing(_Storage):
        def upload_file_if_absent(self, key, *args):
            raise RuntimeError(f"AccessDenied on arn:aws:s3:::bucket/{key}")

    fetched = FetchResult(data=b"url content\n", final_url="https://example.com/r.txt", content_type="text/plain")
    with patch("tools.attachment.fetch_url", return_value=fetched):
        result = _call(_Failing(), "import_attachment", {"source": "https://example.com/r.txt", "deck_id": "d1"})

    body = json.loads(result.content[0].text)
    assert body["error"]["code"] == "IMPORT_ERROR" and "attachment-cache/v1/<user>/" in body["error"]["message"]
    assert SENTINEL not in _seen_by_agent(result)


# --- run_style_python ---------------------------------------------------------


class _CodeInterpreter:
    """Sandbox whose style.html differs from the loaded one after the user code ran."""

    def start_code_interpreter_session(self, **kwargs):
        return {"sessionId": "ci-1"}

    def stop_code_interpreter_session(self, **kwargs):
        return {}

    def invoke_code_interpreter(self, *, name, arguments, **kwargs):
        text = "ok"
        if name == "executeCode" and "open('style.html').read()" in arguments["code"]:
            text = "<title>New</title>"
        return {"stream": [{"result": {"content": [{"type": "text", "text": text}]}}]}


def test_run_style_python_saved_has_no_key():
    storage = _Storage()

    with (
        patch.object(remote_server.boto3, "client", lambda *a, **k: _CodeInterpreter()),
        patch.object(remote_server, "_load_style_html", lambda user_id, name: "<title>Old</title>"),
    ):
        result = _call(storage, "run_style_python", {"purpose": "edit", "code": "pass", "style_name": "mine"})

    body = json.loads(result.content[0].text)
    assert body["saved"] == {"filename": "mine.html", "name": "mine"}
    assert SENTINEL not in _seen_by_agent(result)


def test_run_style_python_rejects_a_style_name_that_is_not_a_file_stem():
    storage = _Storage()

    with patch.object(remote_server.boto3, "client", lambda *a, **k: _CodeInterpreter()):
        result = _call(storage, "run_style_python", {"purpose": "edit", "code": "pass", "style_name": "../other/mine"})

    assert result.isError
    assert "Invalid style name" in result.content[0].text
    assert not storage.objects
