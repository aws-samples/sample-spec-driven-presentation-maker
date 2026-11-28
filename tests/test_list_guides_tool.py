# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The two guide tools, and the one collection behind both of them.

Before this, a guide was reachable only by being named — by code, by a role document or
by another guide — and the only enumeration anywhere was a FileNotFoundError message.
list_guides answers "which guides exist"; read_guides turns a name from it into text.
Both resolve through the merged collection, so a user's guide shadows a bundled one for
listing and reading alike, on the local surface and on the remote.
"""

import json
from pathlib import Path

import pytest

from sdpm import tools as contract
from sdpm.knowledge.reference import (
    TAGS,
    build_collection,
    guides_by_name,
    guides_listing,
    join_guides,
)

GUIDE = "---\ndescription: {desc}\ntags: [{tags}]\n---\n\n{body}\n"


@pytest.fixture
def user_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "guides"
    directory.mkdir()
    monkeypatch.setenv("SDPM_GUIDES_DIR", str(directory))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    from sdpm import entry

    monkeypatch.setattr(entry, "_guide_cache", None)
    return directory


def entry_for(name: str, tags: str = "orchestrator", body: str = "Body.", desc: str = "") -> dict[str, str]:
    text = GUIDE.format(desc=desc or f"{name} does a thing.", tags=tags, body=body)
    return {"name": name, "location": f"/store/{name}.md", "text": text}


class TestListGuidesTool:
    def test_without_a_role_it_lists_everything(self) -> None:
        result = contract.list_guides()
        assert result["role"] == ""
        assert len(result["guides"]) == 31
        assert "invalid" not in result

    def test_each_entry_carries_the_five_listing_fields(self) -> None:
        shown = contract.list_guides()["guides"][0]
        assert set(shown) == {"name", "description", "source", "tags", "always"}

    @pytest.mark.parametrize("role", TAGS)
    def test_a_role_narrows_the_list(self, role: str) -> None:
        result = contract.list_guides(role)
        assert result["role"] == role
        assert result["guides"]
        assert all(role in g["tags"] for g in result["guides"])

    def test_the_composer_modes_see_different_specs(self) -> None:
        pptx = {g["name"] for g in contract.list_guides("composer-pptx")["guides"]}
        html = {g["name"] for g in contract.list_guides("composer-html")["guides"]}
        assert "slide-json-spec" in pptx and "slide-json-spec" not in html
        assert "slide-html-spec" in html and "slide-html-spec" not in pptx

    def test_management_holds_the_guides_about_sdpm_itself(self) -> None:
        names = {g["name"] for g in contract.list_guides("management")["guides"]}
        assert names == {"hand-edit-sync", "import-pptx", "writing-a-guide"}

    def test_an_unknown_role_is_an_error_naming_the_valid_values(self) -> None:
        result = contract.list_guides("reviewer")
        assert "guides" not in result
        for tag in TAGS:
            assert tag in result["error"]
        assert "reviewer" in result["error"]

    def test_its_description_says_what_it_answers(self) -> None:
        doc = contract.list_guides.__doc__
        assert "Which guides exist" in doc
        assert "read_guides" in doc

    def test_list_styles_is_untouched(self) -> None:
        assert "styles" in contract.list_styles()


class TestReadGuidesTool:
    def test_one_name_comes_back_under_its_heading(self) -> None:
        result = contract.read_guides(["grid"])
        assert set(result) == {"guides_text"}
        assert result["guides_text"].startswith("# Guide: grid\n\n")

    def test_several_names_come_back_in_ascending_order(self) -> None:
        result = contract.read_guides(["writing-ja", "aws-design", "html-deck"])
        assert set(result) == {"guides_text"}  # all three fit, so nothing is reported
        assert [line for line in result["guides_text"].splitlines() if line.startswith("# Guide: ")] == [
            "# Guide: aws-design",
            "# Guide: html-deck",
            "# Guide: writing-ja",
        ]

    def test_two_calls_are_byte_identical(self) -> None:
        first = contract.read_guides(["grid", "table"])["guides_text"]
        second = contract.read_guides(["grid", "table"])["guides_text"]
        assert first.encode("utf-8") == second.encode("utf-8")

    def test_no_frontmatter_survives(self) -> None:
        text = contract.read_guides(["grid"])["guides_text"]
        assert "tags:" not in text and "description:" not in text

    def test_an_unknown_name_names_what_does_exist(self) -> None:
        with pytest.raises(FileNotFoundError) as exc:
            contract.read_guides(["no-such-guide"])
        assert "no-such-guide" in str(exc.value)
        assert "grid" in str(exc.value)

    def test_it_takes_names_and_nothing_else(self) -> None:
        # No role or mode selector: the only way to address a guide is by name.
        import inspect

        assert list(inspect.signature(contract.read_guides).parameters) == ["names"]

    def test_the_budget_holds_for_the_biggest_mandatory_set(self) -> None:
        from sdpm.entry import _ROLE_TAGS, guide_collection
        from sdpm.knowledge.reference import GUIDE_RESULT_BUDGET, always_guides

        collection = guide_collection()
        for role, tags in _ROLE_TAGS.items():
            names = sorted(always_guides(collection, tags))
            size = len(json.dumps(contract.read_guides(names), ensure_ascii=False)) if names else 0
            assert size <= GUIDE_RESULT_BUDGET, (role, size)


class TestReadGuidesStaysInsideTheBudget:
    """A result past the budget is filed away by the client and the model sees its ends.

    So the read fills to the budget and says what it left, instead of handing over a set
    nobody can read. Both halves matter: the result fits, and the caller is told.
    """

    def test_a_set_over_the_budget_comes_back_inside_it(self) -> None:
        from sdpm.knowledge.reference import GUIDE_RESULT_BUDGET

        result = contract.read_guides(["grid", "table", "verify"])
        assert len(json.dumps(result, ensure_ascii=False)) <= GUIDE_RESULT_BUDGET

    def test_what_did_not_fit_comes_back_by_name_with_what_to_do(self) -> None:
        result = contract.read_guides(["grid", "table", "verify"])
        assert result["not_included"] == ["table"]
        assert "read_guides again" in result["note"]

    def test_the_spec_is_never_what_goes(self) -> None:
        # verify is bundled and always: a composer that loses it cannot check its own
        # slide, so the fill order keeps it and sheds the guide read on demand.
        result = contract.read_guides(["grid", "table", "verify"])
        assert "# Guide: verify" in result["guides_text"]

    def test_a_set_that_fits_reports_nothing(self) -> None:
        result = contract.read_guides(["aws-design", "html-deck"])
        assert set(result) == {"guides_text"}

    def test_the_fill_is_stable_across_calls(self) -> None:
        first = contract.read_guides(["grid", "table", "verify"])
        second = contract.read_guides(["grid", "table", "verify"])
        assert first == second


class TestShadowing:
    """REQ-9.12: one winning entry, whichever surface asks."""

    def test_a_user_guide_is_listed_read_and_mandatory_as_its_own(self, user_dir: Path) -> None:
        (user_dir / "grid.md").write_text(
            GUIDE.format(desc="My grid rules.", tags="composer, style", body="Mine."), encoding="utf-8"
        )
        listed = next(g for g in contract.list_guides("composer")["guides"] if g["name"] == "grid")
        assert listed["source"] == "user"
        assert listed["description"] == "My grid rules."
        assert contract.read_guides(["grid"])["guides_text"] == "# Guide: grid\n\nMine.\n"

    def test_a_user_guide_can_make_itself_mandatory(self, user_dir: Path) -> None:
        (user_dir / "house-rules.md").write_text(
            "---\ndescription: Our rules.\ntags: [composer]\nalways: true\n---\n\nAlways this.\n",
            encoding="utf-8",
        )
        from sdpm.entry import _ROLE_TAGS, guide_collection
        from sdpm.knowledge.reference import always_guides

        mandatory = always_guides(guide_collection(), _ROLE_TAGS["composer-pptx"])
        assert "house-rules" in mandatory

    def test_an_invalid_user_guide_is_reported_in_the_listing(self, user_dir: Path) -> None:
        (user_dir / "broken.md").write_text("---\ndescription: d\ntags: [review]\n---\n\nx\n", encoding="utf-8")
        result = contract.list_guides()
        assert result["invalid"] == [
            {"path": str(user_dir / "broken.md"), "category": "tag-value"}
        ]
        assert "broken" not in {g["name"] for g in result["guides"]}


class TestEngineFunctionsServeBothSurfaces:
    """The remote passes an S3-built collection to the same two functions."""

    def test_listing_an_s3_built_collection(self) -> None:
        collection = build_collection([
            ("user", [entry_for("mine", desc="Mine.")]),
            ("builtin", [entry_for("theirs")]),
        ])
        result = guides_listing(collection, "orchestrator")
        assert [(g["name"], g["source"]) for g in result["guides"]] == [("mine", "user"), ("theirs", "builtin")]

    def test_reading_an_s3_built_collection(self) -> None:
        collection = build_collection([("user", [entry_for("mine", body="From S3.")])])
        assert join_guides(guides_by_name(collection, ["mine"])) == "# Guide: mine\n\nFrom S3.\n"

    def test_the_user_entry_wins_for_reading_too(self) -> None:
        collection = build_collection([
            ("user", [entry_for("grid", body="Mine.")]),
            ("builtin", [entry_for("grid", body="Theirs.")]),
        ])
        assert guides_by_name(collection, ["grid"]) == {"grid": "Mine.\n"}

    def test_an_unknown_role_errors_before_anything_is_listed(self) -> None:
        collection = build_collection([("builtin", [entry_for("x")])])
        assert "error" in guides_listing(collection, "nope")
