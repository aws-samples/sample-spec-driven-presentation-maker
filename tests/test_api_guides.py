# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Route-level tests for the guide endpoints of api/index.py.

Same harness as tests/test_api_styles_templates.py. Guides are the third resource type
with a per-user S3 prefix, so these mirror the style routes — minus the pin, which guides
do not have — and add what styles do not need: a guide is validated when it is written,
because a guide that fails to parse is left out of every hand-over rather than degrading
one deck's look.
"""

import pytest

from test_api_html_routes import BUCKET, _Event, index  # noqa: F401 — index is a fixture
from user_library_fakes import FakeS3, FakeTable

VALID = b"---\ndescription: Mine.\ntags: [composer]\n---\n\nMy rules.\n"


class _JsonEvent(_Event):
    def __init__(self, user_id: str, body: dict | None = None):
        super().__init__(user_id)
        self.json_body = body or {}


@pytest.fixture()
def api(index, monkeypatch):  # noqa: F811
    s3 = FakeS3({BUCKET: {
        "user-guides/u1/mine.md": VALID,
        "user-guides/u2/theirs.md": VALID,
    }})
    monkeypatch.setattr(index, "s3_client", s3)
    monkeypatch.setattr(index, "table", FakeTable())
    index.app.current_event = _JsonEvent("u1")
    index.s3 = s3
    return index


def call(api, fn, *args, user="u1", body=None):
    api.app.current_event = _JsonEvent(user, body)
    return fn(*args)


def guide(text: str) -> dict:
    return {"name": "house-rules", "text": text}


class TestListing:
    def test_the_users_guides_come_back_over_the_bundled_ones(self, api):
        result = call(api, api.list_guides)
        names = {g["name"] for g in result["guides"]}
        assert "mine" in names  # the caller's own
        assert "story-line" in names  # bundled in the deployment
        assert "theirs" not in names  # another user's

    def test_a_user_guide_shadows_the_bundled_guide_of_that_name(self, api):
        api.s3.put_object(Bucket=BUCKET, Key="user-guides/u1/grid.md", Body=VALID)
        shown = next(g for g in call(api, api.list_guides)["guides"] if g["name"] == "grid")
        assert shown["source"] == "user"
        assert shown["description"] == "Mine."

    def test_an_invalid_guide_is_named_with_its_key(self, api):
        api.s3.put_object(Bucket=BUCKET, Key="user-guides/u1/broken.md",
                          Body=b"---\ndescription: d\ntags: [review]\n---\n\nx\n")
        result = call(api, api.list_guides)
        assert result["invalid"] == [{"path": "user-guides/u1/broken.md", "category": "tag-value"}]
        assert "broken" not in {g["name"] for g in result["guides"]}


class TestSave:
    def test_a_valid_guide_is_written_as_markdown(self, api):
        assert call(api, api.save_user_guide, body=guide(VALID.decode())) == {"saved": "house-rules"}
        assert api.s3.buckets[BUCKET]["user-guides/u1/house-rules.md"] == VALID

    def test_it_lands_under_the_callers_own_prefix(self, api):
        call(api, api.save_user_guide, user="u9", body=guide(VALID.decode()))
        assert "user-guides/u9/house-rules.md" in api.s3.buckets[BUCKET]

    @pytest.mark.parametrize("name", ["a.b", "sub/x", "", ".hidden", ".."])
    def test_a_bad_name_is_refused_before_any_write(self, api, name):
        before = dict(api.s3.buckets[BUCKET])
        result, status = call(api, api.save_user_guide, body={"name": name, "text": VALID.decode()})
        assert status == 400 and "Invalid guide" in result["error"]
        assert api.s3.buckets[BUCKET] == before

    def test_empty_text_is_refused(self, api):
        result, status = call(api, api.save_user_guide, body=guide(""))
        assert status == 400 and result["error"] == "text is required"

    @pytest.mark.parametrize("text,category", [
        ("# No frontmatter\n", "frontmatter"),
        ("---\ndescription: d\ntags: [composer]\ncategory: guide\n---\n\nx\n", "unknown-key"),
        ("---\ntags: [composer]\n---\n\nx\n", "description"),
        ("---\ndescription: d\n---\n\nx\n", "tags"),
        ("---\ndescription: d\ntags: [reviewer]\n---\n\nx\n", "tag-value"),
        ("---\ndescription: d\ntags: [composer]\nalways: yes\n---\n\nx\n", "always"),
    ])
    def test_the_frontmatter_is_validated_at_write_time(self, api, text, category):
        before = dict(api.s3.buckets[BUCKET])
        result, status = call(api, api.save_user_guide, body=guide(text))
        assert status == 400 and category in result["error"]
        assert api.s3.buckets[BUCKET] == before

    def test_a_guide_over_the_cap_is_refused(self, api):
        from sdpm.knowledge.reference import GUIDE_MAX_BYTES

        text = f"---\ndescription: d\ntags: [composer]\n---\n\n{'x' * (GUIDE_MAX_BYTES + 1)}\n"
        result, status = call(api, api.save_user_guide, body=guide(text))
        assert status == 400 and "size" in result["error"]

    @pytest.mark.parametrize("body", [["house-rules", "text"], "house-rules", 7])
    def test_a_body_that_is_not_an_object_is_refused_not_a_server_error(self, api, body):
        # A caller that sends the wrong shape gets told so. Reading name and text off a
        # list raised AttributeError, which the handler returned as a 500.
        before = dict(api.s3.buckets[BUCKET])
        result, status = call(api, api.save_user_guide, body=body)
        assert status == 400
        assert "object" in result["error"]
        assert api.s3.buckets[BUCKET] == before

    @pytest.mark.parametrize("field,value", [
        ("text", 123), ("text", ["---\n"]), ("text", {"a": 1}),
        ("name", 123), ("name", ["house-rules"]),
    ])
    def test_a_field_of_the_wrong_type_is_refused_not_a_server_error(self, api, field, value):
        # The object check alone was not enough: guide_meta works on the text, so a
        # non-string reached it and raised ('int' object has no attribute 'splitlines').
        before = dict(api.s3.buckets[BUCKET])
        body = {"name": "house-rules", "text": VALID.decode()} | {field: value}
        result, status = call(api, api.save_user_guide, body=body)
        assert status == 400
        assert "strings" in result["error"]
        assert api.s3.buckets[BUCKET] == before

    def test_a_write_replaces_the_previous_version(self, api):
        call(api, api.save_user_guide, body={"name": "mine", "text": VALID.decode().replace("Mine.", "Newer.")})
        assert b"Newer." in api.s3.buckets[BUCKET]["user-guides/u1/mine.md"]


class TestDelete:
    def test_it_removes_the_object(self, api):
        assert call(api, api.delete_user_guide, "mine") == {"deleted": "mine"}
        assert "user-guides/u1/mine.md" not in api.s3.buckets[BUCKET]

    def test_an_absent_guide_is_404(self, api):
        result, status = call(api, api.delete_user_guide, "no-such-guide")
        assert status == 404 and "not found" in result["error"]

    def test_a_bad_name_is_400(self, api):
        result, status = call(api, api.delete_user_guide, "a.b")
        assert status == 400

    def test_another_users_guide_is_out_of_reach(self, api):
        result, status = call(api, api.delete_user_guide, "theirs")
        assert status == 404
        assert "user-guides/u2/theirs.md" in api.s3.buckets[BUCKET]


class TestRename:
    def test_it_moves_the_object(self, api):
        result = call(api, api.rename_user_guide, "mine", body={"newName": "ours"})
        assert result == {"renamed": {"from": "mine", "to": "ours"}}
        assert "user-guides/u1/ours.md" in api.s3.buckets[BUCKET]
        assert "user-guides/u1/mine.md" not in api.s3.buckets[BUCKET]

    def test_an_absent_source_is_404(self, api):
        result, status = call(api, api.rename_user_guide, "no-such-guide", body={"newName": "ours"})
        assert status == 404

    def test_an_existing_destination_is_409(self, api):
        api.s3.put_object(Bucket=BUCKET, Key="user-guides/u1/ours.md", Body=VALID)
        result, status = call(api, api.rename_user_guide, "mine", body={"newName": "ours"})
        assert status == 409 and "already exists" in result["error"]
        assert "user-guides/u1/mine.md" in api.s3.buckets[BUCKET]

    @pytest.mark.parametrize("new_name", ["a.b", "sub/x", ""])
    def test_a_bad_new_name_is_400(self, api, new_name):
        result, status = call(api, api.rename_user_guide, "mine", body={"newName": new_name})
        assert status == 400 and "Invalid new name" in result["error"]


class TestNoPins:
    def test_guides_have_no_pin_endpoint(self, api):
        assert not hasattr(api, "pin_guide")
        assert "/guides/pin" not in open(api.__file__, encoding="utf-8").read()


class TestEndToEnd:
    """REQ-10.6: a guide written here reaches that user's reads, and nobody else's."""

    MANDATORY = (
        "---\ndescription: Our house rules.\ntags: [composer]\nalways: true\n---\n\nAlways read this.\n"
    )

    def collection(self, api, user: str):
        return api._guide_collection(user)

    def test_the_author_sees_it_listed_read_and_mandatory(self, api):
        call(api, api.save_user_guide, body={"name": "house-rules", "text": self.MANDATORY})
        from sdpm.entry import _ROLE_TAGS, guide_payload
        from sdpm.knowledge.reference import guides_by_name, guides_listing

        collection = self.collection(api, "u1")
        assert "house-rules" in {g["name"] for g in guides_listing(collection)["guides"]}
        assert guides_by_name(collection, ["house-rules"]) == {"house-rules": "Always read this.\n"}
        assert "house-rules" in guide_payload(collection, _ROLE_TAGS["composer-pptx"])["must_read"]

    def test_nobody_else_sees_it(self, api):
        call(api, api.save_user_guide, body={"name": "house-rules", "text": self.MANDATORY})
        from sdpm.entry import _ROLE_TAGS, guide_payload
        from sdpm.knowledge.reference import guides_listing

        other = self.collection(api, "u2")
        assert "house-rules" not in {g["name"] for g in guides_listing(other)["guides"]}
        assert "house-rules" not in guide_payload(other, _ROLE_TAGS["composer-pptx"])["must_read"]

    def test_deleting_it_takes_it_out_of_the_mandatory_set(self, api):
        call(api, api.save_user_guide, body={"name": "house-rules", "text": self.MANDATORY})
        call(api, api.delete_user_guide, "house-rules")
        from sdpm.entry import _ROLE_TAGS, guide_payload

        assert "house-rules" not in guide_payload(self.collection(api, "u1"), _ROLE_TAGS["composer-pptx"])["must_read"]
