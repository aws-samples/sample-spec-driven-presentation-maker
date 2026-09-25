# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP prompts — user-invoked entry points, one per role (plus the two interaction modes).

A prompt is what a client shows in its slash-command / "+" menu. Each one is a
single instruction that names the role's entry tool and, for the orchestrator,
carries the `Interaction mode:` token the orchestrator role document already
understands. Nothing here restates a role; the tool call fetches it.

Servers register these with ``mcp.prompt(...)(fn)``; the functions are plain and
return the user message text.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

_START = "Call `start_presentation()` on the sdpm MCP server first and follow the role document it returns."


def vibe(
    material: Annotated[str, Field(description="Source material or a URL — what the deck is made from.")] = "",
) -> str:
    """Build a deck from material without questions (fast mode)."""
    body = f"\n\n{material}" if material else ""
    return f"Interaction mode: fast\n\n{_START}{body}"


def spec(
    topic: Annotated[str, Field(description="What the deck is about, or the material to start from.")] = "",
) -> str:
    """Shape a deck together in dialogue — audience, message, outline — before it is built (spec mode)."""
    body = f"\n\n{topic}" if topic else ""
    return f"Interaction mode: dialogue\n\n{_START}{body}"


def style(
    brief: Annotated[str, Field(description="The look you want, a brand, or a reference — anything to start from.")] = "",
) -> str:
    """Create a reusable style guide."""
    body = f"\n\n{brief}" if brief else ""
    return f"Call `start_style()` on the sdpm MCP server first and follow the role document it returns.{body}"


def translate(
    deck_id: Annotated[str, Field(description="Path (or ID) of the deck to translate.")],
    language: Annotated[str, Field(description="Target language, e.g. en, ja.")],
) -> str:
    """Translate an existing deck into another language as a sibling deck."""
    return (
        f"Call `start_translation(deck_id={deck_id!r}, language={language!r})` on the sdpm MCP "
        "server first and follow the role document it returns."
    )


PROMPTS = (vibe, spec, style, translate)


# Registered with an ``sdpm-`` prefix: some clients (Kiro CLI's slash menu) list
# prompts by bare name across all servers, where ``spec`` or ``style`` alone would
# be ambiguous. Clients that namespace by server show ``/mcp__sdpm__sdpm-vibe``;
# the redundancy there is the cheaper of the two problems.
PREFIX = "sdpm-"


def register(mcp) -> None:
    """Bind every prompt on a FastMCP/MCPServer instance."""
    for fn in PROMPTS:
        mcp.prompt(name=PREFIX + fn.__name__, description=fn.__doc__)(fn)
