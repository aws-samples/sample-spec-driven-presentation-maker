# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Remote stateless attachment import adapter with immutable S3 bundle commit."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sdpm.tools.attachment.cache import (
    LocalStageCache,
    StageRecord,
    compute_hash,
    compute_pipeline_key,
)
from sdpm.tools.attachment.errors import AttachmentError, ImportConflict, SourceLimitExceeded, SourceNotFound
from sdpm.tools.attachment.fetcher import fetch_url
from sdpm.tools.attachment.limits import MAX_RAW_SIZE_BYTES
from sdpm.tools.attachment.pipeline import import_attachment_core
from sdpm.tools.attachment.source import (
    classify_source,
    sanitize_filename,
    source_identity_s3,
    validate_cloud_source,
)
from storage import Storage


def _fetch_url_cached_remote(source: str, user_id: str, storage: Storage):
    """Revalidate a URL and reuse its tagged S3 body cache after a secure 304."""
    from sdpm.tools.attachment.fetcher import FetchResult

    url_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    root = f"attachment-cache/v1/{user_id}/urls/{url_hash}"
    index_key = f"{root}/index.json"
    index: dict[str, Any] | None = None
    try:
        candidate = json.loads(storage.download_file_from_pptx_bucket(index_key))
        if isinstance(candidate, dict):
            index = candidate
    except Exception:
        pass

    if index is None:
        result = fetch_url(source)
    else:
        result = fetch_url(
            source,
            etag=index.get("etag") or None,
            last_modified=index.get("lastModified") or None,
        )

    if result.not_modified:
        if index is None:
            raise RuntimeError("URL returned 304 without a cache index")
        body_key = str(index.get("bodyKey", ""))
        if not body_key.startswith(f"{root}/bodies/"):
            raise RuntimeError("Cached URL body escaped its user-scoped prefix")
        body = storage.download_file_from_pptx_bucket(body_key)
        body_sha = str(index.get("bodySha256", ""))
        if len(body) != int(index.get("size", -1)) or hashlib.sha256(body).hexdigest() != body_sha:
            raise RuntimeError("Cached URL body failed checksum verification")
        return FetchResult(
            data=body,
            final_url=str(index.get("finalUrl") or source),
            content_type=index.get("contentType"),
            content_length=len(body),
            etag=result.etag or index.get("etag"),
            last_modified=result.last_modified or index.get("lastModified"),
            filename_from_header=index.get("filename"),
        )

    body_digest = hashlib.sha256(result.data).digest()
    body_sha = body_digest.hex()
    body_key = f"{root}/bodies/{body_sha}"
    checksum_b64 = base64.b64encode(body_digest).decode("ascii")
    storage.upload_file_if_absent(
        body_key,
        result.data,
        result.content_type or "application/octet-stream",
        checksum_b64,
        "sdpm-class=attachment-cache",
    )
    _verify_remote_object(storage, body_key, len(result.data), body_sha, checksum_b64)
    index_data = {
        "etag": result.etag,
        "lastModified": result.last_modified,
        "contentType": result.content_type,
        "filename": result.filename_from_header,
        "size": len(result.data),
        "bodySha256": body_sha,
        "bodyKey": body_key,
        "finalUrl": result.final_url,
    }
    storage.upload_file(
        index_key,
        json.dumps(index_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        "application/json",
        "sdpm-class=attachment-cache",
    )
    return result


def read_attachment(
    source: str,
    user_id: str,
    storage: Storage,
    offset: int = 0,
    limit: int = 10240,
) -> dict[str, Any]:
    """Read an owned S3 source or securely fetched public URL."""
    from sdpm.tools.attachment.pipeline import read_attachment_core

    try:
        kind = classify_source(source)
        if kind == "s3_key":
            validate_cloud_source(source, user_id)
            try:
                metadata = storage.head_object(source)
            except Exception:
                raise SourceNotFound(source)
            if int(metadata.get("ContentLength", 0)) > MAX_RAW_SIZE_BYTES:
                raise SourceLimitExceeded("S3 source exceeds the 100 MiB raw limit")
            raw = storage.download_file_from_pptx_bucket(source)
            if len(raw) != int(metadata.get("ContentLength", len(raw))) or len(raw) > MAX_RAW_SIZE_BYTES:
                raise SourceLimitExceeded("S3 source size changed during materialization")
            resolved_name = source.rsplit("/", 1)[-1]
            content_type = metadata.get("ContentType")
            source_identity = source_identity_s3(
                source,
                str(metadata.get("ETag", "")),
                len(raw),
            )
        elif kind == "url":
            fetched = _fetch_url_cached_remote(source, user_id, storage)
            raw = fetched.data
            resolved_name = fetched.filename_from_header or Path(urlparse(fetched.final_url).path).name or "attachment"
            content_type = fetched.content_type
            source_identity = {
                "kind": "url",
                "requestedUrl": source,
                "finalUrl": fetched.final_url,
                "etag": fetched.etag or "",
                "lastModified": fetched.last_modified or "",
                "size": len(raw),
            }
        else:
            return {"error": {"code": "INVALID_SOURCE", "message": "Cloud attachments require an owned S3 key or public HTTP(S) URL"}}

        resolved_name = sanitize_filename(resolved_name)
        with tempfile.TemporaryDirectory() as tmp:
            materialized = Path(tmp) / resolved_name
            materialized.write_bytes(raw)
            response = read_attachment_core(
                materialized_path=materialized,
                source=source,
                offset=offset,
                limit=limit,
                content_type=content_type,
                source_identity=source_identity,
                cache=_remote_stage_cache(user_id, storage),
            )
            if response.get("kind") == "image":
                response.pop("path", None)
                response["data"] = base64.b64encode(raw).decode("ascii")
                response["encoding"] = "base64"
            return response
    except AttachmentError as error:
        return error.to_dict()


logger = logging.getLogger(__name__)


class _RemoteStageCache(LocalStageCache):
    """S3-backed cache with local verified projection for warm invocations."""

    def __init__(self, storage: Storage, user_id: str) -> None:
        self._storage = storage
        self._user_id = user_id
        user_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
        super().__init__(
            base_dir=Path(tempfile.gettempdir()) / "sdpm-attachment-cache" / user_hash,
        )

    def _prefix(
        self,
        source_identity_hash: str,
        pipeline_key: str,
        stage: str,
        stage_key: str,
    ) -> str:
        return (
            f"attachment-cache/v1/{self._user_id}/sources/{source_identity_hash}/"
            f"pipelines/{pipeline_key}/stages/{stage}/{stage_key}"
        )

    def get_stage(
        self,
        source_identity_hash: str,
        pipeline_key: str,
        stage: str,
        stage_key: str,
    ) -> StageRecord | None:
        local = super().get_stage(source_identity_hash, pipeline_key, stage, stage_key)
        if local is not None:
            return local

        prefix = self._prefix(source_identity_hash, pipeline_key, stage, stage_key)
        try:
            data = json.loads(
                self._storage.download_file_from_pptx_bucket(f"{prefix}/complete.json")
            )
            if (
                data.get("stage") != stage
                or data.get("sourceIdentityHash") != source_identity_hash
                or compute_pipeline_key(
                    str(data.get("pipelineVersion", "")),
                    str(data.get("optionsHash", "")),
                ) != pipeline_key
            ):
                raise ValueError("remote cache completion identity mismatch")

            record_outputs: list[dict[str, Any]] = []
            self.base_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
            with tempfile.TemporaryDirectory(
                dir=str(self.base_dir),
                prefix="remote-download-",
            ) as temporary:
                outputs_dir = Path(temporary) / "outputs"
                outputs_dir.mkdir()
                for output in data.get("outputs", []):
                    relative = Path(str(output["path"]))
                    remote_key = str(output["key"])
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ValueError("unsafe remote cache output path")
                    if not remote_key.startswith(f"{prefix}/attempts/"):
                        raise ValueError("remote cache output escaped its stage prefix")
                    payload = self._storage.download_file_from_pptx_bucket(remote_key)
                    if len(payload) != int(output["size"]) or compute_hash(payload) != output["sha256"]:
                        raise ValueError("remote cache output checksum mismatch")
                    destination = outputs_dir / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(payload)
                    record_outputs.append({key: value for key, value in output.items() if key != "key"})

                record = StageRecord(
                    stage=stage,
                    source_identity_hash=source_identity_hash,
                    source_hash=str(data["sourceHash"]),
                    pipeline_version=str(data["pipelineVersion"]),
                    options_hash=str(data["optionsHash"]),
                    outputs=record_outputs,
                    completed_at=str(data["completedAt"]),
                )
                super().publish_stage(
                    source_identity_hash,
                    pipeline_key,
                    stage,
                    stage_key,
                    record,
                    outputs_dir,
                )
            return super().get_stage(source_identity_hash, pipeline_key, stage, stage_key)
        except Exception as error:
            logger.info("Remote attachment cache miss for %s: %s", stage, error)
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
        local_path = super().publish_stage(
            source_identity_hash,
            pipeline_key,
            stage,
            stage_key,
            record,
            outputs_dir,
        )
        prefix = self._prefix(source_identity_hash, pipeline_key, stage, stage_key)
        attempt_id = uuid.uuid4().hex
        remote_outputs: list[dict[str, Any]] = []
        for output in record.outputs:
            relative = str(output["path"])
            payload = (outputs_dir / relative).read_bytes()
            remote_key = f"{prefix}/attempts/{attempt_id}/outputs/{relative}"
            checksum = hashlib.sha256(payload).digest()
            self._storage.upload_file_if_absent(
                remote_key,
                payload,
                output.get("contentType") or "application/octet-stream",
                base64.b64encode(checksum).decode("ascii"),
                "sdpm-class=attachment-cache",
            )
            _verify_remote_object(
                self._storage,
                remote_key,
                int(output["size"]),
                str(output["sha256"]),
                base64.b64encode(checksum).decode("ascii"),
            )
            remote_outputs.append({**output, "key": remote_key})

        completion = {**record.to_dict(), "outputs": remote_outputs}
        completion_bytes = json.dumps(
            completion,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        checksum = hashlib.sha256(completion_bytes).digest()
        created = self._storage.upload_file_if_absent(
            f"{prefix}/complete.json",
            completion_bytes,
            "application/json",
            base64.b64encode(checksum).decode("ascii"),
            "sdpm-class=attachment-cache",
        )
        if not created:
            # The conditional completion winner is authoritative; repair local projection.
            if local_path.exists():
                import shutil
                shutil.rmtree(local_path)
            winner = self.get_stage(source_identity_hash, pipeline_key, stage, stage_key)
            if winner is None:
                raise RuntimeError("Remote stage cache winner could not be verified")
        return self.stage_dir(source_identity_hash, pipeline_key, stage, stage_key)


def _remote_stage_cache(user_id: str, storage: Storage) -> LocalStageCache:
    return _RemoteStageCache(storage, user_id)


def import_attachment(
    source: str,
    deck_id: str,
    user_id: str,
    storage: Storage,
    filename: str = "",
) -> str:
    """Materialize an owned source and commit one immutable import bundle."""
    try:
        try:
            _gc_manifestless_bundles(storage, deck_id)
        except Exception as error:
            logger.warning("Attachment orphan GC skipped for %s: %s", deck_id, error)
        kind = classify_source(source)
        if kind == "s3_key":
            validate_cloud_source(source, user_id)
            try:
                metadata = storage.head_object(source)
            except Exception:
                raise SourceNotFound(source)
            if int(metadata.get("ContentLength", 0)) > MAX_RAW_SIZE_BYTES:
                raise SourceLimitExceeded("S3 source exceeds the 100 MiB raw limit")
            raw = storage.download_file_from_pptx_bucket(source)
            if len(raw) != int(metadata.get("ContentLength", len(raw))) or len(raw) > MAX_RAW_SIZE_BYTES:
                raise SourceLimitExceeded("S3 source size changed during materialization")
            resolved_name = filename or source.rsplit("/", 1)[-1]
            content_type = metadata.get("ContentType")
            source_identity = source_identity_s3(
                source,
                str(metadata.get("ETag", "")),
                len(raw),
            )
        elif kind == "url":
            fetched = _fetch_url_cached_remote(source, user_id, storage)
            raw = fetched.data
            resolved_name = filename or fetched.filename_from_header or Path(urlparse(fetched.final_url).path).name or "attachment"
            content_type = fetched.content_type
            source_identity = {
                "kind": "url",
                "requestedUrl": source,
                "finalUrl": fetched.final_url,
                "etag": fetched.etag or "",
                "lastModified": fetched.last_modified or "",
                "size": len(raw),
            }
        else:
            return json.dumps({"error": {"code": "INVALID_SOURCE", "message": "Cloud attachments require an owned S3 key or public HTTP(S) URL"}})

        resolved_name = sanitize_filename(resolved_name)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            materialized = root / resolved_name
            materialized.write_bytes(raw)
            workspace = root / "workspace"
            workspace.mkdir()

            result = import_attachment_core(
                materialized_path=materialized,
                source=source,
                deck_dir=workspace,
                filename=resolved_name,
                content_type=content_type,
                source_identity=source_identity,
                cache=_remote_stage_cache(user_id, storage),
            )
            if result.get("code") == "IMPORT_INCOMPLETE" or "error" in result:
                return json.dumps(result, ensure_ascii=False)

            import_key = result["importKey"]
            bundle_prefix = f"decks/{deck_id}/attachments/imports/{import_key}"
            manifest_key = f"{bundle_prefix}/manifest.json"
            existing = _read_manifest(storage, manifest_key)
            if existing is not None:
                _validate_winner(existing, import_key, result["sourceHash"])
                return json.dumps(_response_from_manifest(existing, bundle_prefix, reused=True), ensure_ascii=False)

            local_bundle = workspace / "attachments" / "imports" / import_key
            winner = _commit_bundle(storage, local_bundle, bundle_prefix)
            response = _response_from_manifest(winner, bundle_prefix, reused=False)
            return json.dumps(response, ensure_ascii=False)
    except AttachmentError as error:
        return json.dumps(error.to_dict(), ensure_ascii=False)
    except Exception as error:
        logger.exception("Remote attachment import failed")
        return json.dumps({"error": {"code": "IMPORT_ERROR", "message": str(error)}}, ensure_ascii=False)


def _read_manifest(storage: Storage, key: str) -> dict[str, Any] | None:
    try:
        return json.loads(storage.download_file_from_pptx_bucket(key).decode("utf-8"))
    except Exception:
        return None


def _validate_winner(manifest: dict[str, Any], import_key: str, source_hash: str) -> None:
    if manifest.get("importKey") != import_key or manifest.get("sourceHash") != source_hash:
        raise ImportConflict(import_key)


def _response_from_manifest(manifest: dict[str, Any], bundle_prefix: str, *, reused: bool) -> dict[str, Any]:
    return {
        "importKey": manifest["importKey"],
        "sourceHash": manifest["sourceHash"],
        "reused": reused,
        "files": manifest.get("files", []),
        "imageMapping": manifest.get("imageMapping", {}),
        "deckJson": manifest.get("deckJson"),
        "templatePath": manifest.get("templatePath"),
        "bundlePath": f"attachments/imports/{manifest['importKey']}",
    }


def _commit_bundle(storage: Storage, local_bundle: Path, bundle_prefix: str) -> dict[str, Any]:
    """Publish immutable objects, verify each checksum, then CAS the manifest."""
    manifest_path = local_bundle / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("Core import did not produce a committed local bundle")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for entry in manifest.get("files", []):
        relative = entry["path"]
        local_file = local_bundle / relative
        data = local_file.read_bytes()
        digest = hashlib.sha256(data).digest()
        digest_hex = digest.hex()
        if len(data) != entry["size"] or digest_hex != entry["sha256"]:
            raise RuntimeError(f"Local bundle verification failed: {relative}")
        key = f"{bundle_prefix}/{relative}"
        content_type = entry.get("contentType") or mimetypes.guess_type(relative)[0] or "application/octet-stream"
        checksum_b64 = base64.b64encode(digest).decode("ascii")
        storage.upload_file_if_absent(
            key, data, content_type, checksum_b64, "sdpm-class=attachment-bundle",
        )
        _verify_remote_object(storage, key, len(data), digest_hex, checksum_b64)

    manifest_bytes = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    manifest_key = f"{bundle_prefix}/manifest.json"
    manifest_checksum = hashlib.sha256(manifest_bytes).digest()
    created = storage.upload_file_if_absent(
        manifest_key,
        manifest_bytes,
        "application/json",
        base64.b64encode(manifest_checksum).decode("ascii"),
        "sdpm-class=attachment-bundle",
    )
    if created:
        return manifest

    winner = _read_manifest(storage, manifest_key)
    if winner is None:
        raise RuntimeError("Manifest CAS lost but winner is unreadable")
    _validate_winner(winner, manifest["importKey"], manifest["sourceHash"])
    return winner


def _verify_remote_object(
    storage: Storage, key: str, expected_size: int, expected_hex: str, expected_b64: str,
) -> None:
    metadata = storage.head_object(key)
    if int(metadata.get("ContentLength", -1)) != expected_size:
        raise RuntimeError(f"Remote object size mismatch: {key}")
    remote_checksum = metadata.get("ChecksumSHA256")
    if remote_checksum:
        if remote_checksum != expected_b64:
            raise RuntimeError(f"Remote object checksum mismatch: {key}")
        return
    actual = hashlib.sha256(storage.download_file_from_pptx_bucket(key)).hexdigest()
    if actual != expected_hex:
        raise RuntimeError(f"Remote object checksum mismatch: {key}")


def _gc_manifestless_bundles(storage: Storage, deck_id: str) -> None:
    """Delete old uncommitted final prefixes with a bounded piggyback scan."""
    started = time.monotonic()
    root = f"decks/{deck_id}/attachments/imports/"
    objects = storage.list_object_metadata(root, max_objects=1000)
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in objects:
        relative = str(item.get("Key", "")).removeprefix(root)
        import_key = relative.split("/", 1)[0]
        if import_key:
            groups.setdefault(import_key, []).append(item)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for entries in groups.values():
        if time.monotonic() - started >= 1.0:
            break
        if any(str(entry.get("Key", "")).endswith("/manifest.json") for entry in entries):
            continue
        modified = [entry.get("LastModified") for entry in entries if isinstance(entry.get("LastModified"), datetime)]
        if modified and max(modified) < cutoff:
            storage.delete_object_keys([str(entry["Key"]) for entry in entries])
