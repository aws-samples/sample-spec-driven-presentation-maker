# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for shared/ingest._convert_pdf image extraction.

Regression for the shared-resource-dict pathology: some producers (e.g.
LibreOffice PDF export) put every image of the document into ONE resource
dict referenced by all pages. The old implementation paired pdfplumber
(placed images) with pypdf (resource-dict images) by zip order, so any
mismatch dumped ALL resource images onto every page — and decoded each
image once per page (pages x images decodes; minutes for real decks).

The converter must:
- extract only images actually drawn on each page (name-based matching)
- decode each unique image object once (document-level cache)
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

pytest.importorskip("pypdf", reason="PDF conversion deps not installed in this environment")
pytest.importorskip("pdfplumber", reason="PDF conversion deps not installed in this environment")

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.ingest import convert_file  # noqa: E402


def _jpeg_bytes(color: tuple[int, int, int]) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (4, 4), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _build_pdf(page_draws: list[list[str]], images: dict[str, bytes]) -> bytes:
    """Build a minimal PDF where ALL pages share one resource dict.

    Args:
        page_draws: per page, list of image names to draw (e.g. [["Im1"], ["Im2"]]).
        images: name -> JPEG bytes, all registered in the shared resource dict.

    Returns:
        PDF file bytes.
    """
    objects: list[bytes] = []  # 1-indexed object bodies (without "N 0 obj" wrapper)

    n_pages = len(page_draws)
    image_names = list(images)
    # Object layout:
    #   1 Catalog, 2 Pages, 3 shared Resources,
    #   4..3+len(images) image XObjects,
    #   then per page: page object + content stream object
    first_image_obj = 4
    first_page_obj = first_image_obj + len(image_names)

    image_obj_nums = {name: first_image_obj + i for i, name in enumerate(image_names)}
    page_obj_nums = [first_page_obj + 2 * i for i in range(n_pages)]
    content_obj_nums = [first_page_obj + 2 * i + 1 for i in range(n_pages)]

    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")  # 1
    objects.append(
        f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} "
        f"/MediaBox [0 0 612 792] >>".encode()
    )  # 2
    xobj_entries = " ".join(f"/{n} {image_obj_nums[n]} 0 R" for n in image_names)
    objects.append(f"<< /XObject << {xobj_entries} >> >>".encode())  # 3

    for name in image_names:
        data = images[name]
        head = (
            f"<< /Type /XObject /Subtype /Image /Width 4 /Height 4 "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
            f"/Length {len(data)} >>\nstream\n"
        ).encode()
        objects.append(head + data + b"\nendstream")

    for i, draws in enumerate(page_draws):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /Resources 3 0 R "
            f"/Contents {content_obj_nums[i]} 0 R >>".encode()
        )
        ops = "\n".join(f"q 100 0 0 100 {50 + 120 * j} 500 cm /{n} Do Q" for j, n in enumerate(draws))
        stream = ops.encode()
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = [0]  # object 0 (free)
    for num, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{num} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return out.getvalue()


@pytest.fixture
def red_jpeg() -> bytes:
    return _jpeg_bytes((255, 0, 0))


@pytest.fixture
def blue_jpeg() -> bytes:
    return _jpeg_bytes((0, 0, 255))


class TestSharedResourceDict:
    def test_only_drawn_images_extracted_per_page(
        self, tmp_path: Path, red_jpeg: bytes, blue_jpeg: bytes
    ) -> None:
        """Shared dict has 2 images; each page draws only one → each page's
        markdown references only its own image (no end-of-page dump)."""
        pdf = _build_pdf(
            page_draws=[["Im1"], ["Im2"]],
            images={"Im1": red_jpeg, "Im2": blue_jpeg},
        )
        src = tmp_path / "shared.pdf"
        src.write_bytes(pdf)
        out = tmp_path / "out"

        result = convert_file(src, out)

        assert result.status == "success", result.warnings
        assert len(result.images) == 2
        written = sorted(p.name for p in (out / "images").iterdir())
        assert written == sorted(result.images)

        md = (out / "shared.md").read_text(encoding="utf-8")
        page1, page2 = md.split("### Page 2")
        im1 = next(n for n in result.images if "Im1" in n)
        im2 = next(n for n in result.images if "Im2" in n)
        assert im1 in page1 and im2 not in page1
        assert im2 in page2 and im1 not in page2

    def test_image_reused_across_pages_written_once(
        self, tmp_path: Path, red_jpeg: bytes
    ) -> None:
        """Same image drawn on every page → decoded/written once, referenced
        from every page (document-level cache)."""
        pdf = _build_pdf(
            page_draws=[["Im1"], ["Im1"], ["Im1"]],
            images={"Im1": red_jpeg},
        )
        src = tmp_path / "reused.pdf"
        src.write_bytes(pdf)
        out = tmp_path / "out"

        result = convert_file(src, out)

        assert result.status == "success", result.warnings
        assert len(result.images) == 1
        assert len(list((out / "images").iterdir())) == 1
        md = (out / "reused.md").read_text(encoding="utf-8")
        assert md.count(f"]({result.images[0]})") == 3

    def test_unused_resource_images_not_extracted(
        self, tmp_path: Path, red_jpeg: bytes, blue_jpeg: bytes
    ) -> None:
        """Images present in the resource dict but never drawn are ignored."""
        pdf = _build_pdf(
            page_draws=[["Im1"]],
            images={"Im1": red_jpeg, "Im2": blue_jpeg},
        )
        src = tmp_path / "unused.pdf"
        src.write_bytes(pdf)
        out = tmp_path / "out"

        result = convert_file(src, out)

        assert result.status == "success", result.warnings
        assert len(result.images) == 1
        assert "Im1" in result.images[0]
