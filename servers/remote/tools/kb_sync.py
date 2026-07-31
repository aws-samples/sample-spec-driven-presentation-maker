# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Knowledge Base vector synchronization — uses Titan Embed V2 for embeddings.

Embedding vectors are generated via Amazon Bedrock and stored in S3 Vectors.

Knowledge Base vector synchronization — embed slides and sync to S3 Vectors.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

Standalone class (not part of Storage ABC) because KB is an optional feature.
Uses Amazon Titan Embed V2 for embeddings, S3 Vectors for storage, Amazon Bedrock Retrieve for search.
"""

import json
import logging
import time
from typing import Any

logger = logging.getLogger("sdpm.mcp.kb_sync")


EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSION = 1024


class KBSync:
    """Sync slide vectors to S3 Vectors and search via Amazon Bedrock KB.

    Args:
        kb_id: Amazon Bedrock Knowledge Base ID.
        vector_bucket_name: S3 Vector Bucket name.
        vector_index_name: S3 Vector Index name.
        region: AWS region.
    """

    def __init__(
        self,
        kb_id: str,
        vector_bucket_name: str,
        vector_index_name: str,
        region: str,
    ) -> None:
        import boto3

        self._kb_id = kb_id
        self._vector_bucket_name = vector_bucket_name
        self._vector_index_name = vector_index_name
        self._bedrock_runtime = boto3.client("bedrock-runtime", region_name=region)
        self._bedrock_agent = boto3.client("bedrock-agent-runtime", region_name=region)
        self._s3vectors = boto3.client("s3vectors", region_name=region)

    def _embed(self, text: str) -> list[float]:
        """Generate embedding vector using Amazon Titan Text Embeddings V2.

        Args:
            text: Input text to embed.

        Returns:
            List of floats representing the embedding vector.
        """
        resp = self._bedrock_runtime.invoke_model(
            modelId=EMBEDDING_MODEL_ID,
            body=json.dumps({
                "inputText": text,
                "dimensions": EMBEDDING_DIMENSION,
            }),
        )
        body = json.loads(resp["body"].read())
        embedding = body.get("embedding")
        if not embedding:
            raise ValueError("Empty embedding returned from model")
        return embedding

    def _extract_text_from_elements(self, elements: list[dict]) -> str:
        """Recursively extract text content from slide elements.

        Args:
            elements: List of slide element dicts.

        Returns:
            Concatenated text content.
        """
        parts: list[str] = []
        for el in elements:
            if isinstance(el.get("text"), str):
                parts.append(el["text"])
            elif isinstance(el.get("text"), dict):
                parts.append(el["text"].get("text", ""))
            # Recurse into children (groups, etc.)
            if isinstance(el.get("elements"), list):
                parts.append(self._extract_text_from_elements(el["elements"]))
        return " ".join(p for p in parts if p)

    def _build_notes_text(
        self,
        slide: dict,
        deck_name: str,
        page_number: int,
    ) -> str:
        """Build text for the notes/content vector.

        Args:
            slide: Slide dict from presentation.json.
            deck_name: Deck display name.
            page_number: 1-based page number.

        Returns:
            Formatted text for embedding, or empty string if no content.
        """
        title = slide.get("title", "")
        if isinstance(title, dict):
            title = title.get("text", "")
        notes = slide.get("notes", "")
        elements_text = self._extract_text_from_elements(
            slide.get("elements", []),
        )

        if not notes and not title and not elements_text:
            return ""

        parts = [f"# {deck_name} - Page {page_number}: {title}", ""]
        if notes:
            parts.extend([notes, ""])
        if elements_text:
            parts.extend(["---", f"Slide text: {elements_text}"])
        return "\n".join(parts)

    def _build_metadata(
        self,
        deck_id: str,
        slide_id: str,
        slide_index: int,
        user_id: str,
        deck_name: str,
        visibility: str,
        layout_name: str,
    ) -> dict[str, Any]:
        """Build filterable metadata for a vector.

        Args:
            deck_id: Deck identifier.
            slide_id: Slide identifier from presentation.json (e.g. "slide_01").
            slide_index: 0-based slide index.
            user_id: Author's user ID.
            deck_name: Deck display name.
            visibility: "private" or "public".
            layout_name: Slide layout name.

        Returns:
            Flat dict of filterable metadata.
        """
        return {
            "deckId": deck_id,
            "slideId": slide_id,
            "author": user_id,
            "visibility": visibility,
            "pageNumber": slide_index + 1,
            "deckName": deck_name,
            "layoutName": layout_name,
            "updatedAt": int(time.time()),
        }

    def sync_deck(
        self,
        deck_id: str,
        user_id: str,
        deck_name: str,
        visibility: str,
        slides: list[dict],
    ) -> None:
        """Full sync: delete existing vectors, embed all slides, put_vectors.

        Args:
            deck_id: Deck identifier.
            user_id: Author's user ID.
            deck_name: Deck display name.
            visibility: "private" or "public".
            slides: List of slide dicts from presentation.json.
        """
        # Delete existing vectors for this deck
        self._delete_keys_for_slides(
            deck_id=deck_id, slides=slides,
        )

        # Build vectors
        vectors: list[dict] = []
        for i, slide in enumerate(slides):
            slide_id = slide.get("id") or f"slide_{i + 1:02d}"
            layout = slide.get("layout", "")
            metadata = self._build_metadata(
                deck_id=deck_id,
                slide_id=slide_id,
                slide_index=i,
                user_id=user_id,
                deck_name=deck_name,
                visibility=visibility,
                layout_name=layout,
            )

            # Notes vector
            notes_text = self._build_notes_text(
                slide=slide, deck_name=deck_name, page_number=i + 1,
            )
            if notes_text:
                embedding = self._embed(notes_text)
                vectors.append({
                    "key": f"{deck_id}/{slide_id}",
                    "data": {"float32": embedding},
                    "metadata": {**metadata, "AMAZON_BEDROCK_TEXT": notes_text},
                })

            # Design vector
            design_desc = slide.get("design_description", "")
            if design_desc:
                embedding = self._embed(design_desc)
                vectors.append({
                    "key": f"{deck_id}/{slide_id}_design",
                    "data": {"float32": embedding},
                    "metadata": {
                        **metadata,
                        "AMAZON_BEDROCK_TEXT": design_desc,
                    },
                })

        # put_vectors in batches of 500
        for batch_start in range(0, len(vectors), 500):
            batch = vectors[batch_start:batch_start + 500]
            self._s3vectors.put_vectors(
                vectorBucketName=self._vector_bucket_name,
                indexName=self._vector_index_name,
                vectors=batch,
            )

    def delete_deck_vectors(self, deck_id: str, slides: list[dict]) -> None:
        """Delete all vectors for a deck.

        Args:
            deck_id: Deck identifier.
            slides: Slide dicts (need "id" field for key construction).
        """
        self._delete_keys_for_slides(deck_id=deck_id, slides=slides)

    def _delete_keys_for_slides(self, deck_id: str, slides: list[dict]) -> None:
        """Delete notes + design vector keys for a deck's slides.

        Args:
            deck_id: Deck identifier.
            slides: Slide dicts from presentation.json.
        """
        keys: list[str] = []
        for i, slide in enumerate(slides):
            slide_id = slide.get("id") or f"slide_{i + 1:02d}"
            keys.append(f"{deck_id}/{slide_id}")
            keys.append(f"{deck_id}/{slide_id}_design")

        # delete_vectors accepts max 500 keys per call
        for batch_start in range(0, len(keys), 500):
            batch = keys[batch_start:batch_start + 500]
            try:
                self._s3vectors.delete_vectors(
                    vectorBucketName=self._vector_bucket_name,
                    indexName=self._vector_index_name,
                    keys=batch,
                )
            except Exception as e:
                logger.warning("delete_vectors failed: %s", e)

    def search(
        self,
        query: str,
        user_id: str,
        scope: str = "mine",
        deck_name: str = "",
        layout: str = "",
        days: int = 0,
    ) -> list[dict]:
        """Search slides via Amazon Bedrock Retrieve API with metadata filters.

        Args:
            query: Natural language search query.
            user_id: Current user's ID.
            scope: "mine" | "public" | "all".
            deck_name: Partial match filter on deck name (stringContains).
            layout: Exact match filter on layout name.
            days: Date range filter (0=all time, N=last N days).

        Returns:
            List of result dicts with deckId, slideId, pageNumber, score, excerpt.
        """
        # Build scope filter
        if scope == "mine":
            scope_filter: dict = {"equals": {"key": "author", "value": user_id}}
        elif scope == "public":
            scope_filter = {"equals": {"key": "visibility", "value": "public"}}
        else:  # "all"
            scope_filter = {
                "orAll": [
                    {"equals": {"key": "author", "value": user_id}},
                    {"equals": {"key": "visibility", "value": "public"}},
                ],
            }

        # Combine filters with AND
        filters: list[dict] = [scope_filter]

        if deck_name:
            filters.append({
                "stringContains": {"key": "deckName", "value": deck_name},
            })
        if layout:
            filters.append({"equals": {"key": "layoutName", "value": layout}})
        if days > 0:
            cutoff = int(time.time()) - (days * 86400)
            filters.append({
                "greaterThanOrEquals": {"key": "updatedAt", "value": cutoff},
            })

        # Wrap in andAll if multiple filters
        final_filter = filters[0] if len(filters) == 1 else {"andAll": filters}

        response = self._bedrock_agent.retrieve(
            knowledgeBaseId=self._kb_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": 20,
                    "filter": final_filter,
                },
            },
        )

        results: list[dict] = []
        for r in response.get("retrievalResults", []):
            meta = r.get("metadata", {})
            results.append({
                "deckId": meta.get("deckId", ""),
                "deckName": meta.get("deckName", ""),
                "slideId": meta.get("slideId", ""),
                "pageNumber": int(meta.get("pageNumber", 0)),
                "layoutName": meta.get("layoutName", ""),
                "score": r.get("score", 0),
                "excerpt": r.get("content", {}).get("text", "")[:200],
            })

        # Deduplicate by (deckId, slideId) — keep highest score
        seen: dict[tuple[str, str], int] = {}
        for idx, r in enumerate(results):
            key = (r["deckId"], r["slideId"])
            if key not in seen or results[seen[key]]["score"] < r["score"]:
                seen[key] = idx

        return [results[i] for i in sorted(seen.values())]
