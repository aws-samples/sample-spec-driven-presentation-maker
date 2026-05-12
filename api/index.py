# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unified API Lambda — protected by Cognito authorizer with least-privilege IAM.

IAM roles follow least-privilege: Lambda has scoped access to DynamoDB and S3 only.
Cognito JWT claims are used for user identity and authorization.

Unified API Lambda — deck, upload, chat endpoints.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

Single Lambda with Powertools APIGatewayHttpResolver.
Ported from spec-driven-presentation-maker-web deck-api, upload-api.
"""

import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional

import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, CORSConfig
from aws_lambda_powertools.utilities.typing import LambdaContext
from boto3.dynamodb.conditions import Key
from authz import authorize
from common import get_user_id, now_iso, presigned_url
from shared.schema import (
    deck_pk, deck_sk, shared_pk, fav_sk, upload_sk,
    DECK_SK_PREFIX, FAV_SK_PREFIX,
    extract_deck_id, extract_fav_id,
    GSI_PUBLIC_DECKS, public_gsi1pk,
)

# Environment variables
TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET_NAME = os.environ["PPTX_BUCKET"]
CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "*")
KB_ID = os.environ.get("KB_ID", "")
VECTOR_BUCKET_NAME = os.environ.get("VECTOR_BUCKET_NAME", "")
VECTOR_INDEX_NAME = os.environ.get("VECTOR_INDEX_NAME", "")
RESOURCE_BUCKET = os.environ.get("RESOURCE_BUCKET", "")
CF_DOMAIN = os.environ.get("CF_DOMAIN", "")
CF_KEY_PAIR_ID = os.environ.get("CF_KEY_PAIR_ID", "")
CF_PRIVATE_KEY_PARAM = os.environ.get("CF_PRIVATE_KEY_PARAM", "")

# Module-level cache for styles (references are static, deployed once).
_styles_cache: Optional[List[Dict[str, str]]] = None

# Resolve KB ID from SSM if KB_ID looks like an SSM param path
if KB_ID.startswith("/"):
    try:
        _ssm = boto3.client("ssm")
        KB_ID = _ssm.get_parameter(Name=KB_ID)["Parameter"]["Value"]
    except Exception:
        KB_ID = ""

PRESIGNED_URL_EXPIRY = 900
MAX_FILE_SIZE = 100 * 1024 * 1024

# --- CloudFront preview URL helper ---
_cf_private_key: Optional[str] = None


def _get_cf_private_key() -> str:
    """Load CloudFront signing private key from SSM (cached)."""
    global _cf_private_key
    if _cf_private_key is None:
        ssm = boto3.client("ssm")
        _cf_private_key = ssm.get_parameter(
            Name=CF_PRIVATE_KEY_PARAM, WithDecryption=True,
        )["Parameter"]["Value"]
    return _cf_private_key


def preview_url(s3_key: str) -> Optional[str]:
    """Return CloudFront signed URL for a preview S3 key, or presigned S3 URL fallback."""
    return _cf_signed_url(s3_key) or presigned_url(s3_client, BUCKET_NAME, s3_key)


cors_origins = [o.strip() for o in CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
cors_config = CORSConfig(
    allow_origin=cors_origins[0],
    extra_origins=cors_origins[1:] if len(cors_origins) > 1 else None,
    allow_headers=["Content-Type", "Authorization"],
)

logger = Logger()
metrics = Metrics()
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
s3_client = boto3.client("s3")
app = APIGatewayHttpResolver(cors=cors_config)

# --- KB (optional) ---
_kb_sync = None
if KB_ID and VECTOR_BUCKET_NAME and VECTOR_INDEX_NAME:
    _s3vectors_client = boto3.client("s3vectors")
    _bedrock_agent_client = boto3.client("bedrock-agent-runtime")


def _delete_kb_vectors(deck_id: str, user_id: str) -> None:
    """Delete KB vectors for a deck (best-effort, no-op if KB not configured).

    Args:
        deck_id: Deck identifier.
        user_id: User identifier (for reading presentation.json slide count).
    """
    if not KB_ID or not VECTOR_BUCKET_NAME:
        return
    try:
        resp = s3_client.get_object(
            Bucket=BUCKET_NAME, Key=f"decks/{deck_id}/presentation.json",
        )
        pres = json.loads(resp["Body"].read())
        slides = pres.get("slides", [])
        keys: list = []
        for i, slide in enumerate(slides):
            sid = slide.get("id", f"slide_{i + 1:02d}")
            keys.append(f"{deck_id}/{sid}")
            keys.append(f"{deck_id}/{sid}_design")
        if keys:
            for batch_start in range(0, len(keys), 500):
                _s3vectors_client.delete_vectors(
                    vectorBucketName=VECTOR_BUCKET_NAME,
                    indexName=VECTOR_INDEX_NAME,
                    keys=keys[batch_start:batch_start + 500],
                )
    except Exception as e:
        logger.warning(f"KB vector cleanup failed for {deck_id}: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _list_preview_keys(deck_id: str) -> set:
    """List all preview keys for a deck in one S3 call.

    Returns:
        Set of S3 keys under previews/{deck_id}/.
    """
    prefix = f"previews/{deck_id}/"
    resp = s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix)
    return {obj["Key"] for obj in resp.get("Contents", [])}


def _resolve_preview_url(deck_id: str, slug: str, preview_keys: set) -> Optional[str]:
    """Resolve the best preview URL for a slide from cached keys.

    Uses build_slide_key_map to pick the latest epoch key for the given slug.

    Args:
        deck_id: Deck identifier.
        slug: Slide slug (e.g. "intro").
        preview_keys: Set of S3 keys from _list_preview_keys.

    Returns:
        Presigned/signed URL or None.
    """
    from shared.preview import build_slide_key_map

    key_map = build_slide_key_map(preview_keys)
    key = key_map.get(slug)
    if not key:
        return None
    return preview_url(key)


def _get_deck_extras(deck_items: List[Dict]) -> Dict[str, Dict]:
    """Get thumbnail URLs for deck items (DDB-only, no S3 fallback).

    Returns thumbnailUrl from DDB thumbnailS3Key. Decks without a stored key
    return null so the UI can show a gradient placeholder immediately.

    Args:
        deck_items: List of DDB deck records.

    Returns:
        Dict mapping deckId to {"thumbnailUrl": str|None}.
    """
    extras: Dict[str, Dict] = {}
    for deck in deck_items:
        deck_id = extract_deck_id(deck["SK"])
        key = deck.get("thumbnailS3Key")
        extras[deck_id] = {"thumbnailUrl": preview_url(key) if key else None}
    return extras


def _deck_summary(item: Dict, extras: Dict[str, Dict]) -> Dict[str, Any]:
    """Build a consistent deck summary dict from a DDB item.

    Args:
        item: DDB deck record.
        extras: Output of _get_deck_extras.

    Returns:
        Deck summary dict with all standard fields.
    """
    deck_id = extract_deck_id(item["SK"])
    ex = extras.get(deck_id, {})
    return {
        "deckId": deck_id,
        "name": item.get("name", "Untitled"),
        "slideCount": item.get("slideCount", 0),
        "updatedAt": item.get("updatedAt", ""),
        "thumbnailUrl": ex.get("thumbnailUrl"),
        "visibility": item.get("visibility", "private"),
        "createdBy": item.get("createdBy", ""),
    }


# ---------------------------------------------------------------------------
# Style endpoints
# ---------------------------------------------------------------------------


def _extract_cover_html(html: str) -> str:
    """Extract <head> + first <div class="slide..."> from a style HTML.

    Args:
        html: Full style HTML string.

    Returns:
        Minimal HTML with styles and first slide only.
    """
    head_end = html.find("</head>")
    if head_end == -1:
        return ""
    # Match <div class="slide"> or <div class="slide ..."> (additional classes)
    slide_pattern = re.compile(r'<div class="slide[\s"]')
    matches = list(slide_pattern.finditer(html))
    if not matches:
        return ""
    first_slide = matches[0].start()
    end = matches[1].start() if len(matches) > 1 else html.find("</body>", first_slide)
    if end == -1:
        end = len(html)
    return (
        html[: head_end + 7]
        + '\n<body style="margin:0;padding:0;background:transparent;overflow:hidden">\n'
        + html[first_slide:end].strip()
        + "\n</body></html>"
    )


@app.get("/styles")
def list_styles() -> Dict[str, Any]:
    """List available styles with cover slide HTML for preview.

    Includes builtin styles and user styles with pin/source metadata.

    Returns:
        Dict with styles list (name, description, coverHtml, pinned, source).
    """
    user_id = get_user_id(app.current_event)

    # Builtin styles (cached)
    global _styles_cache  # noqa: PLW0603
    if _styles_cache is None and RESOURCE_BUCKET:
        prefix = "references/examples/styles/"
        resp = s3_client.list_objects_v2(Bucket=RESOURCE_BUCKET, Prefix=prefix)
        builtin: List[Dict[str, str]] = []
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".html"):
                continue
            name = key.removeprefix(prefix).removesuffix(".html")
            body = s3_client.get_object(Bucket=RESOURCE_BUCKET, Key=key)["Body"].read().decode("utf-8")
            description = ""
            m = re.search(r"<title>(.*?)</title>", body, re.IGNORECASE)
            if m:
                description = m.group(1).strip()
            builtin.append({"name": name, "description": description, "coverHtml": _extract_cover_html(body), "source": "builtin"})
        _styles_cache = builtin

    all_styles: List[Dict[str, Any]] = list(_styles_cache or [])

    # User styles
    user_prefix = f"user-styles/{user_id}/"
    try:
        resp = s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=user_prefix)
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".html"):
                continue
            name = key.removeprefix(user_prefix).removesuffix(".html")
            body = s3_client.get_object(Bucket=BUCKET_NAME, Key=key)["Body"].read().decode("utf-8")
            description = ""
            m = re.search(r"<title>(.*?)</title>", body, re.IGNORECASE)
            if m:
                description = m.group(1).strip()
            all_styles.append({"name": name, "description": description, "coverHtml": _extract_cover_html(body), "source": "user"})
    except Exception:
        pass

    # Pins
    pin_resp = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "STYLE_PINS"})
    pinned_names = set(pin_resp.get("Item", {}).get("pinned_styles", []))

    for s in all_styles:
        s["pinned"] = s["name"] in pinned_names

    return {"styles": all_styles}


@app.get("/styles/<name>")
def get_style(name: str) -> Dict[str, Any]:
    """Get full HTML for a single style (user or builtin).

    Returns:
        Dict with name and fullHtml.
    """
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        return {"error": "Invalid style name"}, 400

    user_id = get_user_id(app.current_event)

    # Try user style first
    user_key = f"user-styles/{user_id}/{name}.html"
    try:
        body = s3_client.get_object(Bucket=BUCKET_NAME, Key=user_key)["Body"].read().decode("utf-8")
        return {"name": name, "fullHtml": body, "source": "user"}
    except Exception:
        pass

    # Fall back to builtin
    if RESOURCE_BUCKET:
        builtin_key = f"references/examples/styles/{name}.html"
        try:
            body = s3_client.get_object(Bucket=RESOURCE_BUCKET, Key=builtin_key)["Body"].read().decode("utf-8")
            return {"name": name, "fullHtml": body, "source": "builtin"}
        except Exception:
            pass

    return {"error": f"Style not found: {name}"}, 404


@app.post("/styles/pin")
def pin_style() -> Dict[str, Any]:
    """Toggle pin status for a style.

    Body: {"name": str, "pinned": bool}
    """
    body = app.current_event.json_body
    name = body.get("name", "")
    pinned = body.get("pinned", False)

    if not name or not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        return {"error": "Invalid style name"}, 400

    user_id = get_user_id(app.current_event)
    pin_resp = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "STYLE_PINS"})
    current_pins: List[str] = pin_resp.get("Item", {}).get("pinned_styles", [])

    if pinned and name not in current_pins:
        current_pins.append(name)
    elif not pinned and name in current_pins:
        current_pins.remove(name)

    table.put_item(Item={"PK": f"USER#{user_id}", "SK": "STYLE_PINS", "pinned_styles": current_pins})
    return {"ok": True, "pinned_styles": current_pins}


@app.post("/styles/user")
def save_user_style() -> Dict[str, Any]:
    """Save a user style (import or copy).

    Body: {"name": str, "html": str}
    """
    body = app.current_event.json_body
    name = body.get("name", "")
    html = body.get("html", "")

    if not name or not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        return {"error": "Invalid style name"}, 400
    if not html:
        return {"error": "html is required"}, 400

    user_id = get_user_id(app.current_event)
    key = f"user-styles/{user_id}/{name}.html"
    s3_client.put_object(Bucket=BUCKET_NAME, Key=key, Body=html.encode("utf-8"), ContentType="text/html")
    return {"saved": name}


@app.delete("/styles/user/<style_name>")
def delete_user_style(style_name: str) -> Dict[str, Any]:
    """Delete a user style.

    Also removes from pins if pinned.
    """
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", style_name):
        return {"error": "Invalid style name"}, 400

    user_id = get_user_id(app.current_event)
    key = f"user-styles/{user_id}/{style_name}.html"

    try:
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=key)
    except Exception:
        return {"error": f"Style not found: {style_name}"}, 404

    # Remove from pins
    pin_resp = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "STYLE_PINS"})
    current_pins: List[str] = pin_resp.get("Item", {}).get("pinned_styles", [])
    if style_name in current_pins:
        current_pins.remove(style_name)
        table.put_item(Item={"PK": f"USER#{user_id}", "SK": "STYLE_PINS", "pinned_styles": current_pins})

    return {"deleted": style_name}


@app.patch("/styles/user/<style_name>")
def rename_user_style(style_name: str) -> Dict[str, Any]:
    """Rename a user style.

    Body: {"newName": str}
    """
    body = app.current_event.json_body
    new_name = body.get("newName", "")

    if not re.fullmatch(r"[a-zA-Z0-9_-]+", style_name):
        return {"error": "Invalid style name"}, 400
    if not new_name or not re.fullmatch(r"[a-zA-Z0-9_-]+", new_name):
        return {"error": "Invalid new name"}, 400

    user_id = get_user_id(app.current_event)
    old_key = f"user-styles/{user_id}/{style_name}.html"
    new_key = f"user-styles/{user_id}/{new_name}.html"

    # Check source exists
    try:
        body_bytes = s3_client.get_object(Bucket=BUCKET_NAME, Key=old_key)["Body"].read()
    except Exception:
        return {"error": f"Style not found: {style_name}"}, 404

    # Check destination doesn't exist
    try:
        s3_client.head_object(Bucket=BUCKET_NAME, Key=new_key)
        return {"error": f"Style already exists: {new_name}"}, 409
    except Exception:
        pass

    # Copy + delete
    s3_client.put_object(Bucket=BUCKET_NAME, Key=new_key, Body=body_bytes, ContentType="text/html")
    s3_client.delete_object(Bucket=BUCKET_NAME, Key=old_key)

    # Update pins
    pin_resp = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "STYLE_PINS"})
    current_pins: List[str] = pin_resp.get("Item", {}).get("pinned_styles", [])
    if style_name in current_pins:
        current_pins[current_pins.index(style_name)] = new_name
        table.put_item(Item={"PK": f"USER#{user_id}", "SK": "STYLE_PINS", "pinned_styles": current_pins})

    return {"renamed": {"from": style_name, "to": new_name}}


# ---------------------------------------------------------------------------
# Template endpoints
# ---------------------------------------------------------------------------


@app.get("/templates")
def list_templates() -> Dict[str, Any]:
    """List all templates (builtin + user) with metadata.

    Builtin: S3 is source of truth for existence. DDB is metadata cache.
    User: DDB is source of truth.
    """
    import tempfile
    from pathlib import Path

    user_id = get_user_id(app.current_event)
    templates: List[Dict[str, Any]] = []

    # --- Builtin: S3 source of truth ---
    s3_templates: Dict[str, str] = {}  # name -> etag
    if RESOURCE_BUCKET:
        resp = s3_client.list_objects_v2(Bucket=RESOURCE_BUCKET, Prefix="templates/")
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".pptx"):
                name = key.removeprefix("templates/").removesuffix(".pptx")
                s3_templates[name] = obj["ETag"]

    # Batch get DDB cache for builtins
    ddb_cache: Dict[str, Dict] = {}
    if s3_templates:
        keys = [{"PK": f"TEMPLATE#{n}", "SK": "META"} for n in s3_templates]
        resp = table.meta.client.batch_get_item(
            RequestItems={table.name: {"Keys": keys}}
        )
        for item in resp.get("Responses", {}).get(table.name, []):
            ddb_cache[item["name"]] = item

    # Build builtin list with lazy analysis
    to_analyze: List[str] = []
    for name, etag in s3_templates.items():
        cached = ddb_cache.get(name)
        if cached and cached.get("s3ETag") == etag:
            analysis = {}
            raw = cached.get("analysisJson", "")
            if raw and raw != "{}":
                analysis = json.loads(raw) if isinstance(raw, str) else raw
            templates.append({
                "name": name,
                "source": "builtin",
                "description": cached.get("description", ""),
                "theme_colors": analysis.get("theme_colors", {}),
                "fonts": cached.get("fonts", {}),
                "layout_count": len(analysis.get("layouts", [])),
            })
        else:
            to_analyze.append(name)
            templates.append({
                "name": name,
                "source": "builtin",
                "description": "",
                "theme_colors": {},
                "fonts": {},
                "layout_count": 0,
            })

    # Lazy analyze uncached builtins (async would be better but keep simple)
    if to_analyze:
        from sdpm.analyzer import analyze_template as _analyze

        tmp = Path(tempfile.mkdtemp())
        for name in to_analyze:
            s3_key = f"templates/{name}.pptx"
            tpl_path = tmp / f"{name}.pptx"
            s3_client.download_file(RESOURCE_BUCKET, s3_key, str(tpl_path))
            analysis = _analyze(tpl_path)
            etag = s3_templates[name]
            item = {
                "PK": f"TEMPLATE#{name}",
                "SK": "META",
                "name": name,
                "s3Key": s3_key,
                "s3ETag": etag,
                "fonts": analysis.get("fonts", {}),
                "analysisJson": json.dumps({
                    "theme_colors": analysis.get("theme_colors", {}),
                    "layouts": analysis.get("layouts", []),
                }),
            }
            table.put_item(Item=item)
            # Update the placeholder in templates list
            for t in templates:
                if t["name"] == name and t["source"] == "builtin":
                    t["theme_colors"] = analysis.get("theme_colors", {})
                    t["fonts"] = analysis.get("fonts", {})
                    t["layout_count"] = len(analysis.get("layouts", []))
                    break

    # --- User templates: DDB source of truth ---
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}") & Key("SK").begins_with("TEMPLATE#"),
    )
    for t in resp.get("Items", []):
        analysis = {}
        raw = t.get("analysisJson", "")
        if raw and raw != "{}":
            analysis = json.loads(raw) if isinstance(raw, str) else raw
        templates.append({
            "name": t.get("name", ""),
            "source": "user",
            "description": t.get("description", ""),
            "theme_colors": analysis.get("theme_colors", {}),
            "fonts": t.get("fonts", {}),
            "layout_count": len(analysis.get("layouts", [])),
        })

    return {"templates": templates}


@app.get("/templates/<name>")
def download_template(name: str) -> Any:
    """Download a template .pptx file. Searches user templates first, then builtin."""
    user_id = get_user_id(app.current_event)

    # Try user template
    user_key = f"user-templates/{user_id}/{name}.pptx"
    try:
        s3_client.head_object(Bucket=BUCKET_NAME, Key=user_key)
        url = s3_client.generate_presigned_url(
            "get_object", Params={"Bucket": BUCKET_NAME, "Key": user_key}, ExpiresIn=300
        )
        return {"downloadUrl": url}
    except Exception:
        pass

    # Try builtin (S3 source of truth)
    builtin_key = f"templates/{name}.pptx"
    try:
        s3_client.head_object(Bucket=RESOURCE_BUCKET, Key=builtin_key)
        url = s3_client.generate_presigned_url(
            "get_object", Params={"Bucket": RESOURCE_BUCKET, "Key": builtin_key}, ExpiresIn=300
        )
        return {"downloadUrl": url}
    except Exception:
        return {"error": "Template not found"}, 404


@app.post("/templates/user/upload-url")
def presign_template_upload() -> Dict[str, Any]:
    """Generate a presigned PUT URL for template upload to S3."""
    user_id = get_user_id(app.current_event)
    body = app.current_event.json_body

    name: str = body.get("name", "").strip()
    if not name or not re.fullmatch(r"[a-zA-Z0-9_\-\s.()]+", name):
        return {"error": "Invalid template name"}, 400

    # Duplicate check
    existing = table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"TEMPLATE#{name}"})
    if existing.get("Item"):
        return {"error": f'Template "{name}" already exists'}, 409

    s3_key = f"user-templates/{user_id}/{name}.pptx"
    url = s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": BUCKET_NAME,
            "Key": s3_key,
            "ContentType": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        },
        ExpiresIn=PRESIGNED_URL_EXPIRY,
    )
    return {"presignedUrl": url, "s3Key": s3_key}


@app.post("/templates/user")
def upload_user_template() -> Dict[str, Any]:
    """Register a user template after S3 upload. Analyzes and stores metadata.

    Expects JSON body: {name, description}.
    The .pptx must already be uploaded to S3 via presigned URL.
    """
    import tempfile
    from pathlib import Path

    user_id = get_user_id(app.current_event)
    body = app.current_event.json_body

    name: str = body.get("name", "").strip()
    description: str = body.get("description", "")

    if not name or not re.fullmatch(r"[a-zA-Z0-9_\-\s.()]+", name):
        return {"error": "Invalid template name"}, 400

    s3_key = f"user-templates/{user_id}/{name}.pptx"

    # Verify file exists in S3
    try:
        s3_client.head_object(Bucket=BUCKET_NAME, Key=s3_key)
    except Exception:
        return {"error": "File not found in S3. Upload via presigned URL first."}, 400

    # Download and analyze
    tmp = Path(tempfile.mkdtemp())
    tpl_path = tmp / f"{name}.pptx"
    s3_client.download_file(BUCKET_NAME, s3_key, str(tpl_path))

    from sdpm.analyzer import analyze_template as _analyze

    analysis = _analyze(tpl_path)
    metadata = {
        "description": description,
        "fonts": analysis.get("fonts", {}),
        "analysisJson": json.dumps({
            "theme_colors": analysis.get("theme_colors", {}),
            "layouts": analysis.get("layouts", []),
        }),
    }

    # Store in DDB
    table.put_item(Item={
        "PK": f"USER#{user_id}",
        "SK": f"TEMPLATE#{name}",
        "name": name,
        "s3Key": s3_key,
        **metadata,
    })

    return {"uploaded": name}


@app.delete("/templates/user/<name>")
def delete_user_template(name: str) -> Dict[str, Any]:
    """Delete a user template."""
    user_id = get_user_id(app.current_event)

    # Check exists
    resp = table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"TEMPLATE#{name}"})
    if not resp.get("Item"):
        return {"error": "Template not found"}, 404

    s3_key = f"user-templates/{user_id}/{name}.pptx"
    s3_client.delete_object(Bucket=BUCKET_NAME, Key=s3_key)
    table.delete_item(Key={"PK": f"USER#{user_id}", "SK": f"TEMPLATE#{name}"})

    return {"deleted": name}


@app.patch("/templates/user/<name>")
def patch_user_template(name: str) -> Dict[str, Any]:
    """Rename or update description of a user template.

    Body: {"newName": str} or {"description": str}
    """
    user_id = get_user_id(app.current_event)
    body = app.current_event.json_body

    resp = table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"TEMPLATE#{name}"})
    item = resp.get("Item")
    if not item:
        return {"error": "Template not found"}, 404

    # Rename
    new_name = body.get("newName", "").strip()
    if new_name:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", new_name):
            return {"error": "Letters, numbers, hyphens, underscores only"}, 400
        # Check duplicate
        dup = table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"TEMPLATE#{new_name}"})
        if dup.get("Item"):
            return {"error": "Name already exists"}, 409
        # S3 copy + delete
        old_key = f"user-templates/{user_id}/{name}.pptx"
        new_key = f"user-templates/{user_id}/{new_name}.pptx"
        s3_client.copy_object(
            Bucket=BUCKET_NAME,
            CopySource={"Bucket": BUCKET_NAME, "Key": old_key},
            Key=new_key,
        )
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=old_key)
        # DDB: delete old, put new
        table.delete_item(Key={"PK": f"USER#{user_id}", "SK": f"TEMPLATE#{name}"})
        item["SK"] = f"TEMPLATE#{new_name}"
        item["name"] = new_name
        item["s3Key"] = new_key
        table.put_item(Item=item)
        return {"renamed": {"from": name, "to": new_name}}

    # Update description
    description = body.get("description")
    if description is not None:
        table.update_item(
            Key={"PK": f"USER#{user_id}", "SK": f"TEMPLATE#{name}"},
            UpdateExpression="SET description = :d",
            ExpressionAttributeValues={":d": description},
        )
        return {"updated": name, "description": description}

    return {"error": "No action specified"}, 400


# ---------------------------------------------------------------------------
# Deck endpoints
# ---------------------------------------------------------------------------


@app.get("/decks")
def list_decks() -> Dict[str, Any]:
    """List all decks for the authenticated user."""
    user_id = get_user_id(app.current_event)

    resp = table.query(
        KeyConditionExpression=Key("PK").eq(deck_pk(user_id)) & Key("SK").begins_with(DECK_SK_PREFIX),
        FilterExpression="attribute_not_exists(deletedAt)",
    )
    items = resp.get("Items", [])
    extras = _get_deck_extras(items)

    fav_resp = table.query(
        KeyConditionExpression=Key("PK").eq(deck_pk(user_id)) & Key("SK").begins_with(FAV_SK_PREFIX),
        ProjectionExpression="SK",
    )
    favorite_ids = [extract_fav_id(item["SK"]) for item in fav_resp.get("Items", [])]

    decks = [_deck_summary(item, extras) for item in items]
    decks.sort(key=lambda d: d["updatedAt"], reverse=True)
    return {"decks": decks, "favoriteIds": favorite_ids}


@app.get("/decks/favorites")
def list_favorites() -> Dict[str, Any]:
    """List user's favorite decks."""
    user_id = get_user_id(app.current_event)
    fav_resp = table.query(
        KeyConditionExpression=Key("PK").eq(deck_pk(user_id)) & Key("SK").begins_with(FAV_SK_PREFIX),
    )
    # Resolve each favorite
    decks = []
    for fav in fav_resp.get("Items", []):
        deck_id = extract_fav_id(fav["SK"])
        resp = table.get_item(Key={"PK": deck_pk(user_id), "SK": deck_sk(deck_id)})
        item = resp.get("Item")
        if item and "deletedAt" not in item:
            decks.append(item)

    extras = _get_deck_extras(decks)
    result = [_deck_summary(item, extras) for item in decks]
    result.sort(key=lambda d: d["updatedAt"], reverse=True)
    return {"decks": result}


