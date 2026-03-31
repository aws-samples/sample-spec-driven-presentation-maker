---
name: new-phase-1-outline
description: "Phase 1: Outline design"
category: workflow
---

# Phase 1: Outline Design

Break the agreed brief into per-slide units.

## Deliverable

`specs/outline.md` — approved by the user.

You MUST NOT read the next workflow file until the user explicitly approves `specs/outline.md`.

## Constraints

- You MUST NOT read any other workflow file until `specs/outline.md` is approved
- You MUST read `guides storytelling-vocabulary` before starting the outline — it contains the presentation structure frameworks you need for Step 1
- Each slide MUST have exactly one message — if a message cannot be expressed in one sentence, split the slide
- Before each step, briefly explain what you are doing and what the user needs to decide
- Speak in the user's language, using plain words
- Use inference-based proposals: recommend with rationale, list alternatives briefly — let the user confirm or redirect
- The brief defines what to convey and why — story structure is decided here, not in the brief
- Also cover what the audience would naturally wonder, even if not in the brief
- Include or omit opening/closing slides (title, agenda, summary, ending) based on duration and audience — no need to ask separately

## Steps

### 1. Recommend a structure

Choose a presentation structure from storytelling-vocabulary that fits the brief's intent and audience.
Explain:
- **Why** this structure fits (brief content, audience attributes)
- **How** the slides will flow (concrete section sequence)
- **Effect** on the audience (what they'll take away)

Also mention 2-3 alternatives briefly so the user knows other options exist.

The user confirms ("ok") or redirects.

Example:

> The audience isn't familiar with this yet, so starting with the big picture before diving into each feature should work well.
> Flow: Big picture → Management features → Integration features → Next steps
> This way they can find the area most relevant to them.
> Other options: chronological order or highlights-only, but with this much content, grouping by topic keeps things organized.
>
> Sound good?

### 2. Write outline

Once the structure is confirmed, derive the full slide list from the brief and write `specs/outline.md`.

**Each line = 1 slide = 1 message** — what it changes in the audience and how.
`[N: label]` — label is a short identifier for the outline, not the slide title.

When multiple slides share the same visual base, give them the same label prefix.
The stable base lets the audience focus on what changed, not re-read the whole slide.
Typical cases:
- Building up a diagram layer by layer — a complex picture shown all at once overwhelms; adding one piece at a time guides the eye
- Showing the whole first, then zooming into each part — the overview gives context, then each slide highlights one area with detail; the audience always knows where the detail fits
- Highlighting the current section in an agenda — when there are many sections, repeating the agenda with the active one marked keeps the audience oriented
- Swapping content in the same frame — identical layout makes differences stand out (case studies, comparisons, options)

```markdown
- [1: Title] What it changes in the audience and how
- [2: Current state] What it changes in the audience and how
- [3: Feature A] What it changes in the audience and how
```

Present the outline to the user and ask for feedback.

Example:

> Here's the slide list based on the brief:
>
> - [1: Title] Audience knows the topic and speaker
> - [2: Big picture] Audience sees how much has changed — sets expectation for depth
> - [3: Architecture - components] Audience grasps the building blocks
> - [4: Architecture - data flow] Audience understands how data moves between components
> - [5: Architecture - security] Audience sees where guardrails are applied
> - [6: Next steps] Audience has a concrete action to take Monday morning
>
> Want to add, remove, reorder, or reword anything?

Iterate until the user approves.

Iterate until the user approves the outline.

---

## Next Step

Once the user approves the outline, offer three options.
Detailing means working out what to say, evidence, and supporting data per slide — this makes art direction decisions sharper, but takes more time.

Present the options so the user can answer with a single letter:

> Detailing talking points and evidence per slide helps art direction — knowing what to say clarifies what to show.
> **(a)** Detail all slides **(b)** Detail specific slides (e.g. "b 3,5,8") **(c)** Skip → art direction

- All → read `planner-answers` and follow its process for all slides. Do NOT enrich the outline yourself.
- Pick → read `planner-answers` and follow its process for the specified slides only.
- Skip → read `create-new-1-art-direction` and proceed to art direction.

Do not proceed without the user's explicit choice.
