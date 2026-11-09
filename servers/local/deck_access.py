# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Local storage for the deck viewer (``sdpm.tools.apps.deck.DeckAccess``): the deck directory.

Slide previews come from ``compose/<slug>_<epoch>.json`` (newest per slug, as the Web UI's
Local deck route picks them) and ``preview/<slug>.png``.

``deck_id`` is the deck directory, as for every local deck tool. Reviews are written the way
the Web UI's Local review route writes them (old files under ``reviews/`` removed, the new
file created only if absent), through the shared contract in ``shared/review.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from sdpm.engine.schema import SLUG_RE
from sdpm.tools.apps.deck import DECK_FILES, DeckAccess
from shared.artifact_keys import COMPOSE_NAME_RE, latest_compose_keys
from shared.review import create_review


def _deck(deck_id: str) -> Path:
    return Path(deck_id).expanduser()


def _open(deck_id: str, write: bool) -> None:
    if not (_deck(deck_id) / "deck.json").is_file():
        raise ValueError(f"No deck at {deck_id}")


def _read_text(deck_id: str, rel: str) -> str | None:
    if rel not in DECK_FILES:
        return None
    try:
        return (_deck(deck_id) / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _slide_slugs(deck_id: str) -> set[str]:
    slides = _deck(deck_id) / "slides"
    if not slides.is_dir():
        return set()
    return {p.stem for p in slides.iterdir() if p.suffix in (".json", ".html") and p.is_file()}


def _preview_dir(deck_id: str, fmt: str) -> Path:
    preview = _deck(deck_id) / "preview"
    return preview / "png" if fmt == "html" else preview


def _previews(deck_id: str, fmt: str) -> dict[str, str]:
    folder = _preview_dir(deck_id, fmt)
    if not folder.is_dir():
        return {}
    stamps: dict[str, str] = {}
    for p in folder.glob("*.png"):
        if SLUG_RE.fullmatch(p.stem) and p.is_file():
            st = p.stat()
            stamps[p.stem] = f"{st.st_mtime_ns}-{st.st_size}"
    return stamps


def _read_preview(deck_id: str, fmt: str, slug: str, stamp: str) -> bytes | None:
    if not SLUG_RE.fullmatch(slug):
        return None
    try:
        return (_preview_dir(deck_id, fmt) / f"{slug}.png").read_bytes()
    except OSError:
        return None


def _compose(deck_id: str) -> dict[str, str]:
    folder = _deck(deck_id) / "compose"
    if not folder.is_dir():
        return {}
    return latest_compose_keys(p.name for p in folder.iterdir() if p.is_file())


def _read_compose(deck_id: str, name: str) -> bytes | None:
    # ``name`` is a file name _compose() listed; nothing else under the deck is read.
    if not COMPOSE_NAME_RE.fullmatch(name) or Path(name).name != name or "\\" in name:
        return None
    try:
        return (_deck(deck_id) / "compose" / name).read_bytes()
    except OSError:
        return None


def _submit_review(deck_id: str, body: dict) -> dict:
    deck = _deck(deck_id)
    try:
        deck_json = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        deck_json = {}
    reviews = deck / "reviews"

    def slug_exists(slug: str) -> bool:
        return any((deck / "slides" / f"{slug}{ext}").is_file() for ext in (".json", ".html"))

    def clear() -> None:
        if reviews.is_dir():
            for p in reviews.iterdir():
                if not p.is_dir():
                    p.unlink(missing_ok=True)

    def write_new(path: str, data: bytes) -> bool:
        reviews.mkdir(exist_ok=True)
        try:
            with open(deck / path, "xb") as f:
                f.write(data)
        except FileExistsError:
            return False
        return True

    return create_review(body, deck_json, slug_exists, clear=clear, write_new=write_new)


def _preview_environment(fmt: str) -> dict | None:
    if fmt == "html":
        from sdpm.engine.html.browser import SKIPPED_NOTE, find_browser

        if find_browser() is None:
            return {"status": "unavailable", "missing": ["chrome"], "install": "", "note": SKIPPED_NOTE}
        return None
    from sdpm.engine.preview.environment import preview_unavailable

    return preview_unavailable()


ACCESS = DeckAccess(
    open=_open,
    read_text=_read_text,
    slide_slugs=_slide_slugs,
    previews=_previews,
    read_preview=_read_preview,
    submit_review=_submit_review,
    preview_environment=_preview_environment,
    compose=_compose,
    read_compose=_read_compose,
)