@app.get("/decks/shared")
def list_shared() -> Dict[str, Any]:
    """List decks shared with the current user."""
    user_id = get_user_id(app.current_event)
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(shared_pk(user_id)) & Key("SK").begins_with(DECK_SK_PREFIX),
    )
    deck_items = []
    for item in resp.get("Items", []):
        deck_id = extract_deck_id(item["SK"])
        owner_id = item.get("ownerUserId", "")
        if not owner_id:
            continue
        owner_resp = table.get_item(Key={"PK": deck_pk(owner_id), "SK": deck_sk(deck_id)})
        owner_deck = owner_resp.get("Item")
        if owner_deck and "deletedAt" not in owner_deck:
            deck_items.append(owner_deck)

    extras = _get_deck_extras(deck_items)
    decks = [_deck_summary(item, extras) for item in deck_items]
    decks.sort(key=lambda d: d["updatedAt"], reverse=True)
    return {"decks": decks}


@app.get("/decks/public")
def list_public() -> Dict[str, Any]:
    """List public decks via PublicDecks GSI."""
    get_user_id(app.current_event)

    resp = table.query(
        IndexName=GSI_PUBLIC_DECKS,
        KeyConditionExpression=Key("GSI1PK").eq(public_gsi1pk()),
        ScanIndexForward=False,
        FilterExpression="attribute_not_exists(deletedAt)",
    )
    items = resp.get("Items", [])
    extras = _get_deck_extras(items)
    decks = [_deck_summary(item, extras) for item in items]
    return {"decks": decks}



