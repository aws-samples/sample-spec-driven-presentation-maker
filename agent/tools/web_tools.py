# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Strands Agent tool for fetching web pages, PDFs, and images."""

import io
import re

import html2text
import requests
from strands import tool

_IMAGE_FORMATS = {"image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif", "image/webp": "webp"}


def _detect_content_type(response: requests.Response) -> str:
    return response.headers.get("Content-Type", "").split(";")[0].strip().lower()


@tool
def web_fetch(url: str, max_chars: int = 20000, start: int = 0, include_images: bool = False) -> dict | str:
    """Fetch a web page, PDF, or image from a URL.

    - HTML pages are returned as Markdown text.
    - PDFs are returned as extracted text per page plus page images for visual analysis.
    - Images (PNG, JPEG, GIF, WebP) are returned as image content for vision analysis.

    For long HTML pages, use 'start' to paginate through the content.

    When include_images is True, image references (![alt](url)) are preserved in the
    Markdown output. You can then fetch individual images by calling web_fetch(url) on
    the image URLs that are relevant for the presentation.

    Args:
        url: The URL to fetch.
        max_chars: Maximum characters to return for HTML (default 20000).
        start: Character offset to start from, for HTML reading continuation.
        include_images: If True, keep image URLs in Markdown output (default False).

    Returns:
        Markdown text for HTML, or structured ToolResult for PDF/image.
    """
    response = requests.get(
        url=url,
        timeout=60,
        headers={"User-Agent": "Mozilla/5.0 (compatible; sdpm-agent/1.0)"},
    )
    response.raise_for_status()

    ct = _detect_content_type(response)

    # --- Image ---
    if ct in _IMAGE_FORMATS:
        return {
            "status": "success",
            "content": [
                {"image": {"format": _IMAGE_FORMATS[ct], "source": {"bytes": response.content}}},
                {"text": f"Image fetched from {url} ({ct}, {len(response.content)} bytes)"},
            ],
        }

    # --- PDF ---
    if ct == "application/pdf":
        return _handle_pdf(url, response.content)

    # --- HTML (default) ---
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = not include_images
    h.body_width = 0
    markdown = h.handle(response.text)

    total = len(markdown)
    chunk = markdown[start : start + max_chars]
    end = start + len(chunk)

    if end < total:
        chunk += f"\n\n---\n[Truncated: showing chars {start}-{end} of {total}. Use start={end} to continue.]"

    return chunk


def _handle_pdf(url: str, data: bytes) -> dict:
    """Extract text, page images, and embedded images from PDF bytes.

    Safety limits to prevent oversized responses:
    - Processes up to MAX_PAGES pages per call (use page_start to paginate)
    - Renders up to MAX_PAGE_IMAGES page images for visual analysis
    - Embedded images are listed as metadata only; agent can fetch individually
    - Total response size is capped at MAX_RESPONSE_BYTES
    """
    import pymupdf

    MAX_PAGES = 5
    MAX_PAGE_IMAGES = 3
    MAX_EMBEDDED_IMAGES = 10
    MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB

    doc = pymupdf.open(stream=data, filetype="pdf")
    total_pages = doc.page_count
    content: list[dict] = []
    content.append({"text": f"PDF: {url} ({total_pages} pages, showing pages 1-{min(MAX_PAGES, total_pages)})"})

    response_bytes = 0
    page_images_rendered = 0
    embedded_images_count = 0

    for i, page in enumerate(doc):
        if i >= MAX_PAGES:
            break

        # Text extraction (lightweight)
        text = page.get_text()
        if text.strip():
            content.append({"text": f"--- Page {i + 1} ---\n{text.strip()}"})

        # Render page as image (limited count)
        if page_images_rendered < MAX_PAGE_IMAGES:
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            if response_bytes + len(img_bytes) > MAX_RESPONSE_BYTES:
                content.append({"text": f"[Page {i + 1} image skipped: response size limit reached]"})
                break
            content.append({"image": {"format": "png", "source": {"bytes": img_bytes}}})
            response_bytes += len(img_bytes)
            page_images_rendered += 1
        else:
            content.append({"text": f"[Page {i + 1} image skipped: page image limit ({MAX_PAGE_IMAGES}) reached]"})

        # List embedded images as metadata only
        for img_info in page.get_images(full=True):
            embedded_images_count += 1
            if embedded_images_count > MAX_EMBEDDED_IMAGES:
                break
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                if not base_image:
                    continue
                w = base_image.get("width", "?")
                h = base_image.get("height", "?")
                ext = base_image.get("ext", "?")
                size = len(base_image.get("image", b""))
                content.append({"text": f"[Embedded image page {i + 1}: {w}x{h} {ext}, {size} bytes, xref={xref}]"})
            except Exception:
                continue

    if total_pages > MAX_PAGES:
        content.append({
            "text": f"\n[{total_pages - MAX_PAGES} more pages not shown. "
            f"Call web_fetch with page_start={MAX_PAGES} to continue reading.]"
        })
    if embedded_images_count > MAX_EMBEDDED_IMAGES:
        content.append({"text": f"[{embedded_images_count - MAX_EMBEDDED_IMAGES}+ more embedded images not listed]"})

    doc.close()
    return {"status": "success", "content": content}
