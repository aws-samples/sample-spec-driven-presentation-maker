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

    # --- Deck JSON (split format) ---

    @abstractmethod
    def get_deck_json(self, deck_id: str) -> dict:
        """Read deck.json (metadata only) from S3.

        Args:
            deck_id: Deck identifier.

        Returns:
            Parsed deck metadata dict (template, fonts, defaultTextColor).

        Raises:
            ValueError: If deck.json not found.
        """

    @abstractmethod
    def put_deck_json(self, deck_id: str, data: dict) -> None:
        """Write deck.json to S3.

        Args:
            deck_id: Deck identifier.
            data: Deck metadata dict.
        """

    @abstractmethod
    def get_slide_json(self, deck_id: str, slug: str) -> dict:
        """Read a single slide JSON from S3.

        Args:
            deck_id: Deck identifier.
            slug: Slide slug (filename without .json).

        Returns:
            Parsed slide dict.

        Raises:
            ValueError: If slide not found.
        """

    @abstractmethod
    def put_slide_json(self, deck_id: str, slug: str, data: dict) -> None:
        """Write a single slide JSON to S3.

        Args:
            deck_id: Deck identifier.
            slug: Slide slug.
            data: Slide dict.
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

    # --- Style Pins ---

    @abstractmethod
    def get_style_pins(self, user_id: str) -> list[str]:
        """Get pinned style names for a user.

        Args:
            user_id: User identifier.

        Returns:
            List of pinned style names.
        """

    @abstractmethod
    def put_style_pins(self, user_id: str, pins: list[str]) -> None:
        """Save pinned style names for a user.

        Args:
            user_id: User identifier.
            pins: List of style names to pin.
        """

    # --- User Templates ---

    @abstractmethod
    def list_user_templates(self, user_id: str) -> list[dict]:
        """List user-uploaded templates metadata from DDB.

        Args:
            user_id: User identifier.

        Returns:
            List of template metadata dicts.
        """

    @abstractmethod
    def get_user_template_metadata(self, user_id: str, name: str) -> dict | None:
        """Get metadata for a single user template.

        Args:
            user_id: User identifier.
            name: Template name (stem).

        Returns:
            Metadata dict or None if not found.
        """

    @abstractmethod
    def put_user_template(self, user_id: str, name: str, data: bytes, metadata: dict) -> None:
        """Upload a user template file and store metadata.

        Args:
            user_id: User identifier.
            name: Template name (stem).
            data: .pptx file bytes.
            metadata: Analysis metadata (description, theme_colors, fonts, etc.).
        """

    @abstractmethod
    def delete_user_template(self, user_id: str, name: str) -> None:
        """Delete a user template (file + metadata).

        Args:
            user_id: User identifier.
            name: Template name (stem).
        """

    @abstractmethod
    def download_user_template(self, user_id: str, name: str) -> bytes:
        """Download a user template .pptx file.

        Args:
            user_id: User identifier.
            name: Template name (stem).

        Returns:
            File content as bytes.
        """

    @abstractmethod
    def rename_user_template(self, user_id: str, old_name: str, new_name: str) -> None:
        """Rename a user template (file + metadata).

        Args:
            user_id: User identifier.
            old_name: Current template name.
            new_name: New template name.
        """

    @abstractmethod
    def update_user_template_metadata(self, user_id: str, name: str, updates: dict) -> None:
        """Update specific fields in user template metadata.

        Args:
            user_id: User identifier.
            name: Template name.
            updates: Fields to update (e.g. {"description": "new desc"}).
        """
