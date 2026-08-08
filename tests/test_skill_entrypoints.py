# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Skill entry points must stay thin dispatchers.

v0.5.0 deleted ``skills/`` because each SKILL.md had grown a full copy of the
mode behaviour, which then drifted from the real definition. Behaviour now
lives only in ``personas/*.md`` and is served by ``start_presentation(mode=...)``.

Restoring the entry points is only safe while they stay thin, so these tests
guard the property that made the v0.5.0 removal necessary: a skill may say
*which* mode to load and nothing about *how* that mode behaves.

``personas/`` itself is not asserted on here. A line-count or content lock
would fail on every legitimate persona edit while still missing a same-length
rewrite; the reviewable guarantee is a diff against the base commit.
"""

import re
from pathlib import Path

import pytest

from sdpm.tools import _MODES

_REPO = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO / "skills"
_PERSONAS_DIR = _REPO / "personas"

_SKILL_FILES = sorted(_SKILLS_DIR.glob("*/SKILL.md"))

# Human-invoked modes only. "composer" is called by a dispatched sub-agent and
# "single" by single-agent deployments; neither is something a user picks.
_NON_INTERACTIVE_MODES = {"composer", "single"}

# A dispatcher needs frontmatter plus a few lines of instruction. The old
# in-skill behaviour copies were ~200 lines each.
_MAX_LINES = 40


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md must start with a YAML frontmatter block"
    fields: dict[str, str] = {}
    key = None
    for line in match.group(1).splitlines():
        top = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if top:
            key = top.group(1)
            fields[key] = top.group(2).strip()
        elif key is not None:
            fields[key] += " " + line.strip()
    return {k: v.lstrip(">-|").strip() for k, v in fields.items()}


def test_skills_directory_is_populated():
    assert _SKILL_FILES, "no SKILL.md found under skills/"


@pytest.mark.parametrize("path", _SKILL_FILES, ids=lambda p: p.parent.name)
class TestSkillEntryPoint:
    def test_name_matches_the_directory(self, path):
        assert _frontmatter(path.read_text(encoding="utf-8"))["name"] == path.parent.name

    def test_description_says_when_to_use_it(self, path):
        # Clients match on description alone at discovery time.
        description = _frontmatter(path.read_text(encoding="utf-8"))["description"]
        assert len(description) >= 60

    def test_loads_a_real_mode_first(self, path):
        text = path.read_text(encoding="utf-8")
        modes = re.findall(r'start_presentation\(mode="([a-z]+)"\)', text)
        assert modes, "a skill entry point must call start_presentation(mode=...)"
        for mode in modes:
            assert mode in _MODES, f"unknown mode {mode!r} (valid: {', '.join(_MODES)})"
            assert mode not in _NON_INTERACTIVE_MODES, f"{mode!r} is not a user-invoked mode"

    def test_mode_matches_the_skill_name(self, path):
        mode = re.search(r'start_presentation\(mode="([a-z]+)"\)', path.read_text(encoding="utf-8")).group(1)
        assert path.parent.name == f"sdpm-{mode}"

    def test_stays_thin(self, path):
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= _MAX_LINES, (
            f"{path.relative_to(_REPO)} is {len(lines)} lines — behaviour belongs in "
            "personas/, not in the entry point"
        )

    def test_fails_closed_when_the_mcp_server_is_missing(self, path):
        # An invalid plugin mcp.json disables only the MCP servers, leaving
        # skills loaded, so the entry point is what the user sees. It must not
        # improvise a deck without the behaviour definition.
        text = path.read_text(encoding="utf-8").lower()
        assert "unavailable" in text or "not reachable" in text


@pytest.mark.parametrize("path", _SKILL_FILES, ids=lambda p: p.parent.name)
def test_does_not_duplicate_persona_prose(path):
    """No substantial line of a persona may reappear in a skill entry point."""
    skill_lines = {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if len(line.strip()) >= 30
    }
    for persona in sorted(_PERSONAS_DIR.glob("*.md")):
        persona_lines = {
            line.strip()
            for line in persona.read_text(encoding="utf-8").splitlines()
            if len(line.strip()) >= 30
        }
        shared = skill_lines & persona_lines
        assert not shared, (
            f"{path.relative_to(_REPO)} copies prose from {persona.name}: {sorted(shared)[:2]} — "
            "behaviour must be loaded through start_presentation, not duplicated"
        )


def test_every_user_invoked_mode_has_an_entry_point():
    interactive = set(_MODES) - _NON_INTERACTIVE_MODES
    covered = {
        re.search(r'start_presentation\(mode="([a-z]+)"\)', p.read_text(encoding="utf-8")).group(1)
        for p in _SKILL_FILES
    }
    assert covered == interactive, f"missing entry points for: {sorted(interactive - covered)}"


def test_personas_are_still_the_only_behaviour_source():
    # Guards the inversion this change could reintroduce: skills growing large
    # enough to become the de facto behaviour definition.
    persona_bytes = sum(p.stat().st_size for p in _PERSONAS_DIR.glob("*.md"))
    skill_bytes = sum(p.stat().st_size for p in _SKILL_FILES)
    assert skill_bytes * 4 < persona_bytes, (
        f"skills/ ({skill_bytes} B) is no longer negligible next to personas/ "
        f"({persona_bytes} B) — check for duplicated behaviour"
    )
