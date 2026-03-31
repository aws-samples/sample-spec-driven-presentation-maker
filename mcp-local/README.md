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
| `start_presentation` | Start creating a presentation — returns design rules + workflow |
| `init_presentation` | Initialize workspace with template and fonts |
| `analyze_template` | Analyze a PPTX template (layouts, colors, fonts) |
| `generate_pptx` | Generate PPTX from JSON |
| `preview` | Generate PNG previews (requires PowerPoint) |
| `search_assets` | Search icons by keyword |
| `list_asset_sources` | List available asset sources |
| `list_examples` | List design pattern and component examples |
| `read_examples` | Read example documents |
| `list_workflows` | List workflow documents |
| `read_workflows` | Read workflow instructions |
| `list_guides` | List guide documents |
| `read_guides` | Read guide documents |
| `code_block` | Generate code block elements JSON |
| `pptx_to_json` | Convert PPTX to JSON |

## Requirements

- Python 3.10+
- Microsoft PowerPoint (for `preview` tool, macOS/Windows only)
- poppler (`pdftoppm`) for PNG conversion on macOS
