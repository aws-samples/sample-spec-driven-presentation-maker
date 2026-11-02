# Diagram sources

Each directory here is a one-slide sdpm deck that draws one diagram in `docs/assets/`.
`render.py` builds the deck with this repository's own CLI and writes the PNG.

| Directory | Output | Used by |
|---|---|---|
| `workflow/` | `workflow-en.png`, `workflow-ja.png` | `README.md`, `README_ja.md` |
| `4layer-architecture/` | `4layer-architecture-en.png` | `docs/en/architecture.md` |
| `dependency-direction/` | `dependency-direction-en.png` | `docs/en/architecture.md` |
| `data-flow/` | `data-flow-en.png` | `docs/en/architecture.md` |
| `cdk-dependencies/` | `cdk-dependencies.png` | `docs/en/architecture.md` |
| `style-gallery/` | `style-gallery-en.png` | `README.md`, `README_ja.md` |

`jwt-auth-flow-en.png` / `jwt-auth-flow-ja.png` have no source here. They still match the code
and were not redrawn.

## Regenerate

From the repository root:

```bash
uv run python docs/assets/src/render.py                # every diagram
uv run python docs/assets/src/render.py workflow       # one or more by name
uv run python docs/assets/src/render.py workflow --keep-pptx /tmp   # also keep the .pptx
```

Requirements: LibreOffice (`soffice`) and poppler (`pdftoppm`), the same tools the slide
previews use, plus the fonts named in `strings.<lang>.json` (`_fonts`): Arial for English,
Hiragino Sans for Japanese (macOS). With other fonts the text wraps differently, so check the
result.

## How a diagram is built

- `deck.json` and `specs/outline.md` make the directory a deck (template `blank-light`).
- `slides/<name>.json` holds the shapes, lines and icons with hand-placed coordinates on the
  1920 × 1080 canvas. All visible text is a `{{key}}` placeholder.
- `strings.<lang>.json` gives the text for each key. `_fonts` replaces the deck fonts for that
  language.
- `out.json` maps each language to its output PNG.

`render.py` copies the deck to a temporary directory, fills in the strings, runs
`pptx_builder.py generate_pptx`, exports a PDF through LibreOffice, rasterises it at 1920 px
with `pdftoppm` and trims the white margin to 24 px.

To add a language, add `strings.<lang>.json` and a line in `out.json`. To change a diagram,
edit `slides/<name>.json` (geometry) or the strings (wording), render, and look at the PNG.

## Style gallery

`style-gallery/` is a gallery, not a diagram: `gallery.json` lists full slides taken from
decks under this directory, and `render.py` lays them out in rows with the style name under
each one. It shows slide 3 of the key visual deck (`hero/deck-en`, style `agent-spectrum`)
next to the same slide in six bundled styles. Each of `style-gallery/<style>/` is a one-slide
sdpm deck made with the local MCP server: `apply_style` with that style (`blank-dark` for
`aws-dark` and `duotone`, `blank-light` for the rest), the font of the style in
`deck.json`, then a composer wrote `slides/spec-first.json` from the style's process and
column patterns with the hero slide's wording. `specs/art-direction.html` is the bundled
style as `apply_style` copied it.

`render.py` builds each tile's deck with only that slide in the outline, scales the 1920 px
render to `tile_width` and centres a short last row. The labels use Menlo (macOS) or another
monospace font found on the machine. The 16 pt rule below does not apply: the gallery shows
how each style looks, and the full slides are one click away.

## Checks before committing a diagram

- No text is clipped or runs outside its box, and no boxes overlap.
- Every arrow starts and ends on the box it connects.
- Body text is at least 16 pt in the slide. The README shows the image about 880 px wide, so
  16 pt is about 14.7 px on screen.
- Each PNG stays under 300 KB.

The step names, file names and tool names in the diagrams come from the role documents
(`sdpm/references/workflows/`), `sdpm/sdpm/entry.py`, `sdpm/sdpm/tools/` and
`infra/bin/infra.ts`. Check them against those files when the workflow or the stacks change.

## Why hand-placed slides

The `arch_diagram` layout engine draws icon labels at 11 pt and arrow labels at 9 pt, sized
for a full-screen slide. At README width that text is too small to read, so these diagrams
place their shapes by hand.

## Key visual

`hero/` holds the deck at the top of the README (`deck-en/`, and `deck-ja/` made from it with
the translate role) with its compose history, and the scripts that turn it into
`hero-en.gif` / `hero-ja.gif` and the stills `hero-slides-en.png` / `hero-slides-ja.png`:
`replay.py` places the history again, step by step, in a scratch deck folder that the Local
Web UI shows, and `record.cjs` records the browser with Playwright. The docstring of
`replay.py` describes the two parts of the GIF and the requirements.

```bash
uv run python docs/assets/src/hero/replay.py               # en and ja, GIFs and stills
uv run python docs/assets/src/hero/replay.py ja --no-stills
```

## Screenshots

`docs/assets/screenshots/` is not generated here. Those images are captures of a running Web
UI and of real decks:

- `example-html.png`: three slides of an HTML deck made in the Local Web UI on the Fast path
  with **Build as HTML** (prompt: a 5-slide sourdough introduction with an interactive
  temperature chart, `@style:prism-light`), from the deck's browser-check PNGs.
- `webui-comments.png`, `webui-deck.png`: Playwright captures of the Local Web UI at 1600 px
  wide, English locale, on a copy of `hero/deck-en` (with `preview/` and `output.pptx` built
  from it) in a scratch deck folder and config directory. The comment frames were drawn with
  the **Comment** tool; the change request in `webui-deck.png` was sent to a real agent, which
  had a composer update the slide.
- `webui-styles.png`: the Styles page of the same Web UI, 1280 px wide, cropped to the page
  content.

To retake them, run the Local Web UI from a checkout (`cd web-ui && npm run dev:local`) with
`SDPM_DECK_ROOT` and `XDG_CONFIG_HOME` pointing at scratch directories, and use generic topics.
The key visual deck uses Avenir Next and Menlo (macOS), so take the Web UI captures on macOS.
The HTML deck's slides use Calibri. On a machine without it the browser falls back to a wider
font and long titles overflow, so that capture loaded LibreOffice's metric-compatible Carlito
under the name Calibri, as LibreOffice does for the PNG previews.
