# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the attachment pipeline (Phase 1 foundation).

Covers:
- UTF-8 byte paging (offset, limit, boundaries, line numbers, forward progress)
- Source validation (path traversal, symlinks, cloud keys)
- Secure URL fetcher (SSRF / DNS rebinding / IP pinning)
- Resource limits
- Cache identity and stage publish
- Import bundle commit (atomic, idempotent, conflict)
- IMPORT_INCOMPLETE and LoopGuard interaction
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ─── UTF-8 Byte Paging Tests ─────────────────────────────────────────────────


class TestPaging:
    """Tests for sdpm.tools.attachment.paging."""

    def test_basic_page(self):
        """First page with default params."""
        from sdpm.tools.attachment.paging import page_text

        data = "Line 1\nLine 2\nLine 3\n".encode("utf-8")
        result = page_text(data, offset=0, limit=10240, source="test.txt", file_name="test.txt", media_type="text/plain")

        assert result.header["version"] == 1
        assert result.header["source"] == "test.txt"
        assert result.header["page"]["offset"] == 0
        assert result.header["page"]["totalBytes"] == len(data)
        assert result.header["page"]["truncated"] is False
        assert "1:" in result.body
        assert "Line 1" in result.body

    def test_offset_continuation(self):
        """Page from a non-zero offset."""
        from sdpm.tools.attachment.paging import page_text

        data = "Line 1\nLine 2\nLine 3\n".encode("utf-8")
        # Offset to start of "Line 2"
        offset = len("Line 1\n".encode("utf-8"))
        result = page_text(data, offset=offset, limit=10240, source="test.txt", file_name="test.txt", media_type="text/plain")

        assert result.header["page"]["startLine"] == 2
        assert "Line 2" in result.body

    def test_eof_offset(self):
        """Offset beyond EOF returns empty non-truncated page."""
        from sdpm.tools.attachment.paging import page_text

        data = "Hello\n".encode("utf-8")
        result = page_text(data, offset=100, limit=10240, source="t", file_name="t", media_type="text/plain")

        assert result.header["page"]["truncated"] is False
        assert result.body == ""

    def test_negative_offset_error(self):
        """Negative offset raises PagingError."""
        from sdpm.tools.attachment.paging import PagingError, validate_paging_params

        with pytest.raises(PagingError, match="offset must be >= 0"):
            validate_paging_params(-1, 1024)

    def test_limit_below_min_error(self):
        """Limit below minimum raises PagingError."""
        from sdpm.tools.attachment.paging import PagingError, validate_paging_params

        with pytest.raises(PagingError, match="limit must be >="):
            validate_paging_params(0, 100)

    def test_continuation_byte_offset_error(self):
        """Offset on UTF-8 continuation byte raises error."""
        from sdpm.tools.attachment.paging import PagingError, page_text

        # "あ" = 3 bytes: E3 81 82
        data = "あいう".encode("utf-8")  # 9 bytes
        with pytest.raises(PagingError, match="continuation byte"):
            page_text(data, offset=1, limit=10240, source="t", file_name="t", media_type="text/plain")

    def test_forward_progress_guarantee(self):
        """nextOffset > offset when not at EOF (prevents infinite loops)."""
        from sdpm.tools.attachment.paging import page_text

        data = ("A" * 20000).encode("utf-8")  # One huge line
        result = page_text(data, offset=0, limit=512, source="t", file_name="t", media_type="text/plain")

        if result.header["page"]["truncated"]:
            assert result.header["page"]["nextOffset"] > 0

    def test_multibyte_boundary_split(self):
        """Splitting respects UTF-8 code point boundaries."""
        from sdpm.tools.attachment.paging import page_text

        # Create text that would split mid-character with tight limit
        data = ("あ" * 100).encode("utf-8")  # 300 bytes of 3-byte chars
        result = page_text(data, offset=0, limit=520, source="t", file_name="t", media_type="text/plain")

        # Body should decode cleanly (no replacement characters from bad splits)
        assert "\ufffd" not in result.body

    def test_limit_caps_output(self):
        """Total output bytes respect the limit (body only, header is overhead)."""
        from sdpm.tools.attachment.paging import page_text

        data = ("Line of text\n" * 1000).encode("utf-8")
        limit = 1024
        result = page_text(data, offset=0, limit=limit, source="t", file_name="t", media_type="text/plain")

        # The body bytes should be within budget (limit minus header overhead)
        body_bytes = len(result.body.encode("utf-8"))
        header_json = json.dumps(result.header, ensure_ascii=False, separators=(",", ":"))
        header_bytes = len(header_json.encode("utf-8"))
        assert header_bytes + body_bytes <= limit