@app.get("/decks/<deck_id>")
def get_deck(deck_id: str) -> Dict[str, Any]:
    """Get deck details with presigned URLs. Reads slides from S3 (deck.json + slides/*.json)."""
    user_id = get_user_id(app.current_event)

    decision = authorize(user_id, deck_id, "read", table)
    if not decision.allowed:
        return {"error": decision.reason}, 403

    deck = decision.deck
    pptx_key = deck.get("pptxS3Key")

    # Read slides from S3 (deck.json + slides/*.json format)
    slides = []
    include_json = (app.current_event.get_query_string_value("include") or "") == "slideJson"

    # Collect compose keys for animation (epoch-keyed)
    compose_keys = set()
    try:
        for obj in s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"decks/{deck_id}/compose/").get("Contents", []):
            compose_keys.add(obj["Key"])
    except Exception:
        pass

    import re as _re
    def _latest_compose_key(prefix: str, keys: set) -> Optional[str]:
        """Pick the key with the highest epoch from epoch-keyed compose files."""
        best_epoch, best_key = -1, None
        for k in keys:
            if not k.startswith(prefix):
                continue
            m = _re.search(r"_(\d+)\.json$", k)
            epoch = int(m.group(1)) if m else 0
            if epoch > best_epoch:
                best_epoch, best_key = epoch, k
        return best_key

    defs_key = _latest_compose_key(f"decks/{deck_id}/compose/defs_", compose_keys)
    has_defs = defs_key is not None

    # outline.md for slug order, then slides/*.json
    # Canonical implementation: sdpm.api.parse_outline_slugs (not importable in Lambda)
    slugs = []
    try:
        outline_resp = s3_client.get_object(Bucket=BUCKET_NAME, Key=f"decks/{deck_id}/specs/outline.md")
        outline_text = outline_resp["Body"].read().decode("utf-8")
        slug_re = _re.compile(r"^-\s*\[([a-z0-9-]+)\]\s*")
        for line in outline_text.splitlines():
            m = slug_re.match(line)
            if m:
                slugs.append(m.group(1))
    except Exception:
        pass

    # If no outline slugs, list slides/ directory
    if not slugs:
        prefix = f"decks/{deck_id}/slides/"
        resp = s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix)
        for obj in resp.get("Contents", []):
            name = obj["Key"].rsplit("/", 1)[-1]
            if name.endswith(".json"):
                slugs.append(name[:-5])

    # Legacy fallback: presentation.json (pre-slug era, numbered slides)
    legacy_slides: Optional[list] = None
    if not slugs:
        try:
            pres_resp = s3_client.get_object(Bucket=BUCKET_NAME, Key=f"decks/{deck_id}/presentation.json")
            presentation = json.loads(pres_resp["Body"].read())
            legacy_slides = presentation.get("slides", [])
            slugs = [f"slide_{i + 1:02d}" for i in range(len(legacy_slides))]
        except Exception:
            pass

    preview_keys = _list_preview_keys(deck_id)
    for i, slug in enumerate(slugs):
        slide_data = None
        if legacy_slides is not None:
            slide_data = legacy_slides[i]
        else:
            try:
                slide_resp = s3_client.get_object(Bucket=BUCKET_NAME, Key=f"decks/{deck_id}/slides/{slug}.json")
                slide_data = json.loads(slide_resp["Body"].read())
            except Exception:
                continue
        slide_preview = _resolve_preview_url(deck_id, slug, preview_keys)
        slide_entry: Dict[str, Any] = {"slug": slug, "previewUrl": slide_preview}
        compose_key = _latest_compose_key(f"decks/{deck_id}/compose/{slug}_", compose_keys)
        if not compose_key:
            compose_key = _latest_compose_key(f"decks/{deck_id}/compose/slide_{i + 1}_", compose_keys)
        if compose_key:
            slide_entry["composeUrl"] = preview_url(compose_key)
        if include_json:
            slide_entry["slideJson"] = json.dumps(slide_data)
        slides.append(slide_entry)

    # Read spec files from S3 (brief.md, outline.md, art-direction.html/.md)
    specs: Dict[str, Any] = {}

    # brief and outline — always .md
    for spec_name in ("brief", "outline"):
        spec_key = f"decks/{deck_id}/specs/{spec_name}.md"
        try:
            spec_resp = s3_client.get_object(Bucket=BUCKET_NAME, Key=spec_key)
            content = spec_resp["Body"].read().decode("utf-8")
            specs[spec_name] = content if content.strip() else None
        except Exception:
            specs[spec_name] = None

    # art-direction — try .html first, fall back to .md
    art_direction_content = None
    for ext in (".html", ".md"):
        art_key = f"decks/{deck_id}/specs/art-direction{ext}"
        try:
            art_resp = s3_client.get_object(Bucket=BUCKET_NAME, Key=art_key)
            content = art_resp["Body"].read().decode("utf-8")
            if content.strip():
                art_direction_content = content
                break
        except Exception:
            pass
    specs["artDirection"] = art_direction_content

    return {
        "deckId": deck_id,
        "name": deck.get("name", "Untitled"),
        "slideCount": len(slides),
        "slides": slides,
        "specs": specs,
        "defsUrl": preview_url(defs_key) if has_defs else None,
        "pptxUrl": (_cf_signed_url(pptx_key) or presigned_url(s3_client, BUCKET_NAME, pptx_key)) if pptx_key else None,
        "updatedAt": deck.get("updatedAt", ""),
        "chatSessionId": deck.get("chatSessionId"),
        "isOwner": decision.role == "owner",
        "role": decision.role,
        "visibility": deck.get("visibility", "private"),
    }


