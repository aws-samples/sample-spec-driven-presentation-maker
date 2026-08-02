# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Source validation, type detection, and filename sanitization.

Handles:
- Source string classification (local path / S3 key / URL)
- Filename sanitization (path traversal, control chars, reserved markers)
- Media type detection via magic bytes + container inspection
- Resource limit pre-checks
"""

from __future__ import annotations

import re
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Literal

from sdpm.tools.attachment.errors import SourceLimitExceeded, SourceTypeMismatch, SourceValidationError
from sdpm.tools.attachment.limits import (
    ALLOWED_MEDIA_TYPES,
    MAX_FILENAME_BYTES,
    MAX_GIF_CUMULATIVE_PIXELS,
    MAX_GIF_FRAMES,
    MAX_PDF_PAGES,
    MAX_RASTER_COMPRESSED_BYTES,
    MAX_RASTER_PIXELS,
    MAX_RAW_SIZE_BYTES,
    MAX_SVG_BYTES,
    MAX_ZIP_COMPRESSION_RATIO,
    MAX_ZIP_ENTRIES,
    MAX_ZIP_SINGLE_ENTRY,
    MAX_ZIP_TOTAL_UNCOMPRESSED,
    MEDIA_TYPE_TO_EXT,
    TEXT_MEDIA_TYPES,
)


@contextmanager
def materialize_local_source(
    source: str, *, allow_any_path: bool = False, root: Path | None = None,
) -> Iterator[Path]:
    """Copy a regular local file from a held O_NOFOLLOW fd into a private snapshot."""
    import os
    import stat
    import tempfile

    path = Path(source)
    if not path.is_absolute():
        raise SourceValidationError(f"Source must be an absolute path, got: {source}")
    try:
        parent = path.parent.resolve(strict=True)
    except (OSError, ValueError) as error:
        raise SourceValidationError(f"Cannot resolve source parent: {source} ({error})")
    candidate = parent / path.name
    if not allow_any_path:
        if root is None:
            raise SourceValidationError("Root must be provided for constrained path validation")
        try:
            candidate.relative_to(root.resolve(strict=True))
        except (ValueError, OSError):
            raise SourceValidationError(f"Source {source} is outside allowed root {root}")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as error:
        raise SourceValidationError(f"Cannot safely open source: {source} ({error})")
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise SourceValidationError(f"Source is not a regular file: {source}")
        if before.st_size > MAX_RAW_SIZE_BYTES:
            raise SourceLimitExceeded(f"File size {before.st_size} exceeds maximum {MAX_RAW_SIZE_BYTES} bytes")
        with tempfile.TemporaryDirectory(prefix="sdpm-attachment-") as tmp:
            snapshot = Path(tmp) / sanitize_filename(path.name)
            total = 0
            with snapshot.open("wb") as output:
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_RAW_SIZE_BYTES:
                        raise SourceLimitExceeded("File grew beyond the 100 MiB raw limit")
                    output.write(chunk)
            after = os.fstat(fd)
            if (
                before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
                or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or total != after.st_size
            ):
                raise SourceValidationError("Source changed during materialization")
            yield snapshot
    finally:
        os.close(fd)


SourceKind = Literal["local_path", "s3_key", "url"]

# Cloud source pattern: uploads/{userId}/{uuid4}/{sanitizedName}
_CLOUD_SOURCE_RE = re.compile(
    r"^uploads/[^/]+/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[^/]+$"
)

# Characters forbidden in filenames
_FILENAME_FORBIDDEN = re.compile(r'[/\\]|\.\.|\x00-\x1f')
_FILENAME_RESERVED_MARKERS = re.compile(r'^\[Attached:')


def classify_source(source: str) -> SourceKind:
    """Classify a source string into its kind.

    Returns:
        "url" for http(s):// URLs
        "s3_key" for Cloud source keys (uploads/...)
        "local_path" for everything else (absolute paths)
    """
    if source.startswith("https://") or source.startswith("http://"):
        return "url"
    if _CLOUD_SOURCE_RE.match(source):
        return "s3_key"
    return "local_path"


def validate_local_source(source: str, *, allow_any_path: bool = False, root: Path | None = None) -> Path:
    """Validate a local file path source.

    Args:
        source: The source path string.
        allow_any_path: If True, allow any absolute path (plain Local stdio).
                       If False, require path under root (Web UI/ACP).
        root: Required root directory when allow_any_path is False.

    Returns:
        Resolved absolute Path.

    Raises:
        SourceValidationError: On invalid/unsafe path.
    """
    if not source:
        raise SourceValidationError("Empty source path")

    path = Path(source)

    if not path.is_absolute():
        raise SourceValidationError(f"Source must be an absolute path, got: {source}")

    # Resolve symlinks for validation
    try:
        resolved = path.resolve(strict=True)
    except (OSError, ValueError) as e:
        raise SourceValidationError(f"Cannot resolve path: {source} ({e})")

    # Check it's a regular file (not symlink, device, FIFO, socket)
    if not resolved.is_file():
        raise SourceValidationError(f"Source is not a regular file: {source}")

    # Root prefix check for constrained adapters
    if not allow_any_path:
        if root is None:
            raise SourceValidationError("Root must be provided for constrained path validation")
        resolved_root = root.resolve()
        try:
            resolved.relative_to(resolved_root)
        except ValueError:
            raise SourceValidationError(
                f"Source {source} is outside allowed root {resolved_root}"
            )

    # Size check
    size = resolved.stat().st_size
    if size > MAX_RAW_SIZE_BYTES:
        raise SourceLimitExceeded(
            f"File size {size} exceeds maximum {MAX_RAW_SIZE_BYTES} bytes"
        )

    return resolved


def validate_cloud_source(source: str, current_user_id: str) -> str:
    """Validate a Cloud S3 key source.

    Args:
        source: The source key string.
        current_user_id: The authenticated user's ID.

    Returns:
        Validated source key.

    Raises:
        SourceValidationError: On invalid key format.
        SourceAccessDenied: If key doesn't belong to current user.
    """
    from sdpm.tools.attachment.errors import SourceAccessDenied

    # Check pattern
    if not _CLOUD_SOURCE_RE.match(source):
        raise SourceValidationError(f"Invalid Cloud source format: {source}")

    # Check for path traversal
    if ".." in source or "\\" in source:
        raise SourceValidationError(f"Path traversal in source: {source}")

    # Check control characters
    if any(ord(c) < 0x20 for c in source):
        raise SourceValidationError(f"Control characters in source: {source}")

    # Extract userId from key and verify ownership
    parts = source.split("/")
    # Pattern: uploads/{userId}/{uuid4}/{name}
    if len(parts) != 4:
        raise SourceValidationError(f"Invalid Cloud source structure: {source}")

    key_user_id = parts[1]
    if key_user_id != current_user_id:
        raise SourceAccessDenied(source)

    return source


def sanitize_filename(name: str) -> str:
    """Sanitize a filename for safe storage.

    - Removes path separators and traversal
    - Removes control characters
    - Removes leading dots
    - Removes reserved marker patterns
    - Truncates to MAX_FILENAME_BYTES

    Returns:
        Sanitized filename string.

    Raises:
        SourceValidationError: If filename is empty after sanitization.
    """
    if not name:
        raise SourceValidationError("Empty filename")

    # Remove path separators
    name = name.replace("/", "_").replace("\\", "_")

    # Remove .. sequences
    name = name.replace("..", "_")

    # Remove control characters
    name = re.sub(r'[\x00-\x1f\x7f]', '', name)

    # Remove leading dots
    name = name.lstrip(".")

    # Remove reserved marker patterns
    if _FILENAME_RESERVED_MARKERS.match(name):
        name = "_" + name

    # Truncate to byte limit while respecting UTF-8 boundaries
    encoded = name.encode("utf-8")
    if len(encoded) > MAX_FILENAME_BYTES:
        # Find the last valid code-point boundary within limit
        truncated = encoded[:MAX_FILENAME_BYTES]
        name = truncated.decode("utf-8", errors="ignore")

    if not name:
        raise SourceValidationError("Filename empty after sanitization")

    return name


# --- Magic byte detection ---

_MAGIC_SIGNATURES: list[tuple[bytes, str]] = [
    (b"%PDF", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # need further check for WEBP
]


def detect_media_type(data: bytes, *, filename: str = "", path: Path | None = None) -> str | None:
    """Detect media type from magic bytes and optional filename.

    Args:
        data: First 8192+ bytes of the file.
        filename: Optional filename for extension hint.
        path: Optional full file path — enables reliable OOXML detection
              when the header-only read is truncated (central directory
              beyond 8192 bytes).

    Returns:
        Detected media type string, or None if unrecognized.
    """
    if len(data) < 4:
        return _detect_from_text(data)

    # Check magic signatures
    for magic, media_type in _MAGIC_SIGNATURES:
        if data.startswith(magic):
            if magic == b"RIFF" and len(data) >= 12:
                # Verify it's actually WebP
                if data[8:12] == b"WEBP":
                    return "image/webp"
                return None
            return media_type

    # Check ZIP-based formats (OOXML)
    if data[:4] == b"PK\x03\x04":
        result = _detect_ooxml_type(data)
        if result is not None:
            return result
        # Header truncated — try full file if path is available
        if path is not None:
            return detect_ooxml_from_path(path)
        return None

    # Check SVG (XML with svg root)
    if _looks_like_svg(data):
        return "image/svg+xml"

    # Fall back to text detection
    return _detect_from_text(data)


def _detect_ooxml_type(data: bytes) -> str | None:
    """Detect OOXML type by inspecting [Content_Types].xml inside the ZIP.

    Note: `data` may be a partial read (e.g. first 8192 bytes). If the ZIP
    central directory is not included (truncated), we fall back to None so the
    caller can re-attempt with the full file via `detect_ooxml_from_path`.
    """
    import io

    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            if "[Content_Types].xml" not in zf.namelist():
                return None
            content_types = zf.read("[Content_Types].xml").decode("utf-8", errors="replace")
            if "presentationml" in content_types.lower() or "presentation.main" in content_types.lower():
                return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            if "wordprocessingml" in content_types.lower() or "document.main" in content_types.lower():
                return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if "spreadsheetml" in content_types.lower() or "sheet.main" in content_types.lower():
                return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    except (zipfile.BadZipFile, OSError, KeyError):
        # Truncated or invalid ZIP — return None (caller should retry with full file)
        return None
    return None


def detect_ooxml_from_path(path: Path) -> str | None:
    """Detect OOXML type from a full file on disk (not truncated).

    Use this when the header-only detection returns None for a PK\x03\x04
    file — it reads the central directory from disk.
    """
    try:
        with zipfile.ZipFile(path, "r") as zf:
            if "[Content_Types].xml" not in zf.namelist():
                return None
            content_types = zf.read("[Content_Types].xml").decode("utf-8", errors="replace")
            if "presentationml" in content_types.lower() or "presentation.main" in content_types.lower():
                return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            if "wordprocessingml" in content_types.lower() or "document.main" in content_types.lower():
                return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if "spreadsheetml" in content_types.lower() or "sheet.main" in content_types.lower():
                return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    except (zipfile.BadZipFile, OSError, KeyError):
        return None
    return None


def _looks_like_svg(data: bytes) -> bool:
    """Check if data looks like an SVG file."""
    text = data[:4096].decode("utf-8", errors="replace").strip()
    # Remove XML declaration if present
    if text.startswith("<?xml"):
        close = text.find("?>")
        if close != -1:
            text = text[close + 2:].strip()
    return text.startswith("<svg") or ("<svg" in text[:500])


def _detect_from_text(data: bytes) -> str | None:
    """Try to detect if data is valid UTF-8 text."""
    # Check for NUL bytes (binary indicator)
    if b"\x00" in data[:8192]:
        return None

    try:
        data[:8192].decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None

    return "text/plain"


def validate_media_type(
    detected: str | None,
    content_type: str | None = None,
    filename: str = "",
) -> str:
    """Validate and reconcile media type from detection vs Content-Type.

    Args:
        detected: Magic-detected media type.
        content_type: Content-Type header value (if from URL).
        filename: Filename for extension-based hints.

    Returns:
        Validated media type.

    Raises:
        SourceTypeMismatch: If Content-Type conflicts with magic.
        SourceValidationError: If type is not in allowed set.
    """
    if detected is None:
        if content_type and content_type in ALLOWED_MEDIA_TYPES:
            return content_type
        raise SourceValidationError("Unable to determine file type")

    if content_type and content_type != "application/octet-stream":
        ct_base = content_type.split(";", 1)[0].strip().lower()
        if detected == "text/plain" and ct_base in TEXT_MEDIA_TYPES:
            detected = ct_base
        elif ct_base in ALLOWED_MEDIA_TYPES and ct_base != detected:
            raise SourceTypeMismatch(
                f"Content-Type '{ct_base}' conflicts with detected type '{detected}'"
            )

    if detected not in ALLOWED_MEDIA_TYPES:
        raise SourceValidationError(f"Unsupported media type: {detected}")
    return detected


def enforce_content_limits(path: Path, media_type: str) -> None:
    """Enforce expansion, pixel, page, and safe-SVG limits before conversion."""
    size = path.stat().st_size
    if size > MAX_RAW_SIZE_BYTES:
        raise SourceLimitExceeded(f"File size {size} exceeds maximum {MAX_RAW_SIZE_BYTES} bytes")

    if media_type == "image/svg+xml":
        if size > MAX_SVG_BYTES:
            raise SourceLimitExceeded(f"SVG size exceeds {MAX_SVG_BYTES} bytes")
        text = path.read_text(encoding="utf-8", errors="strict")
        lowered = text.lower()
        forbidden = ("<!doctype", "<!entity", "<script", "<foreignobject")
        if any(token in lowered for token in forbidden) or re.search(r"\son[a-z0-9_-]+\s*=", lowered):
            raise SourceValidationError("SVG contains unsafe active content")
        for match in re.finditer(r"(?:href|xlink:href)\s*=\s*['\"]([^'\"]+)", text, re.IGNORECASE):
            target = match.group(1).strip().lower()
            if not target.startswith("#") and not target.startswith("data:image/"):
                raise SourceValidationError("SVG contains an external resource reference")
        return

    if media_type in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
        if size > MAX_RASTER_COMPRESSED_BYTES:
            raise SourceLimitExceeded(f"Raster image exceeds {MAX_RASTER_COMPRESSED_BYTES} compressed bytes")
        try:
            import warnings
            from PIL import Image
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    pixels = image.width * image.height
                    if pixels > MAX_RASTER_PIXELS:
                        raise SourceLimitExceeded(f"Raster image exceeds {MAX_RASTER_PIXELS} pixels")
                    if media_type == "image/gif":
                        frames = int(getattr(image, "n_frames", 1))
                        if frames > MAX_GIF_FRAMES or pixels * frames > MAX_GIF_CUMULATIVE_PIXELS:
                            raise SourceLimitExceeded("Animated GIF exceeds frame or cumulative-pixel limit")
        except SourceLimitExceeded:
            raise
        except Exception as error:
            raise SourceValidationError(f"Invalid raster image: {error}")
        return

    if media_type in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }:
        try:
            with zipfile.ZipFile(path, "r") as archive:
                entries = archive.infolist()
                if len(entries) > MAX_ZIP_ENTRIES:
                    raise SourceLimitExceeded(f"OOXML archive exceeds {MAX_ZIP_ENTRIES} entries")
                total = 0
                normalized_entries: set[str] = set()
                for entry in entries:
                    import stat

                    normalized = entry.filename.replace("\\", "/")
                    if normalized.startswith("/") or ".." in normalized.split("/"):
                        raise SourceValidationError("OOXML archive contains an unsafe entry path")
                    if normalized in normalized_entries:
                        raise SourceValidationError("OOXML archive contains duplicate entry paths")
                    normalized_entries.add(normalized)
                    if entry.flag_bits & 0x1:
                        raise SourceValidationError("OOXML archive contains an encrypted entry")
                    unix_mode = entry.external_attr >> 16
                    if unix_mode and stat.S_ISLNK(unix_mode):
                        raise SourceValidationError("OOXML archive contains a symlink entry")
                    if entry.file_size > MAX_ZIP_SINGLE_ENTRY:
                        raise SourceLimitExceeded("OOXML archive contains an oversized entry")
                    total += entry.file_size
                    if total > MAX_ZIP_TOTAL_UNCOMPRESSED:
                        raise SourceLimitExceeded("OOXML archive exceeds total uncompressed-size limit")
                    if entry.file_size and (
                        entry.compress_size == 0
                        or entry.file_size / entry.compress_size > MAX_ZIP_COMPRESSION_RATIO
                    ):
                        raise SourceLimitExceeded("OOXML archive exceeds compression-ratio limit")
        except (SourceLimitExceeded, SourceValidationError):
            raise
        except (zipfile.BadZipFile, OSError) as error:
            raise SourceValidationError(f"Invalid OOXML archive: {error}")
        return

    if media_type == "application/pdf":
        try:
            from pypdf import PdfReader
            if len(PdfReader(str(path)).pages) > MAX_PDF_PAGES:
                raise SourceLimitExceeded(f"PDF exceeds {MAX_PDF_PAGES} pages")
        except SourceLimitExceeded:
            raise
        except Exception as error:
            raise SourceValidationError(f"Invalid PDF: {error}")


def get_canonical_extension(media_type: str) -> str:
    """Get canonical file extension for a media type."""
    return MEDIA_TYPE_TO_EXT.get(media_type, "")


def source_identity_local(path: Path) -> dict[str, str | int]:
    """Compute source identity for a local file (realpath + mtime_ns + size)."""
    resolved = path.resolve()
    stat = resolved.stat()
    return {
        "kind": "file",
        "realpath": str(resolved),
        "mtimeNs": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def source_identity_s3(key: str, etag: str, size: int) -> dict[str, str | int]:
    """Compute source identity for an S3 object (key + ETag + size)."""
    return {
        "kind": "s3",
        "key": key,
        "etag": etag,
        "size": size,
    }
