---
name: slide-html-spec
description: "Slide HTML format — slides/<slug>.html sections, data-ph / data-region, fragments, auto-animate, slide scripts with the bundled ECharts / D3, what is forbidden"
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

## Scripts

Write plain code in an inline `<script>` inside the section. The deck wraps it in a function
and runs it once per section element, the first time the slide is shown — also in the
overview, in the speaker view's frames and on every printed page. `section` (and `this`) is
the slide's element; variables stay local to the slide.

**Libraries.** Declare them on the section: `<section data-layout="…" data-libs="echarts d3">`.
Known values: `echarts` (Apache ECharts 6.1.0, global `echarts`) and `d3` (D3 7.9.0, global
`d3`). A deck embeds a library only when a slide declares it: ECharts adds about 1.1 MB,
D3 about 280 KB. Declare it on every slide that uses it, even when another slide already does.

**Rules.**
- Find elements with `section.querySelector(…)`, never by `id` / `document.getElementById`:
  the print view clones a slide once per fragment step, so ids repeat and the script runs
  once per clone.
- Do not wait for `DOMContentLoaded` or `load`: they have fired before the code runs.
- Turn animation off when `Reveal.isPrintView()` is true, or the PDF catches it halfway.
- For something that repeats on every visit, listen yourself:
  `Reveal.on('slidechanged', function (e) { if (e.currentSlide === section) … })`.
- Listen with `addEventListener`; `on*` attributes do not run.
- Size the draw target with its region's px box (`width` / `height` in the style); a chart
  takes the size of the element it is drawn into.
- Colours: `getComputedStyle(section).getPropertyValue('--color-…').trim()` (the style's
  tokens, or `--sdpm-theme-<role>`). Text sizes: `parseFloat(getComputedStyle(el).fontSize)`
  of an element styled with a `--fs-*` token — never a px number of your own.
- ECharts: `renderer: 'svg'` prints sharp in the PDF; the default canvas becomes a bitmap.
- D3: `d3.csvParse`, `tsvParse` and `dsvFormat(…).parse` need eval and fail in the deck. Use
  `d3.csvParseRows` or inline arrays.

**No network, no navigation.** `fetch`, XHR and external images are blocked by the deck's
CSP: put the data in the script. The CSP cannot stop navigation, so `location`,
`window.open`, `top.` and external URLs are warned (`script-external`) even in comments and
strings; SVG namespace URIs (`http://www.w3.org/2000/svg` …) are fine. `<script src>` and
`type="module"` do not run.

**Thumbnails run no script.** `preview/<slug>.html` shows a JS slide's HTML — title, frame,
labels — with empty draw targets. Keep the title and the frame in HTML, not in the script.

ECharts bar chart (svg renderer, colours and text size from tokens, no animation in print):

```html
<section data-layout="Title Only" data-libs="echarts">
  <h1 data-ph="title">Revenue doubled in two years</h1>
  <div data-region="body" class="chart" style="position:absolute;left:96px;top:210px;width:1728px;height:600px"></div>
  <p class="label" style="position:absolute;left:96px;top:830px;font-size:calc(var(--fs-caption) * var(--sdpm-pt-scale))">Revenue, $M</p>
  <script>
    var css = getComputedStyle(section);
    var token = function (name) { return css.getPropertyValue(name).trim(); };
    var size = parseFloat(getComputedStyle(section.querySelector('.label')).fontSize);
    var chart = echarts.init(section.querySelector('.chart'), null, { renderer: 'svg' });
    chart.setOption({
      animation: !Reveal.isPrintView(),
      textStyle: { color: token('--color-text'), fontSize: size },
      xAxis: { type: 'category', data: ['2024', '2025', '2026'] },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: token('--color-border') } } },
      series: [{ type: 'bar', data: [120, 180, 260], itemStyle: { color: token('--sdpm-theme-accent1') } }]
    });
  </script>
</section>
```

D3 chart drawn into an SVG inside a region (data from `csvParseRows`):

