# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Presigned S3 URLs for HTML deck artifacts (pure helpers for the API Lambda).

# Security: HTML decks run scripts, so they are served only from the S3
# regional endpoint (``<bucket>.s3.<region>.amazonaws.com``), a different
# origin from the Web UI. The Web UI CloudFront distribution serves
# ``previews/*``, ``decks/*/*`` and ``pptx/*`` on the app origin; signing an
# ``.html`` key through it would run deck scripts with the app's origin.
# ``html/`` is therefore in no CloudFront behaviour and not in the OAC grant,
# and only ``html/**.html`` keys may be presigned here (forcing a text/html
# response type on any other object, e.g. a user upload, would turn it into
# a page on the bucket origin).

Imported as ``html_presign`` inside the Lambda bundle and as
``api.html_presign`` in tests.
"""

import unicodedata
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import quote

import boto3
from botocore.config import Config as BotoConfig

from shared.html_artifacts import HTML_CONTENT_TYPE, HTML_PREFIX

# Purposes callers may request from GET /decks/{id}/html → URL lifetime (s).
PURPOSES: Dict[str, int] = {"present": 14400, "download": 900}
# In-app viewing (get_deck htmlUrl / previewUrl, deck-list thumbnails, search).
VIEW_EXPIRY = 900
DEFAULT_SLIDE_SIZE: Dict[str, int] = {"width": 1920, "height": 1080}

_EXPIRY: Dict[str, int] = {"view": VIEW_EXPIRY, **PURPOSES}
_MAX_NAME_CHARS = 120
_STRIP_CHARS = frozenset('/\\"\'')


def html_presign_client(region: str) -> Any:
    """S3 client that signs SigV4 URLs on the regional virtual-host endpoint."""
    return boto3.client(
        "s3",
        region_name=region,
        endpoint_url=f"https://s3.{region}.amazonaws.com",
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )


def safe_download_name(name: Any) -> str:
    """File name for a downloaded deck: no control chars, path separators or quotes; ends in .html."""
    text = "".join(
        ch for ch in str(name or "")
        if ch not in _STRIP_CHARS and not unicodedata.category(ch).startswith("C")
    )
    text = " ".join(text.split()).strip(" .")
    if text.lower().endswith(".html"):
        text = text[:-5].rstrip(" .")
    text = text[:_MAX_NAME_CHARS].rstrip(" .")
    return f"{text or 'deck'}.html"


def _content_disposition(deck_name: str) -> str:
    filename = safe_download_name(deck_name)
    ascii_stem = filename[:-5].encode("ascii", "ignore").decode("ascii").strip(" .")
    ascii_name = f"{ascii_stem or 'deck'}.html"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def presign_params(bucket: str, key: str, purpose: str, deck_name: str = "") -> Tuple[Dict[str, str], int]:
    """get_object Params and expiry for an HTML artifact.

    ``purpose`` is ``view`` (in-app), ``present`` or ``download``. Raises
    ValueError for an unknown purpose or a key outside ``html/**.html``.
    """
    if purpose not in _EXPIRY:
        raise ValueError(f"unknown purpose: {purpose!r}")
    if not isinstance(key, str) or not key.startswith(HTML_PREFIX) or not key.endswith(".html") or ".." in key:
        raise ValueError(f"not an HTML artifact key: {key!r}")
    disposition = _content_disposition(deck_name) if purpose == "download" else "inline"
    params = {
        "Bucket": bucket,
        "Key": key,
        "ResponseContentType": HTML_CONTENT_TYPE,
        "ResponseContentDisposition": disposition,
    }
    return params, _EXPIRY[purpose]


def presigned_html_url(client: Any, bucket: str, key: str, purpose: str, deck_name: str = "") -> Tuple[str, int]:
    """(presigned GET URL, expires_in seconds) for an HTML artifact; see presign_params."""
    params, expires = presign_params(bucket, key, purpose, deck_name)
    return client.generate_presigned_url("get_object", Params=params, ExpiresIn=expires), expires


def is_html_deck(deck_json: Any) -> bool:
    """True when deck.json declares outputFormat "html" (absent or anything else → PPTX)."""
    return isinstance(deck_json, dict) and deck_json.get("outputFormat") == "html"


def slide_size(deck_json: Any) -> Dict[str, Any]:
    """{width, height} from deck.json slideSize, defaulting to 1920×1080."""
    size = deck_json.get("slideSize") if isinstance(deck_json, dict) else None
    if not isinstance(size, dict):
        return dict(DEFAULT_SLIDE_SIZE)
    out: Dict[str, Any] = {}
    for dim in ("width", "height"):
        value = size.get(dim)
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
        out[dim] = value if ok else DEFAULT_SLIDE_SIZE[dim]
    return out


def html_slide_slugs(outline_slugs: List[str], slide_keys: Iterable[str], deck_id: str) -> List[str]:
    """Slugs of an HTML deck in outline order, keeping those whose slides/{slug}.html exists.

    Without outline slugs, the listed ``.html`` stems are returned in key order.
    """
    prefix = f"decks/{deck_id}/slides/"
    stems: List[str] = []
    for key in slide_keys:
        if key.startswith(prefix) and key.endswith(".html"):
            stem = key[len(prefix):-5]
            if stem and "/" not in stem:
                stems.append(stem)
    if not outline_slugs:
        return stems
    present = set(stems)
    return [slug for slug in outline_slugs if slug in present]
