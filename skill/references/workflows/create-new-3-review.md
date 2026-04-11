---
name: new-phase-3-review
description: "Phase 3: Generate + review + polish"
category: workflow
---

# Phase 3: Generate + Review + Polish

Generate the PPTX, review the preview, and polish.

**Reminder:** Read relevant guides as needed.

---

### 1. Generate + measure

```bash
# Generate PPTX
uv run python3 scripts/pptx_builder.py generate {output_json} -o {project_dir}/output.pptx

# Final text measurement across all slides
uv run python3 scripts/pptx_builder.py measure {output_json}
```

If warnings appear during generation, address them in Step 3 (Polish):

- **Layout bias detected**: Vertical balance of elements is skewed. Adjust element heights, spacing, or placement to resolve — unless the bias is intentional by design

If measure shows text sizes that differ significantly from your declared heights, address them in Step 3 (Polish). The measure output includes guidance on what to adjust.

**Constraints:**
- You MUST fix Layout bias warnings unless the bias is intentional by design because unbalanced layouts look unprofessional

---

### 2. Design review

Review preview PNGs for design quality.

```bash
uv run python3 scripts/pptx_builder.py preview {output_json}
```

Read preview images with fs_read Image mode.

If grid-overlaid PNGs are needed for position checking:
```bash
uv run python3 scripts/pptx_builder.py preview {output_json} --grid
```

**Constraints:**
- You MUST read ALL preview images before reporting because partial review misses cross-slide inconsistencies
- You MUST check: clarity, layout, text, design
- If element positions look wrong in the preview (e.g. overlapping, misaligned, outside content area), you MUST treat the preview as the source of truth and fix coordinates in the JSON — placeholder positions from analyze-template are guides, not exact specifications

---

### 3. Polish

Edit output_json directly based on review findings and user feedback, then regenerate.
Warnings from Step 1 (Layout bias) and measure discrepancies are also addressed here.

**Constraints:**
- You MUST re-run Step 1 (Generate + measure) → Step 2 (Review) after making changes because edits may introduce new issues

---

### 4. Completion

After polish is done, ask the user whether they want additional reviews.

When no style was specified for this project and the art-direction or polish process involved
significant design decisions (color choices, decoration rules, layout patterns), propose:
"Would you like to save these design decisions as a reusable style?"
If accepted, start Workflow D (`create-style`). The conversation context becomes the input.

**Constraints:**
- You MUST ask the user whether they want additional reviews before completing
