---
name: slide-html-spec
description: "Slide HTML format — slides/<slug>.html sections, data-ph / data-region, tokens, deck.css, slide scripts with the bundled ECharts / D3, notes, images, chrome"
category: guide
---

# Slide HTML Reference

An HTML deck (`deck.json` `"outputFormat": "html"`) is the same deck directory as a PPTX
deck, with slides written as HTML. After each change `run_python` assembles every slide into
one self-contained `output.html` (reveal.js, offline), checks the changed slides and returns
the findings as warnings, each naming its fix.

```
<deck>/
├─ deck.json            template, defaultBackground, outputFormat "html"
├─ deck.css             shared component classes (written by the layout pass)
├─ specs/               brief.md, art-direction.html, outline.md
├─ slides/<slug>.html   one <section> per file
└─ output.html          generated — open it in a browser
```

## What a slide can use

A slide is a web page: HTML, CSS and JS within this range.

- Any layout, styling, inline SVG, CSS transitions and animations.
- Slide scripts (below) that run while presenting and respond to the presenter's clicks,
  keys, pointer and inputs, with the bundled Apache ECharts 6.1.0 and D3 7.9.0.
- Steps within a slide: `class="fragment"` reveals an element on the next step (effect
  classes such as `fade-up`; `data-fragment-index="N"` orders or groups steps).
- Motion across a prefix group (`demo-1`, `demo-2`): `data-auto-animate` on both sections and
  the same `data-id` on each element that carries over; each slide of the group is complete
  on its own.
- Everything offline: data lives in the slide's script or markup, images in the deck.
  Links (`<a href>`) open in a new tab.

## File contract

Each `slides/<slug>.html` holds exactly one `<section>`, with `data-layout` naming a layout of
the template. Slide order comes from `specs/outline.md`; the assembler sets `data-slug`.

```html
<section data-layout="Title Only" data-libs="d3">
  <h1 data-ph="title">Claim headline</h1>
  <div data-region="body" style="left:96px;top:210px;width:1728px;height:640px">
    <p class="lead" style="font-size:calc(var(--fs-body) * var(--sdpm-pt-scale))">…</p>
    <svg class="figure" width="1728" height="520"></svg>
  </div>
  <style>.lead { color: var(--color-text); }</style>
  <script>
    var accent = getComputedStyle(section).getPropertyValue('--sdpm-theme-accent1').trim();
    var figure = d3.select(section.querySelector('.figure'));
    var animate = !Reveal.isPrintView();  // the PDF and the PNG show the final state
    // draw into figure with accent; transition only when animate
  </script>
  <aside class="notes">Speaker notes</aside>
</section>
```

## Canvas

The section is the template's slide size in px (`template_html.slideSize.width` × `height`,
1920 × 1080 for a 16:9 template). `data-ph` elements are positioned by the template and
`data-region` boxes are absolute; give any other positioned element `position:absolute`
yourself. Flex and grid work inside. The template ground and decorations are the section
background.

## `template_html`

`start_composing(..., mode="html")` returns the template's description:

| Field | Meaning |
|---|---|
| `slideSize` | `{width, height, ptPerPx}` — canvas px and points per px |
| `ptScale` | `0.75 / ptPerPx` — the value of `--sdpm-pt-scale` |
| `fonts` | `{major, minor, halfwidth, fullwidth}` |
| `themeColors` | `text`, `background`, `text2`, `background2`, `accent1`…`accent6` (hex) |
| `ground` | master background colour, or null |
| `layouts[].name` | the `data-layout` value (template order) |
| `layouts[].curated`, `notes` | whether the template recommends the layout, and its usage note |
| `layouts[].placeholders[]` | `{key, type, bbox{x,y,w,h}, text, aliases?, prompt?}` — `key` is the `data-ph` value; `aliases` adds `title` / `subtitle`; `text` is the resolved text style |
| `layouts[].chrome` | `slideNumber` / `footer` boxes the deck draws (see Chrome) |
| `layouts[].decorations[]` | `{name, source, bbox, kind}` — `ground` (covers most of the canvas), `band` (backs a placeholder, e.g. a title band) or `obstacle` (logo, copyright, mark) |
| `layouts[].ground` | `{kind: "solid", color}` or `{kind: "baked"}` (picture / gradient ground) |

## Placeholders — `data-ph`

