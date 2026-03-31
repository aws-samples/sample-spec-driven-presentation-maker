# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""PNG generation handler — converts PPTX to per-page PNGs via LibreOffice.

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

Downloads PPTX from S3, converts via LibreOffice headless → PDF → PNG,
uploads PNGs to S3, and reads slide IDs from presentation.json.
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote_plus

import boto3

logger = logging.getLogger("png-worker.handler")

AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")


def handle_png(payload: dict) -> None:
    """Generate PNG previews from a PPTX file in S3.

    Args:
        payload: Dict with keys:
            - bucket (str): S3 bucket name.
            - key (str): S3 key of the PPTX file.
            - deckId (str): Deck identifier.

    Raises:
        FileNotFoundError: If LibreOffice produces no output.
        subprocess.CalledProcessError: If conversion fails.
    """
    bucket: str = payload["bucket"]
    key: str = unquote_plus(payload["key"])
    deck_id: str = payload["deckId"]

    if not bucket or not key or not deck_id:
        raise ValueError("payload must contain non-empty bucket, key, and deckId")

    s3_client = boto3.client("s3", region_name=AWS_REGION)
    work_dir = Path(tempfile.mkdtemp())
    pptx_path = work_dir / "deck.pptx"

    # Download PPTX
    s3_client.download_file(bucket, key, str(pptx_path))
    logger.info("Downloaded %s (%d bytes)", key, pptx_path.stat().st_size)

    # PPTX → LibreOffice re-save (computes autofit scaling values)
    env = os.environ.copy()
    env["HOME"] = str(work_dir)
    lo_out = work_dir / "lo_resave"
    lo_out.mkdir()
    subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        ["soffice", "--headless", "--convert-to", "pptx", "--outdir", str(lo_out), str(pptx_path)],
        env=env, capture_output=True, text=True, timeout=120, check=True,
    )
    resaved = lo_out / "deck.pptx"
    autofit_report: list[dict] = []
    if resaved.exists():
        # Extract scaling values from LibreOffice re-saved copy
        from handlers.autofit import extract_scaling, unlock_autofit
        scaling = extract_scaling(resaved)
        # Replace normAutofit with noAutofit in the ORIGINAL PPTX (no font size bake)
        changed = unlock_autofit(original_path=pptx_path, scaling=scaling)
        if changed:
            # Upload unlocked original to S3
            s3_client.upload_file(str(pptx_path), bucket, key, ExtraArgs={"ContentType": "application/vnd.openxmlformats-officedocument.presentationml.presentation"})
            logger.info("Autofit-unlocked PPTX uploaded to s3://%s/%s", bucket, key)
        # Build report for agent consumption
        for (si, shi), (fs, lsr) in scaling.items():
            autofit_report.append({"slide": si, "shape": shi, "fontScale": round(fs, 3), "lnSpcReduction": round(lsr, 3)})
    else:
        logger.warning("LibreOffice re-save did not produce output, skipping autofit unlock")

    # Save autofit report to S3 (agent reads this after polling)
    if autofit_report:
        report_key = f"previews/{deck_id}/autofit_report.json"
        s3_client.put_object(
            Bucket=bucket, Key=report_key,
            Body=json.dumps(autofit_report).encode("utf-8"),
            ContentType="application/json",
        )

    # PPTX → PDF via LibreOffice
    subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(work_dir), str(pptx_path)],
        env=env, capture_output=True, text=True, timeout=120, check=True,
    )

    pdf_path = work_dir / "deck.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError("LibreOffice did not produce deck.pdf")

    # PDF → per-page PNGs
    subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        ["pdftoppm", "-png", "-r", "200", str(pdf_path), str(work_dir / "slide")],
        capture_output=True, text=True, timeout=120, check=True,
    )

    png_files = sorted(work_dir.glob("slide-*.png"))
    if not png_files:
        raise FileNotFoundError(f"No PNGs generated in {work_dir}")

    # Upload PNGs with sequential naming (slide_01, slide_02, ...)
    for i, png_path in enumerate(png_files):
        s3_key = f"previews/{deck_id}/slide_{i + 1:02d}.png"

        s3_client.upload_file(str(png_path), bucket, s3_key, ExtraArgs={"ContentType": "image/png"})
        logger.info("PNG uploaded: s3://%s/%s", bucket, s3_key)

    logger.info("PNG generation complete: %d pages for deck %s", len(png_files), deck_id)
