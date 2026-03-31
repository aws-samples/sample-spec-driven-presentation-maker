# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Deck CRUD operations via Storage ABC.

Access control is enforced at the storage layer — users can only access their own decks
or decks explicitly shared with them. See shared/authz.py for authorization logic.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

After S3 JSON migration, only deck META operations remain.
Slide data lives in S3 presentation.json, edited by the agent directly.
"""

import uuid
from datetime import datetime, timezone

from storage import Storage


def _now_iso() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def create_deck(
    name: str,
    user_id: str,
    storage: Storage,
    tags: list[str] | None = None,
) -> dict:
    """Create a new empty Deck (META only).

    Args:
        name: Display name for the deck (1-200 characters).
        user_id: Owner's user ID (from Runtime header).
        storage: Storage backend instance.
        tags: Optional list of tags for categorization (max 10, each max 50 chars).

    Returns:
        Dict with deckId and name.

    Raises:
        ValueError: If name is empty or too long, or tags are invalid.
    """
    if not name or not name.strip():
        raise ValueError("Deck name cannot be empty.")
    if len(name) > 200:
        raise ValueError("Deck name cannot exceed 200 characters.")
    if tags:
        if len(tags) > 10:
            raise ValueError("Maximum 10 tags allowed.")
        for tag in tags:
            if len(tag) > 50:
                raise ValueError(f"Tag '{tag[:20]}...' exceeds 50 characters.")
    deck_id = str(uuid.uuid4())[:8]
    now = _now_iso()

    storage.put_deck(deck_id=deck_id, user_id=user_id, meta={
        "name": name,
        "tags": tags or [],
        "createdBy": user_id,
        "createdAt": now,
        "updatedAt": now,
    })

    return {"deckId": deck_id, "name": name}
