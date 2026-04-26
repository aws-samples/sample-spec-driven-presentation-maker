# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Local upload/attachment tools — filesystem-based session storage.

Session storage layout:
    {DECK_ROOT}/.sessions/{sessionId}/uploads/{shortId}_{filename}/
        raw.{ext}           — original file (for images/text)
        {name}.md            — converted Markdown (for PDF/DOCX/XLSX)
        slides.json          — converted JSON (for PPTX)
        images/*             — extracted images
        meta.json            — {fileName, fileType, status, warnings, error}

upload_id format: "{sessionId}/{shortId}_{filename}"
"""

from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import shutil
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from mcp.server.fastmcp.utilities.types import Image
from PIL import Image as PILImage

from shared.ingest import IMAGE_EXTS, TEXT_EXTS, convert_file

_JPEG_QUALITY = 80
_MAX_LONG_EDGE = 1280
_MAX_IMAGE_PREVIEWS = 10
_ALLOWED_URL_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}
_SESSION_TTL_DAYS = 7


def _deck_root() -> Path:
    return Path(os.environ.get("SDPM_DECK_ROOT", "")) or Path.home() / "Documents" / "SDPM-Presentations"


def _session_dir(session_id: str) -> Path:
    # Sanitize session_id to prevent path traversal
    if not re.match(r"^[A-Za-z0-9._-]+$", session_id):
        raise ValueError(f"Invalid session_id: {session_id}")
    return _deck_root() / ".sessions" / session_id / "uploads"


def _resolve_upload_dir(upload_id: str) -> Path:
    """Resolve upload_id (sessionId/shortId_filename) to an absolute path.

    Raises ValueError if upload_id is malformed or escapes session root.
    """
    if "/" not in upload_id:
        raise ValueError(f"Invalid upload_id: {upload_id}")
    session_id, upload_name = upload_id.split("/", 1)
    if not re.match(r"^[A-Za-z0-9._-]+$", upload_name):
        raise ValueError(f"Invalid upload name: {upload_name}")
    session_uploads = _session_dir(session_id)
    path = (session_uploads / upload_name).resolve()
    root = session_uploads.resolve()
    if path != root and not str(path).startswith(str(root) + os.sep):
        raise ValueError("upload_id escapes session root")
    return path


def cleanup_old_sessions(ttl_days: int = _SESSION_TTL_DAYS) -> int:
    """Delete session directories older than ttl_days. Returns count deleted."""
    sessions_root = _deck_root() / ".sessions"
    if not sessions_root.exists():
        return 0
    cutoff = time.time() - ttl_days * 86400
    count = 0
    for session_dir in sessions_root.iterdir():
        if not session_dir.is_dir():
            continue
        try:
            mtime = session_dir.stat().st_mtime
            if mtime < cutoff:
                shutil.rmtree(session_dir)
                count += 1
        except Exception:
            continue
    return count


def upload_file(session_id: str, file_path: str, filename: str = "") -> str:
    """Convert and store a file in session storage.

    Args:
        session_id: ACP session identifier.
        file_path: Absolute path to the source file (from API Route temp dir).
        filename: Original filename (defaults to basename of file_path).

    Returns:
        JSON with {uploadId, fileName, fileType, status, warnings?}.
    """
    src = Path(file_path)
    if not src.exists():
        return json.dumps({"error": f"File not found: {file_path}"})

    original_name = filename or src.name
    short_id = uuid.uuid4().hex[:8]
    upload_dir = _session_dir(session_id) / f"{short_id}_{original_name}"
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = src.suffix.lower()
    file_type = mimetypes.guess_type(original_name)[0] or "application/octet-stream"

    meta: dict = {
        "fileName": original_name,
        "fileType": file_type,
        "status": "unknown",
        "warnings": [],
    }

    try:
        # Passthrough: images/text — just copy the raw file
        if ext in IMAGE_EXTS or ext in TEXT_EXTS:
            shutil.copy2(src, upload_dir / original_name)
            meta["status"] = "completed"
            meta["rawFile"] = original_name
        else:
            # Convert via shared pipeline
            result = convert_file(src, upload_dir)
            if result.status == "error":
                meta["status"] = "error"
                meta["error"] = result.error or "Conversion failed"
            else:
                meta["status"] = "converted"
                meta["warnings"] = result.warnings
    except Exception as e:
        meta["status"] = "error"
        meta["error"] = str(e)

    (upload_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    upload_id = f"{session_id}/{short_id}_{original_name}"
    response = {
        "uploadId": upload_id,
        "fileName": original_name,
        "fileType": file_type,
        "status": meta["status"],
    }
    if meta.get("warnings"):
        response["warnings"] = meta["warnings"]
    if meta.get("error"):
        response["error"] = meta["error"]
    return json.dumps(response, ensure_ascii=False)


def _to_jpeg(data: bytes) -> bytes:
    img = PILImage.open(io.BytesIO(data))
    w, h = img.size
    if max(w, h) > _MAX_LONG_EDGE:
        scale = _MAX_LONG_EDGE / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), PILImage.LANCZOS)
    img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_JPEG_QUALITY)
    return buf.getvalue()


def _format_cat_n(text: str, file_name: str, offset: int, limit: int) -> str:
    """Format text with cat -n style line numbers."""
    lines = text.split("\n")
    total = len(lines)
    start = max(0, offset)
    end = min(total, start + limit)
    page_lines = lines[start:end]
    width = max(6, len(str(end)))
    numbered = [f"{i + 1:>{width}}\t{line}" for i, line in enumerate(page_lines, start=start)]
    header = f"## Content of {file_name} (lines {start + 1}-{end} of {total})"
    body = "\n".join(numbered)
    footer = f"\n\n[Continue reading: call with offset={end}]" if end < total else ""
    return f"{header}\n\n{body}{footer}"


def read_uploaded_file(upload_id: str, offset: int = 0, limit: int = 2000) -> list:
    """Read an uploaded file's pre-converted content (cat -n format)."""
    try:
        upload_dir = _resolve_upload_dir(upload_id)
    except ValueError as e:
        return [f"Error: {e}"]
    if not upload_dir.exists():
        return [f"Error: Upload {upload_id} not found."]

    meta_path = upload_dir / "meta.json"
    if not meta_path.exists():
        return [f"Error: Upload {upload_id} has no metadata."]
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    status = meta.get("status", "unknown")
    file_name = meta.get("fileName", "unknown")
    file_type = meta.get("fileType", "")

    if status == "error":
        return [f"Error: Conversion of {file_name} failed: {meta.get('error', 'Unknown')}"]

    warnings = meta.get("warnings", [])
    warning_text = ""
    if warnings:
        warning_text = "\n\n⚠️ Conversion warnings:\n" + "\n".join(f"- {w}" for w in warnings)

    result: list = []

    # Converted (PDF/DOCX/XLSX/PPTX)
    if status == "converted":
        # Try Markdown
        stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
        md_path = upload_dir / f"{stem}.md"
        if md_path.exists():
            result.append(_format_cat_n(md_path.read_text(encoding="utf-8"), file_name, offset, limit))
        # Try PPTX JSON
        json_path = upload_dir / "slides.json"
        if not result and json_path.exists():
            pretty = json.dumps(json.loads(json_path.read_text(encoding="utf-8")), ensure_ascii=False, indent=2)
            result.append(_format_cat_n(pretty, file_name, offset, limit))
        # Image previews
        img_dir = upload_dir / "images"
        if img_dir.exists():
            imgs = sorted(img_dir.iterdir())
            for i, img_file in enumerate(imgs):
                if i >= _MAX_IMAGE_PREVIEWS:
                    result.append(f"({len(imgs) - i} more images not previewed)")
                    break
                try:
                    jpeg = _to_jpeg(img_file.read_bytes())
                    result.append(f"Extracted image: {img_file.name}")
                    result.append(Image(data=jpeg, format="jpeg"))
                except Exception:
                    continue
    # Completed (text/image, no conversion)
    elif status == "completed":
        raw_name = meta.get("rawFile", file_name)
        raw_path = upload_dir / raw_name
        if file_type.startswith("image/"):
            if raw_path.exists():
                try:
                    jpeg = _to_jpeg(raw_path.read_bytes())
                    result.append(f"Image: {file_name} (use import_attachment to add to deck)")
                    result.append(Image(data=jpeg, format="jpeg"))
                except Exception:
                    result.append(f"Image: {file_name} (preview unavailable)")
        elif raw_path.exists():
            result.append(_format_cat_n(raw_path.read_text(encoding="utf-8"), file_name, offset, limit))

    if not result:
        result.append(f"No content found for {file_name}.")
    if warning_text:
        result.append(warning_text)
    return result


def import_attachment(source: str, deck_id: str, filename: str = "") -> str:
    """Import uploaded file or URL into deck workspace (filesystem version).

    deck_id is the deck directory path (Local convention).
    """
    if source.startswith("http://") or source.startswith("https://"):
        return _import_from_url(source, deck_id, filename)
    return _import_from_upload(source, deck_id, filename)


def _import_from_upload(upload_id: str, deck_id: str, filename: str) -> str:
    try:
        upload_dir = _resolve_upload_dir(upload_id)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    if not upload_dir.exists():
        return json.dumps({"error": f"Upload {upload_id} not found"})

    deck_dir = Path(deck_id)
    if not deck_dir.exists():
        return json.dumps({"error": f"Deck {deck_id} not found"})

    meta = json.loads((upload_dir / "meta.json").read_text(encoding="utf-8"))
    status = meta.get("status", "unknown")
    file_name = filename or meta.get("fileName", "unknown")
    file_type = meta.get("fileType", "")

    short_id = uuid.uuid4().hex[:8]
    result: dict = {"source": upload_id, "files": [], "image_mapping": {}}

    images_dir = deck_dir / "images"
    attachments_dir = deck_dir / "attachments"

    if status == "converted":
        # Copy converted files
        for src_file in upload_dir.iterdir():
            if src_file.name == "meta.json":
                continue
            if src_file.name == "images" and src_file.is_dir():
                images_dir.mkdir(exist_ok=True)
                for img in src_file.iterdir():
                    dest_name = f"{short_id}_{img.name}"
                    shutil.copy2(img, images_dir / dest_name)
                    result["files"].append(f"images/{dest_name}")
                    result["image_mapping"][img.name] = f"images/{dest_name}"
            elif src_file.is_file():
                attachments_dir.mkdir(exist_ok=True)
                if src_file.name == "slides.json":
                    dest_name = f"{short_id}_{file_name.rsplit('.', 1)[0]}.json"
                    shutil.copy2(src_file, attachments_dir / dest_name)
                    result["files"].append(f"attachments/{dest_name}")
                    result["json"] = f"attachments/{dest_name}"
                else:
                    dest_name = f"{short_id}_{src_file.name}"
                    shutil.copy2(src_file, attachments_dir / dest_name)
                    result["files"].append(f"attachments/{dest_name}")
                    if src_file.suffix == ".md":
                        result["markdown"] = f"attachments/{dest_name}"
        return json.dumps(result, ensure_ascii=False)

    if status == "completed":
        raw_name = meta.get("rawFile", file_name)
        src_path = upload_dir / raw_name
        if not src_path.exists():
            return json.dumps({"error": f"Raw file not found for {upload_id}"})
        dest_name = f"{short_id}_{file_name}"
        if file_type.startswith("image/"):
            images_dir.mkdir(exist_ok=True)
            shutil.copy2(src_path, images_dir / dest_name)
            result["files"].append(f"images/{dest_name}")
            result["image_mapping"][file_name] = f"images/{dest_name}"
        else:
            attachments_dir.mkdir(exist_ok=True)
            shutil.copy2(src_path, attachments_dir / dest_name)
            result["files"].append(f"attachments/{dest_name}")
        return json.dumps(result, ensure_ascii=False)

    return json.dumps({"error": f"Upload {upload_id} is {status}, cannot import"})


def _import_from_url(url: str, deck_id: str, filename: str) -> str:
    deck_dir = Path(deck_id)
    if not deck_dir.exists():
        return json.dumps({"error": f"Deck {deck_id} not found"})

    short_id = uuid.uuid4().hex[:8]

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; sdpm-agent/1.0)"})
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (user-provided URL by design)
            data = resp.read()
            ct = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    except Exception as e:
        return json.dumps({"error": f"Failed to download: {e}"})

    if ct not in _ALLOWED_URL_TYPES:
        return json.dumps({"error": f"Not an image: {ct}"})

    if not filename:
        parsed = urllib.parse.urlparse(url)
        basename = os.path.basename(parsed.path.split("?")[0]) or "image"
        ext = mimetypes.guess_extension(ct) or ".png"
        if not basename.endswith(ext):
            basename = basename.rsplit(".", 1)[0] + ext if "." in basename else basename + ext
        filename = basename

    dest_name = f"{short_id}_{filename}"
    images_dir = deck_dir / "images"
    images_dir.mkdir(exist_ok=True)
    (images_dir / dest_name).write_bytes(data)
    return json.dumps({
        "source": url,
        "files": [f"images/{dest_name}"],
        "image_mapping": {filename: f"images/{dest_name}"},
    }, ensure_ascii=False)
