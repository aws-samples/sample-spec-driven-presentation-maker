# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Prompt template loading and variable substitution."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Load a prompt template from the prompts/ directory.

    Args:
        name: Filename without extension (e.g. 'spec_agent', 'composer').

    Returns:
        Raw template string with placeholders intact.
    """
    return (_PROMPTS_DIR / f"{name}.md").read_text()


def build_system_prompt(template: str, **kwargs: str) -> str:
    """Replace template variables in a prompt string.

    Always injects {now} with current JST timestamp.
    All other placeholders are replaced from kwargs.
    Unknown placeholders are left as-is.

    Args:
        template: Prompt template string.
        **kwargs: Placeholder replacements (e.g. mcp_instructions, common_context, deck_id).

    Returns:
        Formatted prompt string.
    """
    jst = timezone(timedelta(hours=9))
    now_str = datetime.now(jst).strftime("%Y-%m-%d %H:%M JST")
    result = template.replace("{now}", now_str)
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", value)
    return result
