# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for tools.deck — Deck META operations via Storage ABC."""

import pytest
from unittest.mock import MagicMock
from tools.deck import create_deck


@pytest.fixture
def mock_storage():
    """Create a mock Storage backend."""
    storage = MagicMock()
    storage.put_deck = MagicMock()
    storage.get_deck = MagicMock(return_value=None)
    storage.update_deck = MagicMock()
    return storage


class TestCreateDeck:
    """Tests for create_deck function."""

    def test_creates_deck_with_valid_name(self, mock_storage):
        """Verify deck creation returns deckId and name."""
        result = create_deck(name="Test Deck", user_id="user-123", storage=mock_storage)
        assert "deckId" in result
        assert result["name"] == "Test Deck"
        mock_storage.put_deck.assert_called_once()

    def test_rejects_empty_name(self, mock_storage):
        """Verify empty name raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            create_deck(name="", user_id="user-123", storage=mock_storage)

    def test_rejects_whitespace_name(self, mock_storage):
        """Verify whitespace-only name raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            create_deck(name="   ", user_id="user-123", storage=mock_storage)

    def test_rejects_long_name(self, mock_storage):
        """Verify name over 200 chars raises ValueError."""
        with pytest.raises(ValueError, match="200 characters"):
            create_deck(name="x" * 201, user_id="user-123", storage=mock_storage)

    def test_rejects_too_many_tags(self, mock_storage):
        """Verify more than 10 tags raises ValueError."""
        with pytest.raises(ValueError, match="Maximum 10"):
            create_deck(name="Test", user_id="u", storage=mock_storage, tags=["t"] * 11)

    def test_rejects_long_tag(self, mock_storage):
        """Verify tag over 50 chars raises ValueError."""
        with pytest.raises(ValueError, match="exceeds 50"):
            create_deck(name="Test", user_id="u", storage=mock_storage, tags=["x" * 51])

    def test_stores_correct_meta(self, mock_storage):
        """Verify put_deck is called with correct metadata."""
        create_deck(name="My Deck", user_id="user-abc", storage=mock_storage, tags=["aws"])
        call_kwargs = mock_storage.put_deck.call_args[1]
        meta = call_kwargs["meta"]
        assert meta["name"] == "My Deck"
        assert meta["createdBy"] == "user-abc"
        assert meta["tags"] == ["aws"]
