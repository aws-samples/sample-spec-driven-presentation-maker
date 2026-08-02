# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Stage cache: identity hashing, atomic publish, and lookup (Phase 0-4).

Cache layout (Local):
    $XDG_CACHE_HOME/sdpm/attachments/v1/
      sources/{sourceIdentityHash}/pipelines/{pipelineKey}/stages/{stage}/{stageKey}/
        outputs/...
        complete.json

Cache layout (Remote):
    attachment-cache/v1/{userId}/
      sources/{sourceIdentityHash}/pipelines/{pipelineKey}/stages/{stage}/{stageKey}/
        attempts/{requestId}/...
        complete.json

Stage order (fixed): materialize, extract_text, extract_images, convert_deck, validate_bundle
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sdpm
from sdpm.tools.attachment import ATTACHMENT_PIPELINE_REVISION

logger = logging.getLogger(__name__)

# Fixed stage order — monotonically increasing
STAGE_ORDER = ("materialize", "extract_text", "extract_images", "convert_deck", "validate_bundle")


def pipeline_version() -> str:
    """Current pipeline version string."""
    return f"{sdpm.__version__}:attachment-{ATTACHMENT_PIPELINE_REVISION}"


def compute_hash(data: str | bytes) -> str:
    """Compute SHA-256 hex digest."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def compute_source_identity_hash(identity: dict[str, Any]) -> str:
    """Compute hash of a source identity dict (canonical JSON)."""
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return compute_hash(canonical)


def compute_pipeline_key(version: str, options_hash: str) -> str:
    """Compute pipeline key from version + options."""
    canonical = json.dumps({"pipelineVersion": version, "optionsHash": options_hash}, sort_keys=True, separators=(",", ":"))
    return compute_hash(canonical)


def compute_import_key(source_hash: str, pipeline_ver: str, options: dict[str, Any]) -> str:
    """Compute importKey = SHA-256(sourceHash + pipelineVersion + canonical(options))."""
    canonical_options = json.dumps(options, sort_keys=True, separators=(",", ":"))
    combined = f"{source_hash}:{pipeline_ver}:{canonical_options}"
    return compute_hash(combined)


def compute_stage_key(stage: str, config: dict[str, Any] | None = None) -> str:
    """Compute stage-specific cache key."""
    data = {"stage": stage}
    if config:
        data["config"] = config
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return compute_hash(canonical)


@dataclass
class StageRecord:
    """A stage completion record."""

    stage: str
    source_identity_hash: str
    source_hash: str
    pipeline_version: str
    options_hash: str
    outputs: list[dict[str, Any]]  # [{path, size, sha256, contentType}]
    completed_at: str  # ISO timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "sourceIdentityHash": self.source_identity_hash,
            "sourceHash": self.source_hash,
            "pipelineVersion": self.pipeline_version,
            "optionsHash": self.options_hash,
            "outputs": self.outputs,
            "completedAt": self.completed_at,
        }


@dataclass
class LocalStageCache:
    """Local XDG-based stage cache with flock + atomic directory rename."""

    base_dir: Path | None = None

    def __post_init__(self) -> None:
        if self.base_dir is None:
            xdg_cache = os.environ.get("XDG_CACHE_HOME", "")
            if not xdg_cache:
                xdg_cache = str(Path.home() / ".cache")
            self.base_dir = Path(xdg_cache) / "sdpm" / "attachments" / "v1"

    def stage_dir(
        self,
        source_identity_hash: str,
        pipeline_key: str,
        stage: str,
        stage_key: str,
    ) -> Path:
        """Compute the path for a stage cache entry."""
        return (
            self.base_dir  # type: ignore[operator]
            / "sources" / source_identity_hash
            / "pipelines" / pipeline_key
            / "stages" / stage
            / stage_key
        )

    def get_stage(
        self,
        source_identity_hash: str,
        pipeline_key: str,
        stage: str,
        stage_key: str,
    ) -> StageRecord | None:
        """Look up a completed stage record. Returns None on miss/corrupt."""
        stage_path = self.stage_dir(source_identity_hash, pipeline_key, stage, stage_key)
        complete_path = stage_path / "complete.json"

        if not complete_path.exists():
            return None

        try:
            data = json.loads(complete_path.read_text(encoding="utf-8"))
            if (
                data.get("stage") != stage
                or data.get("sourceIdentityHash") != source_identity_hash
                or compute_pipeline_key(
                    str(data.get("pipelineVersion", "")),
                    str(data.get("optionsHash", "")),
                ) != pipeline_key
            ):
                logger.warning("Cache miss: completion identity mismatch for %s", stage_path)
                return None
            # Validate outputs exist and checksums match
            outputs_dir = stage_path / "outputs"
            for output in data.get("outputs", []):
                output_path = outputs_dir / output["path"]
                if not output_path.exists():
                    logger.warning("Cache miss: output %s missing", output_path)
                    return None
                if output_path.stat().st_size != output["size"]:
                    logger.warning("Cache miss: size mismatch for %s", output_path)
                    return None
                if compute_hash(output_path.read_bytes()) != output["sha256"]:
                    logger.warning("Cache miss: checksum mismatch for %s", output_path)
                    return None
            return StageRecord(
                stage=data["stage"],
                source_identity_hash=data["sourceIdentityHash"],
                source_hash=data["sourceHash"],
                pipeline_version=data["pipelineVersion"],
                options_hash=data["optionsHash"],
                outputs=data["outputs"],
                completed_at=data["completedAt"],
            )
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning("Cache corrupt for %s: %s", stage_path, e)
            return None

    def publish_stage(
        self,
        source_identity_hash: str,
        pipeline_key: str,
        stage: str,
        stage_key: str,
        record: StageRecord,
        outputs_dir: Path,
    ) -> Path:
        """Atomically publish a stage result using flock + rename.

        Args:
            source_identity_hash: Source identity hash.
            pipeline_key: Pipeline key.
            stage: Stage name.
            stage_key: Stage cache key.
            record: Completion record.
            outputs_dir: Temp directory with outputs to publish.

        Returns:
            Final stage directory path.
        """
        target = self.stage_dir(source_identity_hash, pipeline_key, stage, stage_key)
        lock_dir = target.parent
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / f".{stage_key}.lock"

        # Prepare staging directory as sibling of target
        import uuid
        staging = target.parent / f".staging-{stage_key}-{os.getpid()}-{uuid.uuid4().hex}"
        if staging.exists():
            shutil.rmtree(staging)

        staging.mkdir(parents=True)
        staging_outputs = staging / "outputs"

        # Copy outputs to staging
        if outputs_dir.exists():
            shutil.copytree(outputs_dir, staging_outputs)
        else:
            staging_outputs.mkdir()

        # Write completion record
        complete_path = staging / "complete.json"
        complete_path.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=None),
            encoding="utf-8",
        )

        # Fsync the staging directory
        _fsync_dir(staging)

        # Atomic publish under flock
        try:
            with open(lock_path, "w") as lf:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                try:
                    if target.exists():
                        # Winner already exists — verify and reuse
                        existing = self.get_stage(source_identity_hash, pipeline_key, stage, stage_key)
                        if existing is not None:
                            shutil.rmtree(staging)
                            return target
                        # Corrupt existing — remove and replace
                        shutil.rmtree(target)
                    os.rename(str(staging), str(target))
                finally:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        except OSError:
            # Clean up staging on failure
            if staging.exists():
                shutil.rmtree(staging)
            raise
        finally:
            # Clean up lock file
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass

        return target


def _fsync_dir(path: Path) -> None:
    """Fsync a directory and its contents."""
    for child in path.rglob("*"):
        if child.is_file():
            fd = os.open(str(child), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    # Fsync the directory itself
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def get_completed_stages(
    cache: LocalStageCache,
    source_identity_hash: str,
    pipeline_key: str,
    stage_keys: dict[str, str],
) -> list[str]:
    """Get list of completed stages in order.

    Args:
        cache: The stage cache.
        source_identity_hash: Source identity hash.
        pipeline_key: Pipeline key.
        stage_keys: Dict mapping stage name -> stage key.

    Returns:
        List of completed stage names in STAGE_ORDER.
    """
    completed = []
    for stage in STAGE_ORDER:
        sk = stage_keys.get(stage)
        if sk is None:
            continue
        record = cache.get_stage(source_identity_hash, pipeline_key, stage, sk)
        if record is not None:
            completed.append(stage)
    return completed
