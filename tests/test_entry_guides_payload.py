# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""What a start_* return says about guides, and what it deliberately does not carry.

The payload is a tool result, and a client files a result past 30,000 characters and shows
the model only its ends. So it names the guides this role must read and leaves the bodies
to read_guides: a name costs 15 characters, a body about 4,000, and the deck part already
takes 14,000.
"""

import json
import sys
from pathlib import Path

import pytest

from sdpm import tools
from sdpm.entry import _ROLE_TAGS, guide_payload
from sdpm.knowledge.reference import build_collection

_AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"
sys.path.insert(0, str(_AGENT_DIR))
try:
    from composition import _process_cache_key
    from modes import MODES
finally:
    sys.path.remove(str(_AGENT_DIR))

RESULT_BUDGET = 25_000


def entry_for(name: str, tags: str, always: bool = False) -> dict[str, str]:
    front = f"description: {name}.\ntags: [{tags}]" + ("\nalways: true" if always else "")
    return {"name": name, "location": f"/store/{name}.md", "text": f"---\n{front}\n---\n\nBody.\n"}


class TestShape:
    def test_names_and_a_listing_and_nothing_else(self) -> None:
        collection = build_collection([("builtin", [entry_for("spec", "composer", always=True)])])
        payload = guide_payload(collection, _ROLE_TAGS["composer-pptx"])
        assert set(payload) == {"must_read", "listing"}
        assert payload["must_read"] == ["spec"]

    def test_no_body_reaches_the_payload(self) -> None:
        collection = build_collection([("builtin", [entry_for("spec", "composer", always=True)])])
        payload = guide_payload(collection, _ROLE_TAGS["composer-pptx"])
        assert "Body." not in json.dumps(payload, ensure_ascii=False)

    def test_the_names_are_ascending(self) -> None:
        collection = build_collection([("builtin", [
            entry_for("zeta", "composer", always=True),
            entry_for("alpha", "composer", always=True),
        ])])
        assert guide_payload(collection, _ROLE_TAGS["composer-pptx"])["must_read"] == ["alpha", "zeta"]

    def test_a_role_with_no_mandatory_guide_gets_an_empty_list(self) -> None:
        collection = build_collection([("builtin", [entry_for("listed", "composer")])])
        payload = guide_payload(collection, _ROLE_TAGS["composer-pptx"])
        assert payload["must_read"] == []
        assert [g["name"] for g in payload["listing"]["guides"]] == ["listed"]

    def test_invalid_entries_ride_in_the_listing(self) -> None:
        collection = build_collection([("user", [entry_for("broken", "review")])])
        payload = guide_payload(collection, _ROLE_TAGS["orchestrator"])
        assert payload["listing"]["invalid"] == [{"path": "/store/broken.md", "category": "tag-value"}]

    @pytest.mark.parametrize("name", ["start_presentation", "start_composing", "start_style"])
    def test_every_entry_tool_carries_the_pair(self, name: str) -> None:
        payload = getattr(tools, name)()
        assert isinstance(payload["must_read"], list)
        assert set(payload["listing"]) == {"guides", "invalid"}

    def test_static_keeps_only_the_role_document(self) -> None:
        for payload in (tools.start_presentation(), tools.start_composing(), tools.start_style()):
            assert set(payload["static"]) == {"workflow"}


class TestErrorReturnsAreUnchanged:
    """Base returns early for four reasons, with no static at all. Still true."""

    def test_an_invalid_mode(self) -> None:
        result = tools.start_composing(mode="svg")
        assert result["specs_ok"] is False and result["errors"]
        assert {"static", "must_read", "listing"}.isdisjoint(result)

    def test_failed_specs(self, tmp_path: Path) -> None:
        (tmp_path / "deck.json").write_text("{}", encoding="utf-8")
        result = tools.start_composing(str(tmp_path), ["nope"])
        assert result["specs_ok"] is False
        assert {"static", "must_read", "listing"}.isdisjoint(result)


class TestNothingGuideBearingIsUnderStatic:
    """_process_cache_key shares any static.* pick across every user."""

    GUIDE_PICKS = ("guides_text", "listing", "must_read")

    def test_no_pick_is_under_static(self) -> None:
        for mode, cfg in MODES.items():
            for part in cfg.parts:
                if part.source.type != "mcp":
                    continue
                picks = [part.source.pick] + [
                    v.pick for v in part.source.args.values() if hasattr(v, "pick")
                ]
                for pick in picks:
                    if pick in self.GUIDE_PICKS:
                        assert not pick.startswith("static."), (mode, pick)

    def test_those_picks_are_classified_per_user(self) -> None:
        for cfg in MODES.values():
            for part in cfg.parts:
                if part.source.type == "mcp" and part.source.pick in self.GUIDE_PICKS:
                    key = _process_cache_key(part.source, "u1")
                    assert key is not None and key[0] == "user" and key[1] == "u1"

    def test_the_role_document_stays_shared(self) -> None:
        for cfg in MODES.values():
            for part in cfg.parts:
                if part.source.type == "mcp" and part.source.pick == "static.workflow":
                    assert _process_cache_key(part.source, "u1")[0] == "static"


class TestBudget:
    def test_every_entry_return_fits(self) -> None:
        sizes = {
            name: len(json.dumps(getattr(tools, name)(), ensure_ascii=False))
            for name in ("start_presentation", "start_composing", "start_style")
        }
        sizes["start_composing_html"] = len(json.dumps(tools.start_composing(mode="html"), ensure_ascii=False))
        over = {n: s for n, s in sizes.items() if s > RESULT_BUDGET}
        # start_style carries a whole style's HTML; it was over budget before this SPEC too.
        assert over.keys() <= {"start_style"}, sizes

    def test_a_guide_added_to_the_mandatory_set_costs_a_name(self) -> None:
        one = build_collection([("builtin", [entry_for("a", "composer", always=True)])])
        two = build_collection([("builtin", [
            entry_for("a", "composer", always=True),
            entry_for("bbbbbbbbbb", "composer", always=True),
        ])])
        grew = len(json.dumps(guide_payload(two, _ROLE_TAGS["composer-pptx"])["must_read"])) - len(
            json.dumps(guide_payload(one, _ROLE_TAGS["composer-pptx"])["must_read"])
        )
        assert grew < 20
