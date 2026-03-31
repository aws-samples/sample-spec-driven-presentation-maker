# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Shared utilities for all Lambda handlers.

Some endpoints invoke AI services (Bedrock). Callers should validate AI-generated content.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

Extracted from deck-api to eliminate duplication across
API Lambda functions.
"""

from datetime import datetime, timezone
from typing import Any


def get_user_id(event: Any) -> str:
    """Extract user ID (Cognito sub) from API Gateway authorizer claims.

    Args:
        event: Powertools current_event with request_context.authorizer.

    Returns:
        Cognito sub string.

    Raises:
        ValueError: If authorizer claims or sub are missing.
    """
    authorizer = event.request_context.authorizer
    claims = (authorizer or {}).get("claims", {})
    sub = claims.get("sub")
    if not sub:
        raise ValueError("Unauthorized: missing user identity")
    return sub


def get_user_alias(event: Any) -> str:
    """Extract user alias (email prefix) from API Gateway authorizer claims.

    Args:
        event: Powertools current_event with request_context.authorizer.

    Returns:
        Alias string (email prefix before @), or empty string if unavailable.
    """
    authorizer = event.request_context.authorizer
    claims = (authorizer or {}).get("claims", {})
    email = claims.get("email", "")
    return email.split("@")[0] if email else ""


def now_iso() -> str:
    """Return current UTC time in ISO 8601 format.

    Returns:
        ISO 8601 formatted timestamp string with UTC timezone.
    """
    return datetime.now(timezone.utc).isoformat()


def presigned_url(s3_client: Any, bucket: str, key: str, expiry: int = 900) -> str:
    """Generate a presigned GET URL for an S3 object.

    Args:
        s3_client: boto3 S3 client.
        bucket: S3 bucket name.
        key: S3 object key.
        expiry: URL validity in seconds. Defaults to 900 (15 minutes).

    Returns:
        Presigned URL string.
    """
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expiry,
    )
