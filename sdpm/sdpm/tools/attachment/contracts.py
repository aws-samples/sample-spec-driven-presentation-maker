# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP tool contracts for read_attachment and import_attachment.

These are the port definitions. Adapters (Local/Remote) provide the source
materialization and bind these via `mcp.tool()`.

Tool signatures are identical across all surfaces (Local stdio, Local ACP,
Remote HTTP). The `surface` parameter is internal (not exposed to callers).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from sdpm.tools.attachment.cache import LocalStageCache
from sdpm.tools.attachment.limits import PAGING_DEFAULT_LIMIT, PAGING_MAX_LIMIT, PAGING_MIN_LIMIT
from sdpm.tools.attachment.pipeline import import_attachment_core, read_attachment_core
from sdpm.tools.attachment.source import classify_source, materialize_local_source, source_identity_local


def read_attachment(source: str, offset: int = 0, limit: int = PAGING_DEFAULT_LIMIT) -> dict[str, Any]:
    """Read an attachment: convert + text projection + guidance.

    Pure read — creates no state. Returns paged text with line numbers,
    or image metadata (adapter fills in Image content or path+colorAnalysis).

    Supported formats:
    - text/md/csv/html/json: UTF-8 paged text with line numbers
    - pdf/docx/xlsx: Markdown conversion → paged text
    - pptx: deck_text_summary + slideCount/themeHints + import guidance
    - image: metadata (adapter-specific: Cloud=Image content, Local=path+colorAnalysis)

    Args:
        source: Source identifier — absolute path (Local), S3 key (Cloud), or https:// URL.
        offset: 0-based UTF-8 byte offset into the text projection. Default 0.
        limit: Maximum UTF-8 bytes for the response (header + body). Default/max 10240, min 512.

    Returns:
        Dict with header (JSON metadata) and body (line-numbered text),
        or image metadata dict.
    """
    # Parameter validation
    if offset < 0:
        return {"error": {"code": "INVALID_OFFSET", "message": f"offset must be >= 0, got {offset}"}}
    if limit < PAGING_MIN_LIMIT or limit > PAGING_MAX_LIMIT:
        return {"error": {"code": "INVALID_LIMIT", "message": f"limit must be {PAGING_MIN_LIMIT}..{PAGING_MAX_LIMIT}, got {limit}"}}

    # Classify and validate source
    kind = classify_source(source)

    if kind == "url":
        # URL source: securely revalidate, then process the cached or fresh body.
        try:
            result = _fetch_url_cached_local(source)
        except Exception as e:
            return {"error": {"code": e.code if hasattr(e, "code") else "FETCH_ERROR", "message": str(e)}}

        # Write to temp file for processing
        with tempfile.NamedTemporaryFile(delete=False, suffix=_ext_from_url(source)) as tmp:
            tmp.write(result.data)
            tmp_path = Path(tmp.name)

        try:
            return read_attachment_core(
                materialized_path=tmp_path,
                source=source,
                offset=offset,
                limit=limit,
                content_type=result.content_type,
                source_identity={
                    "kind": "url",
                    "requestedUrl": source,
                    "finalUrl": result.final_url,
                    "etag": result.etag or "",
                    "lastModified": result.last_modified or "",
                    "size": len(result.data),
                },
                cache=LocalStageCache(),
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    elif kind == "local_path":
        try:
            original = Path(source)
            _touch_raw_lease(original)
            with materialize_local_source(source, allow_any_path=True) as snapshot:
                response = read_attachment_core(
                    materialized_path=snapshot,
                    source=source,
                    offset=offset,
                    limit=limit,
                    source_identity=source_identity_local(original),
                    cache=LocalStageCache(),
                )
                if response.get("kind") == "image":
                    response["path"] = str(original)
                return response
        except Exception as e:
            return {"error": {"code": getattr(e, "code", "VALIDATION_ERROR"), "message": str(e)}}

    else:
        # S3 key: Remote adapter handles this — contract only
        return {"error": {"code": "ADAPTER_REQUIRED", "message": "S3 source requires Remote adapter"}}


def import_attachment(source: str, deck_id: str, filename: str = "") -> dict[str, Any]:
    """Import an attachment into a deck — convert + commit to immutable bundle.

    Converts the source and commits the result atomically to:
      {deck_id}/attachments/imports/{importKey}/

    Same source + options = same importKey → no-op/reuse.
    The bundle is immutable after commit. Agent selects from it.

    Supported imports:
    - image: images/{hash}_{name} (webp→PNG) + image_mapping
    - pdf/docx/xlsx: extracted text + images
    - pptx: full deck structure (deck.json + slides/ + template.pptx)
    - URL: downloaded → processed as above

    Args:
        source: Source identifier — absolute path (Local), S3 key (Cloud), or https:// URL.
        deck_id: Deck directory path to import into.
        filename: Optional filename override (default: source filename).

    Returns:
        Dict with importKey, sourceHash, files list, imageMapping, etc.
        On timeout: {code: "IMPORT_INCOMPLETE", retryable: true, completedStages: [...],
                    nextAction: "Call import_attachment again with exactly the same source, deck_id, and filename."}
    """
    deck_dir = Path(deck_id)
    if not deck_dir.is_dir():
        return {"error": {"code": "DECK_NOT_FOUND", "message": f"Deck directory not found: {deck_id}"}}

    # Classify and validate source
    kind = classify_source(source)

    if kind == "url":
        # URL source: fetch, then import
        try:
            result = _fetch_url_cached_local(source)
        except Exception as e:
            return {"error": {"code": getattr(e, "code", "FETCH_ERROR"), "message": str(e)}}

        # Derive filename from URL if not provided
        if not filename and result.filename_from_header:
            filename = result.filename_from_header
        if not filename:
            from urllib.parse import urlparse
            parsed = urlparse(result.final_url)
            filename = Path(parsed.path).name or "attachment"

        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as tmp:
            tmp.write(result.data)
            tmp_path = Path(tmp.name)

        try:
            return import_attachment_core(
                materialized_path=tmp_path,
                source=source,
                deck_dir=deck_dir,
                filename=filename,
                content_type=result.content_type,
                source_identity={
                    "kind": "url",
                    "requestedUrl": source,
                    "finalUrl": result.final_url,
                    "etag": result.etag or "",
                    "lastModified": result.last_modified or "",
                    "size": len(result.data),
                },
                cache=LocalStageCache(),
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    elif kind == "local_path":
        try:
            original = Path(source)
            _touch_raw_lease(original)
            with materialize_local_source(source, allow_any_path=True) as snapshot:
                return import_attachment_core(
                    materialized_path=snapshot,
                    source=source,
                    deck_dir=deck_dir,
                    filename=filename or original.name,
                    source_identity=source_identity_local(original),
                    cache=LocalStageCache(),
                )
        except Exception as e:
            return {"error": {"code": getattr(e, "code", "VALIDATION_ERROR"), "message": str(e)}}

    else:
        # S3 key: Remote adapter handles this
        return {"error": {"code": "ADAPTER_REQUIRED", "message": "S3 source requires Remote adapter"}}


def _fetch_url_cached_local(source: str):
    """Securely revalidate a URL and reuse a checksum-verified local body on 304."""
    from sdpm.tools.attachment.fetcher import FetchResult, fetch_url

    cache = LocalStageCache()
    root = cache.base_dir / "url-cache"  # type: ignore[operator]
    url_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    index_path = root / "indexes" / f"{url_hash}.json"
    index: dict[str, Any] | None = None
    try:
        candidate = json.loads(index_path.read_text(encoding="utf-8"))
        if isinstance(candidate, dict):
            index = candidate
    except (OSError, json.JSONDecodeError):
        pass

    if index is None:
        result = fetch_url(source)
    else:
        result = fetch_url(
            source,
            etag=index.get("etag") or None,
            last_modified=index.get("lastModified") or None,
        )

    if result.not_modified:
        if index is None:
            raise RuntimeError("URL returned 304 without a cache index")
        body_sha = str(index.get("bodySha256", ""))
        body_path = root / "bodies" / body_sha
        body = body_path.read_bytes()
        if hashlib.sha256(body).hexdigest() != body_sha or len(body) != int(index.get("size", -1)):
            raise RuntimeError("Cached URL body failed checksum verification")
        return FetchResult(
            data=body,
            final_url=str(index.get("finalUrl") or source),
            content_type=index.get("contentType"),
            content_length=len(body),
            etag=result.etag or index.get("etag"),
            last_modified=result.last_modified or index.get("lastModified"),
            filename_from_header=index.get("filename"),
        )

    body_sha = hashlib.sha256(result.data).hexdigest()
    body_path = root / "bodies" / body_sha
    body_path.parent.mkdir(parents=True, exist_ok=True)
    if not body_path.exists():
        descriptor, temporary_name = tempfile.mkstemp(dir=body_path.parent, prefix=".body-")
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(result.data)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.chmod(temporary_name, 0o600)
            try:
                os.link(temporary_name, body_path)
            except FileExistsError:
                pass
        finally:
            Path(temporary_name).unlink(missing_ok=True)

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_data = {
        "etag": result.etag,
        "lastModified": result.last_modified,
        "contentType": result.content_type,
        "filename": result.filename_from_header,
        "size": len(result.data),
        "bodySha256": body_sha,
        "finalUrl": result.final_url,
    }
    descriptor, temporary_name = tempfile.mkstemp(dir=index_path.parent, prefix=".index-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            json.dump(index_data, temporary, ensure_ascii=False, separators=(",", ":"))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, index_path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    return result


def _ext_from_url(url: str) -> str:
    """Extract file extension from URL path."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path = Path(parsed.path)
    return path.suffix if path.suffix else ""


def _touch_raw_lease(path: Path) -> None:
    """Keep Local Web raw sources alive while read/import is active."""
    if path.parent.parent.name != ".attachments":
        return
    try:
        lease = path.parent / ".lease"
        lease.touch(mode=0o600, exist_ok=True)
    except OSError:
        pass
