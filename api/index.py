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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, CORSConfig
from aws_lambda_powertools.utilities.typing import LambdaContext
from boto3.dynamodb.conditions import Key
from botocore.config import Config as BotoConfig
from authz import authorize
from chat_history import (
    cap_messages_size,
    strip_tool_result_content,
    truncate_tool_inputs,
)
from common import get_user_id, now_iso, presigned_url
from html_presign import (
    PURPOSES as HTML_PURPOSES,
    html_presign_client,
    html_slide_slugs,
    attachment_disposition,
    is_html_deck,
    presigned_html_url,
    slide_size,
)
from shared.artifact_keys import build_html_preview_key_map, preview_prefix as html_preview_prefix
from shared.review import (
    MAX_BODY_BYTES as REVIEW_MAX_BODY_BYTES,
    build_review_file,
    build_review_message,
    new_review_id,
    review_path,
    slide_size_of,
    validate_review_submission,
)
from shared import user_library
from shared.session_owner import belongs_to
from shared.schema import (
    deck_pk, deck_sk, fav_sk,
    DECK_SK_PREFIX, FAV_SK_PREFIX,
    extract_deck_id, extract_fav_id,
    GSI_PUBLIC_DECKS, public_gsi1pk,
    builtin_note_key, user_template_key, user_template_sk,
    validate_outline_content,
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
s3_client = boto3.client("s3", config=BotoConfig(signature_version="s3v4"))
# HTML decks run scripts, so they are served only from the S3 regional
# endpoint (a different origin from the Web UI): the Web UI CloudFront
# distribution serves previews/*, decks/*/* and pptx/* on the app origin.
# HTML keys are signed with this client only — never preview_url() /
# _cf_signed_url().
REGION = os.environ.get("AWS_REGION") or boto3.session.Session().region_name or "us-east-1"
html_s3_client = html_presign_client(REGION)
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


def _html_presigned(key: str, purpose: str = "view", deck_name: str = "") -> Optional[str]:
    """Presigned S3 URL for an HTML artifact (regional S3 origin, never CloudFront).

    Returns None when the key is not an ``html/**.html`` key.
    """
    try:
        return presigned_html_url(html_s3_client, BUCKET_NAME, key, purpose, deck_name)[0]
    except ValueError:
        return None


def _pptx_download_url(key: str, deck_name: str = "") -> Optional[str]:
    """Signed URL that downloads a built PPTX as ``<deck title>.pptx``.

    CloudFront (the ``pptx/*`` behaviour, inside the distribution's WAF), with
    ``response-content-disposition`` in the signed URL: the behaviour's cache policy
    forwards that parameter to S3, which answers with it as Content-Disposition.
    Without CloudFront configured, an S3 presign on the API's client (as before).
    None for a key outside ``pptx/**.pptx``.
    """
    if not isinstance(key, str) or not key.startswith("pptx/") or not key.endswith(".pptx") or ".." in key:
        return None
    disposition = attachment_disposition(deck_name, ".pptx")
    return _cf_signed_url(key, query={"response-content-disposition": disposition}) or s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET_NAME, "Key": key, "ResponseContentDisposition": disposition},
        ExpiresIn=PRESIGNED_URL_EXPIRY,
    )


def _list_html_preview_map(deck_id: str) -> Dict[str, str]:
    """slug → latest HTML preview key under html/{deck_id}/preview/ (one S3 call)."""
    resp = s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=html_preview_prefix(deck_id))
    return build_html_preview_key_map(obj["Key"] for obj in resp.get("Contents", []))


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
    from shared.artifact_keys import build_slide_key_map

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
        if key and key.endswith(".html"):
            extras[deck_id] = {"thumbnailUrl": _html_presigned(key)}
            continue
        extras[deck_id] = {"thumbnailUrl": preview_url(key) if key else None}
    return extras


def _deck_summary(item: Dict, extras: Dict[str, Dict], owner: bool = False) -> Dict[str, Any]:
    """Build a consistent deck summary dict from a DDB item.

    Args:
        item: DDB deck record.
        extras: Output of _get_deck_extras.
        owner: The caller owns the deck; adds its ``chatSessionId`` (None when the
            deck has no chat link), so a client can find the deck its session created.

    Returns:
        Deck summary dict with all standard fields.
    """
    deck_id = extract_deck_id(item["SK"])
    ex = extras.get(deck_id, {})
    summary = {
        "deckId": deck_id,
        "name": item.get("name", "Untitled"),
        "slideCount": item.get("slideCount", 0),
        "updatedAt": item.get("updatedAt", ""),
        "thumbnailUrl": ex.get("thumbnailUrl"),
        "visibility": item.get("visibility", "private"),
        # A built PPTX exists (GET /decks/{id}/pptx signs it on demand; the list stays URL-free).
        "hasPptx": bool(item.get("pptxS3Key")),
    }
    if owner:
        summary["chatSessionId"] = _chat_session_id(item)
    return summary


