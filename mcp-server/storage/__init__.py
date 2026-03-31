# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Storage abstraction — defines the interface that tools/ depend on.

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

Implementation:
- AwsStorage: DynamoDB + S3 (Layer 3-4)
"""

from abc import ABC, abstractmethod
from typing import Any, Optional  # noqa: F401 — Any used by subclasses


class Storage(ABC):
    """Abstract storage backend for spec-driven-presentation-maker."""

    # --- Deck META ---

    @abstractmethod
    def put_deck(self, deck_id: str, user_id: str, meta: dict) -> None:
        """Store deck metadata."""

    @abstractmethod
    def get_deck(self, deck_id: str, user_id: str) -> Optional[dict]:
        """Get deck metadata. Returns None if not found."""

    @abstractmethod
    def update_deck(self, deck_id: str, user_id: str, updates: dict) -> None:
        """Partial update of deck metadata."""

    # --- Presentation JSON (S3) ---

    @abstractmethod
    def get_presentation_json(self, deck_id: str) -> dict:
        """Read presentation.json from S3.

        Args:
            deck_id: Deck identifier.

        Returns:
            Parsed presentation dict with slides, fonts, theme.

        Raises:
            ValueError: If presentation.json not found.
        """

    @abstractmethod
    def put_presentation_json(self, deck_id: str, data: dict) -> None:
        """Write presentation.json to S3.

        Args:
            deck_id: Deck identifier.
            data: Presentation dict (Layer 1 compatible).
        """

    # --- Template ---

    @abstractmethod
    def list_templates(self) -> list[dict]:
        """List all templates."""

    # --- File I/O ---

    @abstractmethod
    def download_file(self, key: str) -> bytes:
        """Download a file from resource bucket."""

    @abstractmethod
    def download_file_from_pptx_bucket(self, key: str) -> bytes:
        """Download a file from pptx bucket (decks, includes, output).

        Args:
            key: S3 key in pptx bucket.

        Returns:
            File content as bytes.
        """

    @abstractmethod
    def upload_file(self, key: str, data: bytes, content_type: str = "") -> None:
        """Upload a file to pptx bucket."""

    @abstractmethod
    def presign_url(self, key: str, expires: int = 3600) -> str:
        """Generate a presigned URL for pptx bucket."""

    # --- Listing ---

    @abstractmethod
    def list_files(self, prefix: str, bucket: str = "") -> list[str]:
        """List file keys under a prefix."""

    # --- Deletion ---

    @abstractmethod
    def delete_files(self, prefix: str, bucket: str = "") -> int:
        """Delete all objects under a prefix.

        Args:
            prefix: S3 key prefix to delete under.
            bucket: Bucket name. Defaults to pptx_bucket.

        Returns:
            Number of objects deleted.
        """

    # --- PNG Job ---

    def send_png_job(self, message: dict) -> None:
        """Send PNG generation job to SQS. No-op if queue not configured.

        Args:
            message: Dict with deckId, userId, bucket, key.
        """

    # --- Auth ---

    @property
    def table(self) -> Any:
        """DynamoDB Table resource for authorization queries.

        Returns:
            boto3 DynamoDB Table resource.
        """
        raise NotImplementedError("Subclass must expose DDB table for authz")

    def deck_exists(self, deck_id: str, user_id: str) -> bool:
        """Check if user owns the deck.

        Args:
            deck_id: Deck identifier.
            user_id: User identifier.

        Returns:
            True if deck exists and is owned by user.
        """
        return self.get_deck(deck_id, user_id) is not None
