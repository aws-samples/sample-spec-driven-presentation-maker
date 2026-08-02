# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Resource limits for the attachment pipeline (Phase 0-6 / R4c confirmed)."""

from __future__ import annotations

# --- Raw source limits ---
MAX_RAW_SIZE_BYTES = 100 * 1024 * 1024  # 100 MiB
MAX_FILENAME_BYTES = 255  # UTF-8 bytes

# --- Raster image limits ---
MAX_RASTER_COMPRESSED_BYTES = 25 * 1024 * 1024  # 25 MiB
MAX_RASTER_PIXELS = 40_000_000  # 40 megapixels

# --- Animated GIF limits ---
MAX_GIF_FRAMES = 200
MAX_GIF_CUMULATIVE_PIXELS = 100_000_000  # 100 MP cumulative

# --- SVG limits ---
MAX_SVG_BYTES = 5 * 1024 * 1024  # 5 MiB

# --- PDF limits ---
MAX_PDF_PAGES = 100
MAX_PDF_EXTRACTED_IMAGES_BYTES = 200 * 1024 * 1024  # 200 MiB

# --- OOXML ZIP limits ---
MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_TOTAL_UNCOMPRESSED = 500 * 1024 * 1024  # 500 MiB
MAX_ZIP_SINGLE_ENTRY = 100 * 1024 * 1024  # 100 MiB
MAX_ZIP_COMPRESSION_RATIO = 100  # 100:1

# --- URL fetcher limits ---
MAX_REDIRECTS = 5
CONNECT_TIMEOUT_S = 5.0
IDLE_READ_TIMEOUT_S = 15.0
TOTAL_TIMEOUT_S = 90.0
MAX_RESPONSE_HEADER_BYTES = 64 * 1024  # 64 KiB
MAX_BODY_BYTES = MAX_RAW_SIZE_BYTES  # same as raw source

# --- Import deadline ---
IMPORT_DEADLINE_S = 100.0  # 100 seconds internal (120s external timeout - 20s margin)

# --- Paging limits (Phase 0-11) ---
PAGING_DEFAULT_LIMIT = 10_240  # bytes
PAGING_MAX_LIMIT = 10_240
PAGING_MIN_LIMIT = 512

# --- Local GC / quota ---
LOCAL_RAW_TTL_DAYS = 90
LOCAL_RAW_MAX_FILE_BYTES = MAX_RAW_SIZE_BYTES  # 100 MiB per file
LOCAL_RAW_MAX_SESSION_OBJECTS = 100
LOCAL_RAW_MAX_SESSION_BYTES = 1024 * 1024 * 1024  # 1 GiB
LOCAL_RAW_MAX_GLOBAL_OBJECTS = 500
LOCAL_RAW_MAX_GLOBAL_BYTES = 5 * 1024 * 1024 * 1024  # 5 GiB
LOCAL_GC_INTERVAL_S = 3600  # 1 hour
LOCAL_TEMP_TTL_S = 3600  # 1 hour for crash remnants
LOCAL_LEASE_TTL_S = 600  # 10 minutes

# --- Cloud GC / quota ---
CLOUD_RAW_TTL_DAYS = 90
CLOUD_CACHE_TTL_DAYS = 7
CLOUD_ORPHAN_BUNDLE_TTL_HOURS = 24
CLOUD_RAW_MAX_FILE_BYTES = MAX_RAW_SIZE_BYTES
CLOUD_RAW_MAX_OBJECTS_PER_USER = 100
CLOUD_RAW_MAX_BYTES_PER_USER = 1024 * 1024 * 1024  # 1 GiB

# --- Allowed media types ---
TEXT_MEDIA_TYPES = frozenset({
    "text/plain", "text/markdown", "text/csv", "text/html",
    "application/json",
})
DOCUMENT_MEDIA_TYPES = frozenset({
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # xlsx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # pptx
})
IMAGE_MEDIA_TYPES = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml",
})
ALLOWED_MEDIA_TYPES = TEXT_MEDIA_TYPES | DOCUMENT_MEDIA_TYPES | IMAGE_MEDIA_TYPES

# Canonical extensions for media types
MEDIA_TYPE_TO_EXT: dict[str, str] = {
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "text/html": ".html",
    "application/json": ".json",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}
