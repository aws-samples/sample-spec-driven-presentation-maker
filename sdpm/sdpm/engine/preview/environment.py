# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Which preview dependencies this machine has, and the one command that installs the rest.

Previews need LibreOffice (PPTX → PDF/SVG) and poppler (PDF → PNG). Both are
optional: decks build without them. When they are missing, the tool that needed
them reports it in its result — at the point of need, once — instead of failing
or nagging elsewhere.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

_SOFFICE_CANDIDATES = (
    Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
    Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
)

_INSTALL = {
    "darwin": {
        "libreoffice": "brew install --cask libreoffice",
        "poppler": "brew install poppler",
    },
    "linux": {
        "libreoffice": "sudo apt-get install -y libreoffice-impress",
        "poppler": "sudo apt-get install -y poppler-utils",
    },
    "win32": {
        "libreoffice": "winget install --id TheDocumentFoundation.LibreOffice",
        "poppler": "winget install --id oschwartz10612.Poppler",
    },
}


def soffice_path() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    for candidate in _SOFFICE_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None


def preview_environment(platform: str = sys.platform) -> dict:
    """``{"available": bool, "missing": [...], "install": "cmd && cmd"}`` for this machine.

    ``install`` is a single shell line for the current OS (or the SDPM installer's
    dependency mode when the OS is unknown). Empty ``missing`` means previews work.
    """
    missing = []
    if soffice_path() is None:
        missing.append("libreoffice")
    if shutil.which("pdftoppm") is None:
        missing.append("poppler")
    key = "linux" if platform.startswith("linux") else platform
    hints = _INSTALL.get(key)
    if missing and hints:
        install = " && ".join(hints[m] for m in missing)
    elif missing:
        install = "install LibreOffice and poppler (pdftoppm) and put them on PATH"
    else:
        install = ""
    return {"available": not missing, "missing": missing, "install": install}


def preview_unavailable(platform: str = sys.platform) -> dict | None:
    """The structured result a tool returns when previews cannot be produced, else None."""
    env = preview_environment(platform)
    if env["available"]:
        return None
    return {
        "status": "unavailable",
        "missing": env["missing"],
        "install": env["install"],
        "note": "Slides were built; only PNG previews are skipped. Install the missing tools "
                "(or rerun the SDPM installer) to get previews.",
    }
