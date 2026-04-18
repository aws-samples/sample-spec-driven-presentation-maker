# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""User/Organization resources (styles, templates) — scope × type abstraction.

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

S3 key layout:
  user-resources/{userId}/{type}/{name}.{ext}
  org-resources/{orgId}/{type}/{name}.{ext}   (Phase 2)
  references/examples/{type}/{name}.{ext}     (existing, read-only)

DynamoDB:
  PK=USER#{userId}  SK=STYLE#{name} | TEMPLATE#{id}
  PK=ORG#{orgId}    SK=STYLE#{name} | TEMPLATE#{id}   (Phase 2)
"""

from typing import Literal, Optional

Scope = Literal["user", "org", "examples"]
ResourceType = Literal["styles", "templates"]

# Type → (SK prefix, file extension)
_TYPE_META = {
    "styles": ("STYLE#", "html"),
    "templates": ("TEMPLATE#", "pptx"),
}


def sk_prefix(type: ResourceType) -> str:
    """Return SK prefix for the resource type (e.g. 'STYLE#')."""
    return _TYPE_META[type][0]


def file_ext(type: ResourceType) -> str:
    """Return file extension for the resource type (e.g. 'html')."""
    return _TYPE_META[type][1]


def resource_s3_key(scope: Scope, scope_id: str, type: ResourceType, name: str) -> str:
    """Build S3 key for a resource.

    Args:
        scope: "user" | "org" | "examples".
        scope_id: userId for user, orgId for org, empty for examples.
        type: "styles" | "templates".
        name: Resource name (or id for templates).

    Returns:
        S3 key string.
    """
    ext = file_ext(type)
    if scope == "user":
        return f"user-resources/{scope_id}/{type}/{name}.{ext}"
    if scope == "org":
        return f"org-resources/{scope_id}/{type}/{name}.{ext}"
    return f"references/examples/{type}/{name}.{ext}"


def resource_pk(scope: Scope, scope_id: str) -> str:
    """Build DDB PK for user/org scope. Examples scope has no DDB record."""
    if scope == "user":
        return f"USER#{scope_id}"
    if scope == "org":
        return f"ORG#{scope_id}"
    raise ValueError(f"Scope '{scope}' has no DDB record")


def resource_sk(type: ResourceType, name: str) -> str:
    """Build DDB SK for a resource."""
    return f"{sk_prefix(type)}{name}"


def extract_name(sk: str, type: ResourceType) -> str:
    """Extract resource name from SK (e.g. 'STYLE#my-brand' → 'my-brand')."""
    return sk.removeprefix(sk_prefix(type))


def is_valid_name(name: str) -> bool:
    """Validate resource name: alphanumeric, dash, underscore only."""
    import re
    return bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name))
