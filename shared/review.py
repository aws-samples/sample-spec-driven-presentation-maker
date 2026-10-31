# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Review request files (``reviews/<id>.json``) — the authoritative contract.

A review request is one submission of positioned comments from the Web UI: each comment
names a frame (``A``, ``B``, …) drawn on a slide, in slide px. The server (Cloud API Lambda,
Local API route) validates the submission, picks the id and timestamp, computes ``refs``
and writes the file; the orchestrator later sets ``status`` and ``reply``.

The Web UI mirror is ``web-ui/src/lib/review/schema.ts``. Both run the cases in
``tests/fixtures/review_submissions.json``, and ``tests/test_review_contract.py`` checks that
the limits below match the TS source.
"""

from __future__ import annotations

import math
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Callable

REVIEW_VERSION = 1
MAX_COMMENTS = 100
MAX_TEXT_CHARS = 2000
MAX_NOTE_CHARS = 4000
MAX_BODY_BYTES = 512 * 1024
DEFAULT_SLIDE_SIZE = (1920, 1080)

# Always used with fullmatch: ``$`` alone would accept a trailing newline, and ``\d`` would
# accept non-ASCII digits.
REVIEW_ID_RE = re.compile(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{4}")
NAME_RE = re.compile(r"[A-Z]{1,3}")
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
# No ``\b``: Python's ``\b`` is Unicode-aware, so ``@Bと`` would not match.
MENTION_RE = re.compile(r"@([A-Z]{1,3})(?![A-Za-z0-9])")


def is_review_id(value: object) -> bool:
    """True when ``value`` is a review id (safe to use in a path)."""
    return isinstance(value, str) and REVIEW_ID_RE.fullmatch(value) is not None


def new_review_id(now: datetime) -> str:
    """Review id for a submission at ``now``: UTC ``YYYYMMDD-HHMMSS-`` plus 4 random hex digits."""
    return f"{now.astimezone(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


def created_at_iso(now: datetime) -> str:
    """``created_at`` value for a submission at ``now`` (UTC, seconds, ``Z`` suffix)."""
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_refs(text: str, names: set[str] | list[str], self_name: str) -> list[str]:
    """Names mentioned as ``@X`` in ``text`` that belong to the same request, in order.

    Each name appears once; the comment's own name and names outside the request are dropped.
    """
    known = set(names)
    refs: list[str] = []
    for match in MENTION_RE.finditer(text):
        name = match.group(1)
        if name in known and name != self_name and name not in refs:
            refs.append(name)
    return refs


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_rect(rect: object, slide_size: tuple[int, int]) -> str | None:
    if not isinstance(rect, list) or len(rect) != 4 or not all(_is_int(v) for v in rect):
        return "rect must be a list of 4 integers"
    x, y, w, h = rect
    width, height = slide_size
    if x < 0 or y < 0:
        return "rect x and y must be >= 0"
    if w < 1 or h < 1:
        return "rect width and height must be >= 1"
    if x + w > width or y + h > height:
        return "rect must lie inside the slide"
    return None


def _validate_comment(
    comment: object, index: int, slide_size: tuple[int, int], slug_exists: Callable[[str], bool],
) -> tuple[dict | None, str | None]:
    where = f"comments[{index}]"
    if not isinstance(comment, dict):
        return None, f"{where} must be an object"
    name = comment.get("name")
    if not isinstance(name, str) or NAME_RE.fullmatch(name) is None:
        return None, f"{where}.name must be 1-3 uppercase letters"
    slide = comment.get("slide")
    if not isinstance(slide, str) or SLUG_RE.fullmatch(slide) is None:
        return None, f"{where}.slide is not a valid slug"
    if not slug_exists(slide):
        return None, f"{where}.slide does not exist"
    rect_error = _validate_rect(comment.get("rect"), slide_size)
    if rect_error:
        return None, f"{where}.{rect_error}"
    text = comment.get("text")
    if not isinstance(text, str):
        return None, f"{where}.text must be a string"
    if "\x00" in text:
        return None, f"{where}.text must not contain NUL"
    text = text.strip()
    if not 1 <= len(text) <= MAX_TEXT_CHARS:
        return None, f"{where}.text must be 1-{MAX_TEXT_CHARS} characters"
    return {"name": name, "slide": slide, "rect": list(comment["rect"]), "text": text}, None


def validate_review_submission(
    body: object, slide_size: tuple[int, int], slug_exists: Callable[[str], bool],
) -> tuple[dict | None, str | None]:
    """Validate a review submission sent from the Web UI.

    ``body`` is ``{"note": str | None, "comments": [{"name", "slide", "rect", "text"}]}``;
    other keys (including any client ``refs`` / ``status``) are ignored. ``slide_size`` is
    ``(width, height)`` in slide px, and ``slug_exists`` says whether ``slides/<slug>.json``
    or ``slides/<slug>.html`` exists (it is only called with slugs that passed ``SLUG_RE``).

    Returns ``(normalized, None)`` — ``{"note": str | None, "comments": [...]}`` with stripped
    text and an empty note as None — or ``(None, error message)``.
    """
    if not isinstance(body, dict):
        return None, "body must be an object"

    note = body.get("note")
    if note is not None:
        if not isinstance(note, str):
            return None, "note must be a string or null"
        if "\x00" in note:
            return None, "note must not contain NUL"
        note = note.strip()
        if len(note) > MAX_NOTE_CHARS:
            return None, f"note exceeds {MAX_NOTE_CHARS} characters"
        note = note or None

    comments = body.get("comments")
    if not isinstance(comments, list):
        return None, "comments must be a list"
    if not 1 <= len(comments) <= MAX_COMMENTS:
        return None, f"comments must hold 1-{MAX_COMMENTS} items"

    normalized: list[dict] = []
    seen: set[str] = set()
    for index, comment in enumerate(comments):
        item, error = _validate_comment(comment, index, slide_size, slug_exists)
        if error:
            return None, error
        if item["name"] in seen:
            return None, f"comments[{index}].name is duplicated"
        seen.add(item["name"])
        normalized.append(item)
    return {"note": note, "comments": normalized}, None


def build_review_file(
    review_id: str, created_at: str, slide_size: tuple[int, int], normalized: dict,
) -> dict[str, Any]:
    """The review file for a validated submission: refs computed, every comment ``open``."""
    names = [c["name"] for c in normalized["comments"]]
    return {
        "version": REVIEW_VERSION,
        "id": review_id,
        "created_at": created_at,
        "note": normalized["note"],
        "slide_size": [slide_size[0], slide_size[1]],
        "comments": [
            {
                "name": c["name"],
                "slide": c["slide"],
                "rect": list(c["rect"]),
                "text": c["text"],
                "refs": extract_refs(c["text"], names, c["name"]),
                "status": "open",
                "reply": None,
            }
            for c in normalized["comments"]
        ],
    }


def slide_size_of(deck_json: object) -> tuple[int, int]:
    """``(width, height)`` from deck.json ``slideSize`` as whole px; 1920 × 1080 when missing or invalid."""
    size = deck_json.get("slideSize") if isinstance(deck_json, dict) else None
    if not isinstance(size, dict):
        return DEFAULT_SLIDE_SIZE
    out = []
    for dim, default in zip(("width", "height"), DEFAULT_SLIDE_SIZE):
        value = size.get(dim)
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 1
        out.append(int(value) if ok else default)
    return out[0], out[1]
