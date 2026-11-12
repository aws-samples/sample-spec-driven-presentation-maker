# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Input validation of attachment sources (sdpm.tools.attachment.source).

Everything a user hands to read_attachment / import_attachment passes these checks
before any converter sees it: local materialization, media-type detection and
reconciliation with Content-Type, and the content limits (size, pixels, frames,
pages, OOXML archive safety, inert SVG). Limits are patched down to small values so
no test builds a large file.
"""

from __future__ import annotations

import io
import os
import stat
import warnings
import zipfile
from pathlib import Path

import pytest

from sdpm.tools.attachment import source
from sdpm.tools.attachment.errors import SourceLimitExceeded, SourceTypeMismatch, SourceValidationError
from sdpm.tools.attachment.source import (
    detect_media_type,
    detect_ooxml_from_path,
    enforce_content_limits,
    get_canonical_extension,
    materialize_local_source,
    sanitize_filename,
    source_identity_local,
    source_identity_s3,
    validate_local_source,
    validate_media_type,
)

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

_CONTENT_TYPES = {
    DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    PPTX: "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
}


def _ooxml_bytes(media_type: str, extra: dict[str, bytes] | None = None) -> bytes:
    """A minimal ZIP whose [Content_Types].xml names the given OOXML type."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            f'<Types><Override PartName="/x" ContentType="{_CONTENT_TYPES[media_type]}"/></Types>',
        )
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _image_bytes(fmt: str, size: tuple[int, int] = (4, 4), frames: int = 1) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    first = Image.new("RGB", size, (200, 30, 30))
    if frames > 1:
        rest = [Image.new("RGB", size, (30, 30, 200 - i)) for i in range(frames - 1)]
        first.save(buffer, format=fmt, save_all=True, append_images=rest)
    else:
        first.save(buffer, format=fmt)
    return buffer.getvalue()


def _write(path: Path, data: bytes | str) -> Path:
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path


# ─── materialize_local_source ────────────────────────────────────────────────


class TestMaterializeLocalSource:
    def test_snapshot_is_a_private_copy_removed_on_exit(self, tmp_path):
        original = _write(tmp_path / "notes.txt", "hello")
        with materialize_local_source(str(original), root=tmp_path) as snapshot:
            assert snapshot != original
            assert snapshot.read_text() == "hello"
            assert snapshot.name == "notes.txt"
        assert not snapshot.exists()
        assert original.read_text() == "hello"

    def test_relative_path_is_rejected(self):
        with pytest.raises(SourceValidationError, match="absolute"):
            with materialize_local_source("relative/notes.txt", allow_any_path=True):
                pass

    def test_missing_parent_is_rejected(self, tmp_path):
        with pytest.raises(SourceValidationError, match="Cannot resolve"):
            with materialize_local_source(str(tmp_path / "missing" / "x.txt"), allow_any_path=True):
                pass

    def test_constrained_mode_requires_a_root(self, tmp_path):
        original = _write(tmp_path / "x.txt", "x")
        with pytest.raises(SourceValidationError, match="Root must be provided"):
            with materialize_local_source(str(original)):
                pass

    def test_path_outside_root_is_rejected(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        outside = _write(tmp_path / "secret.txt", "x")
        with pytest.raises(SourceValidationError, match="outside allowed root"):
            with materialize_local_source(str(outside), root=root):
                pass

    @pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="needs O_NOFOLLOW")
    def test_symlink_is_not_followed(self, tmp_path):
        target = _write(tmp_path / "target.txt", "x")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        with pytest.raises(SourceValidationError, match="Cannot safely open"):
            with materialize_local_source(str(link), allow_any_path=True):
                pass

    def test_directory_is_not_a_regular_file(self, tmp_path):
        directory = tmp_path / "folder"
        directory.mkdir()
        with pytest.raises(SourceValidationError):
            with materialize_local_source(str(directory), allow_any_path=True):
                pass

    def test_oversized_file_is_rejected_before_copying(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "MAX_RAW_SIZE_BYTES", 4)
        original = _write(tmp_path / "big.txt", "12345")
        with pytest.raises(SourceLimitExceeded):
            with materialize_local_source(str(original), allow_any_path=True):
                pass


# ─── validate_local_source / sanitize_filename ───────────────────────────────


