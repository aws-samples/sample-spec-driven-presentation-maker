---
name: planner-answers
description: "Planner: enrich outline with answers, evidence, and details"
category: workflow
---

# Planner: Answers and Evidence

Enriches the approved outline skeleton with structured details per slide.

## Purpose

The outline skeleton has 1 message per slide. This step adds the "why" and "what" behind
each message: what to say, what supports it, and what to show.
The result is a richer outline that gives Phase 2 (build) much more to work with.

## Constraints

- You MUST process one page at a time — do NOT batch multiple pages
- You MUST extract details from the brief or source material
- You MUST NOT invent data not present in source material — mark as [TBD]
- You MUST NOT proceed to the next page until user agrees on current page
- Speak in the user's language, using plain words
- Use inference-based proposals: recommend what to say and show, let the user confirm or redirect
- You MUST use the exact sub-item format (`  - key: value`) with fixed key names: `what_to_say`, `evidence`, `what_to_show`, `notes` — this format is parsed by external tools
- You MUST NOT rename, translate, or add custom keys

## Process

One page at a time: infer details → write directly to `specs/outline.md` under that slide → present what you wrote → user confirms or adjusts → next page.

After all pages are done, ask if any need revision. The outline file is already complete at this point.

## Per-Page Approach

For each page, infer 3 things and write them as sub-items directly to `specs/outline.md`:

- **what_to_say** — the key point and how to explain it
- **evidence** — data, examples, or sources that support it (mark [TBD] if not available)
- **what_to_show** — suggested visual approach (chart, screenshot, diagram, etc.)
- **notes** — (optional) anticipated questions, caveats, etc.

All keys are optional — include only what's relevant.
Write values in the user's language.

Then present what you wrote and ask the user to confirm.

Example:

> I've added details to slide 3 in outline.md:
>
> - [3: Guardrails] Audience trusts they can control agent behavior
>   - what_to_say: You can set policies that limit what the agent can and can't do — control without slowing down development
>   - evidence: Policy editor with 3 built-in templates [TBD: adoption numbers]
>   - what_to_show: Screenshot of policy editor, or before/after comparison
>
> Sound right? Anything to add or change?

The user responds concisely ("ok", or specific adjustments).

## Hints (internal reference for the agent)

**Quality check:**
- Clear assertion? Takes a position?
- Specific (includes numbers)?
- Fits in 1 page? (If not → decompose)

**Visual suggestions by evidence type:**

| Evidence Type | Visual | Intent |
|--------------|--------|--------|
| Time series | Line chart | Show trends |
| Comparison | Bar chart | Compare differences |
| Composition | Pie/Donut chart | Show proportions |
| Multiple metrics | Table | Detailed data |
| Process | Flow diagram | Show sequence |
| System | Architecture diagram | Show structure |

## Completion

After all pages are done, the outline file is already enriched. Ask if any pages need revision, then return to the outline workflow.
