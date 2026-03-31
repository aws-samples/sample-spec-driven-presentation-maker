[EN](../en/custom-template.md) | [JA](../ja/custom-template.md)

# Custom Templates and Assets

spec-driven-presentation-maker works with any `.pptx` file as a template.
It automatically analyzes the template's layouts, colors, fonts, and placeholders — no manual configuration needed.

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

---

## Analyzing a Template

### Layer 1 (CLI)

```bash
# List all layouts
uv run python3 scripts/pptx_builder.py analyze-template my-template.pptx

# Show specific layout details
uv run python3 scripts/pptx_builder.py analyze-template my-template.pptx --layout "Content"
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
  "tool": "init_presentation",
  "arguments": {
    "name": "My Deck"
  }
}
```

Or simply tell the agent: "Use my-template.pptx for this presentation."

Place templates in `skill/templates/` to have them appear in `list_templates` automatically.

Included sample templates:

```
skill/templates/
├── sample_template_dark.pptx
└── sample_template_light.pptx
```

### Layer 3 (Remote MCP)

Upload the template to S3 and register it in DynamoDB:

```bash
python scripts/upload_template.py \
  --file my-template.pptx \
  --name "Corporate 2026" \
  --bucket <ResourceBucketName> \
  --table <TableName> \
  --default
```

| Parameter | Required | Description |
|-----------|:--------:|-------------|
| `--file` | ✅ | Path to the .pptx template file |
| `--name` | ✅ | Display name for the template |
| `--bucket` | ✅ | S3 bucket name (CDK output `ResourceBucketName`) |
| `--table` | ✅ | Amazon DynamoDB table name (CDK output `TableName`) |
| `--default` | | Set as the default template |

The script handles S3 upload, template analysis, and Amazon DynamoDB metadata registration automatically.

---

## Asset Customization

### Built-in Asset Sources

spec-driven-presentation-maker includes download scripts for two icon sets:

```bash
# AWS Architecture Icons
uv run python3 scripts/download_aws_icons.py

# Material Symbols (Google)
uv run python3 scripts/download_material_icons.py
```

Icons are stored in `skill/assets/` with a `manifest.json` per source:

```
skill/assets/
├── config.json          # Optional: extra source configuration
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

Create a directory with your icons and a `manifest.json`:

```json
{
  "icons": [
    {"name": "my-logo", "file": "logo.svg", "tags": ["brand", "logo"]},
    {"name": "product-icon", "file": "product.svg", "tags": ["product"]}
  ]
}
```

Register in `skill/assets/config.json`:

```json
{
  "extra_sources": [
    {
      "name": "mybrand",
      "manifest": "/path/to/my-icons/manifest.json",
      "files_dir": "/path/to/my-icons/"
    }
  ]
}
```

Now reference as `assets:mybrand/my-logo`.

### Uploading Assets to S3 (Layer 3)

```bash
python scripts/upload_assets.py \
  --dir ./my-icons/ \
  --bucket <ResourceBucketName> \
  --category icons
```

---

## Related Documents

- [Getting Started](getting-started.md) — Setup and deployment instructions
- [Architecture](architecture.md) — How the asset resolver works
