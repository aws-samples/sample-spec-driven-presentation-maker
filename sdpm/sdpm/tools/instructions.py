# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Workflow instructions served to MCP clients.

Single source for the entry-point instructions. Servers expose this both as
MCP Server Instructions (for clients that read them) and via the
``start_presentation`` tool (for clients that do not).
"""

INSTRUCTIONS = """spec-driven-presentation-maker: AI-powered PowerPoint generation from JSON.

**Mode shortcuts:** if the user's intent is already clear, skip this menu and call
`start_presentation(mode=...)` — `"vibe"` for fast generation from existing material
(minimal questions), `"spec"` for dialogue-driven design with hearings and approvals,
`"style"` for creating a reusable style guide, `"translate"` for translating an existing
deck into another language. The returned instructions replace this menu.

**Critical constraint:** Do NOT make any decisions about slide structure, content, design, or layout before loading the workflow. The workflow files contain the full process including briefing, outline, and art direction. Wait until the workflow is loaded and follow it step by step.

**Present the options and ask which to do:**

A. New presentation — create slides from scratch
B. Edit existing PPTX — modify a provided file
C. Hand-edit sync — continue from a user-edited PPTX
D. Create style — build a reusable style guide
E. Translate deck — create a language variant of an existing deck

## Workflow A: New Presentation

When no existing PPTX is provided.
→ Read `read_workflows(["create-new-1-briefing"])` to start. Follow each file's Next Step from there.

## Workflow B: Edit Existing PPTX

When an existing PPTX is provided. Call `read_attachment(source)` with the
file path first — for PPTX the response header contains `guide` and
`guideInstruction` fields, so follow that instruction to proceed with
the import-pptx guide. (Web UI uploads provide the source in the
`[Attached:...]` marker.)

## Workflow C: Hand-Edit Sync

When the user hand-edits the generated PPTX in PowerPoint and then asks for further changes.
→ Read `read_workflows(["create-new-4-hand-edit-sync"])` to start.

## Workflow D: Create Style

When the user wants to create a new reusable style guide.
→ Read `read_workflows(["create-style"])` to start.

## Workflow E: Translate Deck

When the user wants an existing deck in another language (e.g. "translate this deck
to English"). The translation is written to a derived sibling deck — the original
stays untouched. If only the source PPTX exists, import it first (Workflow B).
→ Call `start_presentation(mode="translate")` and follow the returned instructions.
"""
