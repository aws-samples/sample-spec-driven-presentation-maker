## Post-Compose Workflow
**Only runs when `status: "completed"`. If cancelled or errored, skip this section.**

Run a 3-step workflow: consistency review by a single composer, then
verification, then parallel per-slide fixes if defects remain.

1. Check `outline_check` in the report — if `missing` is non-empty, decide whether to retry or inform the user
2. **Consistency review pass**: call `compose_slides(deck_id, slide_groups=[{
     "slugs": [...all slugs in the deck...],
     "instruction": "Consistency review."
   }])`.
   One group covering the entire deck — the composer reviews cross-slide
   inconsistencies (labeling, decorative elements, typography, writing
   style, hierarchy) using get_preview. See composer's Consistency Review
   Mode for the full criteria.
3. **Verification**: call `get_preview(deck_id, slugs=[...])` to see the
   post-review state. Look for individual-slide defects that remain:
   text overflow, element overlap, broken layout, alignment issues.
   Cross-slide consistency should already be handled by Step 2, so do
   not re-review for that here.
4. **Per-slide fix pass** (only if defects found in Step 3): call
   `compose_slides` again with **parallel groups, one per affected
   slide**. Instructions MUST describe the problem, not the solution:
   - ✅ "text overflows the card on data-points"
   - ❌ "reduce fontSize to 20pt" / "increase height to 60px"
   Each fix is self-contained so parallelism is safe and fast.
5. Present the final result to the user with preview images
