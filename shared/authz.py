# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Centralized resource access control for spec-driven-presentation-maker.

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

Used by both api/ and mcp-server/ for Deck-level authorization.

Role resolution order:
  1. USER#{user_id} + DECK#{deck_id} exists → owner
  2. SHARED#{user_id} + DECK#{deck_id} exists → collaborator
  3. Deck visibility=public → viewer
  4. None of the above → none (access denied)

Permission matrix: action × role determines allowed/denied.

Customization:
  - To add roles: modify resolve_role() to check additional DDB records.
  - To add actions: add entries to DEFAULT_PERMISSIONS.
  - This is the single file to modify for authorization changes.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Set

from shared.schema import (
    deck_pk,
    deck_sk,
    shared_pk,
    GSI_PUBLIC_DECKS,
    public_gsi1pk,
)


@dataclass
class AccessDecision:
    """Result of an authorization check.

    Attributes:
        allowed: Whether the action is permitted.
        role: Resolved role — "owner", "collaborator", "viewer", or "none".
        deck: The Deck DynamoDB record if access is granted, None otherwise.
        reason: Human-readable denial reason when allowed=False.
    """

    allowed: bool
    role: str
    deck: Optional[Dict[str, Any]] = None
    reason: str = ""


# action → set of roles that can perform it
DEFAULT_PERMISSIONS: Dict[str, Set[str]] = {
    # Read operations
    "read": {"owner", "collaborator", "viewer"},
    "preview": {"owner", "collaborator", "viewer"},
    # Write operations
    "edit_slide": {"owner", "collaborator"},
    # Generation
    "generate_pptx": {"owner", "collaborator"},
    # Deck management
    "update": {"owner"},
    "delete_deck": {"owner"},
    "change_visibility": {"owner"},
}


def resolve_role(
    user_id: str,
    deck_id: str,
    table: Any,
) -> tuple[str, Optional[Dict[str, Any]]]:
    """Resolve the user's role for a given Deck.

    Queries DynamoDB to determine ownership, shared access, or public visibility.
    This is the single function to modify for custom role resolution
    (e.g. team-based access, external IdP groups).

    Args:
        user_id: User identifier (JWT sub).
        deck_id: Target Deck identifier.
        table: boto3 DynamoDB Table resource.

    Returns:
        Tuple of (role, deck_record). role is one of "owner", "collaborator",
        "viewer", "none". deck_record is the DDB item or None.
    """
    # 1. Owner check
    resp = table.get_item(Key={"PK": deck_pk(user_id), "SK": deck_sk(deck_id)})
    deck = resp.get("Item")
    if deck and "deletedAt" not in deck:
        return "owner", deck

    # 2. Collaborator check
    shared = table.get_item(
        Key={"PK": shared_pk(user_id), "SK": deck_sk(deck_id)}
    ).get("Item")
    if shared:
        owner_id = shared.get("ownerUserId")
        if owner_id:
            owner_resp = table.get_item(
                Key={"PK": deck_pk(owner_id), "SK": deck_sk(deck_id)}
            )
            deck = owner_resp.get("Item")
            if deck and "deletedAt" not in deck:
                return "collaborator", deck

    # 3. Public viewer check (GSI query)
    from boto3.dynamodb.conditions import Key

    gsi_resp = table.query(
        IndexName=GSI_PUBLIC_DECKS,
        KeyConditionExpression=Key("GSI1PK").eq(public_gsi1pk()),
        FilterExpression="SK = :sk AND attribute_not_exists(deletedAt)",
        ExpressionAttributeValues={":sk": deck_sk(deck_id)},
    )
    items = gsi_resp.get("Items", [])
    if items:
        return "viewer", items[0]

    # 4. No access
    return "none", None


def check_permission(role: str, action: str) -> bool:
    """Check if a role is allowed to perform an action.

    Args:
        role: User's resolved role for the resource.
        action: The operation being attempted.

    Returns:
        True if the action is permitted for the role.

    Raises:
        ValueError: If the action is not defined in DEFAULT_PERMISSIONS.
    """
    allowed_roles = DEFAULT_PERMISSIONS.get(action)
    if allowed_roles is None:
        raise ValueError(f"Unknown action: {action}")
    return role in allowed_roles


def authorize(
    user_id: str,
    deck_id: str,
    action: str,
    table: Any,
) -> AccessDecision:
    """Authorize a user action on a Deck.

    Single entry point for all Deck-level authorization across api/ and mcp-server/.
    Resolves the user's role via DynamoDB, then checks the permission matrix.

    Args:
        user_id: User identifier (JWT sub).
        deck_id: Target Deck identifier.
        action: The operation being attempted (must be a key in DEFAULT_PERMISSIONS).
        table: boto3 DynamoDB Table resource.

    Returns:
        AccessDecision with allowed, role, deck record, and denial reason.
    """
    role, deck = resolve_role(user_id=user_id, deck_id=deck_id, table=table)

    if not check_permission(role=role, action=action):
        return AccessDecision(
            allowed=False,
            role=role,
            deck=None,
            reason=f"Role '{role}' cannot perform '{action}' on deck '{deck_id}'",
        )

    return AccessDecision(allowed=True, role=role, deck=deck)