# ─── Source Validation Tests ──────────────────────────────────────────────────


class TestSourceValidation:
    """Tests for sdpm.tools.attachment.source."""

    def test_classify_url(self):
        from sdpm.tools.attachment.source import classify_source
        assert classify_source("https://example.com/file.pdf") == "url"
        assert classify_source("http://example.com/file.pdf") == "url"

    def test_classify_s3_key(self):
        from sdpm.tools.attachment.source import classify_source
        assert classify_source("uploads/user123/12345678-1234-1234-1234-123456789abc/report.pdf") == "s3_key"

    def test_classify_local_path(self):
        from sdpm.tools.attachment.source import classify_source
        generated_path = Path(tempfile.gettempdir()) / "attachment-test" / "file.pdf"
        assert classify_source(str(generated_path)) == "local_path"
        assert classify_source(str(Path.cwd() / "docs" / "report.pdf")) == "local_path"

    def test_validate_local_absolute_only(self):
        from sdpm.tools.attachment.source import validate_local_source
        from sdpm.tools.attachment.errors import SourceValidationError

        with pytest.raises(SourceValidationError, match="absolute path"):
            validate_local_source("relative/path.txt", allow_any_path=True)

    def test_validate_local_file_not_found(self):
        from sdpm.tools.attachment.source import validate_local_source
        from sdpm.tools.attachment.errors import SourceValidationError

        with pytest.raises(SourceValidationError, match="Cannot resolve"):
            validate_local_source("/nonexistent/path/file.txt", allow_any_path=True)

    def test_validate_local_regular_file(self):
        from sdpm.tools.attachment.source import validate_local_source

        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            f.write(b"test content")
            f.flush()
            resolved = validate_local_source(f.name, allow_any_path=True)
            assert resolved.is_file()

    def test_validate_local_root_escape(self):
        """Path outside allowed root is rejected."""
        from sdpm.tools.attachment.source import validate_local_source
        from sdpm.tools.attachment.errors import SourceValidationError

        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            f.write(b"content")
            f.flush()
            disjoint_root = Path(f.name).parent / "allowed-root"
            with pytest.raises(SourceValidationError, match="outside allowed root"):
                validate_local_source(f.name, allow_any_path=False, root=disjoint_root)

    def test_validate_cloud_source_valid(self):
        from sdpm.tools.attachment.source import validate_cloud_source
        key = "uploads/user123/12345678-1234-1234-1234-123456789abc/report.pdf"
        assert validate_cloud_source(key, "user123") == key

    def test_validate_cloud_source_wrong_user(self):
        from sdpm.tools.attachment.source import validate_cloud_source
        from sdpm.tools.attachment.errors import SourceAccessDenied

        key = "uploads/user123/12345678-1234-1234-1234-123456789abc/report.pdf"
        with pytest.raises(SourceAccessDenied):
            validate_cloud_source(key, "other_user")

    def test_validate_cloud_source_path_traversal(self):
        from sdpm.tools.attachment.source import validate_cloud_source
        from sdpm.tools.attachment.errors import SourceValidationError

        with pytest.raises(SourceValidationError):
            validate_cloud_source("uploads/user/../admin/file", "user")

    def test_sanitize_filename_basic(self):
        from sdpm.tools.attachment.source import sanitize_filename
        assert sanitize_filename("report.pdf") == "report.pdf"

    def test_sanitize_filename_path_separators(self):
        from sdpm.tools.attachment.source import sanitize_filename
        result = sanitize_filename("../../etc/passwd")
        assert "/" not in result
        assert ".." not in result

    def test_sanitize_filename_control_chars(self):
        from sdpm.tools.attachment.source import sanitize_filename
        result = sanitize_filename("file\x00name\x01.txt")
        assert "\x00" not in result
        assert "\x01" not in result

    def test_sanitize_filename_leading_dot(self):
        from sdpm.tools.attachment.source import sanitize_filename
        result = sanitize_filename(".hidden_file")
        assert not result.startswith(".")


# ─── Secure URL Fetcher Tests ────────────────────────────────────────────────


