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
    deck_id: str, pptx_path: Path, tmpdir: Path, storage: Storage, slugs: list[str],
    user_id: str = "",
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
                slug = slugs[i] if i < len(slugs) else f"slide_{i + 1:02d}"
                s3_key = f"previews/{deck_id}/{slug}_{epoch}.webp"
                storage.upload_file(key=s3_key, data=webp_path.read_bytes(), content_type="image/webp")
            for key in old_keys:
                try:
                    storage._s3.delete_object(Bucket=storage.pptx_bucket, Key=key)
                except Exception:
                    logger.warning("Failed to delete old preview key: %s", key)
            logger.info("WebP previews uploaded: %d slides for deck %s", len(webp_files), deck_id)

            # Thumbnail: resize first slide to 480px width
            if webp_files and user_id:
                from PIL import Image
                thumb_img = Image.open(webp_files[0])
                thumb_img.thumbnail((480, 270), Image.LANCZOS)
                thumb_path = preview_dir / "thumbnail.webp"
                thumb_img.save(thumb_path, "WEBP", quality=70)
                thumb_key = f"thumbnails/{deck_id}/{slugs[0]}_{epoch}.webp"
                storage.upload_file(key=thumb_key, data=thumb_path.read_bytes(), content_type="image/webp")
                old_thumbs = storage.list_files(prefix=f"thumbnails/{deck_id}/", bucket=storage.pptx_bucket)
                for k in old_thumbs:
                    if k != thumb_key:
                        try:
                            storage._s3.delete_object(Bucket=storage.pptx_bucket, Key=k)
                        except Exception:
                            pass
                storage.update_deck(deck_id=deck_id, user_id=user_id, updates={"thumbnailS3Key": thumb_key})
                logger.info("Thumbnail uploaded for deck %s: %s", deck_id, thumb_key)
        finally:
            shutil.rmtree(preview_dir, ignore_errors=True)
    except Exception as e:
        logger.warning("WebP generation failed for deck %s: %s", deck_id, e)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def schedule_webp_background(
    deck_id: str, pptx_path: Path, tmpdir: Path, storage: Storage, slugs: list[str],
    user_id: str = "",
) -> None:
    """Schedule background WebP generation. Falls back to tmpdir cleanup on error."""
    try:
        asyncio.get_event_loop().create_task(
            _generate_webp_background(deck_id, pptx_path, tmpdir, storage, slugs, user_id=user_id)
        )
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