# ---------------------------------------------------------------------------
# Style endpoints
# ---------------------------------------------------------------------------


def _display_html(htmls: List[str]) -> List[str]:
    """Display copies of style HTML: the catalog icons the styles reference, drawn in.

    The style files hold icon references only (what agents read); every response the
    Web UI renders goes through here. On any failure the HTML is returned as stored.
    """
    if not RESOURCE_BUCKET or not htmls:
        return htmls
    from sdpm.knowledge.assets.style_icons import inline_style_icons_many

    try:
        return inline_style_icons_many(
            htmls, load=lambda ids: user_library.load_catalog_icons(s3_client, RESOURCE_BUCKET, ids))
    except Exception as e:
        logger.warning(f"Style icons not drawn: {e}")
        return htmls


def _with_display_html(styles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Listing entries with their ``html`` replaced by the display copy."""
    shown = _display_html([style.get("html", "") for style in styles])
    return [{**style, "html": html} if "html" in style else style for style, html in zip(styles, shown)]


@app.get("/styles")
def list_styles() -> Dict[str, Any]:
    """List available styles with full HTML for client-side rendering.

    Includes builtin styles and user styles with pin/source metadata, one entry
    per name: a user style replaces the builtin style of the same name.

    Returns:
        Dict with styles list (name, description, html, pinned, source).
    """
    user_id = get_user_id(app.current_event)

    # Bundled styles (cached: references are static, deployed once)
    global _styles_cache  # noqa: PLW0603
    if _styles_cache is None and RESOURCE_BUCKET:
        _styles_cache = _with_display_html(user_library.list_builtin_styles(s3_client, RESOURCE_BUCKET))

    user_styles: List[Dict[str, Any]] = []
    try:
        user_styles = user_library.list_user_styles(s3_client, BUCKET_NAME, user_id, include_html=True)
    except Exception:
        pass
    user_styles = _with_display_html(user_styles)

    # One entry per name — a user style replaces the bundled one (same rule as Local and MCP)
    from sdpm.knowledge.reference import build_styles_listing

    styles = user_library.merge_styles(user_styles, _styles_cache or [])
    pinned = user_library.get_style_pins(table, user_id)
    return {"styles": build_styles_listing(styles, pinned, include_all=True)["styles"]}


@app.get("/styles/<name>")
def get_style(name: str) -> Dict[str, Any]:
    """Get full HTML for a single style (user or builtin).

    Returns:
        Dict with name, source, fullHtml (the stored file: Export / Copy) and html
        (the display copy with the referenced catalog icons drawn in).
    """
    if not user_library.is_valid_style_name(name):
        return {"error": "Invalid style name"}, 400

    user_id = get_user_id(app.current_event)

    # Try user style first
    user_key = user_library.user_style_key(user_id, name)
    try:
        body = s3_client.get_object(Bucket=BUCKET_NAME, Key=user_key)["Body"].read().decode("utf-8")
        return {"name": name, "fullHtml": body, "html": _display_html([body])[0], "source": "user"}
    except Exception:
        pass

    # Fall back to builtin
    if RESOURCE_BUCKET:
        builtin_key = user_library.builtin_style_key(name)
        try:
            body = s3_client.get_object(Bucket=RESOURCE_BUCKET, Key=builtin_key)["Body"].read().decode("utf-8")
            return {"name": name, "fullHtml": body, "html": _display_html([body])[0], "source": "builtin"}
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

    if not name or not user_library.is_valid_style_name(name):
        return {"error": "Invalid style name"}, 400

    user_id = get_user_id(app.current_event)
    current_pins = user_library.get_style_pins(table, user_id)

    if pinned and name not in current_pins:
        current_pins.append(name)
    elif not pinned and name in current_pins:
        current_pins.remove(name)

    user_library.put_style_pins(table, user_id, current_pins)
    return {"ok": True, "pinned_styles": current_pins}


@app.post("/styles/user")
def save_user_style() -> Dict[str, Any]:
    """Save a user style (import or copy).

    Body: {"name": str, "html": str}
    """
    body = app.current_event.json_body
    name = body.get("name", "")
    html = body.get("html", "")

    if not name or not user_library.is_valid_style_name(name):
        return {"error": "Invalid style name"}, 400
    if not html:
        return {"error": "html is required"}, 400

    user_id = get_user_id(app.current_event)
    key = user_library.user_style_key(user_id, name)
    s3_client.put_object(Bucket=BUCKET_NAME, Key=key, Body=html.encode("utf-8"), ContentType="text/html")
    return {"saved": name}


@app.delete("/styles/user/<style_name>")
def delete_user_style(style_name: str) -> Dict[str, Any]:
    """Delete a user style.

    Also removes from pins if pinned.
    """
    if not user_library.is_valid_style_name(style_name):
        return {"error": "Invalid style name"}, 400

    user_id = get_user_id(app.current_event)
    key = user_library.user_style_key(user_id, style_name)

    try:
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=key)
    except Exception:
        return {"error": f"Style not found: {style_name}"}, 404

    # Remove from pins
    current_pins = user_library.get_style_pins(table, user_id)
    if style_name in current_pins:
        current_pins.remove(style_name)
        user_library.put_style_pins(table, user_id, current_pins)

    return {"deleted": style_name}


@app.patch("/styles/user/<style_name>")
def rename_user_style(style_name: str) -> Dict[str, Any]:
    """Rename a user style.

    Body: {"newName": str}
    """
    body = app.current_event.json_body
    new_name = body.get("newName", "")

    if not user_library.is_valid_style_name(style_name):
        return {"error": "Invalid style name"}, 400
    if not new_name or not user_library.is_valid_style_name(new_name):
        return {"error": "Invalid new name"}, 400

    user_id = get_user_id(app.current_event)
    old_key = user_library.user_style_key(user_id, style_name)
    new_key = user_library.user_style_key(user_id, new_name)

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
    current_pins = user_library.get_style_pins(table, user_id)
    if style_name in current_pins:
        current_pins[current_pins.index(style_name)] = new_name
        user_library.put_style_pins(table, user_id, current_pins)

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

    # --- Builtin: S3 source of truth, DDB analysis cache ---
    builtins = user_library.list_builtin_templates(s3_client, table, RESOURCE_BUCKET) if RESOURCE_BUCKET else []

    # Per-user notes overlay builtin metadata without modifying shared cache rows.
    builtin_notes = user_library.list_builtin_template_notes(table, user_id) if builtins else {}

    # Build builtin list with lazy analysis
    to_analyze: List[Dict[str, Any]] = []
    for builtin in builtins:
        name = builtin["name"]
        if builtin["fresh"]:
            cached = builtin["cache"]
            analysis = user_library.parse_analysis(cached.get("analysisJson", ""))
            templates.append({
                "name": name,
                "source": "builtin",
                "description": builtin_notes.get(name, cached.get("description", "")),
                "theme_colors": analysis.get("theme_colors", {}),
                "fonts": cached.get("fonts", {}),
                "layout_count": len(analysis.get("layouts", [])),
            })
        else:
            to_analyze.append(builtin)
            templates.append({
                "name": name,
                "source": "builtin",
                "description": builtin_notes.get(name, ""),
                "theme_colors": {},
                "fonts": {},
                "layout_count": 0,
            })

    # Lazy analyze uncached builtins (async would be better but keep simple)
    if to_analyze:
        from sdpm.engine.analyzer import analyze_template as _analyze

        # TemporaryDirectory (not mkdtemp): warm Lambda containers keep /tmp between invocations
        with tempfile.TemporaryDirectory() as tmp:
            for builtin in to_analyze:
                name = builtin["name"]
                tpl_path = Path(tmp) / f"{name}.pptx"
                s3_client.download_file(RESOURCE_BUCKET, builtin["s3Key"], str(tpl_path))
                analysis = _analyze(tpl_path)
                table.put_item(Item=user_library.builtin_template_cache_item(
                    name, builtin["s3Key"], builtin["s3ETag"], analysis,
                ))
                # Update the placeholder in templates list
                for t in templates:
                    if t["name"] == name and t["source"] == "builtin":
                        t["theme_colors"] = analysis.get("theme_colors", {})
                        t["fonts"] = analysis.get("fonts", {})
                        t["layout_count"] = len(analysis.get("layouts", []))
                        break

    # --- User templates: DDB source of truth ---
    for t in user_library.list_user_templates(table, user_id):
        analysis = user_library.parse_analysis(t.get("analysisJson", ""))
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

    disposition = f'attachment; filename="{name}.pptx"'

    # Try user template
    user_key = user_library.user_template_s3_key(user_id, name)
    try:
        s3_client.head_object(Bucket=BUCKET_NAME, Key=user_key)
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": BUCKET_NAME,
                "Key": user_key,
                "ResponseContentDisposition": disposition,
            },
            ExpiresIn=300,
        )
        return {"downloadUrl": url}
    except Exception:
        pass

    # Try builtin (S3 source of truth)
    builtin_key = user_library.builtin_template_s3_key(name)
    try:
        s3_client.head_object(Bucket=RESOURCE_BUCKET, Key=builtin_key)
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": RESOURCE_BUCKET,
                "Key": builtin_key,
                "ResponseContentDisposition": disposition,
            },
            ExpiresIn=300,
        )
        return {"downloadUrl": url}
    except Exception:
        return {"error": "Template not found"}, 404


@app.patch("/templates/builtin/<name>")
def patch_builtin_template_note(name: str) -> Dict[str, Any]:
    """Create, update, or clear the current user's note for a builtin template.

    Body: {"description": str}. Blank descriptions clear the user overlay.
    """
    user_id = get_user_id(app.current_event)
    body = app.current_event.json_body or {}
    description_raw = body.get("description")
    if not isinstance(description_raw, str):
        return {"error": "Description must be a string"}, 400
    if not name or not re.fullmatch(r"[a-zA-Z0-9_\-\s.()]+", name):
        return {"error": "Invalid template name"}, 400

    # Notes can only target builtin templates that currently exist in S3.
    try:
        s3_client.head_object(Bucket=RESOURCE_BUCKET, Key=user_library.builtin_template_s3_key(name))
    except Exception:
        return {"error": "Template not found"}, 404

    key = builtin_note_key(user_id, name)
    description = description_raw.strip()
    if not description:
        table.delete_item(Key=key)
    else:
        table.put_item(Item={
            **key,
            "name": name,
            "description": description,
            "updatedAt": now_iso(),
        })
    return {"updated": name, "description": description}


@app.post("/templates/user/upload-url")
def presign_template_upload() -> Dict[str, Any]:
    """Generate a presigned PUT URL for template upload to S3."""
    user_id = get_user_id(app.current_event)
    body = app.current_event.json_body

    name: str = body.get("name", "").strip()
    if not name or not re.fullmatch(r"[a-zA-Z0-9_\-\s.()]+", name):
        return {"error": "Invalid template name"}, 400

    # Duplicate check
    existing = table.get_item(Key=user_template_key(user_id, name))
    if existing.get("Item"):
        return {"error": f'Template "{name}" already exists'}, 409

    s3_key = user_library.user_template_s3_key(user_id, name)
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

    s3_key = user_library.user_template_s3_key(user_id, name)

    # Verify file exists in S3
    try:
        s3_client.head_object(Bucket=BUCKET_NAME, Key=s3_key)
    except Exception:
        return {"error": "File not found in S3. Upload via presigned URL first."}, 400

    from sdpm.engine.analyzer import analyze_template as _analyze

    # Download and analyze. TemporaryDirectory (not mkdtemp): warm Lambda
    # containers keep /tmp between invocations.
    with tempfile.TemporaryDirectory() as tmp:
        tpl_path = Path(tmp) / f"{name}.pptx"
        s3_client.download_file(BUCKET_NAME, s3_key, str(tpl_path))
        analysis = _analyze(tpl_path)
    metadata = {
        "description": description,
        "fonts": analysis.get("fonts", {}),
        "analysisJson": json.dumps(analysis, ensure_ascii=False),
    }

    # Store in DDB
    table.put_item(Item={
        **user_template_key(user_id, name),
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
    resp = table.get_item(Key=user_template_key(user_id, name))
    if not resp.get("Item"):
        return {"error": "Template not found"}, 404

    s3_key = user_library.user_template_s3_key(user_id, name)
    s3_client.delete_object(Bucket=BUCKET_NAME, Key=s3_key)
    table.delete_item(Key=user_template_key(user_id, name))

    return {"deleted": name}


@app.patch("/templates/user/<name>")
def patch_user_template(name: str) -> Dict[str, Any]:
    """Rename or update description of a user template.

    Body: {"newName": str} or {"description": str}
    """
    user_id = get_user_id(app.current_event)
    body = app.current_event.json_body

    resp = table.get_item(Key=user_template_key(user_id, name))
    item = resp.get("Item")
    if not item:
        return {"error": "Template not found"}, 404

    # Rename
    new_name = body.get("newName", "").strip()
    if new_name:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", new_name):
            return {"error": "Letters, numbers, hyphens, underscores only"}, 400
        # Check duplicate
        dup = table.get_item(Key=user_template_key(user_id, new_name))
        if dup.get("Item"):
            return {"error": "Name already exists"}, 409
        # S3 copy + delete
        old_key = user_library.user_template_s3_key(user_id, name)
        new_key = user_library.user_template_s3_key(user_id, new_name)
        s3_client.copy_object(
            Bucket=BUCKET_NAME,
            CopySource={"Bucket": BUCKET_NAME, "Key": old_key},
            Key=new_key,
        )
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=old_key)
        # DDB: delete old, put new
        table.delete_item(Key=user_template_key(user_id, name))
        item["SK"] = user_template_sk(new_name)
        item["name"] = new_name
        item["s3Key"] = new_key
        table.put_item(Item=item)
        return {"renamed": {"from": name, "to": new_name}}

    # Update description
    description = body.get("description")
    if description is not None:
        table.update_item(
            Key=user_template_key(user_id, name),
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

    decks = [_deck_summary(item, extras, owner=True) for item in items]
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


def _read_deck_json(deck_id: str) -> Dict[str, Any]:
    """deck.json as a dict ({} when missing, unreadable or not an object)."""
    try:
        dj_resp = s3_client.get_object(Bucket=BUCKET_NAME, Key=f"decks/{deck_id}/deck.json")
        data = json.loads(dj_resp["Body"].read())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _read_outline_slugs(deck_id: str) -> List[str]:
    """Slugs from specs/outline.md in order ([] when missing), as the build reads them."""
    from sdpm.engine.schema import parse_outline_text

    try:
        outline_resp = s3_client.get_object(Bucket=BUCKET_NAME, Key=f"decks/{deck_id}/specs/outline.md")
        return parse_outline_text(outline_resp["Body"].read().decode("utf-8"))
    except Exception:
        return []


def _read_specs(deck_id: str) -> Dict[str, Any]:
    """Read spec files from S3 (brief.md, outline.md, art-direction.html/.md)."""
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
                # the Web UI shows the deck's style copy: draw its referenced icons
                art_direction_content = _display_html([content])[0] if ext == ".html" else content
                break
        except Exception:
            pass
    specs["artDirection"] = art_direction_content
    return specs


_SCRIPT_WARNING_KINDS = frozenset({"navigation", "popup", "external-url", "webrtc"})
_SCRIPT_WARNINGS_MAX = 200


def _script_warnings(raw: Any) -> List[Dict[str, Any]]:
    """The record's htmlScriptExternal as ``[{slug, kinds}]``: at most 200 entries with a
    slide slug and known kinds; anything else is dropped."""
    from sdpm.engine.schema import SLUG_RE

    out: List[Dict[str, Any]] = []
    for entry in raw if isinstance(raw, list) else []:
        if len(out) >= _SCRIPT_WARNINGS_MAX:
            break
        if not isinstance(entry, dict):
            continue
        slug, kinds = entry.get("slug"), entry.get("kinds")
        if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
            continue
        if not isinstance(kinds, list) or not all(isinstance(k, str) and k in _SCRIPT_WARNING_KINDS for k in kinds):
            continue
        out.append({"slug": slug, "kinds": list(kinds)})
    return out


def _chat_session_id(deck: Dict[str, Any]) -> Optional[str]:
    """The Web UI chat session a deck belongs to, or None.

    ``chatSessionId`` is the link the browser PATCHes once the deck appears. When
    that never arrived (tab closed, failed request, no browser), the MCP server's
    record of the creating session stands in: the agent sends the chat's runtime
    session id as ``Mcp-Session-Id`` unchanged when it already belongs to the user
    (``owned_mcp_session_id`` in agent/mcp_clients.py), and ``init_deck_workspace``
    is an orchestrator tool, so it never carries a composer group suffix. Ids that
    are not the owner's own (another client's MCP session) are not chat sessions.
    """
    linked = deck.get("chatSessionId")
    if linked:
        return linked
    created_in = deck.get("createdInMcpSession")
    if created_in and belongs_to(created_in, deck.get("createdBy", "")):
        return created_in
    return None


def _owner_chat_session_id(decision: Any) -> Optional[str]:
    """The deck's chat session id for its owner; None for anyone else."""
    return _chat_session_id(decision.deck) if decision.role == "owner" else None