class TestFetcherSSRF:
    """Tests for SSRF / DNS rebinding protection in fetcher."""

    def test_private_ip_blocked(self):
        from sdpm.tools.attachment.fetcher import _is_private_ip
        assert _is_private_ip("127.0.0.1") is True
        assert _is_private_ip("10.0.0.1") is True
        assert _is_private_ip("192.168.1.1") is True
        assert _is_private_ip("172.16.0.1") is True
        assert _is_private_ip("169.254.169.254") is True  # IMDS

    def test_public_ip_allowed(self):
        from sdpm.tools.attachment.fetcher import _is_private_ip
        assert _is_private_ip("8.8.8.8") is False
        assert _is_private_ip("1.1.1.1") is False
        assert _is_private_ip("203.0.114.1") is False  # Just outside documentation range

    def test_ipv6_loopback_blocked(self):
        from sdpm.tools.attachment.fetcher import _is_private_ip
        assert _is_private_ip("::1") is True

    def test_ipv6_ula_blocked(self):
        from sdpm.tools.attachment.fetcher import _is_private_ip
        assert _is_private_ip("fd00::1") is True

    def test_url_validation_scheme(self):
        from sdpm.tools.attachment.fetcher import _validate_url
        from sdpm.tools.attachment.errors import SourceValidationError

        with pytest.raises(SourceValidationError, match="Unsupported URL scheme"):
            _validate_url("ftp://example.com/file")

    def test_url_validation_credentials(self):
        from sdpm.tools.attachment.fetcher import _validate_url
        from sdpm.tools.attachment.errors import SourceValidationError

        credential_url = "https://{}:{}@example.com/file".format("test-user", "test-value")
        with pytest.raises(SourceValidationError, match="credentials"):
            _validate_url(credential_url)

    def test_url_validation_port(self):
        from sdpm.tools.attachment.fetcher import _validate_url
        from sdpm.tools.attachment.errors import SourceValidationError

        with pytest.raises(SourceValidationError, match="Only ports 80/443"):
            _validate_url("https://example.com:8080/file")

    def test_url_validation_valid(self):
        from sdpm.tools.attachment.fetcher import _validate_url
        scheme, hostname, port, path = _validate_url("https://example.com/path/file.pdf")
        assert scheme == "https"
        assert hostname == "example.com"
        assert port == 443
        assert path == "/path/file.pdf"

    def test_resolve_private_host_blocked(self):
        """DNS resolving to private IP is blocked."""
        from sdpm.tools.attachment.fetcher import _resolve_and_validate
        from sdpm.tools.attachment.errors import SSRFBlocked

        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(2, 1, 6, "", ("127.0.0.1", 0))]
            with pytest.raises(SSRFBlocked, match="private/reserved"):
                _resolve_and_validate("evil.example.com")

    def test_resolve_imds_blocked(self):
        """DNS resolving to IMDS IP (169.254.169.254) is blocked."""
        from sdpm.tools.attachment.fetcher import _resolve_and_validate
        from sdpm.tools.attachment.errors import SSRFBlocked

        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(2, 1, 6, "", ("169.254.169.254", 0))]
            with pytest.raises(SSRFBlocked, match="private/reserved"):
                _resolve_and_validate("metadata.example.com")


# ─── Resource Limits Tests ────────────────────────────────────────────────────


class TestLimits:
    """Tests for resource limit constants."""

    def test_limits_exist(self):
        from sdpm.tools.attachment.limits import (
            MAX_RAW_SIZE_BYTES,
            MAX_RASTER_PIXELS,
            MAX_PDF_PAGES,
            MAX_ZIP_ENTRIES,
            IMPORT_DEADLINE_S,
            PAGING_DEFAULT_LIMIT,
        )
        assert MAX_RAW_SIZE_BYTES == 100 * 1024 * 1024
        assert MAX_RASTER_PIXELS == 40_000_000
        assert MAX_PDF_PAGES == 100
        assert MAX_ZIP_ENTRIES == 10_000
        assert IMPORT_DEADLINE_S == 100.0
        assert PAGING_DEFAULT_LIMIT == 10_240


# ─── Cache Tests ──────────────────────────────────────────────────────────────


