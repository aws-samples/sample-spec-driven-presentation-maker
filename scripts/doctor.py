# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Environment doctor for local use — diagnoses common setup problems.

Checks:
- required commands: uv (server runtime), LibreOffice + poppler (previews)
- checkout integrity: the path anchors in sdpm.config resolve to real
  directories (catches a moved/renamed checkout, the most common breakage)

Run: make doctor
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdpm"))

OK, NG, WARN = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m!\033[0m"


def main() -> int:
    failures = 0

    # --- commands ---
    print("Commands:")
    if shutil.which("uv"):
        print(f"  {OK} uv — {shutil.which('uv')}")
    else:
        failures += 1
        print(f"  {NG} uv not found — required to run the local server.")
        print("      Install: https://docs.astral.sh/uv/")

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        print(f"  {OK} LibreOffice — {soffice}")
    else:
        print(f"  {WARN} LibreOffice not found — slide previews (PNG) will not render.")
        print("      macOS: brew install --cask libreoffice / Linux: apt install libreoffice")

    if shutil.which("pdftoppm"):
        print(f"  {OK} poppler (pdftoppm) — {shutil.which('pdftoppm')}")
    else:
        print(f"  {WARN} poppler not found — slide previews (PNG) will not render.")
        print("      macOS: brew install poppler / Linux: apt install poppler-utils")

    # --- checkout integrity ---
    print("Checkout:")
    try:
        from sdpm import config
    except ImportError as e:
        print(f"  {NG} cannot import sdpm.config: {e}")
        print("      Are you running from the repository root? (make doctor)")
        return 1

    anchors = {
        "SKILL_ROOT": config.SKILL_ROOT,
        "REFERENCES_DIR": config.REFERENCES_DIR,
        "TEMPLATES_DIR": config.TEMPLATES_DIR,
        "PERSONAS_DIR": config.PERSONAS_DIR,
    }
    for name, path in anchors.items():
        if path.is_dir():
            print(f"  {OK} {name} — {path}")
        else:
            failures += 1
            print(f"  {NG} {name} missing — {path}")

    if any(not p.is_dir() for p in anchors.values()):
        print(
            "\n  Hint: if you moved or renamed this checkout, MCP client configs\n"
            "  still point at the old path — re-register the server (e.g.\n"
            "  `make install-kiro`) or set SDPM_SKILL_ROOT to the new sdpm/ path."
        )

    print()
    if failures:
        print(f"doctor: {failures} problem(s) found")
        return 1
    print("doctor: all required checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