```html
<section data-layout="Title Only" data-libs="d3">
  <h1 data-ph="title">Three regions carry the growth</h1>
  <div data-region="body" style="position:absolute;left:96px;top:210px;width:1728px;height:640px">
    <svg class="plot" width="1728" height="640"></svg>
  </div>
  <script>
    var rows = d3.csvParseRows('North,260\nWest,180\nSouth,120', function (r) { return [r[0], +r[1]]; });
    var color = getComputedStyle(section).getPropertyValue('--sdpm-theme-accent1').trim();
    var x = d3.scaleLinear().domain([0, d3.max(rows, function (r) { return r[1]; })]).range([0, 1400]);
    var y = d3.scaleBand().domain(rows.map(function (r) { return r[0]; })).range([0, 640]).padding(0.3);
    var bars = d3.select(section.querySelector('.plot')).selectAll('rect').data(rows).join('rect')
      .attr('x', 300).attr('y', function (r) { return y(r[0]); })
      .attr('height', y.bandwidth()).attr('fill', color);
    var width = function (r) { return x(r[1]); };
    if (Reveal.isPrintView()) bars.attr('width', width);
    else bars.attr('width', 0).transition().duration(600).attr('width', width);
  </script>
</section>
```

Click interaction (a button toggles a class; no `onclick`). The state before any click is
what prints:

```html
<section data-layout="Title Only">
  <h1 data-ph="title">Same service, two cost models</h1>
  <div data-region="body" style="position:absolute;left:96px;top:210px;width:1728px;height:640px">
    <button class="toggle" type="button">Show the cost view</button>
    <div class="panel">…</div>
  </div>
  <style>.panel{opacity:0;transition:opacity .3s} &.cost .panel{opacity:1}</style>
  <script>
    section.querySelector('.toggle').addEventListener('click', function () {
      section.classList.toggle('cost');
    });
  </script>
</section>
```

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
- No external URLs in any of those positions. Links (`<a href="https://…">`) are allowed; the
  engine opens them in a new tab (`target="_blank" rel="noopener noreferrer"`).
- Everything ends up in one file: an embedded file over 5 MB and an `output.html` over 25 MB
  are warned. Compress or shrink large images.

## Chrome — page numbers and footers

The deck draws the slide number (and a footer when the template has literal footer text) on
every slide whose layout has `chrome` boxes, marked `data-sdpm-chrome`. Never draw them
yourself: no `<footer>`, no `data-ph` for date / footer / slide-number placeholders, no
`page-number` / `slide-number` / `footer` classes or ids (`card-footer` is fine).

## Not allowed

