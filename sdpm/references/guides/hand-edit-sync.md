---
name: hand-edit-sync
description: "Phase 4: Sync after hand-editing (only when requested)"
category: workflow
---

# Phase 4: Sync After Hand-Editing

Run this when the user has hand-edited the PPTX in PowerPoint and then asks the agent for further changes.
The agent always edits the deck's source JSON, so hand-edits must be synced there first — otherwise they are lost on regeneration.

---

### 0. Review available guides

Call `list_guides()` and use `read_guides([...])` for guides relevant to the upcoming edits.

**Constraints:**
- You MUST complete Steps 1-2 BEFORE making any additional edits because hand-edits will be lost on regeneration

---

### 1. Run diff

Call `diff_pptx(baseline={deck_dir}, edited={edited_pptx})`. The baseline
may be a deck directory, slides JSON, or PPTX; the operation builds or converts
to round-trip JSON internally.

> **Local / CLI only.** `servers/remote` does not bind `diff_pptx`, so this step
> is unavailable on the cloud stack (Web UI + L4 agent) and the tool is not in the
> agent's allowlist. It is also slated for removal. On the cloud path, treat an
> edited PPTX as an import instead: `import_attachment` commits it and you work
> from the resulting deck rather than diffing against the old one.

---

### 2. Apply hand-edits to JSON

Read the diff output and apply the hand-edit changes to the deck's slide JSON.

- **Modified elements**: Read property diffs and edit the deck's `slides/*.json` directly
- **Added slides/elements**: The diff output is a summary only. Convert the
  edited PPTX to a temporary round-trip deck structure (or use `import_attachment`
  where available), then copy the relevant parts from `slides/slide-NN.json` and
  `images/` into the deck's source JSON.
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
