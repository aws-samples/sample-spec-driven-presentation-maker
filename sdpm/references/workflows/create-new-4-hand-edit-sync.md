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
# baseline is the deck directory (deck.json + slides/) or a slides JSON
uv run python3 scripts/pptx_builder.py diff {deck_dir} {edited_pptx}
```

The diff command accepts a deck directory or PPTX file directly (it builds /
converts to roundtrip JSON internally). On MCP, call
`diff_pptx(baseline={deck_dir}, edited={edited_pptx})` instead.

---

### 2. Apply hand-edits to JSON

Read the diff output and apply the hand-edit changes to the deck's slide JSON.

- **Modified elements**: Read property diffs and edit the deck's `slides/*.json` directly
- **Added slides/elements**: The diff output is a summary only. For actual data, run
  `uv run python3 scripts/pptx_to_json.py {edited_pptx} -o {tmp_dir}` (CLI only;
  the MCP path uses `import_attachment` for import-and-commit) — it writes the roundtrip deck structure (`{tmp_dir}/slides/slide-NN.json` +
  `{tmp_dir}/images/`) — then copy the relevant parts into the deck's slide JSON
- **Added images**: Copy them from `{tmp_dir}/images/` into the deck's `images/` and reference via `src`
- **Reordered slides**: Reorder `specs/outline.md` (deck) or the slide array (single JSON)

**Constraints:**
- You MUST use diff output to identify changes — do NOT replace the deck's slide JSON with
  re-extracted roundtrip JSON because roundtrip JSON loses builder-specific metadata
- You MUST apply changes to the deck's original slide JSON, not the roundtrip JSON

---

### 3. Additional edits + regenerate

After syncing hand-edits, apply the user's requested changes and regenerate.

**Constraints:**
- You MUST regenerate after applying all changes (hand-edit sync + additional edits)