`<script src>`, module and other non-classic scripts, code that needs eval (`eval`,
`new Function`, D3's `csvParse`), `on*` event handlers, `javascript:` URLs,
`<iframe>` / `<object>` / `<embed>`, external URLs, `data-background-*` (the ground comes
from the template and `defaultBackground`). Inline `<svg>` follows the same rules,
`<foreignObject>` content included.

## Static checks

`run_python` reports, per slug (`deck.css` first):

| Rule | Meaning |
|---|---|
| `structure` | not exactly one `<section>`, nested sections, or unparsable HTML — the slide is skipped |
| `layout-missing` | the section has no `data-layout` |
| `layout-unknown` | `data-layout` is not a layout of the template |
| `script` | `<script src>` or a non-classic `<script type>` (module, JSON…; inline classic scripts run), an `on*` handler, `javascript:` (also in an SVG animation `values` list), `expression()`, `<iframe>` / `<object>` / `<embed>`, or `<meta http-equiv>` (a `refresh` navigates the deck away) |
| `external-url` | a non-local URL in `src` / `srcset` / `poster` / `data` / `href` (not `<a>`) / `url()` (also in SVG attributes such as `fill`) / `image-set()` / `@import`; any `@import` or `<link rel=stylesheet>` (not embedded, and the deck blocks linked stylesheets, `data:` ones too) |
| `external-use` | `<use href>` that is not a `#id` in the same slide (another file's sprite does not load): inline the SVG |
| `data-background` | a `data-background-*` attribute |
| `self-chrome` | a hand-drawn page number or footer |
| `placeholder-unknown` | a `data-ph` key (idx or alias) that the slide's layout does not have (not checked for unknown layouts, chrome and `self-chrome` keys) |
| `root-in-slide-style` | a `:root` block in a slide `<style>` |
| `root-in-deck-css` | a `:root` block in `deck.css` |
| `data-slug` | `data-slug` set by hand |
| `font-size-token` | a font size that is not `calc(var(--fs-x) * var(--sdpm-pt-scale))` |
| `font-size-unknown-token` | an `--fs-*` token the style does not define |
| `script-external` | a slide script uses `location`, `window.open` / `open(`, `top.` or an external URL (`http(s)://` other than an SVG / XML namespace URI, `"//host`), comments and strings included |
| `library-unknown` | a `data-libs` value that is not a bundled library (`echarts`, `d3`) |
| `library-undeclared` | a slide script uses `echarts.` / `d3.` while its section's `data-libs` does not name it |
| `script-eval` | a slide script calls something that needs eval: `d3.csvParse`, `tsvParse`, `dsvFormat(…).parse`, `eval`, `new Function` |
| `script-dom` | a slide script uses `getElementById` / `querySelector('#…')` or waits for `DOMContentLoaded` / `load` |

## Browser check

After each `run_python` that writes or changes slides, those slides (and the
`measure_slides` you name) are opened in a headless browser — Chrome or Edge locally, AWS
AgentCore Browser in the cloud — with networking off. Each slide is shown with every
fragment visible and its animations finished, then measured. Findings come back as warnings
`<slug>: <rule>: …`; fix them like static-check warnings. Boxes are canvas px; an
intersection counts only when both sides exceed 4 px, "inside" allows 4 px.

| Rule | Message | Meaning |
|---|---|---|
| `overlap` | `overlap: data-ph="title" × data-region="body" (W×H px)` | two top-level blocks (placeholders, regions, other elements) or two children of the same region partly overlap; one fully inside the other is fine |
| `overflow` | `overflow: … content W×H px exceeds its box W×H px` / `overflow: … extends N px past the slide's bottom edge` | content larger than its placeholder, region or region child (it scrolls or spills), or any element past the slide edge |
| `outside-region` | `outside-region: … extends N px below data-region="body"` | an element inside a region sticks out of the region's box |
| `decoration-overlap` | `decoration-overlap: … covers the template's "Logo" (obstacle) by W×H px` | an element over a template decoration of kind `band` or `obstacle` |
| `js-error` | `JS error: …` (`output.html: JS error (line N): …` when the line belongs to no slide) | an uncaught exception, a slide-helper error or a CSP violation |

More than 10 layout findings on one slide end with `… and N more`. Not judged: the template
ground (decorations of kind `ground`), the page number and footer the deck draws
(`data-sdpm-chrome`), speaker notes. Placeholders may sit on a `band` (it backs them).
Fonts the template names but the checking machine lacks fall back to another font, so a
line that just fits can measure differently on the presenting machine: leave a little room.

Each checked slide also gets a PNG, 1280 px on the long edge, like the PPTX previews:
`preview_files` in the `run_python` result locally, `get_preview` in the cloud. A slide that
ignores the `Reveal.isPrintView()` rule (Scripts) is captured mid-animation, as in the PDF.

When the check does not run or does not finish, the build still succeeds and one warning
says so: `output.html: Browser check skipped: …` (no Chrome or Edge found, or
`SDPM_BROWSER=none`), `Browser check stopped: …` (a slide script navigated the page away),
`Browser check did not finish within N s; …` (a script that never returns) or
`Browser check could not run (…): …`. Layout, JS errors and PNGs of the unchecked slides
are then unknown, not clean.

## Viewing

Open `<deck>/output.html` in a browser. Arrow keys step through slides and fragments, `S`
opens the speaker view, and `output.html?print-pdf` prints to PDF from the browser.