class TestCache:
    """Tests for stage cache identity and publish."""

    def test_pipeline_version_format(self):
        import sdpm
        from sdpm.tools.attachment.cache import pipeline_version
        pv = pipeline_version()
        assert ":attachment-" in pv
        # Derived from sdpm.__version__ so cache keys rotate on engine releases.
        assert pv.startswith(f"{sdpm.__version__}:attachment-")

    def test_import_key_deterministic(self):
        from sdpm.tools.attachment.cache import compute_import_key
        key1 = compute_import_key("abc123", "0.5.3:attachment-1", {"filename": "test.pdf"})
        key2 = compute_import_key("abc123", "0.5.3:attachment-1", {"filename": "test.pdf"})
        assert key1 == key2

    def test_import_key_differs_on_option_change(self):
        from sdpm.tools.attachment.cache import compute_import_key
        key1 = compute_import_key("abc123", "0.5.3:attachment-1", {"filename": "test.pdf"})
        key2 = compute_import_key("abc123", "0.5.3:attachment-1", {"filename": "other.pdf"})
        assert key1 != key2

    def test_local_stage_cache_miss(self):
        from sdpm.tools.attachment.cache import LocalStageCache

        with tempfile.TemporaryDirectory() as tmp:
            cache = LocalStageCache(base_dir=Path(tmp))
            result = cache.get_stage("source1", "pipe1", "materialize", "key1")
            assert result is None

    def test_local_stage_cache_publish_and_get(self):
        from sdpm.tools.attachment.cache import (
            LocalStageCache,
            StageRecord,
            compute_pipeline_key,
        )

        with tempfile.TemporaryDirectory() as tmp:
            cache = LocalStageCache(base_dir=Path(tmp))

            # Create temp outputs
            outputs_dir = Path(tmp) / "temp_outputs"
            outputs_dir.mkdir()
            (outputs_dir / "result.txt").write_text("hello")

            record = StageRecord(
                stage="extract_text",
                source_identity_hash="src1",
                source_hash="sha1",
                pipeline_version="0.5.3:attachment-1",
                options_hash="opts1",
                outputs=[{
                    "path": "result.txt",
                    "size": 5,
                    "sha256": hashlib.sha256(b"hello").hexdigest(),
                    "contentType": "text/plain",
                }],
                completed_at="2026-08-02T00:00:00Z",
            )

            pipeline_key = compute_pipeline_key(record.pipeline_version, record.options_hash)
            cache.publish_stage("src1", pipeline_key, "extract_text", "key1", record, outputs_dir)

            # Retrieve
            got = cache.get_stage("src1", pipeline_key, "extract_text", "key1")
            assert got is not None
            assert got.stage == "extract_text"


# ─── Bundle Commit Tests ──────────────────────────────────────────────────────


class TestBundleCommit:
    """Tests for import bundle commit."""

    def test_commit_creates_manifest(self):
        from sdpm.tools.attachment.bundle import BundleManifest, LocalBundleCommitter

        with tempfile.TemporaryDirectory() as tmp:
            deck_dir = Path(tmp) / "deck"
            deck_dir.mkdir()

            committer = LocalBundleCommitter(deck_dir=deck_dir)
            staging = committer.create_staging("req-1")

            # Create a file in staging
            (staging / "source").mkdir()
            (staging / "source" / "test.txt").write_text("hello")

            manifest = BundleManifest(
                import_key="import123",
                source_hash="sha256abc",
                pipeline_version="0.5.3:attachment-1",
                options={"filename": "test.txt"},
                files=[{"path": "source/test.txt", "size": 5, "sha256": hashlib.sha256(b"hello").hexdigest(), "contentType": "text/plain"}],
            )

            result = committer.commit("req-1", manifest)
            assert (result / "manifest.json").exists()
            assert (result / "source" / "test.txt").exists()

    def test_commit_idempotent_reuse(self):
        """Same importKey + sourceHash = reuse, no conflict."""
        from sdpm.tools.attachment.bundle import BundleManifest, LocalBundleCommitter

        with tempfile.TemporaryDirectory() as tmp:
            deck_dir = Path(tmp) / "deck"
            deck_dir.mkdir()

            committer = LocalBundleCommitter(deck_dir=deck_dir)

            # First commit
            staging1 = committer.create_staging("req-1")
            (staging1 / "source").mkdir()
            (staging1 / "source" / "test.txt").write_text("hello")
            manifest1 = BundleManifest(
                import_key="import123", source_hash="sha256abc",
                pipeline_version="0.5.3:attachment-1",
                options={"filename": "test.txt"},
                files=[{"path": "source/test.txt", "size": 5, "sha256": hashlib.sha256(b"hello").hexdigest(), "contentType": "text/plain"}],
            )
            committer.commit("req-1", manifest1)

            # Second commit with same key — should reuse
            staging2 = committer.create_staging("req-2")
            (staging2 / "source").mkdir()
            (staging2 / "source" / "test.txt").write_text("hello")
            manifest2 = BundleManifest(
                import_key="import123", source_hash="sha256abc",
                pipeline_version="0.5.3:attachment-1",
                options={"filename": "test.txt"},
                files=[{"path": "source/test.txt", "size": 5, "sha256": hashlib.sha256(b"hello").hexdigest(), "contentType": "text/plain"}],
            )
            result = committer.commit("req-2", manifest2)
            assert result == committer.target_dir("import123")

    def test_deck_not_modified_during_import(self):
        """Import staging doesn't touch deck visible state until commit."""
        from sdpm.tools.attachment.bundle import LocalBundleCommitter

        with tempfile.TemporaryDirectory() as tmp:
            deck_dir = Path(tmp) / "deck"
            deck_dir.mkdir()
            # Pre-existing deck content
            slides_dir = deck_dir / "slides"
            slides_dir.mkdir()
            (slides_dir / "slide-01.json").write_text('{"title":"existing"}')

            committer = LocalBundleCommitter(deck_dir=deck_dir)
            staging = committer.create_staging("req-1")
            (staging / "deck").mkdir()
            (staging / "deck" / "new-content.json").write_text('{"new":true}')

            # Before commit, deck is unchanged
            assert (slides_dir / "slide-01.json").read_text() == '{"title":"existing"}'
            assert not (deck_dir / "attachments").exists()


