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
    inference: str,
    q0: dict,
    q1: dict = None,
    q2: dict = None,
    q3: dict = None,
    q4: dict = None,
) -> str:
    """Present structured questions to the user via a rich UI card.

    ALWAYS use this tool when you need the user to make a choice or
    judgment — not just for initial interviews but also for mid-workflow
    decisions, confirmations with options, and next-step selections.
    Only skip this tool for simple yes/no confirmations.

    Always include your reasoning or hypothesis in the inference field
    to help the user think — never ask blank questions.
    Limit to 5 questions per call. If you need more, call again after
    the user responds.

    The Web UI renders a dedicated selection card. The user's answers
    are returned as a normal chat message in the next turn.

    Args:
        inference: Your reasoning or hypothesis to share with the user.
            This is displayed prominently above the questions to provide
            context and stimulate the user's thinking.
        q0: First question object with keys:
            - type (str): "single_select", "multi_select", or "free_text"
            - text (str): The question text
            - options (list[str], optional): Choices for select types
            - recommended (str or list[str], optional): Suggested choice(s)
            - placeholder (str, optional): Hint text for free_text type
        q1: Second question (optional, same schema as q0).
        q2: Third question (optional, same schema as q0).
        q3: Fourth question (optional, same schema as q0).
        q4: Fifth question (optional, same schema as q0).

    Returns:
        Confirmation that the questions were displayed. Wait for the
        user's response in the next message.
    """
    return "Questions displayed to user. Wait for their response."
