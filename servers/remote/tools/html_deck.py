# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""HTML decks on the remote server: S3 I/O around the core HTML build.

Slide content may originate from LLM-generated text. Review output before distribution.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

The build itself is ``sdpm.api.refresh_html`` / ``sdpm.api.generate_html`` — the
same code as the local server. This module only materialises the S3 workspace
into a tmpdir, uploads ``output.html`` and the per-slide previews under ``html/``
(served through presigned URLs only, see shared/html_artifacts.py), keeps the
deck record pointing at the newest artifact, and deletes superseded objects.
"""

import json
import logging
import re
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from shared.html_artifacts import (
    HTML_CONTENT_TYPE,
    build_html_preview_key_map,
    output_key,
    preview_key,
    preview_prefix,
)
from storage import Storage
from tools import template_html_cache

logger = logging.getLogger("sdpm.html_deck")

REMOTE_PREVIEW_NOTE = "HTML decks have no PNG previews; the Web UI shows the deck and its thumbnails."
# Replaces the core report header, which points at a local output.html.
REMOTE_CHECK_REPORT_HEADER = "Static checks (no browser; the Web UI shows the deck and its thumbnails):"

# Deck files the HTML build reads (deck.json is written from the S3 deck.json).
_BUILD_FILES = frozenset({"specs/outline.md", "specs/art-direction.html", "deck.css"})
_SLIDE_RE = re.compile(r"^slides/[A-Za-z0-9_-]+\.html$")
_UPLOAD_WORKERS = 8


def _safe_relative(ref: str) -> str | None:
    """A deck-relative path that stays inside the deck, or None (absolute, ``..``, drive, backslash)."""
    if not ref or ref.startswith("/") or "\\" in ref or ":" in ref:
        return None
    parts = [p for p in PurePosixPath(ref).parts if p != "."]
    if not parts or ".." in parts:
        return None
    return "/".join(parts)


def _write(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def prepare_html_workspace(
    deck_id: str,
    user_id: str,
    storage: Storage,
    cache_root: str | Path | None = None,
) -> tuple[Path, dict]:
    """Materialise an HTML deck from S3 into a new tmpdir the core can build.

    deck.json (``template`` rewritten to the materialised file), the outline, the
    art direction, deck.css, slides/*.html, the files those name (deck-relative
    refs and ``assets:`` refs), the template and its conversion cache.

    Returns:
        (tmpdir, deck_meta) — the caller removes tmpdir.

    Raises:
        ValueError: the deck does not exist or its template cannot be resolved.

    The record is looked up under ``user_id`` (``USER#{user_id}``), as the PPTX
    build does, so only the owner can rebuild; see docs/en/architecture.md.
    """
    from sdpm.api import html_deck_refs
    from tools.generate import materialize_assets, materialize_template

    cache_root = template_html_cache.resolve_root(cache_root)

    if not storage.get_deck(deck_id, user_id):
        raise ValueError(f"Deck {deck_id} not found.")

    tmpdir = Path(tempfile.mkdtemp(prefix="sdpm-html-"))
    try:
        deck_meta = storage.get_deck_json(deck_id)
        prefix = f"decks/{deck_id}/"
        for key in storage.list_files(prefix=prefix, bucket=storage.pptx_bucket):
            rel = key.removeprefix(prefix)
            if rel in _BUILD_FILES or _SLIDE_RE.match(rel):
                _write(tmpdir / rel, storage.download_file_from_pptx_bucket(key))
        # deck.json first with the original template so html_deck_refs can read the deck.
        (tmpdir / "deck.json").write_text(json.dumps(deck_meta, ensure_ascii=False), encoding="utf-8")

        refs = html_deck_refs(tmpdir)
        for ref in sorted(refs["relative"]):
            rel = _safe_relative(ref)
            if rel is None or (tmpdir / rel).exists():
                continue  # the assembler reports what stays unresolved
            try:
                _write(tmpdir / rel, storage.download_file_from_pptx_bucket(f"{prefix}{rel}"))
            except Exception:
                logger.info("html deck %s: %s not on S3", deck_id, rel)
        assets = {ref.removeprefix("assets:") for ref in refs["assets"]}
        if assets:  # manifests are large; fetch them only when a slide names an asset
            materialize_assets(assets, storage, tmpdir)

        template_path = materialize_template(deck_id, user_id, deck_meta, storage, tmpdir)
        built_meta = {**deck_meta, "template": template_path.name}
        (tmpdir / "deck.json").write_text(json.dumps(built_meta, ensure_ascii=False), encoding="utf-8")
        template_html_cache.restore(template_path, storage, cache_root)
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    return tmpdir, deck_meta


def _outline_order(tmpdir: Path, slugs: dict[str, str]) -> list[str]:
    from sdpm.api import parse_outline_slugs

    order = [s for s in parse_outline_slugs(tmpdir / "specs" / "outline.md") if s in slugs]
    return order + [s for s in slugs if s not in order]


def _upload_previews(
    deck_id: str, tmpdir: Path, previews: dict[str, str], slugs: list[str], epoch: int, storage: Storage,
) -> dict[str, str]:
    """Upload ``preview/<slug>.html`` of ``slugs`` under one epoch; returns {slug: key} of the successes."""

    def _one(slug: str) -> tuple[str, str | None]:
        key = preview_key(deck_id, slug, epoch)
        try:
            storage.upload_file(
                key=key, data=(tmpdir / previews[slug]).read_bytes(), content_type=HTML_CONTENT_TYPE,
            )
            return slug, key
        except Exception:
            logger.warning("preview upload failed for %s/%s", deck_id, slug, exc_info=True)
            return slug, None

    if not slugs:
        return {}
    with ThreadPoolExecutor(max_workers=_UPLOAD_WORKERS) as pool:
        done = list(pool.map(_one, slugs))
    return {slug: key for slug, key in done if key}


def _delete(storage: Storage, keys: list[str]) -> None:
    if not keys:
        return
    try:
        storage.delete_object_keys(keys)
    except Exception:
        logger.warning("delete of %d superseded HTML objects failed", len(keys), exc_info=True)


def _publish(
    deck_id: str,
    user_id: str,
    storage: Storage,
    output_path: Path,
    slide_count: int,
    thumbnail_key: str | None,
    set_thumbnail: bool,
) -> str:
    """Upload output.html under a fresh key, point the record at it, delete the superseded one.

    Raises on upload / record failure after deleting the orphaned upload (best effort).
    """
    new_key = output_key(deck_id)
    storage.upload_file(key=new_key, data=output_path.read_bytes(), content_type=HTML_CONTENT_TYPE)
    updates: dict[str, Any] = {
        "htmlS3Key": new_key,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "slideCount": slide_count,
    }
    if set_thumbnail:
        updates["thumbnailS3Key"] = thumbnail_key
    try:
        old = storage.update_deck(deck_id=deck_id, user_id=user_id, updates=updates)
    except Exception:
        _delete(storage, [new_key])
        raise
    old_key = (old or {}).get("htmlS3Key")
    if old_key and old_key != new_key:
        _delete(storage, [old_key])
    return new_key


_PREVIEW_EPOCH_RE = re.compile(r"/([a-z0-9][a-z0-9-_]*)_(\d+)\.html$")


def _slug_epoch(key: str) -> tuple[str, int] | None:
    m = _PREVIEW_EPOCH_RE.search(key)
    return (m.group(1), int(m.group(2))) if m else None


def _listed_previews(storage: Storage, deck_id: str) -> list[str]:
    try:
        return storage.list_files(prefix=preview_prefix(deck_id), bucket=storage.pptx_bucket)
    except Exception:
        logger.warning("preview listing failed for %s", deck_id, exc_info=True)
        return []


def refresh_html_deck(
    deck_id: str,
    user_id: str,
    storage: Storage,
    changed_paths: list[str],
    measure_slides: list[str] | None,
    cache_root: str | Path | None = None,
) -> dict:
    """run_python post-processing for an HTML deck: rebuild, upload, record.

    Uploads output.html to a new ``html/{deck}/<uuid>.html`` key and the previews of
    the affected, measured and not-yet-uploaded slides under one epoch. Never raises:
    a failure comes back as ``html_error`` (the deck's HTML is then stale).

    Returns:
        The ``sdpm.api.refresh_html`` result with ``html`` = the S3 key, ``previews``
        = {slug: key} uploaded now, and the remote preview note.
    """
    from sdpm.api import refresh_html

    cache_root = template_html_cache.resolve_root(cache_root)
    epoch = int(time.time())
    try:
        tmpdir, _ = prepare_html_workspace(deck_id, user_id, storage, cache_root)
    except Exception as e:
        logger.warning("HTML workspace preparation failed for %s", deck_id, exc_info=True)
        return {"html_error": f"HTML build failed — the deck's HTML is stale: {e}"}
    try:
        built = refresh_html(tmpdir, changed_paths, measure_slides, template_cache=cache_root)
        if "html_error" in built:
            return {"html_error": built["html_error"]}
        previews: dict[str, str] = built.get("previews") or {}
        order = _outline_order(tmpdir, previews)

        listed = _listed_previews(storage, deck_id)
        existing = build_html_preview_key_map(listed)
        wanted = set(built.get("affected") or []) | set(measure_slides or [])
        wanted |= {s for s in order if s not in existing}
        uploaded = _upload_previews(deck_id, tmpdir, previews, [s for s in order if s in wanted], epoch, storage)

        result: dict[str, Any] = {k: v for k, v in built.items() if k not in ("html", "previews")}
        # thumbnailS3Key follows slide 1: set when slide 1 was uploaded now, or
        # when the record has none yet.
        first = order[0] if order else None
        thumbnail = (uploaded.get(first) or existing.get(first)) if first else None
        set_thumbnail = first is None or first in uploaded
        if not set_thumbnail:
            try:
                set_thumbnail = not (storage.get_deck(deck_id, user_id) or {}).get("thumbnailS3Key")
            except Exception:
                set_thumbnail = False
        try:
            result["html"] = _publish(
                deck_id, user_id, storage, Path(built["html"]), len(order), thumbnail, set_thumbnail,
            )
        except Exception as e:
            logger.warning("HTML artifact refresh failed for %s: %s", deck_id, e)
            result["html_error"] = (
                f"HTML artifact refresh failed — the deck's HTML is stale. "
                f"Run generate_pptx to refresh it. ({e})"
            )
        else:
            # Older epochs of the slides just uploaded are superseded, and a slide the
            # build left out (e.g. a structure error) loses its preview: the previews
            # must list exactly the slides output.html contains, or the Web UI's
            # thumbnail index drifts from the player's slide index.
            built_slugs = set(order)
            _delete(storage, [
                k for k in listed
                if (se := _slug_epoch(k))
                and ((se[0] in uploaded and se[1] < epoch) or se[0] not in built_slugs)
            ])
        result["previews"] = uploaded
        if "preview" in result:
            result["preview"] = {"status": "unavailable", "reason": "html-deck", "note": REMOTE_PREVIEW_NOTE}
        if isinstance(result.get("measure"), str):
            from sdpm.engine.html.check import CHECK_REPORT_HEADER

            result["measure"] = result["measure"].replace(CHECK_REPORT_HEADER, REMOTE_CHECK_REPORT_HEADER, 1)
        template_html_cache.persist(tmpdir / "template.pptx", storage, cache_root)
        return result
    except Exception as e:  # reported to the agent, never raised
        logger.exception("HTML refresh failed for %s", deck_id)
        return {"html_error": f"HTML build failed — the deck's HTML is stale: {e}"}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def finalize_html_deck(
    deck_id: str,
    user_id: str,
    storage: Storage,
    kb_sync: object | None = None,
    cache_root: str | Path | None = None,
) -> dict:
    """generate_pptx for an HTML deck: full build, every preview, record, KB sync.

    Uploads output.html and all previews under a new epoch, deletes every older
    preview and the superseded output, points the record (htmlS3Key, slideCount,
    thumbnailS3Key = slide 1) at them and indexes the slides' text in the KB.

    Returns:
        {status, outputFormat: "html", slideCount, slides, bytes} plus ``warnings``
        (build, decorations, kbSyncFailed) when there are any.

    Raises:
        ValueError: the deck does not exist; any build or upload failure propagates.
    """
    from sdpm.api import generate_html, html_slide_texts

    cache_root = template_html_cache.resolve_root(cache_root)
    t0 = time.monotonic()
    tmpdir, _ = prepare_html_workspace(deck_id, user_id, storage, cache_root)
    try:
        gen = generate_html(tmpdir, template_cache=cache_root)
        previews: dict[str, str] = gen.get("previews") or {}
        order = _outline_order(tmpdir, previews)
        epoch = int(time.time())
        before = _listed_previews(storage, deck_id)
        uploaded = _upload_previews(deck_id, tmpdir, previews, order, epoch, storage)
        missing = [s for s in order if s not in uploaded]
        if missing:
            # This run's keys would win the preview key map over the previous complete set.
            _delete(storage, list(uploaded.values()))
            raise RuntimeError(f"preview upload failed for {', '.join(missing)}")
        _publish(
            deck_id, user_id, storage, Path(gen["output_path"]), gen["slide_count"],
            uploaded.get(order[0]) if order else None, True,
        )
        fresh = set(uploaded.values())
        _delete(storage, [k for k in before if k not in fresh])
        texts = html_slide_texts(tmpdir)
        template_html_cache.persist(tmpdir / "template.pptx", storage, cache_root)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    logger.info("finalize_html_deck for deck %s took %.1fs", deck_id, time.monotonic() - t0)

    kb_error: str | None = None
    if kb_sync:
        deck = storage.get_deck(deck_id, user_id) or {}
        try:
            kb_sync.sync_deck(
                deck_id=deck_id,
                user_id=user_id,
                deck_name=deck.get("name", ""),
                visibility=deck.get("visibility", "private"),
                slides=[
                    {
                        "id": s["slug"],
                        "layout": s.get("layout") or "",
                        "title": s.get("title") or "",
                        "notes": s.get("notes") or "",
                        "elements": [{"text": s.get("text") or ""}],
                    }
                    for s in texts
                ],
            )
        except Exception as e:
            kb_error = str(e)

    # Structured usage event (same shape as tools.generate.generate_pptx).
    logger.info(json.dumps({
        "kind": "slides_built",
        "user_id": user_id,
        "deck_id": deck_id,
        "slide_count": gen["slide_count"],
    }))
    result: dict[str, Any] = {
        "status": "completed",
        "outputFormat": "html",
        "slideCount": gen["slide_count"],
        "slides": gen["slides"],
        "bytes": gen["bytes"],
    }
    warnings: dict[str, Any] = {}
    if kb_error:
        warnings["kbSyncFailed"] = kb_error
    if gen.get("warnings"):
        warnings["build"] = gen["warnings"]
    if gen.get("decorations"):
        warnings["decorations"] = gen["decorations"]
    if warnings:
        result["warnings"] = warnings
    return result
