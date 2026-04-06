---
name: spec-driven-presentation-maker
description: "Generate PowerPoint presentations from JSON. Use when user wants to create slides, proposals, or presentation materials."
---

# PPTX Maker

Generate PowerPoint from JSON using corporate templates.
All paths in this file are relative to this SKILL.md. `cd` to this directory before running commands.

## CLI

```bash
uv run python3 scripts/pptx_builder.py {command} [args]
```

**Critical constraint:** Do NOT make any decisions about slide structure, content, design, or layout before loading the workflow. The workflow files contain the full process including briefing, outline, and art direction. Wait until the workflow is loaded and follow it step by step.

**After loading:** Present the options and ask which to do:

A. New presentation — create slides from scratch
B. Edit existing PPTX — modify a provided file
C. Hand-edit sync — continue from a user-edited PPTX
D. Create style — build a reusable style guide

## Workflow A: New Presentation

When no existing PPTX is provided.
→ Run `uv run python3 scripts/pptx_builder.py workflows create-new-1-briefing` to start. Follow each file's Next Step from there.

## Workflow B: Edit Existing PPTX

When an existing PPTX is provided.
→ Run `uv run python3 scripts/pptx_builder.py workflows edit-existing` to start.

## Workflow C: Hand-Edit Sync

When the user hand-edits the generated PPTX in PowerPoint and then asks for further changes.
→ Run `uv run python3 scripts/pptx_builder.py workflows create-new-4-hand-edit-sync` to start.

## Workflow D: Create Style

When the user wants to create a new reusable style guide.
→ Run `uv run python3 scripts/pptx_builder.py workflows create-style` to start.