def _get_html_deck(deck_id: str, decision: Any, deck_json: Dict[str, Any]) -> Dict[str, Any]:
    """get_deck response for an HTML deck (outputFormat "html").

    Slides are the outline slugs whose slides/{slug}.html exists; previews are
    the static per-slide HTML thumbnails. Every HTML URL is an S3 presign.
    scriptWarnings lists the slides whose script can reach outside the deck.
    """
    deck = decision.deck
    resp = s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"decks/{deck_id}/slides/")
    slide_keys = [obj["Key"] for obj in resp.get("Contents", [])]
    slugs = html_slide_slugs(_read_outline_slugs(deck_id), slide_keys, deck_id)

    preview_map = _list_html_preview_map(deck_id)
    slides = []
    for slug in slugs:
        key = preview_map.get(slug)
        slides.append({"slug": slug, "previewUrl": _html_presigned(key) if key else None})

    html_key = deck.get("htmlS3Key")
    return {
        "deckId": deck_id,
        "name": deck.get("name", "Untitled"),
        "slideCount": len(slides),
        "slides": slides,
        "specs": _read_specs(deck_id),
        "template": deck_json.get("template") or None,
        "defsUrl": None,
        "pptxUrl": None,
        "outputFormat": "html",
        "htmlUrl": _html_presigned(html_key) if html_key else None,
        "scriptWarnings": _script_warnings(deck.get("htmlScriptExternal")),
        "slideSize": slide_size(deck_json),
        "updatedAt": deck.get("updatedAt", ""),
        "chatSessionId": _owner_chat_session_id(decision),
        "isOwner": decision.role == "owner",
        "role": decision.role,
        "visibility": deck.get("visibility", "private"),
    }


