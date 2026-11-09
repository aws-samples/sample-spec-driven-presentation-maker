# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The deck viewer's operations (``app_action`` with ``action`` deck / slide_preview /
submit_review / outline_edit).

Pure: the server passes in a ``DeckAccess`` that reads its own storage (the deck directory on
the Local server, S3 with the caller's permission check on the remote). Arguments from the
view are checked here; a bad one raises ``ValueError``. Outline edits are never written: the
user's edit comes back as a message for the agent to apply.
"""

from __future__ import annotations

import base64
import difflib
import io
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sdpm.engine.schema import OUTLINE_SLUG_RE, SLUG_RE, deck_output_format, parse_outline_entries, validate_specs

DECK_FILES = ("deck.json", "specs/brief.md", "specs/outline.md")
MAX_TEXT = 200_000
MAX_DECK_ID = 1024
PREVIEW_EDGE = 1280
OUTLINE = "specs/outline.md"
_DEFAULT_SLIDE_SIZE = (1920, 1080)


def _no_environment(fmt: str) -> dict | None:
    return None


@dataclass(frozen=True)
class DeckAccess:
    """How a server reads and writes a deck for the viewer. ``deck_id`` is the id the deck tools take.

    - ``open(deck_id, write)``: raises ValueError when the deck is unknown or the caller may
      not read it (``write=False``) or comment on it (``write=True``)
    - ``read_text(deck_id, rel)``: the UTF-8 text of ``rel`` (one of ``DECK_FILES``), or None
    - ``slide_slugs(deck_id)``: slugs that have a ``slides/<slug>.json|html``
    - ``previews(deck_id, fmt)``: ``{slug: stamp}`` of the slide preview images; a stamp
      changes whenever the image does
    - ``read_preview(deck_id, fmt, slug, stamp)``: that image's bytes, or None
    - ``submit_review(deck_id, body)``: write ``reviews/<id>.json`` through
      ``shared.review.create_review``, return ``{"id", "message"}``
    - ``preview_environment(fmt)``: what the server lacks to make previews
      (``preview_unavailable()``'s shape), or None
    """

    open: Callable[[str, bool], None]
    read_text: Callable[[str, str], str | None]
    slide_slugs: Callable[[str], set[str]]
    previews: Callable[[str, str], dict[str, str]]
    read_preview: Callable[[str, str, str, str], bytes | None]
    submit_review: Callable[[str, dict], dict]
    preview_environment: Callable[[str], dict | None] = field(default=_no_environment)


def _deck_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_DECK_ID or "\x00" in value:
        raise ValueError(f"deck_id must be a deck id of 1 to {MAX_DECK_ID} characters")
    return value


def _slide_size(deck_json: Any) -> tuple[int, int]:
    """deck.json ``slideSize`` in whole px, 1920 × 1080 when missing or invalid (as shared.review)."""
    size = deck_json.get("slideSize") if isinstance(deck_json, dict) else None
    if not isinstance(size, dict):
        return _DEFAULT_SLIDE_SIZE
    out = []
    for dim, default in zip(("width", "height"), _DEFAULT_SLIDE_SIZE):
        value = size.get(dim)
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 1
        out.append(int(value) if ok else default)
    return out[0], out[1]


def _failed(error: str) -> dict:
    return {"ok": False, "errors": [error], "warnings": [], "slugs": []}


def _parse_deck(deck_text: str | None) -> tuple[Any, dict | None]:
    """(deck.json, None) or (None, the check_specs result for an unusable deck.json)."""
    if deck_text is None:
        return None, None
    try:
        deck_json = json.loads(deck_text)
    except json.JSONDecodeError:
        return None, _failed("deck.json is invalid JSON")
    if not isinstance(deck_json, dict):
        return None, _failed("deck.json must contain an object")
    return deck_json, None


def _check(deck_text: str | None, deck_json: Any, failed: dict | None, outline_text: str | None) -> dict:
    """The check_specs result for these files (the same messages as ``sdpm.api.check_specs``)."""
    missing = [m for m, text in (("deck.json is missing", deck_text), ("specs/outline.md is missing", outline_text))
               if text is None]
    if missing:
        return {"ok": False, "errors": missing, "warnings": [], "slugs": []}
    if failed:
        return failed
    return validate_specs(deck_json, outline_text)


def _format(deck_json: Any) -> str:
    try:
        return deck_output_format(deck_json)
    except ValueError:  # the check names the bad outputFormat
        return "pptx"


def deck_view(deck_id: Any, access: DeckAccess) -> dict[str, Any]:
    """Everything the viewer's tabs show, without images (a few KB; the refresh button reloads it).

    ``slides`` are the outline's slide lines with a valid slug, in order: ``built`` when the
    slide file exists, ``preview`` the image's stamp (None without one). ``preview_environment``
    is set only when a built slide has no preview and the server cannot make previews.
    """
    deck_id = _deck_id(deck_id)
    access.open(deck_id, False)
    deck_text = access.read_text(deck_id, "deck.json")
    brief = access.read_text(deck_id, "specs/brief.md")
    outline_text = access.read_text(deck_id, OUTLINE)
    deck_json, failed = _parse_deck(deck_text)
    fmt = _format(deck_json)
    built = access.slide_slugs(deck_id)
    stamps = access.previews(deck_id, fmt)
    entries = parse_outline_entries(outline_text or "")
    slides: list[dict] = []
    seen: set[str] = set()
    for e in entries:
        slug = e["slug"] if e["type"] == "slide" else None
        if slug is None or slug in seen or not OUTLINE_SLUG_RE.fullmatch(slug):
            continue
        seen.add(slug)
        slides.append({"slug": slug, "message": e["message"], "built": slug in built, "preview": stamps.get(slug)})
    lacking = any(s["built"] and s["preview"] is None for s in slides)
    width, height = _slide_size(deck_json)
    return {
        "deck_id": deck_id,
        "format": fmt,
        "slide_size": [width, height],
        "brief": brief,
        "outline_text": outline_text,
        "outline": entries,
        "slides": slides,
        "check": _check(deck_text, deck_json, failed, outline_text),
        "preview_environment": access.preview_environment(fmt) if lacking else None,
    }


def _jpeg(data: bytes) -> str | None:
    """The image as a base64 JPEG whose long edge is at most ``PREVIEW_EDGE``; None if unreadable."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.getchannel("A"))
            else:
                flat = img.convert("RGB")
        flat.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE))
        out = io.BytesIO()
        flat.save(out, format="JPEG", quality=80)
    except Exception:  # noqa: BLE001 - any undecodable image is "no preview"
        return None
    return base64.b64encode(out.getvalue()).decode("ascii")


