# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The user's style and template library in the cloud (S3 + DynamoDB).

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

Shared by the REST API Lambda (api/index.py) and the MCP Runtime
(servers/remote: AwsStorage and tools). Every function takes the boto3 S3
client / DynamoDB Table it works on, so each runtime keeps its own client
lifecycle. DynamoDB keys come from :mod:`shared.schema`; the S3 object layout
is defined here. Rules that are not about storage — the ``<title>``
description and the user-over-bundled shadowing — come from the engine
(:mod:`sdpm.knowledge.reference`).

S3 layout:
  pptx bucket      user-styles/{user_id}/{name}.html
                   user-templates/{user_id}/{name}.pptx
  resource bucket  references/examples/styles/{name}.html  (bundled styles)
                   templates/{name}.pptx                    (builtin templates)
                   assets/{source}/{file}                   (icon catalog)
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from shared.schema import (
    BUILTIN_NOTE_SK_PREFIX,
    USER_TEMPLATE_SK_PREFIX,
    builtin_template_key,
    style_pins_key,
    user_pk,
)

BUILTIN_STYLES_PREFIX = "references/examples/styles/"
BUILTIN_TEMPLATES_PREFIX = "templates/"
ASSETS_PREFIX = "assets/"

_STYLE_NAME_RE = re.compile(r"[a-zA-Z0-9_-]+")


# ---------------------------------------------------------------------------
# Names and S3 keys
# ---------------------------------------------------------------------------


def is_valid_style_name(name: object) -> bool:
    """Whether *name* is a valid style name (letters, digits, ``_`` and ``-``)."""
    return isinstance(name, str) and _STYLE_NAME_RE.fullmatch(name) is not None


def user_styles_prefix(user_id: str) -> str:
    """S3 prefix of the user's styles in the pptx bucket."""
    return f"user-styles/{user_id}/"


def user_style_key(user_id: str, name: str) -> str:
    """S3 key of a user style in the pptx bucket."""
    return f"{user_styles_prefix(user_id)}{name}.html"


def builtin_style_key(name: str) -> str:
    """S3 key of a bundled style in the resource bucket."""
    return f"{BUILTIN_STYLES_PREFIX}{name}.html"


def user_template_s3_key(user_id: str, name: str) -> str:
    """S3 key of a user template in the pptx bucket."""
    return f"user-templates/{user_id}/{name}.pptx"


def builtin_template_s3_key(name: str) -> str:
    """S3 key of a builtin template in the resource bucket."""
    return f"{BUILTIN_TEMPLATES_PREFIX}{name}.pptx"


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------


def _list_keys(s3: Any, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(obj["Key"] for obj in page.get("Contents", []))
    return sorted(keys)


def _list_styles(s3: Any, bucket: str, prefix: str, source: str, include_html: bool) -> list[dict]:
    from sdpm.knowledge.reference import html_title

    styles: list[dict] = []
    for key in _list_keys(s3, bucket, prefix):
        if not key.endswith(".html"):
            continue
        name = key.removeprefix(prefix).removesuffix(".html")
        try:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
        except Exception:
            if include_html:
                raise
            body = ""
        entry = {"name": name, "description": html_title(body), "source": source}
        if include_html:
            entry["html"] = body
        styles.append(entry)
    return styles


def list_builtin_styles(s3: Any, resource_bucket: str, *, include_html: bool = True) -> list[dict]:
    """List the bundled styles uploaded to the resource bucket, sorted by name.

    Returns:
        ``[{name, description, source: "builtin"[, html]}]``. With *include_html*
        a style whose body cannot be read raises; without it the description is
        left empty.
    """
    return _list_styles(s3, resource_bucket, BUILTIN_STYLES_PREFIX, "builtin", include_html)


def list_user_styles(s3: Any, pptx_bucket: str, user_id: str, *, include_html: bool = False) -> list[dict]:
    """List the user's styles in the pptx bucket, sorted by name.

    Returns:
        ``[{name, description, source: "user"[, html]}]``. With *include_html*
        a style whose body cannot be read raises; without it the description is
        left empty.
    """
    return _list_styles(s3, pptx_bucket, user_styles_prefix(user_id), "user", include_html)


def merge_styles(user_styles: list[dict], builtin_styles: list[dict]) -> list[dict]:
    """One entry per name: the user's style replaces the bundled style of the same name.

    Same rule as the filesystem listing (:func:`sdpm.knowledge.reference.merge_style_lists`).
    """
    from sdpm.knowledge.reference import merge_style_lists

    return merge_style_lists(user_styles, builtin_styles)


# ---------------------------------------------------------------------------
# Icon catalog
# ---------------------------------------------------------------------------

# (resource bucket, icon id) -> SVG bytes, or None when the catalog has no such icon.
# The catalog is static between deploys, so hits and misses live for the container.
_icon_cache: dict[tuple[str, str], bytes | None] = {}
_ICON_CACHE_MAX = 1024
_MISSING_CODES = {"NoSuchKey", "404", "NotFound"}


def _is_missing(exc: Exception) -> bool:
    if isinstance(exc, KeyError):
        return True
    code = getattr(exc, "response", {}).get("Error", {}).get("Code")
    return code in _MISSING_CODES


def load_catalog_icons(s3: Any, resource_bucket: str, ids: Any) -> dict[str, bytes]:
    """Read catalog icons ``assets/<source>/<name>.svg`` from the resource bucket.

    The loader for :func:`sdpm.knowledge.assets.style_icons.inline_style_icons_many`.
    Malformed ids are never queried. Missing icons are left out of the result.
    """
    from sdpm.knowledge.assets.style_icons import is_icon_id

    wanted = sorted({i for i in ids if isinstance(i, str) and is_icon_id(i)})
    pending = [i for i in wanted if (resource_bucket, i) not in _icon_cache]
    if pending:
        if len(_icon_cache) + len(pending) > _ICON_CACHE_MAX:
            _icon_cache.clear()

        def fetch(icon_id: str) -> None:
            try:
                body = s3.get_object(Bucket=resource_bucket, Key=f"{ASSETS_PREFIX}{icon_id}.svg")["Body"].read()
            except Exception as exc:  # noqa: BLE001 — a failed icon is drawn as missing
                if _is_missing(exc):
                    _icon_cache[(resource_bucket, icon_id)] = None
                return
            _icon_cache[(resource_bucket, icon_id)] = body

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(fetch, pending))
    found: dict[str, bytes] = {}
    for icon_id in wanted:
        body = _icon_cache.get((resource_bucket, icon_id))
        if body is not None:
            found[icon_id] = body
    return found


