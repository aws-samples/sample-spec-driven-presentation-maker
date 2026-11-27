# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Guide metadata: the frontmatter grammar, the tag vocabulary, the name rule, the cap.

``guide_meta`` is the one parse behind every guide surface, so its diagnostics are
pinned category by category: an invalid guide must be reported, never silently degraded.
"""

from pathlib import Path

import pytest

from sdpm.knowledge.reference import (
    BUNDLED_GUIDES_DIR,
    GUIDE_MAX_BYTES,
    TAGS,
    guide_meta,
    is_guide_name,
    is_style_name,
)


def guide(front: str, body: str = "Body line.\n") -> str:
    return f"---\n{front}\n---\n\n{body}"


class TestVocabulary:
    def test_tags_are_exactly_the_seven(self):
        assert TAGS == (
            "orchestrator",
            "composer",
            "composer-pptx",
            "composer-html",
            "style",
            "translate",
            "management",
        )

    def test_bundled_dir_is_the_guides_directory(self):
        assert BUNDLED_GUIDES_DIR.name == "guides"
        assert BUNDLED_GUIDES_DIR.is_dir()

    def test_cap_is_64_kib(self):
        assert GUIDE_MAX_BYTES == 64 * 1024


class TestGuideName:
    """REQ-9.2. Every rejection is decided by the string alone."""

    REJECTED = [
        "a.b",
        ".hidden",
        "trailing.",
        "with\x00nul",
        "sub/x",
        "a\\b",
        "/absolute/x",
        "C:name",
        ".",
        "..",
        "",
    ]

    @pytest.mark.parametrize("name", REJECTED)
    def test_rejected(self, name):
        assert is_guide_name(name) is False

    @pytest.mark.parametrize("name", ["story-line", "verify", "writing_a_guide", "社内標準", "a1"])
    def test_accepted(self, name):
        assert is_guide_name(name) is True

    @pytest.mark.parametrize("name", [None, 3, ["x"]])
    def test_non_string_rejected(self, name):
        assert is_guide_name(name) is False

    def test_dotted_name_separates_guides_from_styles(self):
        # is_style_name deliberately admits acme.v2; a guide name is also a payload key.
        assert is_style_name("acme.v2") is True
        assert is_guide_name("acme.v2") is False

    @pytest.mark.parametrize("name", REJECTED)
    def test_bad_name_rejected_before_any_filesystem_access(self, name, monkeypatch):
        def forbidden(*args, **kwargs):
            raise AssertionError("guide_meta touched the filesystem for an invalid name")

        monkeypatch.setattr(Path, "read_text", forbidden)
        monkeypatch.setattr(Path, "open", forbidden)
        monkeypatch.setattr(Path, "exists", forbidden)
        assert guide_meta(name, guide("description: x\ntags: [composer]")) == {
            "name": name,
            "category": "name",
        }


class TestValidGuide:
    def test_flow_sequence(self):
        meta = guide_meta("story-line", guide('description: "Why this shape."\ntags: [orchestrator]\nalways: true'))
        assert meta == {
            "name": "story-line",
            "description": "Why this shape.",
            "tags": ["orchestrator"],
            "always": True,
            "body": "Body line.\n",
        }

    def test_block_sequence(self):
        meta = guide_meta("slide-json-spec", guide("description: The spec.\ntags:\n  - composer-pptx\n  - translate"))
        assert meta["tags"] == ["composer-pptx", "translate"]
        assert meta["always"] is False

    def test_unindented_block_sequence(self):
        meta = guide_meta("grid", guide("description: The grid.\ntags:\n- composer\n- style"))
        assert meta["tags"] == ["composer", "style"]

    def test_always_defaults_to_false(self):
        assert guide_meta("table", guide("description: Tables.\ntags: [composer]"))["always"] is False

    def test_always_false_is_explicit_and_valid(self):
        assert guide_meta("table", guide("description: Tables.\ntags: [composer]\nalways: false"))["always"] is False

    def test_body_carries_no_frontmatter(self):
        meta = guide_meta("verify", guide("description: Rules.\ntags: [composer]", body="# Verify\n\nText.\n"))
        assert meta["body"] == "# Verify\n\nText.\n"
        assert "description:" not in meta["body"]

    def test_blank_line_inside_frontmatter_is_allowed(self):
        meta = guide_meta("table", guide("description: Tables.\n\ntags: [composer]"))
        assert meta["tags"] == ["composer"]

    def test_every_tag_in_the_vocabulary_is_accepted(self):
        for tag in TAGS:
            assert guide_meta("x", guide(f"description: d\ntags: [{tag}]"))["tags"] == [tag]

    def test_text_at_the_cap_is_valid(self):
        front = "description: d\ntags: [composer]"
        filler = "x" * (GUIDE_MAX_BYTES - len(guide(front, body="").encode("utf-8")))
        assert "category" not in guide_meta("big", guide(front, body=filler))


class TestInvalidCategories:
    """REQ-2.6, one case per category."""

    def category(self, name: str, text: str) -> str:
        meta = guide_meta(name, text)
        assert "category" in meta, meta
        assert meta["name"] == name
        return meta["category"]

    def test_name(self):
        assert self.category("a.b", guide("description: d\ntags: [composer]")) == "name"

    def test_frontmatter_missing(self):
        assert self.category("x", "# No frontmatter\n") == "frontmatter"

    def test_frontmatter_unterminated(self):
        assert self.category("x", "---\ndescription: d\ntags: [composer]\n") == "frontmatter"

    def test_frontmatter_comment(self):
        assert self.category("x", guide("# a comment\ndescription: d\ntags: [composer]")) == "frontmatter"

    def test_frontmatter_duplicate_key(self):
        assert self.category("x", guide("description: a\ndescription: b\ntags: [composer]")) == "frontmatter"

    def test_frontmatter_nested_mapping(self):
        assert self.category("x", guide("description: d\ntags: [composer]\nmeta:\n  nested: 1")) == "frontmatter"

    def test_frontmatter_multiline_scalar(self):
        assert self.category("x", guide("description: |\n  two\n  lines\ntags: [composer]")) == "frontmatter"

    def test_frontmatter_null_value(self):
        assert self.category("x", guide("description:\ntags: [composer]")) == "frontmatter"

    def test_frontmatter_sequence_without_a_key(self):
        assert self.category("x", guide("- composer\ndescription: d")) == "frontmatter"

    def test_frontmatter_sequence_under_the_wrong_key(self):
        assert self.category("x", guide("description: d\ntags: [composer]\n- extra")) == "frontmatter"

    def test_unknown_key(self):
        assert self.category("x", guide("description: d\ntags: [composer]\ncategory: guide")) == "unknown-key"

    def test_unknown_key_beats_a_later_failure(self):
        # Precedence: unknown-key (3) is reported even though the tag (6) is also bad.
        assert self.category("x", guide("description: d\ntags: [nope]\nname: x")) == "unknown-key"

    def test_description_absent(self):
        assert self.category("x", guide("tags: [composer]")) == "description"

    def test_description_empty(self):
        assert self.category("x", guide('description: ""\ntags: [composer]')) == "description"

    def test_tags_absent(self):
        assert self.category("x", guide("description: d")) == "tags"

    def test_tags_empty_flow(self):
        assert self.category("x", guide("description: d\ntags: []")) == "tags"

    def test_tags_empty_block(self):
        assert self.category("x", guide("description: d\ntags:")) == "tags"

    def test_tags_not_a_sequence(self):
        assert self.category("x", guide("description: d\ntags: composer")) == "tags"

    def test_tags_unterminated_flow(self):
        assert self.category("x", guide("description: d\ntags: [composer")) == "tags"

    def test_tag_value_outside_the_vocabulary(self):
        assert self.category("x", guide("description: d\ntags: [review]")) == "tag-value"

    def test_tag_value_beats_always(self):
        # Precedence: tag-value (6) before always (7).
        assert self.category("x", guide("description: d\ntags: [review]\nalways: yes")) == "tag-value"

    def test_tag_value_empty_item(self):
        assert self.category("x", guide("description: d\ntags: [composer, ]")) == "tag-value"

    def test_always_not_a_boolean(self):
        assert self.category("x", guide("description: d\ntags: [composer]\nalways: yes")) == "always"

    def test_always_capitalised_is_not_a_boolean(self):
        assert self.category("x", guide("description: d\ntags: [composer]\nalways: True")) == "always"

    def test_size_over_the_cap(self):
        text = guide("description: d\ntags: [composer]", body="x" * (GUIDE_MAX_BYTES + 1))
        assert self.category("big", text) == "size"

    def test_size_is_measured_in_bytes_not_characters(self):
        # Multi-byte text over the cap in bytes while under it in characters.
        body = "あ" * (GUIDE_MAX_BYTES // 3)
        text = guide("description: d\ntags: [composer]", body=body)
        assert len(text) < GUIDE_MAX_BYTES < len(text.encode("utf-8"))
        assert self.category("big", text) == "size"

    def test_size_is_reported_last(self):
        # Precedence: a bad tag (6) is reported even on an oversize guide (8).
        text = guide("description: d\ntags: [review]", body="x" * (GUIDE_MAX_BYTES + 1))
        assert self.category("big", text) == "tag-value"
