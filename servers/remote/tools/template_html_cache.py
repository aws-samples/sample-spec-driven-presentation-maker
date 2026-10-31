# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Template HTML conversion cache on S3 (``template-html-cache/{cacheKey}/``).

The core converts a .pptx template into ``template.json`` + ``theme.css`` (+ the
decoration SVGs, which need LibreOffice) on first use and caches the result under
``cache_root/<cache_key>/``. Each runtime microVM starts with an empty local
cache, so the converted files are shared through S3: ``restore`` before a core
call fills the local cache from S3, ``persist`` after it uploads what S3 lacks.
Templates are never converted at registration — only when an HTML deck needs one.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.
"""

import logging
import os
import tempfile
from pathlib import Path

from shared.html_artifacts import TEMPLATE_CACHE_PREFIX, template_cache_object_key
from storage import Storage

logger = logging.getLogger("sdpm.template_html_cache")

# Process-wide local cache (cache_root of sdpm.engine.html.template.load_template_html).
CACHE_ROOT = Path(tempfile.gettempdir()) / "sdpm-template-html"

_CONTENT_TYPES = {".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml"}


def resolve_root(override: str | Path | None = None) -> Path:
    """``override`` or the process-wide ``CACHE_ROOT`` (read at call time)."""
    return Path(override) if override is not None else CACHE_ROOT


def _cache_key(template_path: Path) -> str:
    from sdpm.engine.html.template import cache_key

    return cache_key(template_path)


def _write_atomic(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".restore-", dir=dest.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def restore(template_path: str | Path, storage: Storage, cache_root: str | Path | None = None) -> int:
    """Fill ``cache_root/<key>/`` from S3 unless it already holds ``template.json``.

    Only allowlisted files (theme.css, template.json, layouts/*.svg) are downloaded;
    template.json is written last so its presence means the restore finished.
    Best effort: S3 errors are logged and the core then converts locally.

    Returns:
        Number of files restored.
    """
    key = _cache_key(Path(template_path))
    local = resolve_root(cache_root) / key
    if (local / "template.json").is_file():
        return 0
    prefix = f"{TEMPLATE_CACHE_PREFIX}{key}/"
    try:
        keys = storage.list_files(prefix=prefix, bucket=storage.pptx_bucket)
    except Exception:
        logger.warning("template cache list failed for %s", key, exc_info=True)
        return 0
    wanted: list[tuple[str, str]] = []
    for obj in keys:
        rel = obj.removeprefix(prefix)
        try:
            if template_cache_object_key(key, rel) != obj:
                continue
        except ValueError:
            continue
        wanted.append((rel, obj))
    wanted.sort(key=lambda item: item[0] == "template.json")  # template.json last
    restored = 0
    for rel, obj in wanted:
        try:
            _write_atomic(local / rel, storage.download_file_from_pptx_bucket(obj))
        except Exception:
            logger.warning("template cache restore failed for %s", obj, exc_info=True)
            if rel == "template.json":
                break
            continue
        restored += 1
    return restored


def persist(template_path: str | Path, storage: Storage, cache_root: str | Path | None = None) -> int:
    """Upload every allowlisted file under ``cache_root/<key>/`` that S3 does not have yet.

    Uses S3 If-None-Match writes so concurrent writers never overwrite each other.
    Best effort: failures are logged, never raised.

    Returns:
        Number of files uploaded.
    """
    key = _cache_key(Path(template_path))
    local = resolve_root(cache_root) / key
    if not local.is_dir():
        return 0
    prefix = f"{TEMPLATE_CACHE_PREFIX}{key}/"
    try:
        existing = set(storage.list_files(prefix=prefix, bucket=storage.pptx_bucket))
    except Exception:
        logger.warning("template cache list failed for %s", key, exc_info=True)
        existing = set()
    uploaded = 0
    for path in sorted(local.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(local).as_posix()
        try:
            obj = template_cache_object_key(key, rel)
        except ValueError:
            continue  # staging files, anything not in the allowlist
        if obj in existing:
            continue
        try:
            if storage.upload_file_if_absent(
                key=obj, data=path.read_bytes(), content_type=_CONTENT_TYPES.get(path.suffix, ""),
            ):
                uploaded += 1
        except Exception:
            logger.warning("template cache persist failed for %s", obj, exc_info=True)
    return uploaded
