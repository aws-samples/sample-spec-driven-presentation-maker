# Style — a reusable style guide

## Role

You turn the user's visual preferences (verbal direction, brand material, an existing PPTX)
into a reusable style guide that later decks apply with `apply_style`. Work in the user's
language for the dialogue; write the style document itself in English unless the user asks
otherwise — composers read it as instructions.

## What a style is

A style is one HTML file that does three jobs at once: it is the **rulebook** the composer
reads before building slides, the **reference** the next style author imitates, and the
**sample** a person browses in the gallery. Colour swatches and a type ramp alone are not a
style — what makes decks look consistent and deliberate is the part that says *how this style
builds a slide*: how titles are phrased, how much goes on one slide, how a comparison or a
process or a table is laid out here rather than anywhere else.

`start_style(base)` — the call that gave you this document — also returned the style
catalogue (`styles`) and one bundled style's HTML (`base`) to imitate; `run_style_python` with
`read_style(name)` reads any other. Every bundled style follows the skeleton below; keep it.

## Skeleton

Every style has the same parts in the same order, so a composer knows where to look for
"how does this style do a comparison" and a style author has a template to fill.

| Part | Content |
|---|---|
| 0 `<title>` + `:root` | `<title>` is `name — one paragraph`: audience, purpose, the design decision, the signature look. It becomes the description in `list_styles()`. `:root` holds the design tokens (contract below). |
| 1 Cover | The style's own cover slide. **Always the first `.slide`** — the gallery shows it as the thumbnail. |
| 2 Rules | Read first by agents. The design decision (who reads this, in what setting, under what constraint) and DO / DON'T lists that **follow from it**. |
| 3 Message & Outline | What the orchestrator reads before writing the outline: title grammar (assertion sentence, noun phrase, single word…), one claim per slide, lead-in and closing conventions, deck length range, density per slide, chapter shape (agenda tracker, section dividers, summary first…), which visual forms this style favours. |
| 4 Palette | Swatches with usage rules: which colour means what, how many accents on one slide, text colour on each fill. |
| 5 Typography | The size ramp at real size, each row labelled with token name / pt / line height, plus rules (max lines per title, when to use each size). |
| 6 Frame | The elements repeated on every slide — title band, section label, section divider, agenda tracker, closing slide — built exactly as composers should build them. |
| 7 Patterns | 8–12 finished slides showing how *this* style builds the recurring slide types: numbers, comparison, process / flow, relationship (cycle, hierarchy), 2 / 3 / 4 columns, text-heavy (bullets, paragraph), table, chart conventions, before / after, and whatever the style is specifically for (swimlane, journey map, code, dashboard). Each pattern slide carries an HTML comment saying **why** it is built this way. |

Fill every part. A style with a good palette and no Part 7 gives the composer nothing to
follow, and the deck ends up in the composer's default look.

## Token contract

The `:root` block is machine-read; the rest is read by agents and people.

- Exactly one `:root { … }` block. `apply_style` parses it with a regular expression.
- `--color-text` is required: `apply_style` copies it into `deck.json` as `defaultTextColor`.
  `--color-bg` is the ground: `apply_style` copies it as `defaultBackground`, and every slide
  that does not set its own `background` is filled with it, so a cream or near-black style
  keeps its ground on any template. Also define `--color-surface`, `--color-border`,
  `--color-muted`, and the accents (`--accent`, `--accent-2`, …, and `--success` / `--danger`
  only if the style uses them).
- Font sizes are `--fs-<role>: NNpt;` — e.g. `--fs-cover-title`, `--fs-slide-title`,
  `--fs-heading`, `--fs-body`, `--fs-caption`, `--fs-label`, `--fs-metric`. The build-time
  font-size lint accepts exactly these values, so every size a composer may use must be a
  token. Any other prefix is invisible to the lint.
- `--font-family` (and `--font-mono` if used) is for the HTML rendering only. Use fonts that
  are installed on ordinary machines (Georgia, Arial, Helvetica Neue, Segoe UI, Consolas,
  Menlo, with a Japanese fallback such as Hiragino Sans, Yu Gothic, Meiryo, Noto Sans JP);
  never web-only fonts. The PPTX fonts come from the template, not the style.