@app.get("/decks/<deck_id>/html")
def get_deck_html(deck_id: str) -> Any:
    """Presigned S3 URL of the built HTML deck.

    Query params:
        purpose: "present" (inline, 4 h) or "download" (attachment, 15 min).

    Same read permission as get_deck (owner, or viewer of a public deck). The URL is on the S3 regional endpoint, never CloudFront.

    Returns:
        Dict with url and expiresIn (seconds).
    """
    user_id = get_user_id(app.current_event)

    decision = authorize(user_id, deck_id, "read", table)
    if not decision.allowed:
        return {"error": decision.reason}, 403

    purpose = app.current_event.get_query_string_value("purpose") or ""
    if purpose not in HTML_PURPOSES:
        return {"error": "purpose must be 'present' or 'download'"}, 400

    deck = decision.deck
    html_key = deck.get("htmlS3Key")
    if not html_key:
        return {"error": "HTML not built yet"}, 404

    try:
        url, expires = presigned_html_url(
            html_s3_client, BUCKET_NAME, html_key, purpose, deck.get("name", ""),
        )
    except ValueError:
        logger.warning(f"Deck {deck_id} has a non-HTML htmlS3Key")
        return {"error": "HTML not built yet"}, 404
    return {"url": url, "expiresIn": expires}



