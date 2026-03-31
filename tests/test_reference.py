# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for tools.reference — Reference document access via Storage ABC."""

import pytest
from unittest.mock import MagicMock
from tools.reference import (
    list_styles, read_examples,
    list_workflows, read_workflows,
    list_guides, read_guides,
    _cache,
)


@pytest.fixture
def mock_storage():
    """Create a mock Storage backend."""
    storage = MagicMock()
    storage.download_file.return_value = b"---\ndescription: Test doc\n---\n# Content"
    storage.list_files.return_value = [
        "references/examples/hero-title.md",
        "references/examples/component-catalog.md",
    ]
    return storage


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear reference cache before each test."""
    _cache.clear()


class TestListStyles:
    def test_lists_html_styles(self, mock_storage):
        mock_storage.list_files.return_value = [
            "references/examples/styles/elegant-dark.html",
            "references/examples/styles/tech-cyber.html",
        ]
        mock_storage.download_file.return_value = b"<html><head><title>Elegant Dark</title></head></html>"
        result = list_styles(storage=mock_storage)
        assert len(result["styles"]) == 2
        assert result["styles"][0]["name"] == "elegant-dark"
        assert result["styles"][0]["description"] == "Elegant Dark"


class TestReadExamples:
    def test_reads_file(self, mock_storage):
        result = read_examples(names=["hero-title"], storage=mock_storage)
        assert len(result["documents"]) == 1
        assert "Content" in result["documents"][0]["content"]

    def test_rejects_missing(self, mock_storage):
        mock_storage.download_file.side_effect = Exception("not found")
        with pytest.raises(FileNotFoundError, match="not found"):
            read_examples(names=["nonexistent"], storage=mock_storage)


class TestListWorkflows:
    def test_lists_files(self, mock_storage):
        mock_storage.list_files.return_value = [
            "references/workflows/create-new-1a-hearing.md",
        ]
        result = list_workflows(storage=mock_storage)
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "create-new-1a-hearing"


class TestReadGuides:
    def test_reads_file(self, mock_storage):
        result = read_guides(names=["design-rules"], storage=mock_storage)
        assert len(result["documents"]) == 1
