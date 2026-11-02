# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""POST /attachments/presign: the returned source is a handle without the user id.

Same harness as tests/test_api_html_routes.py. The S3 key (PUT target, quota prefix)
stays per user; only the handle the browser passes on to the agent changes.
"""

import re

from test_api_html_routes import _Event, index  # noqa: F401 — index is a fixture

USER = "u-SENTINEL-7f3a"
_UUID4 = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class _JsonEvent(_Event):
    def __init__(self, user_id: str, body: dict):
        super().__init__(user_id)
        self.json_body = body


class _Paginator:
    def __init__(self, prefixes: list):
        self.prefixes = prefixes

    def paginate(self, Bucket, Prefix):
        self.prefixes.append(Prefix)
        return [{"Contents": []}]


class _PresignS3:
    def __init__(self):
        self.prefixes: list[str] = []
        self.params: list[dict] = []

    def get_paginator(self, op):
        assert op == "list_objects_v2"
        return _Paginator(self.prefixes)

    def generate_presigned_url(self, op, Params, ExpiresIn):
        self.params.append({"op": op, **Params})
        return f"https://bucket.example/{Params['Key']}?sig"


def test_presign_returns_a_handle_and_keeps_the_per_user_key(monkeypatch, index):  # noqa: F811
    s3 = _PresignS3()
    monkeypatch.setattr(index, "s3_client", s3)
    index.app.current_event = _JsonEvent(USER, {
        "fileName": "report.pdf", "fileSize": 10, "contentType": "application/pdf",
    })

    result = index.presign_attachment()

    match = re.fullmatch(rf"uploads/({_UUID4})/report\.pdf", result["source"])
    assert match, result["source"]
    assert USER not in result["source"] and USER not in str(result["requiredHeaders"])
    (put,) = s3.params
    assert put["op"] == "put_object"
    assert put["Key"] == f"uploads/{USER}/{match.group(1)}/report.pdf"
    assert s3.prefixes == [f"uploads/{USER}/"]
