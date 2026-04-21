# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Declarative mode definitions for SDPM agents."""

from dataclasses import dataclass, field


@dataclass
class ModeConfig:
    """Agent mode configuration.

    Attributes:
        prompt_key: Filename (without .md) under prompts/.
        use_composer: Include compose_slides tool.
        prefetch: List of (tool_name, args, label) to prefetch and inject as message history.
        inject_mcp_instructions: Inject collect_mcp_instructions into prompt.
    """

    prompt_key: str
    use_composer: bool = True
    prefetch: list = field(default_factory=list)
    inject_mcp_instructions: bool = False


MODES: dict[str, ModeConfig] = {
    "separated": ModeConfig(
        prompt_key="spec_agent",
        prefetch=[("read_workflows", {"names": ["create-new-1-briefing"]}, "create-new-1-briefing")],
    ),
    "vibe": ModeConfig(
        prompt_key="vibe_agent",
        prefetch=[("read_workflows", {"names": ["create-new-1-briefing"]}, "create-new-1-briefing")],
    ),
    "single": ModeConfig(
        prompt_key="single_agent",
        use_composer=False,
        inject_mcp_instructions=True,
    ),
}
