---
name: new-phase-1-art-direction
description: "Phase 1: Art direction"
category: workflow
---

# Phase 1: Art Direction

Establish a consistent design direction across all slides.
The tone decided here becomes the top-level constraint for each slide's design in Phase 2.
Never compromise on design quality, even for simple decks — maintain a quality bar ready for a Tier 1 conference stage.

**Prerequisite:** Brief and outline agreed in the previous steps.

## Deliverable

`specs/art-direction.html` (when using a style) or `specs/art-direction.md` (when not) — approved by the user.

You MUST NOT read the next workflow file until the user explicitly approves the art direction.

## Constraints

- Tone and color decisions apply to ALL slides — Phase 2's design MUST be consistent with them

---

### 0. Select style

Show available styles and ask the user to choose one — or proceed without a style.

```bash
uv run python3 scripts/pptx_builder.py examples styles
```

This opens the Style Gallery in the browser. The user picks a style or says "no style."

When a style is selected, copy it as the art direction base:
```bash
cp references/examples/styles/{name}.html specs/art-direction.html
```

Read `specs/art-direction.html` after copying — read the ENTIRE file including all `<body>` content.
Do NOT truncate at `<head>` or `:root`. The body contains slide composition examples that define
container styles, card layouts, spacing patterns, and decoration details.
Internalize the design tokens and visual language now — Phase 2 will not re-read this file.

### 1. Select and analyze template

List available templates and ask the user to select one.

```bash
uv run python3 scripts/pptx_builder.py list-templates
```

Once selected, run `analyze-template` to check available layouts, theme colors, and fonts.

```bash
uv run python3 scripts/pptx_builder.py analyze-template templates/{selected_template}.pptx
```

Update `presentation.json` with the template name and fonts from the analyze output.
When `specs/art-direction.html` exists, read `:root` CSS variables and use `--color-text` as `defaultTextColor`.
If the style HTML specifies font-family, ask the user which to use — the style's fonts or the template's fonts.
```json
{
  "template": "{selected_template}.pptx",
  "fonts": {"fullwidth": "(style or template)", "halfwidth": "(style or template)"},
  "defaultTextColor": "(use --color-text from art-direction.html :root)",
  "slides": []
}
```

Review the summary output only (layout names and placeholder types). Detailed layout info (positions, sizes, samples) is retrieved per-layout in Phase 2 via `--layout`.

### 2. Read reference materials

Run `guides` to review available guides. Read any that are relevant to this phase's work.

You MUST read the following before proposing art direction:
```bash
python scripts/pptx_builder.py guides design-rules design-vocabulary
```

### 3. Propose art direction

Art direction is a design agreement. The user sees the actual visual direction in the browser
and says "yes, this is what I want" or "change this." That's it.

**When art-direction.html already exists** (style selected in Step 0):
The user has already seen this style in the Style Gallery.
Present the style name and key design tokens (colors, fonts, decoration level) as text.
Ask: "This is the design direction. Does this work as-is, or do you want to adjust anything?"

If the user is happy, it's done — no need to open the browser.
If they want changes, modify the HTML, then open `specs/art-direction.html` in the browser
so they can verify the edits visually.

**When no style was selected** (art-direction.html does not exist):
Write `specs/art-direction.md` — design direction in prose. Cover color, decoration,
density, and impression. This is a human-readable agreement, not a machine-readable spec.

Also confirm:
- **Source materials** — When image assets are provided, read each one with fs_read Image mode to understand the content and determine placement across slides.

#### Constraints
- You MUST propose an art direction based on Phase 1 context, not ask the user to choose from abstract options
- You MUST use analyze-template color output to determine color scheme for the chosen template
- Text color, table color, chart color, etc. are auto-resolved from the template's theme colors

When art-direction.html was edited, have the user review it in a browser and confirm agreement.
When it was copied from a style without changes, text confirmation is sufficient.

### 4. Review outline fit

After art direction is confirmed, check whether the outline still fits the design direction.
Information density may require splitting dense slides or merging thin ones.

Do NOT ask "shall we review the outline?" every time — that becomes ritual.
Instead, read the outline against the confirmed direction and propose specific changes
if needed (e.g., "Slide 4 has too much content — split into overview + detail").
If the outline fits, say so briefly and move on.

### Scope of art direction

Art direction defines the visual style layer only — colors, typography, spacing, decoration.
It does NOT define slide composition. How elements are arranged (patterns) and how each element
is built (components) are decided per-slide in Phase 2. Art direction constrains the palette;
it does not constrain the structure.

---

## Next Step

Once the user explicitly approves the art direction, proceed to Phase 2 (`create-new-2-compose`).
Do not proceed without approval.