class TestLocalSourceAndFilename:
    def test_empty_source_is_rejected(self):
        with pytest.raises(SourceValidationError, match="Empty"):
            validate_local_source("", allow_any_path=True)

    def test_constrained_mode_requires_a_root(self, tmp_path):
        original = _write(tmp_path / "x.txt", "x")
        with pytest.raises(SourceValidationError, match="Root must be provided"):
            validate_local_source(str(original))

    def test_file_inside_root_is_resolved(self, tmp_path):
        original = _write(tmp_path / "x.txt", "x")
        assert validate_local_source(str(original), root=tmp_path) == original.resolve()

    def test_oversized_file_is_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "MAX_RAW_SIZE_BYTES", 2)
        original = _write(tmp_path / "x.txt", "xyz")
        with pytest.raises(SourceLimitExceeded):
            validate_local_source(str(original), allow_any_path=True)

    def test_reserved_attachment_marker_is_defused(self):
        assert sanitize_filename("[Attached: evil].txt") == "_[Attached: evil].txt"

    def test_long_name_is_truncated_on_a_utf8_boundary(self):
        name = "あ" * 100  # 300 UTF-8 bytes
        result = sanitize_filename(name)
        assert len(result.encode("utf-8")) <= 255
        assert result == "あ" * 85

    @pytest.mark.parametrize("name", ["", "\x00\x01", "."])
    def test_name_that_sanitizes_to_nothing_is_rejected(self, name):
        with pytest.raises(SourceValidationError):
            sanitize_filename(name)

    @pytest.mark.parametrize("name", ["..", "...", "../.."])
    def test_dot_names_never_become_traversal_components(self, name):
        assert sanitize_filename(name) not in ("", ".", "..")


# ─── Media-type detection ────────────────────────────────────────────────────


