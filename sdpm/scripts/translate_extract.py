#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Extract translatable text from a deck and scaffold a derived deck.

Workflow::

    uv run python3 scripts/translate_extract.py {deck_dir} \\
        --target-lang ja \\
        [--skip-short N] \\
        [--output-dir <path>]

Creates a derived deck ``{deck_dir}-{lang}/`` (or the path given via
``--output-dir``) containing copies of the source deck plus a
``translate/`` sub-directory with an empty dictionary template
(``translation_map.json``) and a review-oriented TSV dump
(``texts.tsv``).

The original deck is untouched.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

# Copied verbatim to keep the script self-contained (no sdpm.* imports
# beyond the standard library). Keep in sync with translate_apply.py.
_TRANSLATABLE_KEYS = {
    "text",
    "subtitle",
    "title",
    "date",
    "label",
    "notes",
}
_SKIP_KEYS = {
    "layout",
    "type",
    "shape",
    "preset",
    "connectorType",
    "src",
    "masterIndex",
    "fontFamily",
    "fontColor",
    "fill",
    "color",
    "fontSize",
    "opacity",
    "align",
    "verticalAlign",
    "id",
    "x",
    "y",
    "width",
    "height",
    "defaultTextColor",
    "background",
    "template",
}
# Directories/files NOT copied to the derived deck.
_SKIP_COPY = {"output.pptx", "preview", "compose", "translate"}


def _is_translatable_string(value: str, skip_short: int) -> bool:
    """True when the string should be included in the dictionary template."""
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return False
    if len(stripped) <= skip_short:
        return False
    if stripped.startswith(("http://", "https://")):
        return False
    return True


def _collect(node: object, out: dict[str, None], skip_short: int) -> None:
    """Walk a slide dict/list and collect translatable strings as keys."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _SKIP_KEYS:
                continue
            if key == "_textGradientRuns":
                # Auto-synced by translate_apply when the whole paragraph
                # carries the gradient; not a primary extraction target.
                continue
            if isinstance(value, str):
                if key in _TRANSLATABLE_KEYS and _is_translatable_string(value, skip_short):
                    out.setdefault(value, None)
            elif isinstance(value, list):
                if key == "items":
                    for item in value:
                        if isinstance(item, str) and _is_translatable_string(item, skip_short):
                            out.setdefault(item, None)
                        else:
                            _collect(item, out, skip_short)
                elif key == "headers":
                    for cell in value:
                        if isinstance(cell, str) and _is_translatable_string(cell, skip_short):
                            out.setdefault(cell, None)
                        elif isinstance(cell, dict):
                            _collect(cell, out, skip_short)
                elif key == "rows":
                    for row in value:
                        if isinstance(row, list):
                            for cell in row:
                                if isinstance(cell, str) and _is_translatable_string(cell, skip_short):
                                    out.setdefault(cell, None)
                                elif isinstance(cell, dict):
                                    _collect(cell, out, skip_short)
                else:
                    for child in value:
                        _collect(child, out, skip_short)
            elif isinstance(value, dict):
                _collect(value, out, skip_short)
    elif isinstance(node, list):
        for child in node:
            _collect(child, out, skip_short)


def _copy_deck(src: Path, dst: Path) -> None:
    """Copy the source deck to the derived location, skipping generated files."""
    dst.mkdir(parents=True)
    for entry in src.iterdir():
        if entry.name in _SKIP_COPY:
            continue
        target = dst / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target)
        else:
            shutil.copy2(entry, target)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold a derived translated deck by extracting translatable strings.",
    )
    parser.add_argument("deck_dir", help="Path to the source deck directory")
    parser.add_argument(
        "--target-lang",
        required=True,
        help="Target language code (appended to derived-deck name)",
    )
    parser.add_argument(
        "--skip-short",
        type=int,
        default=0,
        help="Exclude text of this many characters or fewer (default: 0 = keep all)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override derived-deck path (default: {deck_dir}-{target-lang})",
    )
    args = parser.parse_args()

    src = Path(args.deck_dir).resolve()
    if not src.is_dir():
        print(f"Error: deck directory not found: {src}", file=sys.stderr)
        return 1
    if not (src / "deck.json").exists():
        print(f"Error: {src}/deck.json not found — is this a deck directory?", file=sys.stderr)
        return 1

    if args.output_dir:
        dst = Path(args.output_dir).resolve()
    else:
        dst = src.parent / f"{src.name}-{args.target_lang}"

    if dst.exists():
        print(
            f"Error: derived deck already exists: {dst}\n"
            f"  Remove it or pick a different --output-dir / --target-lang.",
            file=sys.stderr,
        )
        return 1

    _copy_deck(src, dst)

    # Walk slides/*.json in the derived deck and collect translatable text.
    collected: dict[str, None] = {}
    slides_dir = dst / "slides"
    if slides_dir.is_dir():
        for slide_file in sorted(slides_dir.glob("*.json")):
            try:
                data = json.loads(slide_file.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"Warning: failed to parse {slide_file.name}: {e}", file=sys.stderr)
                continue
            _collect(data, collected, args.skip_short)

    # Write translate/translation_map.json (empty values) + texts.tsv.
    translate_dir = dst / "translate"
    translate_dir.mkdir()
    dictionary = {text: "" for text in collected}
    (translate_dir / "translation_map.json").write_text(
        json.dumps(dictionary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (translate_dir / "texts.tsv").open("w", encoding="utf-8") as tsv:
        tsv.write("text\n")
        for text in collected:
            # TSV: single column, preserve tabs/newlines as literal escapes for review.
            tsv.write(
                text.replace("\t", "\\t").replace("\n", "\\n").replace("\x0b", "\\v") + "\n"
            )

    print(f"Derived deck created: {dst}")
    print(f"  translate/translation_map.json ({len(dictionary)} entries)")
    print("  translate/texts.tsv (review copy)")
    print()
    print("Next steps:")
    print(f"  1. Fill values in {dst}/translate/translation_map.json")
    print(f"  2. uv run python3 scripts/translate_apply.py {dst} --dry-run")
    print(f"  3. uv run python3 scripts/translate_apply.py {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
