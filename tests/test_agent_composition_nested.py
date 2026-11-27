# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A prompt part that calls one tool with what another returned.

The guide collection decides which guides a role must read, and a user extends that
collection, so the prompt configuration cannot name them. It names the question instead:
read whatever ``start_composing`` reported as mandatory.
"""

import json
import sys
from pathlib import Path

import pytest

_AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"
sys.path.insert(0, str(_AGENT_DIR))
try:
    from composition import (
        Part,
        Source,
        _args_key,
        _process_cache_key,
        clear_process_cache,
        prefetch_sources,
        resolve_parts,
    )
finally:
    sys.path.remove(str(_AGENT_DIR))

MUST_READ = ["slide-json-spec", "verify"]


class FakeMCP:
    """Records every call, and answers the two tools these parts use."""

    def __init__(self, must_read=None):
        self.calls: list[tuple[str, dict]] = []
        self.must_read = MUST_READ if must_read is None else must_read

    def call_tool_sync(self, tool_use_id, name, arguments):
        self.calls.append((name, arguments))
        if name == "read_guides":
            joined = "\n".join(f"# Guide: {n}\n\nBody of {n}.\n" for n in arguments["names"])
            payload = {"guides_text": joined}
        else:
            payload = {
                "static": {"workflow": f"# {name}"},
                "must_read": self.must_read,
                "listing": {"guides": [], "invalid": []},
            }
        return {"status": "success", "content": [{"text": json.dumps(payload)}]}


def guide_parts(tool="start_composing", args=None):
    entry = Source.mcp(tool, args or {}, pick="must_read")
    return [
        Part(Source.mcp(tool, args or {}, pick="static.workflow"), target="system", label="workflow"),
        Part(Source.mcp("read_guides", {"names": entry}, pick="guides_text"), target="system", label="guides"),
        Part(Source.mcp(tool, args or {}, pick="listing"), target="system", label="guides-listing"),
    ]


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_process_cache()
    yield
    clear_process_cache()


class TestNestedResolution:
    def test_the_inner_source_resolves_before_the_outer_call(self):
        client = FakeMCP()
        system, _ = resolve_parts(guide_parts(), mcp_client=client, context={}, enable_cache=False)
        names = [args for name, args in client.calls if name == "read_guides"]
        assert names == [{"names": MUST_READ}]
        assert "# Guide: slide-json-spec" in system and "# Guide: verify" in system

    def test_the_outer_tool_receives_a_list_not_a_json_string(self):
        client = FakeMCP()
        resolve_parts(guide_parts(), mcp_client=client, context={}, enable_cache=False)
        passed = next(args["names"] for name, args in client.calls if name == "read_guides")
        assert isinstance(passed, list)
        assert passed == MUST_READ

    def test_one_fetch_serves_the_nested_resolution_and_the_sibling_picks(self):
        client = FakeMCP()
        resolve_parts(guide_parts(), mcp_client=client, context={}, enable_cache=False)
        assert [name for name, _ in client.calls].count("start_composing") == 1

    def test_the_configuration_names_no_guide(self):
        # The only place a guide name appears is the tool's answer.
        for part in guide_parts():
            assert "slide-json-spec" not in json.dumps(part.source.args, default=str)

    def test_an_empty_mandatory_set_asks_for_nothing(self):
        client = FakeMCP(must_read=[])
        system, _ = resolve_parts(guide_parts(), mcp_client=client, context={}, enable_cache=False)
        assert next(args["names"] for name, args in client.calls if name == "read_guides") == []
        assert "# Guide:" not in system

    def test_a_plain_arg_is_left_alone(self):
        client = FakeMCP()
        parts = [Part(Source.mcp("read_guides", {"names": ["grid"]}, pick="guides_text"), target="system")]
        resolve_parts(parts, mcp_client=client, context={}, enable_cache=False)
        assert client.calls == [("read_guides", {"names": ["grid"]})]

    def test_the_mode_argument_reaches_both_the_inner_and_the_outer_call(self):
        client = FakeMCP()
        resolve_parts(guide_parts(args={"mode": "html"}), mcp_client=client, context={}, enable_cache=False)
        entry_args = [args for name, args in client.calls if name == "start_composing"]
        assert entry_args == [{"mode": "html"}]


class TestCacheKey:
    def test_args_holding_a_nested_source_get_a_stable_key(self):
        source = Source.mcp("read_guides", {"names": Source.mcp("start_composing", {}, pick="must_read")}, pick="guides_text")
        first = _process_cache_key(source, "u1")
        assert first is not None
        assert first == _process_cache_key(source, "u1")
        assert first[0] == "user" and first[1] == "u1"

    def test_two_parts_differing_only_in_the_inner_source_do_not_share(self):
        pptx = Source.mcp("read_guides", {"names": Source.mcp("start_composing", {}, pick="must_read")}, pick="guides_text")
        html = Source.mcp(
            "read_guides",
            {"names": Source.mcp("start_composing", {"mode": "html"}, pick="must_read")},
            pick="guides_text",
        )
        assert _process_cache_key(pptx, "u1") != _process_cache_key(html, "u1")

    def test_a_nested_source_is_rendered_not_dropped(self):
        key = _args_key({"names": Source.mcp("start_composing", {}, pick="must_read")})
        assert "start_composing" in key and "must_read" in key

    def test_the_key_of_plain_args_is_unchanged_json(self):
        assert _args_key({"mode": "html"}) == json.dumps({"mode": "html"}, sort_keys=True)

    def test_a_prefetch_warms_both_parts_and_a_later_resolve_calls_nothing(self):
        client = FakeMCP()
        parts = guide_parts()
        prefetch_sources(parts, client, "u1")
        before = len(client.calls)
        resolve_parts(parts, mcp_client=client, context={}, enable_cache=False, user_id="u1")
        assert len(client.calls) == before
        assert [name for name, _ in client.calls].count("start_composing") == 1


class TestAFailedOuterCallLeavesNothingStale:
    """The inner value must not outlive a failed outer call.

    The inner source is resolved before the outer tool is called. If it were process-cached
    there, a failure of the outer call would leave the names behind, and the next turn would
    ask read_guides for guides the collection no longer holds — which raises, and takes the
    whole part list with it, so the agent would run with an empty system prompt.
    """

    class FlakyMCP(FakeMCP):
        def __init__(self, must_read, fail_read=True):
            super().__init__(must_read)
            self.fail_read = fail_read

        def call_tool_sync(self, tool_use_id, name, arguments):
            if name == "read_guides" and self.fail_read:
                self.calls.append((name, arguments))
                return {"status": "error", "content": [{"text": "boom"}]}
            return super().call_tool_sync(tool_use_id, name, arguments)

    def test_the_names_are_not_cached_by_the_failed_attempt(self):
        parts = guide_parts()
        first = self.FlakyMCP(["my-rules"])
        with pytest.raises(RuntimeError):
            resolve_parts(parts, mcp_client=first, context={}, enable_cache=False, user_id="u1")

        # The collection changed between turns: a different guide is mandatory now.
        second = self.FlakyMCP(["verify"], fail_read=False)
        system, _ = resolve_parts(parts, mcp_client=second, context={}, enable_cache=False, user_id="u1")
        asked = next(args["names"] for name, args in second.calls if name == "read_guides")
        assert asked == ["verify"], "the failed turn pinned the old names"
        assert "# Guide: verify" in system

    def test_a_prefetch_that_fails_caches_nothing(self):
        parts = guide_parts()
        client = self.FlakyMCP(["my-rules"])
        with pytest.raises(RuntimeError):
            prefetch_sources(parts, client, "u1")
        later = self.FlakyMCP(["verify"], fail_read=False)
        resolve_parts(parts, mcp_client=later, context={}, enable_cache=False, user_id="u1")
        assert next(args["names"] for name, args in later.calls if name == "read_guides") == ["verify"]