PATCH_ALLOWED_FIELDS = {"chatSessionId", "visibility"}


@app.patch("/decks/<deck_id>")
def patch_deck(deck_id: str) -> Dict[str, Any]:
    """Update allowed fields on a deck.

    Only fields in PATCH_ALLOWED_FIELDS can be updated.
    Visibility changes require 'change_visibility' permission (owner only).
    Setting visibility to 'public' adds GSI keys; 'private' removes them.

    Args:
        deck_id: Deck identifier.

    Returns:
        Dict confirming the update.
    """
    user_id = get_user_id(app.current_event)
    body = app.current_event.json_body or {}

    # Visibility changes require elevated permission
    action = "change_visibility" if "visibility" in body else "update"
    decision = authorize(user_id, deck_id, action, table)
    if not decision.allowed:
        return {"error": decision.reason}, 403

    updates = {k: v for k, v in body.items() if k in PATCH_ALLOWED_FIELDS}
    if not updates:
        return {"error": "No valid fields to update"}, 400

    # Validate visibility value
    if "visibility" in updates and updates["visibility"] not in ("public", "private"):
        return {"error": "visibility must be 'public' or 'private'"}, 400

    updates["updatedAt"] = now_iso()

    # Build SET and REMOVE expressions
    expr_names: Dict[str, str] = {}
    expr_values: Dict[str, Any] = {}
    set_parts: list[str] = []
    remove_parts: list[str] = []

    for i, (k, v) in enumerate(updates.items()):
        attr = f"#f{i}"
        val = f":v{i}"
        expr_names[attr] = k
        expr_values[val] = v
        set_parts.append(f"{attr} = {val}")

    # Handle GSI keys for visibility changes
    if updates.get("visibility") == "public":
        expr_names["#gsi1pk"] = "GSI1PK"
        expr_names["#gsi1sk"] = "GSI1SK"
        expr_values[":gsi1pk"] = public_gsi1pk()
        expr_values[":gsi1sk"] = updates["updatedAt"]
        set_parts.append("#gsi1pk = :gsi1pk")
        set_parts.append("#gsi1sk = :gsi1sk")
    elif updates.get("visibility") == "private":
        expr_names["#gsi1pk"] = "GSI1PK"
        expr_names["#gsi1sk"] = "GSI1SK"
        remove_parts.append("#gsi1pk")
        remove_parts.append("#gsi1sk")

    expression = "SET " + ", ".join(set_parts)
    if remove_parts:
        expression += " REMOVE " + ", ".join(remove_parts)

    table.update_item(
        Key={"PK": deck_pk(user_id), "SK": deck_sk(deck_id)},
        UpdateExpression=expression,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )
    return {"deckId": deck_id, "updated": list(body.keys())}