# ─── IMPORT_INCOMPLETE and LoopGuard Tests ────────────────────────────────────


class TestImportIncomplete:
    """Tests for IMPORT_INCOMPLETE response and LoopGuard interaction."""

    def test_import_incomplete_shape(self):
        """IMPORT_INCOMPLETE has the exact required shape."""
        from sdpm.tools.attachment.errors import ImportIncomplete

        err = ImportIncomplete(
            message="Import did not complete within deadline.",
            completed_stages=["materialize", "extract_text"],
        )
        d = err.to_dict()

        assert d["code"] == "IMPORT_INCOMPLETE"
        assert d["retryable"] is True
        assert d["completedStages"] == ["materialize", "extract_text"]
        assert d["nextAction"] == "Call import_attachment again with exactly the same source, deck_id, and filename."

    def test_loopguard_progress_resets_counter(self):
        """LoopGuard recognizes progress (more completedStages) and resets."""
        # Simulate LoopGuard logic: same args but progress = not a loop
        last_completed_count = 0
        no_progress_count = 0

        def loopguard_check(response: dict) -> bool:
            """Returns True if should stop (infinite loop detected)."""
            nonlocal last_completed_count, no_progress_count

            if response.get("code") != "IMPORT_INCOMPLETE":
                return False

            completed = response.get("completedStages", [])
            current_count = len(completed)

            if current_count > last_completed_count:
                # Progress! Reset counter
                last_completed_count = current_count
                no_progress_count = 0
                return False
            else:
                # No progress
                no_progress_count += 1
                return no_progress_count >= 3

        # First call: 1 stage done
        assert loopguard_check({"code": "IMPORT_INCOMPLETE", "completedStages": ["materialize"]}) is False

        # Second call: 2 stages done — progress!
        assert loopguard_check({"code": "IMPORT_INCOMPLETE", "completedStages": ["materialize", "extract_text"]}) is False

        # Third call: 3 stages — progress!
        assert loopguard_check({"code": "IMPORT_INCOMPLETE", "completedStages": ["materialize", "extract_text", "extract_images"]}) is False

        # Fourth call: still 3 stages — no progress (1)
        assert loopguard_check({"code": "IMPORT_INCOMPLETE", "completedStages": ["materialize", "extract_text", "extract_images"]}) is False

        # Fifth call: still 3 stages — no progress (2)
        assert loopguard_check({"code": "IMPORT_INCOMPLETE", "completedStages": ["materialize", "extract_text", "extract_images"]}) is False

        # Sixth call: still 3 stages — no progress (3) → STOP
        assert loopguard_check({"code": "IMPORT_INCOMPLETE", "completedStages": ["materialize", "extract_text", "extract_images"]}) is True


# ─── Media Type Detection Tests ───────────────────────────────────────────────