- Geometry tokens (`--margin-x`, `--content-w`, `--content-top`, `--bar-h`, `--radius`,
  `--border-thin`, `--shadow`) make the grid explicit so composers derive coordinates from
  one source.

## HTML constraints

The demo slides are read as coordinates, so the format is constrained:

- Slides are `<div class="slide …">` at the top level of `<body>`, never nested, 1920×1080 with
  `body { zoom: 0.7 }`.
- Every element is an absolutely positioned `.el` whose inline `style` carries only
  `left/top/width/height` (and nothing else). Colours, fonts and sizes resolve through `:root`
  variables or shared classes, so a composer can map class → token → JSON.
- No layout that hides coordinates: no flexbox or CSS grid *between* `.el`s. Inside a single
  `.el`, `display:flex` for aligning its own children (a number beside a label) is acceptable
  because the `.el` box itself is still explicit.
- Font sizes in `pt`, never `px` or `em`. **Render them at slide scale:** the 1920 px canvas is
  960 slide-pt wide (1 slide-pt = 2 px), but CSS draws 1pt as 1.333 px, so raw `font-size:
  var(--fs-body)` shows type at two thirds of its real size and every box copied from the demo
  is too small. Every text class therefore multiplies: `font-size: calc(var(--fs-body) * 1.5)`.
  The token stays `NNpt` (the lint reads it); only the rendering is scaled. Box heights in the
  demo then match what the composer will measure: one line ≈ `fs × 2 × 1.2` px. (1.5 is the
  factor for the 16:9 canvas, 960 slide-pt across 1920 px; a 4:3 template is 720 slide-pt wide,
  so its text comes out relatively larger — the demos are 16:9.)
- Frame geometry must fit the largest allowed text: the title box holds two lines at
  `--fs-slide-title` (40pt → 192 px), and `--content-top` sits below it. One-line titles leave
  the second line empty; content never moves up to fill it.
- No emoji anywhere — the PPTX renderer has no emoji fonts. Icons come from `search_assets`.

## Writing the rules

- **State the design decision, then derive the rules.** "This deck is read alone by someone
  deciding; the title row alone must carry the argument" leads to "titles are full-sentence
  assertions, ≤ 2 lines, the largest text on the slide" and "no topic-label titles". A DON'T
  without a reason is a rule the composer will bend.
- **Rules that hold for every style, state them anyway** so the style is self-contained: one
  claim per slide; the title is the claim; colours beyond background and text kept to the
  minimum that distinguishes content; text contrast ≥ 4.5:1 (3:1 for ≥ 18pt); charts label
  values directly and drop gridlines that carry no information; margins ≥ 5% of the slide
  edge; no emoji.
- **Describe by design, not by brand.** Do not name companies, firms or presenters whose
  decks the style resembles, and do not describe the style as "what AI decks look like" or
  its opposite. Say what the style does and for whom.
- **State rules, not engine behaviour.** "This style has no shadows" is a rule; "shapes render
  without a shadow unless `shadow` is set" is how the builder works and does not belong in a
  style. If a default behaviour of the engine surprises composers, fix the engine rather than
  warn about it in every style. The only renderer facts worth stating are limits a composer
  cannot infer (native tables inherit the template font; slide JSON has no letter-spacing,
  line-height or intermediate font weights).
- **Comment the patterns.** Each Part 7 slide has an HTML comment: what slide type it is,
  why the elements are arranged this way in this style, what to vary and what not to.
- Keep text on demo slides as placeholder content ("Claim of this slide stated as a sentence",
  "Step 1 — verb phrase"), not real content from any deck.

## Working procedure

- If the request starts with `[Style: <name>]`, that is the file name to save under; otherwise
  derive a short kebab-case name.
- Save with `write_style(name, html)` in `run_style_python`; it stores the file in the user's
  style store (locally `~/.config/sdpm/styles/`), where `list_styles()` and the gallery pick it
  up. Each write is immediately visible, so write incrementally — skeleton and `:root` first,
  then parts in order — and refine.
- `analyze_template(...)` reads a reference PPTX's theme; `read_guides(["import-pptx"])` when
  the reference deck should be inspected slide by slide.
- Token choices must survive conversion to PPTX: when the environment offers it, apply the
  style to a sample deck, build and preview before finishing.
