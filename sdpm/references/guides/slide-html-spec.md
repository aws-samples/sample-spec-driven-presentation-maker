---
name: slide-html-spec
description: "Slide HTML format — slides/<slug>.html sections, data-ph / data-region, fragments, auto-animate, what is forbidden"
category: guide
---

# Slide HTML Reference

An HTML deck (`deck.json` `"outputFormat": "html"`) is the same deck directory as a PPTX
deck — `deck.json`, `specs/`, the template and the style — with slides written as HTML.
`run_python` assembles every slide into one self-contained `output.html` (reveal.js, offline)
after each change and returns the static checks as warnings.

```
<deck>/
├─ deck.json            template, defaultBackground, outputFormat "html"
├─ deck.css             shared component classes (written by the layout pass)
├─ specs/               brief.md, art-direction.html, outline.md
├─ slides/<slug>.html   one <section> per file
└─ output.html          generated — open it in a browser
```

## File contract

Each `slides/<slug>.html` holds exactly one `<section>`, with `data-layout` naming a layout
of the template:

```html
<section data-layout="Title Only" data-auto-animate>
  <h1 data-ph="title">Claim headline</h1>
  <div data-region="body" style="position:absolute;left:96px;top:210px;width:1728px;height:640px"> … </div>
  <aside class="notes">Speaker notes</aside>
</section>
```

- `data-layout` is required; a name not in `template_html` is reported (`layout-unknown`).
- No nested `<section>` (vertical slides are not supported), no `data-slug` (the assembler
  sets it).
- Slide order comes from `specs/outline.md`; a slug without a file is skipped with a warning.

## Canvas

The section is the template's slide size in px (`template_html.slideSize.width` × `height`,
1920 × 1080 for a 16:9 template). Children may be absolutely positioned in those px
(`data-ph` elements are positioned by the template and `data-region` boxes are absolute by
default; give every other positioned element `position:absolute` yourself); flex and grid are fine. The template ground and the decoration artwork are the
section background — draw on top of them, not over them.

## `template_html`

`start_composing(..., mode="html")` returns the template's description:

| Field | Meaning |
|---|---|
| `slideSize` | `{width, height, ptPerPx}` — canvas px and points per px |
| `ptScale` | `0.75 / ptPerPx` — the value of `--sdpm-pt-scale` |
| `fonts` | `{major, minor, halfwidth, fullwidth}` — the template's fonts |
| `themeColors` | `text`, `background`, `text2`, `background2`, `accent1`…`accent6` (hex) |
| `ground` | master background colour, or null |
| `layouts[]` | one entry per layout, in template order |
| `layouts[].name` | the `data-layout` value |
| `layouts[].curated`, `notes` | whether the template recommends the layout, and its usage note |
| `layouts[].placeholders[]` | `{key, type, bbox{x,y,w,h}, text, aliases?, prompt?}` — `key` is the `data-ph` value; `aliases` adds `title` / `subtitle`; `text` is the resolved text style (anchor, insets, per-level size / colour / font / bullets) |
| `layouts[].chrome` | `slideNumber` / `footer` boxes the deck draws (see Chrome) |
| `layouts[].decorations[]` | `{name, source, bbox, kind}` — what the template draws; `kind` is `ground` (covers most of the canvas), `band` (contains a placeholder, e.g. a title band) or `obstacle` (logo, copyright, mark) |
| `layouts[].ground` | `{kind: "solid", color}` or `{kind: "baked"}` (picture / gradient ground) |

Keep content clear of `band` and `obstacle` boxes, and never redraw them.

## Placeholders — `data-ph`

`data-ph="<key>"` puts an element where the layout's placeholder is and styles it like the
template (font, size, colour, alignment, bullets per list level). `title` and `subtitle`
work as aliases. The placeholder element's own properties (position, size, padding, font,
colour, alignment) can be overridden with an inline `style`, a slide `<style>` rule or a
`deck.css` class. For its paragraphs and list items (margins, bullets, per-level sizes and
colours), use a slide `<style>` rule that names the placeholder, e.g.
`[data-ph="body"] li { … }`: the template's own rules for them are more specific than a
single class.
A placeholder is optional: leave it out and nothing is drawn there.

## Regions — `data-region`

`data-region="<name>"` marks a content area the layout pass decided: an empty box with
absolute px (`left`, `top`, `width`, `height` in its `style`; the deck makes it `position:absolute`).
Content composers fill it and
keep its coordinates; the name is a short identifier (`body`, `step-1`, `media`).

## Styles

- **Slide `<style>`** — any number inside the section. Rules are nested under that slide
  automatically (`section[data-slug="<slug>"] { … }`), so plain selectors are local to it;
  `&` is the section itself (`&{…}`, `&.dark{…}` — a plain `section{…}` matches nothing).
  `@keyframes`, `@font-face` and `@property` are moved out of the nesting and stay global;
  keyframes are renamed per slide (`sdpm-<slug>-<name>`) together with the `animation` /
  `animation-name` values of that slide, so two slides may both use `pulse`.
  No `:root` block (`root-in-slide-style`): tokens come from the style.