@app.delete("/decks/<deck_id>")
def delete_deck(deck_id: str) -> Dict[str, Any]:
    """Soft-delete a deck and clean up KB vectors if enabled."""
    user_id = get_user_id(app.current_event)
    decision = authorize(user_id, deck_id, "delete_deck", table)
    if not decision.allowed:
        return {"error": decision.reason}, 403

    now = now_iso()
    ttl_value = int(__import__("time").time()) + (30 * 24 * 60 * 60)
    table.update_item(
        Key={"PK": deck_pk(user_id), "SK": deck_sk(deck_id)},
        UpdateExpression="SET deletedAt = :now, #t = :ttl",
        ExpressionAttributeNames={"#t": "ttl"},
        ExpressionAttributeValues={":now": now, ":ttl": ttl_value},
        ConditionExpression="attribute_exists(PK)",
    )

    # Clean up KB vectors (best-effort)
    _delete_kb_vectors(deck_id, user_id)

    return {"deckId": deck_id, "deleted": True}


@app.post("/decks/<deck_id>/favorite")
def toggle_favorite(deck_id: str) -> Dict[str, Any]:
    """Add or remove a deck from favorites."""
    user_id = get_user_id(app.current_event)
    body = app.current_event.json_body or {}
    action: str = body.get("action", "")
    if action not in ("add", "remove"):
        return {"error": "action must be 'add' or 'remove'"}, 400

    if action == "add":
        table.put_item(Item={"PK": deck_pk(user_id), "SK": fav_sk(deck_id), "createdAt": now_iso()})
    else:
        table.delete_item(Key={"PK": deck_pk(user_id), "SK": fav_sk(deck_id)})
    return {"favorited": action == "add"}


