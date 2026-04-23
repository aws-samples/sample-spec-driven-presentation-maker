# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Strands Agent tool for structured user interviews.

The hearing tool displays a structured question UI in the Web UI,
enabling the agent to gather user input through selection-based
and free-text questions instead of plain chat.
"""

from strands import tool


@tool
def hearing(inference: str, questions: list[dict]) -> str:
    """Present structured questions to the user via a rich UI card.

    Use this tool when you need specific input from the user and want to
    provide clear options rather than asking open-ended questions.
    Always include your reasoning or hypothesis in the inference field
    to help the user think — never ask blank questions.

    The Web UI renders a dedicated selection card. The user's answers
    are returned as a normal chat message in the next turn.

    Args:
        inference: Your reasoning or hypothesis to share with the user.
            This is displayed prominently above the questions to provide
            context and stimulate the user's thinking.
        questions: List of question objects. Each question has:
            - id (str): Unique question identifier (e.g. "q1")
            - type (str): "single_select", "multi_select", or "free_text"
            - text (str): The question text
            - options (list[str], optional): Choices for select types
            - recommended (str or list[str], optional): Suggested choice(s)
            - placeholder (str, optional): Hint text for free_text type

    Returns:
        Confirmation that the questions were displayed. Wait for the
        user's response in the next message.
    """
    return "Questions displayed to user. Wait for their response."