@app.get("/decks/<deck_id>/pptx")
def get_deck_pptx(deck_id: str) -> Any:
    """Signed URL that downloads the built PPTX as ``<deck title>.pptx`` (15 min).

    Same read permission as get_deck (owner, or viewer of a public deck); 404 when no
    PPTX is built or the deck is an HTML deck (get_deck gives those no pptxUrl either).

    Returns:
        Dict with url and expiresIn (seconds).
    """
    user_id = get_user_id(app.current_event)

    decision = authorize(user_id, deck_id, "read", table)
    if not decision.allowed:
        return {"error": decision.reason}, 403

    deck = decision.deck
    pptx_key = deck.get("pptxS3Key")
    url = _pptx_download_url(pptx_key, deck.get("name", "")) if pptx_key else None
    if not url or is_html_deck(_read_deck_json(deck_id)):
        return {"error": "PPTX not built yet"}, 404
    return {"url": url, "expiresIn": PRESIGNED_URL_EXPIRY}


@app.get("/decks/<deck_id>")
def get_deck(deck_id: str) -> Dict[str, Any]:
    """Get deck details with presigned URLs. Reads slides from S3 (deck.json + slides/*.json)."""
    user_id = get_user_id(app.current_event)

    decision = authorize(user_id, deck_id, "read", table)
    if not decision.allowed:
        return {"error": decision.reason}, 403

    deck = decision.deck
    deck_json = _read_deck_json(deck_id)
    if is_html_deck(deck_json):
        return _get_html_deck(deck_id, decision, deck_json)

    pptx_key = deck.get("pptxS3Key")

    # Read slides from S3 (deck.json + slides/*.json format)
    slides = []

    # Live-preview payloads: slug → latest compose/{slug}_{epoch}.json (defs included)
    from shared.artifact_keys import COMPOSE_DEFS, compose_prefix, latest_compose_keys

    compose_keys: List[str] = []
    try:
        listed = s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=compose_prefix(deck_id))
        compose_keys = [obj["Key"] for obj in listed.get("Contents", [])]
    except Exception:
        pass
    latest_compose = latest_compose_keys(compose_keys, compose_prefix(deck_id))

    defs_key = latest_compose.get(COMPOSE_DEFS)
    has_defs = defs_key is not None

    # outline.md for slug order, then slides/*.json
    slugs = _read_outline_slugs(deck_id)

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
        if legacy_slides is None:
            # A slug whose slides/{slug}.json is missing or unreadable is not listed.
            try:
                slide_resp = s3_client.get_object(Bucket=BUCKET_NAME, Key=f"decks/{deck_id}/slides/{slug}.json")
                json.loads(slide_resp["Body"].read())
            except Exception:
                continue
        slide_preview = _resolve_preview_url(deck_id, slug, preview_keys)
        slide_entry: Dict[str, Any] = {"slug": slug, "previewUrl": slide_preview}
        compose_key = latest_compose.get(slug) or latest_compose.get(f"slide_{i + 1}")
        if compose_key:
            slide_entry["composeUrl"] = preview_url(compose_key)
        slides.append(slide_entry)

    specs = _read_specs(deck_id)

    # Confirmed template name from deck.json (written by the agent at Art Direction)
    template = deck_json.get("template") or None

    return {
        "deckId": deck_id,
        "name": deck.get("name", "Untitled"),
        "slideCount": len(slides),
        "slides": slides,
        "specs": specs,
        "template": template,
        "defsUrl": preview_url(defs_key) if has_defs else None,
        "pptxUrl": _pptx_download_url(pptx_key, deck.get("name", "")) if pptx_key else None,
        "slideSize": slide_size(deck_json),
        "updatedAt": deck.get("updatedAt", ""),
        "chatSessionId": _owner_chat_session_id(decision),
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


@app.put("/decks/<deck_id>/specs/outline")
def put_outline(deck_id: str) -> Dict[str, Any]:
    """Write `specs/outline.md` from the Web UI storyboard editor.

    Unconditional overwrite by design: the editor tells the agent what changed in the same
    turn (a user message carrying the diff), so the agent — not the API — reconciles its own
    context. Only the owner may write (same permission as editing slides).

    Args:
        deck_id: Deck identifier.

    Returns:
        Dict with the number of bytes written.
    """
    user_id = get_user_id(app.current_event)
    decision = authorize(user_id, deck_id, "edit_slide", table)
    if not decision.allowed:
        return {"error": decision.reason}, 403

    body = app.current_event.json_body or {}
    content = body.get("content")
    error = validate_outline_content(content)
    if error:
        return {"error": error}, 400

    data = content.encode("utf-8")
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=f"decks/{deck_id}/specs/outline.md",
        Body=data,
        ContentType="text/markdown; charset=utf-8",
    )
    if decision.deck:
        table.update_item(
            Key={"PK": decision.deck["PK"], "SK": decision.deck["SK"]},
            UpdateExpression="SET updatedAt = :t",
            ExpressionAttributeValues={":t": now_iso()},
        )
    return {"bytes": len(data)}


