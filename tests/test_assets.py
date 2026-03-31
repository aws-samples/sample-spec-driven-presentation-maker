# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for tools.assets — Asset search via Storage ABC."""

import json
import pytest
from unittest.mock import MagicMock, patch
from tools.assets import search_assets, list_asset_sources, _manifest_cache


SAMPLE_MANIFEST = json.dumps([
    {"name": "AWS Lambda", "file": "lambda.svg", "tags": ["compute", "serverless"]},
    {"name": "Amazon S3", "file": "s3.svg", "tags": ["storage", "simple storage service"]},
    {"name": "Corporate Logo", "file": "corp.png", "tags": ["brand"]},
]).encode()


@pytest.fixture
def mock_storage():
    """Create a mock Storage backend with sample manifest."""
    storage = MagicMock()
    storage.list_files.return_value = ["assets/aws/manifest.json"]
    storage.download_file.return_value = SAMPLE_MANIFEST
    return storage


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear manifest cache before each test."""
    _manifest_cache.clear()


class TestSearchAssets:
    def test_finds_by_name(self, mock_storage):
        result = search_assets(query="lambda", storage=mock_storage)
        assert len(result["results"]) == 1
        assert result["results"][0]["name"] == "AWS Lambda"

    def test_finds_by_tag(self, mock_storage):
        result = search_assets(query="storage", storage=mock_storage)
        names = [a["name"] for a in result["results"]]
        assert "Amazon S3" in names

    def test_filters_by_source(self, mock_storage):
        result = search_assets(query="lambda", storage=mock_storage, source_filter="nonexistent")
        assert result["results"] == []

    def test_returns_empty_for_no_match(self, mock_storage):
        result = search_assets(query="nonexistent", storage=mock_storage)
        assert result["results"] == []
