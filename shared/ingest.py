# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Upload file conversion pipeline (Cloud/Local shared).

Converts uploaded binary files to agent-readable formats at upload time.
Pure function: takes file path + output dir, writes converted files, returns result.
No I/O dependencies (S3, DynamoDB) — callers handle storage.

Conversion matrix:
    Image/Text  → no conversion (copy as-is by caller)
    PDF         → pdfplumber (text+table+image position) + pypdf (image binary)
    DOCX        → MarkItDown (text+image placeholder) + zipfile (image binary)
    XLSX        → MarkItDown (table structure) + zipfile (image binary)
    PPTX        → pptx_to_json Engine
"""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# PDF page limit — pages beyond this are skipped with a warning.
_PDF_MAX_PAGES = 100

# File types that need no conversion (caller copies as-is).
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
_TEXT_EXTS = {".csv", ".json", ".txt", ".md", ".html"}
_PASSTHROUGH_EXTS = _IMAGE_EXTS | _TEXT_EXTS


@dataclass
class ConversionResult:
    """Result of a file conversion."""

    status: Literal["success", "partial", "error"]
    markdown: str | None = None
    json_data: str | None = None
    images: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def convert_file(file_path: Path, output_dir: Path) -> ConversionResult:
    """Convert a file and write results to output_dir.

    - output_dir/{name}.md or output_dir/slides.json
    - output_dir/images/ for extracted images
    - Caller decides what output_dir maps to (S3 prefix, local path, etc.)
    """
    ext = file_path.suffix.lower()

    if ext in _PASSTHROUGH_EXTS:
        return ConversionResult(status="success")

    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"

    if ext == ".pdf":
        return _convert_pdf(file_path, output_dir, images_dir)
    if ext == ".docx":
        return _convert_docx(file_path, output_dir, images_dir)
    if ext == ".xlsx":
        return _convert_xlsx(file_path, output_dir, images_dir)
    if ext == ".pptx":
        return _convert_pptx(file_path, output_dir)

    return ConversionResult(status="error", error=f"Unsupported file type: {ext}")


# ---------------------------------------------------------------------------
# PDF: pdfplumber (text + tables + image positions) + pypdf (image binaries)
# ---------------------------------------------------------------------------


def _convert_pdf(file_path: Path, output_dir: Path, images_dir: Path) -> ConversionResult:
    """Convert PDF with text/table/image interleaving by Y coordinate."""
    try:
        import pdfplumber
        from pypdf import PdfReader
    except ImportError as e:
        return ConversionResult(status="error", error=f"Missing dependency: {e}")

    warnings: list[str] = []
    images: list[str] = []
    md_parts: list[str] = []

    try:
        reader = PdfReader(str(file_path))
    except Exception as e:
        return ConversionResult(status="error", error=f"Cannot open PDF: {e}")

    total_pages = len(reader.pages)
    process_pages = min(total_pages, _PDF_MAX_PAGES)
    if total_pages > _PDF_MAX_PAGES:
        warnings.append(f"PDF has {total_pages} pages; only first {_PDF_MAX_PAGES} processed.")

    try:
        pdf = pdfplumber.open(str(file_path))
    except Exception as e:
        return ConversionResult(status="error", error=f"pdfplumber cannot open PDF: {e}")

    for page_idx in range(process_pages):
        page_num = page_idx + 1
        pb_page = pdf.pages[page_idx]
        pypdf_page = reader.pages[page_idx]

        # Collect content fragments with Y positions for interleaving
        fragments: list[tuple[float, str]] = []

        # --- Text lines ---
        try:
            lines = pb_page.extract_text_lines() or []
            for line in lines:
                fragments.append((line["top"], line["text"]))
        except Exception:
            pass

        # --- Tables ---
        try:
            tables = pb_page.find_tables() or []
            # Track table bounding boxes to exclude overlapping text
            table_bboxes = []
            for tbl in tables:
                bbox = tbl.bbox  # (x0, top, x1, bottom)
                table_bboxes.append(bbox)
                rows = tbl.extract() or []
                if rows:
                    md_table = _rows_to_md_table(rows)
                    fragments.append((bbox[1], md_table))

            # Remove text lines that fall inside table bounding boxes
            if table_bboxes:
                fragments = [
                    (y, text) for y, text in fragments
                    if not any(
                        bbox[1] <= y <= bbox[3] and not text.startswith("|")
                        for bbox in table_bboxes
                    )
                ]
        except Exception:
            pass

        # --- Image positions (pdfplumber) + binaries (pypdf) ---
        try:
            pb_images = pb_page.images or []
            pypdf_images = pypdf_page.images or []

            if len(pb_images) != len(pypdf_images):
                warnings.append(
                    f"Page {page_num}: image count mismatch "
                    f"(position={len(pb_images)}, binary={len(pypdf_images)}). "
                    "Images listed at end of page."
                )
                # Fallback: save binaries without position interleaving
                images_dir.mkdir(parents=True, exist_ok=True)
                for img_idx, img in enumerate(pypdf_images):
                    ext = img.name.rsplit(".", 1)[-1] if "." in img.name else "png"
                    img_name = f"pdf_p{page_num}_img{img_idx + 1}.{ext}"
                    (images_dir / img_name).write_bytes(img.data)
                    images.append(img_name)
                    fragments.append((float("inf"), f"![{img_name}]({img_name})"))
            else:
                images_dir.mkdir(parents=True, exist_ok=True)
                for img_idx, (pb_img, pypdf_img) in enumerate(zip(pb_images, pypdf_images)):
                    ext = pypdf_img.name.rsplit(".", 1)[-1] if "." in pypdf_img.name else "png"
                    img_name = f"pdf_p{page_num}_img{img_idx + 1}.{ext}"
                    (images_dir / img_name).write_bytes(pypdf_img.data)
                    images.append(img_name)
                    y_pos = pb_img["top"]
                    fragments.append((y_pos, f"![{img_name}]({img_name})"))
        except Exception as e:
            warnings.append(f"Page {page_num}: image extraction failed: {e}")

        # Sort by Y position and build page markdown
        fragments.sort(key=lambda f: f[0])
        page_text = "\n\n".join(text for _, text in fragments)
        if page_text.strip():
            md_parts.append(f"### Page {page_num}\n\n{page_text}")

    pdf.close()

    markdown = "\n\n".join(md_parts)
    if not markdown.strip() and not images:
        return ConversionResult(
            status="error", error="No extractable content in PDF."
        )

    name = file_path.stem
    (output_dir / f"{name}.md").write_text(markdown, encoding="utf-8")

    status: Literal["success", "partial"] = "success"
    if not markdown.strip() and images:
        warnings.append("No text extracted (possibly a scanned PDF). Images were extracted.")
        status = "partial"
    elif warnings:
        status = "partial"

    return ConversionResult(
        status=status, markdown=markdown, images=images, warnings=warnings,
    )


def _rows_to_md_table(rows: list[list]) -> str:
    """Convert table rows to Markdown table string."""
    if not rows:
        return ""
    # Sanitize cells
    clean = []
    for row in rows:
        clean.append([(cell or "").replace("|", "\\|").replace("\n", " ") for cell in row])

    header = "| " + " | ".join(clean[0]) + " |"
    sep = "| " + " | ".join("---" for _ in clean[0]) + " |"
    body = "\n".join("| " + " | ".join(r) + " |" for r in clean[1:])
    return f"{header}\n{sep}\n{body}" if body else f"{header}\n{sep}"


# ---------------------------------------------------------------------------
# DOCX: MarkItDown (text + image placeholders) + zipfile (image binaries)
# ---------------------------------------------------------------------------


def _convert_docx(file_path: Path, output_dir: Path, images_dir: Path) -> ConversionResult:
    """Convert DOCX to Markdown with image extraction."""
    try:
        from markitdown import MarkItDown
    except ImportError as e:
        return ConversionResult(status="error", error=f"Missing dependency: {e}")

    warnings: list[str] = []
    images: list[str] = []

    # Text extraction via MarkItDown
    try:
        mid = MarkItDown()
        result = mid.convert(str(file_path))
        markdown = result.text_content or ""
    except Exception as e:
        return ConversionResult(status="error", error=f"DOCX text extraction failed: {e}")

    # Image extraction via zipfile
    try:
        with zipfile.ZipFile(str(file_path), "r") as zf:
            media_files = [n for n in zf.namelist() if n.startswith("word/media/")]
            if media_files:
                images_dir.mkdir(parents=True, exist_ok=True)
                for i, media_path in enumerate(media_files):
                    img_name = Path(media_path).name
                    data = zf.read(media_path)
                    (images_dir / img_name).write_bytes(data)
                    images.append(img_name)
    except Exception as e:
        warnings.append(f"Image extraction failed: {e}")

    # Replace base64 placeholders with filename references
    # MarkItDown outputs ![](data:image/png;base64,...)
    img_idx = 0

    def _replace_b64(match: re.Match) -> str:
        nonlocal img_idx
        if img_idx < len(images):
            name = images[img_idx]
            img_idx += 1
            return f"![{name}]({name})"
        return match.group(0)

    markdown = re.sub(r"!\[.*?\]\(data:image/[^)]+\)", _replace_b64, markdown)

    if not markdown.strip() and not images:
        return ConversionResult(status="error", error="No extractable content in DOCX.")

    name = file_path.stem
    (output_dir / f"{name}.md").write_text(markdown, encoding="utf-8")

    status: Literal["success", "partial"] = "partial" if warnings else "success"
    return ConversionResult(
        status=status, markdown=markdown, images=images, warnings=warnings,
    )


# ---------------------------------------------------------------------------
# XLSX: MarkItDown (table structure) + zipfile (image binaries)
# ---------------------------------------------------------------------------


def _convert_xlsx(file_path: Path, output_dir: Path, images_dir: Path) -> ConversionResult:
    """Convert XLSX to Markdown tables with image extraction."""
    try:
        from markitdown import MarkItDown
    except ImportError as e:
        return ConversionResult(status="error", error=f"Missing dependency: {e}")

    warnings: list[str] = []
    images: list[str] = []

    # Table extraction via MarkItDown
    try:
        mid = MarkItDown()
        result = mid.convert(str(file_path))
        markdown = result.text_content or ""
    except Exception as e:
        return ConversionResult(status="error", error=f"XLSX conversion failed: {e}")

    # Image extraction via zipfile
    try:
        with zipfile.ZipFile(str(file_path), "r") as zf:
            media_files = [n for n in zf.namelist() if n.startswith("xl/media/")]
            if media_files:
                images_dir.mkdir(parents=True, exist_ok=True)
                for media_path in media_files:
                    img_name = Path(media_path).name
                    data = zf.read(media_path)
                    (images_dir / img_name).write_bytes(data)
                    images.append(img_name)
    except Exception as e:
        warnings.append(f"Image extraction failed: {e}")

    if not markdown.strip() and not images:
        return ConversionResult(status="error", error="No extractable content in XLSX.")

    name = file_path.stem
    (output_dir / f"{name}.md").write_text(markdown, encoding="utf-8")

    status: Literal["success", "partial"] = "partial" if warnings else "success"
    return ConversionResult(
        status=status, markdown=markdown, images=images, warnings=warnings,
    )


# ---------------------------------------------------------------------------
# PPTX: pptx_to_json Engine
# ---------------------------------------------------------------------------


def _convert_pptx(file_path: Path, output_dir: Path) -> ConversionResult:
    """Convert PPTX to JSON via Engine's pptx_to_json."""
    import json

    try:
        from sdpm.converter import pptx_to_json
    except ImportError as e:
        return ConversionResult(status="error", error=f"Missing dependency: {e}")

    try:
        result = pptx_to_json(file_path, output_dir=output_dir)
        # pptx_to_json writes slides.json + images/ to output_dir
        json_str = json.dumps(result, ensure_ascii=False)

        # Collect extracted images
        images: list[str] = []
        img_dir = output_dir / "images"
        if img_dir.exists():
            images = [f.name for f in img_dir.iterdir() if f.is_file()]

        return ConversionResult(
            status="success", json_data=json_str, images=images,
        )
    except Exception as e:
        return ConversionResult(status="error", error=f"PPTX conversion failed: {e}")
