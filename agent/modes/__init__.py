# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Declarative mode definitions for SDPM agents."""

from dataclasses import dataclass, field

from composition import Part, Source


@dataclass
class ModeConfig:
    """Agent mode configuration.

    Attributes:
        parts: Ordered prompt parts (static .md files, MCP prefetch, or callables).
        use_composer: Include compose_slides tool.
    """

    parts: list[Part] = field(default_factory=list)
    use_composer: bool = True


# Shared parts — referenced by multiple modes
_COMMON_LANGUAGE = Part(Source.file("common/language"), target="system")
_COMMON_ATTACHMENTS = Part(Source.file("common/attachments"), target="system")
_WF_CANCELLATION = Part(Source.file("workflow/cancellation"), target="system")
_WF_POST_COMPOSE = Part(Source.file("workflow/post_compose"), target="system")
_WF_SLIDE_GROUPS = Part(Source.file("workflow/slide_groups"), target="system",
                        cache_point=True)
_NOW = Part(Source.file("common/now"), target="system")

_PREFETCH_BRIEFING = Part(
    Source.mcp("read_workflows", {"names": ["create-new-1-briefing"]}),
    target="history:tool_result",
    label="read_workflows",
    prefill_text="Starting the Briefing phase. I'll read the workflow to conduct the hearing properly.",
)


MODES: dict[str, ModeConfig] = {
    "separated": ModeConfig(parts=[
        _COMMON_LANGUAGE,
        Part(Source.file("role/spec_agent"), target="system"),
        _COMMON_ATTACHMENTS,
        _WF_CANCELLATION,
        _WF_POST_COMPOSE,
        _WF_SLIDE_GROUPS,
        _NOW,
        _PREFETCH_BRIEFING,
    ]),
    "vibe": ModeConfig(parts=[
        _COMMON_LANGUAGE,
        Part(Source.file("role/vibe_agent"), target="system"),
        _COMMON_ATTACHMENTS,
        Part(Source.file("workflow/vibe"), target="system"),
        _WF_CANCELLATION,
        _WF_POST_COMPOSE,
        _WF_SLIDE_GROUPS,
        _NOW,
    ]),
    "single": ModeConfig(
        parts=[
            _COMMON_LANGUAGE,
            Part(Source.file("role/single_agent"), target="system",
                 cache_point=True),
            _NOW,
        ],
        use_composer=False,
    ),
    # Composer is a sub-agent invoked by compose_slides; ModeConfig is used
    # by compose_slides to build its prompt via the same resolve_parts path.
    # Dynamic parts (deck specs, template analysis) are added at runtime.
    "composer": ModeConfig(
        parts=[
            Part(Source.file("role/composer"), target="system"),
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
    ),
}
