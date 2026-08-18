# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for translate_extract.py / translate_apply.py (deck-structure aware).

Covers T8 translate portion from .kiro/specs/pptx-import-edit/tasks.md.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXTRACT_CLI = _REPO_ROOT / "sdpm" / "scripts" / "translate_extract.py"
_APPLY_CLI = _REPO_ROOT / "sdpm" / "scripts" / "translate_apply.py"


def _make_minimal_deck(deck_dir: Path) -> None:
    """Create a minimal but realistic deck directory for translation tests."""
    deck_dir.mkdir(parents=True, exist_ok=True)
    (deck_dir / "deck.json").write_text(
        json.dumps({"template": "blank-dark.pptx", "defaultTextColor": "#FFFFFF"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    slides_dir = deck_dir / "slides"
    slides_dir.mkdir()

    # slide-01: title + paragraphs + items + table
    slide01 = {
        "layout": "title",
        "title": "Hello World",
        "subtitle": "Welcome",
        "elements": [
            {
                "type": "textbox",
                "text": "Vertical\x0btab preserved",  # \x0b must roundtrip
                "fontSize": 24,
                "fontColor": "#FFFFFF",  # structural: must NOT be in dict
            },
            {
                "type": "textbox",
                "paragraphs": [
                    {"text": "First paragraph"},
                    {"text": "Second paragraph"},
                ],
            },
            {
                "type": "textbox",
                "items": ["Item A", "Item B", "Ab"],  # "Ab" short-text candidate
            },
            {
                "type": "table",
                "headers": ["Name", {"text": "Rich Header", "fontColor": "#FF0000"}],
                "rows": [
                    ["Alpha", "1"],
                    ["Beta", {"text": "Rich Cell", "fill": "#EEEEEE"}],
                ],
            },
            {
                "type": "group",
                "elements": [
                    {"type": "textbox", "text": "Inside group"},
                ],
            },
            {
                "type": "textbox",
                "text": "{{bold:Styled}} text here",
            },
            {
                "type": "image",
                "src": "images/foo.png",  # structural: must NOT be translated
            },
            {
                "type": "textbox",
                "text": "https://example.com",  # URL: must NOT be translated
            },
        ],
        "notes": "speaker note text",
    }
    (slides_dir / "slide-01.json").write_text(
        json.dumps(slide01, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # specs (copied but not translated)
    specs_dir = deck_dir / "specs"
    specs_dir.mkdir()
    (specs_dir / "brief.md").write_text("# Brief\n\nOriginal English content.", encoding="utf-8")
    (specs_dir / "outline.md").write_text("- [slide-01] Hello World\n", encoding="utf-8")

    # attachments (copied)
    attachments_dir = deck_dir / "attachments"
    attachments_dir.mkdir()
    (attachments_dir / "dummy.txt").write_text("attachment content", encoding="utf-8")

    # images (copied)
    images_dir = deck_dir / "images"
    images_dir.mkdir()
    (images_dir / "foo.png").write_bytes(b"fake-png")

    # files that should NOT be copied
    (deck_dir / "output.pptx").write_bytes(b"fake-pptx")
    preview_dir = deck_dir / "preview"
    preview_dir.mkdir()
    (preview_dir / "page1.png").write_bytes(b"fake")
    compose_dir = deck_dir / "compose"
    compose_dir.mkdir()
    (compose_dir / "defs_1.json").write_text("{}", encoding="utf-8")


def _run_extract(*args: str) -> subprocess.CompletedProcess:
    if not _EXTRACT_CLI.exists():
        pytest.skip("translate_extract.py not yet implemented")
    return subprocess.run(
        [sys.executable, str(_EXTRACT_CLI), *args],
        capture_output=True, text=True, timeout=60,
    )


def _run_apply(*args: str) -> subprocess.CompletedProcess:
    if not _APPLY_CLI.exists():
        pytest.skip("translate_apply.py not yet implemented")
    return subprocess.run(
        [sys.executable, str(_APPLY_CLI), *args],
        capture_output=True, text=True, timeout=60,
    )


# ---------------------------------------------------------------------------
# translate_extract.py — derived-deck creation
# ---------------------------------------------------------------------------


class TestTranslateExtract:
    def test_creates_derived_deck(self, tmp_path: Path) -> None:
        deck = tmp_path / "mydeck"
        _make_minimal_deck(deck)
        proc = _run_extract(str(deck), "--target-lang", "ja")
        assert proc.returncode == 0, f"failed: {proc.stderr}"

        derived = tmp_path / "mydeck-ja"
        assert derived.is_dir()
        assert (derived / "deck.json").exists()
        assert (derived / "slides" / "slide-01.json").exists()
        assert (derived / "specs" / "brief.md").exists()
        assert (derived / "attachments" / "dummy.txt").exists()
        assert (derived / "images" / "foo.png").exists()
        # Not copied:
        assert not (derived / "output.pptx").exists()
        assert not (derived / "preview").exists()
        assert not (derived / "compose").exists()
        # translate/ sub-dir created
        assert (derived / "translate" / "translation_map.json").exists()
        assert (derived / "translate" / "texts.tsv").exists()

    def test_generates_empty_map_with_all_translatable_texts(self, tmp_path: Path) -> None:
        deck = tmp_path / "mydeck"
        _make_minimal_deck(deck)
        proc = _run_extract(str(deck), "--target-lang", "ja")
        assert proc.returncode == 0

        map_path = tmp_path / "mydeck-ja" / "translate" / "translation_map.json"
        dictionary = json.loads(map_path.read_text(encoding="utf-8"))

        # All values must be empty strings (template)
        assert all(v == "" for v in dictionary.values())

        # Translatable keys must be present
        translatable = [
            "Hello World",
            "Welcome",
            "Vertical\x0btab preserved",
            "First paragraph",
            "Second paragraph",
            "Item A",
            "Item B",
            "Name",
            "Rich Header",
            "Alpha",
            "Beta",
            "1",
            "Rich Cell",
            "Inside group",
            "{{bold:Styled}} text here",
            "speaker note text",
        ]
        for key in translatable:
            assert key in dictionary, f"Missing translatable key: {key!r}"

        # Non-translatable keys must be absent
        assert "images/foo.png" not in dictionary  # src
        assert "https://example.com" not in dictionary  # URL
        assert "#FFFFFF" not in dictionary  # fontColor / defaultTextColor

    def test_tsv_escapes_control_characters(self, tmp_path: Path) -> None:
        deck = tmp_path / "mydeck"
        _make_minimal_deck(deck)
        proc = _run_extract(str(deck), "--target-lang", "ja")
        assert proc.returncode == 0

        tsv = (tmp_path / "mydeck-ja" / "translate" / "texts.tsv").read_text(encoding="utf-8")
        assert "\x0b" not in tsv  # vertical tab must be escaped, not invisible
        assert "Vertical\\vtab preserved" in tsv
        # ...while the JSON dictionary keeps the raw control character as key
        dictionary = json.loads(
            (tmp_path / "mydeck-ja" / "translate" / "translation_map.json").read_text(encoding="utf-8")
        )
        assert "Vertical\x0btab preserved" in dictionary

    def test_skip_short_option(self, tmp_path: Path) -> None:
        deck = tmp_path / "mydeck"
        _make_minimal_deck(deck)
        proc = _run_extract(str(deck), "--target-lang", "ja", "--skip-short", "2")
        assert proc.returncode == 0

        map_path = tmp_path / "mydeck-ja" / "translate" / "translation_map.json"
        dictionary = json.loads(map_path.read_text(encoding="utf-8"))

        # "1" and "2" (length 1) should be excluded
        assert "1" not in dictionary
        assert "2" not in dictionary
        # "Ab" (length 2) should be excluded
        assert "Ab" not in dictionary
        # Longer text should remain
        assert "Hello World" in dictionary

    def test_existing_target_errors(self, tmp_path: Path) -> None:
        deck = tmp_path / "mydeck"
        _make_minimal_deck(deck)
        (tmp_path / "mydeck-ja").mkdir()  # already exists
        proc = _run_extract(str(deck), "--target-lang", "ja")
        assert proc.returncode != 0, "Should fail when derived deck already exists"


# ---------------------------------------------------------------------------
# translate_apply.py — apply translations in-place on derived deck
# ---------------------------------------------------------------------------


class TestTranslateApply:
    def _prepare_derived(self, tmp_path: Path, translations: dict[str, str]) -> Path:
        """Build a derived deck with a filled-in translation_map."""
        deck = tmp_path / "mydeck"
        _make_minimal_deck(deck)
        proc = _run_extract(str(deck), "--target-lang", "ja")
        assert proc.returncode == 0
        derived = tmp_path / "mydeck-ja"
        map_path = derived / "translate" / "translation_map.json"
        dictionary = json.loads(map_path.read_text(encoding="utf-8"))
        for k, v in translations.items():
            if k in dictionary:
                dictionary[k] = v
        map_path.write_text(
            json.dumps(dictionary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return derived

    def test_translates_dict_table_cells(self, tmp_path: Path) -> None:
        derived = self._prepare_derived(tmp_path, {
            "Rich Header": "リッチ見出し",
            "Rich Cell": "リッチセル",
        })
        proc = _run_apply(str(derived))
        assert proc.returncode == 0, f"failed: {proc.stderr}"

        slide = json.loads((derived / "slides" / "slide-01.json").read_text(encoding="utf-8"))
        table = next(e for e in slide["elements"] if e.get("type") == "table")
        assert table["headers"][1]["text"] == "リッチ見出し"
        assert table["headers"][1]["fontColor"] == "#FF0000"  # styling preserved
        assert table["rows"][1][1]["text"] == "リッチセル"
        assert table["rows"][1][1]["fill"] == "#EEEEEE"

    def test_apply_in_place(self, tmp_path: Path) -> None:
        derived = self._prepare_derived(tmp_path, {
            "Hello World": "こんにちは世界",
            "Welcome": "ようこそ",
            "Item A": "項目A",
        })
        proc = _run_apply(str(derived))
        assert proc.returncode == 0, f"failed: {proc.stderr}"

        slide = json.loads((derived / "slides" / "slide-01.json").read_text(encoding="utf-8"))
        assert slide["title"] == "こんにちは世界"
        assert slide["subtitle"] == "ようこそ"
        # Items list: only "Item A" translated
        items = next(e for e in slide["elements"] if e.get("type") == "textbox" and "items" in e)
        assert items["items"][0] == "項目A"

    def test_dry_run_does_not_modify_files(self, tmp_path: Path) -> None:
        derived = self._prepare_derived(tmp_path, {"Hello World": "こんにちは世界"})
        before = (derived / "slides" / "slide-01.json").read_text(encoding="utf-8")
        proc = _run_apply(str(derived), "--dry-run")
        assert proc.returncode == 0
        after = (derived / "slides" / "slide-01.json").read_text(encoding="utf-8")
        assert before == after, "--dry-run must not modify slide files"

    def test_preserves_vertical_tab(self, tmp_path: Path) -> None:
        derived = self._prepare_derived(tmp_path, {
            "Vertical\x0btab preserved": "縦\x0bタブ保持",
        })
        proc = _run_apply(str(derived))
        assert proc.returncode == 0
        slide = json.loads((derived / "slides" / "slide-01.json").read_text(encoding="utf-8"))
        found = False
        for e in slide["elements"]:
            if e.get("text") == "縦\x0bタブ保持":
                found = True
                break
        assert found, "vertical tab must roundtrip"

    def test_preserves_styled_text_tags(self, tmp_path: Path) -> None:
        derived = self._prepare_derived(tmp_path, {
            "{{bold:Styled}} text here": "{{bold:装飾された}} テキスト",
        })
        proc = _run_apply(str(derived))
        assert proc.returncode == 0
        slide = json.loads((derived / "slides" / "slide-01.json").read_text(encoding="utf-8"))
        found = False
        for e in slide["elements"]:
            if isinstance(e.get("text"), str) and e["text"].startswith("{{bold:"):
                found = True
                assert e["text"] == "{{bold:装飾された}} テキスト"
        assert found, "styled text must be replaced and preserve tag syntax"

    def test_skips_structural_keys(self, tmp_path: Path) -> None:
        """Structural attributes like fontColor/src must never be in the dictionary."""
        deck = tmp_path / "mydeck"
        _make_minimal_deck(deck)
        proc = _run_extract(str(deck), "--target-lang", "ja")
        assert proc.returncode == 0

        dictionary = json.loads(
            (tmp_path / "mydeck-ja" / "translate" / "translation_map.json").read_text(encoding="utf-8")
        )
        # fontColor value should not be a key
        assert "#FFFFFF" not in dictionary
        # src value should not be a key
        assert "images/foo.png" not in dictionary

    def test_does_not_touch_specs(self, tmp_path: Path) -> None:
        derived = self._prepare_derived(tmp_path, {"Hello World": "こんにちは世界"})
        proc = _run_apply(str(derived))
        assert proc.returncode == 0
        brief = (derived / "specs" / "brief.md").read_text(encoding="utf-8")
        assert "Original English content" in brief, "specs/ must remain in source language"


# ---------------------------------------------------------------------------
# _sync_gradient_runs — gradient run sync after translation (PR #215 follow-up, R4)
# ---------------------------------------------------------------------------


def _load_apply_module():
    """Import scripts/translate_apply.py as a module for unit-level tests."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("translate_apply", _APPLY_CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_GRAD_A = {"angle": 0, "stops": [{"position": 0.0, "color": "#FF0000"}]}
_GRAD_B = {"angle": 0, "stops": [{"position": 0.0, "color": "#0000FF"}]}


class TestSyncGradientRuns:
    """Sync decisions must compare against the PRE-translation text.

    The old implementation ran after text replacement and compared
    run-concat against the translated text, so: multi-run whole-paragraph
    gradients were never synced, and a partial-gradient single run was
    wrongly expanded to the full translated text.
    """

    def _apply_node(self, node: dict, dictionary: dict[str, str]) -> dict:
        mod = _load_apply_module()
        return mod._apply(node, dictionary, {})

    def test_whole_paragraph_multi_run_same_gradient_collapses(self) -> None:
        node = {
            "text": "Hello World",
            "_textGradientRuns": [
                {"text": "Hello ", "gradient": _GRAD_A},
                {"text": "World", "gradient": _GRAD_A},
            ],
        }
        self._apply_node(node, {"Hello World": "こんにちは世界"})
        assert node["text"] == "こんにちは世界"
        assert node["_textGradientRuns"] == [
            {"text": "こんにちは世界", "gradient": _GRAD_A},
        ]

    def test_whole_paragraph_single_run_syncs(self) -> None:
        node = {
            "text": "Hello",
            "_textGradientRuns": [{"text": "Hello", "gradient": _GRAD_A}],
        }
        self._apply_node(node, {"Hello": "こんにちは"})
        assert node["_textGradientRuns"] == [
            {"text": "こんにちは", "gradient": _GRAD_A},
        ]

    def test_partial_gradient_single_run_is_not_expanded(self) -> None:
        """Regression: a partial-paragraph gradient run must stay untouched."""
        node = {
            "text": "Hello World",
            "_textGradientRuns": [{"text": "World", "gradient": _GRAD_A}],
        }
        self._apply_node(node, {"Hello World": "こんにちは世界"})
        # Old code rewrote runs[0].text to the full translated text,
        # expanding the gradient to the entire paragraph.
        assert node["_textGradientRuns"] == [{"text": "World", "gradient": _GRAD_A}]

    def test_multi_gradient_runs_left_unchanged(self) -> None:
        runs = [
            {"text": "Hello ", "gradient": _GRAD_A},
            {"text": "World", "gradient": _GRAD_B},
        ]
        node = {"text": "Hello World", "_textGradientRuns": [dict(r) for r in runs]}
        self._apply_node(node, {"Hello World": "こんにちは世界"})
        assert node["_textGradientRuns"] == runs

    def test_untranslated_paragraph_is_untouched(self) -> None:
        runs = [{"text": "Hello", "gradient": _GRAD_A}]
        node = {"text": "Hello", "_textGradientRuns": [dict(r) for r in runs]}
        self._apply_node(node, {})
        assert node["_textGradientRuns"] == runs
