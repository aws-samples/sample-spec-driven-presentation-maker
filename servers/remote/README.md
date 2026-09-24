# spec-driven-presentation-maker MCP Server (Layer 3)

Remote MCP server for Amazon Bedrock AgentCore Runtime. Provides all spec-driven-presentation-maker tools over Streamable HTTP with Amazon DynamoDB + S3 storage and multi-user authorization.

## Tools

### Workflow
| Tool | Description |
|------|-------------|
| `read_workflows` | Load role instructions (`orchestrator`, `composer`, `style`, or `translate`) |
| `init_presentation` | Create deck + associate template |
| `analyze_template` | Get pre-analyzed template info (layouts, colors, fonts) |

### Deck CRUD
| Tool | Description |
|------|-------------|
| `write_slide` | Write a single slide (JSON) |
| `remove_slide` | Remove a slide from a deck |
| `reorder_slides` | Reorder slides in a deck |
| `get_deck` | Get deck metadata and all slides |

### Generation
| Tool | Description |
|------|-------------|
| `generate_pptx` | Generate final PPTX file |
| `get_preview` | Get PNG preview URLs |

### Assets
| Tool | Description |
|------|-------------|
| `search_assets` | Search icons and assets by keyword (empty query = discovery) |

### References
| Tool | Description |
|------|-------------|
| `read_examples` | Bundled style examples (`styles/<name>`) |
| `list_workflows` / `read_workflows` | Role workflows and slide JSON specification |
| `list_guides` / `read_guides` | Design rules and review checklists |

### Utility
| Tool | Description |
|------|-------------|
| `list_templates` | List available templates |
| `code_to_slide` | Generate syntax-highlighted code block JSON |
| `read_attachment` | Read content from an attached file with byte-offset paging |
| `import_attachment` | Import file into deck workspace |
| `search_slides` | Semantic slide search (optional, requires Amazon Bedrock KB) |

## Deployment

Deployed as a Docker container on Amazon Bedrock AgentCore Runtime via CDK (`infra/`).

```bash
cd infra && cdk deploy SdpmData SdpmRuntime
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DECKS_TABLE` | Amazon DynamoDB table name |
| `PPTX_BUCKET` | S3 bucket for PPTX output |
| `RESOURCE_BUCKET` | S3 bucket for templates, assets, references |
| `KB_ID` | Amazon Bedrock Knowledge Base ID (optional) |
| `AWS_DEFAULT_REGION` | AWS region (default: us-east-1) |
