# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Speaker notes: Markdown export and removal from a built PPTX.

``speaker_notes_markdown`` is used by the PPTX build when deck.json ``speakerNotes``
is ``"markdown"``: the notes stay out of the .pptx (a deck handed to an audience must
not carry the presenter's script) and are written next to it instead.

``strip_speaker_notes`` removes the notes from a stored .pptx without rebuilding it,
for a download without speaker notes (Web UI, both modes).
"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

from sdpm.utils.text import parse_styled_text


def plain_notes_text(notes: object) -> str:
    """Return ``notes`` without ``{{attr:...}}`` styling, as the presenter reads it.

    A hyperlink keeps its text and its URL (``text <URL>``). Non-string notes
    (a degenerate slide file) become an empty string.
    """
    if not isinstance(notes, str) or not notes.strip():
        return ""
    parts: list[str] = []
    for seg in parse_styled_text(notes, auto_spacing=False):
        text = seg.get("text", "")
        link = seg.get("link")
        if link and link != text:
            text = f"{text} <{link}>"
        parts.append(text)
    return "".join(parts).replace("\u000b", "\n").strip()


def slide_title_text(slide: dict) -> str:
    """Title of a slide dict for the export heading: the ``title`` field (a string or a
    ``{"text": ...}`` object), else the first placeholder text, else an empty string."""
    title = slide.get("title")
    if isinstance(title, dict):
        title = title.get("text")
    if isinstance(title, str) and title.strip():
        return plain_notes_text(title)
    placeholders = slide.get("placeholders")
    if isinstance(placeholders, dict):
        for value in placeholders.values():
            if isinstance(value, str) and value.strip():
                return plain_notes_text(value)
    return ""


def speaker_notes_markdown(slides: list[dict], title: str | None = None) -> str:
    """Render the speaker notes of ``slides`` (build order) as Markdown.

    One ``## pageNN — <slide title>`` section per slide, each holding that slide's
    plain notes or ``(no notes)``. The slide ``id`` (slug) follows the heading as a
    comment so the file can be matched back to ``slides/<slug>.json``.

    Args:
        slides: Resolved slide dicts in deck order (``sdpm.api.BuildConfig.slides``).
        title: Deck title for the top heading; ``"Speaker notes"`` alone when None.

    Returns:
        The Markdown text, ending with a newline.
    """
    heading = "# Speaker notes" + (f" — {title.strip()}" if title and title.strip() else "")
    lines: list[str] = [heading, ""]
    for index, slide in enumerate(slides, 1):
        slide_title = slide_title_text(slide)
        section = f"## page{index:02d}" + (f" — {slide_title}" if slide_title else "")
        slug = slide.get("id")
        if isinstance(slug, str) and slug:
            section += f" <!-- {slug} -->"
        lines.append(section)
        lines.append("")
        notes = plain_notes_text(slide.get("notes"))
        lines.append(notes if notes else "(no notes)")
        lines.append("")
    return "\n".join(lines)


def strip_speaker_notes(source: str | Path | BinaryIO, target: str | Path | BinaryIO) -> int:
    """Remove every slide's speaker notes from a built PPTX without rebuilding it.

    Each slide loses its notes-slide relationship, so the saved file has no
    ``ppt/notesSlides/`` part; the rest of the file is unchanged.

    Args:
        source: The stored .pptx (path or binary file object).
        target: Where to save the copy without notes (path or binary file object).

    Returns:
        The number of notes slides removed.
    """
    prs = Presentation(source if not isinstance(source, Path) else str(source))
    removed = 0
    for slide in prs.slides:
        rels = slide.part.rels
        for r_id, rel in list(rels.items()):
            if rel.reltype == RT.NOTES_SLIDE:
                rels.pop(r_id)
                removed += 1
    prs.save(target if not isinstance(target, Path) else str(target))
    return removed
