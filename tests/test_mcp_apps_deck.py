# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The deck viewer's operations in ``sdpm.tools.apps.deck`` (no server), on a dict-backed deck."""

from __future__ import annotations

import base64
import io
import json

import pytest
from PIL import Image

from sdpm.engine.schema import validate_specs
from sdpm.tools.apps import deck
from shared.review import slide_size_of

OUTLINE = """# Deck
## Part one
- [cover] The cover
  - body: title
- [why] Why now
- [why] Why now again
- [1: Legacy] skipped
## Part two
- [ask] The ask
"""


def _deck_json() -> dict:
    return {
        "template": "blank-dark",
        "fonts": {"fullwidth": "Noto Sans JP", "halfwidth": "Amazon Ember"},
        "defaultTextColor": "#A1B2C3",
        "slideSize": {"width": 1280, "height": 720, "ptPerPx": 0.75},
    }


def _png(w: int, h: int, mode: str = "RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, (w, h), (10, 20, 30) if mode == "RGB" else (10, 20, 30, 0)).save(out, format="PNG")
    return out.getvalue()


class Fake:
    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files = {"deck.json": json.dumps(_deck_json()), "specs/brief.md": "Brief line\n",
                      "specs/outline.md": OUTLINE} if files is None else files
        self.built = {"cover", "why"}
        self.images = {"cover": _png(2560, 1440)}
        self.opened: list[tuple[str, bool]] = []
        self.reviews: list[tuple[str, dict]] = []
        self.environment: dict | None = {"status": "unavailable", "missing": ["soffice"], "install": "x", "note": "n"}

    def access(self, **over) -> deck.DeckAccess:
        def open_(deck_id, write):
            self.opened.append((deck_id, write))
            if deck_id == "nope":
                raise ValueError("No deck at nope")

        kw = dict(
            open=open_,
            read_text=lambda d, rel: self.files.get(rel),
            slide_slugs=lambda d: set(self.built),
            previews=lambda d, fmt: {s: f"stamp-{s}" for s in self.images},
            read_preview=lambda d, fmt, slug, stamp: self.images.get(slug),
            submit_review=lambda d, body: self.reviews.append((d, body)) or {"id": "r", "message": "m"},
            preview_environment=lambda fmt: self.environment,
        )
        kw.update(over)
        return deck.DeckAccess(**kw)


# --- deck_view ---------------------------------------------------------------------------


def test_the_payload_in_outline_order() -> None:
    fake = Fake()
    got = deck.deck_view("d1", fake.access())
    assert fake.opened == [("d1", False)]
    assert got["deck_id"] == "d1" and got["format"] == "pptx" and got["slide_size"] == [1280, 720]
    assert got["brief"] == "Brief line\n" and got["outline_text"] == OUTLINE
    assert [e["title"] for e in got["outline"] if e["type"] == "section"] == ["Part one", "Part two"]
    assert got["slides"] == [
        {"slug": "cover", "message": "The cover", "built": True, "preview": "stamp-cover"},
        {"slug": "why", "message": "Why now", "built": True, "preview": None},
        {"slug": "ask", "message": "The ask", "built": False, "preview": None},
    ]
    assert got["check"] == validate_specs(_deck_json(), OUTLINE)
    assert got["preview_environment"] == fake.environment  # "why" is built and has no preview


def test_a_valid_deck_checks_ok_and_needs_no_environment() -> None:
    fake = Fake()
    fake.files["specs/outline.md"] = "- [cover] The cover\n  - body: b\n  - visual: v\n  - evidence: e\n"
    got = deck.deck_view("d1", fake.access())
    assert got["check"]["ok"] is True, got["check"]
    assert got["preview_environment"] is None


@pytest.mark.parametrize(("files", "errors"), [
    ({"specs/outline.md": OUTLINE}, ["deck.json is missing"]),
    ({}, ["deck.json is missing", "specs/outline.md is missing"]),
    ({"deck.json": "{", "specs/outline.md": OUTLINE}, ["deck.json is invalid JSON"]),
    ({"deck.json": "[1]", "specs/outline.md": OUTLINE}, ["deck.json must contain an object"]),
    ({"deck.json": "{}"}, ["specs/outline.md is missing"]),
])
def test_unusable_files_give_the_check_specs_errors(files, errors) -> None:
    got = deck.deck_view("d1", Fake(files).access())
    assert got["check"] == {"ok": False, "errors": errors, "warnings": [], "slugs": []}


def test_an_html_deck_and_a_bad_format() -> None:
    fake = Fake()
    asked = []
    fake.files["deck.json"] = json.dumps({**_deck_json(), "outputFormat": "html"})
    deck.deck_view("d1", fake.access(previews=lambda d, fmt: asked.append(fmt) or {}))
    fake.files["deck.json"] = json.dumps({**_deck_json(), "outputFormat": "pdf"})
    got = deck.deck_view("d1", fake.access(previews=lambda d, fmt: asked.append(fmt) or {}))
    assert asked == ["html", "pptx"]
    assert got["check"]["ok"] is False


def test_an_unknown_deck_raises() -> None:
    with pytest.raises(ValueError):
        deck.deck_view("nope", Fake().access())


@pytest.mark.parametrize("value", ["", "   ", None, 3, "a\x00b", "x" * 1025])
def test_bad_deck_ids(value) -> None:
    fake = Fake()
    with pytest.raises(ValueError):
        deck.deck_view(value, fake.access())
    assert fake.opened == []


def test_a_good_deck_id_is_kept_as_given() -> None:
    assert deck._deck_id("/home/me/My Deck") == "/home/me/My Deck"
    assert deck._deck_id("x" * 1024)


# --- slide_preview -----------------------------------------------------------------------


@pytest.mark.parametrize("slug", ["../x", "", "A", None, "a/b"])
def test_slide_preview_refuses_a_bad_slug(slug) -> None:
    with pytest.raises(ValueError):
        deck.slide_preview("d1", slug, Fake().access())


def test_slide_preview_is_a_downscaled_jpeg() -> None:
    got = deck.slide_preview("d1", "cover", Fake().access())
    assert got["available"] and got["mimeType"] == "image/jpeg" and got["stamp"] == "stamp-cover"
    img = Image.open(io.BytesIO(base64.b64decode(got["data"])))
    assert img.format == "JPEG" and img.size == (1280, 720)


def test_slide_preview_flattens_transparency() -> None:
    fake = Fake()
    fake.images["cover"] = _png(100, 50, "RGBA")
    got = deck.slide_preview("d1", "cover", fake.access())
    img = Image.open(io.BytesIO(base64.b64decode(got["data"])))
    assert img.size == (100, 50) and img.getpixel((5, 5))[0] > 240


def test_slide_preview_without_an_image_or_with_garbage() -> None:
    fake = Fake()
    assert deck.slide_preview("d1", "why", fake.access()) == {"slug": "why", "available": False}
    fake.images["cover"] = b"not an image"
    assert deck.slide_preview("d1", "cover", fake.access()) == {"slug": "cover", "available": False}


# --- outline_edit ------------------------------------------------------------------------


def test_outline_edit_is_a_diff_and_writes_nothing() -> None:
    fake = Fake()
    base = "".join(f"- [s{i}] line {i}\n" for i in range(20)) + "- [a] old\n"
    fake.files["specs/outline.md"] = base
    got = deck.outline_edit("d1", base, base.replace("- [a] old", "- [a] new"), fake.access())
    assert "```diff\n--- a/specs/outline.md\n+++ b/specs/outline.md\n" in got["message"]
    assert "\n-- [a] old\n+- [a] new\n" in got["message"]
    assert "check_specs" in got["message"] and "changed after" not in got["message"]
    assert (got["added"], got["deleted"]) == (1, 1)
    assert fake.files["specs/outline.md"] == base
    assert fake.opened == [("d1", False)]


def test_outline_edit_sends_the_whole_text_when_it_is_shorter() -> None:
    fake = Fake()
    base = "- [a] one\n- [b] two\n"
    text = "- [a] ```code``` here\n"
    got = deck.outline_edit("d1", base, text, fake.access())
    assert "Write this text to specs/outline.md" in got["message"]
    assert "````markdown\n- [a] ```code``` here\n````" in got["message"]


def test_outline_edit_says_when_the_file_changed_meanwhile() -> None:
    fake = Fake()
    base = "".join(f"- [s{i}] line {i}\n" for i in range(20))
    fake.files["specs/outline.md"] = base + "- [late] added by the agent\n"
    got = deck.outline_edit("d1", base, base.replace("line 3", "line three"), fake.access())
    assert got["message"].endswith("the diff is against the version I saw.")
    short = deck.outline_edit("d1", "- [a] x\n", "- [a] y\n", fake.access())
    assert short["message"].endswith("my text replaces the version I saw.")


@pytest.mark.parametrize(("base", "text"), [
    ("same", "same"),
    (None, "x"),
    ("x", 3),
    ("x", "y" * (deck.MAX_TEXT + 1)),
])
def test_outline_edit_refuses_no_change_or_bad_text(base, text) -> None:
    with pytest.raises(ValueError):
        deck.outline_edit("d1", base, text, Fake().access())


# --- submit_review -----------------------------------------------------------------------


def test_submit_review_opens_for_writing_and_passes_the_body_on() -> None:
    fake = Fake()
    body = {"note": "n", "comments": []}
    assert deck.submit_review("d1", body, fake.access()) == {"id": "r", "message": "m"}
    assert fake.opened == [("d1", True)]
    assert fake.reviews == [("d1", body)]


@pytest.mark.parametrize("review", [None, [], "x"])
def test_submit_review_needs_an_object(review) -> None:
    fake = Fake()
    with pytest.raises(ValueError):
        deck.submit_review("d1", review, fake.access())
    assert fake.opened == []


@pytest.mark.parametrize("deck_json", [
    {}, None, [1], {"slideSize": "big"},
    {"slideSize": {"width": 1280, "height": 720}},
    {"slideSize": {"width": 1280.7, "height": 720.2}},
    {"slideSize": {"height": 720}},
    {"slideSize": {"width": True, "height": 0}},
    {"slideSize": {"width": float("nan"), "height": float("inf")}},
])
def test_slide_size_matches_the_review_contract(deck_json) -> None:
    assert deck._slide_size(deck_json) == slide_size_of(deck_json)
