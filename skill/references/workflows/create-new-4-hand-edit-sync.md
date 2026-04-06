---
name: new-phase-4-hand-edit-sync
description: "Phase 4: Sync after hand-editing (only when requested)"
category: workflow
---

# Phase 4: Sync After Hand-Editing

Run this when the user has hand-edited the PPTX in PowerPoint and then asks the agent for further changes.
The agent always edits output_json, so hand-edits must be synced to output_json first — otherwise they are lost on regeneration.

---

### 0. Review available guides

Run `guides` to review available guides. Read any that are relevant to the upcoming edits.

**Constraints:**
- You MUST complete Steps 1-2 BEFORE making any additional edits because hand-edits will be lost on regeneration

---

### 1. Run diff

```bash
uv run python3 scripts/pptx_builder.py diff {output_json} {edited_pptx}
```

The diff command accepts a PPTX file directly (it runs pptx_to_json internally).

---

### 2. Apply hand-edits to JSON

Read the diff output and apply the hand-edit changes to output_json.

- **Modified elements**: Read property diffs and edit output_json directly
- **Added slides/elements**: Copy the relevant parts from `/tmp/sdpm/{project}/edited/slides.json` into output_json (diff output is a summary only — refer to the roundtrip JSON for actual data)
- **Added images**: Reference them via src path from `/tmp/sdpm/{project}/edited/images/`
- **Reordered slides**: Change the slide array order in output_json

**Constraints:**
- You MUST use diff output to identify changes — do NOT re-extract the entire PPTX because roundtrip JSON loses builder-specific metadata
- You MUST apply changes to the original output_json, not the roundtrip JSON

---

### 3. Additional edits + regenerate

After syncing hand-edits, apply the user's requested changes and regenerate.

**Constraints:**
- You MUST regenerate after applying all changes (hand-edit sync + additional edits)