# ---------------------------------------------------------------------------
# Style pins
# ---------------------------------------------------------------------------


def get_style_pins(table: Any, user_id: str) -> list[str]:
    """Pinned style names of the user ([] when nothing was pinned yet)."""
    item = table.get_item(Key=style_pins_key(user_id)).get("Item") or {}
    return item.get("pinned_styles", [])


def put_style_pins(table: Any, user_id: str, pins: list[str]) -> None:
    """Replace the user's pinned style names."""
    table.put_item(Item={**style_pins_key(user_id), "pinned_styles": pins})


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def parse_analysis(raw: Any) -> dict:
    """Decode a stored ``analysisJson`` attribute ({} when absent or empty)."""
    if not raw or raw == "{}":
        return {}
    return json.loads(raw) if isinstance(raw, str) else raw


def list_builtin_templates(s3: Any, table: Any, resource_bucket: str) -> list[dict]:
    """List the builtin templates with their analysis-cache rows.

    S3 decides which templates exist; DynamoDB (``TEMPLATE#{name}`` / ``META``)
    caches their analysis, valid while its ``s3ETag`` matches the object's ETag.

    Returns:
        ``[{name, s3Key, s3ETag, cache, fresh}]`` in S3 listing order: *cache* is
        the cache row ({} when there is none), *fresh* whether it matches the object.
    """
    resp = s3.list_objects_v2(Bucket=resource_bucket, Prefix=BUILTIN_TEMPLATES_PREFIX)
    found: dict[str, tuple[str, str]] = {}
    for obj in resp.get("Contents", []):
        key = obj["Key"]
        if key.endswith(".pptx"):
            name = key.removeprefix(BUILTIN_TEMPLATES_PREFIX).removesuffix(".pptx")
            found[name] = (key, obj["ETag"])
    if not found:
        return []

    ddb_resp = table.meta.client.batch_get_item(
        RequestItems={table.name: {"Keys": [builtin_template_key(n) for n in found]}}
    )
    cache = {item["name"]: item for item in ddb_resp.get("Responses", {}).get(table.name, [])}

    results = []
    for name, (key, etag) in found.items():
        row = cache.get(name, {})
        results.append({
            "name": name,
            "s3Key": key,
            "s3ETag": etag,
            "cache": row,
            "fresh": bool(row) and row.get("s3ETag") == etag,
        })
    return results


def builtin_template_cache_item(name: str, s3_key: str, etag: str, analysis: dict) -> dict:
    """The analysis-cache row written after analysing a builtin template."""
    return {
        **builtin_template_key(name),
        "name": name,
        "s3Key": s3_key,
        "s3ETag": etag,
        "fonts": analysis.get("fonts", {}),
        "analysisJson": json.dumps(analysis, ensure_ascii=False),
    }


def list_builtin_template_notes(table: Any, user_id: str) -> dict[str, str]:
    """The user's notes on builtin templates, by template name."""
    resp = table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={":pk": user_pk(user_id), ":prefix": BUILTIN_NOTE_SK_PREFIX},
    )
    return {
        item["SK"].removeprefix(BUILTIN_NOTE_SK_PREFIX): item.get("description", "")
        for item in resp.get("Items", [])
    }


def list_user_templates(table: Any, user_id: str) -> list[dict]:
    """The user's template records (``TEMPLATE#{name}``), as stored."""
    resp = table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={":pk": user_pk(user_id), ":prefix": USER_TEMPLATE_SK_PREFIX},
    )
    return resp.get("Items", [])
