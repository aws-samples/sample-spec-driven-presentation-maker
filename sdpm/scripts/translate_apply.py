#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Apply translations from a derived deck's translation_map.json.

Usage::

    uv run python3 scripts/translate_apply.py {deck_dir} [--dry-run]

Reads ``{deck_dir}/translate/translation_map.json`` and rewrites each
``{deck_dir}/slides/*.json`` in place, replacing translatable strings whose
key exists in the dictionary (and whose value is non-empty).

Structural attributes (layout, type, shape, src, fontColor, fontFamily, etc.)
are never touched. ``\x0b`` (vertical tab) is preserved because the map file
round-trips via ``json``.

Entire-paragraph gradients sync on a best-effort basis: when a paragraph
carries ``_textGradientRuns`` whose concatenated text equals the paragraph's
pre-translation ``text`` AND all runs share the same gradient, the runs are
collapsed into a single run carrying the translated text. Multi-gradient
runs and partial paragraph gradients cannot be re-segmented reliably after
translation — they are left unchanged with a warning, and the operator must
adjust the runs manually.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Keep in sync with translate_extract.py.
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


def _translate_string(
    value: str, dictionary: dict[str, str], counter: dict[str, int],
) -> str:
    """Return the translation when the key exists and value is non-empty."""
    if not isinstance(value, str):
        return value
    replacement = dictionary.get(value)
    if replacement:  # non-empty string means "translate"
        counter["replaced"] = counter.get("replaced", 0) + 1
        return replacement
    return value


def _apply(
    node, dictionary: dict[str, str], counter: dict[str, int],
):
    """Recursively rewrite translatable strings in-place and return node."""
    if isinstance(node, dict):
        # Capture the pre-translation paragraph text: _sync_gradient_runs
        # must decide "did the runs span the entire paragraph?" against the
        # ORIGINAL text (comparing against the translated text is meaningless).
        original_text = node.get("text") if isinstance(node.get("text"), str) else None
        for key, value in list(node.items()):
            if key in _SKIP_KEYS:
                continue
            if key == "_textGradientRuns":
                continue  # auto-synced later at paragraph level
            if isinstance(value, str):
                if key in _TRANSLATABLE_KEYS:
                    node[key] = _translate_string(value, dictionary, counter)
            elif isinstance(value, list):
                if key == "items":
                    node[key] = [
                        _translate_string(item, dictionary, counter)
                        if isinstance(item, str) else _apply(item, dictionary, counter)
                        for item in value
                    ]
                elif key == "headers":
                    node[key] = [
                        _translate_string(cell, dictionary, counter)
                        if isinstance(cell, str)
                        else _apply(cell, dictionary, counter) if isinstance(cell, dict) else cell
                        for cell in value
                    ]
                elif key == "rows":
                    new_rows = []
                    for row in value:
                        if isinstance(row, list):
                            new_rows.append([
                                _translate_string(cell, dictionary, counter)
                                if isinstance(cell, str)
                                else _apply(cell, dictionary, counter) if isinstance(cell, dict) else cell
                                for cell in row
                            ])
                        else:
                            new_rows.append(row)
                    node[key] = new_rows
                else:
                    for child in value:
                        _apply(child, dictionary, counter)
            elif isinstance(value, dict):
                _apply(value, dictionary, counter)
        _sync_gradient_runs(node, original_text)
    elif isinstance(node, list):
        for child in node:
            _apply(child, dictionary, counter)
    return node


def _sync_gradient_runs(node: dict, original_text: str | None) -> None:
    """Best-effort sync of ``_textGradientRuns`` after paragraph translation.

    The builder re-applies per-run gradients by EXACT text match
    (``_apply_text_gradient_runs``), so stale run texts silently lose their
    gradient in the built PPTX. Sync is only attempted when the runs
    originally spanned the entire paragraph — their concatenation equals the
    pre-translation ``text``:

    - All runs share the same gradient → collapse to a single run carrying
      the translated text (visually identical: whole paragraph, one gradient).
    - Runs carry different gradients → left unchanged and a warning is
      printed; translation moves word boundaries, so there is no reliable
      re-segmentation. The operator must adjust the runs manually.

    Partial-paragraph gradients are always left unchanged (with a warning
    when the paragraph was translated), never expanded to the whole text.
    """
    runs = node.get("_textGradientRuns")
    text = node.get("text")
    if not isinstance(runs, list) or not isinstance(text, str) or original_text is None:
        return
    if not all(isinstance(r, dict) and isinstance(r.get("text", ""), str) for r in runs):
        return
    if text == original_text:
        return  # paragraph not translated; runs still in sync
    run_concat = "".join(r.get("text", "") for r in runs)
    if not run_concat or run_concat != original_text:
        # Partial-paragraph gradient: the run texts no longer occur in the
        # translated paragraph, so the gradient will not re-apply on build.
        print(
            "WARNING: partial-paragraph gradient runs left unsynced for "
            f"translated text {text[:40]!r} — adjust _textGradientRuns manually.",
            file=sys.stderr,
        )
        return
    gradients = {json.dumps(r.get("gradient"), sort_keys=True) for r in runs}
    if len(gradients) == 1:
        node["_textGradientRuns"] = [{"text": text, "gradient": runs[0].get("gradient")}]
    else:
        print(
            "WARNING: multi-gradient runs spanning the paragraph could not be "
            f"synced for translated text {text[:40]!r} — adjust "
            "_textGradientRuns manually.",
            file=sys.stderr,
        )


def _diff_summary(before: dict, after: dict) -> list[tuple[str, str]]:
    """Flatten-diff translatable strings for --dry-run reporting."""
    changes: list[tuple[str, str]] = []

    def walk(b, a):
        if isinstance(b, dict) and isinstance(a, dict):
            for k in b.keys() | a.keys():
                if k in _SKIP_KEYS or k == "_textGradientRuns":
                    continue
                if isinstance(b.get(k), str) and isinstance(a.get(k), str):
                    if b[k] != a[k] and k in _TRANSLATABLE_KEYS:
                        changes.append((b[k], a[k]))
                elif isinstance(b.get(k), list) and isinstance(a.get(k), list):
                    for bi, ai in zip(b[k], a[k]):
                        if isinstance(bi, str) and isinstance(ai, str):
                            if bi != ai:
                                changes.append((bi, ai))
                        else:
                            walk(bi, ai)
                elif isinstance(b.get(k), dict) and isinstance(a.get(k), dict):
                    walk(b[k], a[k])
        elif isinstance(b, list) and isinstance(a, list):
            for bi, ai in zip(b, a):
                walk(bi, ai)

    walk(before, after)
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply translations from a derived deck's translation_map.json.",
    )
    parser.add_argument("deck_dir", help="Path to the derived deck directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the diff without modifying any files",
    )
    args = parser.parse_args()

    deck = Path(args.deck_dir).resolve()
    if not deck.is_dir():
        print(f"Error: deck directory not found: {deck}", file=sys.stderr)
        return 1

    map_path = deck / "translate" / "translation_map.json"
    if not map_path.exists():
        print(f"Error: {map_path} not found", file=sys.stderr)
        return 1

    try:
        dictionary: dict[str, str] = json.loads(map_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error: failed to parse translation_map.json: {e}", file=sys.stderr)
        return 1
    if not isinstance(dictionary, dict):
        print("Error: translation_map.json must be a JSON object", file=sys.stderr)
        return 1

    slides_dir = deck / "slides"
    if not slides_dir.is_dir():
        print(f"Error: {slides_dir} not found", file=sys.stderr)
        return 1

    total_changes = 0
    for slide_file in sorted(slides_dir.glob("*.json")):
        try:
            data_text = slide_file.read_text(encoding="utf-8")
            data = json.loads(data_text)
        except Exception as e:
            print(f"Warning: failed to parse {slide_file.name}: {e}", file=sys.stderr)
            continue
        counter: dict[str, int] = {}
        # Work on a deep copy so dry-run diffs are accurate.
        after = json.loads(data_text)
        _apply(after, dictionary, counter)

        if args.dry_run:
            diffs = _diff_summary(data, after)
            if diffs:
                print(f"{slide_file.name}: {len(diffs)} change(s)")
                for before, now in diffs[:3]:
                    # Truncate for readability.
                    b = before if len(before) <= 60 else before[:57] + "..."
                    n = now if len(now) <= 60 else now[:57] + "..."
                    print(f"  - {b!r} → {n!r}")
                if len(diffs) > 3:
                    print(f"  - ... ({len(diffs) - 3} more)")
                total_changes += len(diffs)
        else:
            slide_file.write_text(
                json.dumps(after, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if counter.get("replaced"):
                total_changes += counter["replaced"]

    if args.dry_run:
        print(f"\n[dry-run] {total_changes} replacement(s) — no files modified.")
    else:
        print(f"Applied {total_changes} replacement(s) in-place.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
