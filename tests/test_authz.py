# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for shared.authz — Authorization."""

import pytest
from unittest.mock import MagicMock, patch
from shared.authz import authorize, resolve_role, check_permission, AccessDecision


@pytest.fixture
def mock_table():
    """Create a mock DynamoDB Table resource."""
    return MagicMock()


class TestResolveRole:
    """Tests for resolve_role function."""

    def test_owner(self, mock_table):
        """Owner check: USER#{user_id}/DECK#{deck_id} exists."""
        mock_table.get_item.return_value = {"Item": {"PK": "USER#u1", "SK": "DECK#d1", "name": "Test"}}
        role, deck = resolve_role(user_id="u1", deck_id="d1", table=mock_table)
        assert role == "owner"
        assert deck["name"] == "Test"

    def test_owner_deleted(self, mock_table):
        """Deleted deck should not resolve as owner."""
        mock_table.get_item.return_value = {"Item": {"PK": "USER#u1", "SK": "DECK#d1", "deletedAt": "2026-01-01"}}
        mock_table.query.return_value = {"Items": []}
        role, deck = resolve_role(user_id="u1", deck_id="d1", table=mock_table)
        assert role == "none"

    def test_public_deck_resolves_viewer(self, mock_table):
        """A non-owner of a public deck is a viewer; only the owner key is looked up."""
        mock_table.get_item.return_value = {}
        mock_table.query.return_value = {"Items": [{"PK": "USER#u1", "SK": "DECK#d1", "name": "Test"}]}
        role, deck = resolve_role(user_id="u2", deck_id="d1", table=mock_table)
        assert role == "viewer"
        assert deck["name"] == "Test"
        mock_table.get_item.assert_called_once_with(Key={"PK": "USER#u2", "SK": "DECK#d1"})

    def test_no_access(self, mock_table):
        """No access when no records match."""
        mock_table.get_item.return_value = {}
        mock_table.query.return_value = {"Items": []}
        role, deck = resolve_role(user_id="u3", deck_id="d1", table=mock_table)
        assert role == "none"
        assert deck is None


class TestCheckPermission:
    """Tests for check_permission function."""

    def test_owner_can_delete(self):
        assert check_permission(role="owner", action="delete_deck") is True

    def test_viewer_cannot_delete(self):
        assert check_permission(role="viewer", action="delete_deck") is False

    def test_viewer_can_read(self):
        assert check_permission(role="viewer", action="read") is True

    @pytest.mark.parametrize("action", ["edit_slide", "generate_pptx", "update", "delete_deck", "change_visibility"])
    def test_viewer_cannot_write(self, action):
        assert check_permission(role="viewer", action=action) is False

    def test_collaborator_role_is_gone(self):
        assert check_permission(role="collaborator", action="read") is False

    def test_unknown_action_raises(self):
        with pytest.raises(ValueError, match="Unknown action"):
            check_permission(role="owner", action="nonexistent_action")


class TestAuthorize:
    """Tests for authorize function (integration of resolve_role + check_permission)."""

    def test_owner_allowed(self, mock_table):
        """Owner can perform any action."""
        mock_table.get_item.return_value = {"Item": {"PK": "USER#u1", "SK": "DECK#d1"}}
        decision = authorize(user_id="u1", deck_id="d1", action="delete_deck", table=mock_table)
        assert decision.allowed is True
        assert decision.role == "owner"

    def test_non_owner_denied(self, mock_table):
        """Non-owner cannot delete."""
        mock_table.get_item.return_value = {}
        mock_table.query.return_value = {"Items": []}
        decision = authorize(user_id="u2", deck_id="d1", action="delete_deck", table=mock_table)
        assert decision.allowed is False
        assert decision.role == "none"

    def test_non_owner_can_read_public_deck(self, mock_table):
        """A public deck is readable by a non-owner."""
        mock_table.get_item.return_value = {}
        mock_table.query.return_value = {"Items": [{"PK": "USER#u1", "SK": "DECK#d1"}]}
        decision = authorize(user_id="u2", deck_id="d1", action="read", table=mock_table)
        assert decision.allowed is True
        assert decision.role == "viewer"

    def test_non_owner_cannot_read_private_deck(self, mock_table):
        """A private deck (not in the PublicDecks GSI) is not readable by a non-owner."""
        mock_table.get_item.return_value = {}
        mock_table.query.return_value = {"Items": []}
        decision = authorize(user_id="u2", deck_id="d1", action="read", table=mock_table)
        assert decision.allowed is False
        assert decision.role == "none"
        assert decision.deck is None

    def test_viewer_can_preview(self, mock_table):
        """Viewer (public deck) can preview."""
        mock_table.get_item.return_value = {}
        mock_table.query.return_value = {"Items": [{"PK": "USER#u1", "SK": "DECK#d1"}]}
        decision = authorize(user_id="u2", deck_id="d1", action="preview", table=mock_table)
        assert decision.allowed is True
        assert decision.role == "viewer"
