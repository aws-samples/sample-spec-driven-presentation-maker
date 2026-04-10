<!-- PUBLIC: This file is git-tracked and visible in the public repository. -->

# Principles

## Architecture: 3-Layer Structure

```
Layer 1: CLI (skill/scripts/pptx_builder.py)
  ↓ uses
Skill Engine (skill/sdpm/)          ← Single source of business logic
  ↑ uses                ↑ uses
Layer 2: MCP Local      Layer 3: MCP Remote
(mcp-local/)            (mcp-server/)
```

## Engine (`skill/sdpm/`)

The PPTX generation engine. The single source of truth for all business logic.

- `sdpm.builder` — PPTX construction (slide generation, template processing)
- `sdpm.preview` — Preview (PDF/PNG conversion, autofit, layout validation)
- `sdpm.reference` — Reference document access
- `sdpm.api` — High-level API (generate, preview, init, code_block)
- `sdpm.analyzer`, `sdpm.converter`, `sdpm.layout`, `sdpm.utils` — Utilities

## Skill (`skill/`)

Package containing Engine + CLI + reference documents + templates.
Installed as `sdpm-skill` and consumed by Layer 2 and Layer 3.

## MCP Local (`mcp-local/`) — Layer 2

MCP server for local environments. Must be a **thin wrapper**.

- Input: Convert MCP JSON params to Engine API arguments
- Processing: Call Engine API (`sdpm.api.*`, `sdpm.reference.*`)
- Output: Convert results to JSON strings
- No independent logic (do not implement logic that doesn't exist in Engine API)

## MCP Remote (`mcp-server/`) — Layer 3

MCP server running on AWS with S3/DynamoDB dependencies.

- Infrastructure-dependent operations (S3 Storage file access, etc.) may have independent implementations
- However, use Engine logic when equivalent functionality exists

## Logic Sharing Principles

### Engine is the source of truth
The Engine API is the canonical implementation. CLI, MCP Local, and MCP Remote are consumers.

### What to share

Share:
- Data retrieval and transformation logic (file scanning, frontmatter stripping, pptx notes extraction)
- Business rules (template resolution, icon validation, autofit, imbalance check)
- Computation logic (grid calculation, code highlighting, layout)

Do not share:
- I/O format differences (CLI: print/stdin, MCP Local: JSON, MCP Remote: S3/DynamoDB)
- Environment-specific processing (MCP Remote S3 Storage, CLI argparse)
- UI layer concerns (error message formatting, browser launch behavior)

### Decision flow when uncertain
1. Does the logic exist in the Engine? → Use it
2. Is it infrastructure-dependent? → S3/DynamoDB dependencies allow MCP Remote independent implementation
3. Is the difference only in presentation/output? → Engine API returns data, each layer controls output
