# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""S3 key layout of HTML deck artifacts (shared by servers/remote and api).

    html/{deck_id}/{uuid}.html                    built deck (DDB htmlS3Key)
    html/{deck_id}/preview/{slug}_{epoch}.html    static per-slide thumbnail (latest epoch wins)
    template-html-cache/{cache_key}/{rel}         template conversion cache

``html/`` is served only through presigned URLs: it is in no CloudFront
behaviour and not in the CloudFront OAC bucket-policy grant.
"""

import re
import uuid
from typing import Iterable

HTML_PREFIX = "html/"
HTML_CONTENT_TYPE = "text/html; charset=utf-8"
TEMPLATE_CACHE_PREFIX = "template-html-cache/"

_DECK_ID_RE = re.compile(r"[A-Za-z0-9_-]+")
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-_]*")
# Matches {slug}_{epoch}.html at the end of a preview key (same slug grammar as
# shared/preview._PREVIEW_RE).
_PREVIEW_RE = re.compile(r"([a-z0-9][a-z0-9-_]*)_(\d+)\.html$")
_CACHE_KEY_RE = re.compile(r"[0-9a-f]{1,64}")
_CACHE_FILES = frozenset({"theme.css", "template.json"})
_CACHE_LAYOUT_RE = re.compile(r"layouts/[A-Za-z0-9_-][A-Za-z0-9_.-]*\.svg")


def _deck(deck_id: str) -> str:
    if not isinstance(deck_id, str) or not _DECK_ID_RE.fullmatch(deck_id):
        raise ValueError(f"invalid deck id: {deck_id!r}")
    return deck_id


def output_key(deck_id: str) -> str:
    """A fresh key for a built deck: ``html/{deck_id}/{uuid4}.html``."""
    return f"{HTML_PREFIX}{_deck(deck_id)}/{uuid.uuid4()}.html"


def preview_prefix(deck_id: str) -> str:
    """``html/{deck_id}/preview/`` — every per-slide preview of the deck lives under it."""
    return f"{HTML_PREFIX}{_deck(deck_id)}/preview/"


def preview_key(deck_id: str, slug: str, epoch: int) -> str:
    """``html/{deck_id}/preview/{slug}_{epoch}.html``."""
    if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
        raise ValueError(f"invalid slug: {slug!r}")
    return f"{preview_prefix(deck_id)}{slug}_{int(epoch)}.html"


def build_html_preview_key_map(keys: Iterable[str]) -> dict[str, str]:
    """Map slug → latest preview key (highest epoch wins); other keys are ignored."""
    best: dict[str, tuple[int, str]] = {}
    for key in keys:
        m = _PREVIEW_RE.search(key)
        if not m:
            continue
        slug, epoch = m.group(1), int(m.group(2))
        if slug not in best or epoch > best[slug][0]:
            best[slug] = (epoch, key)
    return {slug: key for slug, (_, key) in best.items()}


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
