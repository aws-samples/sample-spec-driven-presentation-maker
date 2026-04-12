# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Presentation backend — LibreOffice headless."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _is_wsl() -> bool:
    return Path("/proc/version").exists() and "microsoft" in Path("/proc/version").read_text().lower()


class LibreOfficeBackend:
    """LibreOffice headless backend for PDF/SVG export."""

    name = "libreoffice"

    def export_pdf(self, pptx_path: Path, pdf_path: Path) -> bool:
        """Export PPTX to PDF. Returns True on success."""
        tmp_dir = tempfile.mkdtemp()
        try:
            env = os.environ.copy()
            env["HOME"] = tmp_dir
            subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
                ["soffice", "--headless", "--convert-to", "pdf", "--outdir", tmp_dir, str(pptx_path)],
                env=env, capture_output=True, text=True, timeout=120, check=True,
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

    def export_svg(self, pptx_path: Path) -> Path | None:
        """Export PPTX to SVG. Returns temp SVG path or None on failure.

        Caller is responsible for cleaning up the parent directory.
        """
        tmp_dir = tempfile.mkdtemp()
        try:
            env = os.environ.copy()
            env["HOME"] = tmp_dir
            subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
                ["soffice", "--headless", "--convert-to", "svg", "--outdir", tmp_dir, str(pptx_path)],
                env=env, capture_output=True, text=True, timeout=120, check=True,
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
    return None
