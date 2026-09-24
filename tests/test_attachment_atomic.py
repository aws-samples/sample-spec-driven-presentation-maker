# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for sdpm.tools.attachment.atomic and the lock-free publish path (#385).

The local stage cache used to depend on the POSIX-only ``fcntl`` module and on
opening directories for fsync — both fail on native Windows. These tests pin the
replacement: a single ``publish_directory`` primitive shared by the stage cache
and the bundle committer, with first-writer-wins semantics and no lock file.
"""

from __future__ import annotations

import hashlib
import importlib
import os
import sys
from pathlib import Path

import pytest

from sdpm.tools.attachment import atomic
from sdpm.tools.attachment.atomic import fsync_tree, publish_directory


def _make_staging(root: Path, name: str, content: bytes = b"hello") -> Path:
    staging = root / name
    (staging / "nested").mkdir(parents=True)
    (staging / "nested" / "file.txt").write_bytes(content)
    (staging / "complete.json").write_text("{}", encoding="utf-8")
    return staging


class TestPublishDirectory:
    def test_publishes_fresh_target(self, tmp_path: Path):
        staging = _make_staging(tmp_path, ".staging-a")
        target = tmp_path / "out" / "target"

        result = publish_directory(staging, target, reuse_existing=lambda: pytest.fail("not called"))

        assert result == target
        assert (target / "nested" / "file.txt").read_bytes() == b"hello"
        assert not staging.exists()

    def test_reuses_valid_existing_target(self, tmp_path: Path):
        target = _make_staging(tmp_path, "target", b"winner")
        staging = _make_staging(tmp_path, ".staging-b", b"loser")

        result = publish_directory(staging, target, reuse_existing=lambda: True)

        assert result == target
        assert (target / "nested" / "file.txt").read_bytes() == b"winner"
        assert not staging.exists()

    def test_replaces_corrupt_existing_target(self, tmp_path: Path):
        target = tmp_path / "target"
        target.mkdir()
        (target / "garbage").write_text("x")
        staging = _make_staging(tmp_path, ".staging-c", b"fresh")

        result = publish_directory(staging, target, reuse_existing=lambda: False)

        assert result == target
        assert (target / "nested" / "file.txt").read_bytes() == b"fresh"
        assert not (target / "garbage").exists()

    def test_loser_reconciles_when_rename_fails(self, tmp_path: Path, monkeypatch):
        """Another writer publishes between our existence check and rename."""
        target = tmp_path / "target"
        staging = _make_staging(tmp_path, ".staging-d", b"loser")
        calls: list[str] = []

        def racing_rename(src: str, dst: str) -> None:
            # Simulate the winner landing first, then our rename failing as on
            # Windows (FileExistsError) / POSIX (ENOTEMPTY).
            _make_staging(tmp_path, "target", b"winner")
            raise FileExistsError(src, dst)

        monkeypatch.setattr(atomic.os, "rename", racing_rename)

        def reuse_existing() -> bool:
            calls.append("verify")
            return (target / "nested" / "file.txt").read_bytes() == b"winner"

        result = publish_directory(staging, target, reuse_existing=reuse_existing)

        assert result == target
        assert calls == ["verify"]
        assert (target / "nested" / "file.txt").read_bytes() == b"winner"
        assert not staging.exists()

    def test_rename_failure_without_valid_winner_raises_and_cleans_staging(
        self, tmp_path: Path, monkeypatch
    ):
        target = tmp_path / "target"
        staging = _make_staging(tmp_path, ".staging-e")

        def failing_rename(src: str, dst: str) -> None:
            raise PermissionError(src, dst)

        monkeypatch.setattr(atomic.os, "rename", failing_rename)

        with pytest.raises(PermissionError):
            publish_directory(staging, target, reuse_existing=lambda: False)

        assert not staging.exists()
        assert not target.exists()

    def test_conflict_raised_by_callback_propagates_and_cleans_staging(self, tmp_path: Path):
        target = _make_staging(tmp_path, "target", b"other")
        staging = _make_staging(tmp_path, ".staging-f")

        class Conflict(Exception):
            pass

        def conflict() -> bool:
            raise Conflict()

        with pytest.raises(Conflict):
            publish_directory(staging, target, reuse_existing=conflict)

        assert not staging.exists()
        assert (target / "nested" / "file.txt").read_bytes() == b"other"


class TestFsyncTree:
    def test_fsyncs_files_and_directories_on_posix(self, tmp_path: Path, monkeypatch):
        staging = _make_staging(tmp_path, "tree")
        opened: list[Path] = []
        real_open = os.open

        def spy_open(path, flags, *args, **kwargs):
            opened.append(Path(path))
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(atomic, "_CAN_FSYNC_DIRECTORY", True)
        monkeypatch.setattr(atomic.os, "open", spy_open)

        fsync_tree(staging)

        assert staging / "nested" / "file.txt" in opened
        assert staging / "nested" in opened
        assert staging in opened
        # Directories are synced deepest-first, after files
        assert opened.index(staging / "nested") < opened.index(staging)

    def test_skips_directory_fsync_on_windows(self, tmp_path: Path, monkeypatch):
        """Windows cannot os.open() a directory; only files may be fsynced there."""
        staging = _make_staging(tmp_path, "tree")
        opened: list[Path] = []
        real_open = os.open

        def guarded_open(path, flags, *args, **kwargs):
            if Path(path).is_dir():
                raise PermissionError(13, "Permission denied", str(path))
            opened.append(Path(path))
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(atomic, "_CAN_FSYNC_DIRECTORY", False)
        monkeypatch.setattr(atomic.os, "open", guarded_open)

        fsync_tree(staging)  # must not raise

        assert opened == [p for p in opened if p.is_file()]
        assert staging / "nested" / "file.txt" in opened

    def test_platform_flag_matches_sys_platform(self):
        assert atomic._CAN_FSYNC_DIRECTORY == (sys.platform != "win32")


class TestNoPosixOnlyImports:
    def test_attachment_modules_import_without_fcntl(self, monkeypatch):
        """Regression for #385: native Windows has no ``fcntl`` module."""
        monkeypatch.setitem(sys.modules, "fcntl", None)
        for name in (
            "sdpm.tools.attachment.atomic",
            "sdpm.tools.attachment.cache",
            "sdpm.tools.attachment.bundle",
        ):
            importlib.reload(importlib.import_module(name))

    def test_no_fcntl_reference_in_sdpm_package(self):
        package_root = Path(atomic.__file__).resolve().parents[2]
        offenders = [
            path
            for path in package_root.rglob("*.py")
            if "fcntl" in path.read_text(encoding="utf-8")
        ]
        assert offenders == []


