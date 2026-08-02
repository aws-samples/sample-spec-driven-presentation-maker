# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Remote stateless attachment adapter tests."""

from __future__ import annotations

from unittest.mock import patch

from sdpm.tools.attachment.fetcher import FetchResult
from tools.attachment import read_attachment


class _ReadStorage:
    def __init__(self, data: bytes = b"hello\nworld\n") -> None:
        self.data = data
        self.head_calls: list[str] = []
        self.objects: dict[str, bytes] = {}
        self.checksums: dict[str, str] = {}

    def head_object(self, key: str) -> dict:
        self.head_calls.append(key)
        if key in self.objects:
            return {
                "ContentLength": len(self.objects[key]),
                "ChecksumSHA256": self.checksums[key],
            }
        return {"ContentLength": len(self.data), "ContentType": "text/plain", "ETag": '"etag"'}

    def download_file_from_pptx_bucket(self, key: str) -> bytes:
        if key.startswith("attachment-cache/"):
            if key not in self.objects:
                raise KeyError(key)
            return self.objects[key]
        return self.data

    def upload_file_if_absent(
        self,
        key: str,
        data: bytes,
        _content_type: str,
        checksum: str,
        _tagging: str,
    ) -> bool:
        if key in self.objects:
            return False
        self.objects[key] = data
        self.checksums[key] = checksum
        return True

    def upload_file(
        self,
        key: str,
        data: bytes,
        _content_type: str = "",
        _tagging: str = "",
    ) -> None:
        self.objects[key] = data


def test_remote_read_owned_s3_key() -> None:
    source = "uploads/user-1/123e4567-e89b-12d3-a456-426614174000/report.txt"
    storage = _ReadStorage()

    result = read_attachment(source, "user-1", storage)

    assert result["header"]["source"] == source
    assert result["header"]["fileName"] == "report.txt"
    assert "hello" in result["body"]
    assert storage.head_calls[0] == source


def test_remote_read_rejects_wrong_owner_before_s3() -> None:
    source = "uploads/user-1/123e4567-e89b-12d3-a456-426614174000/report.txt"
    storage = _ReadStorage()

    result = read_attachment(source, "user-2", storage)

    assert result["code"] == "SOURCE_ACCESS_DENIED"
    assert storage.head_calls == []


def test_remote_read_url_uses_shared_secure_fetcher() -> None:
    fetched = FetchResult(
        data=b"url content\n",
        final_url="https://cdn.example/report.txt",
        content_type="text/plain",
    )
    with patch("tools.attachment.fetch_url", return_value=fetched) as fetch:
        result = read_attachment("https://example.com/report.txt", "user-1", _ReadStorage())

    fetch.assert_called_once_with("https://example.com/report.txt")
    assert result["header"]["fileName"] == "report.txt"
    assert "url content" in result["body"]


def test_remote_read_reuses_persistent_s3_stage_cache() -> None:
    import hashlib
    import shutil
    import tempfile
    from pathlib import Path

    user_id = "cache-test-user"
    source = f"uploads/{user_id}/123e4567-e89b-12d3-a456-426614174000/report.txt"
    storage = _ReadStorage()
    local_cache = (
        Path(tempfile.gettempdir())
        / "sdpm-attachment-cache"
        / hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    )
    shutil.rmtree(local_cache, ignore_errors=True)

    first = read_attachment(source, user_id, storage)
    assert "hello" in first["body"]
    assert any(key.endswith("/complete.json") for key in storage.objects)

    # Simulate a cold runtime: only the S3 completion record and attempt outputs remain.
    shutil.rmtree(local_cache, ignore_errors=True)
    with patch(
        "sdpm.tools.attachment.pipeline._compute_text_projection",
        side_effect=AssertionError("persistent stage cache should avoid recomputation"),
    ):
        resumed = read_attachment(source, user_id, storage)
    assert "hello" in resumed["body"]
