# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Short workflow discovery instructions served to MCP clients."""

INSTRUCTIONS = """spec-driven-presentation-maker: AI-powered PowerPoint generation from JSON.

Choose the workflow that matches the role:
- Create or edit a deck: `read_workflows(["orchestrator"])`
- Write assigned slides: `read_workflows(["composer"])`
- Create a reusable style guide: `read_workflows(["style"])`
- Translate an existing deck: `read_workflows(["translate"])`

Deck files are written only through `run_python` (never with client-side file tools):
it validates the JSON, rebuilds the PPTX and, with `measure_slides`, renders previews.
"""
