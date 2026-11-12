# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""In-memory S3 client and DynamoDB Table doubles for the user-library tests.

Only the calls shared/user_library.py, api/index.py's style / template routes and
AwsStorage make are implemented. Reads return copies, as boto3 does, so a caller
that mutates a returned list cannot change the stored item behind the table's back.
"""

import copy
import io
import re
from pathlib import Path


class FakeS3:
    """Buckets as ``{bucket: {key: bytes}}``; ETags as ``{(bucket, key): etag}``."""

    def __init__(self, buckets: dict[str, dict[str, bytes]] | None = None, etags: dict | None = None):
        self.buckets = {name: dict(objects) for name, objects in (buckets or {}).items()}
        self.etags = dict(etags or {})
        self.downloads: list[tuple[str, str, str]] = []

    def _bucket(self, name: str) -> dict[str, bytes]:
        return self.buckets.setdefault(name, {})

    def _contents(self, bucket: str, prefix: str) -> list[dict]:
        return [
            {"Key": key, "ETag": self.etags.get((bucket, key), '"etag"')}
            for key in sorted(self._bucket(bucket))
            if key.startswith(prefix)
        ]

    def list_objects_v2(self, Bucket, Prefix):
        return {"Contents": self._contents(Bucket, Prefix)}

    def get_paginator(self, operation):
        assert operation == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):
        yield {"Contents": self._contents(Bucket, Prefix)}

    def get_object(self, Bucket, Key):
        if Key not in self._bucket(Bucket):
            raise KeyError(Key)
        return {"Body": io.BytesIO(self._bucket(Bucket)[Key])}

    def head_object(self, Bucket, Key, **kwargs):
        if Key not in self._bucket(Bucket):
            raise KeyError(Key)
        return {}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self._bucket(Bucket)[Key] = Body if isinstance(Body, bytes) else Body.encode("utf-8")

    def delete_object(self, Bucket, Key):
        self._bucket(Bucket).pop(Key, None)

    def copy_object(self, Bucket, CopySource, Key):
        self._bucket(Bucket)[Key] = self._bucket(CopySource["Bucket"])[CopySource["Key"]]

    def download_file(self, Bucket, Key, Filename):
        self.downloads.append((Bucket, Key, Filename))
        Path(Filename).write_bytes(self._bucket(Bucket)[Key])

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://s3.example/{Params['Bucket']}/{Params['Key']}?op={op}"


class _Meta:
    def __init__(self, table: "FakeTable"):
        self.client = self
        self._table = table

    def batch_get_item(self, RequestItems):
        self._table.batch_requests.append(copy.deepcopy(RequestItems))
        keys = RequestItems[self._table.name]["Keys"]
        found = [copy.deepcopy(self._table.items[(k["PK"], k["SK"])]) for k in keys if (k["PK"], k["SK"]) in self._table.items]
        return {"Responses": {self._table.name: found}}


class FakeTable:
    """DynamoDB Table double keyed by (PK, SK)."""

    name = "sdpm-test"

    def __init__(self, items: list[dict] | None = None):
        self.items: dict[tuple[str, str], dict] = {}
        self.batch_requests: list[dict] = []
        self.queries: list[dict] = []
        self.meta = _Meta(self)
        for item in items or []:
            self.put_item(Item=item)

    def get_item(self, Key):
        item = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": copy.deepcopy(item)} if item is not None else {}

    def put_item(self, Item):
        self.items[(Item["PK"], Item["SK"])] = copy.deepcopy(Item)

    def delete_item(self, Key):
        self.items.pop((Key["PK"], Key["SK"]), None)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None):
        item = self.items[(Key["PK"], Key["SK"])]
        for name, value in re.findall(r"(#?\w+) = (:\w+)", UpdateExpression):
            attr = (ExpressionAttributeNames or {}).get(name, name)
            item[attr] = ExpressionAttributeValues[value]

    def query(self, KeyConditionExpression, ExpressionAttributeValues, **kwargs):
        assert KeyConditionExpression == "PK = :pk AND begins_with(SK, :prefix)"
        self.queries.append(dict(ExpressionAttributeValues))
        pk, prefix = ExpressionAttributeValues[":pk"], ExpressionAttributeValues[":prefix"]
        return {
            "Items": [
                copy.deepcopy(item)
                for (item_pk, item_sk), item in sorted(self.items.items())
                if item_pk == pk and item_sk.startswith(prefix)
            ]
        }


def style_html(title: str) -> bytes:
    return f"<html><head><title> {title} </title></head><body></body></html>".encode()
