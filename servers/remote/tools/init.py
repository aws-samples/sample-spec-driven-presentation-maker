# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Presentation initialization — creates Deck + deck.json + specs/ in S3."""

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

from typing import Any

from storage import Storage
from tools.deck import create_deck

# Spec files always created on init (empty).
_SPEC_FILES_ALWAYS = ("specs/brief.md", "specs/outline.md")


def init_deck_workspace(
    name: str,
    user_id: str,
    storage: Storage,
    output_format: str = "pptx",
) -> dict[str, Any]:
    """Create a Deck, write deck.json and spec files to S3.

    Template is NOT set at init time — it is selected later during the
    design workflow and written to deck.json via run_python / analyze_template.

    Args:
        name: Presentation name (used as Deck display name).
        user_id: Owner's user ID.
        storage: Storage backend instance.
        output_format: "pptx" (default) or "html"; deck.json gets
            ``"outputFormat": "html"`` only for HTML decks.

    Returns:
        Dict with deckId and workspace file list; ``format_notes`` (the orchestrator's
        notes for the format, ``sdpm.entry.format_notes``) for an HTML deck.

    Raises:
        ValueError: output_format is neither "pptx" nor "html" (nothing is created).
    """
    from sdpm.engine.schema import new_deck_json
    from sdpm.entry import format_notes

    # Validate before creating anything.
    deck_json: dict[str, Any] = new_deck_json(output_format)

    # Create deck META in DDB
    deck = create_deck(name=name, user_id=user_id, storage=storage)
    deck_id = deck["deckId"]

    # Write the shared deck.json skeleton to S3.
    storage.put_deck_json(deck_id=deck_id, data=deck_json)

    workspace = ["deck.json"]

    # Always create brief.md and outline.md
    for spec_file in _SPEC_FILES_ALWAYS:
        key = f"decks/{deck_id}/{spec_file}"
        storage.upload_file(key=key, data=b"", content_type="text/markdown")
        workspace.append(spec_file)

    result: dict[str, Any] = {
        "deckId": deck_id,
        "name": name,
        "workspace": workspace,
    }
    notes = format_notes(output_format)
    if notes:
        result["format_notes"] = notes
    return result