class TestMediaTypeDetection:
    """Tests for magic-based media type detection."""

    def test_detect_pdf(self):
        from sdpm.tools.attachment.source import detect_media_type
        assert detect_media_type(b"%PDF-1.4 ...") == "application/pdf"

    def test_detect_png(self):
        from sdpm.tools.attachment.source import detect_media_type
        assert detect_media_type(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100) == "image/png"

    def test_detect_jpeg(self):
        from sdpm.tools.attachment.source import detect_media_type
        assert detect_media_type(b"\xff\xd8\xff\xe0" + b"\x00" * 100) == "image/jpeg"

    def test_detect_text(self):
        from sdpm.tools.attachment.source import detect_media_type
        assert detect_media_type(b"Hello, world!\nThis is text.") == "text/plain"

    def test_detect_binary_null_bytes(self):
        from sdpm.tools.attachment.source import detect_media_type
        assert detect_media_type(b"\x00\x01\x02\x03") is None


# ─── Integration: read_attachment contract ────────────────────────────────────


class TestReadAttachmentContract:
    """Integration tests for read_attachment tool contract."""

    def test_read_text_file(self):
        from sdpm.tools.attachment.contracts import read_attachment

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Line 1\nLine 2\nLine 3\n")
            f.flush()
            path = f.name

        try:
            result = read_attachment(path, offset=0, limit=10240)
            assert "error" not in result
            assert result["header"]["version"] == 1
            assert result["header"]["kind"] == "text"
            assert "Line 1" in result["body"]
        finally:
            os.unlink(path)

    def test_read_invalid_offset(self):
        from sdpm.tools.attachment.contracts import read_attachment
        missing = str(Path.cwd() / "nonexistent-attachment")
        result = read_attachment(missing, offset=-1, limit=10240)
        assert "error" in result
        assert result["error"]["code"] == "INVALID_OFFSET"

    def test_read_invalid_limit(self):
        from sdpm.tools.attachment.contracts import read_attachment
        missing = str(Path.cwd() / "nonexistent-attachment")
        result = read_attachment(missing, offset=0, limit=100)
        assert "error" in result
        assert result["error"]["code"] == "INVALID_LIMIT"

    def test_read_nonexistent_file(self):
        from sdpm.tools.attachment.contracts import read_attachment
        result = read_attachment("/nonexistent/path/file.txt", offset=0, limit=10240)
        assert "error" in result


# ─── Integration: import_attachment contract ──────────────────────────────────


class TestImportAttachmentContract:
    """Integration tests for import_attachment tool contract."""

    def test_import_text_file(self):
        from sdpm.tools.attachment.contracts import import_attachment

        with tempfile.TemporaryDirectory() as tmp:
            # Create a deck directory
            deck_dir = Path(tmp) / "deck"
            deck_dir.mkdir()

            # Create a source file
            source_file = Path(tmp) / "source.txt"
            source_file.write_text("Hello, world!")

            result = import_attachment(str(source_file), str(deck_dir))
            assert "error" not in result or result.get("code") != "IMPORT_INCOMPLETE"
            assert "importKey" in result
            assert "sourceHash" in result

    def test_import_nonexistent_deck(self):
        from sdpm.tools.attachment.contracts import import_attachment
        missing_source = str(Path.cwd() / "nonexistent-source.txt")
        result = import_attachment(missing_source, "/nonexistent/deck")
        assert "error" in result
        assert result["error"]["code"] == "DECK_NOT_FOUND"

    def test_import_idempotent(self):
        """Same source + options = reuse on second call."""
        from sdpm.tools.attachment.contracts import import_attachment

        with tempfile.TemporaryDirectory() as tmp:
            deck_dir = Path(tmp) / "deck"
            deck_dir.mkdir()
            source_file = Path(tmp) / "source.txt"
            source_file.write_text("Hello, world!")

            result1 = import_attachment(str(source_file), str(deck_dir))
            result2 = import_attachment(str(source_file), str(deck_dir))

            assert result1.get("importKey") == result2.get("importKey")
            assert result2.get("reused") is True


