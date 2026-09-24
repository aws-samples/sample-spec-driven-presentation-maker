# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Atomic directory publish for local (same-filesystem) caches and bundles.

Both the attachment stage cache (``cache.py``) and the import bundle committer
(``bundle.py``) publish a fully-built staging directory as a content-addressed
target directory. They share one protocol:

1. Build everything in a staging directory that only this writer knows about.
2. Fsync the staging tree.
3. Rename staging onto the target in a single filesystem operation.
4. If the rename fails because another writer got there first, verify the
   winner's directory and reuse it.

There is no cross-process lock. Correctness comes from the staging directory
being unique per writer, ``os.rename`` being atomic on the same filesystem, and
readers validating checksums before trusting a target. This mirrors the remote
(S3) side, which relies on ``If-None-Match: *`` first-writer-wins semantics.

Windows note: directories cannot be opened with ``os.open`` on Windows, so
directory fsync is skipped there. File fsync still runs on every platform.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

_CAN_FSYNC_DIRECTORY = sys.platform != "win32"


def fsync_file(path: Path) -> None:
    """Fsync a single regular file."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_directory(path: Path) -> None:
    """Fsync a directory entry. No-op on platforms that cannot open directories."""
    if not _CAN_FSYNC_DIRECTORY:
        return
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_tree(path: Path) -> None:
    """Fsync every file under ``path``, then every directory deepest-first, then ``path``."""
    entries = list(path.rglob("*"))
    for child in entries:
        if child.is_file():
            fsync_file(child)
    directories = [child for child in entries if child.is_dir()]
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        fsync_directory(directory)
    fsync_directory(path)


def publish_directory(
    staging: Path,
    target: Path,
    *,
    reuse_existing: Callable[[], bool],
) -> Path:
    """Atomically publish ``staging`` as ``target`` with first-writer-wins semantics.

    Args:
        staging: Fully built directory on the same filesystem as ``target``.
            It is consumed by this call: either renamed onto ``target`` or removed.
        target: Final directory path.
        reuse_existing: Called when ``target`` already exists (before the rename,
            and again if the rename fails). Return ``True`` if the existing target
            is valid and should be reused as-is, ``False`` if it is corrupt and
            should be replaced. May raise to signal a genuine conflict; the
            exception propagates after ``staging`` is cleaned up.

    Returns:
        ``target``.

    Raises:
        OSError: If the rename fails and ``reuse_existing()`` does not accept
            the directory that is now at ``target``.
    """
    try:
        fsync_tree(staging)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            if reuse_existing():
                shutil.rmtree(staging)
                return target
            logger.warning("Replacing corrupt published directory %s", target)
            shutil.rmtree(target, ignore_errors=True)

        try:
            os.rename(str(staging), str(target))
        except OSError:
            # Another writer may have published between our check and rename.
            if target.exists() and reuse_existing():
                shutil.rmtree(staging, ignore_errors=True)
                return target
            raise

        fsync_directory(target.parent)
        return target
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