class TestStageCacheUsesPrimitive:
    def test_concurrent_publish_of_same_stage_reuses_winner(self, tmp_path: Path):
        from sdpm.tools.attachment.cache import (
            LocalStageCache,
            StageRecord,
            compute_pipeline_key,
        )

        cache = LocalStageCache(base_dir=tmp_path / "cache")
        payload = b"hello"
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()
        (outputs_dir / "result.txt").write_bytes(payload)
        record = StageRecord(
            stage="extract_text",
            source_identity_hash="src1",
            source_hash="sha1",
            pipeline_version="0.9.0:attachment-1",
            options_hash="opts1",
            outputs=[{
                "path": "result.txt",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "contentType": "text/plain",
            }],
            completed_at="2026-09-24T00:00:00Z",
        )
        pipeline_key = compute_pipeline_key(record.pipeline_version, record.options_hash)

        first = cache.publish_stage("src1", pipeline_key, "extract_text", "k", record, outputs_dir)
        second = cache.publish_stage("src1", pipeline_key, "extract_text", "k", record, outputs_dir)

        assert first == second
        assert cache.get_stage("src1", pipeline_key, "extract_text", "k") is not None
        # No lock files or staging leftovers next to the target
        leftovers = [p.name for p in first.parent.iterdir() if p != first]
        assert leftovers == []