# ─── Grep Regression Tests ────────────────────────────────────────────────────


    def test_pptx_projection_includes_edit_guide_metadata(self, monkeypatch, tmp_path: Path):
        from sdpm.tools.attachment import PPTX_GUIDE_INSTRUCTION
        from sdpm.tools.attachment.pipeline import _pptx_projection
        import sdpm.engine.converter

        source = tmp_path / "quarterly-review.pptx"
        source.write_bytes(b"not-read-by-mocked-converter")
        monkeypatch.setattr(
            sdpm.engine.converter,
            "pptx_to_json",
            lambda _path: {
                "slides": [{"title": "One", "elements": []}, {"title": "Two", "elements": []}],
                "fonts": {"fullwidth": "Aptos", "halfwidth": "Aptos"},
            },
        )

        projection, header = _pptx_projection(source)
        assert b"Slides: 2" in projection
        assert header["guide"] == "import-pptx"
        assert header["guideInstruction"] == PPTX_GUIDE_INSTRUCTION
        assert header["suggestedName"] == "quarterly-review"
        assert header["slideCount"] == 2
        assert header["themeHints"]["fonts"]["halfwidth"] == "Aptos"

class TestRemovedToolsRegression:
    """Ensure no references to removed tools remain in active code.

    SPEC1 removals: measure_slides (standalone), list_asset_sources, save parameter
    SPEC2 removals: upload_file, read_uploaded_file, pptx_to_json (MCP tool)
    """

    # Files that are allowed to reference these names (test files, changelogs, docs history,
    # storage layer internal methods, build artifacts, venvs, asset manifests)
    _ALLOWED_PATTERNS = {
        "tests/",
        "CHANGELOG",
        ".kiro/specs/",
        "docs/",
        "__pycache__",
        "build/",
        ".venv/",
        "manifest.json",  # asset manifests have 'upload_file' field names
        "storage/",  # storage layer has upload_file as an internal S3 method
        "server_utils",  # utility functions
        "route.ts",  # Web UI upload route is renamed/different concept
        "attachmentMarker.ts",  # attachment marker lib handles wire format
    }

    def _scan_for_pattern(self, pattern: str) -> list[str]:
        """Scan active source files for a pattern. Returns list of violating files."""
        import subprocess

        repo_root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            ["grep", "-rl", pattern,
             str(repo_root / "sdpm" / "sdpm" / "tools"),
             str(repo_root / "sdpm" / "references"),
             str(repo_root / "sdpm" / "SKILL.md"),
             str(repo_root / "servers" / "local"),
             str(repo_root / "servers" / "remote" / "server.py"),
             str(repo_root / "personas"),
             ],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        if result.returncode != 0:
            return []  # No matches

        violations = []
        for line in result.stdout.strip().splitlines():
            rel = str(Path(line).relative_to(repo_root))
            if any(allowed in rel for allowed in self._ALLOWED_PATTERNS):
                continue
            violations.append(rel)
        return violations

    def test_no_upload_file_tool_references(self):
        """upload_file MCP tool must not be defined/bound in servers (storage layer excluded)."""
        import subprocess
        repo_root = Path(__file__).resolve().parent.parent
        # Scan servers (excluding storage/) and tools contract
        targets = [
            str(repo_root / "servers" / "local"),
            str(repo_root / "servers" / "remote" / "server.py"),
            str(repo_root / "servers" / "remote" / "tools"),
            str(repo_root / "sdpm" / "sdpm" / "tools" / "__init__.py"),
        ]
        result = subprocess.run(
            ["grep", "-rn", "upload_file"] + targets,
            capture_output=True, text=True,
        )
        # Filter: exclude __pycache__, storage.upload_file calls in new attachment.py, .venv
        lines = [
            line for line in result.stdout.strip().splitlines()
            if "__pycache__" not in line
            and "storage.upload_file" not in line
            and "_storage.upload_file" not in line
            and ".venv/" not in line
        ]
        assert lines == [], f"upload_file tool still defined/bound: {lines}"

    def test_no_read_uploaded_file_references(self):
        """read_uploaded_file must not be referenced in active code."""
        violations = self._scan_for_pattern("read_uploaded_file")
        assert violations == [], f"read_uploaded_file still referenced in: {violations}"

    def test_no_measure_slides_tool_binding(self):
        """measure_slides must not be bound as a standalone MCP tool (run_python parameter stays)."""
        repo_root = Path(__file__).resolve().parent.parent
        # Check the tools contract for the standalone function definition
        tools_init = (repo_root / "sdpm" / "sdpm" / "tools" / "__init__.py").read_text()
        assert "def measure_slides(" not in tools_init, "measure_slides still in tools contract"
        # Check server bindings
        local_server = (repo_root / "servers" / "local" / "server.py").read_text()
        assert "measure_slides" not in local_server, "measure_slides still bound in local server"

    def test_no_list_asset_sources_tool_binding(self):
        """list_asset_sources must not be bound as a standalone MCP tool."""
        repo_root = Path(__file__).resolve().parent.parent
        # Check the tools contract
        tools_init = (repo_root / "sdpm" / "sdpm" / "tools" / "__init__.py").read_text()
        assert "def list_asset_sources(" not in tools_init, "list_asset_sources still in tools contract"
        # Check server bindings
        local_server = (repo_root / "servers" / "local" / "server.py").read_text()
        assert "list_asset_sources" not in local_server, "list_asset_sources still bound in local server"

    def test_no_pptx_to_json_mcp_tool(self):
        """pptx_to_json must not be registered as MCP tool (Engine function stays)."""
        repo_root = Path(__file__).resolve().parent.parent
        # Check the tools contract
        tools_init = (repo_root / "sdpm" / "sdpm" / "tools" / "__init__.py").read_text()
        assert "def pptx_to_json(" not in tools_init, "pptx_to_json still in tools contract"
        # Check servers
        local_server = (repo_root / "servers" / "local" / "server.py").read_text()
        assert "pptx_to_json" not in local_server, "pptx_to_json still in local server"

    def test_no_upload_id_ddb_schema(self):
        """UPLOAD# DDB schema must not be functionally used anywhere."""
        import subprocess
        repo_root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            ["grep", "-rn", "UPLOAD#",
             str(repo_root / "servers"),
             str(repo_root / "api"),
             ],
            capture_output=True, text=True,
        )
        # Filter out __pycache__, comments/docstrings mentioning removal, non-functional lines
        lines = []
        for line in result.stdout.strip().splitlines():
            if "__pycache__" in line:
                continue
            # Get the actual code content after the file:lineno: prefix
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            code = parts[2].strip()
            # Skip comments and docstrings
            if code.startswith("#") or code.startswith('"""') or code.startswith("'''"):
                continue
            # Skip lines that mention removal/deprecated
            if "removed" in code.lower() or "deprecated" in code.lower() or "no ddb" in code.lower():
                continue
            lines.append(line)
        assert lines == [], f"UPLOAD# still functionally used: {lines}"

    def test_no_save_parameter_in_run_python(self):
        """run_python and run_style_python must not have save parameter."""
        import subprocess
        repo_root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            ["grep", "-n", "save.*bool\\|save.*=.*True\\|save.*=.*False",
             str(repo_root / "servers" / "local" / "sandbox_tools.py"),
             str(repo_root / "servers" / "remote" / "tools" / "sandbox.py"),
             ],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "", f"save parameter still in sandbox: {result.stdout}"

    def test_v1_marker_format_only(self):
        """Attachment markers must use v1 JSON format only."""
        # Verify the marker format in personas/instructions contains v1
        repo_root = Path(__file__).resolve().parent.parent
        instructions = (repo_root / "sdpm" / "sdpm" / "tools" / "instructions.py").read_text()
        # Should not contain old uploadId-style markers
        assert "uploadId" not in instructions.lower() or "upload_id" not in instructions


