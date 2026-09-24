# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Role entry tools: one call returns the role document plus what the role reads first."""

import json
from pathlib import Path

import pytest

from sdpm import tools

_OUTLINE = """# Deck

## Intro
- [intro] Why this matters
  - body: One paragraph of context
  - visual: A single statement
  - evidence: brief Sources 1
- [demo-1] The product, step one
  - body: First step
  - visual: Screenshot left, caption right
  - evidence: brief Sources 1
- [demo-2] The product, step two
  - body: Second step
  - visual: Same as demo-1
  - evidence: brief Sources 1
- [closing] What to do next
  - body: Call to action
  - visual: Three bullets
  - evidence: brief Sources 1
"""


@pytest.fixture
def deck(tmp_path: Path) -> Path:
    r = tools.init_deck_workspace(str(tmp_path / "deck"))
    deck_dir = Path(r["output_dir"])
    tools.apply_style(str(deck_dir), style="typographic", template="blank-dark")
    specs = deck_dir / "specs"
    (specs / "brief.md").write_text("# Brief\n\nAudience: engineers.\n\n## Sources\n1. pasted notes\n", encoding="utf-8")
    (specs / "outline.md").write_text(_OUTLINE, encoding="utf-8")
    slides = deck_dir / "slides"
    slides.mkdir(exist_ok=True)
    for slug in ("intro", "demo-1", "demo-2"):
        (slides / f"{slug}.json").write_text(json.dumps({"id": slug, "elements": []}), encoding="utf-8")
    return deck_dir


class TestStartPresentation:
    def test_returns_workflow_and_environment(self):
        r = tools.start_presentation()
        assert "# Orchestrator" in r["static"]["workflow"]
        assert {s["name"] for s in r["styles"]}
        assert r["templates"]
        assert r["output_dir"]

    def test_workflow_does_not_ask_for_what_it_already_returned(self):
        wf = tools.start_presentation()["static"]["workflow"]
        assert "list_templates()" not in wf
        assert "read_workflows" not in wf
        assert "init_presentation" not in wf


class TestStartComposing:
    def test_static_only_without_deck(self):
        r = tools.start_composing()
        assert set(r) == {"static"}
        assert "# Composer" in r["static"]["workflow"]
        assert "deck.json" in r["static"]["slide_spec"]

    def test_static_is_identical_across_calls(self, deck: Path):
        assert tools.start_composing()["static"] == tools.start_composing(str(deck), ["intro"])["static"]

    def test_deck_payload_for_assigned_slugs(self, deck: Path):
        r = tools.start_composing(str(deck), ["intro", "closing"])
        d = r["deck"]
        assert d["specs_ok"] is True
        assert d["deck"]["template"]
        assert "Audience: engineers" in d["brief"]
        assert "[demo-2]" in d["outline"]  # whole outline, not just assigned rows
        assert "<html" in d["art_direction"].lower()
        assert d["template_analysis"] and d["template_analysis"]["layouts"]
        assert d["assigned_slugs"] == ["intro", "closing"]
        assert d["slides_present"] == ["demo-1", "demo-2", "intro"]
        # only assigned slides' JSON, and only those that exist
        assert set(d["existing_slides"]) == {"intro"}
        assert "readonly" not in d["existing_slides"]["intro"]

    def test_override_group_head_is_included_readonly(self, deck: Path):
        r = tools.start_composing(str(deck), ["demo-2"])
        existing = r["deck"]["existing_slides"]
        assert set(existing) == {"demo-1", "demo-2"}
        assert existing["demo-1"]["readonly"] is True
        assert "readonly" not in existing["demo-2"]

    def test_head_not_marked_readonly_when_assigned(self, deck: Path):
        existing = tools.start_composing(str(deck), ["demo-1", "demo-2"])["deck"]["existing_slides"]
        assert set(existing) == {"demo-1", "demo-2"}
        assert all("readonly" not in e for e in existing.values())

    def test_layout_pass_gets_every_existing_slide(self, deck: Path):
        slugs = ["intro", "demo-1", "demo-2", "closing"]
        existing = tools.start_composing(str(deck), slugs)["deck"]["existing_slides"]
        assert set(existing) == {"intro", "demo-1", "demo-2"}

    def test_broken_specs_return_errors_and_no_workflow(self, deck: Path):
        (deck / "specs" / "outline.md").unlink()
        r = tools.start_composing(str(deck), ["intro"])
        assert r["specs_ok"] is False
        assert r["errors"]
        assert "static" not in r and "deck" not in r

    def test_unknown_assigned_slug_is_rejected(self, deck: Path):
        r = tools.start_composing(str(deck), ["nope"])
        assert r["specs_ok"] is False


class TestStartStyle:
    def test_default_base(self):
        r = tools.start_style()
        assert "# Style" in r["static"]["workflow"]
        assert r["styles"]
        assert r["base"]["name"] == "typographic"
        assert "<title>" in r["base"]["html"]

    def test_named_base(self):
        assert tools.start_style("report")["base"]["name"] == "report"

    def test_unknown_base_raises(self):
        with pytest.raises(FileNotFoundError):
            tools.start_style("no-such-style")


class TestStartTranslation:
    def test_payload(self, deck: Path):
        r = tools.start_translation(str(deck), "en")
        assert "# Translate" in r["static"]["workflow"]
        assert "deck.json" in r["static"]["slide_spec"]
        d = r["deck"]
        assert d["slides_present"] == ["demo-1", "demo-2", "intro"]
        assert d["sibling"] == str(deck.with_name(deck.name + "-en"))
        assert d["sibling_exists"] is False

    def test_not_a_deck(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            tools.start_translation(str(tmp_path), "en")


def test_local_server_binds_entry_tools_and_not_workflow_readers():
    src = (Path(__file__).resolve().parents[1] / "servers" / "local" / "server.py").read_text(encoding="utf-8")
    for name in ("start_presentation", "start_composing", "start_style", "start_translation", "init_deck_workspace"):
        assert f"mcp.tool()(tools.{name})" in src
    assert "read_workflows" not in src
    assert "init_presentation" not in src


def test_instructions_can_be_disabled(monkeypatch):
    from sdpm.tools import instructions as mod

    monkeypatch.delenv("SDPM_DISABLE_INSTRUCTIONS", raising=False)
    assert mod.instructions() and "start_presentation" in mod.instructions()
    monkeypatch.setenv("SDPM_DISABLE_INSTRUCTIONS", "1")
    assert mod.instructions() is None
