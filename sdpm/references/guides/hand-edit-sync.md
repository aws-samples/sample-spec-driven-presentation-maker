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

Use `read_guides([...])` for the guides relevant to the upcoming edits.

**Constraints:**
- You MUST complete Steps 1-2 BEFORE making any additional edits because hand-edits will be lost on regeneration

---

### 1. Run diff

Run the diff from the sdpm checkout (it is a CLI operation, not an MCP tool — it
needs an environment with shell access, like the translate workflow):

```
uv run python3 scripts/pptx_builder.py diff_pptx {deck_dir} {edited_pptx}
```

The baseline may be a deck directory, slides JSON, or PPTX; the operation builds or
converts to round-trip JSON internally.

> Without shell access (Claude Desktop, the cloud Web UI), treat the edited PPTX as
> an import instead: `import_attachment` commits it and you work from the resulting
> deck rather than diffing against the old one.

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

### 2a. Animations and transitions added in PowerPoint

Only relevant when the diff reports transition or animation changes, or when the user says
they used the Animations / Transitions tabs. The contract for the fields below is
`read_guides(["animations"])`.

The diff reports motion the same way it reports anything else — added, removed, reordered
and modified effects by their stable effect ID, and changed transition fields — and
summarises preserved raw XML by digest and affected target names rather than dumping the
document. Apply those changes to the deck's `slides/*.json`:

- **A transition** becomes a `transition` object on the slide **it lands on** (PowerPoint
  stores a transition on the destination slide). PowerPoint's *Apply to All* becomes the same
  object copied into every slide file — there is no deck-wide transition.
- **Object animations** become `animations.mainSequence` (array order = effect order) and one
  `animations.interactiveSequences` entry per trigger shape. Each effect needs the shape's
  logical `id` in `target.element`, so give the animated element an `id` if it has none.
- **Morph** needs the matching objects on both slides to carry the same `morphId`, and the
  `transition` on the destination slide only.
- Anything the converter could not decode semantically comes back as a `_rawTiming` /
  `_rawTransition` reference into an import bundle rather than as editable fields. Copy the
  reference across unchanged together with its `animations/` closure, and never put a raw
  reference and the semantic field for the same feature on one slide — that fails lint
  instead of merging.

**Constraints:**
- You MUST preserve an explicit `animations` / `transitions` switch in `deck.json` exactly as
  the user set it. Derive a switch only when `deck.json` has none, and then from the content
  the edited PPTX actually carries. Never flip an explicit `true` to `false` because this
  round's diff showed no motion.
- You MUST set `animations.enabled` / `transitions.enabled` to `true` when you add the first
  such field to a deck that has neither switch — otherwise the setting is written and then
  suppressed at build time.
- You MUST leave the slide understandable with both switches off. If a hand edit moved a
  claim into an animated state only, fix the static slide too and say so.

---

### 3. Additional edits + regenerate

After syncing hand-edits, apply the user's requested changes and regenerate.

**Constraints:**
- You MUST regenerate after applying all changes (hand-edit sync + additional edits)
- You MUST verify the regenerated deck still carries the synced motion: run the diff once
  more and confirm it reports no transition or animation difference you did not intend
- If generation refuses a setting by catalog key (`animation.*` / `transition.*`), that
  setting is one sdpm can preserve but cannot yet write. Report it to the user and leave the
  field in place; do not delete it, and do not substitute a different effect, to get a build
