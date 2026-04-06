# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Presentation initialization — creates Deck + specs/ + empty presentation.json in S3."""

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

from typing import Any

from storage import Storage
from tools.deck import create_deck

# Spec files always created on init (empty).
_SPEC_FILES_ALWAYS = ("specs/brief.md", "specs/outline.md")


def init_presentation(
    name: str,
    user_id: str,
    storage: Storage,
) -> dict[str, Any]:
    """Create a Deck, write empty presentation.json and spec files to S3.

    Template is NOT set at init time — it is selected later during the
    design workflow and written to the deck via run_python / analyze_template.

    Args:
        name: Presentation name (used as Deck display name).
        user_id: Owner's user ID.
        storage: Storage backend instance.

    Returns:
        Dict with deckId and workspace file list.
    """
    # Create deck META in DDB
    deck = create_deck(name=name, user_id=user_id, storage=storage)
    deck_id = deck["deckId"]

    # Write empty presentation.json to S3
    presentation: dict[str, Any] = {"slides": []}
    storage.put_presentation_json(deck_id=deck_id, data=presentation)

    workspace = ["presentation.json"]

    # Always create brief.md and outline.md
    for spec_file in _SPEC_FILES_ALWAYS:
        key = f"decks/{deck_id}/{spec_file}"
        storage.upload_file(key=key, data=b"", content_type="text/markdown")
        workspace.append(spec_file)

    return {
        "deckId": deck_id,
        "name": name,
        "workspace": workspace,
    }
