# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unified API Lambda — protected by Cognito authorizer with least-privilege IAM.

IAM roles follow least-privilege: Lambda has scoped access to DynamoDB and S3 only.
Cognito JWT claims are used for user identity and authorization.

Unified API Lambda — deck, upload, chat endpoints.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

Single Lambda with Powertools APIGatewayRestResolver.
Ported from spec-driven-presentation-maker-web deck-api, upload-api.
"""

import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional

import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.event_handler import APIGatewayRestResolver, CORSConfig
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
app = APIGatewayRestResolver(cors=cors_config)

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


def _get_deck_extras(deck_items: List[Dict]) -> Dict[str, Dict]:
    """Get thumbnail URLs for deck items.

    Reads presentation.json from S3 only when needed for thumbnail fallback.
    slideCount comes from DDB (written by generate_pptx).

    Args:
        deck_items: List of DDB deck records.

    Returns:
        Dict mapping deckId to {"thumbnailUrl": str|None}.
    """
    extras: Dict[str, Dict] = {}
    for deck in deck_items:
        deck_id = extract_deck_id(deck["SK"])
        thumb_url = None

        key = deck.get("thumbnailS3Key")
        if key:
            thumb_url = presigned_url(s3_client, BUCKET_NAME, key)
        else:
            # Fallback: first slide PNG uses sequential naming (slide_01.png)
            s3_key = f"previews/{deck_id}/slide_01.png"
            try:
                s3_client.head_object(Bucket=BUCKET_NAME, Key=s3_key)
                thumb_url = presigned_url(s3_client, BUCKET_NAME, s3_key)
            except Exception:
                pass

        extras[deck_id] = {"thumbnailUrl": thumb_url}
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
    """Extract <head> + first <div class="slide"> from a style HTML.

    Args:
        html: Full style HTML string.

    Returns:
        Minimal HTML with styles and first slide only.
    """
    head_end = html.find("</head>")
    if head_end == -1:
        return ""
    first_slide = html.find('<div class="slide">')
    if first_slide == -1:
        return ""
    # Find end of first slide: next slide or </body>
    next_slide = html.find('<div class="slide">', first_slide + 1)
    end = next_slide if next_slide != -1 else html.find("</body>", first_slide)
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

    Returns:
        Dict with styles list (name, description, coverHtml).
    """
    global _styles_cache  # noqa: PLW0603
    if _styles_cache is not None:
        return {"styles": _styles_cache}

    if not RESOURCE_BUCKET:
        return {"styles": []}

    prefix = "references/examples/styles/"
    resp = s3_client.list_objects_v2(Bucket=RESOURCE_BUCKET, Prefix=prefix)
    styles: List[Dict[str, str]] = []
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
        styles.append({"name": name, "description": description, "coverHtml": _extract_cover_html(body)})

    _styles_cache = styles
    return {"styles": styles}


@app.get("/styles/<name>")
def get_style(name: str) -> Dict[str, Any]:
    """Get full HTML for a single style.

    Returns:
        Dict with name and fullHtml.
    """
    if not RESOURCE_BUCKET:
        return {"error": f"Style not found: {name}"}, 404
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        return {"error": "Invalid style name"}, 400
    key = f"references/examples/styles/{name}.html"
    try:
        body = s3_client.get_object(Bucket=RESOURCE_BUCKET, Key=key)["Body"].read().decode("utf-8")
    except Exception:
        return {"error": f"Style not found: {name}"}, 404
    return {"name": name, "fullHtml": body}


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
    """Get deck details with presigned URLs. Reads slides from S3 presentation.json."""
    user_id = get_user_id(app.current_event)

    decision = authorize(user_id, deck_id, "read", table)
    if not decision.allowed:
        return {"error": decision.reason}, 403

    deck = decision.deck
    pptx_key = deck.get("pptxS3Key")

    # Read presentation.json from S3
    slides = []
    include_json = (app.current_event.get_query_string_value("include") or "") == "slideJson"
    try:
        pres_key = f"decks/{deck_id}/presentation.json"
        resp = s3_client.get_object(Bucket=BUCKET_NAME, Key=pres_key)
        presentation = json.loads(resp["Body"].read())
        for i, s in enumerate(presentation.get("slides", [])):
            sid = f"slide_{i + 1:02d}"
            preview_key = f"previews/{deck_id}/{sid}.png"
            preview_url = None
            try:
                s3_client.head_object(Bucket=BUCKET_NAME, Key=preview_key)
                preview_url = presigned_url(s3_client, BUCKET_NAME, preview_key)
            except Exception:
                pass
            slide_entry: Dict[str, Any] = {"slideId": sid, "previewUrl": preview_url}
            if include_json:
                slide_entry["slideJson"] = json.dumps(s)
            slides.append(slide_entry)
    except Exception:
        pass

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
        "pptxUrl": presigned_url(s3_client, BUCKET_NAME, pptx_key) if pptx_key else None,
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
    for r in response.get("retrievalResults", []):
        meta = r.get("metadata", {})
        deck_id = meta.get("deckId", "")
        slide_id = meta.get("slideId", "")
        dedup_key = (deck_id, slide_id)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # Generate preview URL — slideId matches PNG filename (e.g. slide_01.png)
        preview_url = ""
        if deck_id and slide_id:
            s3_key = f"previews/{deck_id}/{slide_id}.png"
            try:
                s3_client.head_object(Bucket=BUCKET_NAME, Key=s3_key)
                preview_url = presigned_url(s3_client, BUCKET_NAME, s3_key)
            except Exception:
                pass

        results.append({
            "deckId": deck_id,
            "deckName": meta.get("deckName", ""),
            "slideId": slide_id,
            "pageNumber": int(meta.get("pageNumber", 0)),
            "score": r.get("score", 0),
            "excerpt": r.get("content", {}).get("text", "")[:200],
            "previewUrl": preview_url,
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
# Upload endpoints
# ---------------------------------------------------------------------------

ALLOWED_CONTENT_TYPES = {
    "text/plain", "text/markdown", "application/json", "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "image/png",
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


@app.post("/uploads/<upload_id>/process")
def process_upload(upload_id: str) -> Dict[str, Any]:
    """Process an uploaded file — extract text for text-based files."""
    user_id = get_user_id(app.current_event)
    body = app.current_event.json_body or {}
    session_id: str = body.get("sessionId", "")

    resp = table.get_item(Key={"PK": deck_pk(user_id), "SK": upload_sk(upload_id)})
    item = resp.get("Item")
    if not item:
        raise app.not_found()

    file_type = item.get("fileType", "")
    s3_key = item.get("s3KeyRaw", "")
    update_expr_parts = ["#st = :st", "sessionId = :sid"]
    expr_values: Dict[str, Any] = {":sid": session_id}
    expr_names = {"#st": "status"}

    extracted_text = None
    if file_type in _TEXT_EXTRACTABLE and s3_key:
        try:
            obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=s3_key)
            extracted_text = obj["Body"].read().decode("utf-8")
            update_expr_parts.append("extractedText = :et")
            expr_values[":et"] = extracted_text[:50000]  # cap at 50k chars
            expr_values[":st"] = "completed"
        except Exception:
            expr_values[":st"] = "completed"
    else:
        # Binary files (PDF, DOCX, PPTX, images): mark completed,
        # agent reads directly from S3 via presigned URL or further processing
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
