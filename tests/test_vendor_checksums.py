# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""sdpm/vendor/SHA256SUMS lists every vendored file with its current sha256."""

from __future__ import annotations

import hashlib

from sdpm.config import VENDOR_DIR

_UNLISTED = {"README.md", "SHA256SUMS"}


def _manifest() -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in (VENDOR_DIR / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, path = line.split(maxsplit=1)
        entries[path.removeprefix("./")] = digest
    return entries


def test_manifest_lists_every_vendored_file():
    on_disk = {
        p.relative_to(VENDOR_DIR).as_posix()
        for p in VENDOR_DIR.rglob("*")
        if p.is_file() and p.name not in _UNLISTED and "__pycache__" not in p.parts
    }
    assert set(_manifest()) == on_disk


def test_vendored_files_match_their_checksums():
    for path, digest in _manifest().items():
        actual = hashlib.sha256((VENDOR_DIR / path).read_bytes()).hexdigest()
        assert actual == digest, f"{path} does not match SHA256SUMS"
