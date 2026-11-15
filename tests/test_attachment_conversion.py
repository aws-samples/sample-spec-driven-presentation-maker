# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Attachment read / import for each document kind, and the URL path of the contracts.

Covers sdpm.tools.attachment.pipeline (text projections, image metadata, import
bundles and their error results), sdpm.tools.attachment.ingest (DOCX / XLSX / PDF →
Markdown) and sdpm.tools.attachment.contracts (URL fetch with the checksum-verified
304 cache, S3 sources, raw-source leases). Every document is built in tmp_path; the
network is replaced by a fake fetch_url.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from sdpm.tools.attachment import contracts, ingest, pipeline
from sdpm.tools.attachment.errors import ImportConversionFailed, SourceValidationError, SSRFBlocked
from sdpm.tools.attachment.fetcher import FetchResult


@pytest.fixture(autouse=True)
def _isolated_stage_cache(tmp_path_factory, monkeypatch):
    """LocalStageCache resolves under XDG_CACHE_HOME; keep it out of ~/.cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path_factory.mktemp("xdg-cache")))


# ─── Builders ────────────────────────────────────────────────────────────────


def _png_bytes(color=(20, 20, 20), size=(8, 8), fmt="PNG") -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def _docx(path: Path, *, picture: bool = False) -> Path:
    from docx import Document

    doc = Document()
    doc.add_heading("Quarterly Review", level=0)
    doc.add_heading("Goals", level=1)
    doc.add_paragraph("Ship the importer.")
    doc.add_paragraph("first", style="List Bullet")
    doc.add_paragraph("one", style="List Number")
    doc.add_paragraph("two", style="List Number")
    table = doc.add_table(rows=2, cols=2)
    for (r, c), text in {(0, 0): "Metric", (0, 1): "Value", (1, 0): "Users", (1, 1): "42"}.items():
        table.cell(r, c).text = text
    if picture:
        doc.add_picture(io.BytesIO(_png_bytes()))
    doc.save(str(path))
    return path


def _xlsx(path: Path, rows: list[list], *, picture_dir: Path | None = None) -> Path:
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    for row in rows:
        sheet.append(row)
    workbook.create_sheet("Empty")
    if picture_dir is not None:
        from openpyxl.drawing.image import Image as XLImage

        png = picture_dir / "chart.png"
        png.write_bytes(_png_bytes())
        sheet.add_image(XLImage(str(png)), "D1")
    workbook.save(str(path))
    return path


def _text_pdf(path: Path, lines: list[str]) -> Path:
    """A one-page PDF with real text (Helvetica), xref offsets computed."""
    content = "BT /F1 12 Tf 72 720 Td " + " ".join(f"({line}) Tj 0 -16 Td" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)
    return path


def _deck(tmp_path: Path) -> Path:
    deck = tmp_path / "deck"
    deck.mkdir()
    return deck


# ─── read_attachment_core ────────────────────────────────────────────────────


class TestReadCore:
    def test_docx_projection(self, tmp_path):
        result = pipeline.read_attachment_core(_docx(tmp_path / "review.docx"), "review.docx")
        assert result["header"]["kind"] == "document"
        body = result["body"]
        assert "# Goals" in body
        assert "Ship the importer." in body
        assert "| Users | 42 |" in body

    def test_xlsx_projection(self, tmp_path):
        source = _xlsx(tmp_path / "data.xlsx", [["Name", "Score"], ["Ada", 9], [None, None]])
        body = pipeline.read_attachment_core(source, "data.xlsx")["body"]
        assert "## Sheet: Data" in body
        assert "| Ada | 9 |" in body
        assert "## Sheet: Empty" in body

    def test_pdf_projection(self, tmp_path):
        source = _text_pdf(tmp_path / "memo.pdf", ["Hello PDF", "Second line"])
        body = pipeline.read_attachment_core(source, "memo.pdf")["body"]
        assert "--- Page 1 ---" in body
        assert "Hello PDF" in body

    def test_pdf_projection_truncates_at_the_page_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pipeline, "MAX_PDF_PAGES", 0)
        body = pipeline._pdf_text_projection(_text_pdf(tmp_path / "memo.pdf", ["x"])).decode()
        assert body.startswith("[PDF truncated: showing first 0 of 1 pages]")

    @pytest.mark.parametrize("projection", ["_pdf_text_projection", "_docx_text_projection", "_xlsx_text_projection"])
    def test_unreadable_documents_fail_conversion(self, tmp_path, projection):
        broken = tmp_path / "broken.bin"
        broken.write_bytes(b"not a document")
        with pytest.raises(ImportConversionFailed):
            getattr(pipeline, projection)(broken)

    @pytest.mark.filterwarnings("error::DeprecationWarning:sdpm")
    def test_raster_image_returns_colour_analysis(self, tmp_path):
        source = tmp_path / "dark.png"
        source.write_bytes(_png_bytes((10, 10, 10)))
        result = pipeline.read_attachment_core(source, str(source))
        assert result["kind"] == "image"
        assert result["mediaType"] == "image/png"
        assert result["colorAnalysis"]["brightness"] == "dark"
        assert result["colorAnalysis"]["saturation"] == "low"
        assert result["colorAnalysis"]["palette"][0]["hex"] == "#0A0A0A"

    @pytest.mark.filterwarnings("error::DeprecationWarning:sdpm")
    def test_colour_analysis_weights_each_colour_by_its_pixel_count(self, tmp_path):
        from PIL import Image

        # 3/4 pure red, 1/4 black.
        image = Image.new("RGB", (8, 8))
        image.paste((255, 0, 0), (0, 0, 8, 6))
        image.paste((0, 0, 0), (0, 6, 8, 8))
        source = tmp_path / "mixed.png"
        image.save(source)
        analysis = pipeline.read_attachment_core(source, str(source))["colorAnalysis"]
        # luminance = 0.75 * 54.2 = 40.7 → dark; saturation = 0.75 → high
        assert analysis["brightness"] == "dark"
        assert analysis["saturation"] == "high"
        assert [entry["hex"] for entry in analysis["palette"]] == ["#FF0000", "#000000"]
        assert [entry["ratio"] for entry in analysis["palette"]] == [0.75, 0.25]

    def test_svg_has_no_colour_analysis(self, tmp_path):
        source = tmp_path / "icon.svg"
        source.write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>')
        assert pipeline.read_attachment_core(source, str(source))["colorAnalysis"] is None

    def test_text_that_is_not_utf8_after_the_header_is_rejected(self, tmp_path):
        source = tmp_path / "log.txt"
        source.write_bytes(b"a" * 9000 + b"\xff\xfe")
        with pytest.raises(SourceValidationError, match="not valid UTF-8"):
            pipeline.read_attachment_core(source, str(source))

    def test_missing_file(self, tmp_path):
        with pytest.raises(SourceValidationError, match="not found"):
            pipeline.read_attachment_core(tmp_path / "gone.txt", "gone.txt")

    def test_paging_error_is_returned_not_raised(self, tmp_path):
        source = tmp_path / "x.txt"
        source.write_text("hello\n")
        result = pipeline.read_attachment_core(source, "x.txt", limit=1)
        assert result["error"]["code"] == "INVALID_LIMIT"

    def test_kind_without_projection_fails(self, tmp_path, monkeypatch):
        source = tmp_path / "x.txt"
        source.write_text("hello\n")
        monkeypatch.setattr(pipeline, "_get_text_projection", lambda *_args: None)
        with pytest.raises(ImportConversionFailed, match="Cannot create text projection"):
            pipeline.read_attachment_core(source, "x.txt")

    def test_projection_is_served_from_the_stage_cache(self, tmp_path, monkeypatch):
        from sdpm.tools.attachment.cache import LocalStageCache

        source = _docx(tmp_path / "review.docx")
        identity = {"kind": "file", "realpath": str(source), "mtimeNs": 1, "size": 1}
        cache = LocalStageCache(base_dir=tmp_path / "cache")
        first = pipeline.read_attachment_core(source, "review.docx", source_identity=identity, cache=cache)

        def _must_not_recompute(*_args):
            raise AssertionError("projection recomputed despite a cached stage")

        monkeypatch.setattr(pipeline, "_compute_text_projection", _must_not_recompute)
        second = pipeline.read_attachment_core(source, "review.docx", source_identity=identity, cache=cache)
        assert second["body"] == first["body"]

    def test_unknown_media_type_has_no_projection(self, tmp_path):
        assert pipeline._compute_text_projection(tmp_path / "x", "image/png") is None


# ─── import_attachment_core ──────────────────────────────────────────────────


class TestImportCore:
    def test_png_is_copied_into_extracted_images(self, tmp_path):
        source = tmp_path / "logo.png"
        source.write_bytes(_png_bytes())
        result = pipeline.import_attachment_core(source, str(source), _deck(tmp_path))
        assert result["reused"] is False
        (name, path), = result["imageMapping"].items()
        assert name.endswith("_logo.png") and path == f"extracted/images/{name}"
        assert (tmp_path / "deck" / result["bundlePath"] / path).is_file()

    def test_webp_is_converted_to_png(self, tmp_path):
        source = tmp_path / "photo.webp"
        source.write_bytes(_png_bytes(fmt="WEBP"))
        result = pipeline.import_attachment_core(source, str(source), _deck(tmp_path))
        (name,) = result["imageMapping"]
        assert name.endswith("_photo.png")
        from PIL import Image

        with Image.open(tmp_path / "deck" / result["bundlePath"] / "extracted" / "images" / name) as image:
            assert image.format == "PNG"

    def test_filename_gets_the_canonical_extension(self, tmp_path):
        source = tmp_path / "upload.bin"
        source.write_bytes(_png_bytes())
        result = pipeline.import_attachment_core(source, str(source), _deck(tmp_path), filename="chart")
        assert any(f["path"] == "source/chart.png" for f in result["files"])

    @pytest.mark.parametrize("name,build", [
        ("review.docx", lambda p: _docx(p, picture=True)),
        ("data.xlsx", lambda p: _xlsx(p, [["a", "b"], [1, 2]])),
        ("memo.pdf", lambda p: _text_pdf(p, ["Hello PDF"])),
    ])
    def test_documents_produce_markdown(self, tmp_path, name, build):
        source = build(tmp_path / name)
        result = pipeline.import_attachment_core(source, str(source), _deck(tmp_path))
        paths = {f["path"] for f in result["files"]}
        assert f"extracted/{Path(name).stem}.md" in paths, result
        assert f"source/{name}" in paths
        assert result["deckJson"] is None and result["templatePath"] is None

    def test_deadline_returns_import_incomplete_and_cleans_staging(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pipeline, "IMPORT_DEADLINE_S", 0)
        source = tmp_path / "x.txt"
        source.write_text("hello")
        deck = _deck(tmp_path)
        result = pipeline.import_attachment_core(source, str(source), deck)
        assert result["code"] == "IMPORT_INCOMPLETE"
        assert result["retryable"] is True
        assert result["completedStages"] == []
        staging = list((deck / "attachments").rglob("staging*"))
        assert all(not any(p.iterdir()) for p in staging if p.is_dir())

    def test_unreadable_document_is_a_conversion_failure(self, tmp_path):
        import zipfile

        source = tmp_path / "broken.docx"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<Types><Override ContentType="application/vnd.openxmlformats-officedocument'
                '.wordprocessingml.document.main+xml"/></Types>',
            )
        result = pipeline.import_attachment_core(source, str(source), _deck(tmp_path))
        assert result["code"] == "IMPORT_CONVERSION_FAILED"
        assert "Cannot open DOCX" in result["message"]

    def test_pdf_image_budget_is_enforced(self, tmp_path, monkeypatch):
        def _fake_convert(_path, output_dir):
            (output_dir / "images").mkdir(parents=True)
            (output_dir / "images" / "p1.png").write_bytes(b"x" * 10)
            return ingest.ConversionResult(status="success")

        monkeypatch.setattr(ingest, "convert_file", _fake_convert)
        monkeypatch.setattr(pipeline, "MAX_PDF_EXTRACTED_IMAGES_BYTES", 5)
        source = _text_pdf(tmp_path / "memo.pdf", ["x"])
        result = pipeline.import_attachment_core(source, str(source), _deck(tmp_path))
        assert result["code"] == "IMPORT_LIMIT_EXCEEDED"

    def test_unexpected_error_is_reported_as_conversion_failure(self, tmp_path, monkeypatch):
        def _boom(_staging):
            raise ValueError("disk on fire")

        monkeypatch.setattr(pipeline, "_build_image_mapping", _boom)
        source = tmp_path / "x.txt"
        source.write_text("hello")
        result = pipeline.import_attachment_core(source, str(source), _deck(tmp_path))
        assert result["code"] == "IMPORT_CONVERSION_FAILED"
        assert "disk on fire" in result["message"]

    def test_missing_file(self, tmp_path):
        with pytest.raises(SourceValidationError):
            pipeline.import_attachment_core(tmp_path / "gone.txt", "gone.txt", _deck(tmp_path))


# ─── ingest: DOCX / XLSX / Markdown helpers ──────────────────────────────────


class TestIngest:
    def test_docx_markdown_structure_and_images(self, tmp_path):
        result = ingest.convert_file(_docx(tmp_path / "review.docx", picture=True), tmp_path / "out")
        assert result.status == "success"
        md = result.markdown
        assert "# Quarterly Review" in md
        assert "# Goals" in md
        assert "- first" in md
        assert "1. one\n2. two" in md
        assert "| Metric | Value |\n| --- | --- |\n| Users | 42 |" in md
        assert len(result.images) == 1
        assert (tmp_path / "out" / "images" / result.images[0]).is_file()
        assert (tmp_path / "out" / "review.md").read_text() == md

    def test_empty_docx_is_an_error(self, tmp_path):
        from docx import Document

        Document().save(str(tmp_path / "empty.docx"))
        result = ingest.convert_file(tmp_path / "empty.docx", tmp_path / "out")
        assert result.status == "error"
        assert "No extractable content" in result.error

    def test_xlsx_markdown_and_images(self, tmp_path):
        source = _xlsx(tmp_path / "data.xlsx", [["Name", "Score"], ["Ada", 9], [None, 3]], picture_dir=tmp_path)
        result = ingest.convert_file(source, tmp_path / "out")
        assert result.status == "success"
        assert result.markdown == "## Data\n| Name | Score |\n| --- | --- |\n| Ada | 9 |\n|  | 3 |"
        assert result.images == ["image1.png"]

    def test_empty_xlsx_is_an_error(self, tmp_path):
        import openpyxl

        openpyxl.Workbook().save(str(tmp_path / "empty.xlsx"))
        result = ingest.convert_file(tmp_path / "empty.xlsx", tmp_path / "out")
        assert result.status == "error"

    @pytest.mark.parametrize("name", ["broken.docx", "broken.xlsx", "broken.pdf"])
    def test_unopenable_documents_are_errors(self, tmp_path, name):
        source = tmp_path / name
        source.write_bytes(b"not a document")
        result = ingest.convert_file(source, tmp_path / "out")
        assert result.status == "error"
        assert result.error

    def test_passthrough_and_unsupported_extensions(self, tmp_path):
        assert ingest.convert_file(tmp_path / "a.png", tmp_path / "out").status == "success"
        result = ingest.convert_file(tmp_path / "a.exe", tmp_path / "out")
        assert result.status == "error" and "Unsupported" in result.error

    def test_rows_to_md_table(self):
        assert ingest._rows_to_md_table([]) == ""
        assert ingest._rows_to_md_table([["a", "b"]]) == "| a | b |\n| --- | --- |"
        assert ingest._rows_to_md_table([["h"], ["x|y\nz"], [None]]) == "| h |\n| --- |\n| x\\|y z |\n|  |"

    @pytest.mark.parametrize("value,expected", [
        ("#000000", "#FFFFFF"),
        ("#1E90FF", "#E16F00"),
        ("abcdef", "#543210"),
        ("#zz", "#FFFFFF"),
        ("#12", "#FFFFFF"),
    ])
    def test_invert_hex(self, value, expected):
        assert ingest._invert_hex(value) == expected


class TestMarkdownTableCells:
    """A cell's own '|' and line breaks must survive as one cell (GFM: '\\|', newline → space),
    the way _rows_to_md_table already writes PDF tables."""

    def test_docx_pipe_in_a_cell_is_escaped_once(self, tmp_path):
        from docx import Document

        doc = Document()
        table = doc.add_table(rows=2, cols=2)
        for (r, c), text in {(0, 0): "k", (0, 1): "v", (1, 0): "a|b", (1, 1): "x"}.items():
            table.cell(r, c).text = text
        doc.save(str(tmp_path / "t.docx"))
        md = ingest.convert_file(tmp_path / "t.docx", tmp_path / "out").markdown
        assert "| a\\|b | x |" in md

    def test_xlsx_pipe_and_newline_in_a_cell_stay_in_the_cell(self, tmp_path):
        source = _xlsx(tmp_path / "t.xlsx", [["k", "v"], ["a|b", "line1\nline2"]])
        md = ingest.convert_file(source, tmp_path / "out").markdown
        assert "| a\\|b | line1 line2 |" in md


# ─── contracts: URL path, S3 path, raw leases ────────────────────────────────


class _FakeFetch:
    """Stands in for fetcher.fetch_url: first a 200 with an ETag, then whatever is queued."""

    def __init__(self, *results: FetchResult | Exception):
        self.results = list(results)
        self.calls: list[dict] = []

    def __call__(self, url, *, etag=None, last_modified=None):
        self.calls.append({"url": url, "etag": etag, "last_modified": last_modified})
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


_URL = "https://example.invalid/notes.txt"


def _ok(data=b"hello from the web\n", **kwargs) -> FetchResult:
    defaults = dict(final_url=_URL, content_type="text/plain", etag='"v1"', last_modified="Mon, 01 Jan 2024 00:00:00 GMT")
    defaults.update(kwargs)
    return FetchResult(data=data, **defaults)


def _not_modified() -> FetchResult:
    return FetchResult(data=b"", final_url=_URL, not_modified=True)


@pytest.fixture()
def fake_fetch(monkeypatch):
    from sdpm.tools.attachment import fetcher

    def install(*results):
        fake = _FakeFetch(*results)
        monkeypatch.setattr(fetcher, "fetch_url", fake)
        return fake

    return install


class TestUrlSources:
    def test_read_then_revalidate_from_the_cache(self, fake_fetch):
        fake = fake_fetch(_ok(), _not_modified())
        first = contracts.read_attachment(_URL)
        second = contracts.read_attachment(_URL)
        assert "hello from the web" in first["body"]
        assert second["body"] == first["body"]
        assert fake.calls[0]["etag"] is None
        assert fake.calls[1]["etag"] == '"v1"'
        assert fake.calls[1]["last_modified"] == "Mon, 01 Jan 2024 00:00:00 GMT"

    def test_tampered_cached_body_is_refused(self, fake_fetch, tmp_path):
        import os

        fake_fetch(_ok(), _not_modified())
        contracts.read_attachment(_URL)
        bodies = Path(os.environ["XDG_CACHE_HOME"]).rglob("url-cache/bodies/*")
        (body,) = [p for p in bodies if p.is_file()]
        body.chmod(0o600)
        body.write_bytes(b"swapped content!!!\n")
        result = contracts.read_attachment(_URL)
        assert result["error"]["code"] == "FETCH_ERROR"
        assert "checksum" in result["error"]["message"]

    def test_not_modified_without_an_index_is_an_error(self, fake_fetch, tmp_path):
        import json
        import os

        fake_fetch(_ok(), _not_modified())
        contracts.read_attachment(_URL)
        (index,) = Path(os.environ["XDG_CACHE_HOME"]).rglob("url-cache/indexes/*.json")
        index.write_text(json.dumps(["not", "an", "index"]))
        result = contracts.read_attachment(_URL)
        assert result["error"]["code"] == "FETCH_ERROR"
        assert "without a cache index" in result["error"]["message"]

    def test_fetch_error_code_is_propagated(self, fake_fetch, tmp_path):
        fake_fetch(SSRFBlocked("private address"), SSRFBlocked("private address"))
        assert contracts.read_attachment(_URL)["error"]["code"] == "SSRF_BLOCKED"
        assert contracts.import_attachment(_URL, str(_deck(tmp_path)))["error"]["code"] == "SSRF_BLOCKED"

    @pytest.mark.parametrize("fetched,filename,expected", [
        (_ok(filename_from_header="report.txt"), "", "source/report.txt"),
        (_ok(final_url="https://example.invalid/dl/final-notes.txt"), "", "source/final-notes.txt"),
        (_ok(final_url="https://example.invalid/"), "", "source/attachment.txt"),
        (_ok(filename_from_header="ignored.txt"), "mine.txt", "source/mine.txt"),
    ])
    def test_import_names_the_source(self, fake_fetch, tmp_path, fetched, filename, expected):
        fake_fetch(fetched)
        result = contracts.import_attachment(_URL, str(_deck(tmp_path)), filename=filename)
        assert expected in {f["path"] for f in result["files"]}, result

    def test_ext_from_url(self):
        assert contracts._ext_from_url("https://x.invalid/a/b.pdf?x=1#y") == ".pdf"
        assert contracts._ext_from_url("https://x.invalid/a/") == ""


class TestOtherSources:
    def test_s3_keys_need_the_remote_adapter(self, tmp_path):
        key = "uploads/12345678-1234-4234-8234-123456789abc/file.pdf"
        assert contracts.read_attachment(key)["error"]["code"] == "ADAPTER_REQUIRED"
        assert contracts.import_attachment(key, str(_deck(tmp_path)))["error"]["code"] == "ADAPTER_REQUIRED"

    def test_local_image_reports_the_original_path(self, tmp_path):
        source = tmp_path / "logo.png"
        source.write_bytes(_png_bytes())
        result = contracts.read_attachment(str(source))
        assert result["kind"] == "image"
        assert result["path"] == str(source)

    def test_raw_source_under_attachments_gets_a_lease(self, tmp_path):
        session = tmp_path / ".attachments" / "session-1"
        session.mkdir(parents=True)
        source = session / "notes.txt"
        source.write_text("hello")
        assert "hello" in contracts.read_attachment(str(source))["body"]
        lease = session / ".lease"
        assert lease.is_file()
        assert lease.stat().st_mode & 0o777 == 0o600

    def test_other_paths_get_no_lease(self, tmp_path):
        source = tmp_path / "notes.txt"
        source.write_text("hello")
        contracts.read_attachment(str(source))
        assert not (tmp_path / ".lease").exists()

    def test_local_validation_errors_are_returned(self, tmp_path):
        result = contracts.import_attachment(str(tmp_path / "missing.txt"), str(_deck(tmp_path)))
        assert result["error"]["code"] == "SOURCE_VALIDATION_ERROR"
