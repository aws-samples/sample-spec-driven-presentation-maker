# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""User resources (styles, templates) — MCP tool implementations.

Mirrors the API layer logic for agent consumption via MCP.
"""

from datetime import datetime, timezone
from typing import Any

from shared.resources import (
    resource_s3_key,
    resource_pk,
    resource_sk,
    sk_prefix,
    extract_name,
    is_valid_name,
)
from storage import Storage


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_user_style(
    name: str,
    description: str,
    html: str,
    user_id: str,
    storage: Storage,
) -> dict[str, Any]:
    """Save (create or update) a user style.

    Args:
        name: Style name (alphanumeric, dash, underscore; 1-64 chars).
        description: Short description.
        html: Full style HTML.
        user_id: Owner's user id.
        storage: Storage backend.

    Returns:
        Dict with name and savedAt.
    """
    if not is_valid_name(name):
        raise ValueError(f"Invalid style name: {name!r}")
    if not html:
        raise ValueError("html is required")

    key = resource_s3_key("user", user_id, "styles", name)
    storage.upload_file(key=key, data=html.encode("utf-8"), content_type="text/html")

    now = _now_iso()
    table = storage.table
    existing = table.get_item(
        Key={"PK": resource_pk("user", user_id), "SK": resource_sk("styles", name)}
    ).get("Item") or {}
    item = {
        "PK": resource_pk("user", user_id),
        "SK": resource_sk("styles", name),
        "name": name,
        "description": description,
        "s3Key": key,
        "createdBy": existing.get("createdBy", user_id),
        "createdAt": existing.get("createdAt", now),
        "updatedBy": user_id,
        "updatedAt": now,
    }
    table.put_item(Item=item)
    return {"name": name, "savedAt": now}


def list_user_styles(user_id: str, storage: Storage) -> dict[str, Any]:
    """List user's styles (name + description only)."""
    from boto3.dynamodb.conditions import Key
    resp = storage.table.query(
        KeyConditionExpression=Key("PK").eq(resource_pk("user", user_id))
        & Key("SK").begins_with(sk_prefix("styles")),
    )
    return {
        "styles": [
            {
                "name": extract_name(item["SK"], "styles"),
                "description": item.get("description", ""),
            }
            for item in resp.get("Items", [])
        ]
    }


def delete_user_style(name: str, user_id: str, storage: Storage) -> dict[str, Any]:
    """Delete a user style."""
    if not is_valid_name(name):
        raise ValueError(f"Invalid style name: {name!r}")
    key = resource_s3_key("user", user_id, "styles", name)
    try:
        storage._s3.delete_object(Bucket=storage.pptx_bucket, Key=key)  # noqa: SLF001
    except Exception:
        pass
    storage.table.delete_item(
        Key={"PK": resource_pk("user", user_id), "SK": resource_sk("styles", name)}
    )
    return {"deleted": name}
