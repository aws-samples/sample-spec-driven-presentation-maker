# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Declarative mode definitions for SDPM agents."""

from dataclasses import dataclass, field
from typing import Literal

from composition import Part, Source


@dataclass
class ModeConfig:
    """Agent mode configuration.

    Attributes:
        parts: Ordered prompt parts (static .md files, MCP prefetch, or callables).
        use_composer: Include compose_slides tool.
        agent_model: Which model setting to use for the main agent — "chat" for
            conversations/planning, "create" for modes that also generate artifacts.
        allowed_tools: If set, only these MCP tool names are loaded from the
            Presentation Maker server. None = all tools except style-only tools.
    """

    parts: list[Part] = field(default_factory=list)
    use_composer: bool = True
    agent_model: Literal["chat", "create"] = "chat"
    allowed_tools: list[str] | None = None


# Shared parts — referenced by multiple modes
_COMMON_LANGUAGE = Part(Source.file("common/language"), target="system")
_COMMON_ATTACHMENTS = Part(Source.file("common/attachments"), target="system")
_WIRING_COMPOSE_REPORT = Part(Source.file("wiring/compose_report"), target="system",
                              cache_point=True)
_NOW = Part(Source.file("common/now"), target="system")


def _persona(mode: str) -> Part:
    """Fetch canonical mode behavior from the personas port.

    Persona text lives only in personas/*.md and is served by the MCP server
    via start_presentation(mode=...) — the same port every other client uses.
    tool_filters do not apply to call_tool_sync, so this works regardless of
    the mode's allowed_tools list.
    """
    return Part(
        Source.mcp("start_presentation", {"mode": mode}),
        target="system",
        label=f"persona:{mode}",
    )


_PREFETCH_BRIEFING = Part(
    Source.mcp("read_workflows", {"names": ["create-new-1-briefing"]}),
    target="history:tool_result",
    label="read_workflows",
    prefill_text="Starting the Briefing phase. I'll read the workflow to conduct the hearing properly.",
)

# Tool allowlists — explicit control over which MCP tools each mode can use.
# run_style_python is only available to style_creator.
_DECK_TOOLS = [
    "init_presentation", "analyze_template", "read_attachment",
    "list_styles", "apply_style", "read_examples", "list_workflows",
    "read_workflows", "list_guides", "read_guides", "search_assets",
    "list_templates",
    "run_python", "generate_pptx", "get_preview", "code_to_slide",
    "grid", "arch_diagram", "import_attachment", "diff_pptx",
]

_STYLE_TOOLS = [
    "run_style_python", "list_styles", "analyze_template", "read_attachment",
]


MODES: dict[str, ModeConfig] = {
    # Mode IDs are wire-compatible ("separated" = spec persona).
    # Behavior text comes from personas/*.md via the start_presentation port;
    # only L4 wiring (attachment wire format, compose_slides report format)
    # is defined here as local files.
    "separated": ModeConfig(parts=[
        _COMMON_LANGUAGE,
        _persona("spec"),
        _COMMON_ATTACHMENTS,
        _WIRING_COMPOSE_REPORT,
        _NOW,
        _PREFETCH_BRIEFING,
    ], allowed_tools=_DECK_TOOLS),
    "vibe": ModeConfig(parts=[
        _COMMON_LANGUAGE,
        _persona("vibe"),
        _COMMON_ATTACHMENTS,
        _WIRING_COMPOSE_REPORT,
        _NOW,
    ], allowed_tools=_DECK_TOOLS),
    "single": ModeConfig(
        parts=[
            _COMMON_LANGUAGE,
            Part(Source.file("role/single_agent"), target="system",
                 cache_point=True),
            _NOW,
        ],
        use_composer=False,
        agent_model="create",
        allowed_tools=_DECK_TOOLS,
    ),
    # Composer is a sub-agent invoked by compose_slides; ModeConfig is used
    # by compose_slides to build its prompt via the same resolve_parts path.
    # The persona's "Step 1 — Load references" is skip-if-already-loaded, so
    # prefetching them here is compatible and saves per-group round trips.
    # Dynamic parts (deck specs, template analysis) are added at runtime.
    "composer": ModeConfig(
        parts=[
            _persona("composer"),
            Part(
                Source.mcp("read_workflows", {"names": ["create-new-2-compose"]}),
                target="system", label="create-new-2-compose",
            ),
            Part(
                Source.mcp("read_workflows", {"names": ["slide-json-spec"]}),
                target="system", label="slide-json-spec",
            ),
            Part(Source.mcp("read_guides", {"names": ["grid"]}),
                 target="history:tool_result", label="read_guides"),
            Part(Source.mcp("read_examples", {"names": ["components/all"]}),
                 target="history:tool_result", label="read_examples"),
            Part(Source.mcp("read_examples", {"names": ["patterns"]}),
                 target="history:tool_result", label="read_examples"),
        ],
        use_composer=False,
        allowed_tools=_DECK_TOOLS,
    ),
    "style_creator": ModeConfig(
        parts=[
            _COMMON_LANGUAGE,
            _persona("style"),
            # Remote's run_style_python has different sandbox I/O than the
            # local server the persona documents (no read_style/write_style)
            Part(Source.file("wiring/style_remote"), target="system"),
            _NOW,
            Part(
                Source.mcp("read_workflows", {"names": ["create-style"]}),
                target="history:tool_result",
                label="read_workflows",
                prefill_text="I'll read the style creation workflow.",
            ),
        ],
        use_composer=False,
        agent_model="create",
        allowed_tools=_STYLE_TOOLS,
    ),
}
