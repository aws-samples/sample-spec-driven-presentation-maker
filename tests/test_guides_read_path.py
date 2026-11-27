# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The one read path behind the guide collection, and what it is allowed to remember.

A local server must show an edited guide on the next call, so nothing is cached there.
The cloud image's references cannot change for the life of its process, so it preloads
them — but only the bundled ones: a user's guides live in a store that keeps changing.
"""

from pathlib import Path

import pytest

from sdpm import entry
from sdpm.knowledge.reference import BUNDLED_GUIDES_DIR

GUIDE = "---\ndescription: Mine.\ntags: [orchestrator]\n---\n\n{body}\n"


@pytest.fixture
def user_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "guides"
    directory.mkdir()
    monkeypatch.setenv("SDPM_GUIDES_DIR", str(directory))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    return directory


@pytest.fixture
def uncached(monkeypatch: pytest.MonkeyPatch) -> None:
    """A local process: nothing preloaded, whatever an earlier test in this session did."""
    monkeypatch.setattr(entry, "_guide_cache", None)


@pytest.fixture
def preloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A process that has preloaded, without preloading again inside the test."""
    monkeypatch.setattr(entry, "_guide_cache", {})


def no_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("reopened a guide file after the preload")

    monkeypatch.setattr(Path, "read_text", forbidden)


class TestLocalProcessReadsEveryCall:
    def test_an_edited_guide_is_visible_on_the_next_call(self, uncached, user_dir) -> None:
        (user_dir / "mine.md").write_text(GUIDE.format(body="First."))
        assert entry.guide_collection()["valid"]["mine"]["body"] == "First.\n"
        (user_dir / "mine.md").write_text(GUIDE.format(body="Second."))
        assert entry.guide_collection()["valid"]["mine"]["body"] == "Second.\n"

    def test_a_guide_added_after_the_first_call_is_visible(self, uncached, user_dir) -> None:
        assert "later" not in entry.guide_collection()["valid"]
        (user_dir / "later.md").write_text(GUIDE.format(body="Later."))
        assert "later" in entry.guide_collection()["valid"]

    def test_bundled_text_is_reread_too(self, uncached, monkeypatch) -> None:
        entry._guide_entries(BUNDLED_GUIDES_DIR)
        no_reads(monkeypatch)
        with pytest.raises(AssertionError):
            entry._guide_entries(BUNDLED_GUIDES_DIR)


class TestPreloadedProcessServesBundledFromMemory:
    def test_second_call_does_not_reopen_the_file(self, preloaded, monkeypatch) -> None:
        first = entry._guide_entries(BUNDLED_GUIDES_DIR)
        assert first
        no_reads(monkeypatch)
        assert entry._guide_entries(BUNDLED_GUIDES_DIR) == first

    def test_user_store_entries_are_never_served_from_the_cache(self, preloaded, user_dir) -> None:
        (user_dir / "mine.md").write_text(GUIDE.format(body="First."))
        assert entry.guide_collection()["valid"]["mine"]["body"] == "First.\n"
        (user_dir / "mine.md").write_text(GUIDE.format(body="Second."))
        assert entry.guide_collection()["valid"]["mine"]["body"] == "Second.\n"

    def test_preload_turns_the_guide_cache_on_and_warms_the_bundled_directory(self, monkeypatch) -> None:
        monkeypatch.setattr(entry, "_guide_cache", None)
        monkeypatch.setattr(entry, "_reference_cache", None)
        entry.preload_references()
        assert BUNDLED_GUIDES_DIR in entry._guide_cache
        no_reads(monkeypatch)
        assert entry._guide_entries(BUNDLED_GUIDES_DIR)


class TestSourceEntries:
    def test_text_is_raw_so_the_metadata_survives_the_read(self, uncached, user_dir) -> None:
        (user_dir / "mine.md").write_text(GUIDE.format(body="Body."))
        entries = entry._guide_entries(user_dir)
        assert entries[0]["text"].startswith("---\n")
        assert "tags: [orchestrator]" in entries[0]["text"]

    def test_entry_carries_its_name_and_its_path(self, uncached, user_dir) -> None:
        (user_dir / "mine.md").write_text(GUIDE.format(body="Body."))
        assert entry._guide_entries(user_dir) == [
            {"name": "mine", "location": str(user_dir / "mine.md"), "text": GUIDE.format(body="Body.")}
        ]

    def test_a_directory_that_does_not_exist_yields_nothing(self, uncached, tmp_path) -> None:
        assert entry._guide_entries(tmp_path / "absent") == []

    def test_only_markdown_is_collected(self, uncached, user_dir) -> None:
        (user_dir / "mine.md").write_text(GUIDE.format(body="Body."))
        (user_dir / "notes.txt").write_text("not a guide")
        (user_dir / "deck.pptx").write_bytes(b"not a guide")
        assert [e["name"] for e in entry._guide_entries(user_dir)] == ["mine"]

    def test_entries_are_sorted_by_filename(self, uncached, user_dir) -> None:
        for name in ("c", "a", "b"):
            (user_dir / f"{name}.md").write_text(GUIDE.format(body=name))
        assert [e["name"] for e in entry._guide_entries(user_dir)] == ["a", "b", "c"]


class TestCollectionLabelsItsSources:
    def test_the_bundled_directory_is_labelled_builtin(self, uncached, user_dir) -> None:
        # design-rules survives this SPEC's content changes, so it is a stable witness.
        assert entry.guide_collection() is not None
        assert "design-rules" in [e["name"] for e in entry._guide_entries(BUNDLED_GUIDES_DIR)]

    def test_a_user_guide_shadows_the_bundled_guide_of_that_name(self, uncached, user_dir) -> None:
        (user_dir / "grid.md").write_text(GUIDE.format(body="My grid."))
        won = entry.guide_collection()["valid"]["grid"]
        assert won["source"] == "user"
        assert won["body"] == "My grid.\n"
