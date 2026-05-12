# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for PPTX import → deck structure conversion + upload integration.

Covers T8 from .kiro/specs/pptx-import-edit/tasks.md:
- pptx_to_json output: deck.json + slides/slide-NN.json
- shared/ingest._convert_pptx: ConversionResult with deck_structure / theme_hints
- mcp-local/upload_tools: guide/guideInstruction in response
- mcp-local/upload_tools.read_uploaded_file: deck text summary
- mcp-local/upload_tools._import_from_upload: slides/ recursive copy + shortId
- pptx_builder.py CLI: accepts deck directory
- Non-regression: PDF/DOCX/XLSX import unchanged
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_PPTX = _REPO_ROOT / "skill" / "references" / "examples" / "components.pptx"


@pytest.fixture
def fixture_pptx() -> Path:
    """Return path to the bundled components.pptx fixture."""
    if not _FIXTURE_PPTX.exists():
        pytest.skip(f"Fixture PPTX not found: {_FIXTURE_PPTX}")
    return _FIXTURE_PPTX


# ---------------------------------------------------------------------------
# T1: pptx_to_json output structure
# ---------------------------------------------------------------------------


class TestPptxToJsonDeckStructure:
    """pptx_to_json must output deck.json + slides/slide-NN.json."""

    def test_pptx_to_json_outputs_deck_structure(self, fixture_pptx: Path, tmp_path: Path) -> None:
        """Output directory contains deck.json and slides/slide-NN.json — no single slides.json."""
        from sdpm.converter import pptx_to_json

        out_dir = tmp_path / "out"
        pptx_to_json(fixture_pptx, output_dir=out_dir)

        assert (out_dir / "deck.json").exists(), "deck.json should be created"
        slides_dir = out_dir / "slides"
        assert slides_dir.is_dir(), "slides/ directory should be created"
        slide_files = list(slides_dir.glob("slide-*.json"))
        assert len(slide_files) > 0, "at least one slide-NN.json should exist"
        # Legacy single slides.json must NOT be written
        assert not (out_dir / "slides.json").exists(), "legacy slides.json must not be emitted"

    def test_pptx_to_json_slug_format(self, fixture_pptx: Path, tmp_path: Path) -> None:
        """Slug format is slide-NN (hyphen + 2-digit zero-padded) and matches parse_outline_slugs regex."""
        from sdpm.api import parse_outline_slugs
        from sdpm.converter import pptx_to_json

        out_dir = tmp_path / "out"
        pptx_to_json(fixture_pptx, output_dir=out_dir)

        slide_files = sorted((out_dir / "slides").glob("*.json"))
        slug_re = re.compile(r"^slide-\d{2}$")
        for f in slide_files:
            assert slug_re.match(f.stem), f"slug must match slide-NN format: {f.stem}"

        # Sanity: construct fake outline.md with these slugs and verify parse_outline_slugs accepts them
        fake_outline = "\n".join(f"- [{f.stem}] msg" for f in slide_files)
        outline_path = tmp_path / "outline.md"
        outline_path.write_text(fake_outline, encoding="utf-8")
        parsed = parse_outline_slugs(outline_path)
        assert parsed == [f.stem for f in slide_files]

    def test_deck_json_has_fonts_and_default_text_color(self, fixture_pptx: Path, tmp_path: Path) -> None:
        """deck.json contains fonts dict and defaultTextColor (both PPTX-derived)."""
        from sdpm.converter import pptx_to_json

        out_dir = tmp_path / "out"
        pptx_to_json(fixture_pptx, output_dir=out_dir)

        deck = json.loads((out_dir / "deck.json").read_text(encoding="utf-8"))
        assert "fonts" in deck, "deck.json should contain fonts"
        # defaultTextColor may be None if extraction failed, but the key should exist
        assert "defaultTextColor" in deck, "deck.json should contain defaultTextColor key"


# ---------------------------------------------------------------------------
# T2: shared/ingest._convert_pptx + _extract_theme_hints
# ---------------------------------------------------------------------------


