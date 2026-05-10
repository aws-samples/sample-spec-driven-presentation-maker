# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP Server variant for clients that do NOT read Server Instructions.

Adds a `start_presentation` tool that returns the workflow instructions.
Clients that support Server Instructions should use server.py instead.

Usage:
    python server_with_instruction.py
"""

from server import mcp, _INSTRUCTIONS


@mcp.tool()
def start_presentation() -> str:
    """REQUIRED FIRST STEP for creating any PowerPoint/presentation/slide deck.
    Call this before using any other tool when the user wants to create, edit, or modify slides.

    Returns the complete workflow options and step-by-step instructions.
    """
    return _INSTRUCTIONS


if __name__ == "__main__":
    mcp.run(transport="stdio")