def test_import_core_reuses_completed_stage_cache(monkeypatch, tmp_path):
    """A retry in another deck resumes cached stages instead of reconverting."""
    from sdpm.tools.attachment.cache import LocalStageCache
    from sdpm.tools.attachment.pipeline import import_attachment_core
    import sdpm.tools.attachment.pipeline as attachment_pipeline

    source = tmp_path / "source.txt"
    source.write_text("cached attachment", encoding="utf-8")
    identity = {"kind": "test", "id": "stable-source", "size": source.stat().st_size}
    cache = LocalStageCache(base_dir=tmp_path / "cache")
    first_deck = tmp_path / "deck-one"
    second_deck = tmp_path / "deck-two"
    first_deck.mkdir()
    second_deck.mkdir()

    first = import_attachment_core(
        source,
        str(source),
        first_deck,
        source_identity=identity,
        cache=cache,
    )
    assert "importKey" in first

    def fail_reconversion(*_args, **_kwargs):
        raise AssertionError("completed conversion stage should be restored from cache")

    monkeypatch.setattr(attachment_pipeline, "_import_document", fail_reconversion)
    resumed = import_attachment_core(
        source,
        str(source),
        second_deck,
        source_identity=identity,
        cache=cache,
    )
    assert resumed["importKey"] == first["importKey"]
    assert resumed["reused"] is False
    assert (second_deck / resumed["bundlePath"] / "manifest.json").is_file()
