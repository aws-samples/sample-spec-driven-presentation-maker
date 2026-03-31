---
name: new-phase-2-compose
description: "Phase 2: Compose slides — notes + elements, one slide at a time"
category: workflow
---

# Phase 2: Compose

Build each slide one at a time: notes first, then elements.

**Before starting, you MUST run:**

```bash
uv run python3 scripts/pptx_builder.py workflows slide-json-spec
uv run python3 scripts/pptx_builder.py guides grid
uv run python3 scripts/pptx_builder.py examples components/all
uv run python3 scripts/pptx_builder.py examples patterns
```

**Reminder:** Read relevant guides as needed.

Slides that share a label prefix in the outline share a visual base — use override (inheritance) to build them. The base slide carries the common elements; each derived slide adds or highlights its part. Slide transitions between them create animation effects.

---

## Procedure

```
load(slide-json-spec, grid-guide, components)
patterns = read("examples patterns")   # read the full catalog once

for slide in slides:
    read_patterns(relevant ones)        # read several patterns for this slide
    notes    = write_notes(outline, art_direction)
    source   = lookup_source(slide)
    grid     = run("grid", ...)
    assets   = run("search-assets", ...)
    elements = build_elements(grid, assets, source)
    write(slide)                        # notes + elements — one slide at a time
```

Each variable is input to the next step — do not skip or reorder.
Complete one full iteration before moving to the next slide.

**You MUST write one slide at a time.** Do NOT batch-generate multiple slides at once.
Skipping `grid` or `search-assets` produces broken layouts and missing icons — these are not optional.
Writing all slides in a single operation risks output truncation and write failure — always write per slide.

---

## Notes

For each slide, write notes before elements. Notes are the content spec — you cannot build elements without knowing what the slide says.

1. Check the slide's message in `specs/outline.md`
2. Read `specs/art-direction.html` — this HTML IS the target design. The visual style shown in the HTML
   (colors, typography, containers, spacing, decoration) is exactly what the slides should look like.
   Read `:root` CSS variables for concrete design tokens (hex colors, pt sizes, shadow values).
   Use these values directly in slides.json.
3. Read several patterns (`examples patterns/N`) that might offer effective ways to express the message's logical structure. Don't copy one pattern — absorb the thinking from multiple patterns and combine, adapt, or reinvent. The message drives the design; patterns expand how you deliver it.
4. Write `notes` (speaker notes) — must align with the message in outline.md

## Elements

For each slide, build elements after notes are written.

**grid:**
- Computing coordinates before deciding structure makes the layout rigid — decide structure first, then map to coordinates

**search-assets:**
- AWS icons have `_dark` and `_light` variants — select based on the template's background color from `analyze-template` Theme Colors (dark background → `_dark`, light background → `_light`)

**build_elements:**
- Use components / style components and grid output coordinates
- When style is specified, use the style's components as the primary source — common/components provides the foundation, style provides the application
- Do not avoid or simplify a component/layout just because it is complex — use the component that best fits the content. Simplification is only acceptable when the agreed design level (1/2/3) explicitly calls for it
- Do not carry over colors or styles from source slides — always apply the new theme's design guidelines because source styles conflict with the target theme
- Do not use emoji in slide text, titles, or notes — emoji render inconsistently across platforms. Use icons (`search-assets`) instead
- Include reference URLs in `notes` (after `---` separator) when the slide content is based on external sources
- Do not scale font sizes based on slide dimensions because PowerPoint font size (pt) is absolute — 20pt renders the same physical size on 1280x720 and 1920x1080. Only coordinates (x, y, width, height) change with slide size
- When placing images, maintain the original aspect ratio — run `image-size {path} --width {px}` or `--height {px}` to get the correct dimensions before writing the element. If width-based calculation exceeds the content area height, recalculate with `--height` instead
- Use `mask: "rounded_rectangle"` with `maskAdjustments: [0.03~0.05]` for screenshots because raw edges look unfinished
- When building a code block, use the `code-block` command to generate elements JSON and include it via `{"type": "include", "src": "code.json"}` because inline code properties are no longer supported

**custom template:**
- Use layout names from `analyze-template` output in the `layout` field
- When using a layout for the first time, read its detail file via `analyze-template {template} --layout {name}` to understand placeholder positions and content areas because coordinates differ per layout
- When a layout has a `sample` field in its detail, reference the sample's elements (font sizes, colors, shapes, spacing) to match the template's design language
- When a layout defines content areas via placeholders (OBJECT, BODY, PICTURE), place elements approximately within those areas as a guide — exact alignment is not required

---

## Next Step

Once all slides are composed, read `create-new-3-review` and proceed to Phase 3.
Do NOT ask the user for confirmation — continue non-stop.
The user is away once Phase 2 starts. Stopping to ask breaks the flow and delays completion.
