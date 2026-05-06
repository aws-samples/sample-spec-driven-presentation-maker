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

    # --- Deck JSON (split format) ---

    def get_deck_json(self, deck_id: str) -> dict:
        """Read deck.json from S3 pptx bucket."""
        key = f"decks/{deck_id}/deck.json"
        try:
            resp = self._s3.get_object(Bucket=self._pptx_bucket, Key=key)
            return json.loads(resp["Body"].read())
        except self._s3.exceptions.NoSuchKey:
            raise ValueError(f"deck.json not found for deck {deck_id}")

    def put_deck_json(self, deck_id: str, data: dict) -> None:
        """Write deck.json to S3 pptx bucket."""
        key = f"decks/{deck_id}/deck.json"
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self._s3.put_object(
            Bucket=self._pptx_bucket, Key=key, Body=body,
            ContentType="application/json",
        )

    def get_slide_json(self, deck_id: str, slug: str) -> dict:
        """Read slides/{slug}.json from S3 pptx bucket."""
        key = f"decks/{deck_id}/slides/{slug}.json"
        try:
            resp = self._s3.get_object(Bucket=self._pptx_bucket, Key=key)
            return json.loads(resp["Body"].read())
        except self._s3.exceptions.NoSuchKey:
            raise ValueError(f"slides/{slug}.json not found for deck {deck_id}")

    def put_slide_json(self, deck_id: str, slug: str, data: dict) -> None:
        """Write slides/{slug}.json to S3 pptx bucket."""
        key = f"decks/{deck_id}/slides/{slug}.json"
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self._s3.put_object(
            Bucket=self._pptx_bucket, Key=key, Body=body,
            ContentType="application/json",
        )

    # --- Template ---

    def list_templates(self) -> list[dict]:
        """List builtin templates. S3 is source of truth for existence, DDB is metadata cache."""
        # S3: what exists
        resp = self._s3.list_objects_v2(Bucket=self._resource_bucket, Prefix="templates/")
        s3_templates = {}
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".pptx"):
                name = key.removeprefix("templates/").removesuffix(".pptx")
                s3_templates[name] = {"s3Key": key, "s3ETag": obj["ETag"]}

        if not s3_templates:
            return []

        # DDB: cached metadata
        keys = [{"PK": f"TEMPLATE#{n}", "SK": "META"} for n in s3_templates]
        ddb_resp = self._table.meta.client.batch_get_item(
            RequestItems={self._table.name: {"Keys": keys}}
        )
        ddb_cache = {}
        for item in ddb_resp.get("Responses", {}).get(self._table.name, []):
            ddb_cache[item["name"]] = item

        # Merge: S3 existence + DDB metadata
        results = []
        for name, s3_info in s3_templates.items():
            cached = ddb_cache.get(name, {})
            results.append({
                "name": name,
                "s3Key": s3_info["s3Key"],
                "description": cached.get("description", ""),
                "fonts": cached.get("fonts", {}),
                "analysisJson": cached.get("analysisJson", "{}") if cached.get("s3ETag") == s3_info["s3ETag"] else "{}",
            })
        return results

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

    # --- Style Pins ---

    def get_style_pins(self, user_id: str) -> list[str]:
        """Get pinned style names from DDB."""
        resp = self._table.get_item(Key={"PK": f"USER#{user_id}", "SK": "STYLE_PINS"})
        item = resp.get("Item")
        if not item:
            return []
        return item.get("pinned_styles", [])

    def put_style_pins(self, user_id: str, pins: list[str]) -> None:
        """Save pinned style names to DDB."""
        self._table.put_item(Item={
            "PK": f"USER#{user_id}",
            "SK": "STYLE_PINS",
            "pinned_styles": pins,
        })

    # --- User Templates ---

    def list_user_templates(self, user_id: str) -> list[dict]:
        """List user templates from DDB."""
        resp = self._table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
            ExpressionAttributeValues={":pk": f"USER#{user_id}", ":prefix": "TEMPLATE#"},
        )
        return resp.get("Items", [])

    def get_user_template_metadata(self, user_id: str, name: str) -> dict | None:
        """Get single user template metadata."""
        resp = self._table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"TEMPLATE#{name}"})
        return resp.get("Item")

    def put_user_template(self, user_id: str, name: str, data: bytes, metadata: dict) -> None:
        """Upload user template to S3 and metadata to DDB."""
        s3_key = f"user-templates/{user_id}/{name}.pptx"
        self._s3.put_object(Bucket=self._pptx_bucket, Key=s3_key, Body=data)
        self._table.put_item(Item={
            "PK": f"USER#{user_id}",
            "SK": f"TEMPLATE#{name}",
            "name": name,
            "s3Key": s3_key,
            **metadata,
        })

    def delete_user_template(self, user_id: str, name: str) -> None:
        """Delete user template from S3 and DDB."""
        s3_key = f"user-templates/{user_id}/{name}.pptx"
        self._s3.delete_object(Bucket=self._pptx_bucket, Key=s3_key)
        self._table.delete_item(Key={"PK": f"USER#{user_id}", "SK": f"TEMPLATE#{name}"})

    def download_user_template(self, user_id: str, name: str) -> bytes:
        """Download user template from S3."""
        s3_key = f"user-templates/{user_id}/{name}.pptx"
        resp = self._s3.get_object(Bucket=self._pptx_bucket, Key=s3_key)
        return resp["Body"].read()

    def rename_user_template(self, user_id: str, old_name: str, new_name: str) -> None:
        """Rename user template (copy S3 + update DDB + delete old)."""
        old_key = f"user-templates/{user_id}/{old_name}.pptx"
        new_key = f"user-templates/{user_id}/{new_name}.pptx"
        # Copy S3 object
        self._s3.copy_object(
            Bucket=self._pptx_bucket,
            CopySource={"Bucket": self._pptx_bucket, "Key": old_key},
            Key=new_key,
        )
        self._s3.delete_object(Bucket=self._pptx_bucket, Key=old_key)
        # Move DDB item
        old_item = self._table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"TEMPLATE#{old_name}"}).get("Item", {})
        self._table.delete_item(Key={"PK": f"USER#{user_id}", "SK": f"TEMPLATE#{old_name}"})
        old_item["SK"] = f"TEMPLATE#{new_name}"
        old_item["name"] = new_name
        old_item["s3Key"] = new_key
        self._table.put_item(Item=old_item)

    def update_user_template_metadata(self, user_id: str, name: str, updates: dict) -> None:
        """Update fields in user template DDB item."""
        expr_parts = []
        attr_values = {}
        attr_names = {}
        for i, (k, v) in enumerate(updates.items()):
            alias = f"#k{i}"
            val_alias = f":v{i}"
            expr_parts.append(f"{alias} = {val_alias}")
            attr_names[alias] = k
            attr_values[val_alias] = v
        self._table.update_item(
            Key={"PK": f"USER#{user_id}", "SK": f"TEMPLATE#{name}"},
            UpdateExpression="SET " + ", ".join(expr_parts),
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
        )

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
