# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""AWS storage backend — DynamoDB + S3.

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

Used by Layer 3 (mcp-server) and Layer 4 (agent + web-ui).
Deck metadata in DDB, presentation JSON + includes in S3.
"""

import json
from typing import Any, Optional

from storage import Storage


class AwsStorage(Storage):
    """DynamoDB + S3 storage for production deployment.

    Args:
        table: boto3 DynamoDB Table resource.
        s3_client: boto3 S3 client.
        pptx_bucket: S3 bucket for decks, includes, PPTX output, previews.
        resource_bucket: S3 bucket for templates, assets, references.
    """

    def __init__(
        self,
        table: Any,
        s3_client: Any,
        pptx_bucket: str,
        resource_bucket: str,
    ) -> None:
        self._table = table
        self._s3 = s3_client
        self._pptx_bucket = pptx_bucket
        self._resource_bucket = resource_bucket

    @property
    def pptx_bucket(self) -> str:
        """S3 bucket name for PPTX output and previews."""
        return self._pptx_bucket

    @property
    def table(self) -> Any:
        """DynamoDB Table resource for authorization queries."""
        return self._table

    # --- Deck META ---

    def put_deck(self, deck_id: str, user_id: str, meta: dict) -> None:
        """Store deck metadata in DDB."""
        item = {"PK": f"USER#{user_id}", "SK": f"DECK#{deck_id}", **meta}
        self._table.put_item(Item=item)

    def get_deck(self, deck_id: str, user_id: str) -> Optional[dict]:
        """Get deck metadata from DDB. Returns None if not found."""
        resp = self._table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"DECK#{deck_id}"})
        return resp.get("Item")

    def update_deck(self, deck_id: str, user_id: str, updates: dict) -> None:
        """Partial update of deck metadata in DDB.

        Keys with None values are removed from the item (REMOVE expression).
        All other keys are set (SET expression).

        Args:
            deck_id: Deck identifier.
            user_id: User identifier.
            updates: Dict of attribute names to values. None means remove.
        """
        set_parts = []
        remove_parts = []
        values = {}
        for k, v in updates.items():
            if v is None:
                remove_parts.append(k)
            else:
                set_parts.append(f"{k} = :{k}")
                values[f":{k}"] = v

        expression_parts = []
        if set_parts:
            expression_parts.append("SET " + ", ".join(set_parts))
        if remove_parts:
            expression_parts.append("REMOVE " + ", ".join(remove_parts))

        kwargs: dict = {
            "Key": {"PK": f"USER#{user_id}", "SK": f"DECK#{deck_id}"},
            "UpdateExpression": " ".join(expression_parts),
        }
        if values:
            kwargs["ExpressionAttributeValues"] = values
        self._table.update_item(**kwargs)

    # --- Presentation JSON (S3) ---

    def get_presentation_json(self, deck_id: str) -> dict:
        """Read presentation.json from S3 pptx bucket.

        Args:
            deck_id: Deck identifier.

        Returns:
            Parsed presentation dict.

        Raises:
            ValueError: If presentation.json not found.
        """
        key = f"decks/{deck_id}/presentation.json"
        try:
            resp = self._s3.get_object(Bucket=self._pptx_bucket, Key=key)
            return json.loads(resp["Body"].read())
        except self._s3.exceptions.NoSuchKey:
            raise ValueError(f"presentation.json not found for deck {deck_id}")

    def put_presentation_json(self, deck_id: str, data: dict) -> None:
        """Write presentation.json to S3 pptx bucket.

        Args:
            deck_id: Deck identifier.
            data: Presentation dict (Layer 1 compatible).
        """
        key = f"decks/{deck_id}/presentation.json"
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self._s3.put_object(
            Bucket=self._pptx_bucket, Key=key, Body=body,
            ContentType="application/json",
        )

    # --- Template ---

    def list_templates(self) -> list[dict]:
        """List all templates from DDB."""
        resp = self._table.scan(
            FilterExpression="begins_with(PK, :prefix) AND SK = :sk",
            ExpressionAttributeValues={":prefix": "TEMPLATE#", ":sk": "META"},
        )
        return resp.get("Items", [])

    # --- File I/O ---

    def download_file(self, key: str) -> bytes:
        """Download a file from resource bucket."""
        resp = self._s3.get_object(Bucket=self._resource_bucket, Key=key)
        return resp["Body"].read()

    def download_file_from_pptx_bucket(self, key: str) -> bytes:
        """Download a file from pptx bucket.

        Args:
            key: S3 key in pptx bucket.

        Returns:
            File content as bytes.
        """
        resp = self._s3.get_object(Bucket=self._pptx_bucket, Key=key)
        return resp["Body"].read()

    def upload_file(self, key: str, data: bytes, content_type: str = "") -> None:
        """Upload a file to pptx bucket."""
        extra = {"ContentType": content_type} if content_type else {}
        self._s3.put_object(
            Bucket=self._pptx_bucket, Key=key, Body=data, **extra
        )

    def presign_url(self, key: str, expires: int = 3600) -> str:
        """Generate a presigned URL for pptx bucket."""
        return self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._pptx_bucket, "Key": key},
            ExpiresIn=expires,
        )

    # --- Listing ---

    def list_files(self, prefix: str, bucket: str = "") -> list[str]:
        """List S3 keys under prefix.

        Args:
            prefix: S3 key prefix.
            bucket: Bucket name. Defaults to resource_bucket.

        Returns:
            Sorted list of S3 keys.
        """
        target_bucket = bucket or self._resource_bucket
        keys: list[str] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=target_bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return sorted(keys)

    # --- Auth ---
    # deck_exists is inherited from Storage base class

    # --- Deletion ---

    def delete_files(self, prefix: str, bucket: str = "") -> int:
        """Delete all S3 objects under prefix.

        Args:
            prefix: S3 key prefix.
            bucket: Bucket name. Defaults to pptx_bucket.

        Returns:
            Number of objects deleted.
        """
        target_bucket = bucket or self._pptx_bucket
        keys = self.list_files(prefix=prefix, bucket=target_bucket)
        if not keys:
            return 0
        # S3 delete_objects accepts max 1000 keys per call
        for i in range(0, len(keys), 1000):
            batch = [{"Key": k} for k in keys[i:i + 1000]]
            self._s3.delete_objects(Bucket=target_bucket, Delete={"Objects": batch})
        return len(keys)
