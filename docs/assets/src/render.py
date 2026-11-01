# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Render the documentation diagrams in docs/assets/ from their deck sources.

Each subdirectory of docs/assets/src/ that holds an out.json is one diagram, written as a
small sdpm deck:

    <name>/deck.json            deck metadata (template, fonts, colours)
    <name>/specs/outline.md     slide order (one slide)
    <name>/slides/<slug>.json   the slide; translatable text is written as {{key}}
    <name>/strings.<lang>.json  {key: text} per language; "_fonts" replaces deck.json fonts
    <name>/out.json             {"<lang>": "docs/assets/<file>.png", ...}

For every language in out.json the deck is copied to a temporary directory, the strings are
filled in, generate_pptx builds the deck, and LibreOffice (the preview backend) exports it
to PDF. pdftoppm rasterises the page at 1920 px and the white margin is trimmed to a 24 px
border.

Usage (from the repository root):
    uv run python docs/assets/src/render.py            # all diagrams
    uv run python docs/assets/src/render.py workflow   # one or more by name
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

SRC = Path(__file__).resolve().parent
REPO = SRC.parents[2]
BUILDER = REPO / "sdpm" / "scripts" / "pptx_builder.py"
KEY = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
MARGIN = 24
WIDTH = 1920

sys.path.insert(0, str(REPO / "sdpm"))


def diagrams() -> list[str]:
    """Names of all diagram source directories."""
    return sorted(p.name for p in SRC.iterdir() if (p / "out.json").is_file())


def fill(text: str, strings: dict[str, str], where: str, as_json: bool) -> str:
    """Replace {{key}} with its string; styled-text tags like {{bold:x}} are left alone."""

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in strings:
            raise SystemExit(f"{where}: no string for {{{{{key}}}}}")
        value = strings[key]
        return json.dumps(value, ensure_ascii=False)[1:-1] if as_json else value

    return KEY.sub(sub, text)


def run(cmd: list[str]) -> str:
    """Run a command from the repository root; exit with its output on failure."""
    res = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)  # nosec B603
    if res.returncode != 0:
        raise SystemExit(f"failed: {' '.join(cmd)}\n{res.stdout}\n{res.stderr}")
    return res.stdout + res.stderr


def trim(png: Path, out: Path) -> None:
    """Crop to the drawn content plus MARGIN px of the background colour."""
    img = Image.open(png).convert("RGB")
    bg = Image.new("RGB", img.size, img.getpixel((2, 2)))
    box = ImageChops.difference(img, bg).point(lambda v: 255 if v > 8 else 0).getbbox()
    if box:
        left, top, right, bottom = box
        img = img.crop(
            (
                max(0, left - MARGIN),
                max(0, top - MARGIN),
                min(img.width, right + MARGIN),
                min(img.height, bottom + MARGIN),
            )
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    # Flat colours: a 256-colour palette keeps text crisp and halves the file size.
    img = img.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    img.save(out, optimize=True)


def render(name: str, keep: str | None = None) -> None:
    from sdpm.engine.preview import export_pdf

    src = SRC / name
    targets = json.loads((src / "out.json").read_text(encoding="utf-8"))
    for lang, target in targets.items():
        strings = json.loads((src / f"strings.{lang}.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix=f"sdpm-diagram-{name}-") as tmp:
            deck = Path(tmp) / name
            shutil.copytree(src, deck, ignore=shutil.ignore_patterns("strings.*.json", "out.json"))
            for f in [*deck.rglob("*.json"), *deck.rglob("*.md")]:
                f.write_text(
                    fill(f.read_text(encoding="utf-8"), strings, f"{name}/{f.name}", as_json=f.suffix == ".json"),
                    encoding="utf-8",
                )
            if "_fonts" in strings:
                meta = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
                meta["fonts"] = strings["_fonts"]
                (deck / "deck.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            pptx = Path(tmp) / "out.pptx"
            for line in run([sys.executable, str(BUILDER), "generate_pptx", str(deck), "-o", str(pptx)]).splitlines():
                # The layout-bias check judges a slide's balance; the PNG is trimmed, so skip it.
                skip = ("Generated:", "page01", "Layout bias", "MUST FIX unless")
                if line.strip() and not any(k in line for k in skip):
                    print(f"  {name}/{lang} generate_pptx: {line.strip()}")
            pdf = Path(tmp) / "out.pdf"
            if not export_pdf(pptx, pdf, work_dir=Path(tmp)):
                raise SystemExit("PDF export failed: LibreOffice (soffice) is required")
            run(["pdftoppm", "-png", "-singlefile", "-scale-to", str(WIDTH), str(pdf), str(Path(tmp) / "page")])
            out = REPO / target
            trim(Path(tmp) / "page.png", out)
            if keep:
                shutil.copy(pptx, Path(keep) / f"{name}-{lang}.pptx")
        print(f"{name}/{lang} -> {target} ({out.stat().st_size // 1024} KB)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help=f"diagrams to render (default: all of {diagrams()})")
    parser.add_argument("--keep-pptx", metavar="DIR", help="also copy each built .pptx into DIR")
    args = parser.parse_args()
    for name in args.names or diagrams():
        if not (SRC / name / "out.json").is_file():
            raise SystemExit(f"unknown diagram: {name} (have {diagrams()})")
        render(name, args.keep_pptx)


if __name__ == "__main__":
    main()