class TestDetectMediaType:
    def test_short_data_falls_back_to_text(self):
        assert detect_media_type(b"hi") == "text/plain"

    def test_gif(self):
        assert detect_media_type(_image_bytes("GIF")) == "image/gif"

    def test_webp(self):
        assert detect_media_type(_image_bytes("WEBP")) == "image/webp"

    def test_riff_that_is_not_webp_is_unknown(self):
        assert detect_media_type(b"RIFF\x00\x00\x00\x00WAVEfmt ") is None

    @pytest.mark.parametrize("media_type", [DOCX, XLSX, PPTX])
    def test_ooxml_from_content_types(self, media_type):
        assert detect_media_type(_ooxml_bytes(media_type)) == media_type

    def test_plain_zip_is_unknown(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("readme.txt", "x")
        assert detect_media_type(buffer.getvalue()) is None

    def test_truncated_ooxml_header_is_detected_from_the_full_file(self, tmp_path):
        data = _ooxml_bytes(DOCX, {"word/media/pad.bin": os.urandom(16384)})
        path = _write(tmp_path / "doc.docx", data)
        header = data[:8192]  # central directory is beyond the header read
        assert detect_media_type(header) is None
        assert detect_media_type(header, path=path) == DOCX

    def test_svg_after_xml_declaration(self):
        data = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>'
        assert detect_media_type(data) == "image/svg+xml"

    def test_invalid_utf8_is_unknown(self):
        assert detect_media_type(b"\xff\xfe\xfa\xfb\xfc") is None

    def test_ooxml_from_path_handles_bad_and_plain_zips(self, tmp_path):
        assert detect_ooxml_from_path(_write(tmp_path / "bad.docx", b"PK\x03\x04garbage")) is None
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("x.txt", "x")
        assert detect_ooxml_from_path(_write(tmp_path / "plain.zip", buffer.getvalue())) is None
        assert detect_ooxml_from_path(_write(tmp_path / "x.xlsx", _ooxml_bytes(XLSX))) == XLSX


class TestValidateMediaType:
    def test_unknown_detection_trusts_an_allowed_content_type(self):
        assert validate_media_type(None, "text/csv") == "text/csv"

    def test_unknown_detection_without_content_type_is_rejected(self):
        with pytest.raises(SourceValidationError, match="Unable to determine"):
            validate_media_type(None)

    def test_unknown_detection_with_disallowed_content_type_is_rejected(self):
        with pytest.raises(SourceValidationError):
            validate_media_type(None, "application/x-msdownload")

    def test_plain_text_is_refined_by_a_text_content_type(self):
        assert validate_media_type("text/plain", "text/markdown; charset=utf-8") == "text/markdown"

    def test_conflicting_content_type_is_a_mismatch(self):
        with pytest.raises(SourceTypeMismatch):
            validate_media_type("image/png", "application/pdf")

    def test_octet_stream_does_not_override_detection(self):
        assert validate_media_type("application/pdf", "application/octet-stream") == "application/pdf"

    def test_content_type_parameters_and_case_are_ignored(self):
        assert validate_media_type("application/pdf", "Application/PDF; q=1") == "application/pdf"

    def test_detected_type_outside_the_allowed_set_is_rejected(self):
        with pytest.raises(SourceValidationError, match="Unsupported"):
            validate_media_type("application/x-msdownload")


# ─── Content limits ──────────────────────────────────────────────────────────


class TestRawAndSvgLimits:
    def test_raw_size_limit_applies_to_every_type(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "MAX_RAW_SIZE_BYTES", 3)
        with pytest.raises(SourceLimitExceeded):
            enforce_content_limits(_write(tmp_path / "x.txt", "abcd"), "text/plain")

    def test_svg_size_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "MAX_SVG_BYTES", 10)
        svg = _write(tmp_path / "x.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
        with pytest.raises(SourceLimitExceeded):
            enforce_content_limits(svg, "image/svg+xml")

    @pytest.mark.parametrize("body", [
        "<script>alert(1)</script>",
        '<rect onload="alert(1)"/>',
        "<foreignObject><div/></foreignObject>",
    ])
    def test_active_content_is_rejected(self, tmp_path, body):
        svg = _write(tmp_path / "x.svg", f'<svg xmlns="http://www.w3.org/2000/svg">{body}</svg>')
        with pytest.raises(SourceValidationError, match="unsafe active content"):
            enforce_content_limits(svg, "image/svg+xml")

    @pytest.mark.parametrize("prolog", [
        '<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>',
        "<!ENTITY x 'y'>",
    ])
    def test_doctype_and_entities_are_rejected(self, tmp_path, prolog):
        svg = _write(tmp_path / "x.svg", f'{prolog}<svg xmlns="http://www.w3.org/2000/svg"/>')
        with pytest.raises(SourceValidationError):
            enforce_content_limits(svg, "image/svg+xml")

    @pytest.mark.parametrize("attr", [
        'href="https://example.invalid/a.png"',
        "xlink:href='http://example.invalid/a.png'",
        'href="javascript:alert(1)"',
        'href="file:///etc/passwd"',
    ])
    def test_external_references_are_rejected(self, tmp_path, attr):
        svg = _write(tmp_path / "x.svg", f'<svg xmlns="http://www.w3.org/2000/svg"><image {attr}/></svg>')
        with pytest.raises(SourceValidationError, match="external resource"):
            enforce_content_limits(svg, "image/svg+xml")

    def test_internal_and_data_references_are_allowed(self, tmp_path):
        svg = _write(
            tmp_path / "x.svg",
            '<svg xmlns="http://www.w3.org/2000/svg"><defs><g id="a"/></defs>'
            '<use href="#a"/><image href="data:image/png;base64,AAAA"/></svg>',
        )
        enforce_content_limits(svg, "image/svg+xml")

    def test_svg_that_is_not_utf8_is_rejected(self, tmp_path):
        svg = _write(tmp_path / "x.svg", b"<svg>\xff</svg>")
        with pytest.raises(UnicodeDecodeError):
            enforce_content_limits(svg, "image/svg+xml")


class TestRasterLimits:
    def test_small_png_passes(self, tmp_path):
        enforce_content_limits(_write(tmp_path / "x.png", _image_bytes("PNG")), "image/png")

    def test_compressed_size_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "MAX_RASTER_COMPRESSED_BYTES", 10)
        with pytest.raises(SourceLimitExceeded, match="compressed"):
            enforce_content_limits(_write(tmp_path / "x.png", _image_bytes("PNG")), "image/png")

    def test_pixel_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "MAX_RASTER_PIXELS", 15)
        with pytest.raises(SourceLimitExceeded, match="pixels"):
            enforce_content_limits(_write(tmp_path / "x.png", _image_bytes("PNG")), "image/png")

    def test_gif_frame_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "MAX_GIF_FRAMES", 2)
        gif = _write(tmp_path / "x.gif", _image_bytes("GIF", frames=3))
        with pytest.raises(SourceLimitExceeded, match="GIF"):
            enforce_content_limits(gif, "image/gif")

    def test_gif_cumulative_pixel_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "MAX_GIF_CUMULATIVE_PIXELS", 40)
        gif = _write(tmp_path / "x.gif", _image_bytes("GIF", frames=3))  # 3 × 16 px
        with pytest.raises(SourceLimitExceeded, match="GIF"):
            enforce_content_limits(gif, "image/gif")

    def test_decompression_bomb_warning_is_a_validation_error(self, tmp_path, monkeypatch):
        from PIL import Image

        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)  # 16 px > limit → warning, not error
        with pytest.raises(SourceValidationError, match="Invalid raster"):
            enforce_content_limits(_write(tmp_path / "x.png", _image_bytes("PNG")), "image/png")

    def test_corrupt_image_is_a_validation_error(self, tmp_path):
        bad = _write(tmp_path / "x.png", b"\x89PNG\r\n\x1a\nnot really")
        with pytest.raises(SourceValidationError, match="Invalid raster"):
            enforce_content_limits(bad, "image/png")


def _zip_with(tmp_path: Path, infos: list[tuple[zipfile.ZipInfo | str, bytes]],
              compression: int = zipfile.ZIP_STORED) -> Path:
    path = tmp_path / "doc.docx"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicate names warn on write
        with zipfile.ZipFile(path, "w", compression) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            for info, data in infos:
                archive.writestr(info, data)
    return path


