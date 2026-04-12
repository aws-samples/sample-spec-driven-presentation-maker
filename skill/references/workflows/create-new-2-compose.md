---
name: new-phase-2-compose
description: "Phase 2: Compose slides — design then build with measure feedback"
category: workflow
---

# Phase 2: Compose

Design then build each slide. Build is iterative — place components, measure, adjust.

## Design = Style × Components × Patterns

Slide design is formed by three layers:
- **Style** (art-direction.html) — visual tokens: colors, typography, spacing, decoration
- **Components** — building blocks: how to construct each element (card, icon-label, table, etc.)
- **Patterns** — composition thinking: how to arrange components to express a message

Components and patterns are references, not constraints. They teach principles and techniques —
you are expected to combine, adapt, and invent new compositions that don't exist in the catalog.
Do not shy away from complex compositions or subtle decoration — details that carry
no information still carry craft. The audience feels the difference.
Bold layouts — asymmetry, extreme size contrast, generous whitespace, full-bleed visuals —
create impact. Safe, centered, evenly-spaced arrangements are forgettable.
The slide-json-spec gives you the full vocabulary of what's possible; components and patterns
show how others have used that vocabulary. Use them as a springboard, not a ceiling.
Style decides *how it looks*. Components decide *what to use*. Patterns decide *how to compose*.

**Before starting, you MUST run:**

```bash
uv run python3 scripts/pptx_builder.py workflows slide-json-spec
uv run python3 scripts/pptx_builder.py guides grid
uv run python3 scripts/pptx_builder.py examples components/all
uv run python3 scripts/pptx_builder.py examples patterns
```

**Reminder:** Read relevant guides as needed. When a slide contains a chart, read the corresponding guide (`guides chart-bar`, `guides chart-line`, or `guides chart-pie`) before building elements.

Slides that share a label prefix in the outline share a visual base — use override (inheritance) to build them. The base slide carries the common elements; each derived slide adds or highlights its part. Slide transitions between them create animation effects.

---

## Procedure

```
load(slide-json-spec, grid-guide, components)
patterns = read("examples patterns")   # read the full catalog once

for slide in slides:
    # Design
    read_patterns(relevant ones)
    think: message + visual structure together
    check: layout fits message? no repetition?

    # Build — iterative
    while components remain or adjustments needed:
        place(next components)
        measure()                       # actual rendered size
        adjust or continue              # result feeds next decision
```

**Why iterative build?** The actual rendered size of text affects everything that follows.
A title's real height determines where the content area starts. A card's text wrapping
determines whether the card width works. You cannot know these until you measure.
Building everything at once and checking later means large rework when something doesn't fit.
Building incrementally lets each measurement inform the next placement decision.

Early in the deck, measure frequently — font size and width interact in ways you can only
learn by seeing the result. Once you have a feel for how text behaves at a given size and width,
you can place more components before measuring, or even build a full slide in one pass.

**You MUST write one slide at a time.** Do NOT batch-generate multiple slides at once.
Writing all slides in a single operation risks output truncation and write failure — always write per slide.

---

## Design

For each slide, think through what to say and how to show it — together.

1. Check the slide's message in `specs/outline.md`
2. Apply the design tokens and visual language from art direction (already internalized in Phase 1)
3. Read several patterns (`examples patterns/N`) that might express the message's logical structure. Don't copy one pattern — absorb the thinking from multiple patterns and combine, adapt, or reinvent. The message drives the design; patterns expand how you deliver it.
4. Decide notes content and visual structure together — what you say shapes how you show it, and how you show it shapes what you say. The message's logical structure determines the layout, not the number of items. Three points don't automatically mean three cards — think about what relationship the items have (hierarchy, sequence, contrast, grouping) and choose a layout that expresses it.
5. No repetition without intent. Same layout on consecutive slides feels monotonous — the audience sees the shape before reading the words. Same component reused across the deck feels cheap — especially containers. Don't default to lining up cards. Explore different components, add supporting elements (icons, dividers, accent shapes), or rethink the layout entirely. Vary unless repetition serves a clear purpose (e.g. comparison).
6. Check: does this layout fit the message's logical structure? If not, rethink before building.

## Build

Build is not a single pass — it is a loop of place, measure, adjust.

The actual rendered size of an element affects what comes next. A title that wraps to 3 lines
instead of 2 pushes the content area down. A card whose text is wider than expected needs a
different width — which changes the spacing for all cards in the row. You cannot know these
until you measure — and you cannot measure until you write.

Write partial elements, measure, then write more. For example: write the title and subtitle,
measure to see their actual height, then use that height to decide where the content area starts.
Write one card, measure to confirm the text fits, then write the remaining cards with the same
dimensions. Do not write all elements at once and measure afterward — by then every decision
is already made and measurement can only confirm or force rework.

**measure:**

```bash
uv run python3 scripts/pptx_builder.py measure {output_json} -p {slide_number}
```

Reports each text element's actual position, size, line count, and text preview.
Compare the actual size against your intended size (the `height` you declared in JSON).
The measure output includes guidance on what to adjust when sizes don't match.

Early in the deck, measure after each major component — this is how you learn the relationship
between font size, width, and line count for this deck's content. Once you have a feel for how
text behaves, you can write more components before measuring, or even build a full slide in one pass.

If measure reveals that the layout structure itself doesn't work (not just a size tweak, but
the design assumption was wrong — e.g., too much text for a 3-column layout), go back to
Design and rethink the structure. Forcing text into a broken layout produces worse results
than changing the layout.

**coordinate calculation:**
- Decide structure first, then calculate coordinates — computing coordinates before structure makes the layout rigid
- **grid command**: rectangular layouts — rows × columns with items at intersections
- **inline python** (`python3 -c "..."`): everything else — arcs, bezier curves, radial placement, trigonometric positions, color interpolation, any free-form calculation. Use it whenever you need a value that isn't a simple grid intersection
- Relying only on grid produces rectangular arrangements for every slide. Inline python unlocks curves, diagonals, and organic placement that give a deck visual variety
- When both are needed (e.g. arc positions + card internals), use inline python for the outer structure and grid for the inner content

**search-assets:**
- AWS icons have `_dark` and `_light` variants — select based on the template's background color from `analyze-template` Theme Colors (dark background → `_dark`, light background → `_light`)

**build_elements:**
- Do not carry over colors or styles from source slides — always apply the new theme's design guidelines because source styles conflict with the target theme
- Do not use emoji in slide text, titles, or notes — emoji render inconsistently across platforms. Use icons (`search-assets`) instead
- Include reference URLs in `notes` (after `---` separator) when the slide content is based on external sources
- When placing images, maintain the original aspect ratio — run `image-size {path} --width {px}` or `--height {px}` to get the correct dimensions before writing the element. If width-based calculation exceeds the content area height, recalculate with `--height` instead
- When building a code block, use the `code-block` command and include the output via `{"type": "include", "src": "code.json"}`

**custom template:**
- Use layout names from `analyze-template` output in the `layout` field
- When using a layout for the first time, read its detail via `analyze-template {template} --layout {name}` to understand placeholder positions and content areas

---

## Next Step

Once all slides are composed, read `create-new-3-review` and proceed to Phase 3.
Do NOT ask the user for confirmation — continue non-stop.
The user is away once Phase 2 starts. Stopping to ask breaks the flow and delays completion.
