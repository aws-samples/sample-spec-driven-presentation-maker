# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Role skills and dedicated client agents stay thin workflow dispatchers."""

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO / "skills"
_EXPECTED = {
    "sdpm-create": "start_presentation",
    "sdpm-composer": "start_composing",
    "sdpm-style": "start_style",
    "sdpm-translate": "start_translation",
}
_SKILL_FILES = sorted(_SKILLS_DIR.glob("*/SKILL.md"))
_DISPATCH = re.compile(r"`(start_[a-z]+)\(")
_WORKFLOW_PROSE = (
    "# Role",
    "## Workflow",
    "Layout pass.",
    "specs/brief.md",
)


def _parts(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    assert match, f"{path}: missing YAML frontmatter"
    fields: dict[str, str] = {}
    key = None
    for line in match.group(1).splitlines():
        top = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if top:
            key = top.group(1)
            fields[key] = top.group(2).strip()
        elif key is not None:
            fields[key] += " " + line.strip()
    return {k: v.lstrip(">-|").strip() for k, v in fields.items()}, match.group(2)


def test_exactly_four_role_skills_exist():
    assert {path.parent.name for path in _SKILL_FILES} == set(_EXPECTED)


@pytest.mark.parametrize("path", _SKILL_FILES, ids=lambda path: path.parent.name)
def test_skill_is_a_thin_matching_dispatch(path: Path):
    frontmatter, body = _parts(path)
    name = path.parent.name
    assert frontmatter["name"] == name
    assert len(frontmatter["description"]) >= 60
    assert _DISPATCH.findall(body) == [_EXPECTED[name]]
    assert len(body.splitlines()) <= 10
    assert not [phrase for phrase in _WORKFLOW_PROSE if phrase in body]
    assert "unavailable" in body.lower()
    if name != "sdpm-composer":
        assert "assigned_slugs" not in body


def test_claude_composer_agent_is_a_thin_matching_dispatch():
    path = _REPO / "clients" / "claude-code" / "agents" / "sdpm-composer.md"
    frontmatter, body = _parts(path)
    assert frontmatter["name"] == "sdpm-composer"
    assert frontmatter["tools"]
    assert _DISPATCH.findall(body) == ["start_composing"]
    assert len(body.splitlines()) <= 6
    assert not [phrase for phrase in _WORKFLOW_PROSE if phrase in body]
    assert "deck_id" in body and "assigned_slugs" in body and "task_instruction" in body
    assert "missing" in body.lower() and "stop" in body.lower()


def test_workflow_prose_is_not_duplicated_into_entry_surfaces():
    roots = [
        _REPO / "sdpm" / "SKILL.md",
        _REPO / "skills",
        _REPO / "clients",
        _REPO / "sdpm" / "sdpm" / "tools" / "instructions.py",
    ]
    offenders: list[tuple[str, str]] = []
    for root in roots:
        paths = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for phrase in ("Layout pass.", "specs/brief.md"):
                if phrase in text:
                    offenders.append((str(path.relative_to(_REPO)), phrase))
    assert not offenders
