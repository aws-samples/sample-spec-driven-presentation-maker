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


def _role(tool: str) -> Part:
    """The role document, fetched through the role's entry tool and placed in the system prompt.

    The L4 agent decides roles itself, so the document goes to system at
    discovery time; interactive clients get the same text as a tool result.
    Only the deck-independent part is placed here — per-user data (templates)
    would fragment the prompt cache.
    """
    return Part(
        Source.mcp(tool, {}, pick="static.workflow"),
        target="system",
        label=f"workflow:{tool}",
    )


# The environment start_presentation returns (templates) is per user, so it
# goes into the system prompt *after* the cache point, next to the timestamp, and
# never fragments the cached prefix. The orchestrator sees the same data an
# interactive client's model sees after calling the entry tool.
_ORCHESTRATOR_ENVIRONMENT = [
    Part(Source.file("wiring/environment"), target="system"),
    Part(Source.mcp("start_presentation", {}, pick="templates"), target="system", label="environment"),
]


# Tool allowlists — explicit control over which MCP tools each mode can use.
# run_style_python is only available to style_creator.
#
# Hand-edit sync (diff) is a CLI capability, not an MCP tool; the hand-edit-sync
# guide says how to run it from a checkout.
# start_* are deliberately absent: the role document and start_presentation's
# environment are already in the system prompt, so exposing them would only
# invite a redundant call.
_DECK_TOOLS = [
    "init_deck_workspace", "analyze_template", "read_attachment",
    "list_styles", "apply_style",
    "read_guides", "search_assets",
    "list_templates", "check_specs",
    "run_python", "generate_pptx", "get_preview", "code_to_slide",
    "grid", "arch_diagram", "import_attachment",
]

_STYLE_TOOLS = [
    "run_style_python", "list_styles", "analyze_template", "read_attachment",
]

def _guides(tool: str, args: dict | None = None) -> list[Part]:
    """The guides this role must read, and the listing of every guide it can see.

    The text comes from ``read_guides``, called with the names the role's own entry tool
    reported as mandatory. No guide is named here: which ones a role must read depends on
    the collection, and a user extends that collection.

    This surface has no 30,000-character tool-result limit, so it takes the bodies up front
    rather than leaving the model to ask. An interactive client reads ``must_read`` and
    calls ``read_guides`` itself; the role documents say so.

    Picked from the top level rather than from ``static``: ``_process_cache_key`` shares
    anything under ``static.`` across every user, and a user's own guide must never reach
    another user's prompt. Both parts sit inside the cached prefix — identical for every
    user who has not written a guide of their own, and a user who has genuinely has a
    different prompt.
    """
    args = args or {}
    return [
        Part(
            Source.mcp("read_guides", {"names": Source.mcp(tool, args, pick="must_read")}, pick="guides_text"),
            target="system", label="guides",
        ),
        Part(Source.mcp(tool, args, pick="listing"), target="system", label="guides-listing"),
    ]

_INTERACTION_DIALOGUE = Part(Source.file("wiring/interaction_dialogue"), target="system")
_INTERACTION_FAST = Part(Source.file("wiring/interaction_fast"), target="system")


def _orchestrator(*wiring: Part, use_composer: bool = True, **overrides) -> ModeConfig:
    """Orchestrator workflow plus environment facts the UI decided (interaction depth)."""
    return ModeConfig(
        parts=[
            _COMMON_LANGUAGE,
            _role("start_presentation"),
            *_guides("start_presentation"),
            *wiring,
            _COMMON_ATTACHMENTS,
            *([_WIRING_COMPOSE_REPORT] if use_composer else []),
            _NOW,
            *_ORCHESTRATOR_ENVIRONMENT,
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

# Composer: the role document and the mode's guides are system and cached across
# groups and repeat composes; the per-deck part is replayed per group by compose_slides
# as a start_composing tool result.
_COMPOSER = ModeConfig(
    parts=[
        Part(Source.mcp("start_composing", {}, pick="static.workflow"), target="system", label="workflow:composer"),
        *_guides("start_composing"),
    ],
    use_composer=False,
    allowed_tools=_DECK_TOOLS,
)

# HTML composer: the html mode of the same entry tool. Its tag set picks up
# slide-html-spec where the pptx mode picks up slide-json-spec. compose_slides chooses
# this mode for decks with outputFormat html.
_HTML_COMPOSER = ModeConfig(
    parts=[
        Part(
            Source.mcp("start_composing", {"mode": "html"}, pick="static.workflow"),
            target="system", label="workflow:composer-html",
        ),
        *_guides("start_composing", {"mode": "html"}),
    ],
    use_composer=False,
    allowed_tools=_DECK_TOOLS,
)

_STYLE_CREATOR = ModeConfig(
    parts=[
        _COMMON_LANGUAGE,
        _role("start_style"),
        *_guides("start_style"),
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
    "html_composer": _HTML_COMPOSER,
    "style_creator": _STYLE_CREATOR,
}
