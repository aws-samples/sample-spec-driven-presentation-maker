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
    offset: int = 0,
    limit: int = 2000,
) -> list:
    """Read an uploaded file's pre-converted content.

    Files are converted at upload time. This function returns the converted data
    in cat -n format (with line numbers, like Claude Code's Read tool).
    No deck_id required — works during hearing (before deck creation).

    Args:
        upload_id: The upload identifier.
        user_id: The user identifier.
        storage: Storage backend.
        offset: Starting line number (0-indexed). Default 0.
        limit: Number of lines to read. Default 2000.

    Returns:
        List of str and Image objects for MCP content serialization.
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
        return _read_converted(storage, converted_prefix, file_name, warning_text, offset, limit)

    # --- Text-based files (completed, no conversion needed) ---
    if status == "completed" and file_type in _TEXT_TYPES:
        text = item.get("extractedText")
        if not text and s3_key:
            text = storage.download_file_from_pptx_bucket(s3_key).decode("utf-8")
        return [_format_cat_n(text or "", file_name, offset, limit)]

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

    # --- PPTX (completed, lazy conversion via Engine on MCP Server) ---
    _PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if status == "completed" and file_type == _PPTX_MIME and s3_key:
        converted_prefix = f"uploads/{user_id}/{upload_id}/converted"
        # Check if already converted (cached)
        cached = storage.list_files(converted_prefix, bucket=storage.pptx_bucket)
        if cached:
            return _read_converted(storage, converted_prefix, file_name, warning_text, offset, limit)
        # Lazy convert: download → convert → upload to S3
        import tempfile
        from pathlib import Path as _Path
        from shared.ingest import convert_file
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = _Path(tmp)
                local_file = tmp_path / file_name
                output_dir = tmp_path / "converted"
                local_file.write_bytes(storage.download_file_from_pptx_bucket(s3_key))
                result = convert_file(local_file, output_dir)
                if result.status == "error":
                    return [f"Error: PPTX conversion failed: {result.error}"]
                # Upload converted files to S3
                if output_dir.exists():
                    import mimetypes
                    for f in output_dir.rglob("*"):
                        if f.is_file():
                            rel = f.relative_to(output_dir)
                            s3_dest = f"{converted_prefix}/{rel}"
                            ct = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
                            storage.upload_file(key=s3_dest, data=f.read_bytes(), content_type=ct)
                # Update DynamoDB status to converted
                storage.table.update_item(
                    Key={"PK": f"USER#{user_id}", "SK": f"UPLOAD#{upload_id}"},
                    UpdateExpression="SET #st = :st",
                    ExpressionAttributeNames={"#st": "status"},
                    ExpressionAttributeValues={":st": "converted"},
                )
                return _read_converted(storage, converted_prefix, file_name, warning_text, offset, limit)
        except Exception as e:
            return [f"Error: PPTX conversion failed: {e}"]

    if status == "completed":
        return [f"File: {file_name} (type: {file_type})"]

    return [f"Upload {file_name} is {status}. Please wait and try again."]


def _format_cat_n(text: str, file_name: str, offset: int, limit: int) -> str:
    """Format text in cat -n style with line numbers.

    Args:
        text: The full text content.
        file_name: Display name for the header.
        offset: Starting line (0-indexed).
        limit: Number of lines to include.

    Returns:
        Formatted string with line numbers and range header.
    """
    lines = text.split("\n")
    total = len(lines)
    start = max(0, offset)
    end = min(total, start + limit)
    page_lines = lines[start:end]

    # Width for line numbers (6 chars like cat -n)
    width = max(6, len(str(end)))
    numbered = [f"{i + 1:>{width}}\t{line}" for i, line in enumerate(page_lines, start=start)]

    header = f"## Content of {file_name} (lines {start + 1}-{end} of {total})"
    body = "\n".join(numbered)
    footer = ""
    if end < total:
        footer = f"\n\n[Continue reading: call with offset={end}]"
    return f"{header}\n\n{body}{footer}"


def _read_converted(
    storage: Storage, prefix: str, file_name: str, warning_text: str,
    offset: int, limit: int,
) -> list:
    """Read converted files from S3 prefix (cat -n format)."""
    result: list = []

    # Try Markdown (.md)
    md_found = False
    stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    candidate = f"{prefix}/{stem}.md"
    try:
        md_data = storage.download_file_from_pptx_bucket(candidate)
        result.append(_format_cat_n(md_data.decode("utf-8"), file_name, offset, limit))
        md_found = True
    except Exception:
        pass

    # Try JSON (slides.json for PPTX)
    if not md_found:
        try:
            json_data = storage.download_file_from_pptx_bucket(f"{prefix}/slides.json")
            # JSON is usually compact; format with line numbers too
            import json as _json
            pretty = _json.dumps(_json.loads(json_data), ensure_ascii=False, indent=2)
            result.append(_format_cat_n(pretty, file_name, offset, limit))
        except Exception:
            pass

    # Image previews
    try:
        img_prefix = f"{prefix}/images/"
        keys = storage.list_files(img_prefix, bucket=storage.pptx_bucket)
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
