# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The guide collection: where its sources come from, and how they merge into one object.

Resolution has the same three layers as styles and templates, and the merge gives a
user's guide the name, so it shadows the bundled guide for listing, read-by-name and
automatic hand-over alike. An invalid entry is reported and never wins a name.
"""

import os
from pathlib import Path

import pytest

from sdpm.api import get_guides_dirs, get_styles_dirs
from sdpm.knowledge.reference import BUNDLED_GUIDES_DIR, GUIDE_MAX_BYTES, build_collection


def test_bundled_dir_is_last() -> None:
    dirs = get_guides_dirs()
    assert dirs[-1] == BUNDLED_GUIDES_DIR


def test_env_override_comes_first(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SDPM_GUIDES_DIR", str(tmp_path))
    assert get_guides_dirs()[0] == tmp_path


def test_user_dir_sits_between_env_and_bundled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SDPM_GUIDES_DIR", raising=False)
    dirs = get_guides_dirs()
    assert dirs == [tmp_path / "sdpm" / "guides", BUNDLED_GUIDES_DIR]


def test_user_dir_is_named_guides_not_user_guides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SDPM_GUIDES_DIR", raising=False)
    assert get_guides_dirs()[0].name == "guides"


def test_multiple_env_paths_keep_their_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    monkeypatch.setenv("SDPM_GUIDES_DIR", f"{first}{os.pathsep}{second}")
    assert get_guides_dirs()[:2] == [first, second]


def test_guides_and_styles_resolve_independently(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SDPM_GUIDES_DIR", str(tmp_path / "g"))
    monkeypatch.delenv("SDPM_STYLES_DIR", raising=False)
    assert get_guides_dirs()[0] == tmp_path / "g"
    assert get_styles_dirs()[0] != tmp_path / "g"


# ---------------------------------------------------------------------------
# build_collection — the one merged object behind every guide surface
# ---------------------------------------------------------------------------


def entry(name: str, front: str, body: str = "Body.\n", location: str | None = None) -> dict[str, str]:
    return {"name": name, "location": location or f"/store/{name}.md", "text": f"---\n{front}\n---\n\n{body}"}


def valid_entry(name: str, tags: str = "[composer]", body: str = "Body.\n", **kw) -> dict[str, str]:
    return entry(name, f"description: {name} does a thing.\ntags: {tags}", body=body, **kw)


class TestMerge:
    def test_user_guide_shadows_the_bundled_guide_of_that_name(self) -> None:
        collection = build_collection([
            ("user", [valid_entry("grid", body="Mine.\n", location="/home/u/guides/grid.md")]),
            ("builtin", [valid_entry("grid", body="Theirs.\n")]),
        ])
        assert collection["valid"]["grid"]["body"] == "Mine.\n"
        assert collection["valid"]["grid"]["source"] == "user"

    def test_bundled_guide_survives_when_the_user_has_no_guide_of_that_name(self) -> None:
        collection = build_collection([
            ("user", [valid_entry("mine")]),
            ("builtin", [valid_entry("table")]),
        ])
        assert set(collection["valid"]) == {"mine", "table"}
        assert collection["valid"]["table"]["source"] == "builtin"

    def test_entry_carries_the_listing_fields(self) -> None:
        collection = build_collection([("builtin", [entry("story-line", "description: Why.\ntags: [orchestrator]\nalways: true")])])
        assert collection["valid"]["story-line"] == {
            "name": "story-line",
            "description": "Why.",
            "tags": ["orchestrator"],
            "always": True,
            "body": "Body.\n",
            "source": "builtin",
        }

    def test_first_group_wins_across_several_user_directories(self) -> None:
        collection = build_collection([
            ("user", [valid_entry("grid", body="First.\n")]),
            ("user", [valid_entry("grid", body="Second.\n")]),
        ])
        assert collection["valid"]["grid"]["body"] == "First.\n"

    def test_a_shadowed_entry_is_not_reported_as_invalid(self) -> None:
        # The bundled copy is unreachable, so its metadata is never parsed.
        collection = build_collection([
            ("user", [valid_entry("grid")]),
            ("builtin", [entry("grid", "description: broken\ntags: [nope]")]),
        ])
        assert collection["invalid"] == []
        assert collection["valid"]["grid"]["source"] == "user"

    def test_no_sources_is_an_empty_collection(self) -> None:
        assert build_collection([]) == {"valid": {}, "invalid": []}


class TestInvalidEntries:
    """REQ-2.6 from a user-store entry: reported, never silently degraded."""

    CASES = [
        ("a.b", "description: d\ntags: [composer]", "name"),
        ("nofront", None, "frontmatter"),
        ("unknown", "description: d\ntags: [composer]\ncategory: guide", "unknown-key"),
        ("nodesc", "tags: [composer]", "description"),
        ("notags", "description: d", "tags"),
        ("badtag", "description: d\ntags: [review]", "tag-value"),
        ("badalways", "description: d\ntags: [composer]\nalways: yes", "always"),
    ]

    @pytest.mark.parametrize("name,front,category", CASES)
    def test_category_is_reported_with_its_location(self, name, front, category) -> None:
        item = (
            {"name": name, "location": f"user-guides/u1/{name}.md", "text": "# no frontmatter\n"}
            if front is None
            else entry(name, front, location=f"user-guides/u1/{name}.md")
        )
        collection = build_collection([("user", [item])])
        assert collection["invalid"] == [{"path": f"user-guides/u1/{name}.md", "category": category}]
        assert collection["valid"] == {}

    def test_oversize_entry_is_reported(self) -> None:
        collection = build_collection([("user", [valid_entry("big", body="x" * (GUIDE_MAX_BYTES + 1))])])
        assert collection["invalid"] == [{"path": "/store/big.md", "category": "size"}]

    def test_invalid_user_entry_does_not_shadow_the_valid_bundled_entry(self) -> None:
        collection = build_collection([
            ("user", [entry("grid", "description: d\ntags: [nope]", location="/home/u/guides/grid.md")]),
            ("builtin", [valid_entry("grid", body="Theirs.\n")]),
        ])
        assert collection["valid"]["grid"]["source"] == "builtin"
        assert collection["valid"]["grid"]["body"] == "Theirs.\n"
        assert collection["invalid"] == [{"path": "/home/u/guides/grid.md", "category": "tag-value"}]

    def test_one_invalid_guide_never_fails_the_call(self) -> None:
        collection = build_collection([
            ("user", [
                valid_entry("good-one"),
                entry("broken", "description: d\ntags: [nope]"),
                valid_entry("good-two"),
            ]),
        ])
        assert set(collection["valid"]) == {"good-one", "good-two"}
        assert len(collection["invalid"]) == 1

    def test_the_same_bad_name_is_reported_once_per_source(self) -> None:
        collection = build_collection([
            ("user", [entry("a.b", "description: d\ntags: [composer]", location="/u/a.b.md")]),
            ("builtin", [entry("a.b", "description: d\ntags: [composer]", location="/b/a.b.md")]),
        ])
        assert [i["path"] for i in collection["invalid"]] == ["/u/a.b.md", "/b/a.b.md"]
        assert collection["valid"] == {}
