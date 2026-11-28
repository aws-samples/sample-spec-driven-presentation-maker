# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The user's guides in the cloud: their S3 layout, and how they feed the collection.

Same shape as the style library — one prefix per user in the pptx bucket — and the same
shadowing rule, except that a guide's description and tags live in its own frontmatter,
so there is nothing to list without reading the object.
"""

from sdpm.knowledge.reference import build_collection
from shared import user_library
from user_library_fakes import FakeS3

PPTX = "pptx-bucket"


def guide_md(name: str, tags: str = "[orchestrator]", body: str = "Body.\n") -> bytes:
    return f"---\ndescription: {name} does a thing.\ntags: {tags}\n---\n\n{body}".encode()


class TestKeys:
    def test_the_prefix_is_per_user(self) -> None:
        assert user_library.user_guides_prefix("u1") == "user-guides/u1/"

    def test_the_key_keeps_its_layout(self) -> None:
        assert user_library.user_guide_key("u1", "mine") == "user-guides/u1/mine.md"

    def test_it_sits_beside_the_style_and_template_prefixes(self) -> None:
        assert user_library.user_style_key("u1", "mine") == "user-styles/u1/mine.html"
        assert user_library.user_template_s3_key("u1", "mine") == "user-templates/u1/mine.pptx"


class TestListing:
    def test_entries_are_collection_sources_in_name_order(self) -> None:
        s3 = FakeS3({PPTX: {
            "user-guides/u1/beta.md": guide_md("beta"),
            "user-guides/u1/alpha.md": guide_md("alpha"),
        }})
        assert user_library.list_user_guides(s3, PPTX, "u1") == [
            {"name": "alpha", "location": "user-guides/u1/alpha.md", "text": guide_md("alpha").decode()},
            {"name": "beta", "location": "user-guides/u1/beta.md", "text": guide_md("beta").decode()},
        ]

    def test_another_users_guides_are_not_reached(self) -> None:
        s3 = FakeS3({PPTX: {
            "user-guides/u1/mine.md": guide_md("mine"),
            "user-guides/u2/theirs.md": guide_md("theirs"),
        }})
        assert [e["name"] for e in user_library.list_user_guides(s3, PPTX, "u1")] == ["mine"]
        assert [e["name"] for e in user_library.list_user_guides(s3, PPTX, "u2")] == ["theirs"]

    def test_a_user_with_no_guides_gets_an_empty_list(self) -> None:
        assert user_library.list_user_guides(FakeS3({PPTX: {}}), PPTX, "u1") == []

    def test_objects_that_are_not_markdown_are_skipped(self) -> None:
        s3 = FakeS3({PPTX: {
            "user-guides/u1/mine.md": guide_md("mine"),
            "user-guides/u1/notes.txt": b"not a guide",
            "user-guides/u1/": b"",
        }})
        assert [e["name"] for e in user_library.list_user_guides(s3, PPTX, "u1")] == ["mine"]

    def test_the_text_always_comes_back(self) -> None:
        # Unlike a style, a guide has no description to list without reading it.
        s3 = FakeS3({PPTX: {"user-guides/u1/mine.md": guide_md("mine")}})
        assert "tags: [orchestrator]" in user_library.list_user_guides(s3, PPTX, "u1")[0]["text"]


class TestUnreadableObject:
    class BrokenS3(FakeS3):
        def get_object(self, Bucket, Key):
            if Key.endswith("broken.md"):
                raise RuntimeError("AccessDenied")
            return super().get_object(Bucket=Bucket, Key=Key)

    def test_it_is_reported_rather_than_dropped(self) -> None:
        s3 = self.BrokenS3({PPTX: {
            "user-guides/u1/broken.md": guide_md("broken"),
            "user-guides/u1/fine.md": guide_md("fine"),
        }})
        entries = user_library.list_user_guides(s3, PPTX, "u1")
        assert [e["name"] for e in entries] == ["broken", "fine"]
        collection = build_collection([("user", entries)])
        assert sorted(collection["valid"]) == ["fine"]
        assert collection["invalid"] == [{"path": "user-guides/u1/broken.md", "category": "frontmatter"}]


class TestFeedingTheCollection:
    BUNDLED = [{"name": "grid", "location": "/image/guides/grid.md", "text": guide_md("grid").decode()}]

    def test_a_user_guide_shadows_the_bundled_guide_of_that_name(self) -> None:
        s3 = FakeS3({PPTX: {"user-guides/u1/grid.md": guide_md("grid", body="My grid.\n")}})
        collection = build_collection([
            ("user", user_library.list_user_guides(s3, PPTX, "u1")),
            ("builtin", self.BUNDLED),
        ])
        assert collection["valid"]["grid"]["source"] == "user"
        assert collection["valid"]["grid"]["body"] == "My grid.\n"

    def test_a_key_outside_one_path_component_is_reported_with_its_key(self) -> None:
        s3 = FakeS3({PPTX: {"user-guides/u1/sub/x.md": guide_md("x")}})
        collection = build_collection([("user", user_library.list_user_guides(s3, PPTX, "u1"))])
        assert collection["valid"] == {}
        assert collection["invalid"] == [{"path": "user-guides/u1/sub/x.md", "category": "name"}]

    def test_a_dotted_name_is_reported_with_its_key(self) -> None:
        s3 = FakeS3({PPTX: {"user-guides/u1/acme.v2.md": guide_md("acme.v2")}})
        collection = build_collection([("user", user_library.list_user_guides(s3, PPTX, "u1"))])
        assert collection["invalid"] == [{"path": "user-guides/u1/acme.v2.md", "category": "name"}]

    def test_a_bad_tag_is_reported_and_the_bundled_guide_still_wins(self) -> None:
        s3 = FakeS3({PPTX: {"user-guides/u1/grid.md": guide_md("grid", tags="[review]")}})
        collection = build_collection([
            ("user", user_library.list_user_guides(s3, PPTX, "u1")),
            ("builtin", self.BUNDLED),
        ])
        assert collection["valid"]["grid"]["source"] == "builtin"
        assert collection["invalid"] == [{"path": "user-guides/u1/grid.md", "category": "tag-value"}]
