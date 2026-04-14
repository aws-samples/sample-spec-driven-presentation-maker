# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""PPTX generation — builds PowerPoint from S3 presentation.json.

Slide content may originate from LLM-generated text. Review output before distribution.
Generated PPTX files are uploaded to S3 with server-side encryption.
Presigned URLs are used for time-limited access to output files.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

Reads presentation.json + includes from S3, resolves include references,
and builds PPTX via sdpm.builder.
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
from pathlib import Path

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


def _parse_outline_slugs(outline_path: Path) -> list[str]:
    """Parse outline.md and return ordered list of slugs.

    Format: ``- [slug] Message text``
    """
    import re as _re

    pattern = _re.compile(r"^-\s*\[([a-z0-9-]+)\]\s*")
    slugs: list[str] = []
    if not outline_path.exists():
        return slugs
    for line in outline_path.read_text(encoding="utf-8").splitlines():
        m = pattern.match(line)
        if m:
            slugs.append(m.group(1))
    return slugs


def _assemble_slides(tmpdir: Path) -> list[dict]:
    """Assemble slide list from workspace directory.

    New format (deck.json exists): reads outline.md for slug order,
    then loads slides/{slug}.json in order. Missing slides are skipped silently.

    Legacy format (presentation.json exists): reads slides directly.

    Args:
        tmpdir: Workspace directory.

    Returns:
        Ordered list of slide dicts.
    """
    deck_json_path = tmpdir / "deck.json"
    if deck_json_path.exists():
        slugs = _parse_outline_slugs(tmpdir / "specs" / "outline.md")
        slides: list[dict] = []
        for slug in slugs:
            slide_path = tmpdir / "slides" / f"{slug}.json"
            if not slide_path.exists():
                continue
            slide = json.loads(slide_path.read_text(encoding="utf-8"))
            slide.setdefault("id", slug)
            slides.append(slide)
        return slides

    pres_path = tmpdir / "presentation.json"
    if pres_path.exists():
        data = json.loads(pres_path.read_text(encoding="utf-8"))
        return data.get("slides", [])

    raise ValueError(f"No deck.json or presentation.json found in {tmpdir}")


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
    from sdpm.analyzer import extract_fonts
    from sdpm.builder import PPTXBuilder  # noqa: F401 — validate import

    deck = storage.get_deck(deck_id, user_id)
    if not deck:
        raise ValueError(f"Deck {deck_id} not found.")

    tmpdir = Path(tempfile.mkdtemp())

    # Detect format: try deck.json first, fall back to presentation.json
    has_deck_json = False
    try:
        deck_meta = storage.get_deck_json(deck_id)
        (tmpdir / "deck.json").write_text(
            json.dumps(deck_meta, ensure_ascii=False), encoding="utf-8"
        )
        has_deck_json = True
    except (ValueError, Exception):
        pass

    if has_deck_json:
        # Download outline.md
        outline_key = f"decks/{deck_id}/specs/outline.md"
        try:
            data = storage.download_file_from_pptx_bucket(outline_key)
            specs_dir = tmpdir / "specs"
            specs_dir.mkdir(parents=True, exist_ok=True)
            (specs_dir / "outline.md").write_bytes(data)
        except Exception:
            pass

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
    else:
        presentation = storage.get_presentation_json(deck_id)
        if not isinstance(presentation, dict):
            raise ValueError(f"Deck {deck_id} has invalid presentation.json.")
        (tmpdir / "presentation.json").write_text(
            json.dumps(presentation, ensure_ascii=False), encoding="utf-8"
        )

    # Assemble slides
    slides = _assemble_slides(tmpdir)
    if not slides:
        raise ValueError(f"Deck {deck_id} has no slides.")

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
    import sdpm.assets as _assets_mod
    _assets_mod.ASSETS_DIR = assets_dir
    _assets_mod.ICON_DIR = assets_dir
    _assets_mod.ICON_LOCAL_DIR = assets_dir
    _assets_mod._manifest_cache = None

    # Resolve template
    template_key = ""
    tmpl_name = presentation.get("template", "")
    if tmpl_name:
        for t in storage.list_templates():
            if t.get("name") == tmpl_name or t.get("name") + ".pptx" == tmpl_name:
                template_key = t.get("s3Key", "")
                break
    if not template_key:
        template_key = deck.get("templateS3Key", "templates/default.pptx")
    template_path = tmpdir / "template.pptx"
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
    """Generate a PowerPoint file from S3 presentation.json.

    Downloads presentation.json and all includes/ files to a tmpdir,
    then uses engine builder with base_dir set to tmpdir for include resolution.
    Template is resolved from presentation.json's "template" field.
    After PPTX build, generates WebP previews synchronously via LibreOffice.

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
    from sdpm.builder import PPTXBuilder, resolve_override

    tmpdir, slides, build_kwargs = _prepare_workspace(deck_id, user_id, storage)
    try:
        builder = PPTXBuilder(**build_kwargs)

        # Build id_map for resolve_override
        id_map: dict[str, dict] = {}
        for s in slides:
            if "id" in s:
                id_map[s["id"]] = s

        for s in slides:
            resolved = resolve_override(s, id_map)
            builder.add_slide(resolved)

        out = tmpdir / "output.pptx"
        builder.save(out)

        # Upload PPTX to S3
        pptx_key = f"pptx/{deck_id}/{uuid.uuid4()}.pptx"
        storage.upload_file(
            key=pptx_key, data=out.read_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )

        # Update deck record
        deck = storage.get_deck(deck_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        storage.update_deck(deck_id=deck_id, user_id=user_id, updates={
            "pptxS3Key": pptx_key, "updatedAt": now, "slideCount": len(slides),
        })

        # Preview: epoch-keyed WebP (background)
        from server_utils import schedule_webp_background
        schedule_webp_background(deck_id, out, tmpdir, storage)
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
        "slideCount": len(slides),
        "slides": [
            f"page{i:02d} - {s.get('title', {}).get('text', s.get('title', '(no title)')) if isinstance(s.get('title'), dict) else s.get('title', '(no title)')}"
            for i, s in enumerate(slides, 1)
        ],
    }
    if kb_error:
        result["warnings"] = {"kbSyncFailed": kb_error}
    return result
