# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Read uploaded files — returns pre-converted content (no conversion at read time)."""

import io

from mcp.server.fastmcp.utilities.types import Image
from PIL import Image as PILImage

from storage import Storage

_JPEG_QUALITY = 80
_MAX_LONG_EDGE = 1280
_MAX_IMAGE_PREVIEWS = 10

_TEXT_TYPES = {"text/plain", "text/markdown", "application/json"}


def _to_jpeg(data: bytes) -> bytes:
    """Resize image to fit within max edge and convert to JPEG."""
    img = PILImage.open(io.BytesIO(data))
    w, h = img.size
    if max(w, h) > _MAX_LONG_EDGE:
        scale = _MAX_LONG_EDGE / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), PILImage.LANCZOS)
    img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_JPEG_QUALITY)
    return buf.getvalue()


def read_uploaded_file(
    upload_id: str,
    user_id: str,
    storage: Storage,
    page_start: int = 0,
) -> list:
    """Read an uploaded file's pre-converted content.

    Files are converted at upload time. This function returns the converted data.
    No deck_id required — works during hearing (before deck creation).

    Returns a list of str and Image objects for MCP content serialization.
    """
    resp = storage.table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"UPLOAD#{upload_id}"})
    item = resp.get("Item")
    if not item:
        return [f"Error: Upload {upload_id} not found."]

    status = item.get("status", "unknown")
    file_name = item.get("fileName", "unknown")
    file_type = item.get("fileType", "")
    s3_key = item.get("s3KeyRaw", "")

    # Status check
    if status == "converting":
        return [f"Upload {file_name} is still being converted. Please wait and try again."]
    if status == "error":
        error = item.get("conversionError", "Unknown error")
        return [f"Error: Conversion of {file_name} failed: {error}"]

    # Warnings from conversion
    warnings = item.get("conversionWarnings", [])
    warning_text = ""
    if warnings:
        warning_text = "\n\n⚠️ Conversion warnings:\n" + "\n".join(f"- {w}" for w in warnings)

    # --- Converted files (PDF/DOCX/XLSX/PPTX) ---
    if status == "converted":
        converted_prefix = f"uploads/{user_id}/{upload_id}/converted"
        return _read_converted(storage, converted_prefix, file_name, warning_text, page_start)

    # --- Text-based files (completed, no conversion needed) ---
    if status == "completed" and file_type in _TEXT_TYPES:
        text = item.get("extractedText")
        if not text and s3_key:
            text = storage.download_file_from_pptx_bucket(s3_key).decode("utf-8")
        return [f"## Content of {file_name}\n\n{text or '(empty)'}"]

    # --- Images (completed, no conversion needed) ---
    if status == "completed" and file_type.startswith("image/") and s3_key:
        data = storage.download_file_from_pptx_bucket(s3_key)
        parts = [f"Image: {file_name} (use import_attachment to add to deck)"]
        try:
            jpeg = _to_jpeg(data)
            parts.append(Image(data=jpeg, format="jpeg"))
        except Exception:
            parts.append("(preview unavailable)")
        return parts

    if status == "completed":
        return [f"File: {file_name} (type: {file_type})"]

    return [f"Upload {file_name} is {status}. Please wait and try again."]


def _read_converted(
    storage: Storage, prefix: str, file_name: str, warning_text: str, page_start: int,
) -> list:
    """Read converted files from S3 prefix."""
    result: list = []

    # Try Markdown (.md)
    md_key = None
    stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    candidate = f"{prefix}/{stem}.md"
    try:
        md_data = storage.download_file_from_pptx_bucket(candidate)
        md_key = candidate
        md_text = md_data.decode("utf-8")

        # Paginate long documents
        lines = md_text.split("\n")
        page_size = 200  # lines per page
        start = page_start * page_size
        end = start + page_size
        page_lines = lines[start:end]

        header = f"## Content of {file_name}"
        if len(lines) > page_size:
            total_pages = (len(lines) + page_size - 1) // page_size
            current_page = page_start + 1
            header += f" (page {current_page}/{total_pages})"

        result.append(header + "\n\n" + "\n".join(page_lines))

        if end < len(lines):
            result.append(
                f"\n[More content available. "
                f"Call read_uploaded_file with page_start={page_start + 1} to continue.]"
            )
    except Exception:
        pass

    # Try JSON (slides.json for PPTX)
    if not md_key:
        try:
            json_data = storage.download_file_from_pptx_bucket(f"{prefix}/slides.json")
            result.append(f"## PPTX Content of {file_name}\n\n```json\n{json_data.decode('utf-8')}\n```")
        except Exception:
            pass

    # Image previews
    try:
        img_prefix = f"{prefix}/images/"
        keys = storage.list_files(img_prefix)
        preview_count = 0
        for key in keys:
            if preview_count >= _MAX_IMAGE_PREVIEWS:
                result.append(f"({len(keys) - preview_count} more images not previewed)")
                break
            try:
                img_data = storage.download_file_from_pptx_bucket(key)
                jpeg = _to_jpeg(img_data)
                img_name = key.rsplit("/", 1)[-1]
                result.append(f"Extracted image: {img_name}")
                result.append(Image(data=jpeg, format="jpeg"))
                preview_count += 1
            except Exception:
                continue
    except Exception:
        pass

    if not result:
        result.append(f"No converted content found for {file_name}.")

    if warning_text:
        result.append(warning_text)

    return result
