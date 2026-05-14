# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Presentation backend — LibreOffice headless."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_WORK_DIR_NAME = "_work"


def _is_wsl() -> bool:
    return Path("/proc/version").exists() and "microsoft" in Path("/proc/version").read_text().lower()


def get_work_dir(project_path: Path | None = None) -> Path:
    """Return a working directory for temp files.

    When *project_path* is given, creates ``<project_path>/_work/`` to keep
    temp files inside the project — avoids macOS EDR/DLP blocking system temp
    paths (``/private/var/folders/...``).

    When *project_path* is None, falls back to the system temp directory.
    """
    if project_path is not None:
        d = project_path / _WORK_DIR_NAME
    else:
        d = Path(tempfile.gettempdir())
    d.mkdir(parents=True, exist_ok=True)
    return d


class LibreOfficeBackend:
    """LibreOffice headless backend for PDF/SVG export."""

    name = "libreoffice"

    def __init__(self, soffice_path: str = "soffice"):
        self._soffice = soffice_path

    def _make_cmd(self, fmt: str, outdir: str, pptx_path: Path) -> tuple[list[str], dict[str, str]]:
        """Build command and env for LibreOffice conversion."""
        env = os.environ.copy()
        cmd = [self._soffice, "--headless", "--convert-to", fmt, "--outdir", outdir]
        if sys.platform == "win32":
            cmd.append(f"-env:UserInstallation=file:///{outdir.replace(os.sep, '/')}")
        else:
            env["HOME"] = outdir
        cmd.append(str(pptx_path))
        return cmd, env

    def export_pdf(self, pptx_path: Path, pdf_path: Path, work_dir: Path | None = None) -> bool:
        """Export PPTX to PDF. Returns True on success."""
        base = work_dir or get_work_dir()
        tmp_dir = tempfile.mkdtemp(dir=base)
        try:
            cmd, env = self._make_cmd("pdf", tmp_dir, pptx_path)
            subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
                cmd, env=env, capture_output=True, text=True, timeout=120, check=True, stdin=subprocess.DEVNULL,
            )
            tmp_pdf = Path(tmp_dir) / (pptx_path.stem + ".pdf")
            if tmp_pdf.exists():
                shutil.move(str(tmp_pdf), str(pdf_path))
                return True
            return False
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return False
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def export_svg(self, pptx_path: Path, work_dir: Path | None = None) -> Path | None:
        """Export PPTX to SVG. Returns temp SVG path or None on failure.

        Caller is responsible for cleaning up the parent directory.
        """
        base = work_dir or get_work_dir()
        tmp_dir = tempfile.mkdtemp(dir=base)
        try:
            cmd, env = self._make_cmd("svg", tmp_dir, pptx_path)
            subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
                cmd, env=env, capture_output=True, text=True, timeout=120, check=True, stdin=subprocess.DEVNULL,
            )
            tmp_svg = Path(tmp_dir) / (pptx_path.stem + ".svg")
            if tmp_svg.exists():
                return tmp_svg
            return None
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None


def detect_backend() -> LibreOfficeBackend | None:
    """Return LibreOffice backend if available."""
    if shutil.which("soffice") is not None:
        return LibreOfficeBackend()
    # Windows: LibreOffice is typically not on PATH
    win_lo = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
    if win_lo.exists():
        return LibreOfficeBackend(soffice_path=str(win_lo))
    return None