def slide_preview(deck_id: Any, slug: Any, access: DeckAccess) -> dict[str, Any]:
    """One slide's preview as a JPEG data payload, or ``{"slug", "available": False}``."""
    deck_id = _deck_id(deck_id)
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
        raise ValueError("slug must be a slide slug")
    access.open(deck_id, False)
    deck_json, _ = _parse_deck(access.read_text(deck_id, "deck.json"))
    fmt = _format(deck_json)
    stamp = access.previews(deck_id, fmt).get(slug)
    data = access.read_preview(deck_id, fmt, slug, stamp) if stamp is not None else None
    encoded = _jpeg(data) if data else None
    if encoded is None:
        return {"slug": slug, "available": False}
    return {"slug": slug, "available": True, "mimeType": "image/jpeg", "data": encoded, "stamp": stamp}


def _fence(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _block(lang: str, text: str) -> str:
    fence = _fence(text)
    return f"{fence}{lang}\n{text}{'' if text.endswith(chr(10)) else chr(10)}{fence}"


def outline_edit(deck_id: Any, base: Any, text: Any, access: DeckAccess) -> dict[str, Any]:
    """The user's outline edit as a message for the agent: a unified diff of ``base`` (the text
    the viewer loaded) to ``text``, or the whole text when that is shorter than the diff.
    Nothing is written. Returns ``{"message", "added", "deleted"}``.
    """
    deck_id = _deck_id(deck_id)
    for name, value in (("base", base), ("text", text)):
        if not isinstance(value, str) or len(value) > MAX_TEXT:
            raise ValueError(f"{name} must be the outline text, at most {MAX_TEXT} characters")
    if base == text:
        raise ValueError("no changes to send")
    access.open(deck_id, False)
    current = access.read_text(deck_id, OUTLINE) or ""
    old, new = base.splitlines(), text.splitlines()
    diff = list(difflib.unified_diff(old, new, f"a/{OUTLINE}", f"b/{OUTLINE}", lineterm=""))
    added = sum(1 for line in diff[2:] if line.startswith("+"))
    deleted = sum(1 for line in diff[2:] if line.startswith("-"))
    if len(diff) <= len(new):
        message = (f"I edited {OUTLINE} in the deck viewer. Apply this diff to {OUTLINE}, then check it with "
                   f"check_specs.\n\n{_block('diff', chr(10).join(diff))}")
        stale = f"{OUTLINE} changed after the viewer loaded it; the diff is against the version I saw."
    else:
        message = (f"I edited {OUTLINE} in the deck viewer. Write this text to {OUTLINE} as it is, then check "
                   f"it with check_specs.\n\n{_block('markdown', text)}")
        stale = f"{OUTLINE} changed after the viewer loaded it; my text replaces the version I saw."
    if current != base:
        message = f"{message}\n\n{stale}"
    return {"message": message, "added": added, "deleted": deleted}


def submit_review(deck_id: Any, review: Any, access: DeckAccess) -> dict[str, Any]:
    """Save the user's slide comments as ``reviews/<id>.json``; returns ``{"id", "message"}``,
    the message being the Web UI's review message for ``ui/message``."""
    deck_id = _deck_id(deck_id)
    if not isinstance(review, dict) or not review:
        raise ValueError("review must be an object {note, comments}")
    access.open(deck_id, True)
    return access.submit_review(deck_id, review)