# ---------------------------------------------------------------------------
# Slide search endpoint (optional, requires KB)
# ---------------------------------------------------------------------------


@app.get("/slides/search")
def search_slides_api() -> Dict[str, Any]:
    """Search slides via Amazon Bedrock Knowledge Base.

    Query params:
        q: Search query string (required).

    Returns:
        Dict with results list.
    """
    if not KB_ID:
        return {"results": [], "error": "Knowledge Base not configured"}

    query = app.current_event.get_query_string_value("q", "")
    if not query or len(query) < 2:
        return {"results": [], "error": "Query must be at least 2 characters"}
    if len(query) > 500:
        return {"results": [], "error": "Query too long"}

    user_id = get_user_id(app.current_event)

    # scope: own slides OR public slides
    retrieval_filter: Dict = {
        "orAll": [
            {"equals": {"key": "author", "value": user_id}},
            {"equals": {"key": "visibility", "value": "public"}},
        ],
    }

    response = _bedrock_agent_client.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": 20,
                "filter": retrieval_filter,
            },
        },
    )

    results: List[Dict] = []
    seen: set = set()
    seen_decks: Dict[str, set] = {}
    for r in response.get("retrievalResults", []):
        meta = r.get("metadata", {})
        deck_id = meta.get("deckId", "")
        slide_id = meta.get("slideId", "")
        dedup_key = (deck_id, slide_id)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # Generate preview URL — slideId matches preview filename
        slide_preview_url = ""
        if deck_id and slide_id:
            # Lazy-load preview keys per deck
            if deck_id not in seen_decks:
                seen_decks[deck_id] = _list_preview_keys(deck_id)
            slide_preview_url = _resolve_preview_url(deck_id, slide_id, seen_decks[deck_id])
            slide_preview_url = slide_preview_url or ""

        results.append({
            "deckId": deck_id,
            "deckName": meta.get("deckName", ""),
            "slideId": slide_id,
            "pageNumber": int(meta.get("pageNumber", 0)),
            "score": r.get("score", 0),
            "excerpt": r.get("content", {}).get("text", "")[:200],
            "previewUrl": slide_preview_url,
        })

    return {"results": results}


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------


