# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Import bundle commit contract (Phase 0-7).

Bundle layout:
    attachments/imports/{importKey}/
    ├── manifest.json           # last to appear = committed
    ├── source/                 # original copy when needed
    ├── extracted/text/...
    ├── extracted/images/...
    ├── deck/deck.json          # PPTX edit branch
    ├── deck/slides/...
    └── deck/template.pptx

Local commit: same-filesystem staging → single directory rename.
Remote commit: immutable objects → manifest-last PUT with If-None-Match: *.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sdpm.tools.attachment.atomic import publish_directory
from sdpm.tools.attachment.errors import ImportConflict

logger = logging.getLogger(__name__)


@dataclass
class BundleManifest:
    """Import bundle manifest (version 1)."""

    import_key: str
    source_hash: str
    pipeline_version: str
    options: dict[str, Any]
    files: list[dict[str, Any]]  # [{path, size, sha256, contentType}]
    image_mapping: dict[str, str] = field(default_factory=dict)
    deck_json: str | None = None  # Relative path to deck.json within bundle
    template_path: str | None = None  # Relative path to template
    committed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "version": 1,
            "importKey": self.import_key,
            "sourceHash": self.source_hash,
            "pipelineVersion": self.pipeline_version,
            "options": self.options,
            "files": self.files,
            "committedAt": self.committed_at,
        }
        if self.image_mapping:
            d["imageMapping"] = self.image_mapping
        if self.deck_json:
            d["deckJson"] = self.deck_json
        if self.template_path:
            d["templatePath"] = self.template_path
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BundleManifest":
        """Parse a manifest from dict."""
        return cls(
            import_key=data["importKey"],
            source_hash=data["sourceHash"],
            pipeline_version=data["pipelineVersion"],
            options=data["options"],
            files=data["files"],
            image_mapping=data.get("imageMapping", {}),
            deck_json=data.get("deckJson"),
            template_path=data.get("templatePath"),
            committed_at=data.get("committedAt", ""),
        )


@dataclass
class LocalBundleCommitter:
    """Local import bundle committer using same-filesystem rename.

    Staging:  {deck_dir}/.sdpm-staging/imports/{request_id}/
    Target:   {deck_dir}/attachments/imports/{import_key}/
    """

    deck_dir: Path

    @property
    def imports_dir(self) -> Path:
        return self.deck_dir / "attachments" / "imports"

    def target_dir(self, import_key: str) -> Path:
        return self.imports_dir / import_key

    def staging_dir(self, request_id: str) -> Path:
        return self.deck_dir / ".sdpm-staging" / "imports" / request_id

    def get_committed(self, import_key: str) -> BundleManifest | None:
        """Check if a bundle is already committed.

        Returns manifest if committed and valid, None otherwise.
        """
        target = self.target_dir(import_key)
        manifest_path = target / "manifest.json"

        if not manifest_path.exists():
            return None

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = BundleManifest.from_dict(data)

            # Validate files exist and checksums match
            for file_entry in manifest.files:
                file_path = target / file_entry["path"]
                if not file_path.exists():
                    logger.warning("Bundle corrupt: missing %s", file_path)
                    return None
                if file_path.stat().st_size != file_entry["size"]:
                    logger.warning("Bundle corrupt: size mismatch %s", file_path)
                    return None
                if compute_file_sha256(file_path) != file_entry["sha256"]:
                    logger.warning("Bundle corrupt: checksum mismatch %s", file_path)
                    return None

            return manifest
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning("Bundle manifest corrupt for %s: %s", import_key, e)
            return None

    def create_staging(self, request_id: str) -> Path:
        """Create a staging directory for the import."""
        staging = self.staging_dir(request_id)
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        return staging

    def commit(self, request_id: str, manifest: BundleManifest) -> Path:
        """Atomically commit the staging bundle.

        Steps:
        1. Write manifest.json to staging (last file to appear)
        2. Publish via :func:`publish_directory` — fsync, then a single rename;
           if another writer already committed the same importKey, reuse it

        Returns:
            Path to committed bundle.

        Raises:
            ImportConflict: If target exists with different manifest.
        """
        staging = self.staging_dir(request_id)
        target = self.target_dir(manifest.import_key)

        for entry in manifest.files:
            candidate = staging / entry["path"]
            if (
                not candidate.is_file()
                or candidate.stat().st_size != entry["size"]
                or compute_file_sha256(candidate) != entry["sha256"]
            ):
                raise ImportConflict(manifest.import_key)

        # Write manifest as last file
        manifest.committed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        def _reuse_existing() -> bool:
            existing = self.get_committed(manifest.import_key)
            if existing is not None:
                if existing.source_hash == manifest.source_hash:
                    return True  # Same importKey already committed — reuse
                raise ImportConflict(manifest.import_key)
            if (target / "manifest.json").exists():
                # Manifest present but unreadable/mismatched — do not overwrite
                raise ImportConflict(manifest.import_key)
            return False  # No manifest: partial/corrupt target, replace it

        return publish_directory(staging, target, reuse_existing=_reuse_existing)

    def cleanup_staging(self, request_id: str) -> None:
        """Clean up a staging directory on failure."""
        staging = self.staging_dir(request_id)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def build_file_list(bundle_dir: Path) -> list[dict[str, Any]]:
    """Build the files list for a manifest from a staged bundle directory.

    Excludes manifest.json itself.
    """
    files: list[dict[str, Any]] = []
    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "manifest.json":
            continue
        rel = str(path.relative_to(bundle_dir))
        files.append({
            "path": rel,
            "size": path.stat().st_size,
            "sha256": compute_file_sha256(path),
            "contentType": _guess_content_type(path),
        })
    return files


def _guess_content_type(path: Path) -> str:
    """Guess content type from extension."""
    ext = path.suffix.lower()
    mapping = {
        ".json": "application/json",
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".pdf": "application/pdf",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    return mapping.get(ext, "application/octet-stream")
