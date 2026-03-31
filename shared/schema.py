# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""DynamoDB key schema constants.

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

Single source of truth for PK/SK patterns and GSI configuration.
All DDB access in api/ and mcp-server/ should use these helpers
instead of hardcoding key strings.
"""


# ---------------------------------------------------------------------------
# Primary key helpers
# ---------------------------------------------------------------------------


def deck_pk(user_id: str) -> str:
    """Partition key for a user's deck records.

    Args:
        user_id: User identifier (JWT sub).

    Returns:
        PK string in format USER#{user_id}.
    """
    return f"USER#{user_id}"


def deck_sk(deck_id: str) -> str:
    """Sort key for a specific deck.

    Args:
        deck_id: Deck identifier.

    Returns:
        SK string in format DECK#{deck_id}.
    """
    return f"DECK#{deck_id}"


def shared_pk(user_id: str) -> str:
    """Partition key for shared deck access records.

    Args:
        user_id: User identifier of the collaborator.

    Returns:
        PK string in format SHARED#{user_id}.
    """
    return f"SHARED#{user_id}"


def fav_sk(deck_id: str) -> str:
    """Sort key for a favorite record.

    Args:
        deck_id: Deck identifier.

    Returns:
        SK string in format FAV#{deck_id}.
    """
    return f"FAV#{deck_id}"


def template_pk(template_id: str) -> str:
    """Partition key for a template record.

    Args:
        template_id: Template identifier.

    Returns:
        PK string in format TEMPLATE#{template_id}.
    """
    return f"TEMPLATE#{template_id}"


def upload_sk(upload_id: str) -> str:
    """Sort key for an upload record.

    Args:
        upload_id: Upload identifier.

    Returns:
        SK string in format UPLOAD#{upload_id}.
    """
    return f"UPLOAD#{upload_id}"


# ---------------------------------------------------------------------------
# Key prefix constants (for begins_with queries)
# ---------------------------------------------------------------------------

DECK_SK_PREFIX = "DECK#"
FAV_SK_PREFIX = "FAV#"
TEMPLATE_PK_PREFIX = "TEMPLATE#"
UPLOAD_SK_PREFIX = "UPLOAD#"


# ---------------------------------------------------------------------------
# GSI constants
# ---------------------------------------------------------------------------

GSI_PUBLIC_DECKS = "PublicDecks"
GSI1PK = "GSI1PK"
GSI1SK = "GSI1SK"


def public_gsi1pk() -> str:
    """GSI1PK value for public decks.

    Returns:
        GSI1PK string VISIBILITY#public.
    """
    return "VISIBILITY#public"


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def extract_deck_id(sk: str) -> str:
    """Extract deck_id from a DECK# sort key.

    Args:
        sk: Sort key string (e.g. DECK#abc123).

    Returns:
        The deck_id portion.
    """
    return sk.replace(DECK_SK_PREFIX, "")


def extract_fav_id(sk: str) -> str:
    """Extract deck_id from a FAV# sort key.

    Args:
        sk: Sort key string (e.g. FAV#abc123).

    Returns:
        The deck_id portion.
    """
    return sk.replace(FAV_SK_PREFIX, "")



