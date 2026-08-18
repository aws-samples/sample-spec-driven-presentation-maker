# spec-driven-presentation-maker Local MCP Server (Layer 2)

Local stdio MCP server for desktop MCP clients. No AWS required.

## Quick Start

```bash
# Install
cd servers/local && uv sync

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
      "args": ["run", "--directory", "/path/to/spec-driven-presentation-maker/servers/local", "python", "server.py"]
    }
  }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `init_presentation` | Initialize a new deck workspace |
| `analyze_template` | Analyze a PPTX template (layouts, colors, fonts) |
| `generate_pptx` | Generate PPTX from JSON |
| `read_attachment` | Read content from an attached file with byte-offset paging |
| `import_attachment` | Import attached files into the deck workspace |
| `search_assets` | Search icons by keyword (empty query = discovery mode) |
| `list_templates` | List available templates |
| `list_styles` | List design styles |
| `read_examples` | Read design pattern and component examples |
| `list_workflows` | List workflow documents |
| `read_workflows` | Read workflow instructions |
| `list_guides` | List guide documents |
| `read_guides` | Read guide documents |
| `code_to_slide` | Generate code block elements JSON |
| `grid` | CSS Grid coordinate calculation |

## Requirements

- Python 3.10+
- LibreOffice (for `run_python` preview generation and text measurement)
- poppler-utils (`pdftoppm`) for PNG conversion