- **Inline `style`** — fine for positions and one-off tweaks.
- **Font sizes** — only `font-size: calc(var(--fs-x) * var(--sdpm-pt-scale))` (also in the
  `font:` shorthand), with an `--fs-*` token defined in `specs/art-direction.html`. The
  tokens are points; `--sdpm-pt-scale` (`0.75 / ptPerPx`, 1.5 for a 13.33 in 16:9 template,
  2.0 for 4:3) turns them into canvas px, so one token gives the same printed size on any
  template. Raw px / pt / em sizes are warned (`font-size-token`).
- **Colours** — the style's `:root` colour tokens (`var(--color-…)`); the template's are
  `var(--sdpm-theme-<role>)`.
- **Fonts** — the style's `--font-family` wins; the template's fonts are the fallback.

## `deck.css`

`<deck>/deck.css`, next to `deck.json`, holds what the whole deck shares: the component
classes the style's `Component:` and `Pattern:` parts define (card, takeaway, table, step…),
sized with `--fs-*` tokens and coloured from `:root` tokens.

- Only the layout-pass composer writes it, together with the slide frames. Content
  composers use its classes and never edit it; a missing shared component is reported to the
  orchestrator.
- What belongs there: classes used on more than one slide. What does not: a tweak for one
  slide — that goes in the slide's `<style>`.
- No `:root` block (`root-in-deck-css`); the same font-size and forbidden-construct checks
  as slides apply.
- It is embedded once in `output.html`, unscoped, after the style and the template CSS and
  before the slide styles. A change re-renders every slide.

## Progressive builds

- **Fragments** — within one slide: `class="fragment"` reveals the element on the next step;
  add an effect class (`fade-up`, `fade-in-then-out`, `semi-fade-out`, `grow`,
  `highlight-current-blue`…) and `data-fragment-index="N"` to order or group steps.
- **Auto-animate** — across a prefix group (`demo-1`, `demo-2`): put `data-auto-animate` on
  both sections and the same `data-id` on each element that carries over; reveal.js moves and
  resizes it between the slides. Each slide of the group is complete on its own (no
  `override`, no `includes/`).

## Notes

`<aside class="notes">…</aside>` inside the section. Press `S` in `output.html` for the
speaker view.

## Icons and images

- Icons: `search_assets` → `<img src="assets:<source>/<name>">`. SVG icons are inlined;
  `alt` becomes the accessible label.
- Images: paths relative to the deck root (`images/photo.png`, not relative to `slides/`) or
  `attachments/…`; they are embedded as data URIs wherever they load something: `src`,
  `srcset`, `poster`, SVG `<image href>`, and CSS `url(…)` / `image-set("…")`. A deck SVG
  file (`images/chart.svg`) stays an image: it is embedded as a data URI, never inlined, so
  scripts or links inside it do nothing. To style or animate an SVG, write the `<svg>` in the
  slide.
- `<link rel=stylesheet>` and `@import` are not embedded (`external-url`): shared rules go in
  `deck.css`, one-slide rules in the slide's `<style>`.
- No external URLs in any of those positions. Links (`<a href="https://…">`) are allowed.
- Everything ends up in one file: an embedded file over 5 MB and an `output.html` over 25 MB
  are warned. Compress or shrink large images.

## Chrome — page numbers and footers

The deck draws the slide number (and a footer when the template has literal footer text) on
every slide whose layout has `chrome` boxes, marked `data-sdpm-chrome`. Never draw them
yourself: no `<footer>`, no `data-ph` for date / footer / slide-number placeholders, no
`page-number` / `slide-number` / `footer` classes or ids (`card-footer` is fine).

## Not allowed

`<script>`, `on*` event handlers, `javascript:` URLs, `<iframe>` / `<object>` / `<embed>`,
external URLs, `data-background-*` (the ground comes from the template and
`defaultBackground`). Inline `<svg>` follows the same rules, `<foreignObject>` content included.

## Static checks

`run_python` reports, per slug (`deck.css` first):

| Rule | Meaning |
|---|---|
| `structure` | not exactly one `<section>`, nested sections, or unparsable HTML — the slide is skipped |
| `layout-missing` | the section has no `data-layout` |
| `layout-unknown` | `data-layout` is not a layout of the template |
| `script` | `<script>`, an `on*` handler, `javascript:` (also in an SVG animation `values` list), `expression()`, or `<iframe>` / `<object>` / `<embed>` |
| `external-url` | a non-local URL in `src` / `srcset` / `poster` / `data` / `href` (not `<a>`) / `url()` (also in SVG attributes such as `fill`) / `image-set()` / `@import`; any `@import` or `<link rel=stylesheet>` (not embedded, and the deck blocks linked stylesheets, `data:` ones too) |
| `external-use` | `<use href>` that is not a `#id` in the same slide (another file's sprite does not load): inline the SVG |
| `data-background` | a `data-background-*` attribute |
| `self-chrome` | a hand-drawn page number or footer |
| `root-in-slide-style` | a `:root` block in a slide `<style>` |
| `root-in-deck-css` | a `:root` block in `deck.css` |
| `data-slug` | `data-slug` set by hand |
| `font-size-token` | a font size that is not `calc(var(--fs-x) * var(--sdpm-pt-scale))` |
| `font-size-unknown-token` | an `--fs-*` token the style does not define |

The checks need no browser. Overflow and overlap are not measured: look at the slides.

## Viewing

Open `<deck>/output.html` in a browser. Arrow keys step through slides and fragments, `S`
opens the speaker view, and `output.html?print-pdf` prints to PDF from the browser.