class TestOoxmlArchiveLimits:
    def test_ordinary_archive_passes(self, tmp_path):
        enforce_content_limits(_zip_with(tmp_path, [("word/document.xml", b"<w/>")]), DOCX)

    @pytest.mark.parametrize("name", ["../evil.xml", "/abs.xml", "word\\..\\..\\evil.xml"])
    def test_unsafe_entry_path(self, tmp_path, name):
        with pytest.raises(SourceValidationError, match="unsafe entry path"):
            enforce_content_limits(_zip_with(tmp_path, [(name, b"x")]), DOCX)

    def test_duplicate_entry_path(self, tmp_path):
        archive = _zip_with(tmp_path, [("word/a.xml", b"1"), ("word/a.xml", b"2")])
        with pytest.raises(SourceValidationError, match="duplicate"):
            enforce_content_limits(archive, XLSX)

    def test_encrypted_entry(self, tmp_path):
        archive = _zip_with(tmp_path, [("word/secret.xml", b"x")])
        # zipfile cannot write encrypted entries; set the flag bit in the central directory.
        data = bytearray(archive.read_bytes())
        record = data.rfind(b"PK\x01\x02")  # last entry = word/secret.xml
        data[record + 8] |= 0x1
        archive.write_bytes(bytes(data))
        with pytest.raises(SourceValidationError, match="encrypted"):
            enforce_content_limits(archive, DOCX)

    def test_symlink_entry(self, tmp_path):
        info = zipfile.ZipInfo("word/link.xml")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with pytest.raises(SourceValidationError, match="symlink"):
            enforce_content_limits(_zip_with(tmp_path, [(info, b"/etc/passwd")]), PPTX)

    def test_entry_count_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "MAX_ZIP_ENTRIES", 2)
        archive = _zip_with(tmp_path, [("a.xml", b"1"), ("b.xml", b"2")])
        with pytest.raises(SourceLimitExceeded, match="entries"):
            enforce_content_limits(archive, DOCX)

    def test_single_entry_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "MAX_ZIP_SINGLE_ENTRY", 4)
        with pytest.raises(SourceLimitExceeded, match="oversized entry"):
            enforce_content_limits(_zip_with(tmp_path, [("a.xml", b"12345")]), DOCX)

    def test_total_uncompressed_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "MAX_ZIP_TOTAL_UNCOMPRESSED", 15)
        archive = _zip_with(tmp_path, [("a.xml", b"x" * 6), ("b.xml", b"y" * 6)])
        with pytest.raises(SourceLimitExceeded, match="total"):
            enforce_content_limits(archive, DOCX)

    def test_compression_ratio_limit(self, tmp_path):
        archive = _zip_with(tmp_path, [("bomb.xml", b"\x00" * 1_000_000)], zipfile.ZIP_DEFLATED)
        with pytest.raises(SourceLimitExceeded, match="compression-ratio"):
            enforce_content_limits(archive, DOCX)

    def test_not_a_zip(self, tmp_path):
        with pytest.raises(SourceValidationError, match="Invalid OOXML"):
            enforce_content_limits(_write(tmp_path / "x.docx", b"PK\x03\x04broken"), DOCX)


class TestPdfLimits:
    @staticmethod
    def _pdf(tmp_path: Path, pages: int) -> Path:
        from pypdf import PdfWriter

        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=72, height=72)
        path = tmp_path / "x.pdf"
        with path.open("wb") as handle:
            writer.write(handle)
        return path

    def test_page_count_within_limit(self, tmp_path):
        enforce_content_limits(self._pdf(tmp_path, 2), "application/pdf")

    def test_page_count_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "MAX_PDF_PAGES", 1)
        with pytest.raises(SourceLimitExceeded, match="pages"):
            enforce_content_limits(self._pdf(tmp_path, 2), "application/pdf")

    def test_corrupt_pdf(self, tmp_path):
        with pytest.raises(SourceValidationError, match="Invalid PDF"):
            enforce_content_limits(_write(tmp_path / "x.pdf", b"%PDF-1.4 nothing"), "application/pdf")


# ─── Small helpers ───────────────────────────────────────────────────────────


def test_canonical_extension():
    assert get_canonical_extension("image/jpeg") == ".jpg"
    assert get_canonical_extension("application/x-unknown") == ""


def test_source_identities(tmp_path):
    original = _write(tmp_path / "x.txt", "abc")
    local = source_identity_local(original)
    assert local["kind"] == "file" and local["size"] == 3 and local["realpath"] == str(original.resolve())
    assert source_identity_s3("uploads/u/k", '"etag"', 9) == {
        "kind": "s3", "key": "uploads/u/k", "etag": '"etag"', "size": 9,
    }