def _review_key(deck_id: str, review_id: str) -> str:
    """S3 key of a review file; ``review_id`` comes from ``new_review_id``."""
    return f"decks/{deck_id}/{review_path(review_id)}"


def _slide_slugs(deck_id: str) -> set:
    """Slugs that have a slides/<slug>.json or slides/<slug>.html object."""
    prefix = f"decks/{deck_id}/slides/"
    resp = s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix)
    slugs = set()
    for obj in resp.get("Contents", []):
        name = obj["Key"][len(prefix):]
        for ext in (".json", ".html"):
            if name.endswith(ext) and "/" not in name:
                slugs.add(name[: -len(ext)])
    return slugs


def _delete_reviews(deck_id: str) -> None:
    """Delete every object under the deck's reviews/ (a review file is used once)."""
    paginator = s3_client.get_paginator("list_objects_v2")
    keys = [
        obj["Key"]
        for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=f"decks/{deck_id}/reviews/")
        for obj in page.get("Contents", [])
    ]
    for key in keys:
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=key)


def _object_exists(key: str) -> bool:
    try:
        s3_client.head_object(Bucket=BUCKET_NAME, Key=key)
    except Exception:
        return False
    return True


@app.post("/decks/<deck_id>/reviews")
def create_review(deck_id: str) -> Any:
    """Create a change request from the Web UI comment tool.

    Replaces the deck's review file: deletes everything under ``reviews/`` (the file is a
    disposable hand-off, and the Web UI only sends while the agent is idle), then writes
    ``reviews/<id>.json`` (what was sent plus the composers' guide; nobody rewrites it) and
    returns the chat message the Web UI sends to the orchestrator. The server picks the
    id and takes slide_size from deck.json; the client sends only
    ``{note, comments: [{name, slide, rect, text}]}``. Only the owner may write (same
    permission as editing slides).

    Args:
        deck_id: Deck identifier.

    Returns:
        ``{"id": review id, "message": chat message}``.
    """
    user_id = get_user_id(app.current_event)
    decision = authorize(user_id, deck_id, "edit_slide", table)
    if not decision.allowed:
        return {"error": decision.reason}, 403

    raw = app.current_event.body or ""
    if len(raw.encode("utf-8")) > REVIEW_MAX_BODY_BYTES:
        return {"error": f"body exceeds {REVIEW_MAX_BODY_BYTES} bytes"}, 413
    try:
        body = app.current_event.json_body
    except Exception:
        return {"error": "Invalid JSON"}, 400

    size = slide_size_of(_read_deck_json(deck_id))
    slugs = _slide_slugs(deck_id)
    normalized, error = validate_review_submission(body, size, lambda slug: slug in slugs)
    if error:
        return {"error": error}, 400

    _delete_reviews(deck_id)
    for _ in range(3):
        review_id = new_review_id(datetime.now(timezone.utc))
        key = _review_key(deck_id, review_id)
        if not _object_exists(key):
            break
    else:
        return {"error": "Could not allocate a review id"}, 409

    review = build_review_file(review_id, size, normalized)
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=json.dumps(review, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )
    return {"id": review_id, "message": build_review_message(review_id, normalized)}


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
    seen_html_decks: Dict[str, Dict[str, str]] = {}
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
            if not slide_preview_url:
                # HTML decks keep static per-slide previews under html/{deck}/preview/
                if deck_id not in seen_html_decks:
                    try:
                        seen_html_decks[deck_id] = _list_html_preview_map(deck_id)
                    except Exception:
                        seen_html_decks[deck_id] = {}
                html_key = seen_html_decks[deck_id].get(slide_id)
                slide_preview_url = _html_presigned(html_key) if html_key else None
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
        FilterExpression=Attr("chatSessionId").eq(session_id) | Attr("createdInMcpSession").eq(session_id),
        ProjectionExpression="chatSessionId, createdInMcpSession, createdBy",
    )
    if not any(_chat_session_id(item) == session_id for item in resp.get("Items", [])):
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

        # Keep the response under Lambda's 6MB limit (see chat_history.py):
        # toolResult bodies and giant toolUse inputs are UI-irrelevant; the
        # agent reads AgentCore Memory directly, not via this API.
        strip_tool_result_content(messages)
        truncate_tool_inputs(messages)
        messages, truncated = cap_messages_size(messages)
        if truncated:
            logger.warning(
                "Chat history for session %s exceeded size budget — oldest messages dropped",
                session_id,
            )
            return {"messages": messages, "truncated": True}
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