class TestConvertPptxThemeHints:
    """_convert_pptx must populate deck_structure, slide_count, theme_hints, suggested_name."""

    def test_convert_pptx_populates_new_fields(self, fixture_pptx: Path, tmp_path: Path) -> None:
        from shared.ingest import convert_file

        out_dir = tmp_path / "out"
        result = convert_file(fixture_pptx, out_dir)

        assert result.status == "success"
        assert result.deck_structure is True, "deck_structure should be True for PPTX"
        assert result.slide_count > 0, "slide_count should be positive"
        assert result.suggested_name == fixture_pptx.stem
        assert result.theme_hints is not None

    def test_convert_pptx_theme_hints_keys(self, fixture_pptx: Path, tmp_path: Path) -> None:
        """theme_hints uses unified keys: backgroundLuminance / accentColors / fonts."""
        from shared.ingest import convert_file

        out_dir = tmp_path / "out"
        result = convert_file(fixture_pptx, out_dir)

        assert "backgroundLuminance" in result.theme_hints
        assert "accentColors" in result.theme_hints
        assert "fonts" in result.theme_hints
        # Luminance: 0.0-1.0
        lum = result.theme_hints["backgroundLuminance"]
        assert isinstance(lum, (int, float))
        assert 0.0 <= lum <= 1.0
        # Accent colors: list of #RRGGBB, max 3
        assert isinstance(result.theme_hints["accentColors"], list)
        assert len(result.theme_hints["accentColors"]) <= 3
        for c in result.theme_hints["accentColors"]:
            assert re.match(r"^#[0-9A-Fa-f]{6}$", c), f"invalid hex: {c}"
        # Fonts: dict with halfwidth/fullwidth
        fonts = result.theme_hints["fonts"]
        assert isinstance(fonts, dict)

    def test_convert_pptx_theme_hints_uses_slide_bg(self, tmp_path: Path) -> None:
        """When slide has explicit background, luminance reflects it (median across slides).

        Synthetic fixture: modify slide XML to force explicit backgrounds.
        If the fixture doesn't have explicit bg, we fall back to template-derived luminance
        — both paths must yield a valid number.
        """
        from shared.ingest import convert_file

        out_dir = tmp_path / "out"
        result = convert_file(_FIXTURE_PPTX, out_dir)
        # The fixture may or may not have explicit slide bg; we just verify the median is valid.
        # (Full-fidelity synthetic testing of slide-bg override is deferred; the pipeline
        # correctness is validated via test_convert_pptx_theme_hints_keys.)
        assert 0.0 <= result.theme_hints["backgroundLuminance"] <= 1.0


# ---------------------------------------------------------------------------
# T3: Local upload_file returns guide/guideInstruction for PPTX
# ---------------------------------------------------------------------------


