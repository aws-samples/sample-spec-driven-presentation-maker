# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Declarative mode definitions for SDPM agents."""

from dataclasses import dataclass, field
from typing import Literal

from composition import Part, Source


@dataclass
class ModeConfig:
    """Prompt composition and tool configuration for one agent role."""

    parts: list[Part] = field(default_factory=list)
    use_composer: bool = True
    agent_model: Literal["chat", "create"] = "chat"
    allowed_tools: list[str] | None = None


_COMMON_LANGUAGE = Part(Source.file("common/language"), target="system")
_COMMON_ATTACHMENTS = Part(Source.file("common/attachments"), target="system")
_WIRING_COMPOSE_REPORT = Part(
    Source.file("wiring/compose_report"), target="system", cache_point=True,
)
_NOW = Part(Source.file("common/now"), target="system")


def _workflow(name: str) -> Part:
    """Fetch canonical role behavior through the workflow contract."""
    return Part(
        Source.mcp("read_workflows", {"names": [name]}),
        target="system",
        label=f"workflow:{name}",
    )


# Tool allowlists — explicit control over which MCP tools each mode can use.
# run_style_python is only available to style_creator.
#
# diff_pptx is deliberately absent: the hand-edit sync workflow is a local/CLI
# capability, and servers/remote does not bind the tool. Listing it here only
# produced a "not found on MCP server" warning on every request. The tool is
# slated for removal, so the workflow document carries the same note rather than
# the cloud path growing an implementation.
_DECK_TOOLS = [
    "init_presentation", "analyze_template", "read_attachment",
    "list_styles", "apply_style", "read_examples", "list_workflows",
    "read_workflows", "list_guides", "read_guides", "search_assets",
    "list_templates", "check_specs",
    "run_python", "generate_pptx", "get_preview", "code_to_slide",
    "grid", "arch_diagram", "import_attachment",
]

_STYLE_TOOLS = [
    "run_style_python", "list_styles", "analyze_template", "read_attachment",
    "read_workflows",
]

_INTERACTION_DIALOGUE = Part(Source.file("wiring/interaction_dialogue"), target="system")
_INTERACTION_FAST = Part(Source.file("wiring/interaction_fast"), target="system")


def _orchestrator(*wiring: Part, use_composer: bool = True, **overrides) -> ModeConfig:
    """Orchestrator workflow plus environment facts the UI decided (interaction depth)."""
    return ModeConfig(
        parts=[
            _COMMON_LANGUAGE,
            _workflow("orchestrator"),
            *wiring,
            _COMMON_ATTACHMENTS,
            *([_WIRING_COMPOSE_REPORT] if use_composer else []),
            _NOW,
        ],
        use_composer=use_composer,
        allowed_tools=_DECK_TOOLS,
        **overrides,
    )


_ORCHESTRATOR = _orchestrator()
# Web UI "Spec" (dialogue) / "Vibe" (fast, from material) — the pick is an
# environment fact the workflow cannot know, so it is passed as a one-line token.
_ORCHESTRATOR_DIALOGUE = _orchestrator(_INTERACTION_DIALOGUE)
_ORCHESTRATOR_FAST = _orchestrator(_INTERACTION_FAST)

_COMPOSER = ModeConfig(
    parts=[_workflow("composer")],
    use_composer=False,
    allowed_tools=_DECK_TOOLS,
)

_STYLE_CREATOR = ModeConfig(
    parts=[
        _COMMON_LANGUAGE,
        _workflow("style"),
        Part(Source.file("wiring/style_remote"), target="system"),
        _NOW,
    ],
    use_composer=False,
    agent_model="create",
    allowed_tools=_STYLE_TOOLS,
)

# Wire values from API/Web UI. "spec" and "vibe" share the orchestrator workflow
# and differ only in the interaction-mode token.
MODES: dict[str, ModeConfig] = {
    "orchestrator": _ORCHESTRATOR,
    "vibe": _ORCHESTRATOR_FAST,
    "spec": _ORCHESTRATOR_DIALOGUE,
    "composer": _COMPOSER,
    "style_creator": _STYLE_CREATOR,
}