def _cf_signed_url(s3_key: str, expires_in: int = 900, query: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Generate a CloudFront signed URL for an S3 key.

    Args:
        s3_key: S3 object key (e.g. previews/deck_id/slide_01.webp).
        expires_in: URL validity in seconds (default 15 min).
        query: Query parameters for the origin (e.g. response-content-disposition).
            Percent-encoded once and part of the signed policy's Resource, so they
            cannot be changed or dropped without breaking the signature.

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
    if query:
        from urllib.parse import urlencode, quote

        url = f"{url}?{urlencode(query, quote_via=quote, safe='')}"

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

    sep = "&" if query else "?"
    return f"{url}{sep}Policy={_b64(policy.encode())}&Signature={_b64(sig_raw)}&Key-Pair-Id={CF_KEY_PAIR_ID}"


# ---------------------------------------------------------------------------
# Attachment raw-upload endpoint
# ---------------------------------------------------------------------------

ALLOWED_CONTENT_TYPES = {
    "text/plain", "text/markdown", "text/csv", "text/html", "application/json",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml",
}
# Per-user raw attachment caps. These are safety valves against runaway
# automation and leaked-token cost exposure — not usage discipline for
# legitimate users. Defaults are deliberately generous for an internal /
# team deployment (PPTX sources can be ~100MB each); override via Lambda
# environment variables if your deployment needs tighter or looser bounds.
CLOUD_RAW_MAX_OBJECTS = int(os.environ.get("ATTACHMENT_MAX_OBJECTS", "1000"))
CLOUD_RAW_MAX_BYTES = int(os.environ.get("ATTACHMENT_MAX_BYTES", str(50 * 1024 * 1024 * 1024)))


def _raw_attachment_usage(user_id: str) -> tuple[int, int]:
    """Return current raw-object count and bytes for one user."""
    count = 0
    total_bytes = 0
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=f"uploads/{user_id}/"):
        objects = page.get("Contents", [])
        count += len(objects)
        total_bytes += sum(int(obj.get("Size", 0)) for obj in objects)
        if count >= CLOUD_RAW_MAX_OBJECTS or total_bytes >= CLOUD_RAW_MAX_BYTES:
            break
    return count, total_bytes