`data-ph="<key>"` puts an element where the layout's placeholder is and styles it like the
template (font, size, colour, alignment, bullets per list level); `title` and `subtitle` work
as aliases. Override the element's own properties with an inline `style`, a slide `<style>`
rule or a `deck.css` class. For its paragraphs and list items, use a slide `<style>` rule that
names the placeholder, `[data-ph="body"] li { … }`, which outranks the template's own rules.
A placeholder left out draws nothing.

## Regions — `data-region`

`data-region="<name>"` marks a content area the layout pass decided: a box with absolute px
(`left`, `top`, `width`, `height` in its `style`) and a short identifier as its name. Content
composers fill it and keep its coordinates.

## Styles

- **Slide `<style>`** — any number inside the section, nested under that slide automatically
  (`section[data-slug="<slug>"] { … }`), so plain selectors are local to it; `&` is the
  section itself (`&{…}`, `&.dark{…}`). Keyframe names are made per slide, so two slides
  may both use `pulse`; `@font-face` and `@property` stay global.
- **Inline `style`** — positions and one-off tweaks.
- **Font sizes** — `calc(var(--fs-x) * var(--sdpm-pt-scale))` with an `--fs-*` token of
  `specs/art-direction.html`. Tokens are points; `--sdpm-pt-scale` turns them into canvas px,
  so one token prints at the same size on any template.
- **Colours** — the style's `:root` tokens (`var(--color-…)`) and the template's
  `var(--sdpm-theme-<role>)`.
- **Fonts** — the style's `--font-family`, with the template's fonts as fallback.

## `deck.css`

`<deck>/deck.css` holds what the whole deck shares: the component classes of the style's
`Component:` and `Pattern:` parts (card, takeaway, table, step…), sized with `--fs-*` tokens
and coloured from `:root` tokens. The layout pass writes it; content composers use its classes
and put one-slide rules in the slide's `<style>`. It is embedded once, unscoped, after the
style and template CSS and before the slide styles, so a change re-renders every slide.

## Scripts

An inline `<script>` inside the section. The deck wraps it in a function and runs it once per
section element, the first time the slide is shown, and also in the overview, in the speaker
view's frames and on every printed page. `section` is the slide's element;
variables stay local to the slide.

- **Libraries** — declare them on the section: `data-libs="echarts d3"` (globals `echarts`,
  `d3`). A deck embeds a library only when a slide declares it: ECharts adds about 1.1 MB,
  D3 about 280 KB.
- **Elements** — `section.querySelector(…)`; listeners with `addEventListener`.
- **Each visit** — `Reveal.on('slidechanged', function (e) { if (e.currentSlide === section) … })`
  for something that repeats whenever the slide is shown.
- **Print view** — when `Reveal.isPrintView()` is true, draw the final state without
  animation; the PDF and the PNG previews capture it. The state before any click or input is
  what prints.
- **Sizes** — size a draw target from its region's px box; a chart takes the size of the
  element it is drawn into. Text sizes: `parseFloat(getComputedStyle(el).fontSize)` of an
  element styled with a `--fs-*` token.
- **Colours** — `getComputedStyle(section).getPropertyValue('--color-…').trim()` (or
  `--sdpm-theme-<role>`).
- **ECharts** — `renderer: 'svg'` prints sharp in the PDF.
- **Thumbnails** — `preview/<slug>.html` shows a slide's HTML without running its script, so
  the title and the frame belong in the HTML.

## Icons and images

- Icons: `search_assets` → `<img src="assets:<source>/<name>">`. SVG icons are inlined; `alt`
  becomes the accessible label.
- Images: paths relative to the deck root (`images/photo.png`) or `attachments/…`, in `src`,
  `srcset`, `poster`, SVG `<image href>` and CSS `url(…)` / `image-set(…)`; each is embedded
  as a data URI. A deck SVG file stays an image; to style or animate an SVG, write the `<svg>`
  in the slide.

## Chrome — page numbers and footers

On every slide whose layout has `chrome` boxes, the deck draws the slide number (and a footer
when the template has literal footer text), marked `data-sdpm-chrome`.

## Notes and viewing

Speaker notes go in `<aside class="notes">` inside the section. Open `<deck>/output.html` in a
browser: arrow keys step through slides and fragments, `S` opens the speaker view with the
notes, and `output.html?print-pdf` prints to PDF.
