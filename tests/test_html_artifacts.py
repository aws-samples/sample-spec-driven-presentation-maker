# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""shared.html_artifacts — S3 key layout of HTML deck artifacts."""

import re

import pytest

from shared import html_artifacts as ha


def test_output_key_is_a_fresh_uuid_under_html_prefix():
    a, b = ha.output_key("d1"), ha.output_key("d1")
    assert a != b
    assert re.fullmatch(r"html/d1/[0-9a-f-]{36}\.html", a)
    assert a.startswith(ha.HTML_PREFIX)


def test_preview_keys():
    assert ha.preview_prefix("d1") == "html/d1/preview/"
    assert ha.preview_key("d1", "intro", 123) == "html/d1/preview/intro_123.html"


@pytest.mark.parametrize("deck_id", ["", "../x", "a/b", None])
def test_invalid_deck_ids_are_rejected(deck_id):
    with pytest.raises(ValueError):
        ha.output_key(deck_id)


@pytest.mark.parametrize("slug", ["", "Intro", "../x", "a/b"])
def test_invalid_slugs_are_rejected(slug):
    with pytest.raises(ValueError):
        ha.preview_key("d1", slug, 1)


def test_preview_key_map_latest_epoch_wins_and_ignores_other_keys():
    keys = [
        "html/d1/preview/intro_100.html",
        "html/d1/preview/intro_200.html",
        "html/d1/preview/demo-1_150.html",
        "html/d1/preview/notes.txt",
        "html/d1/0b6f3a52-1111-4222-8333-444455556666.html",
    ]
    assert ha.build_html_preview_key_map(keys) == {
        "intro": "html/d1/preview/intro_200.html",
        "demo-1": "html/d1/preview/demo-1_150.html",
    }


def test_png_keys_and_latest_epoch_map():
    assert ha.png_prefix("d1") == "html/d1/png/"
    assert ha.png_key("d1", "intro", 123) == "html/d1/png/intro_123.png"
    assert ha.png_slug_epoch("html/d1/png/demo-1_7.png") == ("demo-1", 7)
    assert ha.png_slug_epoch("html/d1/preview/intro_100.html") is None
    keys = [
        "html/d1/png/intro_100.png",
        "html/d1/png/intro_200.png",
        "html/d1/png/demo-1_150.png",
        "html/d1/preview/intro_300.html",
        "html/d1/preview/cover_300.png",
        "html/d1/png/notes.txt",
    ]
    assert ha.build_html_png_key_map(keys) == {
        "intro": "html/d1/png/intro_200.png",
        "demo-1": "html/d1/png/demo-1_150.png",
    }
    assert ha.build_html_preview_key_map(keys) == {"intro": "html/d1/preview/intro_300.html"}
    with pytest.raises(ValueError):
        ha.png_key("d1", "../x", 1)


def test_template_cache_object_key_allowlist():
    assert ha.template_cache_object_key("ab12", "theme.css") == "template-html-cache/ab12/theme.css"
    assert ha.template_cache_object_key("ab12", "template.json") == "template-html-cache/ab12/template.json"
    assert ha.template_cache_object_key("ab12", "layouts/01-Title_Slide.ground.svg") == (
        "template-html-cache/ab12/layouts/01-Title_Slide.ground.svg"
    )
    for rel in ("other.json", "layouts/../x.svg", "layouts/a/b.svg", "layouts/.hidden.svg",
                "layouts/a.png", "/theme.css", ".render-x/layouts/a.svg"):
        with pytest.raises(ValueError):
            ha.template_cache_object_key("ab12", rel)
    for key in ("", "../x", "ABC", "ab/12"):
        with pytest.raises(ValueError):
            ha.template_cache_object_key(key, "theme.css")


def test_html_content_type():
    assert ha.HTML_CONTENT_TYPE == "text/html; charset=utf-8"
