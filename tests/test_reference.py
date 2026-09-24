# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the shared tool contract (sdpm.tools) reference access
and the remote-specific style listing (tools.reference)."""

from pathlib import Path
from unittest.mock import MagicMock

from sdpm import tools as contract
from tools.reference import list_styles as remote_list_styles


class TestContractReference:
    """Contract reference tools read bundled data from the local filesystem."""

    def test_workflow_readers_are_gone(self):
        # Role documents arrive through the start_* entry tools; the spec is a guide.
        assert not hasattr(contract, "read_workflows")
        assert not hasattr(contract, "list_workflows")

    def test_list_guides(self):
        result = contract.list_guides()
        names = [item["name"] for item in result["items"]]
        assert "design-rules" in names
        assert "hand-edit-sync" in names
        assert "slide-json-spec" in names

    def test_read_slide_spec_as_guide(self):
        result = contract.read_guides(["slide-json-spec"])
        assert len(result["documents"]) == 1
        assert "deck.json" in result["documents"][0]["content"]

    def test_read_guides(self):
        result = contract.read_guides(["hand-edit-sync"])
        assert len(result["documents"]) == 1
        assert result["documents"][0]["content"]

    def test_read_examples_is_gone(self):
        # components/all and patterns were retired; styles are reached via
        # list_styles / apply_style, not a generic example reader.
        assert not hasattr(contract, "read_examples")


def test_reference_vocabulary_is_environment_neutral():
    """Role/fact docs use contract vocabulary, apart from documented CLI setup."""
    references = Path(__file__).parents[1] / "sdpm" / "references"
    roots = [references / name for name in ("workflows", "guides")]
    allowed_cli = {
        references / "guides" / "setup.md",
        references / "guides" / "arch-layout-engine.md",
    }
    banned = ("pptx_builder.py", "uv run", "read_workflows", "init_presentation")

    offenders = []
    for base in roots:
        for path in base.glob("*.md"):
            if path in allowed_cli:
                continue
            found = [token for token in banned if token in path.read_text(encoding="utf-8")]
            if found:
                offenders.append((str(path.relative_to(references)), found))
    assert not offenders

    arch = (references / "guides" / "arch-layout-engine.md").read_text(encoding="utf-8")
    assert arch.count("pptx_builder.py") == 1
    assert "start_presentation" not in arch


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

    def test_pinned_filter_reports_hidden_builtin_names(self):
        storage = MagicMock()
        storage.pptx_bucket = "bucket"
        storage.list_files.return_value = []
        all_builtin = remote_list_styles(storage=storage, user_id="", include_all=True)["styles"]
        assert len(all_builtin) >= 2
        pinned, *others = [s["name"] for s in all_builtin]
        storage.get_style_pins.return_value = [pinned]

        result = remote_list_styles(storage=storage, user_id="u1", include_all=False)
        assert [s["name"] for s in result["styles"]] == [pinned]
        assert result["other_styles"] == others
        assert "hint" in result
