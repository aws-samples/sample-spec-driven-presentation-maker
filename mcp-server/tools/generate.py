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
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from storage import Storage


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

    # Get deck metadata from DDB
    deck = storage.get_deck(deck_id, user_id)
    if not deck:
        raise ValueError(f"Deck {deck_id} not found.")

    # Read presentation.json from S3
    presentation = storage.get_presentation_json(deck_id)
    if not isinstance(presentation, dict):
        raise ValueError(f"Deck {deck_id} has invalid presentation.json (expected object).")
    slides = presentation.get("slides", [])
    if not isinstance(slides, list):
        raise ValueError(f"Deck {deck_id} has invalid slides (expected array).")
    if not slides:
        raise ValueError(f"Deck {deck_id} has no slides.")

    # Set up tmpdir with presentation.json + includes
    tmpdir = Path(tempfile.mkdtemp())
    (tmpdir / "presentation.json").write_text(
        json.dumps(presentation, ensure_ascii=False), encoding="utf-8"
    )

    # Download includes
    include_keys = storage.list_files(
        prefix=f"decks/{deck_id}/includes/", bucket=storage.pptx_bucket
    )
    for key in include_keys:
        rel = key.replace(f"decks/{deck_id}/", "")
        dest = tmpdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(storage.download_file_from_pptx_bucket(key))

    # Download images extracted by pptx_to_json
    image_keys = storage.list_files(
        prefix=f"decks/{deck_id}/images/", bucket=storage.pptx_bucket
    )
    for key in image_keys:
        rel = key.replace(f"decks/{deck_id}/", "")
        dest = tmpdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(storage.download_file_from_pptx_bucket(key))

    # Download asset manifests + referenced icons from S3
    assets_dir = tmpdir / "assets"
    asset_keys = storage.list_files(prefix="assets/")
    # Always download manifests
    for key in [k for k in asset_keys if k.endswith("manifest.json")]:
        dest = tmpdir / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(storage.download_file(key=key))
    # Collect referenced asset files from slides
    slide_text = json.dumps(slides)
    refs = set(re.findall(r'(?:assets:|icons:)([^"]+)', slide_text))
    # Load manifests to map name → file
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
    _assets_mod._manifest_cache = None  # Reset so engine reloads from new ASSETS_DIR

    # Resolve template S3 key from presentation.json or deck metadata
    template_key = ""
    tmpl_name = presentation.get("template", "")
    if tmpl_name:
        for t in storage.list_templates():
            if t.get("name") == tmpl_name or t.get("name") + ".pptx" == tmpl_name:
                template_key = t.get("s3Key", "")
                break
    if not template_key:
        template_key = deck.get("templateS3Key", "templates/default.pptx")
    template_data = storage.download_file(key=template_key)
    template_path = tmpdir / "template.pptx"
    template_path.write_bytes(template_data)

    # Get fonts
    fonts = presentation.get("fonts") or deck.get("fonts")
    if not fonts or not fonts.get("fullwidth"):
        from sdpm.analyzer import extract_fonts
        fonts = extract_fonts(template_path)

    # Build PPTX
    builder = PPTXBuilder(
        template_path, custom_template=True,
        fonts=fonts, base_dir=tmpdir,
        default_text_color=presentation.get("defaultTextColor"),
    )

    # Lint slide JSON
    from sdpm.schema.lint import lint as lint_slides
    lint_diagnostics = lint_slides(presentation)

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

    # Detect layout bias (centroid offset from content area center)
    from sdpm.preview import check_layout_imbalance_data
    layout_bias = check_layout_imbalance_data(out, slide_defs=slides)

    # Upload result
    key = f"pptx/{deck_id}/{uuid.uuid4()}.pptx"
    storage.upload_file(
        key=key, data=out.read_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )

    # Update deck record
    now = datetime.now(timezone.utc).isoformat()
    storage.update_deck(deck_id=deck_id, user_id=user_id, updates={
        "pptxS3Key": key, "updatedAt": now, "slideCount": len(slides),
    })

    # Delete old previews before triggering new PNG generation
    storage.delete_files(prefix=f"previews/{deck_id}/", bucket=storage.pptx_bucket)

    # Trigger PNG generation via SQS (no-op if PNG Worker not deployed)
    storage.send_png_job({
        "deckId": deck_id,
        "userId": user_id,
        "bucket": storage.pptx_bucket,
        "key": key,
    })

    # --- Parallel: PNG polling + KB sync ---
    import concurrent.futures

    def _run_kb_sync() -> str | None:
        """Run KB sync in background thread. Returns error string or None."""
        if not kb_sync:
            return None
        try:
            visibility = deck.get("visibility", "private")
            deck_name = deck.get("name", "")
            kb_sync.sync_deck(
                deck_id=deck_id,
                user_id=user_id,
                deck_name=deck_name,
                visibility=visibility,
                slides=slides,
            )
            return None
        except Exception as e:
            return str(e)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        kb_future = executor.submit(_run_kb_sync)

        # Poll for PNG completion (timeout if PNG Worker not deployed)
        expected = len(slides)
        for _ in range(30):  # 30 * 2s = 60s timeout
            png_keys = [
                k for k in storage.list_files(
                    prefix=f"previews/{deck_id}/", bucket=storage.pptx_bucket
                ) if k.endswith(".png")
            ]
            if len(png_keys) >= expected:
                break
            time.sleep(2)

        # Collect KB sync result
        kb_error = kb_future.result(timeout=60)

    # Read autofit report if available (written by PNG Worker)
    autofit_overflow: list[dict] = []
    try:
        report_data = storage.download_file_from_pptx_bucket(f"previews/{deck_id}/autofit_report.json")
        autofit_overflow = json.loads(report_data)
    except Exception:
        pass  # No report = no overflow or PNG Worker not deployed

    warnings: dict = {}
    if layout_bias:
        warnings["layoutBias"] = layout_bias
    if autofit_overflow:
        warnings["autofitOverflow"] = autofit_overflow
        warnings["autofitOverflowAdvice"] = (
            "Text may not fit — would need fontSize reduction to fit within shape bounds. "
            "fontSize reduction also changes text wrapping — exact cause of overflow varies. "
            "Check preview for: text overflowing shape bounds, unintended wrapping, overlap with nearby elements. "
            "If no visible problem, no action needed. "
            "If text overflows, adjust layout (width/height) or content (text length). "
            "fontSize has recommended minimums — prefer layout/content adjustments over reducing fontSize. "
            "Review surrounding layout together — don't fix in isolation."
        )
    if kb_error:
        warnings["kbSyncFailed"] = kb_error

    result: dict = {
        "status": "completed",
        "slideCount": len(slides),
        "slides": [
            f"page{i:02d} - {s.get('title', {}).get('text', s.get('title', '(no title)')) if isinstance(s.get('title'), dict) else s.get('title', '(no title)')}"
            for i, s in enumerate(slides, 1)
        ],
    }
    if warnings:
        result["warnings"] = warnings
    if lint_diagnostics:
        result["errors"] = {"lintDiagnostics": lint_diagnostics}
    return result
