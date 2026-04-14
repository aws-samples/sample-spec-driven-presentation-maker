# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Read uploaded files with multimodal support (images, PDF)."""

import io
import mimetypes

from mcp.server.fastmcp.utilities.types import Image
from PIL import Image as PILImage

from storage import Storage

_JPEG_QUALITY = 80
_MAX_LONG_EDGE = 1280

_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
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


def _save_image_to_deck(storage: Storage, deck_id: str, filename: str, data: bytes) -> str:
    """Save image to deck workspace and return relative src path."""
    ct = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    key = f"decks/{deck_id}/images/{filename}"
    storage.upload_file(key=key, data=data, content_type=ct)
    return f"images/{filename}"


def read_uploaded_file(
    upload_id: str,
    deck_id: str,
    user_id: str,
    storage: Storage,
    page_start: int = 0,
) -> list:
    """Read an uploaded file, returning text and/or ImageContent.

    Returns a list of str and Image objects for MCP content serialization.
    """
    resp = storage.table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"UPLOAD#{upload_id}"})
    item = resp.get("Item")
    if not item:
        return [f"Error: Upload {upload_id} not found."]

    status = item.get("status", "unknown")
    if status not in ("completed",):
        return [f"Upload is still {status}. Please wait and try again."]

    file_type = item.get("fileType", "")
    file_name = item.get("fileName", "unknown")
    s3_key = item.get("s3KeyRaw", "")

    # --- Text-based files ---
    if file_type in _TEXT_TYPES:
        text = item.get("extractedText")
        if not text and s3_key:
            text = storage.download_file_from_pptx_bucket(s3_key).decode("utf-8")
        return [f"## Content of {file_name}\n\n{text or '(empty)'}"]

    # --- PPTX ---
    if file_type == _PPTX_MIME:
        text = item.get("extractedText", "")
        hint = f'Use pptx_to_json(deck_id="{deck_id}", upload_id="{upload_id}") to convert to editable JSON.'
        parts = []
        if text:
            parts.append(f"## Content of {file_name}\n\n{text}\n\n---\n{hint}")
        else:
            parts.append(f"PPTX file: {file_name}. {hint}")
        return parts

    # --- Image ---
    if file_type.startswith("image/") and s3_key:
        data = storage.download_file_from_pptx_bucket(s3_key)
        src = _save_image_to_deck(storage, deck_id, file_name, data)
        jpeg = _to_jpeg(data)
        return [
            f"Image saved to deck workspace as `{src}`. Use this path in slide JSON image elements.",
            Image(data=jpeg, format="jpeg"),
        ]

    # --- PDF ---
    if file_type == "application/pdf" and s3_key:
        return _read_pdf(storage, deck_id, s3_key, file_name, page_start=page_start)

    return [f"Unsupported file type: {file_type} ({file_name})"]


def _read_pdf(storage: Storage, deck_id: str, s3_key: str, file_name: str, *, page_start: int = 0) -> list:
    """Extract text and images from PDF.

    Safety limits:
    - MAX_PAGES: pages to process per call (use page_start to paginate)
    - MAX_IMAGES: total image previews (JPEG) to return
    - Images beyond the limit are saved to deck workspace but not previewed
    """
    from pypdf import PdfReader

    MAX_PAGES = 20
    MAX_IMAGES = 10

    data = storage.download_file_from_pptx_bucket(s3_key)
    reader = PdfReader(io.BytesIO(data))
    total_pages = len(reader.pages)
    page_end = min(page_start + MAX_PAGES, total_pages)

    result: list = []
    all_text = []
    img_idx = 0
    preview_count = 0

    for pi in range(page_start, page_end):
        page = reader.pages[pi]
        page_num = pi + 1  # 1-based display

        text = page.extract_text() or ""
        if text.strip():
            all_text.append(f"### Page {page_num}\n{text.strip()}")

        for image in page.images:
            img_idx += 1
            ext = image.name.rsplit(".", 1)[-1] if "." in image.name else "png"
            img_name = f"pdf_p{page_num}_img{img_idx}.{ext}"
            src = _save_image_to_deck(storage, deck_id, img_name, image.data)
            if preview_count < MAX_IMAGES:
                try:
                    jpeg = _to_jpeg(image.data)
                    result.append(f"PDF page {page_num} image → `{src}`")
                    result.append(Image(data=jpeg, format="jpeg"))
                    preview_count += 1
                except Exception:
                    result.append(f"PDF page {page_num} image → `{src}` (preview unavailable)")
            else:
                result.append(f"PDF page {page_num} image → `{src}` (saved, preview limit reached)")

    if all_text:
        header = f"## Text from {file_name} ({total_pages} pages, showing pages {page_start + 1}-{page_end})"
        result.insert(0, header + "\n\n" + "\n\n".join(all_text))
    elif not result:
        result.append(f"No extractable text or images found in {file_name}.")

    if page_end < total_pages:
        result.append(
            f"\n[{total_pages - page_end} more pages not shown. "
            f"Call read_uploaded_file with page_start={page_end} to continue reading.]"
        )

    return result
