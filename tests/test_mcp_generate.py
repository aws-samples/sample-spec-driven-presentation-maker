# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for mcp-server tools.generate — S3 workspace materialization +
delegation to the engine facade (sdpm.api.generate)."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tools import generate as generate_mod

_TEMPLATE = Path(__file__).resolve().parent.parent / "sdpm" / "templates" / "blank-dark.pptx"

_SLIDE = {
    "layout": "blank",
    "elements": [
        {"type": "textbox", "text": "Hello", "x": 100, "y": 100, "w": 600, "h": 80,
         "fontSize": 32},
    ],
}


@pytest.fixture
def mock_storage():
    """Storage mock materializing a one-slide deck."""
    storage = MagicMock()
    storage.pptx_bucket = "pptx-bucket"
    storage.get_deck.return_value = {"deckId": "d1", "name": "Test"}
    storage.get_deck_json.return_value = {
        "template": "", "fonts": {"fullwidth": "", "halfwidth": ""},
    }
    storage.get_user_template_metadata.return_value = None
    storage.list_user_templates.return_value = []

    def list_files(prefix: str, bucket: str = ""):
        if prefix.endswith("/slides/"):
            return ["decks/d1/slides/intro.json"]
        return []

    storage.list_files.side_effect = list_files

    def download_pptx_bucket(key: str):
        if key.endswith("outline.md"):
            return b"- [intro] Opening slide\n"
        if key.endswith("intro.json"):
            return json.dumps(_SLIDE).encode()
        raise FileNotFoundError(key)

    storage.download_file_from_pptx_bucket.side_effect = download_pptx_bucket
    storage.download_file.side_effect = lambda key: (
        _TEMPLATE.read_bytes() if key == "templates/blank-dark.pptx"
        else (_ for _ in ()).throw(FileNotFoundError(key))
    )
    storage.list_templates.return_value = []
    return storage


def test_generate_pptx_via_api_facade(mock_storage, monkeypatch):
    """Full remote generate path: materialize → api.generate → upload."""
    import server_utils
    monkeypatch.setattr(server_utils, "schedule_webp_background", MagicMock())

    result = generate_mod.generate_pptx(
        deck_id="d1", user_id="u1", storage=mock_storage, kb_sync=None,
    )

    assert result["status"] == "completed"
    assert result["slideCount"] == 1
    assert result["slides"][0].startswith("page01")
    # PPTX was uploaded
    upload_call = mock_storage.upload_file.call_args
    assert upload_call.kwargs["key"].startswith("pptx/d1/")
    assert upload_call.kwargs["data"][:2] == b"PK"  # zip magic
    # Deck record updated
    assert mock_storage.update_deck.called


def test_generate_pptx_missing_deck(mock_storage):
    mock_storage.get_deck.return_value = None
    with pytest.raises(ValueError, match="not found"):
        generate_mod.generate_pptx(deck_id="dX", user_id="u1", storage=mock_storage)


def test_prepare_workspace_resolves_user_template(mock_storage):
    """A deck referencing an uploaded user template uses it (Issue #206)."""
    mock_storage.get_deck_json.return_value = {
        "template": "my-brand.pptx", "fonts": {"fullwidth": "", "halfwidth": ""},
    }
    mock_storage.get_user_template_metadata.return_value = {
        "name": "my-brand", "s3Key": "user-templates/u1/my-brand.pptx",
    }
    mock_storage.download_user_template.return_value = _TEMPLATE.read_bytes()

    tmpdir, _slides, build_kwargs = generate_mod._prepare_workspace(
        "d1", "u1", mock_storage,
    )

    mock_storage.get_user_template_metadata.assert_called_once_with("u1", "my-brand")
    mock_storage.download_user_template.assert_called_once_with("u1", "my-brand")
    assert build_kwargs["template_path"].read_bytes()[:2] == b"PK"
    # Builtin download path must not be used for the template
    for call in mock_storage.download_file.call_args_list:
        assert not call.kwargs.get("key", "").startswith("templates/")


def test_prepare_workspace_unknown_template_raises(mock_storage):
    """An unresolvable template name fails loudly instead of silently
    falling back to blank-dark (Issue #206)."""
    mock_storage.get_deck_json.return_value = {
        "template": "ghost.pptx", "fonts": {"fullwidth": "", "halfwidth": ""},
    }
    mock_storage.list_templates.return_value = [
        {"name": "blank-dark", "s3Key": "templates/blank-dark.pptx"},
    ]
    mock_storage.list_user_templates.return_value = [{"name": "my-brand"}]

    with pytest.raises(ValueError, match=r"'ghost\.pptx' not found.*blank-dark.*my-brand"):
        generate_mod._prepare_workspace("d1", "u1", mock_storage)


def test_prepare_workspace_empty_template_defaults_to_blank_dark(mock_storage):
    """No template specified → blank-dark default (regression guard)."""
    tmpdir, _slides, build_kwargs = generate_mod._prepare_workspace(
        "d1", "u1", mock_storage,
    )

    mock_storage.download_file.assert_any_call(key="templates/blank-dark.pptx")
    assert build_kwargs["template_path"].read_bytes()[:2] == b"PK"
