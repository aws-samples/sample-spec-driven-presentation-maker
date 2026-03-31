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

    def test_collaborator(self, mock_table):
        """Collaborator check: SHARED#{user_id}/DECK#{deck_id} exists."""
        def get_item_side_effect(Key):
            if Key["PK"] == "USER#u2":
                return {}  # Not owner
            if Key["PK"] == "SHARED#u2":
                return {"Item": {"PK": "SHARED#u2", "SK": "DECK#d1", "ownerUserId": "u1"}}
            if Key["PK"] == "USER#u1":
                return {"Item": {"PK": "USER#u1", "SK": "DECK#d1", "name": "Test"}}
            return {}

        mock_table.get_item.side_effect = get_item_side_effect
        role, deck = resolve_role(user_id="u2", deck_id="d1", table=mock_table)
        assert role == "collaborator"
        assert deck["name"] == "Test"

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

    def test_collaborator_can_edit(self):
        assert check_permission(role="collaborator", action="edit_slide") is True

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

    def test_viewer_can_preview(self, mock_table):
        """Viewer (public deck) can preview."""
        mock_table.get_item.return_value = {}
        mock_table.query.return_value = {"Items": [{"PK": "USER#u1", "SK": "DECK#d1"}]}
        decision = authorize(user_id="u2", deck_id="d1", action="preview", table=mock_table)
        assert decision.allowed is True
        assert decision.role == "viewer"
