# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""PPTX generation — builds PowerPoint from S3 deck workspace.

Slide content may originate from LLM-generated text. Review output before distribution.
Generated PPTX files are uploaded to S3 with server-side encryption.
Presigned URLs are used for time-limited access to output files.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

Reads deck.json + outline.md + slides/*.json + includes from S3,
resolves include references, and builds PPTX via sdpm.engine.builder.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from storage import Storage

logger = logging.getLogger("sdpm.generate")


def generate_previews(pptx_path: Path, output_dir: Path) -> list[Path]:
    """Convert PPTX → PDF → per-page WebP via LibreOffice + pdftoppm + Pillow.

    Args:
        pptx_path: Path to the PPTX file.
        output_dir: Directory for intermediate and output files.

    Returns:
        Sorted list of WebP file paths.
    """
    from PIL import Image

    env = os.environ.copy()
    env["HOME"] = str(output_dir)

    # PPTX → PDF
    subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(pptx_path)],
        env=env, capture_output=True, text=True, timeout=120, check=True,
    )
    pdf_path = output_dir / pptx_path.with_suffix(".pdf").name
    if not pdf_path.exists():
        raise FileNotFoundError("LibreOffice did not produce PDF")

    # PDF → per-page PNGs
    subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        ["pdftoppm", "-png", "-r", "200", str(pdf_path), str(output_dir / "slide")],
        capture_output=True, text=True, timeout=120, check=True,
    )

    # PNG → WebP
    webp_files: list[Path] = []
    for png_path in sorted(output_dir.glob("slide-*.png")):
        webp_path = png_path.with_suffix(".webp")
        Image.open(png_path).save(webp_path, "WEBP", quality=85)
        webp_files.append(webp_path)
    return webp_files


def _assemble_slides(tmpdir: Path) -> list[dict]:
    """Assemble slide list from workspace directory.

    Reads outline.md for slug order, then loads slides/{slug}.json in order.
    Missing slides are skipped silently.

    Args:
        tmpdir: Workspace directory.

    Returns:
        Ordered list of slide dicts.
    """
    from sdpm.api import parse_outline_slugs
    slugs = parse_outline_slugs(tmpdir / "specs" / "outline.md")
    slides: list[dict] = []
    for slug in slugs:
        slide_path = tmpdir / "slides" / f"{slug}.json"
        if not slide_path.exists():
            continue
        slide = json.loads(slide_path.read_text(encoding="utf-8"))
        slide.setdefault("id", slug)
        slides.append(slide)
    if not slides:
        raise ValueError(f"No slides found in {tmpdir}")
    return slides


def _prepare_workspace(
    deck_id: str,
    user_id: str,
    storage: Storage,
) -> tuple[Path, list[dict], dict]:
    """Download S3 workspace to tmpdir and prepare for PPTX build.

    Returns:
        (tmpdir, slides, build_kwargs) where build_kwargs has keys:
        template_path, custom_template, fonts, base_dir, default_text_color
    """
    from sdpm.engine.analyzer import extract_fonts
    from sdpm.engine.builder import PPTXBuilder  # noqa: F401 — validate import

    deck = storage.get_deck(deck_id, user_id)
    if not deck:
        raise ValueError(f"Deck {deck_id} not found.")

    tmpdir = Path(tempfile.mkdtemp())

    # Download deck.json
    deck_meta = storage.get_deck_json(deck_id)
    (tmpdir / "deck.json").write_text(
        json.dumps(deck_meta, ensure_ascii=False), encoding="utf-8"
    )

    # Download outline.md
    outline_key = f"decks/{deck_id}/specs/outline.md"
    try:
        data = storage.download_file_from_pptx_bucket(outline_key)
        specs_dir = tmpdir / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        (specs_dir / "outline.md").write_bytes(data)
    except Exception:
        logger.warning("outline.md not found for deck %s", deck_id)

    # Download slides/*.json
    slide_keys = storage.list_files(
        prefix=f"decks/{deck_id}/slides/", bucket=storage.pptx_bucket
    )
    for key in slide_keys:
        rel = key.replace(f"decks/{deck_id}/", "")
        dest = tmpdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(storage.download_file_from_pptx_bucket(key))

    presentation = {**deck_meta}

    # Assemble slides
    slides = _assemble_slides(tmpdir)
    if not slides:
        raise ValueError(f"Deck {deck_id} has no slides.")

    # Materialize only immutable bundle artifacts referenced by active slide JSON.
    def _collect_import_refs(value: object) -> set[str]:
        refs: set[str] = set()
        if isinstance(value, str) and value.startswith("attachments/imports/"):
            if ".." not in PurePosixPath(value).parts:
                refs.add(value)
        elif isinstance(value, dict):
            for child in value.values():
                refs.update(_collect_import_refs(child))
        elif isinstance(value, list):
            for child in value:
                refs.update(_collect_import_refs(child))
        return refs

    for relative in _collect_import_refs(slides):
        destination = tmpdir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(
            storage.download_file_from_pptx_bucket(f"decks/{deck_id}/{relative}")
        )

    # Download includes
    for key in storage.list_files(prefix=f"decks/{deck_id}/includes/", bucket=storage.pptx_bucket):
        rel = key.replace(f"decks/{deck_id}/", "")
        dest = tmpdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(storage.download_file_from_pptx_bucket(key))

    # Download images
    for key in storage.list_files(prefix=f"decks/{deck_id}/images/", bucket=storage.pptx_bucket):
        rel = key.replace(f"decks/{deck_id}/", "")
        dest = tmpdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(storage.download_file_from_pptx_bucket(key))

    # Download asset manifests + referenced icons
    assets_dir = tmpdir / "assets"
    asset_keys = storage.list_files(prefix="assets/")
    for key in [k for k in asset_keys if k.endswith("manifest.json")]:
        dest = tmpdir / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(storage.download_file(key=key))
    slide_text = json.dumps(slides)
    refs = set(re.findall(r'(?:assets:|icons:)([^"]+)', slide_text))
    for source_dir in assets_dir.iterdir() if assets_dir.exists() else []:
        manifest_path = source_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text())
        entries = manifest if isinstance(manifest, list) else manifest.get("icons", manifest.get("assets", []))
        for entry in entries:
            entry_name = entry.get("name", "")
            entry_file = entry.get("file", "")
            for ref in refs:
                name = ref.split("/", 1)[-1] if "/" in ref else ref
                if name.lower() in entry_name.lower() or name in entry_file:
                    s3_key = f"assets/{source_dir.name}/{entry_file}"
                    if s3_key in asset_keys:
                        dest = tmpdir / s3_key
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(storage.download_file(key=s3_key))

    # Point engine's ASSETS_DIR to tmpdir/assets
    import sdpm.knowledge.assets as _assets_mod
    _assets_mod.ASSETS_DIR = assets_dir
    _assets_mod.ICON_DIR = assets_dir
    _assets_mod.ICON_LOCAL_DIR = assets_dir
    _assets_mod._manifest_cache = None

    # Resolve template
    template_key = ""
    template_path = tmpdir / "template.pptx"
    tmpl_name = presentation.get("template", "")
    # New imports reference the immutable bundle template directly.
    if isinstance(tmpl_name, str) and tmpl_name.startswith("attachments/imports/"):
        if ".." in PurePosixPath(tmpl_name).parts or not tmpl_name.endswith("/deck/template.pptx"):
            raise ValueError(f"Invalid imported template path: {tmpl_name}")
        template_path.write_bytes(
            storage.download_file_from_pptx_bucket(f"decks/{deck_id}/{tmpl_name}")
        )
        tmpl_name = ""
    # Existing decks may still use their historical deck-root template.
    elif tmpl_name == "template.pptx":
        deck_template_key = f"decks/{deck_id}/template.pptx"
        try:
            template_path.write_bytes(
                storage.download_file_from_pptx_bucket(deck_template_key),
            )
        except Exception as e:
            # Do NOT fall back to a stock template: imported decks reference
            # layout names from the original PPTX, so building with a stock
            # template would fail later with an obscure layout mismatch.
            raise ValueError(
                f"Deck template not found: {deck_template_key}. "
                "This deck was imported from a PPTX and requires its own "
                "template.pptx. Re-import the PPTX to restore it."
            ) from e
        tmpl_name = ""  # signal: resolved
    if tmpl_name:
        normalized = tmpl_name.removesuffix(".pptx")
        # User templates take precedence (same order as analyze_template).
        if storage.get_user_template_metadata(user_id, normalized):
            template_path.write_bytes(
                storage.download_user_template(user_id, normalized)
            )
        else:
            for t in storage.list_templates():
                if t.get("name") == normalized:
                    template_key = t.get("s3Key", "")
                    break
            if not template_key:
                # Do NOT silently fall back to a stock template: the deck
                # explicitly references a template, so building with a
                # different one would silently produce the wrong design.
                available = [t.get("name", "") for t in storage.list_templates()]
                available += [
                    t.get("name", "") for t in storage.list_user_templates(user_id)
                ]
                raise ValueError(
                    f"Template '{tmpl_name}' not found. "
                    f"Available: {', '.join(available)}"
                )
    if not template_path.exists():
        if not template_key:
            template_key = "templates/blank-dark.pptx"
        template_path.write_bytes(storage.download_file(key=template_key))

    # Fonts
    fonts = presentation.get("fonts") or deck.get("fonts")
    if not fonts or not fonts.get("fullwidth"):
        fonts = extract_fonts(template_path)

    return tmpdir, slides, {
        "template_path": template_path,
        "custom_template": True,
        "fonts": fonts,
        "base_dir": tmpdir,
        "default_text_color": presentation.get("defaultTextColor"),
    }


def generate_pptx(
    deck_id: str,
    user_id: str,
    storage: Storage,
    kb_sync: object | None = None,
) -> dict:
    """Generate a PowerPoint file from the deck's S3 workspace.

    Materializes the S3 workspace (deck.json, specs/, slides/, includes/,
    images/, referenced assets, template) into a tmpdir, then delegates the
    build to the engine facade ``sdpm.api.generate`` — the same code path as
    the local server. Remote-only orchestration (S3 upload, deck record
    update, WebP previews, KB sync) happens around it.

    Args:
        deck_id: Deck identifier.
        user_id: Owner's user ID.
        storage: Storage backend instance.
        kb_sync: Optional KBSync instance for vector synchronization.

    Returns:
        Dict with status, slideCount, slides summary, and optional warnings.

    Raises:
        ValueError: If deck not found or has no slides.
    """
    from sdpm.api import generate as api_generate

    tmpdir, slides, build_kwargs = _prepare_workspace(deck_id, user_id, storage)
    try:
        # Rewrite deck.json so api.generate resolves exactly what the
        # workspace materialized (template file, fonts, text color).
        deck_meta = json.loads((tmpdir / "deck.json").read_text(encoding="utf-8"))
        deck_meta["template"] = str(Path(build_kwargs["template_path"]).name)
        deck_meta["fonts"] = build_kwargs["fonts"]
        if build_kwargs.get("default_text_color"):
            deck_meta["defaultTextColor"] = build_kwargs["default_text_color"]
        (tmpdir / "deck.json").write_text(
            json.dumps(deck_meta, ensure_ascii=False), encoding="utf-8"
        )

        out = tmpdir / "output.pptx"
        gen_result = api_generate(json_path=tmpdir, output_path=out)

        # Upload PPTX to S3
        pptx_key = f"pptx/{deck_id}/{uuid.uuid4()}.pptx"
        storage.upload_file(
            key=pptx_key, data=out.read_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )

        # Update deck record
        deck = storage.get_deck(deck_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        old = storage.update_deck(deck_id=deck_id, user_id=user_id, updates={
            "pptxS3Key": pptx_key, "updatedAt": now, "slideCount": len(slides),
        })
        # Delete the superseded artifact (best effort) — every refresh
        # uploads a new UUID key and only the newest is referenced.
        old_key = (old or {}).get("pptxS3Key")
        if old_key and old_key != pptx_key:
            try:
                storage._s3.delete_object(Bucket=storage.pptx_bucket, Key=old_key)
            except Exception:
                pass

        # Preview: epoch-keyed WebP (background)
        slugs = [s.get("id") or f"slide_{i + 1:02d}" for i, s in enumerate(slides)]
        from server_utils import schedule_webp_background
        schedule_webp_background(deck_id, out, tmpdir, storage, slugs, user_id=user_id)
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise

    # KB sync
    kb_error: str | None = None
    if kb_sync:
        try:
            kb_sync.sync_deck(
                deck_id=deck_id,
                user_id=user_id,
                deck_name=(deck or {}).get("name", ""),
                visibility=(deck or {}).get("visibility", "private"),
                slides=slides,
            )
        except Exception as e:
            kb_error = str(e)

    result: dict = {
        "status": "completed",
        "slideCount": gen_result["slide_count"],
        "slides": gen_result["slides"],
    }
    # Structured usage event: source for per-user slide-build measurement
    # (Logs Insights: filter kind = "slides_built" | stats sum(slide_count) by user_id)
    logger.info(json.dumps({
        "kind": "slides_built",
        "user_id": user_id,
        "deck_id": deck_id,
        "slide_count": gen_result["slide_count"],
    }))
    warnings: dict = {}
    if kb_error:
        warnings["kbSyncFailed"] = kb_error
    if gen_result.get("invalid_layouts"):
        warnings["invalidLayouts"] = gen_result["invalid_layouts"]
    if gen_result.get("warnings"):
        warnings["build"] = gen_result["warnings"]
    if warnings:
        result["warnings"] = warnings
    return result