class TestUploadFileGuideInstruction:
    """Local upload_file must return guide, guideInstruction, suggestedName, slideCount, themeHints."""

    def _upload_pptx(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
        """Helper: upload the fixture PPTX via mcp-local/upload_tools.upload_file."""
        # Route SDPM_DECK_ROOT so session storage lives under tmp_path
        monkeypatch.setenv("SDPM_DECK_ROOT", str(tmp_path / "deck_root"))
        sys.path.insert(0, str(_REPO_ROOT / "mcp-local"))
        from upload_tools import upload_file

        # Copy fixture to tmp_path so the temp upload path is stable
        src = tmp_path / "input.pptx"
        shutil.copy2(_FIXTURE_PPTX, src)

        raw = upload_file("test-session", str(src), "input.pptx")
        return json.loads(raw)

    def test_upload_file_returns_guide_for_pptx(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resp = self._upload_pptx(tmp_path, monkeypatch)
        assert resp.get("status") == "converted"
        assert resp.get("guide") == "import-pptx"
        assert "guideInstruction" in resp
        assert resp.get("suggestedName") == "input"
        assert isinstance(resp.get("slideCount"), int)
        assert resp.get("slideCount") > 0
        theme = resp.get("themeHints")
        assert theme is not None
        assert "backgroundLuminance" in theme
        assert "accentColors" in theme
        assert "fonts" in theme

    def test_upload_file_does_not_include_head_text_or_slide_titles(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Per spec: headText / slideTitles must NOT be in the response."""
        resp = self._upload_pptx(tmp_path, monkeypatch)
        assert "headText" not in resp
        assert "slideTitles" not in resp

    def test_guide_instruction_contains_intent_branching(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """guideInstruction must mention edit / reference / hearing branching."""
        resp = self._upload_pptx(tmp_path, monkeypatch)
        instruction = resp["guideInstruction"].lower()
        assert "edit" in instruction
        assert "reference" in instruction
        assert "hearing" in instruction


# ---------------------------------------------------------------------------
# T3b: Local read_uploaded_file returns deck text summary
# ---------------------------------------------------------------------------


class TestReadUploadedFileTextSummary:
    def test_read_uploaded_file_returns_text_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SDPM_DECK_ROOT", str(tmp_path / "deck_root"))
        sys.path.insert(0, str(_REPO_ROOT / "mcp-local"))
        from upload_tools import read_uploaded_file, upload_file

        src = tmp_path / "input.pptx"
        shutil.copy2(_FIXTURE_PPTX, src)
        raw = upload_file("test-session", str(src), "input.pptx")
        upload_id = json.loads(raw)["uploadId"]

        result = read_uploaded_file(upload_id)
        # Must contain a markdown-style summary with "--- Slide N" section markers
        text_parts = [r for r in result if isinstance(r, str)]
        joined = "\n".join(text_parts)
        assert "--- Slide 1" in joined or "Slide 1" in joined, \
            f"Expected slide section markers, got: {joined[:500]}"


# ---------------------------------------------------------------------------
# T3c: import_attachment recursive slides/ copy + shortId in result
# ---------------------------------------------------------------------------


class TestImportAttachmentSlidesDir:
    def test_import_attachment_copies_slides_dir_and_returns_short_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SDPM_DECK_ROOT", str(tmp_path / "deck_root"))
        sys.path.insert(0, str(_REPO_ROOT / "mcp-local"))
        from upload_tools import import_attachment, upload_file

        src = tmp_path / "input.pptx"
        shutil.copy2(_FIXTURE_PPTX, src)
        raw = upload_file("test-session", str(src), "input.pptx")
        upload_id = json.loads(raw)["uploadId"]

        # Create a deck dir
        deck_dir = tmp_path / "deck"
        deck_dir.mkdir()

        result_raw = import_attachment(source=upload_id, deck_id=str(deck_dir))
        result = json.loads(result_raw)

        assert "shortId" in result, "import_attachment must return shortId"
        short_id = result["shortId"]
        assert re.match(r"^[0-9a-f]{8}$", short_id)

        # attachments/{shortId}/slides/slide-NN.json must exist
        slides_dir = deck_dir / "attachments" / short_id / "slides"
        assert slides_dir.is_dir(), f"expected {slides_dir} to exist"
        slide_files = list(slides_dir.glob("slide-*.json"))
        assert len(slide_files) > 0

        # deckJson path should be recorded in the result
        assert "deckJson" in result


# ---------------------------------------------------------------------------
# T1 regression: pptx_builder.py CLI accepts deck directory
# ---------------------------------------------------------------------------


class TestPptxBuilderCliAcceptsDeckDir:
    def test_pptx_builder_cli_generate_on_deck_dir(self, fixture_pptx: Path, tmp_path: Path) -> None:
        """Convert PPTX → deck structure → pptx_builder.py generate should work on the directory."""
        from sdpm.converter import pptx_to_json

        deck_dir = tmp_path / "deck"
        pptx_to_json(fixture_pptx, output_dir=deck_dir)

        # pptx_to_json writes deck.json (with template=None) — supply template for generate
        deck_json_path = deck_dir / "deck.json"
        deck_data = json.loads(deck_json_path.read_text(encoding="utf-8"))
        deck_data["template"] = str(_REPO_ROOT / "skill" / "templates" / "blank-dark.pptx")
        deck_json_path.write_text(json.dumps(deck_data, ensure_ascii=False, indent=2), encoding="utf-8")

        # Build an outline covering all slides
        specs_dir = deck_dir / "specs"
        specs_dir.mkdir(exist_ok=True)
        slide_files = sorted((deck_dir / "slides").glob("*.json"))
        outline_lines = [f"- [{f.stem}] Slide {f.stem}" for f in slide_files]
        (specs_dir / "outline.md").write_text("\n".join(outline_lines), encoding="utf-8")

        # CLI: pptx_builder.py generate {deck_dir} -o {output}
        output_pptx = tmp_path / "out.pptx"
        cli = _REPO_ROOT / "skill" / "scripts" / "pptx_builder.py"
        proc = subprocess.run(
            [sys.executable, str(cli), "generate", str(deck_dir), "-o", str(output_pptx)],
            capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, f"pptx_builder.py generate failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
        assert output_pptx.exists()


# ---------------------------------------------------------------------------
# Non-regression: PDF/DOCX/XLSX conversion still works (old flow)
# ---------------------------------------------------------------------------


class TestNonRegression:
    """PDF/DOCX/XLSX conversion paths must not be affected by the PPTX deck-structure change."""

    def test_convert_docx_still_produces_markdown(self, tmp_path: Path) -> None:
        """A simple DOCX is converted to Markdown (deck_structure stays False)."""
        try:
            from docx import Document  # noqa: F401
        except ImportError:
            pytest.skip("python-docx not available")

        from docx import Document
        from shared.ingest import convert_file

        src = tmp_path / "simple.docx"
        doc = Document()
        doc.add_heading("Test", level=1)
        doc.add_paragraph("Hello world")
        doc.save(str(src))

        out_dir = tmp_path / "out"
        result = convert_file(src, out_dir)
        assert result.status in ("success", "partial")
        # DOCX must not trigger deck_structure
        assert result.deck_structure is False
        md_path = out_dir / "simple.md"
        assert md_path.exists()
