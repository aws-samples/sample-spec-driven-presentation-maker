<!-- PUBLIC: This file is git-tracked and visible in the public repository. -->

# Principles

## Architecture: 4-Layer Structure

```
Layer 4: Agent + Web UI (agent/, web-ui/)
  ↓ uses
Layer 3: MCP Remote (mcp-server/)   ← AWS (S3/DynamoDB)
  ↓ uses
Skill Engine (skill/sdpm/)          ← Single source of business logic
  ↑ uses
Layer 2: MCP Local (mcp-local/)
  ↑ uses
Layer 1: CLI (skill/scripts/pptx_builder.py)
```

Layer 4 hosts the Strands Agent (SPEC agent + composer agents) and the React Web UI.
The SPEC agent handles user dialogue (Phase 1). Composer agents handle slide generation
(Phase 2+3) via the `compose_slides` tool (Agents as Tools pattern).

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

## PR前ローカルチェック

PR作成前に以下をローカルで実行し、CI待ちを減らす:

```bash
ash scan --mode local --fail-on-findings
```

## Web UI: Dual-Mode (Cloud / Local)

Single Next.js codebase serves two modes via build-time feature toggle `NEXT_PUBLIC_MODE`.
Cloud mode is the primary target; Local mode exists for users who want to try the app without deploying to AWS.

```
Cloud (default)  — AWS direct (AgentCore, S3, Cognito), static export via CloudFront
Local            — Next.js API Routes → kiro-cli ACP, filesystem storage
```

### Branching rules

| Layer | How to branch |
|-------|--------------|
| UI components | `<CloudOnly>` / `<LocalOnly>` (declarative) |
| Service layer | `IS_LOCAL` early return at function entry point |
| API Routes (`src/app/api/`) | Local-only. Excluded from cloud build by `build:cloud` |
| Local-only logic | Isolated in `src/lib/local/` |

### Web-first principle
- Web (Cloud) code must remain the cleanest path — no Local logic mixed in
- Local is a subset: no auth, no public/shared decks, no Bedrock search
- `build:cloud` output must be identical whether Local code exists or not

### Build strategy
- `output: "export"` and `trailingSlash: true` are cloud-only (`next.config.ts`)
- `build:cloud` temporarily moves `src/app/api/` out to enable static export (with `trap EXIT` for safe restore)
- This is a known workaround — Next.js does not support `output: "export"` + API Routes coexistence

### Session persistence (Local)
- `.session` file in deck directory — ACP sessionId
- `.chat.json` file in deck directory — chat messages for UI display
- `session/load` restores agent context; replay is not used for UI (Obsidian agent-client pattern)
