# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Strands Agent tool for structured user interviews.

The hearing tool displays a structured question UI in the Web UI,
enabling the agent to gather user input through selection-based
and free-text questions instead of plain chat.
"""

from strands import tool


@tool
def hearing(
    q0: dict,
    q1: dict = None,
    q2: dict = None,
    q3: dict = None,
) -> str:
    """Present structured questions to the user via a rich UI card.

    ALWAYS use this tool when you need the user to make a choice or
    judgment — not just for initial interviews but also for mid-workflow
    decisions, confirmations with options, and next-step selections.
    Only skip this tool for simple yes/no confirmations.

    Share your hypothesis through the options: mark the option you
    suggest as recommended and say in its description why — never ask
    blank questions. The card adds an "Other" choice with a text field
    to every select question itself, so list only real options.
    Limit to 4 questions per call. If you need more, call again after
    the user responds.

    The Web UI shows one question at a time. The user's answers are
    returned as a normal chat message in the next turn.

    Args:
        q0: First question object with keys:
            - header (str): Short label shown as a chip (about 6
              Japanese or 12 English characters), e.g. "聞き手"
            - type (str): "single_select", "multi_select", or "free_text"
            - text (str): The question text
            - options (list[dict], select types): 2-4 choices, each
              {"label": str, "description": str, "recommended": bool}.
              label is short; description is one line on what choosing
              it leads to or its trade-off; recommended (optional) marks
              your suggestion
            - placeholder (str, optional): Hint text for free_text type
        q1: Second question (optional, same schema as q0).
        q2: Third question (optional, same schema as q0).
        q3: Fourth question (optional, same schema as q0).

    Returns:
        Confirmation that the questions were displayed. Wait for the
        user's response in the next message.
    """
    return "Questions displayed to user. Wait for their response."
