# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Key layout of deck artifacts and the one "latest epoch wins" selector.

Shared by servers/remote, servers/local and api. Slide artifacts carry an epoch, and
for every slug the key with the highest epoch is the current one::

    previews/{deck_id}/{slug}_{epoch}.webp        PPTX slide preview image
    decks/{deck_id}/compose/{slug}_{epoch}.json   PPTX live-preview payload of a slide
    decks/{deck_id}/compose/defs_{epoch}.json     PPTX live-preview defs of the deck
                                                  (Local: compose/ in the deck directory)
    html/{deck_id}/{uuid}.html                    built HTML deck (DDB htmlS3Key)
    html/{deck_id}/preview/{slug}_{epoch}.html    static per-slide thumbnail of an HTML deck
    html/{deck_id}/png/{slug}_{epoch}.png         browser-check PNG of an HTML slide (get_preview)
    template-html-cache/{cache_key}/{rel}         template conversion cache

Slugs in preview, PNG and HTML preview keys follow the artifact grammar
(``sdpm.engine.schema.SLUG_RE``), which also accepts the legacy ``slide_NN``. Compose
names carry whatever slug the deck uses: everything before the last ``_{epoch}``.

``html/`` is served only through presigned URLs: it is in no CloudFront behaviour and
not in the CloudFront OAC bucket-policy grant. The PNGs are not under ``preview/``,
which the API lists for the Web UI thumbnails.
"""

import re
import uuid
from typing import Callable, Iterable, Optional, Tuple

from sdpm.engine.schema.slugs import SLUG, SLUG_RE

HTML_PREFIX = "html/"
HTML_CONTENT_TYPE = "text/html; charset=utf-8"
TEMPLATE_CACHE_PREFIX = "template-html-cache/"
COMPOSE_DEFS = "defs"

SlugEpoch = Tuple[str, int]

_DECK_ID_RE = re.compile(r"[A-Za-z0-9_-]+")
# {slug}_{epoch}.<ext> at the end of a key; searched, not anchored at "/".
_SLIDE_PREVIEW_RE = re.compile(rf"({SLUG})_(\d+)\.(?:webp|png)$")
_HTML_PREVIEW_RE = re.compile(rf"({SLUG})_(\d+)\.html$")
_PNG_RE = re.compile(rf"/png/({SLUG})_(\d+)\.png$")
# {slug}_{epoch}.json, the whole name after the compose prefix (fullmatch).
COMPOSE_NAME_RE = re.compile(r"(.+)_(\d+)\.json")
_CACHE_KEY_RE = re.compile(r"[0-9a-f]{1,64}")
_CACHE_FILES = frozenset({"theme.css", "template.json"})
_CACHE_LAYOUT_RE = re.compile(r"layouts/[A-Za-z0-9_-][A-Za-z0-9_.-]*\.svg")


def latest_by_slug(keys: Iterable[str], slug_epoch: Callable[[str], Optional[SlugEpoch]]) -> dict[str, str]:
    """Map slug → its key with the highest epoch. ``slug_epoch`` parses a key into
    ``(slug, epoch)``, or None to ignore it; on equal epochs the first key wins."""
    best: dict[str, Tuple[int, str]] = {}
    for key in keys:
        se = slug_epoch(key)
        if se is None:
            continue
        slug, epoch = se
        if slug not in best or epoch > best[slug][0]:
            best[slug] = (epoch, key)
    return {slug: key for slug, (_, key) in best.items()}


def _search(pattern: re.Pattern, key: str) -> Optional[SlugEpoch]:
    m = pattern.search(key)
    return (m.group(1), int(m.group(2))) if m else None


def _deck(deck_id: str) -> str:
    if not isinstance(deck_id, str) or not _DECK_ID_RE.fullmatch(deck_id):
        raise ValueError(f"invalid deck id: {deck_id!r}")
    return deck_id


def _slug(slug: str) -> str:
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
        raise ValueError(f"invalid slug: {slug!r}")
    return slug


# --- PPTX slide previews: previews/{deck_id}/{slug}_{epoch}.webp ---


def slide_preview_slug_epoch(key: str) -> Optional[SlugEpoch]:
    """``(slug, epoch)`` of a slide preview key (``.webp``, or ``.png``), or None."""
    return _search(_SLIDE_PREVIEW_RE, key)


def build_slide_key_map(keys: Iterable[str]) -> dict[str, str]:
    """Map slug → latest slide preview key (highest epoch wins); other keys are ignored."""
    return latest_by_slug(keys, slide_preview_slug_epoch)


# --- PPTX live-preview payloads: decks/{deck_id}/compose/{slug}_{epoch}.json ---


def compose_prefix(deck_id: str) -> str:
    """``decks/{deck_id}/compose/`` — the compose payloads of a deck live under it."""
    return f"decks/{deck_id}/compose/"


def compose_key(prefix: str, slug: str, epoch: int) -> str:
    """``{prefix}{slug}_{epoch}.json``; ``slug`` ``COMPOSE_DEFS`` is the deck's defs.

    ``prefix`` is ``compose_prefix(deck_id)`` in S3, ``""`` for a Local file name.
    """
    return f"{prefix}{slug}_{int(epoch)}.json"


def compose_slug_epoch(key: str, prefix: str = "") -> Optional[SlugEpoch]:
    """``(slug, epoch)`` of ``{prefix}{slug}_{epoch}.json`` (defs included), or None."""
    if not key.startswith(prefix):
        return None
    m = COMPOSE_NAME_RE.fullmatch(key[len(prefix):])
    return (m.group(1), int(m.group(2))) if m else None


def latest_compose_keys(keys: Iterable[str], prefix: str = "") -> dict[str, str]:
    """Map slug → latest compose key under ``prefix`` (highest epoch wins). The deck's
    defs is the entry ``COMPOSE_DEFS``."""
    return latest_by_slug(keys, lambda key: compose_slug_epoch(key, prefix))


def superseded_compose_keys(keys: Iterable[str], prefix: str, slugs: Iterable[str], epoch: int) -> list[str]:
    """Compose keys under ``prefix`` of ``slugs`` (``COMPOSE_DEFS`` for the defs) with an
    epoch below ``epoch``: what a write of those slugs at ``epoch`` replaces."""
    wanted = set(slugs)
    out = []
    for key in keys:
        se = compose_slug_epoch(key, prefix)
        if se and se[0] in wanted and se[1] < epoch:
            out.append(key)
    return out


# --- HTML decks: html/{deck_id}/... ---


def output_key(deck_id: str) -> str:
    """A fresh key for a built deck: ``html/{deck_id}/{uuid4}.html``."""
    return f"{HTML_PREFIX}{_deck(deck_id)}/{uuid.uuid4()}.html"


def preview_prefix(deck_id: str) -> str:
    """``html/{deck_id}/preview/`` — every per-slide preview of the deck lives under it."""
    return f"{HTML_PREFIX}{_deck(deck_id)}/preview/"


def preview_key(deck_id: str, slug: str, epoch: int) -> str:
    """``html/{deck_id}/preview/{slug}_{epoch}.html``."""
    _slug(slug)
    return f"{preview_prefix(deck_id)}{slug}_{int(epoch)}.html"


def html_preview_slug_epoch(key: str) -> Optional[SlugEpoch]:
    """``(slug, epoch)`` of an HTML preview key, or None for any other key."""
    return _search(_HTML_PREVIEW_RE, key)


def build_html_preview_key_map(keys: Iterable[str]) -> dict[str, str]:
    """Map slug → latest preview key (highest epoch wins); other keys are ignored."""
    return latest_by_slug(keys, html_preview_slug_epoch)


def png_prefix(deck_id: str) -> str:
    """``html/{deck_id}/png/`` — every browser-check PNG of the deck lives under it."""
    return f"{HTML_PREFIX}{_deck(deck_id)}/png/"


def png_key(deck_id: str, slug: str, epoch: int) -> str:
    """``html/{deck_id}/png/{slug}_{epoch}.png``."""
    _slug(slug)
    return f"{png_prefix(deck_id)}{slug}_{int(epoch)}.png"


def png_slug_epoch(key: str) -> Optional[SlugEpoch]:
    """``(slug, epoch)`` of a PNG key, or None for any other key."""
    return _search(_PNG_RE, key)


def build_html_png_key_map(keys: Iterable[str]) -> dict[str, str]:
    """Map slug → latest PNG key (highest epoch wins); other keys are ignored."""
    return latest_by_slug(keys, png_slug_epoch)


def template_cache_object_key(cache_key: str, rel: str) -> str:
    """S3 key of one template-conversion cache file.

    ``rel`` must be ``theme.css``, ``template.json`` or ``layouts/<name>.svg``;
    anything else (other files, nested paths, ``..``) raises ValueError.
    """
    if not isinstance(cache_key, str) or not _CACHE_KEY_RE.fullmatch(cache_key):
        raise ValueError(f"invalid template cache key: {cache_key!r}")
    if not isinstance(rel, str) or not (rel in _CACHE_FILES or _CACHE_LAYOUT_RE.fullmatch(rel)):
        raise ValueError(f"not a template cache file: {rel!r}")
    return f"{TEMPLATE_CACHE_PREFIX}{cache_key}/{rel}"
