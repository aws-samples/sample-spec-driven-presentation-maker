[EN](../en/custom-template.md) | [JA (日本語ドキュメントは Getting Started のみ)](../ja/getting-started.md)

# Custom Templates, Styles, and Assets

spec-driven-presentation-maker works with any `.pptx` file as a template.
It automatically analyzes the template's layouts, colors, fonts, and placeholders — no manual configuration needed.

Beyond templates, three other resource types can be customized per-user:

- **Templates** (`.pptx`) — slide masters
- **Styles** (`.html`) — design guides used by the agent
- **Assets** (images such as `.svg`, `.png`) — icons, logos, illustrations
- **Config** (`config.json`) — output directory, extra asset sources, etc.

All four support user-local placement so your customizations survive
`pip install --upgrade` or a repository re-clone.

---

## How Template Analysis Works

When you call `analyze_template`, the engine inspects the .pptx file and extracts:

- **Slide layouts** — Name, dimensions, placeholder positions and sizes
- **Theme colors** — Background, accent colors, text colors
- **Fonts** — Heading and body fonts
- **Placeholders** — Title, body, footer with exact coordinates

The agent uses this information to place elements precisely within the template's design system.

---

## Creating a Template

Design your template in PowerPoint, Google Slides, or Keynote (export as .pptx):

1. **Define slide layouts** — At minimum, create:
   - A title slide layout
   - A content slide layout (title placeholder + body area)
   - A section divider layout (optional)
   - A blank layout (for custom designs)

2. **Set theme colors** — Define your brand colors in the slide master's color theme. The agent reads these and uses them consistently.

3. **Set fonts** — Define heading and body fonts in the slide master. The agent extracts these automatically.

4. **Keep it clean** — Remove sample content from layouts. The agent works with placeholder positions, not sample text.

5. **Add layout instructions via speaker notes** — Write usage instructions in the speaker notes of each layout's sample slide. The agent reads these when analyzing the template and follows them when building slides with that layout.

   Examples:
   - "Use this layout for two-column comparisons"
   - "Place images on the right side only"
   - "Title should be kept to one line"

### Tips

- Use descriptive layout names (e.g., "Content with Image", "Two Column") — the agent reads these names
- Ensure background-to-text color contrast ratio of at least 4.5:1
- Test your template by running `analyze_template` and reviewing the output

### Slide size (aspect ratio)

Any slide size works — 16:9, 4:3, 16:10, and other ratios are all supported.
The engine derives the drawing canvas from your template's actual dimensions.

The coordinate system is **1920 px wide, with height following the aspect ratio**:

| Template slide size | Canvas in slide JSON |
|---|---|
| 16:9 (13.33 × 7.5 in) | 1920 × 1080 px |
| 4:3 (10 × 7.5 in) | 1920 × 1440 px |
| 16:10 | 1920 × 1200 px |

`analyze_template` reports the canvas size as `slide_size`, and the agent records
it in `deck.json` as `slideSize` so that slide composition uses the full canvas.

Known limitations for non-16:9 templates:

- **Architecture diagram boxes** — fixed in #285. Box auto-height is now
  calibrated using `slideSize.ptPerPx` (the pt-to-px conversion rate reported
  by `analyze_template` and stored in `deck.json`). Explicit `box.height` is
  still accepted for manual fine-tuning.
- **Style demos** — the bundled style gallery HTML files use a fixed 16:9 canvas.
  This does not affect generated slides (only the design tokens are consumed).
- **Deck list thumbnails** — the Web UI deck list crops thumbnails to a fixed
  ratio so that card heights stay aligned in the grid. Slide previews
  (workspace, carousel) follow the real aspect ratio.

---

## Analyzing a Template

### Layer 1 (CLI)

```bash
# List all layouts
uv run python3 scripts/pptx_builder.py analyze_template my-template.pptx

# Show specific layout details
uv run python3 scripts/pptx_builder.py analyze_template my-template.pptx --layout "Content"
```

### Layer 2 (MCP)

The agent calls `analyze_template` automatically during the design phase. You can also ask directly:

> "Analyze the template and show me the available layouts"

### Layer 3 (Remote)

Templates are stored in S3 and registered in DynamoDB. The agent calls `list_templates` to see available templates, then `analyze_template` with the selected template ID.

---

## Registering a Template

### Layer 2 (Local MCP)

Place your .pptx file anywhere accessible and specify the path when initializing:

```json
{
  "tool": "init_deck_workspace",
  "arguments": {
    "name": "My Deck"
  }
}
```

Or simply tell the agent: "Use my-template.pptx for this presentation."

Place templates in `sdpm/templates/` to have them appear in `list_templates` automatically.

Included sample templates:

```
sdpm/templates/
├── sample_template_dark.pptx
└── sample_template_light.pptx
```

#### User-local templates

Custom templates can also be placed outside the package, so they survive a
`pip install --upgrade` or a re-clone of the repository. Kiro CLI / `pptx_builder.py`
searches the following locations in order and merges the results in
`list_templates`:

1. Directories listed in `$SDPM_TEMPLATES_DIR` (platform path separator: `:` on Unix, `;` on Windows — same semantics as `PATH`)
2. `<user-config>/templates/` — see **User-local directory layout** below
3. `sdpm/templates/` (package-bundled)

A user-local template shadows a bundled one with the same file name, which
makes it easy to override sample templates without editing the repository.

#### User-local directory layout

The user-local base directory is platform-aware:

| Platform | Location |
|----------|----------|
| macOS / Linux | `$XDG_CONFIG_HOME/sdpm/` (default: `~/.config/sdpm/`) |
| Windows | `%APPDATA%/sdpm/` (default: `C:\Users\<you>\AppData\Roaming\sdpm\`) |

Layout:

```
<user-config>/sdpm/
├── templates/          # User-local .pptx templates
├── styles/             # User-local style HTMLs (see "Custom Styles" below)
├── assets/             # User-local asset sources (see "Custom Assets" below)
│   └── my-company/
│       ├── manifest.json
│       └── logo.svg
└── config.json         # Per-user config overrides (output_dir, extra_sources, …)
```

None of these paths exist by default — create only what you need
(`mkdir -p ~/.config/sdpm/styles` etc.).

### Layer 3 (Remote MCP)

Upload the template to S3 and register it in DynamoDB:

```bash
uv run python scripts/upload_template.py \
  --file my-template.pptx \
  --name "Corporate 2026" \
  --bucket <ResourceBucketName> \
  --table <TableName>
```

| Parameter | Required | Description |
|-----------|:--------:|-------------|
| `--file` | ✅ | Path to the .pptx template file |
| `--name` | ✅ | Display name for the template |
| `--bucket` | ✅ | S3 bucket name (CDK output `ResourceBucketName`) |
| `--table` | ✅ | Amazon DynamoDB table name (CDK output `TableName`) |

The script handles S3 upload, template analysis, and Amazon DynamoDB metadata registration automatically.

In the cloud Web UI, each user can add a private note to builtin and user templates from the Templates page. The agent considers these notes—including intended use cases, preferences, and default-use requests—when proposing or selecting a template.

---

## Custom Styles

A style is one HTML file that serves as rulebook, reference and gallery sample at once: its
`:root` tokens (colours, `--fs-*` font sizes, geometry) are machine-read by `apply_style` and
the build-time lint, and its slides show — and explain in comments — the frame *this* style repeats, the
components it builds slides from, the layouts (named regions) it divides a slide into, and a
few finished slides. Composers read the whole file
as `specs/art-direction.html`, and the orchestrator reads its Message & Outline part before
writing the outline, so a style shapes the deck's structure, not only its look. The skeleton
and token contract are defined in the `style` workflow (returned by `start_style()`).

### Bundled styles

Bundled styles come in two tiers. The **orthodox** tier is for when you do not want to
think about looks: any subject, any audience, light or dark. The **concept** tier is
chosen by look — each style commits to one visual idea and states how far it may be
pushed. Purpose-specific structure (how a lesson or a workshop deck is organised) belongs
to the outline, not the style, so any concept style can carry any kind of deck.

**Orthodox — pick one of these when in doubt**

| Style | Built for | Look |
|---|---|---|
| `report` | Documents read alone; numbers, tables and findings first | White, serif findings, one deep-green accent, tables and small multiples, greyscale-safe |
| `briefing` | Decks spoken to a room, re-read afterwards | Dark, one teal accent, noun-phrase titles with a topic sentence, header bands and rules instead of cards |
| `aws-dark` / `aws-light` | Decks about AWS services, architectures and cost — talks/demos (dark) or documents/print (light) | Squid Ink or white ground, official service-category colours for identification, official icons, one Smile Orange emphasis |

**Concept — choose by look**

| Style | Idea | Look |
|---|---|---|
| `neo-brutalist` | Blunt hierarchy over polish; "zero apology" | Cream ground, 6px black borders, hard 12px offset shadows, flat primary fills, uppercase labels, square corners |
| `typographic` | Type is the image; one beat per slide | White, display type at 384px that bleeds off the left edge, focus stacks in black and light grey, one red word or number at most, no shapes or rules at all |
| `signal` | Warning-sign vocabulary; one thing is highlighted | Near-black, one safety-yellow panel per slide, upright ultra-bold headlines, huge numerals, monospaced metadata, one hazard stripe |
| `racing` | Momentum; every slide hands off to the next | Near-black, italic condensed headlines, blue-violet-red top stripe, thin white speed lines, one red element |
| `bento` | One fact per tile; modular product-story rhythm | Soft grey ground, white rounded tiles (20px) on a 24px grid, exactly one dark tile and at most one blue accent tile per slide, faint shadow |
| `newspaper` | Broadsheet; the deck is meant to be read | Aged paper, near-black serif headlines, 3px masthead rule and 1px hairlines, 2–3 justified columns, drop cap, one red figure or rule |
| `swiss-poster` | One red geometric shape anchors the page | White, black type at poster sizes that never bleeds, exactly one red circle / bar / band / square (may bleed), 1–2 grid lines, a vertical label |
| `duotone` | One hard edge, two fields: claim on one, evidence on the other | Near-black and vivid orange, 50/50 or 33/67 split (vertical or horizontal); near-black type on orange, white and orange type on near-black, grey only for meta; shape bar charts with one white bar |
| `prism-dark` | The gradient is a pointer: it marks the one thing the title is talking about, everything else is flat | Near-black ground, one violet-to-pink gradient used as gradient text on the key figure, a 4px outline + one filled pill on the chosen card, or one gradient bar; a 40px gradient bar down the left edge is the only constant. No gradient panels, no blur or glow |
| `prism-light` | Same rule set as `prism-dark` for lit rooms and print | White ground, near-black type, flat white cards with 1px borders, the same violet-to-pink gradient in the same pointer roles |
| `aws-console` | The deck is an AWS Management Console screen; every piece of chrome carries deck information | Two dark header bands (aws wordmark, search box showing the deck title and slide index, notification badge = open actions, date and presenter where region and account sit; a favourites row of numbered section chips with the current section lit) over a white toolbar; page title with an Info link and an outline + orange button pair; white 2px-bordered containers with drag handle, Info, kebab and resize handle; blue links and blue metrics; three fixed status colours; dense 56px rows, no prose |

### User-local styles

Use the `style` workflow (agent-driven) to generate a new style HTML.
The workflow writes to `<user-config>/styles/{name}.html` — i.e.
`~/.config/sdpm/styles/` on macOS/Linux or `%APPDATA%/sdpm/styles/` on Windows.

You can also copy an existing style manually:

```bash
mkdir -p ~/.config/sdpm/styles
cp sdpm/references/examples/styles/report.html \
   ~/.config/sdpm/styles/my-style.html
```

Search order (first match wins on same file name):

1. Directories listed in `$SDPM_STYLES_DIR` (platform path separator, like `PATH`)
2. `<user-config>/styles/`
3. `sdpm/references/examples/styles/` (package-bundled samples)

The styles gallery (opened by `list_styles` or the CLI `examples styles` command)
scans all three locations and displays them in a single list. User-local styles
shadow bundled ones of the same name so you can override samples without
touching the repository.

---

### Built-in Asset Sources

spec-driven-presentation-maker includes download scripts for two icon sets:

```bash
# AWS Architecture Icons
uv run python3 scripts/download_aws_icons.py

# Material Symbols (Google)
uv run python3 scripts/download_material_icons.py
```

Icons are stored in `sdpm/assets/` with a `manifest.json` per source:

```
sdpm/assets/
├── config.json          # Optional: user settings (gitignored, see config.example.json)
├── config.example.json  # Example config (git-managed)
├── aws/
│   ├── manifest.json    # {"icons": [{"name": "Lambda", "file": "Lambda.svg", "tags": [...]}]}
│   └── *.svg
└── material/
    ├── manifest.json
    └── *.svg
```

### Referencing Assets in Slides

```json
{
  "type": "image",
  "src": "assets:aws/Lambda",
  "x": 100, "y": 200, "width": 64, "height": 64
}
```

Reference formats:
- `assets:{source}/{name}` — From a specific source (e.g., `assets:aws/Lambda`)
- `icons:{name}` — Search all sources (backward compatible)

### Adding Custom Asset Sources

There are two ways to add a custom asset source (e.g. your company logos):

#### Option A — Drop-in under `<user-config>/assets/` (auto-discovered)

Place the source directory under the user-local assets path. It is automatically
scanned at runtime — no config changes required:

```
~/.config/sdpm/assets/my-company/     # (Windows: %APPDATA%/sdpm/assets/my-company/)
├── manifest.json
└── logo.svg
```

`manifest.json` follows the built-in format:

```json
{
  "source": "my-company",
  "icons": [
    {"name": "my-logo", "file": "logo.svg", "tags": ["brand", "logo"], "type": "service"}
  ]
}
```

Reference in `slides.json`:

```json
{ "type": "image", "src": "assets:my-company/logo", "x": 100, "y": 200, "width": 64, "height": 64 }
```

#### Option B — Explicit registration via `config.json`

Use this when the files live anywhere on disk (e.g. a shared network drive),
or when you want to point at an existing directory without moving it:

```json
{
  "extra_sources": [
    {
      "source": "mybrand",
      "manifest": "/path/to/my-icons/manifest.json",
      "files_dir": "/path/to/my-icons/"
    }
  ]
}
```

Save as `<user-config>/config.json` (see **User config** below).

### Priority order

When an asset name appears in multiple sources, the earlier source wins:

1. `extra_sources` from `config.json` — explicit override
2. `<user-config>/assets/` — auto-discovered user-local sources
3. `sdpm/assets/` — built-in sources (aws, material)
4. Legacy `icons/` directory (only if present)

This lets `extra_sources` override user-local sources, which in turn override
bundled ones. Registering a built-in name in `extra_sources` is an intentional
way to replace a bundled icon with your own.

---

## User config

Per-user configuration lives in `<user-config>/config.json` (that is,
`~/.config/sdpm/config.json` on macOS/Linux or `%APPDATA%/sdpm/config.json`
on Windows). The file is optional; missing keys fall back to defaults.

Full schema with defaults:

```json
{
  "output_dir": "~/Documents/SDPM-Presentations",
  "extra_sources": []
}
```

- `output_dir` — Base directory where generated PPTX files are written.
  Supports `~` expansion. Can also be overridden per-run via
  `$SDPM_OUTPUT_DIR`.
- `extra_sources` — Additional asset manifests (see **Option B** above).

The previously-shipped `sdpm/assets/config.json` is no longer read — it was
lost on `pip install --upgrade` and is replaced entirely by the user-local
path above.

---

### Uploading Assets to S3 (Layer 3)

```bash
uv run python scripts/upload_assets.py \
  --dir ./my-icons/ \
  --bucket <ResourceBucketName> \
  --category icons
```

---

## Related Documents

- [Getting Started](getting-started.md) — Setup and deployment instructions
- [Architecture](architecture.md) — How the asset resolver works
