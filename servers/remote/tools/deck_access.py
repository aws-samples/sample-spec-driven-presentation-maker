# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""S3 storage for the deck viewer (``sdpm.tools.apps.deck.DeckAccess``).

Every operation starts with the caller's permission check (``open``): ``read`` to view a
deck, ``edit_slide`` to comment on it, the same permissions the Web UI's API uses. Reviews
are written the way the cloud API route writes them (old files under ``reviews/`` deleted, the
new object created only if absent), through the shared contract in ``shared/review.py``.
Previews are read as they are: a host gives a view's call about 20 seconds, so nothing here
waits for a preview still being rendered.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from sdpm.tools.apps.deck import DECK_FILES, DeckAccess
from shared.artifact_keys import build_html_png_key_map, build_slide_key_map, png_prefix
from shared.review import create_review

logger = logging.getLogger("sdpm.deck_access")


def make(get_storage: Callable[[], Any], check: Callable[[str, str], None]) -> DeckAccess:
    """A ``DeckAccess`` over ``get_storage()`` (read at call time) that runs ``check(deck_id, action)`` first."""

    def open_(deck_id: str, write: bool) -> None:
        check(deck_id, "edit_slide" if write else "read")

    def read_text(deck_id: str, rel: str) -> str | None:
        if rel not in DECK_FILES:
            return None
        try:
            return get_storage().download_file_from_pptx_bucket(key=f"decks/{deck_id}/{rel}").decode("utf-8")
        except Exception:  # noqa: BLE001 - missing or unreadable is "no file"
            return None

    def slide_slugs(deck_id: str) -> set[str]:
        prefix = f"decks/{deck_id}/slides/"
        storage = get_storage()
        slugs = set()
        for key in storage.list_files(prefix=prefix, bucket=storage.pptx_bucket):
            name = key[len(prefix):]
            if "/" not in name and name.endswith((".json", ".html")):
                slugs.add(name.rsplit(".", 1)[0])
        return slugs

    def previews(deck_id: str, fmt: str) -> dict[str, str]:
        storage = get_storage()
        if fmt == "html":
            return build_html_png_key_map(storage.list_files(prefix=png_prefix(deck_id), bucket=storage.pptx_bucket))
        return build_slide_key_map(storage.list_files(prefix=f"previews/{deck_id}/", bucket=storage.pptx_bucket))

    def read_preview(deck_id: str, fmt: str, slug: str, stamp: str) -> bytes | None:
        # ``stamp`` is the S3 key previews() listed under this deck's prefix.
        try:
            return get_storage().download_file_from_pptx_bucket(key=stamp)
        except Exception as e:  # noqa: BLE001 - a preview that cannot be read is "no preview"
            logger.warning("preview %s of %s unreadable: %s", slug, deck_id, e)
            return None

    def submit_review(deck_id: str, body: dict) -> dict:
        storage = get_storage()
        try:
            deck_json = storage.get_deck_json(deck_id)
        except Exception:  # noqa: BLE001 - the default slide size applies
            deck_json = {}
        slugs = slide_slugs(deck_id)

        def clear() -> None:
            storage.delete_files(prefix=f"decks/{deck_id}/reviews/")

        def write_new(path: str, data: bytes) -> bool:
            return storage.upload_file_if_absent(
                key=f"decks/{deck_id}/{path}", data=data, content_type="application/json; charset=utf-8",
            )

        return create_review(body, deck_json, lambda slug: slug in slugs, clear=clear, write_new=write_new)

    return DeckAccess(
        open=open_,
        read_text=read_text,
        slide_slugs=slide_slugs,
        previews=previews,
        read_preview=read_preview,
        submit_review=submit_review,
    )
