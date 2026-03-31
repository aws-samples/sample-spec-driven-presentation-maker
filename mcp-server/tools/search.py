# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Semantic slide search via Amazon Bedrock Knowledge Base (optional).

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

kb_client is Bedrock-specific and intentionally outside Storage ABC.
"""

from typing import Any

from storage import Storage


def search_slides(
    query: str,
    user_id: str,
    kb_client: Any,
    kb_id: str,
    storage: Storage,
    scope: str = "mine",
) -> dict:
    """Search slides by content using semantic search.

    Args:
        query: Natural language search query.
        user_id: Current user's ID for filtering.
        kb_client: boto3 bedrock-agent-runtime client.
        kb_id: Amazon Bedrock Knowledge Base ID.
        storage: Storage backend instance.
        scope: "mine" for own slides only, "public" for public slides.

    Returns:
        Dict with list of matching slides.
    """
    retrieval_config: dict = {
        "vectorSearchConfiguration": {
            "numberOfResults": 20,
            "filter": {
                "orAll": [
                    {"equals": {"key": "author", "value": user_id}},
                    {"equals": {"key": "visibility", "value": "public"}},
                ],
            },
        }
    }

    response = kb_client.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration=retrieval_config,
    )

    results: list[dict] = []
    for r in response.get("retrievalResults", []):
        meta = r.get("metadata", {})
        deck_id = meta.get("deckId", "")
        slide_id = meta.get("slideId", "")
        page_number = int(meta.get("pageNumber", 0))

        deck_name = _lookup_deck_name(deck_id=deck_id, user_id=user_id, storage=storage)

        results.append({
            "deckId": deck_id,
            "deckName": deck_name,
            "slideId": slide_id,
            "pageNumber": page_number,
            "score": r.get("score", 0),
            "excerpt": r.get("content", {}).get("text", "")[:200],
        })

    # Deduplicate by (deckId, slideId)
    seen: set[tuple[str, str]] = set()
    filtered: list[dict] = []
    for r in results:
        key = (r["deckId"], r["slideId"])
        if key not in seen:
            seen.add(key)
            filtered.append(r)

    return {"results": filtered}


def _lookup_deck_name(deck_id: str, user_id: str, storage: Storage) -> str:
    """Look up deck name from storage.

    Args:
        deck_id: Deck identifier.
        user_id: User identifier.
        storage: Storage backend instance.

    Returns:
        Deck name string, or empty string if not found.
    """
    if not deck_id:
        return ""
    try:
        deck = storage.get_deck(deck_id, user_id)
        return deck.get("name", "") if deck else ""
    except Exception:
        return ""
