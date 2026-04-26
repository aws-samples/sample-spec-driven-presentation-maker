# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Import attachments into deck workspace — from uploads or URLs."""

import json
import mimetypes
import uuid

import requests as http_requests

from storage import Storage

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
_ALLOWED_URL_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}


def import_attachment(
    source: str,
    deck_id: str,
    user_id: str,
    storage: Storage,
    filename: str = "",
) -> str:
    """Import a file into the deck workspace.

    source is either an uploadId or an HTTP(S) URL.
    - uploadId: copies pre-converted files from upload storage to deck.
    - URL: downloads image and saves to deck.

    Returns JSON with saved paths and image_mapping.
    """
    if source.startswith("http://") or source.startswith("https://"):
        return _import_from_url(source, deck_id, storage, filename)
    return _import_from_upload(source, deck_id, user_id, storage, filename)


def _import_from_upload(
    upload_id: str, deck_id: str, user_id: str, storage: Storage, filename: str,
) -> str:
    """Copy pre-converted upload files to deck workspace."""
    short_id = uuid.uuid4().hex[:8]

    resp = storage.table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"UPLOAD#{upload_id}"})
    item = resp.get("Item")
    if not item:
        return json.dumps({"error": f"Upload {upload_id} not found"})

    status = item.get("status", "unknown")
    file_name = filename or item.get("fileName", "unknown")
    file_type = item.get("fileType", "")
    s3_key = item.get("s3KeyRaw", "")

    result = {"source": upload_id, "files": [], "image_mapping": {}}

    # --- Converted files (PDF/DOCX/XLSX/PPTX) ---
    if status == "converted":
        converted_prefix = f"uploads/{user_id}/{upload_id}/converted"
        return _import_converted(converted_prefix, deck_id, user_id, storage, file_name, filename, short_id, result)

    # --- Completed PPTX: lazy convert then import ---
    _PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if status == "completed" and file_type == _PPTX_MIME and s3_key:
        converted_prefix = f"uploads/{user_id}/{upload_id}/converted"
        # Check cache first
        cached = storage.list_files(converted_prefix)
        if not cached:
            import mimetypes as _mt
            import tempfile
            from pathlib import Path as _Path
            from shared.ingest import convert_file
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = _Path(tmp)
                local_file = tmp_path / file_name
                output_dir = tmp_path / "converted"
                local_file.write_bytes(storage.download_file_from_pptx_bucket(s3_key))
                conv = convert_file(local_file, output_dir)
                if conv.status == "error":
                    return json.dumps({"error": f"PPTX conversion failed: {conv.error}"})
                if output_dir.exists():
                    for f in output_dir.rglob("*"):
                        if f.is_file():
                            rel = f.relative_to(output_dir)
                            ct = _mt.guess_type(str(f))[0] or "application/octet-stream"
                            storage.upload_file(key=f"{converted_prefix}/{rel}", data=f.read_bytes(), content_type=ct)
            storage.table.update_item(
                Key={"PK": f"USER#{user_id}", "SK": f"UPLOAD#{upload_id}"},
                UpdateExpression="SET #st = :st",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={":st": "converted"},
            )
        # Now import as converted
        item["status"] = "converted"
        return _import_converted(converted_prefix, deck_id, user_id, storage, file_name, filename, short_id, result)

    if status == "completed" and s3_key:
        data = storage.download_file_from_pptx_bucket(s3_key)

        if file_type.startswith("image/"):
            dest_name = f"{short_id}_{file_name}"
            dest_key = f"decks/{deck_id}/images/{dest_name}"
            ct = mimetypes.guess_type(file_name)[0] or file_type
            storage.upload_file(key=dest_key, data=data, content_type=ct)
            result["files"].append(f"images/{dest_name}")
            result["image_mapping"][file_name] = f"images/{dest_name}"
        else:
            dest_name = f"{short_id}_{file_name}"
            dest_key = f"decks/{deck_id}/attachments/{dest_name}"
            ct = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
            storage.upload_file(key=dest_key, data=data, content_type=ct)
            result["files"].append(f"attachments/{dest_name}")

        return json.dumps(result, ensure_ascii=False)

    return json.dumps({"error": f"Upload {upload_id} is {status}, cannot import"})


def _import_from_url(url: str, deck_id: str, storage: Storage, filename: str) -> str:
    """Download image from URL and save to deck workspace."""
    import os
    import urllib.parse

    short_id = uuid.uuid4().hex[:8]

    try:
        resp = http_requests.get(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; sdpm-agent/1.0)"}, timeout=30,
        )
        resp.raise_for_status()
        data = resp.content
        ct = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    except Exception as e:
        return json.dumps({"error": f"Failed to download: {e}"})

    if ct not in _ALLOWED_URL_TYPES:
        return json.dumps({"error": f"Not an image: {ct}"})

    if not filename:
        parsed = urllib.parse.urlparse(url)
        basename = os.path.basename(parsed.path.split("?")[0]) or "image"
        ext = mimetypes.guess_extension(ct) or ".png"
        if not basename.endswith(ext):
            basename = basename.rsplit(".", 1)[0] + ext if "." in basename else basename + ext
        filename = basename

    dest_name = f"{short_id}_{filename}"
    dest_key = f"decks/{deck_id}/images/{dest_name}"
    storage.upload_file(key=dest_key, data=data, content_type=ct)

    result = {
        "source": url,
        "files": [f"images/{dest_name}"],
        "image_mapping": {filename: f"images/{dest_name}"},
    }
    return json.dumps(result, ensure_ascii=False)


def _import_converted(
    converted_prefix: str, deck_id: str, user_id: str, storage: Storage,
    file_name: str, filename: str, short_id: str, result: dict,
) -> str:
    """Copy converted files from S3 upload prefix to deck workspace."""
    keys = storage.list_files(converted_prefix)

    for key in keys:
        rel = key[len(converted_prefix) + 1:]  # strip prefix + /
        src_data = storage.download_file_from_pptx_bucket(key)

        if rel.startswith("images/"):
            img_name = rel.split("/", 1)[1]
            dest_name = f"{short_id}_{img_name}"
            dest_key = f"decks/{deck_id}/images/{dest_name}"
            ct = mimetypes.guess_type(img_name)[0] or "application/octet-stream"
            storage.upload_file(key=dest_key, data=src_data, content_type=ct)
            result["files"].append(f"images/{dest_name}")
            result["image_mapping"][img_name] = f"images/{dest_name}"
        elif rel == "slides.json":
            dest_name = f"{short_id}_{file_name.rsplit('.', 1)[0]}.json"
            dest_key = f"decks/{deck_id}/attachments/{dest_name}"
            storage.upload_file(key=dest_key, data=src_data, content_type="application/json")
            result["files"].append(f"attachments/{dest_name}")
            result["json"] = f"attachments/{dest_name}"
        else:
            dest_name = f"{short_id}_{rel}"
            dest_key = f"decks/{deck_id}/attachments/{dest_name}"
            ct = "text/markdown" if rel.endswith(".md") else "application/octet-stream"
            storage.upload_file(key=dest_key, data=src_data, content_type=ct)
            result["files"].append(f"attachments/{dest_name}")
            if rel.endswith(".md"):
                result["markdown"] = f"attachments/{dest_name}"

    return json.dumps(result, ensure_ascii=False)
