# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the shared tool contract (sdpm.tools) reference access
and the remote-specific style listing (tools.reference)."""

import pytest
from unittest.mock import MagicMock

from sdpm import tools as contract
from tools.reference import list_styles as remote_list_styles


class TestContractReference:
    """Contract reference tools read bundled data from the local filesystem."""

    def test_list_workflows(self):
        result = contract.list_workflows()
        names = [i["name"] for i in result["items"]]
        assert "create-new-1-briefing" in names

    def test_read_workflows(self):
        result = contract.read_workflows(["create-new-1-briefing"])
        assert len(result["documents"]) == 1
        assert result["documents"][0]["content"]

    def test_list_guides(self):
        result = contract.list_guides()
        names = [i["name"] for i in result["items"]]
        assert "design-rules" in names

    def test_read_guides(self):
        result = contract.read_guides(["design-rules"])
        assert len(result["documents"]) == 1
        assert result["documents"][0]["content"]

    def test_read_examples_rejects_missing(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            contract.read_examples(["nonexistent-doc-xyz"])

    def test_start_presentation_returns_instructions(self):
        text = contract.start_presentation()
        assert "read_workflows" in text
        assert "create-new-1-briefing" in text


class TestRemoteListStyles:
    """Remote list_styles merges bundled styles with user styles from storage."""

    def test_bundled_styles_no_user(self):
        storage = MagicMock()
        result = remote_list_styles(storage=storage, user_id="", include_all=True)
        assert len(result["styles"]) > 0
        assert all(s["source"] == "builtin" for s in result["styles"])
        # No user_id → storage must not be touched
        storage.list_files.assert_not_called()

    def test_user_styles_merged(self):
        storage = MagicMock()
        storage.pptx_bucket = "bucket"
        storage.list_files.return_value = ["user-styles/u1/my-style.html"]
        storage.download_file_from_pptx_bucket.return_value = (
            b"<html><head><title>My Style</title></head></html>"
        )
        storage.get_style_pins.return_value = []
        result = remote_list_styles(storage=storage, user_id="u1", include_all=True)
        user = [s for s in result["styles"] if s["source"] == "user"]
        assert len(user) == 1
        assert user[0]["name"] == "my-style"
        assert user[0]["description"] == "My Style"
