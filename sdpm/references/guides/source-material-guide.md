---
description: "Rules for incorporating user-provided assets — read when source slides or images are provided"
---

# Source Material Guide

How to incorporate existing PPTX files as source material.
Reference this when existing PPTX is provided during Phase 1 (art direction).

## Procedure

Run the following for each PPTX (`{name}` is the filename without extension):

1. Convert the existing PPTX to JSON to get structural data
   ```bash
   uv run python3 scripts/pptx_to_json.py {input_pptx} -o /tmp/sdpm/{name}/{name}.json
   ```
2. Generate previews to see all slides visually
   ```bash
   uv run python3 scripts/pptx_builder.py preview {input_pptx} --no-grid
   ```
3. Read all preview images to understand each slide's content

## Reuse assessment

Review preview images and JSON, then inventory the following:
- **Reusable pages**: Slides that can be used as-is or with minor edits (layout structure and message align with the brief)
- **Reusable text**: Boilerplate, product descriptions, company overviews, numerical data
- **Reusable visuals**: Architecture diagrams, comparison tables, flow diagrams (shape groups, tables, freeforms, etc.)

Present the inventory to the user and agree on what to reuse.

## Rules
- Output to `/tmp/sdpm/{name}/` — use distinct names to avoid collisions across multiple PPTXs
- Complete both JSON conversion AND preview before proceeding to reuse assessment
- Do NOT reuse colors (fill, fontColor, line, etc.) or styles — re-apply according to the new theme and design-rules.md
- Only content (text, data, diagram structure) may be reused
- Present reuse candidates to the user and get approval before using them

## Rules when reusing source material:
- Copy the JSON structure of reusable slides from source_json and modify text/data to fit the new brief
- For diagram elements (tables, shape groups, freeforms, etc.), copy structure and coordinates, update content only
- Strip all colors (fill, fontColor, line, etc.) and styles from the source — re-apply according to the new theme and design-rules.md
- Consider using override to create variations based on reused slides
