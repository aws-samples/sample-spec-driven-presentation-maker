# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Regenerate the pre-converted HTML-mode artifacts of the bundled templates.

Writes ``sdpm/templates/html/<stem>/`` (theme.css, template.json, layouts/*.svg)
for blank-light and blank-dark. Run it whenever one of those .pptx files or
``sdpm.engine.html.template.CONVERTER_VERSION`` changes, then commit the result
(tests/test_html_template.py fails on drift). Needs LibreOffice and poppler for
the decoration SVGs.

Usage:
    uv run python scripts/build_bundled_template_html.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

from sdpm.config import TEMPLATES_DIR
from sdpm.engine.html.template import load_template_html, template_json_text

BUNDLED = ("blank-light", "blank-dark")


def build(stem: str, out_root: Path) -> Path:
    template = TEMPLATES_DIR / f"{stem}.pptx"
    with tempfile.TemporaryDirectory(prefix="sdpm-bundle-") as tmp:
        converted = load_template_html(
            template, decorations=True,
            cache_root=Path(tmp) / "cache", bundled_root=Path(tmp) / "no-bundle",
        )
        if converted.decorations_status is not None:
            raise SystemExit(f"{stem}: decoration render unavailable: {converted.decorations_status}")
        out = out_root / stem
        if out.exists():
            shutil.rmtree(out)
        (out / "layouts").mkdir(parents=True)
        (out / "theme.css").write_text(converted.theme_css, encoding="utf-8", newline="\n")
        (out / "template.json").write_text(template_json_text(converted.info), encoding="utf-8", newline="\n")
        for svg in sorted((converted.dir / "layouts").glob("*.svg")):
            shutil.copyfile(svg, out / "layouts" / svg.name)
    return out


def main() -> int:
    out_root = TEMPLATES_DIR / "html"
    for stem in BUNDLED:
        out = build(stem, out_root)
        print(f"{stem}: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
