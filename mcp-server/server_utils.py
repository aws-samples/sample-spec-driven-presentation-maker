# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Shared server utilities for background tasks."""

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

from storage import Storage

logger = logging.getLogger("sdpm.mcp")


async def _generate_webp_background(
    deck_id: str, pptx_path: Path, tmpdir: Path, storage: Storage,
) -> None:
    """Background WebP preview generation → S3 upload → tmpdir cleanup."""
    from tools.generate import generate_previews

    try:
        preview_dir = Path(tempfile.mkdtemp())
        try:
            old_keys = storage.list_files(prefix=f"previews/{deck_id}/", bucket=storage.pptx_bucket)
            epoch = int(__import__("time").time())
            webp_files = generate_previews(pptx_path, preview_dir)
            for i, webp_path in enumerate(webp_files):
                s3_key = f"previews/{deck_id}/slide_{i + 1:02d}_{epoch}.webp"
                storage.upload_file(key=s3_key, data=webp_path.read_bytes(), content_type="image/webp")
            for key in old_keys:
                try:
                    storage._s3.delete_object(Bucket=storage.pptx_bucket, Key=key)
                except Exception:
                    logger.warning("Failed to delete old preview key: %s", key)
            logger.info("WebP previews uploaded: %d slides for deck %s", len(webp_files), deck_id)
        finally:
            shutil.rmtree(preview_dir, ignore_errors=True)
    except Exception as e:
        logger.warning("WebP generation failed for deck %s: %s", deck_id, e)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def schedule_webp_background(
    deck_id: str, pptx_path: Path, tmpdir: Path, storage: Storage,
) -> None:
    """Schedule background WebP generation. Falls back to tmpdir cleanup on error."""
    try:
        asyncio.get_event_loop().create_task(
            _generate_webp_background(deck_id, pptx_path, tmpdir, storage)
        )
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
