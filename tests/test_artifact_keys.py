# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""shared.artifact_keys — the latest-epoch selector, slide previews and compose keys.

HTML deck keys and the template cache are covered by tests/test_html_artifacts.py.
"""

from shared import artifact_keys as ak


def test_latest_by_slug_highest_epoch_wins_and_first_wins_on_ties():
    parse = {"a1": ("a", 1), "a3": ("a", 3), "a2": ("a", 2), "b5": ("b", 5), "b5'": ("b", 5)}
    assert ak.latest_by_slug(["a1", "a3", "a2", "b5", "b5'", "zz"], parse.get) == {"a": "a3", "b": "b5"}
    assert ak.latest_by_slug([], parse.get) == {}


def test_slide_preview_keys():
    assert ak.slide_preview_slug_epoch("previews/d1/intro_100.webp") == ("intro", 100)
    assert ak.slide_preview_slug_epoch("previews/d1/slide_01_100.webp") == ("slide_01", 100)
    assert ak.slide_preview_slug_epoch("previews/d1/intro.webp") is None
    keys = [
        "previews/d1/intro_100.webp",
        "previews/d1/intro_200.webp",
        "previews/d1/demo-1_150.png",
        "previews/d1/slide_01_50.webp",
        "previews/d1/slide_01_60.webp",
        "previews/d1/thumbnail_300.webp",
        "previews/d1/notes.txt",
    ]
    assert ak.build_slide_key_map(keys) == {
        "intro": "previews/d1/intro_200.webp",
        "demo-1": "previews/d1/demo-1_150.png",
        "slide_01": "previews/d1/slide_01_60.webp",
        "thumbnail": "previews/d1/thumbnail_300.webp",
    }


def test_slide_preview_of_a_leading_dash_slug_is_read_without_the_dash():
    """Current behaviour, kept on purpose (findings F1): the search is not anchored at "/"."""
    assert ak.build_slide_key_map(["previews/d1/-intro_200.webp"]) == {"intro": "previews/d1/-intro_200.webp"}


def test_compose_keys_build_and_parse():
    prefix = ak.compose_prefix("d1")
    assert prefix == "decks/d1/compose/"
    assert ak.compose_key(prefix, "intro", 100) == "decks/d1/compose/intro_100.json"
    assert ak.compose_key(prefix, ak.COMPOSE_DEFS, 7) == "decks/d1/compose/defs_7.json"
    assert ak.compose_key("", "-intro", 5) == "-intro_5.json"
    assert ak.compose_slug_epoch("decks/d1/compose/intro_100.json", prefix) == ("intro", 100)
    assert ak.compose_slug_epoch("decks/d1/compose/slide_3_100.json", prefix) == ("slide_3", 100)
    assert ak.compose_slug_epoch("decks/d1/compose/defs_7.json", prefix) == ("defs", 7)
    assert ak.compose_slug_epoch("-intro_5.json") == ("-intro", 5)
    for key in ("decks/d2/compose/intro_1.json", "decks/d1/compose/intro.json",
                "decks/d1/compose/_1.json", "decks/d1/compose/intro_1.json.tmp"):
        assert ak.compose_slug_epoch(key, prefix) is None


def test_latest_compose_keys_mixed_slugs():
    prefix = ak.compose_prefix("d1")
    keys = [
        f"{prefix}intro_100.json",
        f"{prefix}intro_300.json",
        f"{prefix}intro_200.json",
        f"{prefix}intro-2_400.json",
        f"{prefix}slide_1_50.json",
        f"{prefix}slide_10_40.json",
        f"{prefix}defs_100.json",
        f"{prefix}defs_250.json",
        "decks/d2/compose/intro_999.json",
        f"{prefix}notes.txt",
    ]
    assert ak.latest_compose_keys(keys, prefix) == {
        "intro": f"{prefix}intro_300.json",
        "intro-2": f"{prefix}intro-2_400.json",
        "slide_1": f"{prefix}slide_1_50.json",
        "slide_10": f"{prefix}slide_10_40.json",
        ak.COMPOSE_DEFS: f"{prefix}defs_250.json",
    }
    assert ak.latest_compose_keys(["intro_1.json", "intro_2.json"]) == {"intro": "intro_2.json"}


def test_compose_lookup_is_exact_not_a_prefix_match():
    """slug ``slide`` vs legacy ``slide_N_*.json``, slug ``intro`` vs ``intro_2_*.json``."""
    prefix = ak.compose_prefix("d1")
    keys = [f"{prefix}slide_3_500.json", f"{prefix}slide_100.json", f"{prefix}intro_2_900.json"]
    latest = ak.latest_compose_keys(keys, prefix)
    assert latest["slide"] == f"{prefix}slide_100.json"
    assert "intro" not in latest


def test_superseded_compose_keys():
    prefix = ak.compose_prefix("d1")
    keys = [
        f"{prefix}intro_100.json",
        f"{prefix}intro_300.json",
        f"{prefix}intro_2_100.json",
        f"{prefix}slide_1_100.json",
        f"{prefix}slide_100.json",
        f"{prefix}defs_100.json",
        f"{prefix}defs_300.json",
        f"{prefix}intro.json",
    ]
    assert ak.superseded_compose_keys(keys, prefix, ["intro"], 300) == [f"{prefix}intro_100.json"]
    assert ak.superseded_compose_keys(keys, prefix, ["slide"], 300) == [f"{prefix}slide_100.json"]
    assert ak.superseded_compose_keys(keys, prefix, [ak.COMPOSE_DEFS], 300) == [f"{prefix}defs_100.json"]
    assert ak.superseded_compose_keys(keys, prefix, ["intro", ak.COMPOSE_DEFS], 100) == []
    assert ak.superseded_compose_keys(["intro_1.json", "intro_2_1.json"], "", ["intro"], 5) == ["intro_1.json"]
