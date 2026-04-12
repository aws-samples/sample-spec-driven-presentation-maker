# spec-driven-presentation-maker Local MCP Server (Layer 2)

Local stdio MCP server for desktop MCP clients. No AWS required.

## Quick Start

```bash
# Install
cd mcp-local && uv sync

# Run
uv run python server.py
```

## MCP Client Configuration

### Kiro CLI / Claude Desktop / VS Code
```json
{
  "mcpServers": {
    "spec-driven-presentation-maker": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/spec-driven-presentation-maker/mcp-local", "python", "server.py"]
    }
  }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `init_presentation` | Initialize workspace with template and fonts |
| `analyze_template` | Analyze a PPTX template (layouts, colors, fonts) |
| `generate_pptx` | Generate PPTX from JSON |
| `get_preview` | Generate PNG previews (requires LibreOffice + poppler) |
| `measure_slides` | Measure text bounding boxes (requires LibreOffice) |
| `search_assets` | Search icons by keyword |
| `list_asset_sources` | List available asset sources |
| `list_templates` | List available templates |
| `list_styles` | List design styles |
| `read_examples` | Read design pattern and component examples |
| `list_workflows` | List workflow documents |
| `read_workflows` | Read workflow instructions |
| `list_guides` | List guide documents |
| `read_guides` | Read guide documents |
| `code_to_slide` | Generate code block elements JSON |
| `pptx_to_json` | Convert PPTX to JSON |
| `grid` | CSS Grid coordinate calculation |

## Requirements

- Python 3.10+
- LibreOffice (for `get_preview` and `measure_slides` tools)
- poppler-utils (`pdftoppm`) for PNG conversion
