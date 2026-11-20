# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""deck.json ``speakerNotes``: where the PPTX build puts slide ``notes``.

``pptx`` (default) writes them as speaker notes; ``markdown`` leaves them out of the
.pptx and writes ``<output stem>.notes.md`` next to it. The slide files are never
touched, so composing is unchanged.
"""

import io
import json
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest
from pptx import Presentation

from sdpm.api import check_specs, generate
from sdpm.engine.notes import plain_notes_text, speaker_notes_markdown, strip_speaker_notes
from sdpm.engine.schema import SPEAKER_NOTES, deck_speaker_notes, validate_specs

_DECK_JSON = {
    "template": "blank-dark.pptx",
    "fonts": {"fullwidth": "Meiryo", "halfwidth": "Arial"},
    "defaultTextColor": "#FFFFFF",
    "slideSize": {"width": 1920, "height": 1080, "ptPerPx": 0.75},
}

_SLIDES = {
    "intro": {
        "layout": "Blank",
        "title": "Intro",
        "elements": [],
        "notes": "Welcome {{bold:everyone}}.\nSee {{link:https://example.com/docs:the docs}}.",
    },
    "body": {"layout": "Blank", "title": {"text": "Body"}, "elements": []},
    "close": {"layout": "Blank", "elements": [], "notes": "Internal: pricing is confidential."},
}


def _make_deck(tmp_path: Path, **deck_extra) -> Path:
    deck = tmp_path / "deck"
    (deck / "slides").mkdir(parents=True)
    (deck / "specs").mkdir()
    (deck / "deck.json").write_text(json.dumps({**_DECK_JSON, **deck_extra}), encoding="utf-8")
    (deck / "specs" / "outline.md").write_text("".join(f"- [{slug}] {slug}\n" for slug in _SLIDES), encoding="utf-8")
    for slug, slide in _SLIDES.items():
        (deck / "slides" / f"{slug}.json").write_text(json.dumps(slide, ensure_ascii=False), encoding="utf-8")
    return deck


def _notes_in(pptx: Path) -> list[str]:
    """Speaker notes text per slide; "" for a slide without a notes slide."""
    out = []
    for slide in Presentation(str(pptx)).slides:
        out.append(slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else "")
    return out


# ── schema ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "deck,expected",
    [
        ({}, "pptx"),
        ({"speakerNotes": None}, "pptx"),
        ({"speakerNotes": "pptx"}, "pptx"),
        ({"speakerNotes": "markdown"}, "markdown"),
        ("not a dict", "pptx"),
    ],
)
def test_deck_speaker_notes_default_and_explicit(deck, expected: str) -> None:
    assert deck_speaker_notes(deck) == expected
    assert SPEAKER_NOTES == ("pptx", "markdown")


@pytest.mark.parametrize("value", ["PPTX", "keep", "strip", "export", "", 1, True])
def test_deck_speaker_notes_rejects_unknown_value(value: object) -> None:
    with pytest.raises(ValueError, match="speakerNotes"):
        deck_speaker_notes({"speakerNotes": value})


def test_validate_specs_rejects_invalid_speaker_notes() -> None:
    deck = deepcopy(_DECK_JSON)
    deck["speakerNotes"] = "strip"
    result = validate_specs(deck, "- [intro] Intro\n")
    assert 'deck.json speakerNotes must be "pptx" or "markdown"' in result["errors"]
    assert result["ok"] is False


@pytest.mark.parametrize("value", SPEAKER_NOTES)
def test_check_specs_accepts_every_speaker_notes_value(tmp_path: Path, value: str) -> None:
    result = check_specs(_make_deck(tmp_path, speakerNotes=value))
    assert result["errors"] == []


# ── build ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("deck_extra", [{}, {"speakerNotes": "pptx"}])
def test_default_and_pptx_keep_speaker_notes_in_the_pptx(tmp_path: Path, deck_extra: dict) -> None:
    out = tmp_path / "out.pptx"
    result = generate(_make_deck(tmp_path, **deck_extra), output_path=out)
    notes = _notes_in(out)
    assert notes[0].startswith("Welcome everyone.")
    assert notes[2] == "Internal: pricing is confidential."
    assert "notes_path" not in result
    assert not out.with_name("out.notes.md").exists()


def test_markdown_leaves_the_pptx_without_notes_and_writes_notes_markdown(tmp_path: Path) -> None:
    out = tmp_path / "out.pptx"
    result = generate(_make_deck(tmp_path, speakerNotes="markdown", title="Quarterly review"), output_path=out)
    assert _notes_in(out) == ["", "", ""]
    notes_path = Path(result["notes_path"])
    assert notes_path == out.with_name("out.notes.md")
    text = notes_path.read_text(encoding="utf-8")
    assert text.startswith("# Speaker notes — Quarterly review\n")
    assert "## page01 — Intro <!-- intro -->" in text
    assert "## page02 — Body <!-- body -->" in text
    assert "## page03 <!-- close -->" in text
    # Styling is removed; a link keeps its text and URL; the slide without notes says so.
    assert "Welcome everyone.\nSee the docs <https://example.com/docs>." in text
    assert "{{" not in text
    assert "(no notes)" in text
    assert "Internal: pricing is confidential." in text
    # The slide files are the source of truth and keep their notes.
    assert json.loads((tmp_path / "deck" / "slides" / "intro.json").read_text(encoding="utf-8"))["notes"]


def test_markdown_partial_build_writes_no_notes_file(tmp_path: Path) -> None:
    out = tmp_path / "iso.pptx"
    result = generate(_make_deck(tmp_path, speakerNotes="markdown"), output_path=out, only_slugs={"intro"})
    assert result["slide_count"] == 1
    assert _notes_in(out) == [""]
    assert "notes_path" not in result
    assert not out.with_name("iso.notes.md").exists()


def test_full_pptx_build_deletes_a_stale_notes_file(tmp_path: Path) -> None:
    out = tmp_path / "out.pptx"
    deck = _make_deck(tmp_path, speakerNotes="markdown")
    generate(deck, output_path=out)
    stale = out.with_name("out.notes.md")
    assert stale.exists()
    meta = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
    (deck / "deck.json").write_text(json.dumps({**meta, "speakerNotes": "pptx"}), encoding="utf-8")
    generate(deck, output_path=out)
    assert not stale.exists()
    # A partial build never touches it
    (deck / "deck.json").write_text(json.dumps({**meta, "speakerNotes": "markdown"}), encoding="utf-8")
    generate(deck, output_path=out)
    (deck / "deck.json").write_text(json.dumps({**meta, "speakerNotes": "pptx"}), encoding="utf-8")
    generate(deck, output_path=out, only_slugs={"intro"})
    assert stale.exists()


def test_invalid_speaker_notes_stops_the_build(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="speakerNotes"):
        generate(_make_deck(tmp_path, speakerNotes="strip"), output_path=tmp_path / "out.pptx")


def test_former_notes_mode_key_is_ignored(tmp_path: Path) -> None:
    """notesMode is not a deck.json field: it is ignored like any unknown key."""
    out = tmp_path / "out.pptx"
    deck = _make_deck(tmp_path)
    meta = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
    (deck / "deck.json").write_text(json.dumps({**meta, "notesMode": "export"}), encoding="utf-8")
    result = generate(deck, output_path=out)
    assert _notes_in(out)[0].startswith("Welcome everyone.")
    assert "notes_path" not in result
    assert check_specs(deck)["errors"] == []


# ── strip from a stored PPTX ─────────────────────────────────────────────────


def _has_notes_part(data: bytes) -> bool:
    return any(name.startswith("ppt/notesSlides/") for name in zipfile.ZipFile(io.BytesIO(data)).namelist())


def test_strip_speaker_notes_removes_every_notes_slide(tmp_path: Path) -> None:
    built = tmp_path / "out.pptx"
    generate(_make_deck(tmp_path), output_path=built)
    assert _has_notes_part(built.read_bytes())
    stripped = tmp_path / "stripped.pptx"
    assert strip_speaker_notes(built, stripped) == 2
    assert _notes_in(stripped) == ["", "", ""]
    assert not _has_notes_part(stripped.read_bytes())
    assert len(Presentation(str(stripped)).slides) == 3
    # The source is left as it was
    assert _notes_in(built)[2] == "Internal: pricing is confidential."


def test_strip_speaker_notes_with_file_objects(tmp_path: Path) -> None:
    built = tmp_path / "out.pptx"
    generate(_make_deck(tmp_path), output_path=built)
    out = io.BytesIO()
    assert strip_speaker_notes(io.BytesIO(built.read_bytes()), out) == 2
    assert not _has_notes_part(out.getvalue())
    assert all(not s.has_notes_slide for s in Presentation(io.BytesIO(out.getvalue())).slides)


def test_strip_speaker_notes_on_a_deck_without_notes(tmp_path: Path) -> None:
    built = tmp_path / "out.pptx"
    generate(_make_deck(tmp_path, speakerNotes="markdown"), output_path=built)
    stripped = tmp_path / "stripped.pptx"
    assert strip_speaker_notes(str(built), str(stripped)) == 0
    assert len(Presentation(str(stripped)).slides) == 3


# ── markdown rendering ──────────────────────────────────────────────────────


def test_plain_notes_text_handles_styles_links_and_non_strings() -> None:
    assert plain_notes_text("A {{bold:b}} {{#FF0000:c}} {{14pt:d}}") == "A b c d"
    assert plain_notes_text("{{link:https://x.test/p:go}}") == "go <https://x.test/p>"
    assert plain_notes_text("{{link:https://x.test/p}}") == "https://x.test/p"
    assert plain_notes_text("line1\u000bline2") == "line1\nline2"
    assert plain_notes_text(None) == ""
    assert plain_notes_text(["not", "a", "string"]) == ""
    assert plain_notes_text("   ") == ""


def test_speaker_notes_markdown_without_title_or_slugs() -> None:
    text = speaker_notes_markdown([{"placeholders": {"0": "From placeholder"}, "notes": "n1"}, {"elements": []}])
    assert text.splitlines()[0] == "# Speaker notes"
    assert "## page01 — From placeholder\n\nn1\n" in text
    assert "## page02\n\n(no notes)\n" in text
    assert text.endswith("\n")