def _sanitize_attachment_filename(name: str) -> str:
    """Return a single safe UTF-8 filename for an attachment source key."""
    name = name.replace("/", "_").replace("\\", "_").replace("..", "_")
    name = "".join(c for c in name if ord(c) >= 0x20 and ord(c) != 0x7F).lstrip(".")
    encoded = name.encode("utf-8")[:255]
    name = encoded.decode("utf-8", errors="ignore")
    if not name or name.startswith("[Attached:"):
        raise ValueError("Invalid fileName")
    return name


@app.post("/attachments/presign")
def presign_attachment() -> Dict[str, Any]:
    """Presign one immutable raw attachment PUT; no processing state is created."""
    user_id = get_user_id(app.current_event)
    body = app.current_event.json_body or {}

    try:
        file_name = _sanitize_attachment_filename(str(body.get("fileName", "")))
        file_size = int(body.get("fileSize", 0))
    except (TypeError, ValueError):
        return {"error": "Valid fileName and fileSize are required"}, 400

    content_type = str(body.get("contentType", "")).split(";", 1)[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        return {"error": f"Unsupported file type: {content_type or 'unknown'}"}, 400
    if file_size < 0 or file_size > MAX_FILE_SIZE:
        return {"error": f"fileSize must be between 0 and {MAX_FILE_SIZE} bytes"}, 400

    object_count, stored_bytes = _raw_attachment_usage(user_id)
    if object_count >= CLOUD_RAW_MAX_OBJECTS or stored_bytes + file_size > CLOUD_RAW_MAX_BYTES:
        return {"error": "Raw attachment quota exceeded"}, 429

    # The S3 key is per user; the browser and the agent get the handle without the
    # user id, which the MCP server resolves back to this key for the same caller.
    upload_id = uuid.uuid4()
    key = f"uploads/{user_id}/{upload_id}/{file_name}"
    presigned_url = s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": BUCKET_NAME,
            "Key": key,
            "ContentType": content_type,
            "IfNoneMatch": "*",
            "Tagging": "sdpm-class=attachment-source",
        },
        ExpiresIn=PRESIGNED_URL_EXPIRY,
    )
    return {
        "source": f"uploads/{upload_id}/{file_name}",
        "presignedUrl": presigned_url,
        "requiredHeaders": {
            "Content-Type": content_type,
            "If-None-Match": "*",
            "x-amz-tagging": "sdpm-class=attachment-source",
        },
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