@app.get("/chat/<session_id>")
def get_chat(session_id: str) -> Dict[str, Any]:
    """Get chat history for a session from Amazon Bedrock AgentCore Memory.

    Verifies the session belongs to a deck owned by the requesting user
    before reading from Amazon Bedrock AgentCore Memory.

    Args:
        session_id: Conversation session ID linked to a deck.

    Returns:
        Dict with messages array in Converse API format.
    """
    user_id = get_user_id(app.current_event)
    memory_id = os.environ.get("MEMORY_ID", "")
    if not memory_id:
        return {"messages": []}

    # Verify session_id belongs to a deck owned by this user
    from boto3.dynamodb.conditions import Key, Attr

    resp = table.query(
        KeyConditionExpression=Key("PK").eq(deck_pk(user_id)) & Key("SK").begins_with(DECK_SK_PREFIX),
        FilterExpression=Attr("chatSessionId").eq(session_id),
        ProjectionExpression="SK",
    )
    if not resp.get("Items"):
        return {"messages": []}
    memory_id = os.environ.get("MEMORY_ID", "")
    if not memory_id:
        return {"messages": []}

    agentcore_client = boto3.client("bedrock-agentcore")
    messages: List[Dict] = []

    try:
        # Strands SDK uses actor_id = user_id (JWT sub)
        paginator_token = None
        while True:
            params: Dict[str, Any] = {
                "memoryId": memory_id,
                "actorId": user_id,
                "sessionId": session_id,
                "includePayloads": True,
            }
            if paginator_token:
                params["nextToken"] = paginator_token

            resp = agentcore_client.list_events(**params)

            for event in resp.get("events", []):
                for payload_item in event.get("payload", []):
                    msg = _parse_memory_payload(payload_item)
                    if msg:
                        messages.append(msg)

            paginator_token = resp.get("nextToken")
            if not paginator_token:
                break

        # Strands stores events in reverse chronological order
        messages.reverse()

        # Strip toolResult content — frontend only needs status for ToolCard display.
        # Agent reads from Amazon Bedrock AgentCore Memory directly, not via this API.
        # This prevents Lambda 6MB response limit errors on long conversations.
        for msg in messages:
            if msg.get("role") == "user" and isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    if isinstance(block, dict) and "toolResult" in block:
                        block["toolResult"]["content"] = []
    except Exception as e:
        logger.warning("Failed to read chat history from AgentCore Memory: %s", e)

    return {"messages": messages}


def _parse_memory_payload(payload_item: Dict) -> Dict | None:
    """Parse a single Amazon Bedrock AgentCore Memory event payload into a Converse API message.

    Strands SDK stores SessionMessage.to_dict() as JSON in the text field.
    The dict has a "message" key containing the Converse API message.

    Args:
        payload_item: Single payload entry from list_events response.

    Returns:
        Converse API message dict, or None if unparseable.
    """
    try:
        if "conversational" in payload_item:
            text = payload_item["conversational"]["content"]["text"]
            session_msg = json.loads(text)
            return session_msg.get("message", session_msg)
        if "blob" in payload_item:
            blob_data = json.loads(payload_item["blob"])
            if isinstance(blob_data, (list, tuple)) and len(blob_data) == 2:
                session_msg = json.loads(blob_data[0])
                return session_msg.get("message", session_msg)
    except (json.JSONDecodeError, KeyError, TypeError, IndexError, UnicodeDecodeError):
        pass
    return None


# ---------------------------------------------------------------------------
# CloudFront signed URL helper
# ---------------------------------------------------------------------------


def _cf_signed_url(s3_key: str, expires_in: int = 900) -> Optional[str]:
    """Generate a CloudFront signed URL for an S3 key.

    Args:
        s3_key: S3 object key (e.g. previews/deck_id/slide_01.webp).
        expires_in: URL validity in seconds (default 15 min).

    Returns:
        Signed URL string, or None if CloudFront is not configured.
    """
    if not CF_DOMAIN or not CF_KEY_PAIR_ID or not CF_PRIVATE_KEY_PARAM:
        return None

    import datetime
    import base64
    import subprocess
    import tempfile

    private_key_pem = _get_cf_private_key()
    expires = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=expires_in)).timestamp())
    url = f"https://{CF_DOMAIN}/{s3_key}"

    policy = json.dumps({
        "Statement": [{
            "Resource": url,
            "Condition": {"DateLessThan": {"AWS:EpochTime": expires}},
        }],
    }, separators=(",", ":"))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as kf:
        kf.write(private_key_pem)
        key_path = kf.name
    try:
        sig_raw = subprocess.check_output(  # nosec B603 B607 — fixed args, key_path is tempfile
            ["/usr/bin/openssl", "dgst", "-sha1", "-sign", key_path],
            input=policy.encode(), stderr=subprocess.DEVNULL,
        )
    finally:
        os.unlink(key_path)

    def _b64(data: bytes) -> str:
        return base64.b64encode(data).decode().replace("+", "-").replace("=", "_").replace("/", "~")

    return f"{url}?Policy={_b64(policy.encode())}&Signature={_b64(sig_raw)}&Key-Pair-Id={CF_KEY_PAIR_ID}"


# ---------------------------------------------------------------------------
# Upload endpoints
# ---------------------------------------------------------------------------

ALLOWED_CONTENT_TYPES = {
    "text/plain", "text/markdown", "application/json", "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml",
}


