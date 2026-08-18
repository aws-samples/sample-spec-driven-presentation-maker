# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""DynamoDB key schema constants.

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

Single source of truth for PK/SK patterns and GSI configuration.
All DDB access in api/ and servers/remote/ should use these helpers
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


# ---------------------------------------------------------------------------
# Key prefix constants (for begins_with queries)
# ---------------------------------------------------------------------------

DECK_SK_PREFIX = "DECK#"
FAV_SK_PREFIX = "FAV#"
TEMPLATE_PK_PREFIX = "TEMPLATE#"


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


# ---------------------------------------------------------------------------
# Item builders
# ---------------------------------------------------------------------------


def theme_hints_ddb_item(theme_hints: dict | None) -> dict:
    """Build the DynamoDB ``themeHints`` attribute from a ConversionResult.

    Tolerates ``theme_hints=None`` (shared.ingest continues with a warning
    when theme extraction fails) so a successful conversion is never
    reported as failed. DynamoDB rejects native floats, so
    ``backgroundLuminance`` is round-tripped via ``str(Decimal)``.

    Args:
        theme_hints: ``ConversionResult.theme_hints`` — may be None.

    Returns:
        Dict with backgroundLuminance (Decimal | None), accentColors, fonts.
    """
    from decimal import Decimal

    hints = theme_hints or {}
    bg_lum = hints.get("backgroundLuminance")
    return {
        "backgroundLuminance": Decimal(str(bg_lum)) if bg_lum is not None else None,
        "accentColors": hints.get("accentColors", []),
        "fonts": hints.get("fonts", {}),
    }



