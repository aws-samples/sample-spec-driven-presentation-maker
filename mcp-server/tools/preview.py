# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Slide preview retrieval as multimodal image content for agent visual review."""

import io

from mcp.server.fastmcp.utilities.types import Image
from PIL import Image as PILImage

from storage import Storage

# Long-edge pixel limits per quality level.
_MAX_LONG_EDGE: dict[str, int] = {"low": 800, "high": 1280}

# JPEG quality for preview images (80 = good visual quality, ~6x smaller than PNG).
_JPEG_QUALITY: int = 80


def _resize_to_jpeg(data: bytes, quality: str) -> bytes:
    """Resize a PNG image and convert to JPEG for compact transfer.

    PNG previews are large (1-3 MB) and become enormous as base64 text.
    JPEG at quality 80 reduces size ~6x while preserving visual clarity
    sufficient for agent review.

    Args:
        data: Raw PNG bytes from S3.
        quality: "low" (800px) or "high" (1280px) long-edge limit.

    Returns:
        JPEG bytes.
    """
    max_edge = _MAX_LONG_EDGE[quality]
    img = PILImage.open(io.BytesIO(data))
    w, h = img.size
    if max(w, h) > max_edge:
        scale = max_edge / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), PILImage.LANCZOS)
    img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_JPEG_QUALITY)
    return buf.getvalue()


def get_preview(
    deck_id: str,
    slide_numbers: list[int],
    storage: Storage,
    quality: str = "high",
) -> list:
    """Fetch slide PNGs from S3, resize, convert to JPEG, and return as Image list.

    The returned list alternates between text labels (slide numbers) and
    FastMCP Image objects. FastMCP converts these into TextContent and
    ImageContent blocks that the LLM can visually inspect.

    Args:
        deck_id: The deck ID.
        slide_numbers: List of 1-based slide numbers to preview (at least one required).
        storage: Storage backend instance.
        quality: "low" (800px long edge) or "high" (1280px long edge).

    Returns:
        List of str and Image objects for MCP content serialization.
    """
    result: list = []
    for n in slide_numbers:
        key = f"previews/{deck_id}/slide_{n:02d}.png"
        data = storage.download_file_from_pptx_bucket(key=key)
        jpeg_data = _resize_to_jpeg(data=data, quality=quality)
        result.append(f"Slide {n}")
        result.append(Image(data=jpeg_data, format="jpeg"))
    return result