@app.post("/uploads/presign")
def presign_upload() -> Dict[str, Any]:
    """Generate a presigned PUT URL for file upload."""
    user_id = get_user_id(app.current_event)
    body = app.current_event.json_body

    file_name: str = body.get("fileName", "")
    content_type: str = body.get("contentType", "")
    file_size: int = int(body.get("fileSize", 0))

    if not file_name or not content_type:
        return {"error": "fileName and contentType are required"}, 400
    if content_type not in ALLOWED_CONTENT_TYPES:
        return {"error": f"Unsupported file type: {content_type}"}, 400
    if file_size > MAX_FILE_SIZE:
        return {"error": "File too large"}, 400

    upload_id = str(uuid.uuid4())[:8]
    s3_key = f"uploads/tmp/{user_id}/{upload_id}/{file_name}"

    url = s3_client.generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET_NAME, "Key": s3_key, "ContentType": content_type},
        ExpiresIn=PRESIGNED_URL_EXPIRY,
    )

    table.put_item(Item={
        "PK": deck_pk(user_id), "SK": upload_sk(upload_id),
        "fileName": file_name, "fileType": content_type, "fileSize": file_size,
        "s3KeyRaw": s3_key, "status": "uploading", "createdAt": now_iso(),
    })
    return {"uploadId": upload_id, "presignedUrl": url, "s3Key": s3_key}


# Text-extractable MIME types (can be read directly from S3 in Lambda)
_TEXT_EXTRACTABLE = {"text/plain", "text/markdown", "application/json"}


def _extract_pptx_text(s3_key: str) -> str:
    """Extract slide text from PPTX using zipfile + XML (no python-pptx needed)."""
    import io
    import re
    import zipfile
    obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=s3_key)
    data = obj["Body"].read()
    slides_text = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        slide_names = sorted(n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n))
        for name in slide_names:
            xml = zf.read(name).decode("utf-8")
            texts = re.findall(r"<a:t>([^<]+)</a:t>", xml)
            if texts:
                slide_num = re.search(r"slide(\d+)", name).group(1)
                slides_text.append(f"--- Slide {slide_num} ---\n" + "\n".join(texts))
    return "\n\n".join(slides_text)


@app.post("/uploads/<upload_id>/process")
def process_upload(upload_id: str) -> Dict[str, Any]:
    """Process an uploaded file — convert binary files at upload time."""
    import tempfile
    from pathlib import Path as _Path
    from shared.ingest import IMAGE_EXTS, convert_file

    user_id = get_user_id(app.current_event)
    body = app.current_event.json_body or {}
    session_id: str = body.get("sessionId", "")

    resp = table.get_item(Key={"PK": deck_pk(user_id), "SK": upload_sk(upload_id)})
    item = resp.get("Item")
    if not item:
        raise app.not_found()

    file_type = item.get("fileType", "")
    file_name = item.get("fileName", "unknown")
    s3_key = item.get("s3KeyRaw", "")
    update_expr_parts = ["#st = :st", "sessionId = :sid"]
    expr_values: Dict[str, Any] = {":sid": session_id}
    expr_names = {"#st": "status"}

    extracted_text = None
    ext = _Path(file_name).suffix.lower()

    # --- Text files: read directly from S3 ---
    if file_type in _TEXT_EXTRACTABLE and s3_key:
        try:
            obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=s3_key)
            extracted_text = obj["Body"].read().decode("utf-8")
            update_expr_parts.append("extractedText = :et")
            expr_values[":et"] = extracted_text[:50000]
            expr_values[":st"] = "completed"
        except Exception:
            expr_values[":st"] = "completed"

    # --- Images: no conversion needed ---
    elif ext in IMAGE_EXTS:
        expr_values[":st"] = "completed"

    # --- Binary files (PDF/DOCX/XLSX/PPTX): download → convert → upload ---
    elif ext in (".pdf", ".docx", ".xlsx") and s3_key:
        converted_prefix = f"uploads/{user_id}/{upload_id}/converted"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = _Path(tmp)
                local_file = tmp_path / file_name
                output_dir = tmp_path / "converted"

                obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=s3_key)
                local_file.write_bytes(obj["Body"].read())

                result = convert_file(local_file, output_dir)

                if result.status == "error":
                    expr_values[":st"] = "error"
                    update_expr_parts.append("conversionError = :ce")
                    expr_values[":ce"] = result.error or "Unknown error"
                else:
                    if output_dir.exists():
                        for f in output_dir.rglob("*"):
                            if f.is_file():
                                rel = f.relative_to(output_dir)
                                s3_dest = f"{converted_prefix}/{rel}"
                                ct = "application/octet-stream"
                                if f.suffix in (".md", ".txt"):
                                    ct = "text/markdown"
                                elif f.suffix == ".json":
                                    ct = "application/json"
                                elif f.suffix in (".png", ".jpg", ".jpeg"):
                                    ct = f"image/{f.suffix.lstrip('.')}"
                                s3_client.put_object(
                                    Bucket=BUCKET_NAME, Key=s3_dest,
                                    Body=f.read_bytes(), ContentType=ct,
                                )

                    expr_values[":st"] = "converted"
                    if result.warnings:
                        update_expr_parts.append("conversionWarnings = :cw")
                        expr_values[":cw"] = result.warnings

        except Exception as e:
            logger.exception("Conversion failed for %s", upload_id)
            expr_values[":st"] = "error"
            update_expr_parts.append("conversionError = :ce")
            expr_values[":ce"] = str(e)[:500]

    else:
        expr_values[":st"] = "completed"

    table.update_item(
        Key={"PK": deck_pk(user_id), "SK": upload_sk(upload_id)},
        UpdateExpression="SET " + ", ".join(update_expr_parts),
        ExpressionAttributeValues=expr_values,
        ExpressionAttributeNames=expr_names,
    )

    image_url = None
    if file_type.startswith("image/") and s3_key:
        image_url = presigned_url(s3_client, BUCKET_NAME, s3_key)

    return {
        "uploadId": upload_id,
        "status": expr_values[":st"],
        "extractedText": extracted_text,
        "imageUrl": image_url,
    }


@app.get("/uploads/<upload_id>/status")
def get_upload_status(upload_id: str) -> Dict[str, Any]:
    """Return current processing status of an upload."""
    user_id = get_user_id(app.current_event)
    resp = table.get_item(Key={"PK": deck_pk(user_id), "SK": upload_sk(upload_id)})
    item = resp.get("Item")
    if not item:
        raise app.not_found()

    image_url = None
    if item.get("fileType", "").startswith("image/") and item.get("s3KeyRaw"):
        image_url = presigned_url(s3_client, BUCKET_NAME, item["s3KeyRaw"])

    return {
        "uploadId": upload_id,
        "fileName": item.get("fileName", ""),
        "fileType": item.get("fileType", ""),
        "status": item.get("status", "unknown"),
        "extractedText": item.get("extractedText"),
        "imageUrl": image_url,
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    """AWS Lambda handler — unified API.

    Args:
        event: Amazon API Gateway event.
        context: Lambda context.

    Returns:
        Amazon API Gateway response.
    """
    return app.resolve(event, context)
